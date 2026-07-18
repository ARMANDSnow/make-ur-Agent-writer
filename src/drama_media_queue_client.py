"""Pure-local G4 client for durable, backend-bound media task queues."""

from __future__ import annotations

import re
import time
from collections.abc import Sequence
from typing import Any

from .drama_media_tasks import (
    DramaMediaTaskError,
    TERMINAL_MEDIA_TASK_STATES,
    _backend_binding_status,
    cancel_media_task_cascade,
    enqueue_bound_media_task,
    load_media_task_ledger,
)
from .drama_schemas import (
    DramaMediaBackendRegistrySnapshot,
    DramaMediaKind,
    DramaMediaStage,
    DramaMediaTask,
    normalize_episode_no,
)


MAX_WAIT_TIMEOUT_MS = 300_000
MIN_POLL_INTERVAL_MS = 10
MAX_POLL_INTERVAL_MS = 10_000
_WAIT_COMPLETE_STATES = TERMINAL_MEDIA_TASK_STATES | {"submission_unknown"}


class DramaMediaQueueClientError(ValueError):
    """Fail-closed local queue client error."""


class DramaMediaQueueTimeout(DramaMediaQueueClientError):
    """A bounded local wait elapsed without a durable completion state."""


def _wall_clock_ms() -> int:
    return time.time_ns() // 1_000_000


def _monotonic_ns() -> int:
    return time.monotonic_ns()


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


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
        raise DramaMediaQueueClientError(f"media queue {label} is invalid")
    return value


def _validate_task_id(task_id: str) -> str:
    if (
        not isinstance(task_id, str)
        or re.fullmatch(r"dmt_[0-9a-f]{24}", task_id) is None
    ):
        raise DramaMediaQueueClientError("media queue task identity is invalid")
    return task_id


def _task_projection(
    task: DramaMediaTask,
    *,
    binding_status: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "task_id": task.task_id,
        "episode_no": task.episode_no,
        "media_kind": task.media_kind,
        "stage": task.stage,
        "subject_id": task.subject_id,
        "dependency_task_ids": list(task.dependency_task_ids),
        "attempt_no": task.attempt_no,
        "state": task.state,
        "revision": task.revision,
        "created_at_ms": task.created_at_ms,
        "updated_at_ms": task.updated_at_ms,
        "result_fingerprint": task.result_fingerprint,
        "outcome_code": task.outcome_code,
        "backend_binding_status": binding_status,
    }


def _project_from_ledger(ledger: Any, task_id: str) -> dict[str, Any]:
    task = next(
        (item for item in ledger.tasks if item.task_id == task_id),
        None,
    )
    if task is None:
        raise DramaMediaQueueClientError("media queue task is missing")
    bound = any(
        item.task_id == task.task_id for item in ledger.backend_bindings
    )
    return _task_projection(
        task,
        binding_status=_backend_binding_status(task, bound=bound),
    )


def enqueue_media_task(
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
) -> dict[str, Any]:
    """Create task+binding in one ledger commit and return a safe projection."""

    try:
        number = normalize_episode_no(episode_no)
        try:
            expected = load_media_task_ledger(
                workspace, episode_no=number
            ).ledger_fingerprint
        except FileNotFoundError:
            expected = None
        task, _binding = enqueue_bound_media_task(
            workspace,
            episode_no=number,
            media_kind=media_kind,
            stage=stage,
            subject_id=subject_id,
            input_fingerprint=input_fingerprint,
            backend_id=backend_id,
            provider_id=provider_id,
            model_id=model_id,
            provider_fingerprint=provider_fingerprint,
            model_fingerprint=model_fingerprint,
            account_fingerprint=account_fingerprint,
            endpoint_fingerprint=endpoint_fingerprint,
            registry=registry,
            dependency_task_ids=dependency_task_ids,
            attempt_no=attempt_no,
            now_ms=_wall_clock_ms(),
            expected_ledger_fingerprint=expected,
        )
        return _task_projection(task, binding_status="frozen")
    except DramaMediaQueueClientError:
        raise
    except (DramaMediaTaskError, OSError, RecursionError, TypeError, ValueError):
        raise DramaMediaQueueClientError(
            "media queue enqueue was rejected"
        ) from None


def get_media_task(
    workspace: str,
    *,
    episode_no: int,
    task_id: str,
) -> dict[str, Any]:
    """Read one durable task without exposing provider or binding identity."""

    try:
        number = normalize_episode_no(episode_no)
        identity = _validate_task_id(task_id)
        ledger = load_media_task_ledger(workspace, episode_no=number)
        return _project_from_ledger(ledger, identity)
    except DramaMediaQueueClientError:
        raise
    except (FileNotFoundError, DramaMediaTaskError, OSError, TypeError, ValueError):
        raise DramaMediaQueueClientError(
            "media queue task could not be loaded"
        ) from None


def wait_for_media_task(
    workspace: str,
    *,
    episode_no: int,
    task_id: str,
    timeout_ms: int,
    poll_interval_ms: int = 100,
) -> dict[str, Any]:
    """Wait locally for a durable terminal/unknown state within strict bounds."""

    number = normalize_episode_no(episode_no)
    identity = _validate_task_id(task_id)
    timeout = _strict_int(
        timeout_ms,
        label="wait timeout",
        minimum=0,
        maximum=MAX_WAIT_TIMEOUT_MS,
    )
    interval = _strict_int(
        poll_interval_ms,
        label="poll interval",
        minimum=MIN_POLL_INTERVAL_MS,
        maximum=MAX_POLL_INTERVAL_MS,
    )
    started = _monotonic_ns()
    deadline = started + timeout * 1_000_000
    if deadline < started:
        raise DramaMediaQueueClientError("media queue wait clock is invalid")
    first_read = True
    while True:
        if not first_read:
            before_read = _monotonic_ns()
            if before_read < started:
                raise DramaMediaQueueClientError(
                    "media queue monotonic clock is invalid"
                )
            if before_read >= deadline:
                raise DramaMediaQueueTimeout("media queue wait timed out")
        projection = get_media_task(
            workspace,
            episode_no=number,
            task_id=identity,
        )
        now = _monotonic_ns()
        if now < started:
            raise DramaMediaQueueClientError(
                "media queue monotonic clock is invalid"
            )
        if projection["state"] in _WAIT_COMPLETE_STATES:
            if first_read and timeout == 0:
                return projection
            if now >= deadline:
                raise DramaMediaQueueTimeout("media queue wait timed out")
            return projection
        if now >= deadline:
            raise DramaMediaQueueTimeout("media queue wait timed out")
        remaining_ns = deadline - now
        _sleep(min(interval / 1000, remaining_ns / 1_000_000_000))
        first_read = False


def request_media_task_cancel(
    workspace: str,
    *,
    episode_no: int,
    task_id: str,
) -> list[dict[str, Any]]:
    """Request durable cancellation using the current local CAS snapshot."""

    try:
        number = normalize_episode_no(episode_no)
        identity = _validate_task_id(task_id)
        ledger = load_media_task_ledger(workspace, episode_no=number)
        task = next(
            (item for item in ledger.tasks if item.task_id == identity),
            None,
        )
        if task is None:
            raise DramaMediaQueueClientError("media queue task is missing")
        affected = cancel_media_task_cascade(
            workspace,
            episode_no=number,
            task_id=identity,
            expected_task_revision=task.revision,
            expected_ledger_fingerprint=ledger.ledger_fingerprint,
            now_ms=max(_wall_clock_ms(), task.updated_at_ms),
        )
        persisted = load_media_task_ledger(workspace, episode_no=number)
        bound_ids = {
            item.task_id for item in persisted.backend_bindings
        }
        return [
            _task_projection(
                item,
                binding_status=(
                    _backend_binding_status(
                        item, bound=item.task_id in bound_ids
                    )
                ),
            )
            for item in affected
        ]
    except DramaMediaQueueClientError:
        raise
    except (FileNotFoundError, DramaMediaTaskError, OSError, TypeError, ValueError):
        raise DramaMediaQueueClientError(
            "media queue cancellation was rejected"
        ) from None
