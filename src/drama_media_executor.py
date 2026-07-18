"""Owner-guarded G5 execution loop over authoritative paid evidence.

The executor owns only generic task/lease transitions.  A code-reviewed,
explicitly injected bridge remains responsible for provider calls and its
media-specific paid ledger.  No provider task id, response, URL, prompt,
credential, artifact path, or paid receipt is copied into the generic ledger.
"""

from __future__ import annotations

import re
import time
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from typing import Any, Literal

from .drama_media_queue_client import get_media_task
from .drama_media_tasks import (
    DramaMediaTaskError,
    load_media_task_ledger,
    transition_media_task,
)
from .drama_media_worker import (
    MAX_LEASE_DURATION_MS,
    MIN_LEASE_DURATION_MS,
    DramaMediaWorkerError,
    heartbeat_media_task,
)
from .drama_schemas import (
    DramaMediaBackendBinding,
    DramaMediaTask,
    DramaMediaWorkerLease,
    _canonical_sha256,
    normalize_episode_no,
)


ExecutionPhase = Literal["submit", "poll", "download", "validate"]
ExecutionOutcome = Literal[
    "submitted",
    "not_sent",
    "submission_unknown",
    "provider_failed",
    "pending",
    "ready",
    "poll_failed",
    "download_failed",
    "succeeded",
    "validation_failed",
]

_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_BRIDGE_ID_RE = re.compile(r"[a-z][a-z0-9._-]{0,63}")
_TASK_ID_RE = re.compile(r"dmt_[0-9a-f]{24}")
_TERMINAL_STATES = frozenset(
    {"succeeded", "failed", "cancelled", "submission_unknown"}
)
_MAX_RUN_STEPS = 16
_MAX_TIMEOUT_MS = 300_000
_OUTCOMES_BY_PHASE: dict[str, frozenset[str]] = {
    "submit": frozenset(
        {
            "submitted",
            "not_sent",
            "submission_unknown",
            "provider_failed",
        }
    ),
    "poll": frozenset({"pending", "ready", "provider_failed", "poll_failed"}),
    "download": frozenset({"ready", "download_failed"}),
    "validate": frozenset({"succeeded", "validation_failed"}),
}


class DramaMediaExecutorError(ValueError):
    """Bounded executor failure without provider or paid-ledger internals."""


class DramaMediaExecutorDeadline(DramaMediaExecutorError):
    """The local execution deadline elapsed before another provider action."""


@dataclass(frozen=True)
class DramaMediaExecutionIdentity:
    """Secret-free operational identity of one reviewed paid bridge."""

    bridge_id: str
    backend_id: str
    provider_fingerprint: str
    model_fingerprint: str
    account_fingerprint: str
    endpoint_fingerprint: str
    source_capability_fingerprint: str


@dataclass(frozen=True)
class DramaMediaExecutionContext:
    """Bounded identity context; intentionally excludes prompts and paths."""

    schema_version: int
    episode_no: int
    task_id: str
    task_revision: int
    media_kind: str
    stage: str
    subject_id: str
    input_fingerprint: str
    binding_fingerprint: str
    worker_fingerprint: str
    lease_token_fingerprint: str
    lease_revision: int
    deadline_monotonic_ns: int


@dataclass(frozen=True)
class DramaMediaExecutionObservation:
    """Content-addressed projection of authoritative media-specific evidence."""

    schema_version: int
    phase: ExecutionPhase
    outcome: ExecutionOutcome
    context_fingerprint: str
    paid_evidence_fingerprint: str
    artifact_evidence_fingerprint: str | None
    observation_fingerprint: str


class DramaMediaPaidEvidenceBridge(ABC):
    """Explicit code seam to an existing image/video/audio paid ledger.

    Implementations must inspect their durable paid ledger before any action.
    In particular, ``submit`` is an inspect-or-submit operation: after a crash
    it returns existing evidence and never blindly repeats an unknown request.
    """

    @property
    @abstractmethod
    def identity(self) -> DramaMediaExecutionIdentity:
        raise NotImplementedError

    @abstractmethod
    def submit(
        self, context: DramaMediaExecutionContext
    ) -> DramaMediaExecutionObservation:
        raise NotImplementedError

    @abstractmethod
    def poll(
        self, context: DramaMediaExecutionContext
    ) -> DramaMediaExecutionObservation:
        raise NotImplementedError

    @abstractmethod
    def download(
        self, context: DramaMediaExecutionContext
    ) -> DramaMediaExecutionObservation:
        raise NotImplementedError

    @abstractmethod
    def validate(
        self, context: DramaMediaExecutionContext
    ) -> DramaMediaExecutionObservation:
        raise NotImplementedError


def build_media_execution_observation(
    *,
    context: DramaMediaExecutionContext,
    phase: ExecutionPhase,
    outcome: ExecutionOutcome,
    paid_evidence_fingerprint: str,
    artifact_evidence_fingerprint: str | None = None,
) -> DramaMediaExecutionObservation:
    """Build a strict content-addressed bridge observation."""

    payload: dict[str, Any] = {
        "schema_version": 1,
        "phase": phase,
        "outcome": outcome,
        "context_fingerprint": _context_fingerprint(context),
        "paid_evidence_fingerprint": paid_evidence_fingerprint,
        "artifact_evidence_fingerprint": artifact_evidence_fingerprint,
    }
    observation = DramaMediaExecutionObservation(
        **payload,
        observation_fingerprint=_canonical_sha256(payload),
    )
    _validate_observation(observation, phase=phase)
    return observation


def _strict_int(
    value: Any, *, label: str, minimum: int, maximum: int
) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < minimum
        or value > maximum
    ):
        raise DramaMediaExecutorError(f"media executor {label} is invalid")
    return value


def _validate_sha(value: Any, *, label: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise DramaMediaExecutorError(f"media executor {label} is invalid")
    return value


def _validate_identity(
    bridge: DramaMediaPaidEvidenceBridge,
    task: DramaMediaTask,
    binding: DramaMediaBackendBinding,
) -> DramaMediaExecutionIdentity:
    if not isinstance(bridge, DramaMediaPaidEvidenceBridge):
        raise DramaMediaExecutorError(
            "media executor paid bridge is not explicitly registered"
        )
    try:
        identity = bridge.identity
    except Exception:
        raise DramaMediaExecutorError(
            "media executor paid bridge identity is unavailable"
        ) from None
    if (
        not isinstance(identity, DramaMediaExecutionIdentity)
        or _BRIDGE_ID_RE.fullmatch(identity.bridge_id) is None
    ):
        raise DramaMediaExecutorError(
            "media executor paid bridge identity is invalid"
        )
    for label, value in (
        ("provider identity", identity.provider_fingerprint),
        ("model identity", identity.model_fingerprint),
        ("account identity", identity.account_fingerprint),
        ("endpoint identity", identity.endpoint_fingerprint),
        (
            "source capability identity",
            identity.source_capability_fingerprint,
        ),
    ):
        _validate_sha(value, label=label)
    if (
        identity.bridge_id != binding.backend_id
        or identity.backend_id != task.backend_id
        or identity.backend_id != binding.backend_id
        or identity.provider_fingerprint != task.provider_fingerprint
        or identity.provider_fingerprint != binding.provider_fingerprint
        or identity.model_fingerprint != task.model_fingerprint
        or identity.model_fingerprint != binding.model_fingerprint
        or identity.account_fingerprint != task.account_fingerprint
        or identity.endpoint_fingerprint != task.endpoint_fingerprint
        or identity.source_capability_fingerprint
        != binding.source_capability_fingerprint
    ):
        raise DramaMediaExecutorError(
            "media executor paid bridge identity changed"
        )
    return identity


def _validate_observation(
    observation: Any,
    *,
    phase: ExecutionPhase,
    context: DramaMediaExecutionContext | None = None,
) -> DramaMediaExecutionObservation:
    if (
        not isinstance(observation, DramaMediaExecutionObservation)
        or observation.schema_version != 1
        or observation.phase != phase
        or observation.outcome not in _OUTCOMES_BY_PHASE[phase]
    ):
        raise DramaMediaExecutorError(
            "media executor paid observation is invalid"
        )
    _validate_sha(
        observation.paid_evidence_fingerprint,
        label="paid evidence",
    )
    _validate_sha(
        observation.context_fingerprint,
        label="execution context",
    )
    if (
        context is not None
        and observation.context_fingerprint != _context_fingerprint(context)
    ):
        raise DramaMediaExecutorError(
            "media executor observation context changed"
        )
    if observation.artifact_evidence_fingerprint is not None:
        _validate_sha(
            observation.artifact_evidence_fingerprint,
            label="artifact evidence",
        )
    if (
        observation.outcome == "succeeded"
    ) != (observation.artifact_evidence_fingerprint is not None):
        raise DramaMediaExecutorError(
            "media executor artifact evidence is invalid"
        )
    payload = asdict(observation)
    fingerprint = payload.pop("observation_fingerprint", None)
    if (
        not isinstance(fingerprint, str)
        or _canonical_sha256(payload) != fingerprint
    ):
        raise DramaMediaExecutorError(
            "media executor observation fingerprint is invalid"
        )
    return observation


def _context_fingerprint(context: Any) -> str:
    if (
        not isinstance(context, DramaMediaExecutionContext)
        or context.schema_version != 1
        or not isinstance(context.episode_no, int)
        or isinstance(context.episode_no, bool)
        or context.episode_no < 1
        or not isinstance(context.task_revision, int)
        or isinstance(context.task_revision, bool)
        or context.task_revision < 1
        or not isinstance(context.lease_revision, int)
        or isinstance(context.lease_revision, bool)
        or context.lease_revision < 0
        or not isinstance(context.deadline_monotonic_ns, int)
        or isinstance(context.deadline_monotonic_ns, bool)
        or context.deadline_monotonic_ns < 0
        or context.deadline_monotonic_ns > 9_999_999_999_999_999_999
        or _TASK_ID_RE.fullmatch(context.task_id) is None
    ):
        raise DramaMediaExecutorError(
            "media executor execution context is invalid"
        )
    for label, value in (
        ("input identity", context.input_fingerprint),
        ("binding identity", context.binding_fingerprint),
        ("worker identity", context.worker_fingerprint),
        ("lease token", context.lease_token_fingerprint),
    ):
        _validate_sha(value, label=label)
    return _canonical_sha256(asdict(context))


def _snapshot(
    workspace: str,
    *,
    episode_no: int,
    task_id: str,
    worker_fingerprint: str,
    lease_token_fingerprint: str,
) -> tuple[
    Any,
    DramaMediaTask,
    DramaMediaWorkerLease | None,
    DramaMediaBackendBinding,
]:
    if not isinstance(task_id, str) or _TASK_ID_RE.fullmatch(task_id) is None:
        raise DramaMediaExecutorError("media executor task identity is invalid")
    _validate_sha(worker_fingerprint, label="worker identity")
    _validate_sha(lease_token_fingerprint, label="lease token")
    ledger = load_media_task_ledger(workspace, episode_no=episode_no)
    task = next(
        (item for item in ledger.tasks if item.task_id == task_id), None
    )
    binding = next(
        (
            item
            for item in ledger.backend_bindings
            if item.task_id == task_id
        ),
        None,
    )
    if (
        task is None
        or task.media_kind not in {"image", "video", "audio"}
        or binding is None
        or binding.task_id != task.task_id
        or binding.task_input_fingerprint != task.input_fingerprint
    ):
        raise DramaMediaExecutorError(
            "media executor task binding is unavailable"
        )
    lease = next(
        (item for item in ledger.leases if item.task_id == task_id), None
    )
    if task.state not in _TERMINAL_STATES and task.state != "cancelling":
        if (
            lease is None
            or lease.worker_fingerprint != worker_fingerprint
            or lease.lease_token_fingerprint != lease_token_fingerprint
            or lease.task_revision != task.revision
        ):
            raise DramaMediaExecutorError(
                "media executor worker ownership changed"
            )
    return ledger, task, lease, binding


def _context(
    *,
    task: DramaMediaTask,
    binding: DramaMediaBackendBinding,
    lease: DramaMediaWorkerLease,
    deadline_monotonic_ns: int,
) -> DramaMediaExecutionContext:
    return DramaMediaExecutionContext(
        schema_version=1,
        episode_no=task.episode_no,
        task_id=task.task_id,
        task_revision=task.revision,
        media_kind=task.media_kind,
        stage=task.stage,
        subject_id=task.subject_id,
        input_fingerprint=task.input_fingerprint,
        binding_fingerprint=binding.binding_fingerprint,
        worker_fingerprint=lease.worker_fingerprint,
        lease_token_fingerprint=lease.lease_token_fingerprint,
        lease_revision=lease.lease_revision,
        deadline_monotonic_ns=deadline_monotonic_ns,
    )


def _transition(
    workspace: str,
    *,
    ledger: Any,
    task: DramaMediaTask,
    lease: DramaMediaWorkerLease,
    target_state: str,
    outcome_code: str | None = None,
    result_fingerprint: str | None = None,
) -> None:
    transition_media_task(
        workspace,
        episode_no=task.episode_no,
        task_id=task.task_id,
        target_state=target_state,  # type: ignore[arg-type]
        expected_task_revision=task.revision,
        expected_ledger_fingerprint=ledger.ledger_fingerprint,
        worker_fingerprint=lease.worker_fingerprint,
        lease_token_fingerprint=lease.lease_token_fingerprint,
        expected_lease_revision=lease.lease_revision,
        outcome_code=outcome_code,  # type: ignore[arg-type]
        result_fingerprint=result_fingerprint,
    )


def _heartbeat(
    workspace: str,
    *,
    ledger: Any,
    task: DramaMediaTask,
    lease: DramaMediaWorkerLease,
    lease_duration_ms: int,
) -> None:
    heartbeat_media_task(
        workspace,
        episode_no=task.episode_no,
        task_id=task.task_id,
        worker_fingerprint=lease.worker_fingerprint,
        lease_token_fingerprint=lease.lease_token_fingerprint,
        expected_task_revision=task.revision,
        expected_lease_revision=lease.lease_revision,
        expected_ledger_fingerprint=ledger.ledger_fingerprint,
        lease_duration_ms=lease_duration_ms,
    )


def _safe_result(
    workspace: str,
    *,
    episode_no: int,
    task_id: str,
    action: str,
    status: str,
) -> dict[str, Any]:
    result = get_media_task(
        workspace, episode_no=episode_no, task_id=task_id
    )
    result["execution_action"] = action
    result["execution_status"] = status
    return result


def _invoke(
    bridge: DramaMediaPaidEvidenceBridge,
    *,
    phase: ExecutionPhase,
    context: DramaMediaExecutionContext,
) -> DramaMediaExecutionObservation:
    method = {
        "submit": bridge.submit,
        "poll": bridge.poll,
        "download": bridge.download,
        "validate": bridge.validate,
    }[phase]
    return method(context)


def execute_media_task_step(
    workspace: str,
    *,
    episode_no: int,
    task_id: str,
    worker_fingerprint: str,
    lease_token_fingerprint: str,
    bridge: DramaMediaPaidEvidenceBridge,
    lease_duration_ms: int,
    deadline_monotonic_ns: int,
) -> dict[str, Any]:
    """Run at most one paid-bridge action and commit its generic projection."""

    try:
        number = normalize_episode_no(episode_no)
        duration = _strict_int(
            lease_duration_ms,
            label="lease duration",
            minimum=MIN_LEASE_DURATION_MS,
            maximum=MAX_LEASE_DURATION_MS,
        )
        deadline = _strict_int(
            deadline_monotonic_ns,
            label="deadline",
            minimum=0,
            maximum=9_999_999_999_999_999_999,
        )
        ledger, task, lease, binding = _snapshot(
            workspace,
            episode_no=number,
            task_id=task_id,
            worker_fingerprint=worker_fingerprint,
            lease_token_fingerprint=lease_token_fingerprint,
        )
        if task.state in _TERMINAL_STATES:
            return _safe_result(
                workspace,
                episode_no=number,
                task_id=task_id,
                action="none",
                status="terminal",
            )
        if task.state == "cancelling":
            return _safe_result(
                workspace,
                episode_no=number,
                task_id=task_id,
                action="none",
                status="cancel_requested",
            )
        _validate_identity(bridge, task, binding)
        if lease is None:
            raise DramaMediaExecutorError(
                "media executor worker ownership is unavailable"
            )
        if time.monotonic_ns() >= deadline:
            raise DramaMediaExecutorDeadline(
                "media executor deadline elapsed"
            )

        phase: ExecutionPhase
        if task.state == "claimed":
            _transition(
                workspace,
                ledger=ledger,
                task=task,
                lease=lease,
                target_state="submitting",
            )
            ledger, task, lease, binding = _snapshot(
                workspace,
                episode_no=number,
                task_id=task_id,
                worker_fingerprint=worker_fingerprint,
                lease_token_fingerprint=lease_token_fingerprint,
            )
            phase = "submit"
        elif task.state == "submitting":
            phase = "submit"
        elif task.state == "submitted":
            target = (
                "polling"
                if binding.registration.capability.supports_poll
                else "downloading"
            )
            _transition(
                workspace,
                ledger=ledger,
                task=task,
                lease=lease,
                target_state=target,
            )
            ledger, task, lease, binding = _snapshot(
                workspace,
                episode_no=number,
                task_id=task_id,
                worker_fingerprint=worker_fingerprint,
                lease_token_fingerprint=lease_token_fingerprint,
            )
            if task.state == "polling":
                phase = "poll"
            elif binding.registration.capability.supports_download:
                phase = "download"
            else:
                _transition(
                    workspace,
                    ledger=ledger,
                    task=task,
                    lease=lease,
                    target_state="validating",
                )
                return _safe_result(
                    workspace,
                    episode_no=number,
                    task_id=task_id,
                    action="route",
                    status="validation_ready",
                )
        elif task.state == "polling":
            phase = "poll"
        elif task.state == "downloading":
            if binding.registration.capability.supports_download:
                phase = "download"
            else:
                _transition(
                    workspace,
                    ledger=ledger,
                    task=task,
                    lease=lease,
                    target_state="validating",
                )
                return _safe_result(
                    workspace,
                    episode_no=number,
                    task_id=task_id,
                    action="route",
                    status="validation_ready",
                )
        elif task.state == "validating":
            phase = "validate"
        else:
            raise DramaMediaExecutorError(
                "media executor task state is not executable"
            )

        now_ns = time.monotonic_ns()
        if now_ns >= deadline:
            raise DramaMediaExecutorDeadline(
                "media executor deadline elapsed"
            )
        _heartbeat(
            workspace,
            ledger=ledger,
            task=task,
            lease=lease,
            lease_duration_ms=duration,
        )
        ledger, task, lease, binding = _snapshot(
            workspace,
            episode_no=number,
            task_id=task_id,
            worker_fingerprint=worker_fingerprint,
            lease_token_fingerprint=lease_token_fingerprint,
        )
        if lease is None:
            raise DramaMediaExecutorError(
                "media executor worker ownership is unavailable"
            )
        context = _context(
            task=task,
            binding=binding,
            lease=lease,
            deadline_monotonic_ns=deadline,
        )
        if time.monotonic_ns() >= deadline:
            raise DramaMediaExecutorDeadline(
                "media executor deadline elapsed"
            )
        try:
            observation = _invoke(
                bridge, phase=phase, context=context
            )
            _validate_identity(bridge, task, binding)
            observation = _validate_observation(
                observation, phase=phase, context=context
            )
        except Exception:
            if phase == "submit":
                try:
                    _transition(
                        workspace,
                        ledger=ledger,
                        task=task,
                        lease=lease,
                        target_state="submission_unknown",
                        outcome_code="transport_unknown",
                    )
                except (DramaMediaTaskError, DramaMediaWorkerError):
                    pass
                raise DramaMediaExecutorError(
                    "media executor submission requires reconciliation"
                ) from None
            raise DramaMediaExecutorError(
                f"media executor {phase} step failed"
            ) from None

        outcome = observation.outcome
        if phase == "submit":
            if outcome == "submitted":
                _transition(
                    workspace,
                    ledger=ledger,
                    task=task,
                    lease=lease,
                    target_state="submitted",
                )
            elif outcome == "not_sent":
                _transition(
                    workspace,
                    ledger=ledger,
                    task=task,
                    lease=lease,
                    target_state="failed",
                    outcome_code="local_failure",
                )
            elif outcome == "submission_unknown":
                _transition(
                    workspace,
                    ledger=ledger,
                    task=task,
                    lease=lease,
                    target_state="submission_unknown",
                    outcome_code="transport_unknown",
                )
            else:
                _transition(
                    workspace,
                    ledger=ledger,
                    task=task,
                    lease=lease,
                    target_state="failed",
                    outcome_code="provider_failed",
                )
        elif phase == "poll":
            if outcome == "pending":
                return _safe_result(
                    workspace,
                    episode_no=number,
                    task_id=task_id,
                    action="poll",
                    status="pending",
                )
            _transition(
                workspace,
                ledger=ledger,
                task=task,
                lease=lease,
                target_state=(
                    "downloading" if outcome == "ready" else "failed"
                ),
                outcome_code=(
                    None
                    if outcome == "ready"
                    else (
                        "provider_failed"
                        if outcome == "provider_failed"
                        else "poll_failed"
                    )
                ),
            )
        elif phase == "download":
            _transition(
                workspace,
                ledger=ledger,
                task=task,
                lease=lease,
                target_state=(
                    "validating" if outcome == "ready" else "failed"
                ),
                outcome_code=(
                    None if outcome == "ready" else "download_failed"
                ),
            )
        else:
            _transition(
                workspace,
                ledger=ledger,
                task=task,
                lease=lease,
                target_state=(
                    "succeeded" if outcome == "succeeded" else "failed"
                ),
                outcome_code=(
                    None if outcome == "succeeded" else "validation_failed"
                ),
                result_fingerprint=(
                    observation.artifact_evidence_fingerprint
                    if outcome == "succeeded"
                    else None
                ),
            )
        return _safe_result(
            workspace,
            episode_no=number,
            task_id=task_id,
            action=phase,
            status=outcome,
        )
    except DramaMediaExecutorError:
        raise
    except (DramaMediaTaskError, DramaMediaWorkerError):
        raise DramaMediaExecutorError(
            "media executor state changed; refresh"
        ) from None
    except (OSError, RecursionError, TypeError, ValueError):
        raise DramaMediaExecutorError(
            "media executor step was rejected"
        ) from None


def run_media_task(
    workspace: str,
    *,
    episode_no: int,
    task_id: str,
    worker_fingerprint: str,
    lease_token_fingerprint: str,
    bridge: DramaMediaPaidEvidenceBridge,
    lease_duration_ms: int,
    timeout_ms: int,
    max_steps: int = _MAX_RUN_STEPS,
) -> dict[str, Any]:
    """Run a bounded zero-sleep sequence, stopping on pending or terminal."""

    timeout = _strict_int(
        timeout_ms,
        label="timeout",
        minimum=0,
        maximum=_MAX_TIMEOUT_MS,
    )
    steps = _strict_int(
        max_steps,
        label="step count",
        minimum=1,
        maximum=_MAX_RUN_STEPS,
    )
    started = time.monotonic_ns()
    deadline = started + timeout * 1_000_000
    if deadline < started:
        raise DramaMediaExecutorError("media executor deadline is invalid")
    result: dict[str, Any] | None = None
    for _ in range(steps):
        result = execute_media_task_step(
            workspace,
            episode_no=episode_no,
            task_id=task_id,
            worker_fingerprint=worker_fingerprint,
            lease_token_fingerprint=lease_token_fingerprint,
            bridge=bridge,
            lease_duration_ms=lease_duration_ms,
            deadline_monotonic_ns=deadline,
        )
        if (
            result["state"] in _TERMINAL_STATES
            or result["state"] == "cancelling"
            or result["execution_status"] == "pending"
        ):
            return result
    if result is None:
        raise DramaMediaExecutorError("media executor made no progress")
    return result
