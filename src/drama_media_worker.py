"""G2 persistent worker leases and workspace-wide media capacity lanes.

The worker layer owns only claim/heartbeat/release/takeover.  It performs no
provider operation and never reads or writes image/video/TTS paid evidence.
"""

from __future__ import annotations

import os
import re
import stat
import time
from pathlib import Path
from typing import Any

from . import paths
from .drama_media_tasks import (
    DramaMediaTaskError,
    _build_ledger,
    _build_worker_lease,
    _media_lane_key,
    _persist_ledger,
    _read_ledger,
    _replace_task,
    _target_token,
    media_task_ledger_path,
)
from .drama_schemas import (
    DramaMediaTask,
    DramaMediaTaskLedgerV2,
    DramaMediaWorkerLease,
    DramaMediaWorkerReleaseReceipt,
    _canonical_sha256,
    normalize_episode_no,
)
from .drama_store import _validate_render_workspace_root
from .web.workspace_ctx import use_workspace
from .workspace_lock import WorkspaceLocked, acquire_write_lock


MIN_LEASE_DURATION_MS = 1_000
MAX_LEASE_DURATION_MS = 3_600_000
MAX_EPISODE_LEDGERS = 1000
MAX_LEDGER_NAMESPACE_ENTRIES = 5000
_LEDGER_NAME_RE = re.compile(r"episode_([0-9]{3})\.tasks\.json")
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_LEASED_STATES = frozenset(
    {"claimed", "submitting", "submitted", "polling", "downloading", "validating"}
)


class DramaMediaWorkerError(ValueError):
    """Bounded worker error without owner, token, provider, or path details."""


def _clock_ms() -> int:
    return time.time_ns() // 1_000_000


def _trusted_now_ms() -> int:
    return _strict_int(
        _clock_ms(),
        label="clock",
        minimum=0,
        maximum=9_999_999_999_999,
    )


def _strict_int(
    value: Any,
    *,
    label: str,
    minimum: int,
    maximum: int,
) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < minimum
        or value > maximum
    ):
        raise DramaMediaWorkerError(f"media worker {label} is invalid")
    return value


def _validate_fingerprint(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise DramaMediaWorkerError(f"media worker {label} is invalid")
    return value


def _validate_claim_inputs(
    *,
    task_id: Any,
    worker_fingerprint: Any,
    lease_token_fingerprint: Any,
    expected_task_revision: Any,
    expected_ledger_fingerprint: Any,
    lease_duration_ms: Any,
    lane_capacity: Any,
) -> tuple[int, int, int]:
    if not isinstance(task_id, str) or re.fullmatch(r"dmt_[0-9a-f]{24}", task_id) is None:
        raise DramaMediaWorkerError("media worker task identity is invalid")
    _validate_fingerprint(worker_fingerprint, label="owner identity")
    _validate_fingerprint(lease_token_fingerprint, label="lease token")
    _validate_fingerprint(expected_ledger_fingerprint, label="ledger identity")
    revision = _strict_int(
        expected_task_revision,
        label="task revision",
        minimum=0,
        maximum=10_000,
    )
    duration = _strict_int(
        lease_duration_ms,
        label="lease duration",
        minimum=MIN_LEASE_DURATION_MS,
        maximum=MAX_LEASE_DURATION_MS,
    )
    capacity = _strict_int(
        lane_capacity,
        label="lane capacity",
        minimum=1,
        maximum=64,
    )
    return revision, duration, capacity


def _episode_numbers_with_ledgers(workspace: str) -> list[int]:
    root = paths.workspace_root(workspace)
    _validate_render_workspace_root(root)
    directory = root / "outputs" / "drama" / "media_tasks"
    try:
        info = directory.lstat()
    except FileNotFoundError:
        return []
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise DramaMediaWorkerError("media worker ledger namespace is invalid")
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory_flag = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory_flag is None:
        raise DramaMediaWorkerError("media worker strict scan is unavailable")
    fd: int | None = None
    try:
        fd = os.open(str(directory), os.O_RDONLY | directory_flag | nofollow)
        numbers = []
        entry_count = 0
        with os.scandir(fd) as entries:
            for entry in entries:
                entry_count += 1
                if entry_count > MAX_LEDGER_NAMESPACE_ENTRIES:
                    raise DramaMediaWorkerError(
                        "media worker ledger namespace is too large"
                    )
                match = _LEDGER_NAME_RE.fullmatch(entry.name)
                if match is not None:
                    numbers.append(int(match.group(1)))
    except OSError:
        raise DramaMediaWorkerError("media worker ledger scan failed") from None
    finally:
        if fd is not None:
            os.close(fd)
    numbers.sort()
    if len(numbers) > MAX_EPISODE_LEDGERS or len(numbers) != len(set(numbers)):
        raise DramaMediaWorkerError("media worker ledger scan is invalid")
    return numbers


def _workspace_ledgers(
    workspace: str,
    *,
    include_episode_no: int,
) -> list[DramaMediaTaskLedgerV2]:
    numbers = set(_episode_numbers_with_ledgers(workspace))
    numbers.add(include_episode_no)
    ledgers = []
    for number in sorted(numbers):
        try:
            ledgers.append(_read_ledger(workspace, episode_no=number))
        except FileNotFoundError:
            if number != include_episode_no:
                raise DramaMediaWorkerError(
                    "media worker ledger scan changed concurrently"
                ) from None
    return ledgers


def _require_lane_capacity(
    ledgers: list[DramaMediaTaskLedgerV2],
    *,
    lane_key: str,
    lane_capacity: int,
    now_ms: int,
    exclude_task_id: str | None = None,
) -> None:
    active = [
        lease
        for ledger in ledgers
        for lease in ledger.leases
        if lease.lane_key == lane_key
        and lease.expires_at_ms > now_ms
        and lease.task_id != exclude_task_id
    ]
    if any(lease.lane_capacity != lane_capacity for lease in active):
        raise DramaMediaWorkerError("media worker lane policy changed")
    if len(active) >= lane_capacity:
        raise DramaMediaWorkerError("media worker lane capacity is full")


def _task_and_lease(
    ledger: DramaMediaTaskLedgerV2,
    task_id: str,
) -> tuple[DramaMediaTask, DramaMediaWorkerLease | None]:
    task = next((item for item in ledger.tasks if item.task_id == task_id), None)
    if task is None:
        raise DramaMediaWorkerError("media worker task is missing")
    lease = next((item for item in ledger.leases if item.task_id == task_id), None)
    return task, lease


def _build_release_receipt(
    *,
    before: DramaMediaTask,
    released: DramaMediaTask,
    lease: DramaMediaWorkerLease,
    before_ledger_fingerprint: str,
    released_at_ms: int,
) -> DramaMediaWorkerReleaseReceipt:
    payload = {
        "schema_version": 1,
        "task_id": before.task_id,
        "from_task_revision": before.revision,
        "to_task_revision": released.revision,
        "worker_fingerprint": lease.worker_fingerprint,
        "lease_token_fingerprint": lease.lease_token_fingerprint,
        "lease_revision": lease.lease_revision,
        "released_at_ms": released_at_ms,
        "before_ledger_fingerprint": before_ledger_fingerprint,
        "released_task_fingerprint": released.record_fingerprint,
    }
    payload["record_fingerprint"] = _canonical_sha256(payload)
    try:
        return DramaMediaWorkerReleaseReceipt(**payload)
    except (RecursionError, TypeError, ValueError):
        raise DramaMediaWorkerError(
            "media worker release receipt is invalid"
        ) from None


def claim_media_task(
    workspace: str,
    *,
    episode_no: int,
    task_id: str,
    worker_fingerprint: str,
    lease_token_fingerprint: str,
    expected_task_revision: int,
    expected_ledger_fingerprint: str,
    lease_duration_ms: int,
    lane_capacity: int,
) -> DramaMediaWorkerLease:
    """Atomically claim one ready task without exceeding its workspace lane."""

    try:
        number = normalize_episode_no(episode_no)
        revision, duration, capacity = _validate_claim_inputs(
            task_id=task_id,
            worker_fingerprint=worker_fingerprint,
            lease_token_fingerprint=lease_token_fingerprint,
            expected_task_revision=expected_task_revision,
            expected_ledger_fingerprint=expected_ledger_fingerprint,
            lease_duration_ms=lease_duration_ms,
            lane_capacity=lane_capacity,
        )
        with use_workspace(workspace), acquire_write_lock(
            source="drama-media-worker-claim"
        ):
            root = paths.workspace_root(workspace)
            path = media_task_ledger_path(workspace, episode_no=number)
            token = _target_token(root, path)
            ledger = _read_ledger(workspace, episode_no=number)
            task, existing = _task_and_lease(ledger, task_id)
            if existing is not None:
                replay_now = _trusted_now_ms()
                if (
                    task.state == "claimed"
                    and task.revision == revision + 1
                    and existing.lease_revision == 0
                    and existing.worker_fingerprint == worker_fingerprint
                    and existing.lease_token_fingerprint == lease_token_fingerprint
                    and existing.expires_at_ms - existing.claimed_at_ms
                    == duration
                    and existing.lane_capacity == capacity
                    and existing.expires_at_ms > replay_now
                ):
                    return existing
                raise DramaMediaWorkerError("media worker task is already leased")
            if task.revision != revision:
                raise DramaMediaWorkerError("media worker task changed; refresh")
            if ledger.ledger_fingerprint != expected_ledger_fingerprint:
                raise DramaMediaWorkerError("media worker ledger changed; refresh")
            if task.state != "ready":
                raise DramaMediaWorkerError("media worker task is not claimable")
            now = _trusted_now_ms()
            if now < task.updated_at_ms or now + duration > 9_999_999_999_999:
                raise DramaMediaWorkerError(
                    "media worker claim time is invalid"
                )
            ledgers = _workspace_ledgers(
                workspace, include_episode_no=number
            )
            _require_lane_capacity(
                ledgers,
                lane_key=_media_lane_key(task),
                lane_capacity=capacity,
                now_ms=now,
            )
            claimed = _replace_task(task, state="claimed", now_ms=now)
            lease = _build_worker_lease(
                task=claimed,
                worker_fingerprint=worker_fingerprint,
                lease_token_fingerprint=lease_token_fingerprint,
                lane_capacity=capacity,
                lease_revision=0,
                claimed_at_ms=now,
                heartbeat_at_ms=now,
                expires_at_ms=now + duration,
            )
            updated = _build_ledger(
                number,
                [
                    claimed if item.task_id == task_id else item
                    for item in ledger.tasks
                ],
                revision=ledger.revision + 1,
                leases=[*ledger.leases, lease],
                release_receipts=[
                    item
                    for item in ledger.release_receipts
                    if item.task_id != task_id
                ],
                transition_receipts=[
                    item
                    for item in ledger.transition_receipts
                    if item.task_id != task_id
                ],
            )
            _persist_ledger(workspace, updated, expected_target_token=token)
            return lease
    except WorkspaceLocked:
        raise DramaMediaWorkerError("media worker workspace is busy") from None
    except (DramaMediaWorkerError, DramaMediaTaskError):
        raise
    except (OSError, RecursionError, TypeError, ValueError):
        raise DramaMediaWorkerError("media worker claim was rejected") from None


def heartbeat_media_task(
    workspace: str,
    *,
    episode_no: int,
    task_id: str,
    worker_fingerprint: str,
    lease_token_fingerprint: str,
    expected_task_revision: int,
    expected_lease_revision: int,
    expected_ledger_fingerprint: str,
    lease_duration_ms: int,
) -> DramaMediaWorkerLease:
    """Renew one live lease; expired ownership cannot be revived."""

    try:
        number = normalize_episode_no(episode_no)
        revision, duration, _capacity = _validate_claim_inputs(
            task_id=task_id,
            worker_fingerprint=worker_fingerprint,
            lease_token_fingerprint=lease_token_fingerprint,
            expected_task_revision=expected_task_revision,
            expected_ledger_fingerprint=expected_ledger_fingerprint,
            lease_duration_ms=lease_duration_ms,
            lane_capacity=1,
        )
        lease_revision = _strict_int(
            expected_lease_revision,
            label="lease revision",
            minimum=0,
            maximum=10_000,
        )
        with use_workspace(workspace), acquire_write_lock(
            source="drama-media-worker-heartbeat"
        ):
            root = paths.workspace_root(workspace)
            path = media_task_ledger_path(workspace, episode_no=number)
            token = _target_token(root, path)
            ledger = _read_ledger(workspace, episode_no=number)
            task, lease = _task_and_lease(ledger, task_id)
            if lease is None:
                raise DramaMediaWorkerError("media worker lease is missing")
            now = _trusted_now_ms()
            if lease.lease_revision != lease_revision:
                if (
                    lease.lease_revision == lease_revision + 1
                    and task.revision == revision
                    and lease.worker_fingerprint == worker_fingerprint
                    and lease.lease_token_fingerprint == lease_token_fingerprint
                    and lease.expires_at_ms - lease.heartbeat_at_ms
                    == duration
                    and lease.expires_at_ms > now
                ):
                    return lease
                raise DramaMediaWorkerError("media worker lease changed; refresh")
            if (
                task.revision != revision
                or ledger.ledger_fingerprint != expected_ledger_fingerprint
            ):
                raise DramaMediaWorkerError("media worker state changed; refresh")
            if (
                lease.worker_fingerprint != worker_fingerprint
                or lease.lease_token_fingerprint != lease_token_fingerprint
            ):
                raise DramaMediaWorkerError("media worker lease ownership mismatch")
            if task.state not in _LEASED_STATES or now >= lease.expires_at_ms:
                raise DramaMediaWorkerError("media worker lease is expired")
            if now < max(lease.heartbeat_at_ms, task.updated_at_ms):
                raise DramaMediaWorkerError("media worker heartbeat time is invalid")
            if now + duration > 9_999_999_999_999:
                raise DramaMediaWorkerError("media worker lease expiry is invalid")
            renewed = _build_worker_lease(
                task=task,
                worker_fingerprint=worker_fingerprint,
                lease_token_fingerprint=lease_token_fingerprint,
                lane_capacity=lease.lane_capacity,
                lease_revision=lease.lease_revision + 1,
                claimed_at_ms=lease.claimed_at_ms,
                heartbeat_at_ms=now,
                expires_at_ms=now + duration,
            )
            updated = _build_ledger(
                number,
                ledger.tasks,
                revision=ledger.revision + 1,
                leases=[
                    renewed if item.task_id == task_id else item
                    for item in ledger.leases
                ],
                release_receipts=ledger.release_receipts,
                transition_receipts=ledger.transition_receipts,
            )
            _persist_ledger(workspace, updated, expected_target_token=token)
            return renewed
    except WorkspaceLocked:
        raise DramaMediaWorkerError("media worker workspace is busy") from None
    except (DramaMediaWorkerError, DramaMediaTaskError):
        raise
    except (OSError, RecursionError, TypeError, ValueError):
        raise DramaMediaWorkerError("media worker heartbeat was rejected") from None


def release_media_task(
    workspace: str,
    *,
    episode_no: int,
    task_id: str,
    worker_fingerprint: str,
    lease_token_fingerprint: str,
    expected_task_revision: int,
    expected_lease_revision: int,
    expected_ledger_fingerprint: str,
) -> DramaMediaTask:
    """Release a merely claimed task back to ready without executing it."""

    try:
        number = normalize_episode_no(episode_no)
        revision, _duration, _capacity = _validate_claim_inputs(
            task_id=task_id,
            worker_fingerprint=worker_fingerprint,
            lease_token_fingerprint=lease_token_fingerprint,
            expected_task_revision=expected_task_revision,
            expected_ledger_fingerprint=expected_ledger_fingerprint,
            lease_duration_ms=MIN_LEASE_DURATION_MS,
            lane_capacity=1,
        )
        lease_revision = _strict_int(
            expected_lease_revision,
            label="lease revision",
            minimum=0,
            maximum=10_000,
        )
        with use_workspace(workspace), acquire_write_lock(
            source="drama-media-worker-release"
        ):
            root = paths.workspace_root(workspace)
            path = media_task_ledger_path(workspace, episode_no=number)
            token = _target_token(root, path)
            ledger = _read_ledger(workspace, episode_no=number)
            task, lease = _task_and_lease(ledger, task_id)
            if lease is None:
                receipt = next(
                    (
                        item
                        for item in ledger.release_receipts
                        if item.task_id == task_id
                    ),
                    None,
                )
                if (
                    receipt is not None
                    and task.state == "ready"
                    and receipt.from_task_revision == revision
                    and receipt.to_task_revision == task.revision
                    and receipt.worker_fingerprint == worker_fingerprint
                    and receipt.lease_token_fingerprint
                    == lease_token_fingerprint
                    and receipt.lease_revision == lease_revision
                    and receipt.before_ledger_fingerprint
                    == expected_ledger_fingerprint
                    and receipt.released_task_fingerprint
                    == task.record_fingerprint
                ):
                    return task
                raise DramaMediaWorkerError("media worker lease is missing")
            if (
                task.revision != revision
                or lease.lease_revision != lease_revision
                or ledger.ledger_fingerprint != expected_ledger_fingerprint
            ):
                raise DramaMediaWorkerError("media worker state changed; refresh")
            if (
                lease.worker_fingerprint != worker_fingerprint
                or lease.lease_token_fingerprint != lease_token_fingerprint
            ):
                raise DramaMediaWorkerError("media worker lease ownership mismatch")
            now = _trusted_now_ms()
            if (
                task.state != "claimed"
                or now < max(task.updated_at_ms, lease.heartbeat_at_ms)
                or now >= lease.expires_at_ms
            ):
                raise DramaMediaWorkerError("media worker task cannot be released")
            ready = _replace_task(task, state="ready", now_ms=now)
            receipt = _build_release_receipt(
                before=task,
                released=ready,
                lease=lease,
                before_ledger_fingerprint=ledger.ledger_fingerprint,
                released_at_ms=now,
            )
            updated = _build_ledger(
                number,
                [
                    ready if item.task_id == task_id else item
                    for item in ledger.tasks
                ],
                revision=ledger.revision + 1,
                leases=[
                    item for item in ledger.leases if item.task_id != task_id
                ],
                release_receipts=[
                    *[
                        item
                        for item in ledger.release_receipts
                        if item.task_id != task_id
                    ],
                    receipt,
                ],
                transition_receipts=[
                    item
                    for item in ledger.transition_receipts
                    if item.task_id != task_id
                ],
            )
            _persist_ledger(workspace, updated, expected_target_token=token)
            return ready
    except WorkspaceLocked:
        raise DramaMediaWorkerError("media worker workspace is busy") from None
    except (DramaMediaWorkerError, DramaMediaTaskError):
        raise
    except (OSError, RecursionError, TypeError, ValueError):
        raise DramaMediaWorkerError("media worker release was rejected") from None


def takeover_media_task(
    workspace: str,
    *,
    episode_no: int,
    task_id: str,
    worker_fingerprint: str,
    lease_token_fingerprint: str,
    expected_task_revision: int,
    expected_lease_revision: int,
    expected_ledger_fingerprint: str,
    lease_duration_ms: int,
    lane_capacity: int,
) -> DramaMediaWorkerLease:
    """Replace one expired lease without changing the execution state."""

    try:
        number = normalize_episode_no(episode_no)
        revision, duration, capacity = _validate_claim_inputs(
            task_id=task_id,
            worker_fingerprint=worker_fingerprint,
            lease_token_fingerprint=lease_token_fingerprint,
            expected_task_revision=expected_task_revision,
            expected_ledger_fingerprint=expected_ledger_fingerprint,
            lease_duration_ms=lease_duration_ms,
            lane_capacity=lane_capacity,
        )
        lease_revision = _strict_int(
            expected_lease_revision,
            label="lease revision",
            minimum=0,
            maximum=10_000,
        )
        with use_workspace(workspace), acquire_write_lock(
            source="drama-media-worker-takeover"
        ):
            root = paths.workspace_root(workspace)
            path = media_task_ledger_path(workspace, episode_no=number)
            token = _target_token(root, path)
            ledger = _read_ledger(workspace, episode_no=number)
            task, lease = _task_and_lease(ledger, task_id)
            now = _trusted_now_ms()
            if (
                lease is not None
                and task.revision == revision + 1
                and lease.lease_revision == lease_revision + 1
                and lease.worker_fingerprint == worker_fingerprint
                and lease.lease_token_fingerprint == lease_token_fingerprint
                and lease.expires_at_ms - lease.claimed_at_ms == duration
                and lease.lane_capacity == capacity
                and lease.expires_at_ms > now
            ):
                return lease
            if (
                lease is None
                or task.revision != revision
                or lease.lease_revision != lease_revision
                or ledger.ledger_fingerprint != expected_ledger_fingerprint
            ):
                raise DramaMediaWorkerError("media worker state changed; refresh")
            if task.state not in _LEASED_STATES or now < lease.expires_at_ms:
                raise DramaMediaWorkerError("media worker lease is still active")
            if now < task.updated_at_ms or now + duration > 9_999_999_999_999:
                raise DramaMediaWorkerError(
                    "media worker takeover time is invalid"
                )
            if lease.lease_token_fingerprint == lease_token_fingerprint:
                raise DramaMediaWorkerError(
                    "media worker takeover requires a new lease token"
                )
            ledgers = _workspace_ledgers(
                workspace, include_episode_no=number
            )
            _require_lane_capacity(
                ledgers,
                lane_key=lease.lane_key,
                lane_capacity=capacity,
                now_ms=now,
                exclude_task_id=task_id,
            )
            owned = _replace_task(task, state=task.state, now_ms=now)
            replacement = _build_worker_lease(
                task=owned,
                worker_fingerprint=worker_fingerprint,
                lease_token_fingerprint=lease_token_fingerprint,
                lane_capacity=capacity,
                lease_revision=lease.lease_revision + 1,
                claimed_at_ms=now,
                heartbeat_at_ms=now,
                expires_at_ms=now + duration,
            )
            updated = _build_ledger(
                number,
                [
                    owned if item.task_id == task_id else item
                    for item in ledger.tasks
                ],
                revision=ledger.revision + 1,
                leases=[
                    replacement if item.task_id == task_id else item
                    for item in ledger.leases
                ],
                release_receipts=[
                    item
                    for item in ledger.release_receipts
                    if item.task_id != task_id
                ],
                transition_receipts=[
                    item
                    for item in ledger.transition_receipts
                    if item.task_id != task_id
                ],
            )
            _persist_ledger(workspace, updated, expected_target_token=token)
            return replacement
    except WorkspaceLocked:
        raise DramaMediaWorkerError("media worker workspace is busy") from None
    except (DramaMediaWorkerError, DramaMediaTaskError):
        raise
    except (OSError, RecursionError, TypeError, ValueError):
        raise DramaMediaWorkerError("media worker takeover was rejected") from None


def build_media_worker_projection(
    workspace: str,
    *,
    now_ms: int,
) -> dict[str, Any]:
    """Return a bounded lease projection without owner/token/lane/provider data."""

    now = _strict_int(
        now_ms,
        label="time",
        minimum=0,
        maximum=9_999_999_999_999,
    )
    try:
        with use_workspace(workspace), acquire_write_lock(
            source="drama-media-worker-projection"
        ):
            numbers = _episode_numbers_with_ledgers(workspace)
            ledgers = [
                _read_ledger(workspace, episode_no=number)
                for number in numbers
            ]
            rows = []
            tasks = {
                (ledger.episode_no, task.task_id): task
                for ledger in ledgers
                for task in ledger.tasks
            }
            for ledger in ledgers:
                for lease in ledger.leases:
                    task = tasks[(ledger.episode_no, lease.task_id)]
                    rows.append(
                        {
                            "episode_no": ledger.episode_no,
                            "task_id": task.task_id,
                            "media_kind": task.media_kind,
                            "stage": task.stage,
                            "state": task.state,
                            "task_revision": task.revision,
                            "lease_revision": lease.lease_revision,
                            "heartbeat_at_ms": lease.heartbeat_at_ms,
                            "expires_at_ms": lease.expires_at_ms,
                            "lease_status": (
                                "active"
                                if lease.expires_at_ms > now
                                else "expired"
                            ),
                        }
                    )
            rows.sort(key=lambda item: (item["episode_no"], item["task_id"]))
            return {
                "schema_version": 1,
                "lease_count": len(rows),
                "active_count": sum(
                    item["lease_status"] == "active" for item in rows
                ),
                "expired_count": sum(
                    item["lease_status"] == "expired" for item in rows
                ),
                "leases": rows,
            }
    except WorkspaceLocked:
        raise DramaMediaWorkerError("media worker workspace is busy") from None
    except (DramaMediaWorkerError, DramaMediaTaskError):
        raise
    except (OSError, RecursionError, TypeError, ValueError):
        raise DramaMediaWorkerError("media worker projection was rejected") from None
