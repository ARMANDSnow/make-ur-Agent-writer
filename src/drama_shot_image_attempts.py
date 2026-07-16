"""Pure C3 provider capability and once-only shot-image attempt transitions."""

from __future__ import annotations

import hashlib
from typing import Any, Mapping

from .drama_schemas import (
    EpisodeShotImageAttemptLedger,
    EpisodeShotImageCandidateManifest,
    EpisodeShotImagePlan,
    ShotImageAttemptArtifactReceipt,
    ShotImageAttemptRecord,
    ShotImageAttemptSpec,
    ShotImageAttemptStatus,
    ShotImageCandidate,
    ShotImageProviderCapability,
    _canonical_sha256,
)
from .schemas import model_to_dict


class DramaShotImageAttemptError(ValueError):
    """Bounded public failure for caller-controlled attempt inputs."""


def build_shot_image_provider_capability(
    *,
    backend_id: str,
    capability_version: str,
    max_reference_images: int,
) -> ShotImageProviderCapability:
    try:
        payload: dict[str, Any] = {
            "schema_version": 1,
            "backend_id": backend_id,
            "capability_version": capability_version,
            "supports_reference_images": max_reference_images > 0,
            "max_reference_images": max_reference_images,
            "supported_media_types": ["image/png"],
            "response_mode": "sync_png",
        }
        payload["capability_fingerprint"] = _canonical_sha256(payload)
        return ShotImageProviderCapability(**payload)
    except (RecursionError, TypeError, ValueError):
        raise DramaShotImageAttemptError("shot image provider capability was rejected") from None


def _as_plan(value: EpisodeShotImagePlan | Mapping[str, Any]) -> EpisodeShotImagePlan:
    return value if isinstance(value, EpisodeShotImagePlan) else EpisodeShotImagePlan(**value)


def _as_manifest(
    value: EpisodeShotImageCandidateManifest | Mapping[str, Any],
) -> EpisodeShotImageCandidateManifest:
    return (
        value
        if isinstance(value, EpisodeShotImageCandidateManifest)
        else EpisodeShotImageCandidateManifest(**value)
    )


def _as_capability(
    value: ShotImageProviderCapability | Mapping[str, Any],
) -> ShotImageProviderCapability:
    return (
        value
        if isinstance(value, ShotImageProviderCapability)
        else ShotImageProviderCapability(**value)
    )


def build_shot_image_attempt_spec(
    plan: EpisodeShotImagePlan | Mapping[str, Any],
    manifest: EpisodeShotImageCandidateManifest | Mapping[str, Any],
    *,
    shot_id: str,
    capability: ShotImageProviderCapability | Mapping[str, Any],
    provider_fingerprint: str,
) -> ShotImageAttemptSpec:
    """Freeze one exact C1 request without reordering or re-clipping references."""

    try:
        current_plan = _as_plan(plan)
        current_manifest = _as_manifest(manifest)
        current_capability = _as_capability(capability)
        if (
            current_manifest.season_no != current_plan.season_no
            or current_manifest.episode_no != current_plan.episode_no
            or current_manifest.source_plan_fingerprint != current_plan.plan_fingerprint
        ):
            raise ValueError("candidate manifest does not match the shot image plan")
        request = next(
            (item for item in current_plan.shot_specs if item.shot_id == shot_id),
            None,
        )
        pool = next(
            (item for item in current_manifest.shots if item.shot_id == shot_id),
            None,
        )
        if request is None or pool is None:
            raise ValueError("shot image attempt target is unknown")
        if request.status != "assembled" or pool.source_status != "assembled":
            raise ValueError("blocked shot cannot start an image attempt")
        if pool.current_request_fingerprint != request.request_fingerprint:
            raise ValueError("candidate manifest request is stale")
        references = [model_to_dict(item) for item in request.image_references]
        if len(references) > current_capability.max_reference_images:
            raise ValueError("provider capability cannot consume the exact C1 references")
        if references and not current_capability.supports_reference_images:
            raise ValueError("provider capability cannot consume image references")
        prompt_sha256 = hashlib.sha256(request.image_prompt.encode("utf-8")).hexdigest()
        payload: dict[str, Any] = {
            "schema_version": 1,
            "season_no": current_plan.season_no,
            "episode_no": current_plan.episode_no,
            "shot_id": request.shot_id,
            "source_plan_fingerprint": current_plan.plan_fingerprint,
            "request_fingerprint": request.request_fingerprint,
            "pre_manifest_fingerprint": current_manifest.manifest_fingerprint,
            "backend_id": current_capability.backend_id,
            "provider_fingerprint": provider_fingerprint,
            "capability": model_to_dict(current_capability),
            "prompt_sha256": prompt_sha256,
            "references": references,
            "references_fingerprint": _canonical_sha256(references),
            "output_media_type": "image/png",
        }
        payload["input_fingerprint"] = _canonical_sha256(payload)
        return ShotImageAttemptSpec(**payload)
    except DramaShotImageAttemptError:
        raise
    except (RecursionError, TypeError, ValueError):
        raise DramaShotImageAttemptError("shot image attempt specification was rejected") from None


def build_empty_shot_image_attempt_ledger(
    plan: EpisodeShotImagePlan | Mapping[str, Any],
) -> EpisodeShotImageAttemptLedger:
    try:
        current = _as_plan(plan)
        payload: dict[str, Any] = {
            "schema_version": 1,
            "generator_version": "shot-image-attempts-v1",
            "season_no": current.season_no,
            "episode_no": current.episode_no,
            "revision": 0,
            "attempts": [],
        }
        payload["ledger_fingerprint"] = _canonical_sha256(payload)
        return EpisodeShotImageAttemptLedger(**payload)
    except (RecursionError, TypeError, ValueError):
        raise DramaShotImageAttemptError("shot image attempt ledger was rejected") from None


def _record_payload(record: ShotImageAttemptRecord) -> dict[str, Any]:
    return record.model_dump(exclude={"record_fingerprint"})


def _build_record(payload: Mapping[str, Any]) -> ShotImageAttemptRecord:
    current = dict(payload)
    current["record_fingerprint"] = _canonical_sha256(current)
    return ShotImageAttemptRecord(**current)


def _ledger_with_attempts(
    ledger: EpisodeShotImageAttemptLedger,
    attempts: list[ShotImageAttemptRecord],
) -> EpisodeShotImageAttemptLedger:
    payload: dict[str, Any] = {
        "schema_version": 1,
        "generator_version": "shot-image-attempts-v1",
        "season_no": ledger.season_no,
        "episode_no": ledger.episode_no,
        "revision": ledger.revision + 1,
        "attempts": [model_to_dict(item) for item in attempts],
    }
    payload["ledger_fingerprint"] = _canonical_sha256(payload)
    return EpisodeShotImageAttemptLedger(**payload)


def start_shot_image_attempt(
    ledger: EpisodeShotImageAttemptLedger,
    spec: ShotImageAttemptSpec,
    *,
    expected_ledger_fingerprint: str,
) -> tuple[EpisodeShotImageAttemptLedger, ShotImageAttemptRecord]:
    try:
        if expected_ledger_fingerprint != ledger.ledger_fingerprint:
            raise ValueError("shot image attempt ledger changed")
        if spec.season_no != ledger.season_no or spec.episode_no != ledger.episode_no:
            raise ValueError("shot image attempt spec belongs to another episode")
        same_shot = [item for item in ledger.attempts if item.spec.shot_id == spec.shot_id]
        if same_shot and same_shot[-1].status not in {
            "timeout",
            "network_error",
            "provider_error",
            "local_error",
            "succeeded",
        }:
            raise ValueError("previous shot image attempt requires reconciliation")
        attempt_no = len(same_shot) + 1
        if attempt_no > 32:
            raise ValueError("shot image attempt limit reached")
        attempt_id = f"sia_{_canonical_sha256({'input_fingerprint': spec.input_fingerprint, 'attempt_no': attempt_no})[:24]}"
        staging_path = (
            f"logs/drama_shot_images/episode_{spec.episode_no:02d}/"
            f"{spec.shot_id}/{attempt_id}.png"
        )
        record = _build_record(
            {
                "schema_version": 1,
                "attempt_id": attempt_id,
                "attempt_no": attempt_no,
                "spec": model_to_dict(spec),
                "status": "started",
                "staging_path": staging_path,
                "artifact_receipt": None,
                "candidate_id": None,
                "candidate_fingerprint": None,
                "post_manifest_fingerprint": None,
            }
        )
        updated = _ledger_with_attempts(ledger, [*ledger.attempts, record])
        return updated, record
    except (RecursionError, TypeError, ValueError):
        raise DramaShotImageAttemptError("shot image attempt start was rejected") from None


def build_shot_image_attempt_receipt(
    record: ShotImageAttemptRecord,
    *,
    artifact_sha256: str,
    artifact_size_bytes: int,
    width: int,
    height: int,
) -> ShotImageAttemptArtifactReceipt:
    try:
        payload: dict[str, Any] = {
            "media_type": "image/png",
            "staging_path": record.staging_path,
            "sha256": artifact_sha256,
            "size_bytes": artifact_size_bytes,
            "width": width,
            "height": height,
        }
        payload["receipt_fingerprint"] = _canonical_sha256(payload)
        return ShotImageAttemptArtifactReceipt(**payload)
    except (RecursionError, TypeError, ValueError):
        raise DramaShotImageAttemptError("shot image attempt receipt was rejected") from None


def _replace_attempt(
    ledger: EpisodeShotImageAttemptLedger,
    record: ShotImageAttemptRecord,
    replacement: ShotImageAttemptRecord,
    *,
    expected_ledger_fingerprint: str,
) -> EpisodeShotImageAttemptLedger:
    if ledger.ledger_fingerprint != expected_ledger_fingerprint:
        raise ValueError("shot image attempt ledger changed")
    matches = [index for index, item in enumerate(ledger.attempts) if item.attempt_id == record.attempt_id]
    if len(matches) != 1 or ledger.attempts[matches[0]].record_fingerprint != record.record_fingerprint:
        raise ValueError("shot image attempt record changed")
    attempts = list(ledger.attempts)
    attempts[matches[0]] = replacement
    return _ledger_with_attempts(ledger, attempts)


def record_shot_image_artifact_received(
    ledger: EpisodeShotImageAttemptLedger,
    record: ShotImageAttemptRecord,
    receipt: ShotImageAttemptArtifactReceipt,
    *,
    expected_ledger_fingerprint: str,
) -> tuple[EpisodeShotImageAttemptLedger, ShotImageAttemptRecord]:
    try:
        if record.status != "started" or receipt.staging_path != record.staging_path:
            raise ValueError("shot image attempt cannot accept this artifact")
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
        raise DramaShotImageAttemptError("shot image artifact receipt was rejected") from None


def fail_shot_image_attempt(
    ledger: EpisodeShotImageAttemptLedger,
    record: ShotImageAttemptRecord,
    *,
    status: ShotImageAttemptStatus,
    expected_ledger_fingerprint: str,
) -> tuple[EpisodeShotImageAttemptLedger, ShotImageAttemptRecord]:
    try:
        if record.status != "started" or status not in {
            "timeout",
            "network_error",
            "provider_error",
            "local_error",
        }:
            raise ValueError("shot image attempt failure transition is invalid")
        payload = _record_payload(record)
        payload["status"] = status
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
        raise DramaShotImageAttemptError("shot image attempt failure was rejected") from None


def discard_not_sent_shot_image_attempt(
    ledger: EpisodeShotImageAttemptLedger,
    record: ShotImageAttemptRecord,
    *,
    expected_ledger_fingerprint: str,
) -> EpisodeShotImageAttemptLedger:
    """Release only an exact started marker proven not to have been submitted."""

    try:
        if ledger.ledger_fingerprint != expected_ledger_fingerprint or record.status != "started":
            raise ValueError("shot image attempt cannot be released")
        matches = [
            index
            for index, item in enumerate(ledger.attempts)
            if item.attempt_id == record.attempt_id
            and item.record_fingerprint == record.record_fingerprint
        ]
        if len(matches) != 1 or matches[0] != len(ledger.attempts) - 1:
            raise ValueError("only the latest exact attempt can be released")
        same_shot = [
            item for item in ledger.attempts if item.spec.shot_id == record.spec.shot_id
        ]
        if not same_shot or same_shot[-1].attempt_id != record.attempt_id:
            raise ValueError("shot image attempt is not the latest for its shot")
        return _ledger_with_attempts(ledger, list(ledger.attempts[:-1]))
    except (RecursionError, TypeError, ValueError):
        raise DramaShotImageAttemptError("shot image not-sent release was rejected") from None


def complete_shot_image_attempt(
    ledger: EpisodeShotImageAttemptLedger,
    record: ShotImageAttemptRecord,
    candidate: ShotImageCandidate,
    *,
    post_manifest_fingerprint: str,
    expected_ledger_fingerprint: str,
) -> tuple[EpisodeShotImageAttemptLedger, ShotImageAttemptRecord]:
    try:
        if record.status != "artifact_received" or record.artifact_receipt is None:
            raise ValueError("shot image attempt has no durable artifact receipt")
        if (
            candidate.season_no != record.spec.season_no
            or candidate.episode_no != record.spec.episode_no
            or candidate.shot_id != record.spec.shot_id
            or candidate.source_plan_fingerprint != record.spec.source_plan_fingerprint
            or candidate.request_fingerprint != record.spec.request_fingerprint
            or candidate.artifact.sha256 != record.artifact_receipt.sha256
            or candidate.artifact.size_bytes != record.artifact_receipt.size_bytes
            or candidate.artifact.width != record.artifact_receipt.width
            or candidate.artifact.height != record.artifact_receipt.height
        ):
            raise ValueError("shot image candidate does not match its attempt receipt")
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
        raise DramaShotImageAttemptError("shot image attempt completion was rejected") from None


def latest_shot_image_attempt(
    ledger: EpisodeShotImageAttemptLedger,
    *,
    shot_id: str,
    input_fingerprint: str | None = None,
) -> ShotImageAttemptRecord | None:
    matches = [item for item in ledger.attempts if item.spec.shot_id == shot_id]
    if input_fingerprint is not None:
        matches = [item for item in matches if item.spec.input_fingerprint == input_fingerprint]
    return matches[-1] if matches else None
