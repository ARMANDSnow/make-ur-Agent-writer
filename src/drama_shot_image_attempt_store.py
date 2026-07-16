"""Strict local C3 storage and crash-safe execution for shot-image attempts."""

from __future__ import annotations

import json
import hashlib
import os
import secrets
import stat
from pathlib import Path
from typing import Any, Mapping, Protocol, Sequence

from . import paths
from .drama_schemas import (
    EpisodeShotImageAttemptLedger,
    EpisodeShotImageCandidateManifest,
    ShotImageAttemptInspection,
    ShotImageAttemptRecord,
    ShotImageAttemptSpec,
    ShotImageCandidate,
    ShotImageProviderCapability,
    normalize_episode_no,
)
from .drama_shot_image_attempts import (
    DramaShotImageAttemptError,
    build_empty_shot_image_attempt_ledger,
    build_shot_image_attempt_receipt,
    build_shot_image_attempt_spec,
    complete_shot_image_attempt,
    discard_not_sent_shot_image_attempt,
    fail_shot_image_attempt,
    record_shot_image_artifact_received,
    start_shot_image_attempt,
)
from .drama_shot_image_candidate_store import (
    MAX_SHOT_IMAGE_CANDIDATE_BYTES,
    _candidate_payload_identity,
    _open_parent_dir,
    _target_token_at,
    append_local_shot_image_candidate,
    load_fresh_episode_shot_image_candidates,
)
from .drama_shot_image_candidates import build_shot_image_candidate
from .drama_shot_image_store import load_fresh_episode_shot_image_plan
from .drama_store import (
    _read_strict_workspace_bytes,
    _read_strict_workspace_json,
    _validate_render_workspace_root,
)
from .schemas import model_to_dict
from .secure_http import RequestNotSentError
from .web.workspace_ctx import use_workspace
from .workspace_lock import WorkspaceLocked, acquire_write_lock


MAX_SHOT_IMAGE_ATTEMPT_LEDGER_BYTES = 8_000_000


class ShotImageProviderTimeout(TimeoutError):
    pass


class ShotImageProviderNetworkError(ConnectionError):
    pass


class ShotImageProviderResponseError(ValueError):
    pass


class ShotImageProviderAdapter(Protocol):
    """Minimal injected seam; it is not a dynamic provider registry."""

    def generate(
        self,
        spec: ShotImageAttemptSpec,
        *,
        prompt: str,
        reference_bytes: Sequence[bytes],
    ) -> bytes: ...


class DramaShotImageAttemptStoreError(ValueError):
    pass


class ShotImageAttemptReconciliationRequired(DramaShotImageAttemptStoreError):
    pass


class _AttemptLedgerReadError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _ledger_target_token(root: Path, path: Path) -> tuple[Any, ...]:
    try:
        payload = _read_strict_workspace_bytes(
            root,
            path,
            maximum=MAX_SHOT_IMAGE_ATTEMPT_LEDGER_BYTES,
        )
    except FileNotFoundError:
        return ("missing",)
    except ValueError:
        return ("invalid",)
    return ("file", len(payload), hashlib.sha256(payload).hexdigest())


def _ledger_target_token_at(directory_fd: int, name: str) -> tuple[Any, ...]:
    file_fd: int | None = None
    try:
        file_fd = os.open(
            name,
            os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0),
            dir_fd=directory_fd,
        )
    except FileNotFoundError:
        return ("missing",)
    except OSError:
        return ("invalid",)
    try:
        info = os.fstat(file_fd)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_size <= 0
            or info.st_size > MAX_SHOT_IMAGE_ATTEMPT_LEDGER_BYTES
        ):
            return ("invalid",)
        chunks: list[bytes] = []
        remaining = MAX_SHOT_IMAGE_ATTEMPT_LEDGER_BYTES + 1
        while remaining > 0:
            chunk = os.read(file_fd, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) != info.st_size or len(payload) > MAX_SHOT_IMAGE_ATTEMPT_LEDGER_BYTES:
            return ("invalid",)
        return ("file", len(payload), hashlib.sha256(payload).hexdigest())
    except OSError:
        return ("invalid",)
    finally:
        try:
            os.close(file_fd)
        except OSError:
            pass


def shot_image_attempt_ledger_path(
    workspace: str,
    *,
    episode_no: int = 1,
) -> Path:
    number = normalize_episode_no(episode_no)
    root = paths.workspace_root(workspace)
    path = root / "logs" / "drama_shot_images" / f"episode_{number:02d}.attempts.json"
    if path.parent.parent.parent != root:
        raise ValueError("shot image attempt ledger path does not match the workspace")
    return path


def _read_ledger(
    workspace: str,
    *,
    episode_no: int,
) -> EpisodeShotImageAttemptLedger:
    root = paths.workspace_root(workspace)
    path = shot_image_attempt_ledger_path(workspace, episode_no=episode_no)
    try:
        raw = _read_strict_workspace_json(
            root,
            path,
            maximum=MAX_SHOT_IMAGE_ATTEMPT_LEDGER_BYTES,
        )
    except FileNotFoundError:
        raise
    except (OSError, RecursionError, TypeError, ValueError) as exc:
        raise _AttemptLedgerReadError("schema_invalid") from exc
    if not isinstance(raw, dict) or set(raw) != {
        "schema_version",
        "artifact_type",
        "ledger_fingerprint",
        "ledger",
    }:
        raise _AttemptLedgerReadError("schema_invalid")
    if type(raw["schema_version"]) is not int or raw["schema_version"] != 1:
        raise _AttemptLedgerReadError("schema_unsupported")
    if raw["artifact_type"] != "drama_episode_shot_image_attempts":
        raise _AttemptLedgerReadError("schema_invalid")
    if not isinstance(raw["ledger"], dict):
        raise _AttemptLedgerReadError("schema_invalid")
    try:
        ledger = EpisodeShotImageAttemptLedger(**raw["ledger"])
    except (TypeError, ValueError) as exc:
        raise _AttemptLedgerReadError("schema_invalid") from exc
    if raw["ledger_fingerprint"] != ledger.ledger_fingerprint:
        raise _AttemptLedgerReadError("ledger_hash_mismatch")
    if ledger.episode_no != episode_no:
        raise _AttemptLedgerReadError("schema_invalid")
    return ledger


def _write_ledger(
    workspace: str,
    ledger: EpisodeShotImageAttemptLedger,
    *,
    expected_target_token: tuple[Any, ...],
) -> None:
    envelope = {
        "schema_version": 1,
        "artifact_type": "drama_episode_shot_image_attempts",
        "ledger_fingerprint": ledger.ledger_fingerprint,
        "ledger": model_to_dict(ledger),
    }
    payload = (
        json.dumps(envelope, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")
    if not payload or len(payload) > MAX_SHOT_IMAGE_ATTEMPT_LEDGER_BYTES:
        raise DramaShotImageAttemptStoreError("shot image attempt ledger exceeds its size limit")
    root = paths.workspace_root(workspace)
    path = shot_image_attempt_ledger_path(workspace, episode_no=ledger.episode_no)
    _validate_render_workspace_root(root)
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise DramaShotImageAttemptStoreError("shot image attempt ledger escapes the workspace") from exc
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise DramaShotImageAttemptStoreError("strict no-follow writes are unavailable")
    directory_fd: int | None = None
    temp_fd: int | None = None
    temp_created = False
    temp_identity: tuple[int, int] | None = None
    temp_name = f".{relative.name}.tmp.{secrets.token_hex(16)}"
    try:
        directory_fd = _open_parent_dir(root, relative, create=True)
        if _ledger_target_token_at(directory_fd, relative.name) != expected_target_token:
            raise DramaShotImageAttemptStoreError(
                "shot image attempt ledger changed concurrently"
            )
        temp_fd = os.open(
            temp_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow,
            0o600,
            dir_fd=directory_fd,
        )
        temp_created = True
        initial = os.fstat(temp_fd)
        temp_identity = (initial.st_dev, initial.st_ino)
        view = memoryview(payload)
        while view:
            written = os.write(temp_fd, view)
            if written <= 0:
                raise OSError("short shot image attempt ledger write")
            view = view[written:]
        os.fsync(temp_fd)
        if _ledger_target_token_at(directory_fd, relative.name) != expected_target_token:
            raise DramaShotImageAttemptStoreError(
                "shot image attempt ledger changed concurrently"
            )
        opened = os.fstat(temp_fd)
        named = os.stat(temp_name, dir_fd=directory_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(named.st_mode)
            or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
        ):
            raise DramaShotImageAttemptStoreError(
                "shot image attempt temporary ledger changed"
            )
        os.replace(
            temp_name,
            relative.name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        os.fsync(directory_fd)
    except DramaShotImageAttemptStoreError:
        raise
    except OSError as exc:
        raise DramaShotImageAttemptStoreError(
            "shot image attempt ledger could not be written safely"
        ) from exc
    finally:
        if temp_fd is not None:
            try:
                os.close(temp_fd)
            except OSError:
                pass
        if directory_fd is not None and temp_created and temp_identity is not None:
            try:
                cleanup = os.stat(temp_name, dir_fd=directory_fd, follow_symlinks=False)
            except OSError:
                pass
            else:
                if (
                    stat.S_ISREG(cleanup.st_mode)
                    and (cleanup.st_dev, cleanup.st_ino) == temp_identity
                ):
                    try:
                        os.unlink(temp_name, dir_fd=directory_fd)
                    except OSError:
                        pass
        if directory_fd is not None:
            try:
                os.close(directory_fd)
            except OSError:
                pass


def _persist_ledger(
    workspace: str,
    ledger: EpisodeShotImageAttemptLedger,
    *,
    target_token: tuple[Any, ...],
) -> EpisodeShotImageAttemptLedger:
    _write_ledger(workspace, ledger, expected_target_token=target_token)
    persisted = _read_ledger(workspace, episode_no=ledger.episode_no)
    if persisted.ledger_fingerprint != ledger.ledger_fingerprint:
        raise DramaShotImageAttemptStoreError("shot image attempt ledger persistence failed")
    return persisted


def load_episode_shot_image_attempts(
    workspace: str,
    *,
    episode_no: int = 1,
) -> EpisodeShotImageAttemptLedger:
    try:
        return _read_ledger(workspace, episode_no=normalize_episode_no(episode_no))
    except _AttemptLedgerReadError:
        raise DramaShotImageAttemptStoreError("shot image attempt ledger is invalid") from None
    except (OSError, RecursionError, TypeError, ValueError):
        raise DramaShotImageAttemptStoreError("shot image attempt ledger could not be loaded") from None


def _current_sources(
    workspace: str,
    *,
    episode_no: int,
):
    plan = load_fresh_episode_shot_image_plan(workspace, episode_no=episode_no)
    manifest = load_fresh_episode_shot_image_candidates(workspace, episode_no=episode_no)
    if manifest.source_plan_fingerprint != plan.plan_fingerprint:
        raise DramaShotImageAttemptStoreError("shot image candidate source is stale")
    return plan, manifest


def _current_spec(
    workspace: str,
    *,
    episode_no: int,
    shot_id: str,
    capability: ShotImageProviderCapability | Mapping[str, Any],
    provider_fingerprint: str,
) -> tuple[Any, EpisodeShotImageCandidateManifest, ShotImageAttemptSpec, str]:
    plan, manifest = _current_sources(workspace, episode_no=episode_no)
    spec = build_shot_image_attempt_spec(
        plan,
        manifest,
        shot_id=shot_id,
        capability=capability,
        provider_fingerprint=provider_fingerprint,
    )
    request = next(item for item in plan.shot_specs if item.shot_id == shot_id)
    return plan, manifest, spec, request.image_prompt


def _reference_bytes(workspace: str, spec: ShotImageAttemptSpec) -> tuple[bytes, ...]:
    root = paths.workspace_root(workspace)
    result: list[bytes] = []
    for reference in spec.references:
        data = _read_strict_workspace_bytes(
            root,
            root / reference.artifact_path,
            maximum=MAX_SHOT_IMAGE_CANDIDATE_BYTES,
        )
        identity = hashlib.sha256(data).hexdigest()
        if identity != reference.artifact_sha256 or len(data) != reference.artifact_size_bytes:
            raise DramaShotImageAttemptStoreError("shot image attempt reference changed")
        result.append(data)
    return tuple(result)


def _read_staging(
    workspace: str,
    record: ShotImageAttemptRecord,
) -> tuple[bytes, tuple[str, int, int, int]]:
    root = paths.workspace_root(workspace)
    data = _read_strict_workspace_bytes(
        root,
        root / record.staging_path,
        maximum=MAX_SHOT_IMAGE_CANDIDATE_BYTES,
    )
    return data, _candidate_payload_identity(data)


def _write_staging_create_only(
    workspace: str,
    record: ShotImageAttemptRecord,
    data: bytes,
) -> None:
    identity = _candidate_payload_identity(data)
    root = paths.workspace_root(workspace)
    _validate_render_workspace_root(root)
    path = root / record.staging_path
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise DramaShotImageAttemptStoreError("shot image staging path escapes the workspace") from exc
    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        raise DramaShotImageAttemptStoreError("strict no-follow writes are unavailable")
    directory_fd: int | None = None
    file_fd: int | None = None
    file_identity: tuple[int, int] | None = None
    try:
        directory_fd = _open_parent_dir(root, relative, create=True)
        if _target_token_at(directory_fd, relative.name) != ("missing",):
            raise DramaShotImageAttemptStoreError("shot image staging path is occupied")
        file_fd = os.open(
            relative.name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow,
            0o600,
            dir_fd=directory_fd,
        )
        initial = os.fstat(file_fd)
        file_identity = (initial.st_dev, initial.st_ino)
        view = memoryview(data)
        while view:
            written = os.write(file_fd, view)
            if written <= 0:
                raise OSError("short shot image staging write")
            view = view[written:]
        os.fsync(file_fd)
        os.fsync(directory_fd)
        named = os.stat(relative.name, dir_fd=directory_fd, follow_symlinks=False)
        if not stat.S_ISREG(named.st_mode) or (
            named.st_dev,
            named.st_ino,
        ) != file_identity:
            raise DramaShotImageAttemptStoreError("shot image staging file changed")
    except DramaShotImageAttemptStoreError:
        raise
    except OSError as exc:
        raise DramaShotImageAttemptStoreError("shot image staging could not be written safely") from exc
    finally:
        if file_fd is not None:
            try:
                os.close(file_fd)
            except OSError:
                pass
        if directory_fd is not None:
            try:
                os.close(directory_fd)
            except OSError:
                pass
    persisted, persisted_identity = _read_staging(workspace, record)
    if persisted != data or persisted_identity != identity:
        raise DramaShotImageAttemptStoreError("shot image staging persistence failed")


def inspect_episode_shot_image_attempts(
    workspace: str,
    *,
    episode_no: int = 1,
) -> ShotImageAttemptInspection:
    try:
        number = normalize_episode_no(episode_no)
        try:
            ledger = _read_ledger(workspace, episode_no=number)
        except FileNotFoundError:
            return ShotImageAttemptInspection(
                state="needs_attempts",
                reasons=["missing"],
                ledger_fingerprint=None,
                outstanding_attempt_ids=[],
            )
        plan, manifest = _current_sources(workspace, episode_no=number)
        latest_by_shot: dict[str, ShotImageAttemptRecord] = {}
        for attempt in ledger.attempts:
            latest_by_shot[attempt.spec.shot_id] = attempt
        current_requests = {
            request.shot_id: request.request_fingerprint for request in plan.shot_specs
        }
        current_succeeded_shots = {
            item.spec.shot_id
            for item in ledger.attempts
            if item.status == "succeeded"
            and item.spec.source_plan_fingerprint == plan.plan_fingerprint
            and current_requests.get(item.spec.shot_id) == item.spec.request_fingerprint
        }
        stale = [
            item.attempt_id
            for item in latest_by_shot.values()
            if item.status == "succeeded"
            and item.spec.shot_id not in current_succeeded_shots
        ]
        if manifest.source_plan_fingerprint != plan.plan_fingerprint:
            return ShotImageAttemptInspection(
                state="stale",
                reasons=["source_changed"],
                ledger_fingerprint=ledger.ledger_fingerprint,
                outstanding_attempt_ids=[],
            )
        outstanding = [
            item.attempt_id
            for item in latest_by_shot.values()
            if item.status != "succeeded"
        ]
        if outstanding:
            return ShotImageAttemptInspection(
                state="reconciliation_required",
                reasons=["unfinished_attempts"],
                ledger_fingerprint=ledger.ledger_fingerprint,
                outstanding_attempt_ids=outstanding[:100],
            )
        if stale:
            return ShotImageAttemptInspection(
                state="stale",
                reasons=["source_changed"],
                ledger_fingerprint=ledger.ledger_fingerprint,
                outstanding_attempt_ids=[],
            )
        return ShotImageAttemptInspection(
            state="fresh",
            reasons=[],
            ledger_fingerprint=ledger.ledger_fingerprint,
            outstanding_attempt_ids=[],
        )
    except _AttemptLedgerReadError:
        return ShotImageAttemptInspection(
            state="invalid",
            reasons=["schema_invalid"],
            ledger_fingerprint=None,
            outstanding_attempt_ids=[],
        )
    except (OSError, RecursionError, TypeError, ValueError):
        return ShotImageAttemptInspection(
            state="invalid",
            reasons=["inspection_failed"],
            ledger_fingerprint=None,
            outstanding_attempt_ids=[],
        )


def _candidate_for_receipt(
    plan: Any,
    record: ShotImageAttemptRecord,
) -> ShotImageCandidate:
    receipt = record.artifact_receipt
    if receipt is None:
        raise DramaShotImageAttemptStoreError("shot image attempt receipt is missing")
    return build_shot_image_candidate(
        plan,
        shot_id=record.spec.shot_id,
        artifact_sha256=receipt.sha256,
        artifact_size_bytes=receipt.size_bytes,
        width=receipt.width,
        height=receipt.height,
    )


def _latest_compatible_attempt(
    ledger: EpisodeShotImageAttemptLedger,
    current_spec: ShotImageAttemptSpec,
) -> ShotImageAttemptRecord | None:
    matches = [
        item
        for item in ledger.attempts
        if item.spec.shot_id == current_spec.shot_id
        and item.spec.source_plan_fingerprint == current_spec.source_plan_fingerprint
        and item.spec.request_fingerprint == current_spec.request_fingerprint
        and item.spec.provider_fingerprint == current_spec.provider_fingerprint
        and item.spec.capability.capability_fingerprint
        == current_spec.capability.capability_fingerprint
    ]
    return matches[-1] if matches else None


def _latest_attempt_for_shot(
    ledger: EpisodeShotImageAttemptLedger,
    shot_id: str,
) -> ShotImageAttemptRecord | None:
    matches = [item for item in ledger.attempts if item.spec.shot_id == shot_id]
    return matches[-1] if matches else None


def _find_exact_candidate(
    manifest: EpisodeShotImageCandidateManifest,
    expected: ShotImageCandidate,
) -> ShotImageCandidate | None:
    matches = [
        candidate
        for pool in manifest.shots
        for candidate in pool.candidates
        if candidate.candidate_id == expected.candidate_id
    ]
    if not matches:
        return None
    if matches != [expected]:
        raise DramaShotImageAttemptStoreError("shot image candidate identity collision")
    return matches[0]


def _complete_received_attempt(
    workspace: str,
    record: ShotImageAttemptRecord,
) -> ShotImageAttemptRecord:
    if record.status != "artifact_received" or record.artifact_receipt is None:
        raise DramaShotImageAttemptStoreError("shot image attempt is not ready to commit")
    receipt = record.artifact_receipt
    plan, manifest = _current_sources(workspace, episode_no=record.spec.episode_no)
    if plan.plan_fingerprint != record.spec.source_plan_fingerprint:
        raise DramaShotImageAttemptStoreError("shot image attempt source changed")
    expected = _candidate_for_receipt(plan, record)
    candidate = _find_exact_candidate(manifest, expected)
    if candidate is None:
        data, identity = _read_staging(workspace, record)
        if identity != (receipt.sha256, receipt.size_bytes, receipt.width, receipt.height):
            raise DramaShotImageAttemptStoreError(
                "shot image staging no longer matches its receipt"
            )
        if manifest.manifest_fingerprint != record.spec.pre_manifest_fingerprint:
            raise ShotImageAttemptReconciliationRequired(
                "candidate manifest changed after the paid artifact receipt"
            )
        manifest, candidate = append_local_shot_image_candidate(
            workspace,
            episode_no=record.spec.episode_no,
            shot_id=record.spec.shot_id,
            png_bytes=data,
            expected_manifest_fingerprint=record.spec.pre_manifest_fingerprint,
        )
    root = paths.workspace_root(workspace)
    ledger_path = shot_image_attempt_ledger_path(
        workspace,
        episode_no=record.spec.episode_no,
    )
    with use_workspace(workspace), acquire_write_lock(source="drama-shot-image-attempts"):
        token = _ledger_target_token(root, ledger_path)
        ledger = _read_ledger(workspace, episode_no=record.spec.episode_no)
        current = next(
            (item for item in ledger.attempts if item.attempt_id == record.attempt_id),
            None,
        )
        if current is None:
            raise DramaShotImageAttemptStoreError("shot image attempt record disappeared")
        if current.status == "succeeded":
            return current
        if current.record_fingerprint != record.record_fingerprint:
            raise DramaShotImageAttemptStoreError("shot image attempt changed concurrently")
        locked_plan, locked_manifest = _current_sources(
            workspace,
            episode_no=record.spec.episode_no,
        )
        if locked_plan.plan_fingerprint != current.spec.source_plan_fingerprint:
            raise ShotImageAttemptReconciliationRequired(
                "shot image attempt source changed before completion"
            )
        locked_expected = _candidate_for_receipt(locked_plan, current)
        locked_candidate = _find_exact_candidate(locked_manifest, locked_expected)
        if locked_candidate is None:
            raise ShotImageAttemptReconciliationRequired(
                "shot image candidate changed before attempt completion"
            )
        updated, completed = complete_shot_image_attempt(
            ledger,
            current,
            locked_candidate,
            post_manifest_fingerprint=locked_manifest.manifest_fingerprint,
            expected_ledger_fingerprint=ledger.ledger_fingerprint,
        )
        _persist_ledger(workspace, updated, target_token=token)
    return completed


def resume_shot_image_attempt(
    workspace: str,
    *,
    shot_id: str,
    capability: ShotImageProviderCapability | Mapping[str, Any],
    provider_fingerprint: str,
    episode_no: int = 1,
) -> ShotImageAttemptRecord:
    try:
        number = normalize_episode_no(episode_no)
        plan, manifest, spec, _ = _current_spec(
            workspace,
            episode_no=number,
            shot_id=shot_id,
            capability=capability,
            provider_fingerprint=provider_fingerprint,
        )
        ledger = _read_ledger(workspace, episode_no=number)
        record = _latest_compatible_attempt(ledger, spec)
        if record is None:
            unresolved = _latest_attempt_for_shot(ledger, shot_id)
            if unresolved is not None and unresolved.status != "succeeded":
                raise ShotImageAttemptReconciliationRequired(
                    "an earlier shot image attempt must be reconciled before provider or source drift"
                )
            raise DramaShotImageAttemptStoreError("shot image attempt does not exist")
        if record.status == "succeeded":
            expected = _candidate_for_receipt(plan, record)
            candidate = _find_exact_candidate(manifest, expected)
            if candidate is None:
                raise DramaShotImageAttemptStoreError("succeeded shot image candidate is missing")
            if (
                record.candidate_id != candidate.candidate_id
                or record.candidate_fingerprint != candidate.candidate_fingerprint
            ):
                raise DramaShotImageAttemptStoreError(
                    "succeeded shot image ledger does not match its exact candidate"
                )
            return record
        if record.status == "started":
            try:
                _, identity = _read_staging(workspace, record)
            except FileNotFoundError:
                raise ShotImageAttemptReconciliationRequired(
                    "shot image submission outcome is unknown; adapter will not be called again"
                ) from None
            receipt = build_shot_image_attempt_receipt(
                record,
                artifact_sha256=identity[0],
                artifact_size_bytes=identity[1],
                width=identity[2],
                height=identity[3],
            )
            root = paths.workspace_root(workspace)
            path = shot_image_attempt_ledger_path(workspace, episode_no=number)
            with use_workspace(workspace), acquire_write_lock(source="drama-shot-image-attempts"):
                token = _ledger_target_token(root, path)
                latest_ledger = _read_ledger(workspace, episode_no=number)
                latest = next(
                    item for item in latest_ledger.attempts if item.attempt_id == record.attempt_id
                )
                updated, record = record_shot_image_artifact_received(
                    latest_ledger,
                    latest,
                    receipt,
                    expected_ledger_fingerprint=latest_ledger.ledger_fingerprint,
                )
                _persist_ledger(workspace, updated, target_token=token)
        if record.status == "artifact_received":
            return _complete_received_attempt(workspace, record)
        raise ShotImageAttemptReconciliationRequired(
            "shot image attempt is terminal and will not be retried automatically"
        )
    except (DramaShotImageAttemptStoreError, ShotImageAttemptReconciliationRequired):
        raise
    except (DramaShotImageAttemptError, OSError, RecursionError, TypeError, ValueError, WorkspaceLocked):
        raise DramaShotImageAttemptStoreError("shot image attempt resume was rejected") from None


def run_shot_image_attempt_with_adapter(
    workspace: str,
    *,
    shot_id: str,
    capability: ShotImageProviderCapability | Mapping[str, Any],
    provider_fingerprint: str,
    adapter: ShotImageProviderAdapter,
    episode_no: int = 1,
    expected_manifest_fingerprint: str,
) -> ShotImageAttemptRecord:
    """Call an injected adapter at most once, then commit through the C2 store."""

    try:
        number = normalize_episode_no(episode_no)
        root = paths.workspace_root(workspace)
        _validate_render_workspace_root(root)
        ledger_path = shot_image_attempt_ledger_path(workspace, episode_no=number)
        existing_record: ShotImageAttemptRecord | None = None
        with use_workspace(workspace), acquire_write_lock(source="drama-shot-image-attempts"):
            plan, manifest, spec, prompt = _current_spec(
                workspace,
                episode_no=number,
                shot_id=shot_id,
                capability=capability,
                provider_fingerprint=provider_fingerprint,
            )
            token = _ledger_target_token(root, ledger_path)
            try:
                ledger = _read_ledger(workspace, episode_no=number)
            except FileNotFoundError:
                ledger = build_empty_shot_image_attempt_ledger(plan)
            existing_record = _latest_compatible_attempt(ledger, spec)
            if existing_record is None:
                unresolved = _latest_attempt_for_shot(ledger, shot_id)
                if unresolved is not None and unresolved.status != "succeeded":
                    raise ShotImageAttemptReconciliationRequired(
                        "an earlier shot image attempt must be reconciled before provider or source drift"
                    )
                if manifest.manifest_fingerprint != expected_manifest_fingerprint:
                    raise DramaShotImageAttemptStoreError(
                        "candidate manifest changed before the shot image attempt"
                    )
                references = _reference_bytes(workspace, spec)
                updated, record = start_shot_image_attempt(
                    ledger,
                    spec,
                    expected_ledger_fingerprint=ledger.ledger_fingerprint,
                )
                try:
                    _read_staging(workspace, record)
                except FileNotFoundError:
                    pass
                else:
                    raise DramaShotImageAttemptStoreError(
                        "shot image staging exists before adapter invocation"
                    )
                ledger = _persist_ledger(workspace, updated, target_token=token)
                token = _ledger_target_token(root, ledger_path)
                adapter_failure: tuple[str, str] | None = None
                result: bytes | None = None
                try:
                    result = adapter.generate(
                        spec,
                        prompt=prompt,
                        reference_bytes=references,
                    )
                except RequestNotSentError:
                    adapter_failure = ("not_sent", "shot image request was proven not sent")
                except (ShotImageProviderTimeout, TimeoutError):
                    adapter_failure = ("timeout", "shot image adapter timed out")
                except ShotImageProviderNetworkError:
                    adapter_failure = ("network_error", "shot image adapter failed")
                except Exception:
                    adapter_failure = ("local_error", "shot image adapter failed")
                if adapter_failure is not None:
                    failure_status, public_message = adapter_failure
                    if failure_status == "not_sent":
                        released = discard_not_sent_shot_image_attempt(
                            ledger,
                            record,
                            expected_ledger_fingerprint=ledger.ledger_fingerprint,
                        )
                        _persist_ledger(workspace, released, target_token=token)
                    else:
                        updated, _ = fail_shot_image_attempt(
                            ledger,
                            record,
                            status=failure_status,
                            expected_ledger_fingerprint=ledger.ledger_fingerprint,
                        )
                        _persist_ledger(workspace, updated, target_token=token)
                    raise DramaShotImageAttemptStoreError(public_message)
                try:
                    if type(result) is not bytes:
                        raise ShotImageProviderResponseError(
                            "shot image adapter did not return bytes"
                        )
                    identity = _candidate_payload_identity(result)
                    receipt = build_shot_image_attempt_receipt(
                        record,
                        artifact_sha256=identity[0],
                        artifact_size_bytes=identity[1],
                        width=identity[2],
                        height=identity[3],
                    )
                except (DramaShotImageAttemptError, RecursionError, TypeError, ValueError):
                    updated, _ = fail_shot_image_attempt(
                        ledger,
                        record,
                        status="provider_error",
                        expected_ledger_fingerprint=ledger.ledger_fingerprint,
                    )
                    _persist_ledger(workspace, updated, target_token=token)
                    raise DramaShotImageAttemptStoreError("shot image adapter failed") from None
                try:
                    _write_staging_create_only(workspace, record, result)
                    updated, record = record_shot_image_artifact_received(
                        ledger,
                        record,
                        receipt,
                        expected_ledger_fingerprint=ledger.ledger_fingerprint,
                    )
                    _persist_ledger(workspace, updated, target_token=token)
                except Exception:
                    raise DramaShotImageAttemptStoreError(
                        "shot image artifact requires zero-provider reconciliation"
                    ) from None
            else:
                if existing_record.status in {
                    "timeout",
                    "network_error",
                    "provider_error",
                    "local_error",
                }:
                    raise ShotImageAttemptReconciliationRequired(
                        "shot image attempt failed and will not be retried automatically"
                    )
        return resume_shot_image_attempt(
            workspace,
            episode_no=number,
            shot_id=shot_id,
            capability=capability,
            provider_fingerprint=provider_fingerprint,
        )
    except (DramaShotImageAttemptStoreError, ShotImageAttemptReconciliationRequired):
        raise
    except (DramaShotImageAttemptError, OSError, RecursionError, TypeError, ValueError, WorkspaceLocked):
        raise DramaShotImageAttemptStoreError("shot image attempt operation was rejected") from None
