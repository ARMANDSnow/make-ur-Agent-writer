"""Strict local D3 storage and crash-safe execution for shot-video attempts."""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Mapping, Protocol, Sequence

from . import paths
from .drama_schemas import (
    EpisodeShotVideoAttemptLedger,
    EpisodeShotVideoCandidateManifest,
    ShotVideoAttemptInspection,
    ShotVideoAttemptRecord,
    ShotVideoAttemptSpec,
    ShotVideoCandidate,
    ShotVideoProviderCapability,
    ShotVideoSubmissionGate,
    ShotVideoSubmissionReceipt,
    ShotVideoTerminalReceipt,
    normalize_episode_no,
)
from .drama_shot_video_attempts import (
    DramaShotVideoAttemptError,
    build_empty_shot_video_attempt_ledger,
    build_shot_video_artifact_receipt,
    build_shot_video_attempt_spec,
    build_shot_video_closure_receipt,
    build_shot_video_submission_receipt,
    build_shot_video_terminal_receipt,
    classify_shot_video_attempt,
    close_unknown_shot_video_attempt,
    complete_shot_video_attempt,
    record_shot_video_artifact_received,
    record_shot_video_not_sent,
    record_shot_video_submission_unknown,
    record_shot_video_submitted,
    record_shot_video_terminal,
    shot_video_attempt_prompt,
    start_shot_video_attempt,
)
from .drama_shot_video_candidate_store import (
    MAX_SHOT_VIDEO_CANDIDATE_BYTES,
    _candidate_payload_identity,
    _open_parent_dir,
    _validate_exact_candidate_artifact,
    append_local_shot_video_candidate,
    load_fresh_episode_shot_video_candidates,
)
from .drama_shot_video_candidates import build_shot_video_candidate
from .drama_shot_video_store import load_fresh_episode_shot_video_plan
from .drama_store import (
    _read_strict_workspace_bytes,
    _read_strict_workspace_json,
    _validate_render_workspace_root,
)
from .schemas import model_to_dict
from .secure_http import RequestNotSentError
from .web.workspace_ctx import use_workspace
from .workspace_lock import WorkspaceLocked, acquire_write_lock


MAX_SHOT_VIDEO_ATTEMPT_LEDGER_BYTES = 12_000_000


class ShotVideoProviderTimeout(TimeoutError):
    pass


class ShotVideoProviderNetworkError(ConnectionError):
    pass


class ShotVideoProviderResponseError(ValueError):
    pass


@dataclass(frozen=True)
class ShotVideoPollResult:
    state: Literal["pending", "succeeded", "failed"]
    result_token: str | None = None
    cost_reported: bool = False
    actual_cost_microunits: int | None = None


@dataclass(frozen=True)
class ShotVideoAdapterIdentity:
    backend_id: str
    provider_fingerprint: str
    model_fingerprint: str
    account_fingerprint: str
    endpoint_fingerprint: str
    auth_fingerprint: str


def shot_video_adapter_identity_from_gate(
    gate: ShotVideoSubmissionGate,
) -> ShotVideoAdapterIdentity:
    return ShotVideoAdapterIdentity(
        backend_id=gate.backend_id,
        provider_fingerprint=gate.provider_fingerprint,
        model_fingerprint=gate.model_fingerprint,
        account_fingerprint=gate.account_fingerprint,
        endpoint_fingerprint=gate.endpoint_fingerprint,
        auth_fingerprint=gate.auth_fingerprint,
    )


class LocalFakeShotVideoAdapter:
    """Deterministic offline adapter; callers inject already-synthetic MP4 bytes."""

    def __init__(
        self,
        *,
        identity: ShotVideoAdapterIdentity,
        output_bytes: bytes,
        terminal_state: Literal["succeeded", "failed"] = "succeeded",
    ) -> None:
        if type(output_bytes) is not bytes:
            raise TypeError("local fake shot video output must be bytes")
        self.identity = identity
        self._output_bytes = output_bytes
        self._terminal_state = terminal_state
        self.submit_calls = 0
        self.poll_calls = 0
        self.download_calls = 0

    def submit(self, spec: ShotVideoAttemptSpec, **_: Any) -> str:
        self.submit_calls += 1
        return f"fake-{spec.input_fingerprint[:32]}"

    def poll(
        self,
        spec: ShotVideoAttemptSpec,
        submission: ShotVideoSubmissionReceipt,
    ) -> ShotVideoPollResult:
        self.poll_calls += 1
        if self._terminal_state == "failed":
            return ShotVideoPollResult("failed")
        return ShotVideoPollResult(
            "succeeded", result_token=f"fake-result-{spec.input_fingerprint[:24]}"
        )

    def download(self, *_: Any) -> bytes:
        self.download_calls += 1
        return self._output_bytes


class ShotVideoProviderAdapter(Protocol):
    """Minimal injected seam; it is not a registry or network implementation."""

    identity: ShotVideoAdapterIdentity

    def submit(
        self,
        spec: ShotVideoAttemptSpec,
        *,
        prompt: str,
        frame_bytes: Sequence[bytes],
        reference_bytes: Sequence[bytes],
    ) -> str: ...

    def poll(
        self,
        spec: ShotVideoAttemptSpec,
        submission: ShotVideoSubmissionReceipt,
    ) -> ShotVideoPollResult: ...

    def download(
        self,
        spec: ShotVideoAttemptSpec,
        submission: ShotVideoSubmissionReceipt,
        terminal: ShotVideoTerminalReceipt,
    ) -> bytes: ...


class DramaShotVideoAttemptStoreError(ValueError):
    pass


class ShotVideoAttemptReconciliationRequired(DramaShotVideoAttemptStoreError):
    pass


class _AttemptLedgerReadError(ValueError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def _validate_adapter_identity(
    adapter: ShotVideoProviderAdapter,
    gate: ShotVideoSubmissionGate,
) -> None:
    try:
        identity = adapter.identity
    except Exception:
        raise DramaShotVideoAttemptStoreError(
            "shot video adapter identity is unavailable"
        ) from None
    if not isinstance(identity, ShotVideoAdapterIdentity):
        raise DramaShotVideoAttemptStoreError("shot video adapter identity is invalid")
    expected = shot_video_adapter_identity_from_gate(gate)
    if identity != expected:
        raise ShotVideoAttemptReconciliationRequired(
            "shot video adapter identity changed"
        )


def shot_video_attempt_ledger_path(
    workspace: str,
    *,
    episode_no: int = 1,
) -> Path:
    number = normalize_episode_no(episode_no)
    root = paths.workspace_root(workspace)
    path = root / "logs" / "drama_shot_videos" / f"episode_{number:02d}.attempts.json"
    if path.parent.parent.parent != root:
        raise ValueError("shot video attempt ledger path does not match workspace")
    return path


def _target_token(root: Path, path: Path) -> tuple[Any, ...]:
    try:
        payload = _read_strict_workspace_bytes(
            root,
            path,
            maximum=MAX_SHOT_VIDEO_ATTEMPT_LEDGER_BYTES,
        )
    except FileNotFoundError:
        return ("missing",)
    except ValueError:
        return ("invalid",)
    return ("file", len(payload), hashlib.sha256(payload).hexdigest())


def _target_token_at(directory_fd: int, name: str) -> tuple[Any, ...]:
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
            or info.st_size > MAX_SHOT_VIDEO_ATTEMPT_LEDGER_BYTES
        ):
            return ("invalid",)
        chunks: list[bytes] = []
        remaining = MAX_SHOT_VIDEO_ATTEMPT_LEDGER_BYTES + 1
        while remaining > 0:
            chunk = os.read(file_fd, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) != info.st_size or len(payload) > MAX_SHOT_VIDEO_ATTEMPT_LEDGER_BYTES:
            return ("invalid",)
        return ("file", len(payload), hashlib.sha256(payload).hexdigest())
    except OSError:
        return ("invalid",)
    finally:
        if file_fd is not None:
            try:
                os.close(file_fd)
            except OSError:
                pass


def _read_ledger(
    workspace: str,
    *,
    episode_no: int,
) -> EpisodeShotVideoAttemptLedger:
    root = paths.workspace_root(workspace)
    path = shot_video_attempt_ledger_path(workspace, episode_no=episode_no)
    try:
        raw = _read_strict_workspace_json(
            root,
            path,
            maximum=MAX_SHOT_VIDEO_ATTEMPT_LEDGER_BYTES,
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
    if raw["artifact_type"] != "drama_episode_shot_video_attempts":
        raise _AttemptLedgerReadError("schema_invalid")
    try:
        ledger = EpisodeShotVideoAttemptLedger(**raw["ledger"])
    except (TypeError, ValueError) as exc:
        raise _AttemptLedgerReadError("schema_invalid") from exc
    if raw["ledger_fingerprint"] != ledger.ledger_fingerprint or ledger.episode_no != episode_no:
        raise _AttemptLedgerReadError("ledger_hash_mismatch")
    return ledger


def _write_ledger(
    workspace: str,
    ledger: EpisodeShotVideoAttemptLedger,
    *,
    expected_target_token: tuple[Any, ...],
) -> None:
    envelope = {
        "schema_version": 1,
        "artifact_type": "drama_episode_shot_video_attempts",
        "ledger_fingerprint": ledger.ledger_fingerprint,
        "ledger": model_to_dict(ledger),
    }
    payload = (
        json.dumps(envelope, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
    ).encode("utf-8")
    if not payload or len(payload) > MAX_SHOT_VIDEO_ATTEMPT_LEDGER_BYTES:
        raise DramaShotVideoAttemptStoreError("shot video attempt ledger exceeds its limit")
    root = paths.workspace_root(workspace)
    path = shot_video_attempt_ledger_path(workspace, episode_no=ledger.episode_no)
    _validate_render_workspace_root(root)
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise DramaShotVideoAttemptStoreError("shot video ledger escapes workspace") from exc
    directory_fd: int | None = None
    temp_fd: int | None = None
    temp_identity: tuple[int, int] | None = None
    temp_name = f".{relative.name}.tmp.{secrets.token_hex(16)}"
    try:
        directory_fd = _open_parent_dir(root, relative, create=True)
        if _target_token_at(directory_fd, relative.name) != expected_target_token:
            raise DramaShotVideoAttemptStoreError("shot video attempt ledger changed concurrently")
        temp_fd = os.open(
            temp_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=directory_fd,
        )
        opened = os.fstat(temp_fd)
        temp_identity = (opened.st_dev, opened.st_ino)
        view = memoryview(payload)
        while view:
            written = os.write(temp_fd, view)
            if written <= 0:
                raise OSError("short shot video attempt ledger write")
            view = view[written:]
        os.fsync(temp_fd)
        if _target_token_at(directory_fd, relative.name) != expected_target_token:
            raise DramaShotVideoAttemptStoreError("shot video attempt ledger changed concurrently")
        opened = os.fstat(temp_fd)
        named = os.stat(temp_name, dir_fd=directory_fd, follow_symlinks=False)
        if (
            not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(named.st_mode)
            or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
        ):
            raise DramaShotVideoAttemptStoreError("shot video temporary ledger changed")
        os.replace(
            temp_name,
            relative.name,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        os.fsync(directory_fd)
    except DramaShotVideoAttemptStoreError:
        raise
    except OSError as exc:
        raise DramaShotVideoAttemptStoreError(
            "shot video attempt ledger could not be written safely"
        ) from exc
    finally:
        if temp_fd is not None:
            try:
                os.close(temp_fd)
            except OSError:
                pass
        if directory_fd is not None and temp_identity is not None:
            try:
                current = os.stat(temp_name, dir_fd=directory_fd, follow_symlinks=False)
            except OSError:
                pass
            else:
                if stat.S_ISREG(current.st_mode) and (
                    current.st_dev,
                    current.st_ino,
                ) == temp_identity:
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
    ledger: EpisodeShotVideoAttemptLedger,
    *,
    target_token: tuple[Any, ...],
) -> EpisodeShotVideoAttemptLedger:
    _write_ledger(workspace, ledger, expected_target_token=target_token)
    persisted = _read_ledger(workspace, episode_no=ledger.episode_no)
    if persisted.ledger_fingerprint != ledger.ledger_fingerprint:
        raise DramaShotVideoAttemptStoreError("shot video attempt ledger persistence failed")
    return persisted


def load_episode_shot_video_attempts(
    workspace: str,
    *,
    episode_no: int = 1,
) -> EpisodeShotVideoAttemptLedger:
    try:
        return _read_ledger(workspace, episode_no=normalize_episode_no(episode_no))
    except _AttemptLedgerReadError:
        raise DramaShotVideoAttemptStoreError("shot video attempt ledger is invalid") from None
    except (OSError, RecursionError, TypeError, ValueError):
        raise DramaShotVideoAttemptStoreError("shot video attempt ledger could not be loaded") from None


def _current_sources(
    workspace: str,
    *,
    episode_no: int,
) -> tuple[Any, EpisodeShotVideoCandidateManifest]:
    plan = load_fresh_episode_shot_video_plan(workspace, episode_no=episode_no)
    manifest = load_fresh_episode_shot_video_candidates(workspace, episode_no=episode_no)
    if manifest.source_plan_fingerprint != plan.plan_fingerprint:
        raise DramaShotVideoAttemptStoreError("shot video candidate source is stale")
    return plan, manifest


def _current_spec(
    workspace: str,
    *,
    episode_no: int,
    shot_id: str,
    capability: ShotVideoProviderCapability | Mapping[str, Any],
    submission_gate: ShotVideoSubmissionGate | Mapping[str, Any],
    mode: str,
    output_width: int,
    output_height: int,
) -> tuple[Any, EpisodeShotVideoCandidateManifest, ShotVideoAttemptSpec, str]:
    plan, manifest = _current_sources(workspace, episode_no=episode_no)
    spec = build_shot_video_attempt_spec(
        plan,
        manifest,
        shot_id=shot_id,
        capability=capability,
        submission_gate=submission_gate,
        mode=mode,
        output_width=output_width,
        output_height=output_height,
    )
    request = next(item for item in plan.shot_specs if item.shot_id == shot_id)
    return plan, manifest, spec, shot_video_attempt_prompt(request)


def _read_exact_artifact(
    root: Path,
    relative_path: str,
    *,
    size_bytes: int,
    sha256: str,
) -> bytes:
    data = _read_strict_workspace_bytes(root, root / relative_path, maximum=size_bytes)
    if len(data) != size_bytes or hashlib.sha256(data).hexdigest() != sha256:
        raise DramaShotVideoAttemptStoreError("shot video input artifact changed")
    return data


def _input_bytes(
    workspace: str,
    spec: ShotVideoAttemptSpec,
) -> tuple[tuple[bytes, ...], tuple[bytes, ...]]:
    root = paths.workspace_root(workspace)
    frames = [spec.first_frame]
    if spec.tail_frame is not None:
        frames.append(spec.tail_frame)
    frame_bytes = tuple(
        _read_exact_artifact(
            root,
            frame.artifact.path,
            size_bytes=frame.artifact.size_bytes,
            sha256=frame.artifact.sha256,
        )
        for frame in frames
    )
    reference_bytes = tuple(
        _read_exact_artifact(
            root,
            reference.artifact_path,
            size_bytes=reference.artifact_size_bytes,
            sha256=reference.artifact_sha256,
        )
        for reference in spec.ordered_references
    )
    return frame_bytes, reference_bytes


def _read_staging(
    workspace: str,
    record: ShotVideoAttemptRecord,
) -> tuple[bytes, tuple[str, int, int, int, int, bool]]:
    root = paths.workspace_root(workspace)
    data = _read_strict_workspace_bytes(
        root,
        root / record.staging_path,
        maximum=MAX_SHOT_VIDEO_CANDIDATE_BYTES,
    )
    return data, _candidate_payload_identity(data)


def _write_staging_create_only(
    workspace: str,
    record: ShotVideoAttemptRecord,
    data: bytes,
) -> None:
    identity = _candidate_payload_identity(data)
    if identity[3:5] != (record.spec.output_width, record.spec.output_height):
        raise DramaShotVideoAttemptStoreError("shot video output resolution is invalid")
    target_duration = record.spec.target_duration_seconds * 1000
    if abs(identity[2] - target_duration) > 1000:
        raise DramaShotVideoAttemptStoreError("shot video output duration is invalid")
    root = paths.workspace_root(workspace)
    path = root / record.staging_path
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise DramaShotVideoAttemptStoreError("shot video staging escapes workspace") from exc
    try:
        existing = _read_strict_workspace_bytes(
            root,
            path,
            maximum=MAX_SHOT_VIDEO_CANDIDATE_BYTES,
        )
    except FileNotFoundError:
        existing = None
    except (OSError, ValueError) as exc:
        raise DramaShotVideoAttemptStoreError("shot video staging target is invalid") from exc
    if existing is not None:
        if existing != data or _candidate_payload_identity(existing) != identity:
            raise DramaShotVideoAttemptStoreError("shot video staging target is occupied")
        return
    directory_fd: int | None = None
    file_fd: int | None = None
    created_identity: tuple[int, int] | None = None
    committed = False
    try:
        directory_fd = _open_parent_dir(root, relative, create=True)
        file_fd = os.open(
            relative.name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0),
            0o600,
            dir_fd=directory_fd,
        )
        opened = os.fstat(file_fd)
        created_identity = (opened.st_dev, opened.st_ino)
        view = memoryview(data)
        while view:
            written = os.write(file_fd, view)
            if written <= 0:
                raise OSError("short shot video staging write")
            view = view[written:]
        os.fsync(file_fd)
        named = os.stat(relative.name, dir_fd=directory_fd, follow_symlinks=False)
        opened = os.fstat(file_fd)
        if (
            not stat.S_ISREG(opened.st_mode)
            or not stat.S_ISREG(named.st_mode)
            or (opened.st_dev, opened.st_ino) != (named.st_dev, named.st_ino)
        ):
            raise DramaShotVideoAttemptStoreError("shot video staging changed concurrently")
        os.fsync(directory_fd)
        committed = True
    except DramaShotVideoAttemptStoreError:
        raise
    except OSError as exc:
        raise DramaShotVideoAttemptStoreError("shot video staging could not be written safely") from exc
    finally:
        if file_fd is not None:
            try:
                os.close(file_fd)
            except OSError:
                pass
        if directory_fd is not None:
            if created_identity is not None:
                try:
                    current = os.stat(relative.name, dir_fd=directory_fd, follow_symlinks=False)
                except OSError:
                    pass
                else:
                    owned = stat.S_ISREG(current.st_mode) and (
                        current.st_dev,
                        current.st_ino,
                    ) == created_identity
                    if not committed and owned:
                        try:
                            os.unlink(relative.name, dir_fd=directory_fd)
                            os.fsync(directory_fd)
                        except OSError:
                            pass
                    elif not owned:
                        try:
                            os.close(directory_fd)
                        except OSError:
                            pass
                        directory_fd = None
            if directory_fd is not None:
                try:
                    os.close(directory_fd)
                except OSError:
                    pass
    persisted, persisted_identity = _read_staging(workspace, record)
    if persisted != data or persisted_identity != identity:
        raise DramaShotVideoAttemptStoreError("shot video staging persistence failed")


def _latest_for_shot(
    ledger: EpisodeShotVideoAttemptLedger,
    shot_id: str,
) -> ShotVideoAttemptRecord | None:
    matches = [item for item in ledger.attempts if item.spec.shot_id == shot_id]
    return matches[-1] if matches else None


def _latest_compatible_attempt(
    ledger: EpisodeShotVideoAttemptLedger,
    spec: ShotVideoAttemptSpec,
) -> ShotVideoAttemptRecord | None:
    matches = [
        item
        for item in ledger.attempts
        if item.spec.shot_id == spec.shot_id
        and item.spec.source_plan_fingerprint == spec.source_plan_fingerprint
        and item.spec.request_fingerprint == spec.request_fingerprint
        and item.spec.mode == spec.mode
        and item.spec.output_width == spec.output_width
        and item.spec.output_height == spec.output_height
        and item.spec.capability.capability_fingerprint
        == spec.capability.capability_fingerprint
        and item.spec.submission_gate.authorization_fingerprint
        == spec.submission_gate.authorization_fingerprint
    ]
    return matches[-1] if matches else None


def _spec_identity_matches(
    record: ShotVideoAttemptRecord,
    capability: ShotVideoProviderCapability | Mapping[str, Any],
    submission_gate: ShotVideoSubmissionGate | Mapping[str, Any],
) -> bool:
    try:
        current_capability = (
            capability
            if isinstance(capability, ShotVideoProviderCapability)
            else ShotVideoProviderCapability(**capability)
        )
        current_gate = (
            submission_gate
            if isinstance(submission_gate, ShotVideoSubmissionGate)
            else ShotVideoSubmissionGate(**submission_gate)
        )
    except (TypeError, ValueError):
        return False
    return (
        record.spec.capability.capability_fingerprint
        == current_capability.capability_fingerprint
        and record.spec.submission_gate.authorization_fingerprint
        == current_gate.authorization_fingerprint
    )


def _validate_poll_result(value: Any) -> ShotVideoPollResult:
    if not isinstance(value, ShotVideoPollResult):
        raise ShotVideoProviderResponseError("shot video poll result is invalid")
    if value.state == "pending":
        if value.result_token is not None or value.cost_reported or value.actual_cost_microunits is not None:
            raise ShotVideoProviderResponseError("pending shot video poll has terminal data")
    elif value.state == "succeeded":
        if not isinstance(value.result_token, str) or not value.result_token or "://" in value.result_token:
            raise ShotVideoProviderResponseError("shot video result token is invalid")
    elif value.result_token is not None:
        raise ShotVideoProviderResponseError("failed shot video poll has a result token")
    if type(value.cost_reported) is not bool:
        raise ShotVideoProviderResponseError("shot video cost state is invalid")
    if value.actual_cost_microunits is not None and (
        not isinstance(value.actual_cost_microunits, int)
        or isinstance(value.actual_cost_microunits, bool)
        or not 0 <= value.actual_cost_microunits <= 1_000_000_000_000
    ):
        raise ShotVideoProviderResponseError("shot video cost is invalid")
    if value.cost_reported != (value.actual_cost_microunits is not None):
        raise ShotVideoProviderResponseError("shot video cost reporting is inconsistent")
    return value


def _candidate_for_receipt(
    plan: Any,
    record: ShotVideoAttemptRecord,
) -> ShotVideoCandidate:
    receipt = record.artifact_receipt
    if receipt is None:
        raise DramaShotVideoAttemptStoreError("shot video artifact receipt is missing")
    return build_shot_video_candidate(
        plan,
        shot_id=record.spec.shot_id,
        artifact_sha256=receipt.sha256,
        artifact_size_bytes=receipt.size_bytes,
        duration_milliseconds=receipt.duration_milliseconds,
        width=receipt.width,
        height=receipt.height,
        has_audio_track=receipt.has_audio_track,
    )


def _find_exact_candidate(
    manifest: EpisodeShotVideoCandidateManifest,
    expected: ShotVideoCandidate,
) -> ShotVideoCandidate | None:
    matches = [
        candidate
        for pool in [*manifest.shots, *manifest.retired_shots]
        for candidate in pool.candidates
        if candidate.candidate_id == expected.candidate_id
    ]
    if not matches:
        return None
    if matches != [expected]:
        raise DramaShotVideoAttemptStoreError("shot video candidate identity collision")
    return matches[0]


def _verify_succeeded_attempt(
    workspace: str,
    record: ShotVideoAttemptRecord,
) -> ShotVideoAttemptRecord:
    plan, manifest = _current_sources(workspace, episode_no=record.spec.episode_no)
    if (
        plan.plan_fingerprint != record.spec.source_plan_fingerprint
        or next(
            (item.spec_fingerprint for item in plan.shot_specs if item.shot_id == record.spec.shot_id),
            None,
        )
        != record.spec.request_fingerprint
    ):
        raise ShotVideoAttemptReconciliationRequired("succeeded shot video source changed")
    expected = _candidate_for_receipt(plan, record)
    candidate = _find_exact_candidate(manifest, expected)
    if candidate is None:
        raise DramaShotVideoAttemptStoreError("succeeded shot video candidate is missing")
    if (
        record.candidate_id != candidate.candidate_id
        or record.candidate_fingerprint != candidate.candidate_fingerprint
    ):
        raise DramaShotVideoAttemptStoreError(
            "succeeded shot video ledger does not match its exact candidate"
        )
    _validate_exact_candidate_artifact(workspace, candidate)
    return record


def _complete_received_attempt(
    workspace: str,
    record: ShotVideoAttemptRecord,
) -> ShotVideoAttemptRecord:
    if record.status != "artifact_received" or record.artifact_receipt is None:
        raise DramaShotVideoAttemptStoreError("shot video attempt is not ready to commit")
    plan, manifest = _current_sources(workspace, episode_no=record.spec.episode_no)
    if (
        plan.plan_fingerprint != record.spec.source_plan_fingerprint
        or next(
            (item.spec_fingerprint for item in plan.shot_specs if item.shot_id == record.spec.shot_id),
            None,
        )
        != record.spec.request_fingerprint
    ):
        raise ShotVideoAttemptReconciliationRequired("shot video attempt source changed")
    expected = _candidate_for_receipt(plan, record)
    candidate = _find_exact_candidate(manifest, expected)
    if candidate is None:
        data, identity = _read_staging(workspace, record)
        receipt = record.artifact_receipt
        if identity != (
            receipt.sha256,
            receipt.size_bytes,
            receipt.duration_milliseconds,
            receipt.width,
            receipt.height,
            receipt.has_audio_track,
        ):
            raise DramaShotVideoAttemptStoreError("shot video staging changed after receipt")
        manifest, candidate = append_local_shot_video_candidate(
            workspace,
            episode_no=record.spec.episode_no,
            shot_id=record.spec.shot_id,
            mp4_bytes=data,
            expected_manifest_fingerprint=manifest.manifest_fingerprint,
        )
    else:
        _validate_exact_candidate_artifact(workspace, candidate)
    root = paths.workspace_root(workspace)
    ledger_path = shot_video_attempt_ledger_path(
        workspace,
        episode_no=record.spec.episode_no,
    )
    with use_workspace(workspace), acquire_write_lock(source="drama-shot-video-attempts"):
        token = _target_token(root, ledger_path)
        ledger = _read_ledger(workspace, episode_no=record.spec.episode_no)
        current = next(
            (item for item in ledger.attempts if item.attempt_id == record.attempt_id),
            None,
        )
        if current is None:
            raise DramaShotVideoAttemptStoreError("shot video attempt disappeared")
        if current.status == "succeeded":
            return current
        if current.record_fingerprint != record.record_fingerprint:
            raise DramaShotVideoAttemptStoreError("shot video attempt changed concurrently")
        locked_plan, locked_manifest = _current_sources(
            workspace,
            episode_no=record.spec.episode_no,
        )
        locked_expected = _candidate_for_receipt(locked_plan, current)
        locked_candidate = _find_exact_candidate(locked_manifest, locked_expected)
        if locked_candidate is None:
            raise ShotVideoAttemptReconciliationRequired("shot video candidate changed before completion")
        updated, completed = complete_shot_video_attempt(
            ledger,
            current,
            locked_candidate,
            post_manifest_fingerprint=locked_manifest.manifest_fingerprint,
            expected_ledger_fingerprint=ledger.ledger_fingerprint,
        )
        _persist_ledger(workspace, updated, target_token=token)
    return completed


def inspect_episode_shot_video_attempts(
    workspace: str,
    *,
    episode_no: int = 1,
) -> ShotVideoAttemptInspection:
    empty = {
        "not_sent_attempt_ids": [],
        "unknown_attempt_ids": [],
        "submitted_attempt_ids": [],
        "terminal_attempt_ids": [],
    }
    try:
        number = normalize_episode_no(episode_no)
        try:
            ledger = _read_ledger(workspace, episode_no=number)
        except FileNotFoundError:
            return ShotVideoAttemptInspection(
                state="needs_attempts",
                reasons=["missing"],
                ledger_fingerprint=None,
                **empty,
            )
        latest: dict[str, ShotVideoAttemptRecord] = {}
        for attempt in ledger.attempts:
            latest[attempt.spec.shot_id] = attempt
        groups = {key: [] for key in ("not_sent", "unknown", "submitted", "terminal")}
        for attempt in latest.values():
            groups[classify_shot_video_attempt(attempt)].append(attempt.attempt_id)
        projection = {
            "not_sent_attempt_ids": groups["not_sent"],
            "unknown_attempt_ids": groups["unknown"],
            "submitted_attempt_ids": groups["submitted"],
            "terminal_attempt_ids": groups["terminal"],
        }
        if groups["unknown"] or groups["submitted"]:
            state = "reconciliation_required"
            reasons = ["unfinished_attempts"]
        else:
            plan, _manifest = _current_sources(workspace, episode_no=number)
            current = {
                item.shot_id: item.spec_fingerprint for item in plan.shot_specs
            }
            succeeded = {
                item.spec.shot_id
                for item in ledger.attempts
                if item.status == "succeeded"
                and item.spec.source_plan_fingerprint == plan.plan_fingerprint
                and current.get(item.spec.shot_id) == item.spec.request_fingerprint
            }
            if any(
                item.status == "succeeded" and item.spec.shot_id not in succeeded
                for item in latest.values()
            ):
                state = "stale"
                reasons = ["source_changed"]
            elif set(current) <= succeeded:
                state = "fresh"
                reasons = []
            else:
                state = "needs_attempts"
                reasons = ["incomplete"]
        return ShotVideoAttemptInspection(
            state=state,
            reasons=reasons,
            ledger_fingerprint=ledger.ledger_fingerprint,
            **projection,
        )
    except _AttemptLedgerReadError:
        return ShotVideoAttemptInspection(
            state="invalid",
            reasons=["schema_invalid"],
            ledger_fingerprint=None,
            **empty,
        )
    except (OSError, RecursionError, TypeError, ValueError):
        return ShotVideoAttemptInspection(
            state="invalid",
            reasons=["inspection_failed"],
            ledger_fingerprint=None,
            **empty,
        )


def _persist_transition(
    workspace: str,
    ledger: EpisodeShotVideoAttemptLedger,
    record: ShotVideoAttemptRecord,
    *,
    expected_ledger_fingerprint: str,
) -> ShotVideoAttemptRecord:
    root = paths.workspace_root(workspace)
    path = shot_video_attempt_ledger_path(workspace, episode_no=ledger.episode_no)
    with use_workspace(workspace), acquire_write_lock(source="drama-shot-video-attempts"):
        token = _target_token(root, path)
        latest = _read_ledger(workspace, episode_no=ledger.episode_no)
        current = next(
            (item for item in latest.attempts if item.attempt_id == record.attempt_id),
            None,
        )
        if current is not None and current.record_fingerprint == record.record_fingerprint:
            return current
        if latest.ledger_fingerprint != expected_ledger_fingerprint:
            raise DramaShotVideoAttemptStoreError("shot video attempt changed concurrently")
        _persist_ledger(workspace, ledger, target_token=token)
    return record


def resume_shot_video_attempt(
    workspace: str,
    *,
    shot_id: str,
    capability: ShotVideoProviderCapability | Mapping[str, Any],
    submission_gate: ShotVideoSubmissionGate | Mapping[str, Any],
    adapter: ShotVideoProviderAdapter,
    episode_no: int = 1,
) -> ShotVideoAttemptRecord:
    """Resume only poll/download/local commit; this function never calls submit."""

    try:
        number = normalize_episode_no(episode_no)
        ledger = _read_ledger(workspace, episode_no=number)
        record = _latest_for_shot(ledger, shot_id)
        if record is None:
            raise DramaShotVideoAttemptStoreError("shot video attempt does not exist")
        if not _spec_identity_matches(record, capability, submission_gate):
            raise ShotVideoAttemptReconciliationRequired(
                "shot video provider or authorization identity changed"
            )
        _validate_adapter_identity(adapter, record.spec.submission_gate)
        if record.status in {"started", "submission_unknown"}:
            raise ShotVideoAttemptReconciliationRequired(
                "shot video submission outcome is unknown; submit will not be called again"
            )
        if record.status == "not_sent":
            raise ShotVideoAttemptReconciliationRequired(
                "shot video request was not sent; a new explicit attempt is required"
            )
        if record.status in {"provider_failed", "closed_unknown"}:
            return record
        if record.status == "submitted":
            assert record.submission_receipt is not None
            poll_failure = False
            polled: ShotVideoPollResult | None = None
            try:
                polled = _validate_poll_result(
                    adapter.poll(record.spec, record.submission_receipt)
                )
            except Exception:
                poll_failure = True
            if poll_failure:
                raise DramaShotVideoAttemptStoreError("shot video poll failed")
            assert polled is not None
            if polled.state == "pending":
                return record
            receipt = build_shot_video_terminal_receipt(
                record,
                terminal_status=polled.state,
                result_token=polled.result_token,
                cost_reported=polled.cost_reported,
                actual_cost_microunits=polled.actual_cost_microunits,
            )
            updated, next_record = record_shot_video_terminal(
                ledger,
                record,
                receipt,
                expected_ledger_fingerprint=ledger.ledger_fingerprint,
            )
            record = _persist_transition(
                workspace,
                updated,
                next_record,
                expected_ledger_fingerprint=ledger.ledger_fingerprint,
            )
            ledger = _read_ledger(workspace, episode_no=number)
            if record.status == "provider_failed":
                return record
        if record.status == "provider_succeeded":
            assert record.submission_receipt is not None and record.terminal_receipt is not None
            download_failure = False
            payload: bytes | None = None
            try:
                payload = adapter.download(
                    record.spec,
                    record.submission_receipt,
                    record.terminal_receipt,
                )
            except Exception:
                download_failure = True
            if download_failure or type(payload) is not bytes:
                raise DramaShotVideoAttemptStoreError("shot video download failed")
            identity = _candidate_payload_identity(payload)
            if identity[3:5] != (record.spec.output_width, record.spec.output_height):
                raise DramaShotVideoAttemptStoreError("shot video output resolution is invalid")
            if abs(identity[2] - record.spec.target_duration_seconds * 1000) > 1000:
                raise DramaShotVideoAttemptStoreError("shot video output duration is invalid")
            receipt = build_shot_video_artifact_receipt(
                record,
                artifact_sha256=identity[0],
                artifact_size_bytes=identity[1],
                duration_milliseconds=identity[2],
                width=identity[3],
                height=identity[4],
                has_audio_track=identity[5],
            )
            _write_staging_create_only(workspace, record, payload)
            ledger = _read_ledger(workspace, episode_no=number)
            latest = next(item for item in ledger.attempts if item.attempt_id == record.attempt_id)
            updated, next_record = record_shot_video_artifact_received(
                ledger,
                latest,
                receipt,
                expected_ledger_fingerprint=ledger.ledger_fingerprint,
            )
            record = _persist_transition(
                workspace,
                updated,
                next_record,
                expected_ledger_fingerprint=ledger.ledger_fingerprint,
            )
        if record.status == "artifact_received":
            return _complete_received_attempt(workspace, record)
        if record.status == "succeeded":
            return _verify_succeeded_attempt(workspace, record)
        raise ShotVideoAttemptReconciliationRequired("shot video attempt cannot be resumed")
    except (DramaShotVideoAttemptStoreError, ShotVideoAttemptReconciliationRequired):
        raise
    except (DramaShotVideoAttemptError, OSError, RecursionError, TypeError, ValueError, WorkspaceLocked):
        raise DramaShotVideoAttemptStoreError("shot video attempt resume was rejected") from None


def close_unknown_shot_video_attempt_in_store(
    workspace: str,
    *,
    shot_id: str,
    expected_record_fingerprint: str,
    resolution: Literal["operator_abandoned", "provider_case_closed"],
    evidence_fingerprint: str,
    episode_no: int = 1,
) -> ShotVideoAttemptRecord:
    """Durably close an unknown outcome without claiming that it was not sent."""

    try:
        number = normalize_episode_no(episode_no)
        root = paths.workspace_root(workspace)
        ledger_path = shot_video_attempt_ledger_path(workspace, episode_no=number)
        with use_workspace(workspace), acquire_write_lock(
            source="drama-shot-video-attempts"
        ):
            token = _target_token(root, ledger_path)
            ledger = _read_ledger(workspace, episode_no=number)
            record = _latest_for_shot(ledger, shot_id)
            if (
                record is None
                or record.record_fingerprint != expected_record_fingerprint
            ):
                raise ShotVideoAttemptReconciliationRequired(
                    "shot video attempt changed before reconciliation"
                )
            receipt = build_shot_video_closure_receipt(
                resolution=resolution,
                evidence_fingerprint=evidence_fingerprint,
            )
            updated, closed = close_unknown_shot_video_attempt(
                ledger,
                record,
                receipt,
                expected_ledger_fingerprint=ledger.ledger_fingerprint,
            )
            _persist_ledger(workspace, updated, target_token=token)
            return closed
    except (DramaShotVideoAttemptStoreError, ShotVideoAttemptReconciliationRequired):
        raise
    except (
        DramaShotVideoAttemptError,
        OSError,
        RecursionError,
        TypeError,
        ValueError,
        WorkspaceLocked,
    ):
        raise DramaShotVideoAttemptStoreError(
            "shot video attempt reconciliation was rejected"
        ) from None


def run_shot_video_attempt_with_adapter(
    workspace: str,
    *,
    shot_id: str,
    capability: ShotVideoProviderCapability | Mapping[str, Any],
    submission_gate: ShotVideoSubmissionGate | Mapping[str, Any],
    mode: str,
    output_width: int,
    output_height: int,
    adapter: ShotVideoProviderAdapter,
    episode_no: int = 1,
    expected_manifest_fingerprint: str,
    start_new_attempt: bool = False,
) -> ShotVideoAttemptRecord:
    """Create at most one submit call, then resume through poll/download/commit."""

    try:
        number = normalize_episode_no(episode_no)
        root = paths.workspace_root(workspace)
        _validate_render_workspace_root(root)
        ledger_path = shot_video_attempt_ledger_path(workspace, episode_no=number)
        with use_workspace(workspace), acquire_write_lock(source="drama-shot-video-attempts"):
            plan, manifest, spec, prompt = _current_spec(
                workspace,
                episode_no=number,
                shot_id=shot_id,
                capability=capability,
                submission_gate=submission_gate,
                mode=mode,
                output_width=output_width,
                output_height=output_height,
            )
            token = _target_token(root, ledger_path)
            try:
                ledger = _read_ledger(workspace, episode_no=number)
            except FileNotFoundError:
                ledger = build_empty_shot_video_attempt_ledger(plan)
            existing = _latest_compatible_attempt(ledger, spec)
            latest_for_shot = _latest_for_shot(ledger, shot_id)
            if type(start_new_attempt) is not bool:
                raise DramaShotVideoAttemptStoreError(
                    "shot video new-attempt flag is invalid"
                )
            should_start = latest_for_shot is None
            if latest_for_shot is not None and existing is None:
                if latest_for_shot.status not in {
                    "not_sent",
                    "provider_failed",
                    "succeeded",
                    "closed_unknown",
                }:
                    raise ShotVideoAttemptReconciliationRequired(
                        "earlier shot video attempt must be reconciled before source or provider drift"
                    )
                if not start_new_attempt:
                    raise ShotVideoAttemptReconciliationRequired(
                        "a new shot video attempt requires explicit authorization"
                    )
                should_start = True
            elif existing is not None and existing.status == "not_sent":
                if not start_new_attempt:
                    raise ShotVideoAttemptReconciliationRequired(
                        "a proven not-sent retry requires an explicit new attempt"
                    )
                should_start = True
            if should_start:
                if manifest.manifest_fingerprint != expected_manifest_fingerprint:
                    raise DramaShotVideoAttemptStoreError(
                        "candidate manifest changed before shot video attempt"
                    )
                frame_bytes, reference_bytes = _input_bytes(workspace, spec)
                _validate_adapter_identity(adapter, spec.submission_gate)
                updated, record = start_shot_video_attempt(
                    ledger,
                    spec,
                    expected_ledger_fingerprint=ledger.ledger_fingerprint,
                )
                try:
                    _read_staging(workspace, record)
                except FileNotFoundError:
                    pass
                else:
                    raise DramaShotVideoAttemptStoreError(
                        "shot video staging exists before submit"
                    )
                ledger = _persist_ledger(workspace, updated, target_token=token)
                token = _target_token(root, ledger_path)
                failure: Literal["not_sent", "unknown"] | None = None
                task_id: str | None = None
                try:
                    task_id = adapter.submit(
                        spec,
                        prompt=prompt,
                        frame_bytes=frame_bytes,
                        reference_bytes=reference_bytes,
                    )
                except RequestNotSentError:
                    failure = "not_sent"
                except Exception:
                    failure = "unknown"
                if failure == "not_sent":
                    updated, _ = record_shot_video_not_sent(
                        ledger,
                        record,
                        expected_ledger_fingerprint=ledger.ledger_fingerprint,
                    )
                    _persist_ledger(workspace, updated, target_token=token)
                    raise DramaShotVideoAttemptStoreError("shot video request was proven not sent")
                if failure == "unknown":
                    updated, _ = record_shot_video_submission_unknown(
                        ledger,
                        record,
                        expected_ledger_fingerprint=ledger.ledger_fingerprint,
                    )
                    _persist_ledger(workspace, updated, target_token=token)
                    raise ShotVideoAttemptReconciliationRequired(
                        "shot video submission outcome is unknown"
                    )
                try:
                    receipt = build_shot_video_submission_receipt(
                        record,
                        task_id,  # type: ignore[arg-type]
                    )
                    updated, _ = record_shot_video_submitted(
                        ledger,
                        record,
                        receipt,
                        expected_ledger_fingerprint=ledger.ledger_fingerprint,
                    )
                    _persist_ledger(workspace, updated, target_token=token)
                except Exception:
                    latest = _read_ledger(workspace, episode_no=number)
                    latest_record = next(
                        item for item in latest.attempts if item.attempt_id == record.attempt_id
                    )
                    if latest_record.status == "started":
                        next_ledger, _ = record_shot_video_submission_unknown(
                            latest,
                            latest_record,
                            expected_ledger_fingerprint=latest.ledger_fingerprint,
                        )
                        _persist_ledger(
                            workspace,
                            next_ledger,
                            target_token=_target_token(root, ledger_path),
                        )
                    raise ShotVideoAttemptReconciliationRequired(
                        "shot video submission receipt requires reconciliation"
                    ) from None
            else:
                if not _spec_identity_matches(existing, capability, submission_gate):
                    raise ShotVideoAttemptReconciliationRequired(
                        "earlier shot video attempt uses another provider or authorization"
                    )
        return resume_shot_video_attempt(
            workspace,
            episode_no=number,
            shot_id=shot_id,
            capability=capability,
            submission_gate=submission_gate,
            adapter=adapter,
        )
    except (DramaShotVideoAttemptStoreError, ShotVideoAttemptReconciliationRequired):
        raise
    except (DramaShotVideoAttemptError, OSError, RecursionError, TypeError, ValueError, WorkspaceLocked):
        raise DramaShotVideoAttemptStoreError("shot video attempt operation was rejected") from None
