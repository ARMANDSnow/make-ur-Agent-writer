"""Pure D3 provider capability and once-only shot-video attempt transitions."""

from __future__ import annotations

import hashlib
from typing import Any, Mapping

from .drama_schemas import (
    EpisodeShotVideoAttemptLedger,
    EpisodeShotVideoCandidateManifest,
    EpisodeShotVideoPlan,
    ShotVideoAttemptArtifactReceipt,
    ShotVideoAttemptClosureReceipt,
    ShotVideoAttemptOutcome,
    ShotVideoAttemptRecord,
    ShotVideoAttemptSpec,
    ShotVideoCandidate,
    ShotVideoProviderCapability,
    ShotVideoResolution,
    ShotVideoSubmissionGate,
    ShotVideoSubmissionReceipt,
    ShotVideoTerminalReceipt,
    _canonical_sha256,
)
from .paid_recovery_states import (
    SHOT_VIDEO_NOT_SENT_STATUSES,
    SHOT_VIDEO_SUBMITTED_STATUSES,
    SHOT_VIDEO_TERMINAL_STATUSES,
    SHOT_VIDEO_UNKNOWN_STATUSES,
)
from .schemas import model_to_dict


class DramaShotVideoAttemptError(ValueError):
    """Bounded public failure for caller-controlled D3 inputs."""


def build_shot_video_provider_capability(
    *,
    backend_id: str,
    capability_version: str,
    supported_modes: list[str],
    supports_tail_frame: bool,
    max_reference_images: int,
    supported_durations_seconds: list[int],
    supported_resolutions: list[tuple[int, int]],
) -> ShotVideoProviderCapability:
    try:
        payload: dict[str, Any] = {
            "schema_version": 1,
            "backend_id": backend_id,
            "capability_version": capability_version,
            "supported_modes": list(supported_modes),
            "supports_async_submission": True,
            "supports_poll_resume": True,
            "supports_tail_frame": supports_tail_frame,
            "max_reference_images": max_reference_images,
            "supported_durations_seconds": list(supported_durations_seconds),
            "supported_resolutions": [
                model_to_dict(ShotVideoResolution(width=width, height=height))
                for width, height in supported_resolutions
            ],
            "output_media_type": "video/mp4",
        }
        payload["capability_fingerprint"] = _canonical_sha256(payload)
        return ShotVideoProviderCapability(**payload)
    except (RecursionError, TypeError, ValueError):
        raise DramaShotVideoAttemptError(
            "shot video provider capability was rejected"
        ) from None


def build_shot_video_submission_gate(
    *,
    backend_id: str,
    authorization_id: str,
    authorized_episode_no: int,
    authorized_shot_id: str,
    authorized_request_fingerprint: str,
    provider_fingerprint: str,
    model_fingerprint: str,
    account_fingerprint: str,
    endpoint_fingerprint: str,
    auth_fingerprint: str,
    estimated_cost_microunits: int,
    authorized_budget_microunits: int,
) -> ShotVideoSubmissionGate:
    try:
        payload: dict[str, Any] = {
            "schema_version": 1,
            "backend_id": backend_id,
            "authorization_id": authorization_id,
            "authorized_episode_no": authorized_episode_no,
            "authorized_shot_id": authorized_shot_id,
            "authorized_request_fingerprint": authorized_request_fingerprint,
            "provider_fingerprint": provider_fingerprint,
            "model_fingerprint": model_fingerprint,
            "account_fingerprint": account_fingerprint,
            "endpoint_fingerprint": endpoint_fingerprint,
            "auth_fingerprint": auth_fingerprint,
            "authorization_scope": "shot_video_once",
            "confirmed": True,
            "currency": "CNY",
            "estimated_cost_microunits": estimated_cost_microunits,
            "authorized_budget_microunits": authorized_budget_microunits,
            "max_submit_calls": 1,
        }
        payload["authorization_fingerprint"] = _canonical_sha256(payload)
        return ShotVideoSubmissionGate(**payload)
    except (RecursionError, TypeError, ValueError):
        raise DramaShotVideoAttemptError(
            "shot video submission authorization was rejected"
        ) from None


def _as_plan(value: EpisodeShotVideoPlan | Mapping[str, Any]) -> EpisodeShotVideoPlan:
    return value if isinstance(value, EpisodeShotVideoPlan) else EpisodeShotVideoPlan(**value)


def _as_manifest(
    value: EpisodeShotVideoCandidateManifest | Mapping[str, Any],
) -> EpisodeShotVideoCandidateManifest:
    return (
        value
        if isinstance(value, EpisodeShotVideoCandidateManifest)
        else EpisodeShotVideoCandidateManifest(**value)
    )


def _as_capability(
    value: ShotVideoProviderCapability | Mapping[str, Any],
) -> ShotVideoProviderCapability:
    return (
        value
        if isinstance(value, ShotVideoProviderCapability)
        else ShotVideoProviderCapability(**value)
    )


def _as_gate(
    value: ShotVideoSubmissionGate | Mapping[str, Any],
) -> ShotVideoSubmissionGate:
    return value if isinstance(value, ShotVideoSubmissionGate) else ShotVideoSubmissionGate(**value)


def shot_video_attempt_prompt(request: Any) -> str:
    """Return the in-memory provider prompt; it is never persisted in the ledger."""

    return "\n".join(
        part
        for part in (
            request.visual_action,
            request.image_prompt,
            request.transition_hint,
        )
        if part
    )


def build_shot_video_attempt_spec(
    plan: EpisodeShotVideoPlan | Mapping[str, Any],
    manifest: EpisodeShotVideoCandidateManifest | Mapping[str, Any],
    *,
    shot_id: str,
    capability: ShotVideoProviderCapability | Mapping[str, Any],
    submission_gate: ShotVideoSubmissionGate | Mapping[str, Any],
    mode: str,
    output_width: int,
    output_height: int,
) -> ShotVideoAttemptSpec:
    """Freeze one exact D1 request without reordering or clipping its references."""

    try:
        current_plan = _as_plan(plan)
        current_manifest = _as_manifest(manifest)
        current_capability = _as_capability(capability)
        current_gate = _as_gate(submission_gate)
        if (
            current_manifest.season_no != current_plan.season_no
            or current_manifest.episode_no != current_plan.episode_no
            or current_manifest.source_plan_fingerprint != current_plan.plan_fingerprint
        ):
            raise ValueError("candidate manifest does not match the shot video plan")
        request = next(
            (item for item in current_plan.shot_specs if item.shot_id == shot_id),
            None,
        )
        pool = next(
            (item for item in current_manifest.shots if item.shot_id == shot_id),
            None,
        )
        if request is None or pool is None:
            raise ValueError("shot video attempt target is unknown")
        if pool.current_request_fingerprint != request.spec_fingerprint:
            raise ValueError("shot video candidate manifest request is stale")
        prompt = shot_video_attempt_prompt(request)
        references = [model_to_dict(item) for item in request.ordered_references]
        payload: dict[str, Any] = {
            "schema_version": 1,
            "season_no": current_plan.season_no,
            "episode_no": current_plan.episode_no,
            "shot_id": request.shot_id,
            "source_plan_fingerprint": current_plan.plan_fingerprint,
            "request_fingerprint": request.spec_fingerprint,
            "pre_manifest_fingerprint": current_manifest.manifest_fingerprint,
            "mode": mode,
            "target_duration_seconds": request.target_duration_seconds,
            "output_width": output_width,
            "output_height": output_height,
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "first_frame": model_to_dict(request.first_frame),
            "tail_frame": (
                model_to_dict(request.tail_frame) if request.tail_frame is not None else None
            ),
            "ordered_references": references,
            "references_fingerprint": _canonical_sha256(references),
            "capability": model_to_dict(current_capability),
            "submission_gate": model_to_dict(current_gate),
            "output_media_type": "video/mp4",
        }
        payload["input_fingerprint"] = _canonical_sha256(payload)
        return ShotVideoAttemptSpec(**payload)
    except DramaShotVideoAttemptError:
        raise
    except (RecursionError, TypeError, ValueError):
        raise DramaShotVideoAttemptError(
            "shot video attempt specification was rejected"
        ) from None


def build_empty_shot_video_attempt_ledger(
    plan: EpisodeShotVideoPlan | Mapping[str, Any],
) -> EpisodeShotVideoAttemptLedger:
    try:
        current = _as_plan(plan)
        payload: dict[str, Any] = {
            "schema_version": 1,
            "generator_version": "shot-video-attempts-v1",
            "season_no": current.season_no,
            "episode_no": current.episode_no,
            "revision": 0,
            "attempts": [],
        }
        payload["ledger_fingerprint"] = _canonical_sha256(payload)
        return EpisodeShotVideoAttemptLedger(**payload)
    except (RecursionError, TypeError, ValueError):
        raise DramaShotVideoAttemptError("shot video attempt ledger was rejected") from None


def classify_shot_video_attempt(record: ShotVideoAttemptRecord) -> ShotVideoAttemptOutcome:
    if record.status in SHOT_VIDEO_NOT_SENT_STATUSES:
        return "not_sent"
    if record.status in SHOT_VIDEO_UNKNOWN_STATUSES:
        return "unknown"
    if record.status in SHOT_VIDEO_SUBMITTED_STATUSES:
        return "submitted"
    if record.status in SHOT_VIDEO_TERMINAL_STATUSES:
        return "terminal"
    raise DramaShotVideoAttemptError("shot video attempt status is unclassified")


def _record_payload(record: ShotVideoAttemptRecord) -> dict[str, Any]:
    return record.model_dump(exclude={"record_fingerprint"})


def _build_record(payload: Mapping[str, Any]) -> ShotVideoAttemptRecord:
    current = dict(payload)
    current["record_fingerprint"] = _canonical_sha256(current)
    return ShotVideoAttemptRecord(**current)


def _ledger_with_attempts(
    ledger: EpisodeShotVideoAttemptLedger,
    attempts: list[ShotVideoAttemptRecord],
) -> EpisodeShotVideoAttemptLedger:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "generator_version": "shot-video-attempts-v1",
        "season_no": ledger.season_no,
        "episode_no": ledger.episode_no,
        "revision": ledger.revision + 1,
        "attempts": [model_to_dict(item) for item in attempts],
    }
    payload["ledger_fingerprint"] = _canonical_sha256(payload)
    return EpisodeShotVideoAttemptLedger(**payload)


def _replace_attempt(
    ledger: EpisodeShotVideoAttemptLedger,
    previous: ShotVideoAttemptRecord,
    replacement: ShotVideoAttemptRecord,
    *,
    expected_ledger_fingerprint: str,
) -> EpisodeShotVideoAttemptLedger:
    if expected_ledger_fingerprint != ledger.ledger_fingerprint:
        raise ValueError("shot video attempt ledger changed")
    matches = [index for index, item in enumerate(ledger.attempts) if item.attempt_id == previous.attempt_id]
    if len(matches) != 1 or ledger.attempts[matches[0]] != previous:
        raise ValueError("shot video attempt changed")
    attempts = list(ledger.attempts)
    attempts[matches[0]] = replacement
    return _ledger_with_attempts(ledger, attempts)


def start_shot_video_attempt(
    ledger: EpisodeShotVideoAttemptLedger,
    spec: ShotVideoAttemptSpec,
    *,
    expected_ledger_fingerprint: str,
) -> tuple[EpisodeShotVideoAttemptLedger, ShotVideoAttemptRecord]:
    try:
        if expected_ledger_fingerprint != ledger.ledger_fingerprint:
            raise ValueError("shot video attempt ledger changed")
        if spec.season_no != ledger.season_no or spec.episode_no != ledger.episode_no:
            raise ValueError("shot video attempt belongs to another episode")
        same_shot = [item for item in ledger.attempts if item.spec.shot_id == spec.shot_id]
        if same_shot and same_shot[-1].status not in {
            "not_sent",
            "provider_failed",
            "succeeded",
            "closed_unknown",
        }:
            raise ValueError("previous shot video attempt requires reconciliation")
        attempt_no = len(same_shot) + 1
        if attempt_no > 32:
            raise ValueError("shot video attempt limit reached")
        attempt_id = f"sva_{_canonical_sha256({'input_fingerprint': spec.input_fingerprint, 'attempt_no': attempt_no})[:24]}"
        staging_path = (
            f"logs/drama_shot_videos/episode_{spec.episode_no:02d}/"
            f"{spec.shot_id}/{attempt_id}.mp4"
        )
        record = _build_record(
            {
                "schema_version": 1,
                "attempt_id": attempt_id,
                "attempt_no": attempt_no,
                "spec": model_to_dict(spec),
                "status": "started",
                "staging_path": staging_path,
                "submission_receipt": None,
                "terminal_receipt": None,
                "artifact_receipt": None,
                "closure_receipt": None,
                "candidate_id": None,
                "candidate_fingerprint": None,
                "post_manifest_fingerprint": None,
            }
        )
        return _ledger_with_attempts(ledger, [*ledger.attempts, record]), record
    except (RecursionError, TypeError, ValueError):
        raise DramaShotVideoAttemptError("shot video attempt start was rejected") from None


def _simple_status_transition(
    ledger: EpisodeShotVideoAttemptLedger,
    record: ShotVideoAttemptRecord,
    *,
    expected_status: str,
    desired_status: str,
    expected_ledger_fingerprint: str,
) -> tuple[EpisodeShotVideoAttemptLedger, ShotVideoAttemptRecord]:
    if record.status != expected_status:
        raise ValueError("shot video attempt status changed")
    payload = _record_payload(record)
    payload["status"] = desired_status
    replacement = _build_record(payload)
    return (
        _replace_attempt(
            ledger,
            record,
            replacement,
            expected_ledger_fingerprint=expected_ledger_fingerprint,
        ),
        replacement,
    )


def record_shot_video_not_sent(
    ledger: EpisodeShotVideoAttemptLedger,
    record: ShotVideoAttemptRecord,
    *,
    expected_ledger_fingerprint: str,
) -> tuple[EpisodeShotVideoAttemptLedger, ShotVideoAttemptRecord]:
    try:
        return _simple_status_transition(
            ledger,
            record,
            expected_status="started",
            desired_status="not_sent",
            expected_ledger_fingerprint=expected_ledger_fingerprint,
        )
    except (RecursionError, TypeError, ValueError):
        raise DramaShotVideoAttemptError("shot video not-sent transition was rejected") from None


def record_shot_video_submission_unknown(
    ledger: EpisodeShotVideoAttemptLedger,
    record: ShotVideoAttemptRecord,
    *,
    expected_ledger_fingerprint: str,
) -> tuple[EpisodeShotVideoAttemptLedger, ShotVideoAttemptRecord]:
    try:
        return _simple_status_transition(
            ledger,
            record,
            expected_status="started",
            desired_status="submission_unknown",
            expected_ledger_fingerprint=expected_ledger_fingerprint,
        )
    except (RecursionError, TypeError, ValueError):
        raise DramaShotVideoAttemptError("shot video unknown transition was rejected") from None


def build_shot_video_submission_receipt(
    record: ShotVideoAttemptRecord,
    provider_task_id: str,
) -> ShotVideoSubmissionReceipt:
    try:
        payload = {
            "attempt_id": record.attempt_id,
            "backend_id": record.spec.submission_gate.backend_id,
            "account_fingerprint": record.spec.submission_gate.account_fingerprint,
            "authorization_fingerprint": (
                record.spec.submission_gate.authorization_fingerprint
            ),
            "input_fingerprint": record.spec.input_fingerprint,
            "provider_task_id": provider_task_id,
        }
        payload["receipt_fingerprint"] = _canonical_sha256(payload)
        return ShotVideoSubmissionReceipt(**payload)
    except (RecursionError, TypeError, ValueError):
        raise DramaShotVideoAttemptError("shot video submission receipt was rejected") from None


def record_shot_video_submitted(
    ledger: EpisodeShotVideoAttemptLedger,
    record: ShotVideoAttemptRecord,
    receipt: ShotVideoSubmissionReceipt,
    *,
    expected_ledger_fingerprint: str,
) -> tuple[EpisodeShotVideoAttemptLedger, ShotVideoAttemptRecord]:
    try:
        if record.status != "started":
            raise ValueError("shot video attempt is not awaiting submission")
        payload = _record_payload(record)
        payload.update({"status": "submitted", "submission_receipt": model_to_dict(receipt)})
        replacement = _build_record(payload)
        return (
            _replace_attempt(
                ledger,
                record,
                replacement,
                expected_ledger_fingerprint=expected_ledger_fingerprint,
            ),
            replacement,
        )
    except (RecursionError, TypeError, ValueError):
        raise DramaShotVideoAttemptError("shot video submitted transition was rejected") from None


def build_shot_video_terminal_receipt(
    record: ShotVideoAttemptRecord,
    *,
    terminal_status: str,
    result_token: str | None,
    cost_reported: bool,
    actual_cost_microunits: int | None,
) -> ShotVideoTerminalReceipt:
    try:
        if record.submission_receipt is None:
            raise ValueError("shot video attempt has no submission receipt")
        payload: dict[str, Any] = {
            "submission_receipt_fingerprint": (
                record.submission_receipt.receipt_fingerprint
            ),
            "provider_task_id": record.submission_receipt.provider_task_id,
            "terminal_status": terminal_status,
            "result_token": result_token,
            "cost_reported": cost_reported,
            "actual_cost_microunits": actual_cost_microunits,
        }
        payload["receipt_fingerprint"] = _canonical_sha256(payload)
        return ShotVideoTerminalReceipt(**payload)
    except (RecursionError, TypeError, ValueError):
        raise DramaShotVideoAttemptError("shot video terminal receipt was rejected") from None


def build_shot_video_closure_receipt(
    *,
    resolution: str,
    evidence_fingerprint: str,
) -> ShotVideoAttemptClosureReceipt:
    try:
        payload: dict[str, Any] = {
            "resolution": resolution,
            "evidence_fingerprint": evidence_fingerprint,
        }
        payload["receipt_fingerprint"] = _canonical_sha256(payload)
        return ShotVideoAttemptClosureReceipt(**payload)
    except (RecursionError, TypeError, ValueError):
        raise DramaShotVideoAttemptError(
            "shot video closure receipt was rejected"
        ) from None


def close_unknown_shot_video_attempt(
    ledger: EpisodeShotVideoAttemptLedger,
    record: ShotVideoAttemptRecord,
    receipt: ShotVideoAttemptClosureReceipt,
    *,
    expected_ledger_fingerprint: str,
) -> tuple[EpisodeShotVideoAttemptLedger, ShotVideoAttemptRecord]:
    try:
        if record.status not in {"started", "submission_unknown"}:
            raise ValueError("shot video attempt is not awaiting reconciliation")
        payload = _record_payload(record)
        payload.update(
            {"status": "closed_unknown", "closure_receipt": model_to_dict(receipt)}
        )
        replacement = _build_record(payload)
        return (
            _replace_attempt(
                ledger,
                record,
                replacement,
                expected_ledger_fingerprint=expected_ledger_fingerprint,
            ),
            replacement,
        )
    except (RecursionError, TypeError, ValueError):
        raise DramaShotVideoAttemptError(
            "shot video closure transition was rejected"
        ) from None


def record_shot_video_terminal(
    ledger: EpisodeShotVideoAttemptLedger,
    record: ShotVideoAttemptRecord,
    receipt: ShotVideoTerminalReceipt,
    *,
    expected_ledger_fingerprint: str,
) -> tuple[EpisodeShotVideoAttemptLedger, ShotVideoAttemptRecord]:
    try:
        if record.status != "submitted" or record.submission_receipt is None:
            raise ValueError("shot video attempt is not submitted")
        if receipt.provider_task_id != record.submission_receipt.provider_task_id:
            raise ValueError("shot video terminal receipt uses another task")
        payload = _record_payload(record)
        payload.update(
            {
                "status": (
                    "provider_succeeded"
                    if receipt.terminal_status == "succeeded"
                    else "provider_failed"
                ),
                "terminal_receipt": model_to_dict(receipt),
            }
        )
        replacement = _build_record(payload)
        return (
            _replace_attempt(
                ledger,
                record,
                replacement,
                expected_ledger_fingerprint=expected_ledger_fingerprint,
            ),
            replacement,
        )
    except (RecursionError, TypeError, ValueError):
        raise DramaShotVideoAttemptError("shot video terminal transition was rejected") from None


def build_shot_video_artifact_receipt(
    record: ShotVideoAttemptRecord,
    *,
    artifact_sha256: str,
    artifact_size_bytes: int,
    duration_milliseconds: int,
    width: int,
    height: int,
    has_audio_track: bool,
) -> ShotVideoAttemptArtifactReceipt:
    try:
        payload: dict[str, Any] = {
            "media_type": "video/mp4",
            "staging_path": record.staging_path,
            "sha256": artifact_sha256,
            "size_bytes": artifact_size_bytes,
            "duration_milliseconds": duration_milliseconds,
            "width": width,
            "height": height,
            "has_audio_track": has_audio_track,
        }
        payload["receipt_fingerprint"] = _canonical_sha256(payload)
        return ShotVideoAttemptArtifactReceipt(**payload)
    except (RecursionError, TypeError, ValueError):
        raise DramaShotVideoAttemptError("shot video artifact receipt was rejected") from None


def record_shot_video_artifact_received(
    ledger: EpisodeShotVideoAttemptLedger,
    record: ShotVideoAttemptRecord,
    receipt: ShotVideoAttemptArtifactReceipt,
    *,
    expected_ledger_fingerprint: str,
) -> tuple[EpisodeShotVideoAttemptLedger, ShotVideoAttemptRecord]:
    try:
        if record.status != "provider_succeeded" or receipt.staging_path != record.staging_path:
            raise ValueError("shot video attempt is not ready for an artifact")
        payload = _record_payload(record)
        payload.update({"status": "artifact_received", "artifact_receipt": model_to_dict(receipt)})
        replacement = _build_record(payload)
        return (
            _replace_attempt(
                ledger,
                record,
                replacement,
                expected_ledger_fingerprint=expected_ledger_fingerprint,
            ),
            replacement,
        )
    except (RecursionError, TypeError, ValueError):
        raise DramaShotVideoAttemptError("shot video artifact transition was rejected") from None


def complete_shot_video_attempt(
    ledger: EpisodeShotVideoAttemptLedger,
    record: ShotVideoAttemptRecord,
    candidate: ShotVideoCandidate,
    *,
    post_manifest_fingerprint: str,
    expected_ledger_fingerprint: str,
) -> tuple[EpisodeShotVideoAttemptLedger, ShotVideoAttemptRecord]:
    try:
        receipt = record.artifact_receipt
        if record.status != "artifact_received" or receipt is None:
            raise ValueError("shot video attempt has no artifact receipt")
        if (
            candidate.season_no != record.spec.season_no
            or candidate.episode_no != record.spec.episode_no
            or candidate.shot_id != record.spec.shot_id
            or candidate.source_plan_fingerprint != record.spec.source_plan_fingerprint
            or candidate.request_fingerprint != record.spec.request_fingerprint
            or candidate.artifact.sha256 != receipt.sha256
            or candidate.artifact.size_bytes != receipt.size_bytes
            or candidate.artifact.duration_milliseconds != receipt.duration_milliseconds
            or candidate.artifact.width != receipt.width
            or candidate.artifact.height != receipt.height
            or candidate.artifact.has_audio_track != receipt.has_audio_track
            or candidate.is_placeholder
        ):
            raise ValueError("shot video candidate does not match its attempt receipt")
        payload = _record_payload(record)
        payload.update(
            {
                "status": "succeeded",
                "candidate_id": candidate.candidate_id,
                "candidate_fingerprint": candidate.candidate_fingerprint,
                "post_manifest_fingerprint": post_manifest_fingerprint,
            }
        )
        replacement = _build_record(payload)
        return (
            _replace_attempt(
                ledger,
                record,
                replacement,
                expected_ledger_fingerprint=expected_ledger_fingerprint,
            ),
            replacement,
        )
    except (RecursionError, TypeError, ValueError):
        raise DramaShotVideoAttemptError("shot video attempt completion was rejected") from None
