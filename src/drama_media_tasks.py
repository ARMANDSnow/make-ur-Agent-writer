"""G1 strict, provider-neutral media task DAG and persistent state store.

This module coordinates dependencies and generic execution state only.  It
does not submit provider requests and never replaces image/video/TTS paid
attempt ledgers or their receipts.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Sequence

from . import drama_edit_export, paths
from .drama_schemas import (
    DramaMediaKind,
    DramaMediaBackendBinding,
    DramaMediaBackendRegistrySnapshot,
    DramaMediaTaskOutcomeCode,
    DramaMediaStage,
    DramaMediaTask,
    DramaMediaTaskLedger,
    DramaMediaTaskLedgerV2,
    DramaMediaTaskLedgerV3,
    DramaMediaTaskState,
    DramaMediaWorkerLease,
    DramaMediaWorkerReleaseReceipt,
    DramaMediaWorkerTransitionReceipt,
    _canonical_sha256,
    normalize_episode_no,
)
from .drama_store import (
    _read_strict_workspace_bytes,
    _read_strict_workspace_json,
    _validate_render_workspace_root,
)
from .drama_media_backends.base import DramaMediaBackendError
from .drama_media_backends.registry import resolve_task_backend
from .schemas import model_to_dict
from .web.workspace_ctx import use_workspace
from .workspace_lock import WorkspaceLocked, acquire_write_lock


MAX_MEDIA_TASK_LEDGER_BYTES = 4 * 1024 * 1024
MAX_WORKSPACE_METADATA_BYTES = 4 * 1024
TERMINAL_MEDIA_TASK_STATES = frozenset({"succeeded", "failed", "cancelled"})
ACTIVE_MEDIA_TASK_STATES = frozenset(
    {
        "planned",
        "ready",
        "claimed",
        "submitting",
        "submitted",
        "polling",
        "submission_unknown",
        "downloading",
        "validating",
        "cancelling",
    }
)
PROVIDER_BACKED_MEDIA_KINDS = frozenset({"image", "video", "audio"})
LEASED_MEDIA_TASK_STATES = frozenset(
    {"claimed", "submitting", "submitted", "polling", "downloading", "validating"}
)
_TRANSITIONS: dict[str, frozenset[str]] = {
    "planned": frozenset({"ready", "cancelling"}),
    "ready": frozenset({"claimed", "cancelling"}),
    "claimed": frozenset(
        {"submitting", "downloading", "validating", "failed", "cancelling"}
    ),
    "submitting": frozenset(
        {"submitted", "submission_unknown", "failed", "cancelling"}
    ),
    "submitted": frozenset(
        {"polling", "downloading", "failed", "cancelling"}
    ),
    "polling": frozenset({"downloading", "failed", "cancelling"}),
    "submission_unknown": frozenset(),
    "downloading": frozenset({"validating", "failed", "cancelling"}),
    "validating": frozenset({"succeeded", "failed", "cancelling"}),
    "succeeded": frozenset(),
    "failed": frozenset(),
    "cancelling": frozenset({"cancelled"}),
    "cancelled": frozenset(),
}


class DramaMediaTaskError(ValueError):
    """Fail-closed public error without paths, prompts, or provider payloads."""


def _canonical_dependency_task_ids(value: Any) -> list[str]:
    if (
        not isinstance(value, (list, tuple))
        or isinstance(value, (str, bytes, bytearray))
        or len(value) > 32
        or any(
            not isinstance(item, str)
            or re.fullmatch(r"dmt_[0-9a-f]{24}", item) is None
            for item in value
        )
        or len(value) != len(set(value))
    ):
        raise DramaMediaTaskError("media task dependency list is invalid")
    return sorted(value)


def _requires_backend_binding(task: DramaMediaTask) -> bool:
    return task.media_kind in PROVIDER_BACKED_MEDIA_KINDS


def _backend_binding_status(
    task: DramaMediaTask,
    *,
    bound: bool,
) -> str:
    if not _requires_backend_binding(task):
        return "not_applicable"
    return "frozen" if bound else "legacy_unbound"


def _clock_ms() -> int:
    return time.time_ns() // 1_000_000


def media_task_ledger_path(
    workspace: str,
    *,
    episode_no: int = 1,
) -> Path:
    number = normalize_episode_no(episode_no)
    root = paths.workspace_root(workspace)
    result = (
        root
        / "outputs"
        / "drama"
        / "media_tasks"
        / f"episode_{number:03d}.tasks.json"
    )
    if result.parent.parent.parent.parent != root:
        raise DramaMediaTaskError("media task ledger path is invalid")
    return result


def _task_dedupe_payload(
    *,
    episode_no: int,
    media_kind: DramaMediaKind,
    stage: DramaMediaStage,
    subject_id: str,
    input_fingerprint: str,
    backend_id: str,
    provider_fingerprint: str,
    model_fingerprint: str,
    account_fingerprint: str,
    endpoint_fingerprint: str,
    dependency_task_ids: Sequence[str],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "episode_no": episode_no,
        "media_kind": media_kind,
        "stage": stage,
        "subject_id": subject_id,
        "input_fingerprint": input_fingerprint,
        "backend_id": backend_id,
        "provider_fingerprint": provider_fingerprint,
        "model_fingerprint": model_fingerprint,
        "account_fingerprint": account_fingerprint,
        "endpoint_fingerprint": endpoint_fingerprint,
        "dependency_task_ids": list(dependency_task_ids),
    }


def _build_task(
    *,
    episode_no: int,
    media_kind: DramaMediaKind,
    stage: DramaMediaStage,
    subject_id: str,
    input_fingerprint: str,
    backend_id: str,
    provider_fingerprint: str,
    model_fingerprint: str,
    account_fingerprint: str,
    endpoint_fingerprint: str,
    dependency_task_ids: Sequence[str],
    attempt_no: int,
    state: DramaMediaTaskState,
    revision: int,
    created_at_ms: int,
    updated_at_ms: int,
    result_fingerprint: str | None = None,
    outcome_code: str | None = None,
) -> DramaMediaTask:
    canonical_dependencies = _canonical_dependency_task_ids(
        dependency_task_ids
    )
    dedupe_payload = _task_dedupe_payload(
        episode_no=episode_no,
        media_kind=media_kind,
        stage=stage,
        subject_id=subject_id,
        input_fingerprint=input_fingerprint,
        backend_id=backend_id,
        provider_fingerprint=provider_fingerprint,
        model_fingerprint=model_fingerprint,
        account_fingerprint=account_fingerprint,
        endpoint_fingerprint=endpoint_fingerprint,
        dependency_task_ids=canonical_dependencies,
    )
    dedupe_key = _canonical_sha256(dedupe_payload)
    task_payload = {
        **dedupe_payload,
        "attempt_no": attempt_no,
    }
    task_id = f"dmt_{_canonical_sha256(task_payload)[:24]}"
    payload = {
        **dedupe_payload,
        "task_id": task_id,
        "dedupe_key": dedupe_key,
        "attempt_no": attempt_no,
        "state": state,
        "revision": revision,
        "created_at_ms": created_at_ms,
        "updated_at_ms": updated_at_ms,
        "result_fingerprint": result_fingerprint,
        "outcome_code": outcome_code,
    }
    payload["record_fingerprint"] = _canonical_sha256(payload)
    try:
        return DramaMediaTask(**payload)
    except (RecursionError, TypeError, ValueError):
        raise DramaMediaTaskError("media task input is invalid") from None


def _replace_task(
    task: DramaMediaTask,
    *,
    state: DramaMediaTaskState,
    now_ms: int,
    result_fingerprint: str | None = None,
    outcome_code: str | None = None,
) -> DramaMediaTask:
    return _build_task(
        episode_no=task.episode_no,
        media_kind=task.media_kind,
        stage=task.stage,
        subject_id=task.subject_id,
        input_fingerprint=task.input_fingerprint,
        backend_id=task.backend_id,
        provider_fingerprint=task.provider_fingerprint,
        model_fingerprint=task.model_fingerprint,
        account_fingerprint=task.account_fingerprint,
        endpoint_fingerprint=task.endpoint_fingerprint,
        dependency_task_ids=task.dependency_task_ids,
        attempt_no=task.attempt_no,
        state=state,
        revision=task.revision + 1,
        created_at_ms=task.created_at_ms,
        updated_at_ms=now_ms,
        result_fingerprint=result_fingerprint,
        outcome_code=outcome_code,
    )


def _media_lane_key(task: DramaMediaTask) -> str:
    return _canonical_sha256(
        {
            "schema_version": 1,
            "provider_fingerprint": task.provider_fingerprint,
            "media_kind": task.media_kind,
        }
    )


def _build_worker_lease(
    *,
    task: DramaMediaTask,
    worker_fingerprint: str,
    lease_token_fingerprint: str,
    lane_capacity: int,
    lease_revision: int,
    claimed_at_ms: int,
    heartbeat_at_ms: int,
    expires_at_ms: int,
) -> DramaMediaWorkerLease:
    payload = {
        "schema_version": 1,
        "task_id": task.task_id,
        "task_revision": task.revision,
        "worker_fingerprint": worker_fingerprint,
        "lease_token_fingerprint": lease_token_fingerprint,
        "lane_key": _media_lane_key(task),
        "lane_capacity": lane_capacity,
        "lease_revision": lease_revision,
        "claimed_at_ms": claimed_at_ms,
        "heartbeat_at_ms": heartbeat_at_ms,
        "expires_at_ms": expires_at_ms,
    }
    payload["record_fingerprint"] = _canonical_sha256(payload)
    try:
        return DramaMediaWorkerLease(**payload)
    except (RecursionError, TypeError, ValueError):
        raise DramaMediaTaskError("media worker lease input is invalid") from None


def _lease_with_task_revision(
    lease: DramaMediaWorkerLease,
    task: DramaMediaTask,
) -> DramaMediaWorkerLease:
    return _build_worker_lease(
        task=task,
        worker_fingerprint=lease.worker_fingerprint,
        lease_token_fingerprint=lease.lease_token_fingerprint,
        lane_capacity=lease.lane_capacity,
        lease_revision=lease.lease_revision,
        claimed_at_ms=lease.claimed_at_ms,
        heartbeat_at_ms=lease.heartbeat_at_ms,
        expires_at_ms=lease.expires_at_ms,
    )


def _build_transition_receipt(
    *,
    before: DramaMediaTask,
    transitioned: DramaMediaTask,
    lease: DramaMediaWorkerLease,
    before_ledger_fingerprint: str,
    transitioned_at_ms: int,
) -> DramaMediaWorkerTransitionReceipt:
    payload = {
        "schema_version": 1,
        "task_id": before.task_id,
        "from_task_revision": before.revision,
        "to_task_revision": transitioned.revision,
        "from_state": before.state,
        "to_state": transitioned.state,
        "worker_fingerprint": lease.worker_fingerprint,
        "lease_token_fingerprint": lease.lease_token_fingerprint,
        "lease_revision": lease.lease_revision,
        "transitioned_at_ms": transitioned_at_ms,
        "before_ledger_fingerprint": before_ledger_fingerprint,
        "result_fingerprint": transitioned.result_fingerprint,
        "outcome_code": transitioned.outcome_code,
        "transitioned_task_fingerprint": transitioned.record_fingerprint,
    }
    payload["record_fingerprint"] = _canonical_sha256(payload)
    try:
        return DramaMediaWorkerTransitionReceipt(**payload)
    except (RecursionError, TypeError, ValueError):
        raise DramaMediaTaskError(
            "media worker transition receipt is invalid"
        ) from None


def _build_ledger(
    episode_no: int,
    tasks: Sequence[DramaMediaTask],
    *,
    revision: int,
    leases: Sequence[DramaMediaWorkerLease] = (),
    release_receipts: Sequence[DramaMediaWorkerReleaseReceipt] = (),
    transition_receipts: Sequence[DramaMediaWorkerTransitionReceipt] = (),
    backend_bindings: Sequence[DramaMediaBackendBinding] = (),
) -> DramaMediaTaskLedgerV3:
    payload = {
        "schema_version": 3,
        "episode_no": episode_no,
        "revision": revision,
        "tasks": [
            model_to_dict(item)
            for item in sorted(tasks, key=lambda item: item.task_id)
        ],
        "leases": [
            model_to_dict(item)
            for item in sorted(leases, key=lambda item: item.task_id)
        ],
        "release_receipts": [
            model_to_dict(item)
            for item in sorted(
                release_receipts, key=lambda item: item.task_id
            )
        ],
        "transition_receipts": [
            model_to_dict(item)
            for item in sorted(
                transition_receipts, key=lambda item: item.task_id
            )
        ],
        "backend_bindings": [
            item.model_dump(mode="json")
            for item in sorted(
                backend_bindings, key=lambda item: item.task_id
            )
        ],
    }
    payload["ledger_fingerprint"] = _canonical_sha256(payload)
    try:
        return DramaMediaTaskLedgerV3(**payload)
    except (RecursionError, TypeError, ValueError):
        raise DramaMediaTaskError("media task DAG is invalid") from None


def _empty_ledger(episode_no: int) -> DramaMediaTaskLedgerV3:
    return _build_ledger(episode_no, (), revision=0)


def _ledger_bytes(
    ledger: DramaMediaTaskLedger
    | DramaMediaTaskLedgerV2
    | DramaMediaTaskLedgerV3,
) -> bytes:
    return (
        json.dumps(
            {
                "schema_version": 1,
                "artifact_type": "drama_media_task_ledger",
                "ledger_fingerprint": ledger.ledger_fingerprint,
                "ledger": model_to_dict(ledger),
            },
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _read_ledger(
    workspace: str,
    *,
    episode_no: int,
) -> DramaMediaTaskLedgerV3:
    number = normalize_episode_no(episode_no)
    root = paths.workspace_root(workspace)
    _validate_render_workspace_root(root)
    try:
        metadata = _read_strict_workspace_json(
            root,
            root / "data" / "workspace.json",
            maximum=MAX_WORKSPACE_METADATA_BYTES,
        )
    except (FileNotFoundError, OSError, RecursionError, TypeError, ValueError):
        raise DramaMediaTaskError("media task workspace metadata is invalid") from None
    if (
        not isinstance(metadata, dict)
        or set(metadata) != {"type", "created_at", "schema_version"}
        or metadata.get("type") != "drama"
        or type(metadata.get("schema_version")) is not int
        or metadata.get("schema_version") != 1
        or (
            metadata.get("created_at") is not None
            and not isinstance(metadata.get("created_at"), str)
        )
    ):
        raise DramaMediaTaskError("media task workspace is not a drama workspace")
    path = media_task_ledger_path(workspace, episode_no=number)
    try:
        raw = _read_strict_workspace_bytes(
            root, path, maximum=MAX_MEDIA_TASK_LEDGER_BYTES
        )
        payload = _read_strict_workspace_json(
            root, path, maximum=MAX_MEDIA_TASK_LEDGER_BYTES
        )
        if (
            not isinstance(payload, dict)
            or set(payload)
            != {
                "schema_version",
                "artifact_type",
                "ledger_fingerprint",
                "ledger",
            }
            or payload.get("schema_version") != 1
            or payload.get("artifact_type") != "drama_media_task_ledger"
            or not isinstance(payload.get("ledger"), dict)
        ):
            raise ValueError("invalid media task envelope")
        ledger_payload = payload["ledger"]
        if ledger_payload.get("schema_version") == 1:
            legacy = DramaMediaTaskLedger(**ledger_payload)
            if (
                legacy.episode_no != number
                or payload["ledger_fingerprint"] != legacy.ledger_fingerprint
                or raw != _ledger_bytes(legacy)
            ):
                raise ValueError("legacy media task ledger identity mismatch")
            if any(
                task.state in LEASED_MEDIA_TASK_STATES
                for task in legacy.tasks
            ):
                raise DramaMediaTaskError(
                    "legacy active media task requires reconciliation"
                )
            return _build_ledger(
                number,
                legacy.tasks,
                revision=legacy.revision,
                leases=(),
                release_receipts=(),
                transition_receipts=(),
            )
        if ledger_payload.get("schema_version") == 2:
            legacy_v2 = DramaMediaTaskLedgerV2(**ledger_payload)
            if (
                legacy_v2.episode_no != number
                or payload["ledger_fingerprint"]
                != legacy_v2.ledger_fingerprint
                or raw != _ledger_bytes(legacy_v2)
            ):
                raise ValueError("media task ledger identity mismatch")
            return _build_ledger(
                number,
                legacy_v2.tasks,
                revision=legacy_v2.revision,
                leases=legacy_v2.leases,
                release_receipts=legacy_v2.release_receipts,
                transition_receipts=legacy_v2.transition_receipts,
                backend_bindings=(),
            )
        ledger = DramaMediaTaskLedgerV3(**ledger_payload)
        if (
            ledger.episode_no != number
            or payload["ledger_fingerprint"] != ledger.ledger_fingerprint
            or raw != _ledger_bytes(ledger)
        ):
            raise ValueError("media task ledger identity mismatch")
        return ledger
    except FileNotFoundError:
        raise
    except DramaMediaTaskError:
        raise
    except (OSError, RecursionError, TypeError, ValueError):
        raise DramaMediaTaskError("media task ledger is invalid") from None


def _target_token(root: Path, path: Path) -> tuple[Any, ...]:
    try:
        data = _read_strict_workspace_bytes(
            root, path, maximum=MAX_MEDIA_TASK_LEDGER_BYTES
        )
    except FileNotFoundError:
        return ("missing",)
    except (OSError, ValueError):
        return ("invalid",)
    return ("file", len(data), hashlib.sha256(data).hexdigest())


def _write_ledger(
    workspace: str,
    ledger: DramaMediaTaskLedgerV3,
    *,
    expected_target_token: tuple[Any, ...],
) -> None:
    root = paths.workspace_root(workspace)
    _validate_render_workspace_root(root)
    target = media_task_ledger_path(workspace, episode_no=ledger.episode_no)
    relative = target.relative_to(root)
    directory = str(relative.parent)
    directory_fd: int | None = None
    try:
        directory_fd = drama_edit_export._open_output_directory(
            root, directory, create=True
        )
        identity = drama_edit_export._directory_identity(directory_fd)
        if (
            drama_edit_export._target_token_at(
                directory_fd,
                relative.name,
                maximum=MAX_MEDIA_TASK_LEDGER_BYTES,
            )
            != expected_target_token
        ):
            raise DramaMediaTaskError("media task ledger changed concurrently")
        drama_edit_export._atomic_write_at(
            directory_fd,
            relative.name,
            _ledger_bytes(ledger),
            maximum=MAX_MEDIA_TASK_LEDGER_BYTES,
        )
        drama_edit_export._require_current_output_directory(
            root, directory, expected=identity
        )
    except DramaMediaTaskError:
        raise
    except (OSError, drama_edit_export.DramaEditExportError):
        raise DramaMediaTaskError(
            "media task ledger could not be committed safely"
        ) from None
    finally:
        if directory_fd is not None:
            os.close(directory_fd)


def _persist_ledger(
    workspace: str,
    ledger: DramaMediaTaskLedgerV3,
    *,
    expected_target_token: tuple[Any, ...],
) -> DramaMediaTaskLedgerV3:
    _write_ledger(
        workspace, ledger, expected_target_token=expected_target_token
    )
    persisted = _read_ledger(workspace, episode_no=ledger.episode_no)
    if persisted != ledger:
        raise DramaMediaTaskError("media task ledger persistence failed")
    return persisted


def load_media_task_ledger(
    workspace: str,
    *,
    episode_no: int = 1,
) -> DramaMediaTaskLedgerV3:
    try:
        return _read_ledger(
            workspace, episode_no=normalize_episode_no(episode_no)
        )
    except FileNotFoundError:
        raise
    except DramaMediaTaskError:
        raise
    except (OSError, RecursionError, TypeError, ValueError):
        raise DramaMediaTaskError("media task ledger could not be loaded") from None


def _validate_expected_ledger(
    ledger: DramaMediaTaskLedgerV3,
    expected_ledger_fingerprint: str | None,
    *,
    missing: bool,
) -> None:
    expected = None if missing else ledger.ledger_fingerprint
    if expected_ledger_fingerprint != expected:
        raise DramaMediaTaskError("media task ledger changed; refresh")


def _validate_mutation_cas(
    *,
    task_id: str,
    expected_task_revision: int,
    expected_ledger_fingerprint: str,
    now_ms: int,
) -> None:
    if (
        not isinstance(task_id, str)
        or re.fullmatch(r"dmt_[0-9a-f]{24}", task_id) is None
    ):
        raise DramaMediaTaskError("media task identity is invalid")
    if (
        not isinstance(expected_task_revision, int)
        or isinstance(expected_task_revision, bool)
        or expected_task_revision < 0
        or expected_task_revision > 10_000
    ):
        raise DramaMediaTaskError("media task revision is invalid")
    if (
        not isinstance(expected_ledger_fingerprint, str)
        or re.fullmatch(r"[0-9a-f]{64}", expected_ledger_fingerprint) is None
    ):
        raise DramaMediaTaskError("media task ledger identity is invalid")
    if (
        not isinstance(now_ms, int)
        or isinstance(now_ms, bool)
        or now_ms < 0
        or now_ms > 9_999_999_999_999
    ):
        raise DramaMediaTaskError("media task update time is invalid")


def create_media_task(
    workspace: str,
    *,
    episode_no: int,
    media_kind: DramaMediaKind,
    stage: DramaMediaStage,
    subject_id: str,
    input_fingerprint: str,
    backend_id: str,
    provider_fingerprint: str,
    model_fingerprint: str,
    account_fingerprint: str,
    endpoint_fingerprint: str,
    dependency_task_ids: Sequence[str] = (),
    attempt_no: int = 1,
    now_ms: int,
    expected_ledger_fingerprint: str | None,
) -> DramaMediaTask:
    """Create or exact-replay one task; active dedupe never mutates old input."""

    try:
        number = normalize_episode_no(episode_no)
        dependencies = _canonical_dependency_task_ids(
            dependency_task_ids
        )
        if media_kind in PROVIDER_BACKED_MEDIA_KINDS:
            raise DramaMediaTaskError(
                "provider media task requires a frozen backend binding"
            )
        with use_workspace(workspace), acquire_write_lock(
            source="drama-media-task-create"
        ):
            root = paths.workspace_root(workspace)
            path = media_task_ledger_path(workspace, episode_no=number)
            token = _target_token(root, path)
            try:
                ledger = _read_ledger(workspace, episode_no=number)
                missing = False
            except FileNotFoundError:
                ledger = _empty_ledger(number)
                missing = True
            by_id = {item.task_id: item for item in ledger.tasks}
            if any(item not in by_id for item in dependencies):
                raise DramaMediaTaskError("media task dependency is missing")
            if any(now_ms < by_id[item].created_at_ms for item in dependencies):
                raise DramaMediaTaskError(
                    "media task creation time is invalid"
                )
            ready = all(by_id[item].state == "succeeded" for item in dependencies)
            proposed = _build_task(
                episode_no=number,
                media_kind=media_kind,
                stage=stage,
                subject_id=subject_id,
                input_fingerprint=input_fingerprint,
                backend_id=backend_id,
                provider_fingerprint=provider_fingerprint,
                model_fingerprint=model_fingerprint,
                account_fingerprint=account_fingerprint,
                endpoint_fingerprint=endpoint_fingerprint,
                dependency_task_ids=dependencies,
                attempt_no=attempt_no,
                state="ready" if ready else "planned",
                revision=0,
                created_at_ms=now_ms,
                updated_at_ms=now_ms,
            )
            existing = by_id.get(proposed.task_id)
            if existing is not None:
                if existing.dedupe_key != proposed.dedupe_key:
                    raise DramaMediaTaskError("media task identity collision")
                return existing
            if any(
                by_id[item].state
                in {"failed", "cancelled", "cancelling", "submission_unknown"}
                for item in dependencies
            ):
                raise DramaMediaTaskError(
                    "media task dependency cannot reach success"
                )
            _validate_expected_ledger(
                ledger,
                expected_ledger_fingerprint,
                missing=missing,
            )
            active = next(
                (
                    item
                    for item in ledger.tasks
                    if item.dedupe_key == proposed.dedupe_key
                    and item.state in ACTIVE_MEDIA_TASK_STATES
                ),
                None,
            )
            if active is not None:
                return active
            updated = _build_ledger(
                number,
                [*ledger.tasks, proposed],
                revision=ledger.revision + 1,
                leases=ledger.leases,
                release_receipts=ledger.release_receipts,
                transition_receipts=ledger.transition_receipts,
                backend_bindings=ledger.backend_bindings,
            )
            _persist_ledger(
                workspace, updated, expected_target_token=token
            )
            return proposed
    except WorkspaceLocked:
        raise DramaMediaTaskError("media task workspace is busy") from None
    except DramaMediaTaskError:
        raise
    except (OSError, RecursionError, TypeError, ValueError):
        raise DramaMediaTaskError("media task creation was rejected") from None


def enqueue_bound_media_task(
    workspace: str,
    *,
    episode_no: int,
    media_kind: DramaMediaKind,
    stage: DramaMediaStage,
    subject_id: str,
    input_fingerprint: str,
    backend_id: str,
    provider_id: str,
    model_id: str,
    provider_fingerprint: str,
    model_fingerprint: str,
    account_fingerprint: str,
    endpoint_fingerprint: str,
    registry: DramaMediaBackendRegistrySnapshot,
    dependency_task_ids: Sequence[str] = (),
    attempt_no: int = 1,
    now_ms: int,
    expected_ledger_fingerprint: str | None,
) -> tuple[DramaMediaTask, DramaMediaBackendBinding]:
    """Atomically persist one task and its immutable G3 backend binding."""

    try:
        number = normalize_episode_no(episode_no)
        dependencies = _canonical_dependency_task_ids(
            dependency_task_ids
        )
        if media_kind not in PROVIDER_BACKED_MEDIA_KINDS:
            raise DramaMediaTaskError(
                "local media task does not use a provider backend binding"
            )
        if not isinstance(registry, DramaMediaBackendRegistrySnapshot):
            raise DramaMediaTaskError("media backend registry is invalid")
        with use_workspace(workspace), acquire_write_lock(
            source="drama-media-task-bound-enqueue"
        ):
            root = paths.workspace_root(workspace)
            path = media_task_ledger_path(workspace, episode_no=number)
            token = _target_token(root, path)
            try:
                ledger = _read_ledger(workspace, episode_no=number)
                missing = False
            except FileNotFoundError:
                ledger = _empty_ledger(number)
                missing = True
            by_id = {item.task_id: item for item in ledger.tasks}
            bindings = {
                item.task_id: item for item in ledger.backend_bindings
            }
            if any(item not in by_id for item in dependencies):
                raise DramaMediaTaskError("media task dependency is missing")
            if any(now_ms < by_id[item].created_at_ms for item in dependencies):
                raise DramaMediaTaskError("media task creation time is invalid")
            ready = all(by_id[item].state == "succeeded" for item in dependencies)
            proposed = _build_task(
                episode_no=number,
                media_kind=media_kind,
                stage=stage,
                subject_id=subject_id,
                input_fingerprint=input_fingerprint,
                backend_id=backend_id,
                provider_fingerprint=provider_fingerprint,
                model_fingerprint=model_fingerprint,
                account_fingerprint=account_fingerprint,
                endpoint_fingerprint=endpoint_fingerprint,
                dependency_task_ids=dependencies,
                attempt_no=attempt_no,
                state="ready" if ready else "planned",
                revision=0,
                created_at_ms=now_ms,
                updated_at_ms=now_ms,
            )

            def existing_binding(
                task: DramaMediaTask,
            ) -> DramaMediaBackendBinding:
                binding = bindings.get(task.task_id)
                if binding is None:
                    raise DramaMediaTaskError(
                        "legacy unbound media task requires reconciliation"
                    )
                if (
                    binding.provider_id != provider_id
                    or binding.model_id != model_id
                    or binding.backend_id != backend_id
                    or binding.provider_fingerprint != provider_fingerprint
                    or binding.model_fingerprint != model_fingerprint
                ):
                    raise DramaMediaTaskError(
                        "frozen media backend binding changed"
                    )
                return binding

            existing = by_id.get(proposed.task_id)
            if existing is not None:
                if existing.dedupe_key != proposed.dedupe_key:
                    raise DramaMediaTaskError("media task identity collision")
                return existing, existing_binding(existing)
            if any(
                by_id[item].state
                in {"failed", "cancelled", "cancelling", "submission_unknown"}
                for item in dependencies
            ):
                raise DramaMediaTaskError(
                    "media task dependency cannot reach success"
                )
            _validate_expected_ledger(
                ledger,
                expected_ledger_fingerprint,
                missing=missing,
            )
            active = next(
                (
                    item
                    for item in ledger.tasks
                    if item.dedupe_key == proposed.dedupe_key
                    and item.state in ACTIVE_MEDIA_TASK_STATES
                ),
                None,
            )
            if active is not None:
                return active, existing_binding(active)
            binding = resolve_task_backend(
                registry,
                proposed,
                provider_id=provider_id,
                model_id=model_id,
                provider_fingerprint=provider_fingerprint,
                model_fingerprint=model_fingerprint,
            )
            updated = _build_ledger(
                number,
                [*ledger.tasks, proposed],
                revision=ledger.revision + 1,
                leases=ledger.leases,
                release_receipts=ledger.release_receipts,
                transition_receipts=ledger.transition_receipts,
                backend_bindings=[*ledger.backend_bindings, binding],
            )
            _persist_ledger(
                workspace, updated, expected_target_token=token
            )
            return proposed, binding
    except WorkspaceLocked:
        raise DramaMediaTaskError("media task workspace is busy") from None
    except (DramaMediaTaskError, DramaMediaBackendError):
        raise
    except (OSError, RecursionError, TypeError, ValueError):
        raise DramaMediaTaskError(
            "bound media task enqueue was rejected"
        ) from None


def _transition_outcome(
    target_state: DramaMediaTaskState,
    *,
    result_fingerprint: str | None,
    outcome_code: DramaMediaTaskOutcomeCode | None,
) -> tuple[str | None, DramaMediaTaskOutcomeCode | None]:
    if target_state == "succeeded":
        if result_fingerprint is None or outcome_code is not None:
            raise DramaMediaTaskError("media task success result is invalid")
        return result_fingerprint, None
    if target_state == "submission_unknown":
        if result_fingerprint is not None or outcome_code != "transport_unknown":
            raise DramaMediaTaskError("media task unknown outcome is invalid")
        return None, outcome_code
    if target_state == "cancelled":
        if result_fingerprint is not None or outcome_code != "cancel_confirmed":
            raise DramaMediaTaskError("media task cancellation outcome is invalid")
        return None, outcome_code
    if target_state == "failed":
        if (
            result_fingerprint is not None
            or outcome_code is None
            or outcome_code in {"transport_unknown", "cancel_confirmed"}
        ):
            raise DramaMediaTaskError("media task outcome is invalid")
        return None, outcome_code
    if result_fingerprint is not None or outcome_code is not None:
        raise DramaMediaTaskError("active media task outcome is invalid")
    return None, None


def _refresh_ready_tasks(
    tasks: Sequence[DramaMediaTask],
    *,
    now_ms: int,
) -> list[DramaMediaTask]:
    by_id = {item.task_id: item for item in tasks}
    refreshed: list[DramaMediaTask] = []
    for task in tasks:
        if task.state == "planned" and all(
            by_id[item].state == "succeeded"
            for item in task.dependency_task_ids
        ):
            refreshed.append(
                _replace_task(
                    task,
                    state="ready",
                    now_ms=max(now_ms, task.updated_at_ms),
                )
            )
        else:
            refreshed.append(task)
    return refreshed


def _fail_blocked_dependents(
    tasks: Sequence[DramaMediaTask],
    *,
    now_ms: int,
) -> list[DramaMediaTask]:
    """Fail planned descendants whose immutable dependency task has failed."""

    current = list(tasks)
    while True:
        by_id = {item.task_id: item for item in current}
        changed = False
        updated: list[DramaMediaTask] = []
        for task in current:
            if task.state == "planned" and any(
                by_id[item].state == "failed"
                for item in task.dependency_task_ids
            ):
                updated.append(
                    _replace_task(
                        task,
                        state="failed",
                        now_ms=max(now_ms, task.updated_at_ms),
                        outcome_code="dependency_failed",
                    )
                )
                changed = True
            else:
                updated.append(task)
        current = updated
        if not changed:
            return current


def _dependent_closure(
    tasks: Sequence[DramaMediaTask],
    task_id: str,
) -> set[str]:
    affected = {task_id}
    changed = True
    while changed:
        before = len(affected)
        affected.update(
            item.task_id
            for item in tasks
            if any(dep in affected for dep in item.dependency_task_ids)
        )
        changed = len(affected) != before
    return affected


def transition_media_task(
    workspace: str,
    *,
    episode_no: int,
    task_id: str,
    target_state: DramaMediaTaskState,
    expected_task_revision: int,
    expected_ledger_fingerprint: str,
    worker_fingerprint: str | None = None,
    lease_token_fingerprint: str | None = None,
    expected_lease_revision: int | None = None,
    result_fingerprint: str | None = None,
    outcome_code: DramaMediaTaskOutcomeCode | None = None,
) -> DramaMediaTask:
    """Transition one task; leased execution states require current ownership."""

    try:
        number = normalize_episode_no(episode_no)
        _validate_mutation_cas(
            task_id=task_id,
            expected_task_revision=expected_task_revision,
            expected_ledger_fingerprint=expected_ledger_fingerprint,
            now_ms=0,
        )
        result, outcome = _transition_outcome(
            target_state,
            result_fingerprint=result_fingerprint,
            outcome_code=outcome_code,
        )
        if target_state == "claimed":
            raise DramaMediaTaskError(
                "media task claim requires the worker lease API"
            )
        with use_workspace(workspace), acquire_write_lock(
            source="drama-media-task-transition"
        ):
            root = paths.workspace_root(workspace)
            path = media_task_ledger_path(workspace, episode_no=number)
            token = _target_token(root, path)
            ledger = _read_ledger(workspace, episode_no=number)
            by_id = {item.task_id: item for item in ledger.tasks}
            current = by_id.get(task_id)
            if current is None:
                raise DramaMediaTaskError("media task is missing")
            if (
                _requires_backend_binding(current)
                and current.state in LEASED_MEDIA_TASK_STATES
                and not any(
                item.task_id == current.task_id
                for item in ledger.backend_bindings
                )
            ):
                raise DramaMediaTaskError(
                    "media task has no frozen backend binding"
                )
            transition_receipt = next(
                (
                    item
                    for item in ledger.transition_receipts
                    if item.task_id == task_id
                ),
                None,
            )
            authenticated_replay = (
                transition_receipt is not None
                and current.state == target_state
                and current.result_fingerprint == result
                and current.outcome_code == outcome
                and transition_receipt.from_task_revision
                == expected_task_revision
                and transition_receipt.to_task_revision == current.revision
                and transition_receipt.worker_fingerprint
                == worker_fingerprint
                and transition_receipt.lease_token_fingerprint
                == lease_token_fingerprint
                and transition_receipt.lease_revision
                == expected_lease_revision
                and transition_receipt.before_ledger_fingerprint
                == expected_ledger_fingerprint
                and transition_receipt.transitioned_task_fingerprint
                == current.record_fingerprint
            )
            if current.revision != expected_task_revision:
                if authenticated_replay:
                    if current.state in LEASED_MEDIA_TASK_STATES:
                        replay_lease = next(
                            (
                                item
                                for item in ledger.leases
                                if item.task_id == current.task_id
                            ),
                            None,
                        )
                        replay_now = _clock_ms()
                        if (
                            replay_lease is None
                            or replay_lease.worker_fingerprint
                            != worker_fingerprint
                            or replay_lease.lease_token_fingerprint
                            != lease_token_fingerprint
                            or replay_lease.lease_revision
                            != expected_lease_revision
                            or replay_lease.task_revision != current.revision
                            or not isinstance(replay_now, int)
                            or isinstance(replay_now, bool)
                            or replay_now < 0
                            or replay_now > 9_999_999_999_999
                            or replay_now >= replay_lease.expires_at_ms
                        ):
                            raise DramaMediaTaskError(
                                "media task worker replay is expired"
                            )
                    return current
                raise DramaMediaTaskError("media task changed; refresh")
            if ledger.ledger_fingerprint != expected_ledger_fingerprint:
                raise DramaMediaTaskError("media task ledger changed; refresh")
            if current.state == target_state:
                if (
                    transition_receipt is None
                    and current.result_fingerprint == result
                    and current.outcome_code == outcome
                    and current.state not in LEASED_MEDIA_TASK_STATES
                ):
                    return current
                raise DramaMediaTaskError("media task replay does not match")
            if target_state not in _TRANSITIONS[current.state]:
                raise DramaMediaTaskError("media task transition is invalid")
            now_ms = _clock_ms()
            if (
                not isinstance(now_ms, int)
                or isinstance(now_ms, bool)
                or now_ms < 0
                or now_ms > 9_999_999_999_999
            ):
                raise DramaMediaTaskError("media task clock is invalid")
            current_lease = None
            if current.state in LEASED_MEDIA_TASK_STATES:
                current_lease = next(
                    (
                        item
                        for item in ledger.leases
                        if item.task_id == current.task_id
                    ),
                    None,
                )
                if (
                    current_lease is None
                    or not isinstance(worker_fingerprint, str)
                    or re.fullmatch(r"[0-9a-f]{64}", worker_fingerprint)
                    is None
                    or not isinstance(lease_token_fingerprint, str)
                    or re.fullmatch(
                        r"[0-9a-f]{64}", lease_token_fingerprint
                    )
                    is None
                    or not isinstance(expected_lease_revision, int)
                    or isinstance(expected_lease_revision, bool)
                    or expected_lease_revision < 0
                    or expected_lease_revision > 10_000
                ):
                    raise DramaMediaTaskError(
                        "media task worker ownership is required"
                    )
                if (
                    current_lease.worker_fingerprint != worker_fingerprint
                    or current_lease.lease_token_fingerprint
                    != lease_token_fingerprint
                    or current_lease.lease_revision != expected_lease_revision
                    or current_lease.task_revision != current.revision
                ):
                    raise DramaMediaTaskError(
                        "media task worker ownership changed; refresh"
                    )
                if now_ms >= current_lease.expires_at_ms:
                    raise DramaMediaTaskError(
                        "media task worker lease is expired"
                    )
            if now_ms < current.updated_at_ms:
                raise DramaMediaTaskError("media task update time is invalid")
            if target_state == "ready" and any(
                by_id[item].state != "succeeded"
                for item in current.dependency_task_ids
            ):
                raise DramaMediaTaskError("media task dependencies are incomplete")
            replacement = _replace_task(
                current,
                state=target_state,
                now_ms=now_ms,
                result_fingerprint=result,
                outcome_code=outcome,
            )
            tasks = [
                replacement if item.task_id == task_id else item
                for item in ledger.tasks
            ]
            if target_state == "succeeded":
                tasks = _refresh_ready_tasks(tasks, now_ms=now_ms)
            elif target_state == "failed":
                tasks = _fail_blocked_dependents(tasks, now_ms=now_ms)
            leases = []
            for lease in ledger.leases:
                if lease.task_id != task_id:
                    leases.append(lease)
                elif target_state in {
                    "claimed",
                    "submitting",
                    "submitted",
                    "polling",
                    "downloading",
                    "validating",
                }:
                    leases.append(_lease_with_task_revision(lease, replacement))
            updated = _build_ledger(
                number,
                tasks,
                revision=ledger.revision + 1,
                leases=leases,
                release_receipts=[
                    item
                    for item in ledger.release_receipts
                    if item.task_id != task_id
                ],
                transition_receipts=[
                    *[
                        item
                        for item in ledger.transition_receipts
                        if item.task_id != task_id
                    ],
                    *(
                        [
                            _build_transition_receipt(
                                before=current,
                                transitioned=replacement,
                                lease=current_lease,
                                before_ledger_fingerprint=(
                                    ledger.ledger_fingerprint
                                ),
                                transitioned_at_ms=now_ms,
                            )
                        ]
                        if current_lease is not None
                        else []
                    ),
                ],
                backend_bindings=ledger.backend_bindings,
            )
            _persist_ledger(
                workspace, updated, expected_target_token=token
            )
            return next(item for item in updated.tasks if item.task_id == task_id)
    except FileNotFoundError:
        raise DramaMediaTaskError("media task ledger is missing") from None
    except WorkspaceLocked:
        raise DramaMediaTaskError("media task workspace is busy") from None
    except DramaMediaTaskError:
        raise
    except (OSError, RecursionError, TypeError, ValueError):
        raise DramaMediaTaskError("media task transition was rejected") from None


def cancel_media_task_cascade(
    workspace: str,
    *,
    episode_no: int,
    task_id: str,
    expected_task_revision: int,
    expected_ledger_fingerprint: str,
    now_ms: int,
) -> list[DramaMediaTask]:
    """Move a task and its active transitive dependents to ``cancelling``."""

    try:
        number = normalize_episode_no(episode_no)
        _validate_mutation_cas(
            task_id=task_id,
            expected_task_revision=expected_task_revision,
            expected_ledger_fingerprint=expected_ledger_fingerprint,
            now_ms=now_ms,
        )
        with use_workspace(workspace), acquire_write_lock(
            source="drama-media-task-cancel"
        ):
            root = paths.workspace_root(workspace)
            path = media_task_ledger_path(workspace, episode_no=number)
            token = _target_token(root, path)
            ledger = _read_ledger(workspace, episode_no=number)
            by_id = {item.task_id: item for item in ledger.tasks}
            current = by_id.get(task_id)
            if current is None:
                raise DramaMediaTaskError("media task is missing")
            if current.revision != expected_task_revision:
                affected = _dependent_closure(ledger.tasks, task_id)
                replayable_states = (
                    TERMINAL_MEDIA_TASK_STATES
                    | {"cancelling", "submission_unknown"}
                )
                if (
                    current.revision > expected_task_revision
                    and current.state in {"cancelling", "cancelled"}
                    and all(
                        by_id[item_id].state in replayable_states
                        for item_id in affected
                    )
                ):
                    return [by_id[item] for item in sorted(affected)]
                raise DramaMediaTaskError("media task changed; refresh")
            if ledger.ledger_fingerprint != expected_ledger_fingerprint:
                raise DramaMediaTaskError("media task ledger changed; refresh")
            if current.state in {"succeeded", "failed"}:
                raise DramaMediaTaskError("terminal media task cannot be cancelled")
            if current.state == "cancelled":
                return [current]
            affected = _dependent_closure(ledger.tasks, task_id)
            replacements: dict[str, DramaMediaTask] = {}
            for item_id in sorted(affected):
                item = by_id[item_id]
                if item.state in TERMINAL_MEDIA_TASK_STATES:
                    continue
                if item.state == "submission_unknown":
                    continue
                if item.state == "cancelling":
                    replacements[item_id] = item
                    continue
                if now_ms < item.updated_at_ms:
                    raise DramaMediaTaskError("media task update time is invalid")
                replacements[item_id] = _replace_task(
                    item, state="cancelling", now_ms=now_ms
                )
            if not any(
                replacements[item_id] != by_id[item_id]
                for item_id in replacements
            ):
                return [by_id[item] for item in sorted(affected)]
            tasks = [
                replacements.get(item.task_id, item) for item in ledger.tasks
            ]
            leases = [
                item for item in ledger.leases if item.task_id not in affected
            ]
            updated = _build_ledger(
                number,
                tasks,
                revision=ledger.revision + 1,
                leases=leases,
                release_receipts=[
                    item
                    for item in ledger.release_receipts
                    if item.task_id not in affected
                ],
                transition_receipts=[
                    item
                    for item in ledger.transition_receipts
                    if item.task_id not in affected
                ],
                backend_bindings=ledger.backend_bindings,
            )
            _persist_ledger(
                workspace, updated, expected_target_token=token
            )
            updated_by_id = {item.task_id: item for item in updated.tasks}
            return [updated_by_id[item] for item in sorted(affected)]
    except FileNotFoundError:
        raise DramaMediaTaskError("media task ledger is missing") from None
    except WorkspaceLocked:
        raise DramaMediaTaskError("media task workspace is busy") from None
    except DramaMediaTaskError:
        raise
    except (OSError, RecursionError, TypeError, ValueError):
        raise DramaMediaTaskError("media task cancellation was rejected") from None


def build_media_task_projection(
    workspace: str,
    *,
    episode_no: int = 1,
) -> dict[str, Any]:
    """Return a bounded allowlist projection; missing storage is an empty DAG."""

    number = normalize_episode_no(episode_no)
    try:
        ledger = _read_ledger(workspace, episode_no=number)
    except FileNotFoundError:
        ledger = _empty_ledger(number)
    by_id = {item.task_id: item for item in ledger.tasks}
    bound_ids = {item.task_id for item in ledger.backend_bindings}
    tasks = []
    for item in ledger.tasks:
        blocked = [
            dependency_id
            for dependency_id in item.dependency_task_ids
            if by_id[dependency_id].state != "succeeded"
        ]
        tasks.append(
            {
                "task_id": item.task_id,
                "episode_no": item.episode_no,
                "media_kind": item.media_kind,
                "stage": item.stage,
                "subject_id": item.subject_id,
                "dependency_task_ids": list(item.dependency_task_ids),
                "blocked_dependency_ids": blocked,
                "state": item.state,
                "revision": item.revision,
                "created_at_ms": item.created_at_ms,
                "updated_at_ms": item.updated_at_ms,
                "result_fingerprint": item.result_fingerprint,
                "outcome_code": item.outcome_code,
                "backend_binding_status": (
                    _backend_binding_status(
                        item, bound=item.task_id in bound_ids
                    )
                ),
            }
        )
    counts = {
        state: sum(1 for item in ledger.tasks if item.state == state)
        for state in _TRANSITIONS
    }
    return {
        "schema_version": 1,
        "episode_no": number,
        "ledger_revision": ledger.revision,
        "ledger_fingerprint": ledger.ledger_fingerprint,
        "task_count": len(tasks),
        "state_counts": counts,
        "tasks": tasks,
    }
