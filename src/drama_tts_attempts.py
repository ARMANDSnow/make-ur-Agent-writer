"""Pure E2 provider capability and once-only TTS attempt transitions."""

from __future__ import annotations

import hashlib
from typing import Any

from .drama_schemas import (
    TtsAttemptRecord,
    TtsAttemptSpec,
    TtsAudioArtifact,
    TtsAuthorization,
    TtsProviderCapability,
    TtsSubmissionReceipt,
    UtteranceSpec,
    _canonical_sha256,
)
from .schemas import model_to_dict


class DramaTtsAttemptError(ValueError):
    pass


def _build(model: Any, payload: dict[str, Any], fingerprint_field: str) -> Any:
    try:
        payload[fingerprint_field] = _canonical_sha256(payload)
        return model(**payload)
    except (RecursionError, TypeError, ValueError):
        raise DramaTtsAttemptError("TTS attempt input was rejected") from None


def build_tts_provider_capability(
    *, backend_id: str, capability_version: str, provider_id: str, model_id: str,
    sample_rate: int = 16000, max_text_characters: int = 220,
) -> TtsProviderCapability:
    return _build(TtsProviderCapability, {
        "schema_version": 1, "backend_id": backend_id,
        "capability_version": capability_version, "provider_id": provider_id,
        "model_id": model_id,
        "task_kind": "text_to_speech", "output_media_type": "audio/wav",
        "sample_rate": sample_rate, "max_text_characters": max_text_characters,
    }, "capability_fingerprint")


def build_tts_authorization(
    utterance: UtteranceSpec, capability: TtsProviderCapability, *,
    provider_fingerprint: str, model_fingerprint: str,
    account_fingerprint: str, endpoint_fingerprint: str, auth_fingerprint: str,
) -> TtsAuthorization:
    payload = {
        "schema_version": 1, "utterance_id": utterance.utterance_id,
        "utterance_spec_fingerprint": utterance.spec_fingerprint,
        "capability_fingerprint": capability.capability_fingerprint,
        "provider_fingerprint": provider_fingerprint,
        "model_fingerprint": model_fingerprint,
        "account_fingerprint": account_fingerprint,
        "endpoint_fingerprint": endpoint_fingerprint,
        "auth_fingerprint": auth_fingerprint,
        "authorization_scope": "utterance_tts_once", "confirmed": True,
        "max_synthesis_posts": 1,
    }
    fingerprint = _canonical_sha256(payload)
    payload["authorization_id"] = f"ttsauth_{fingerprint[:24]}"
    payload["authorization_fingerprint"] = fingerprint
    try:
        return TtsAuthorization(**payload)
    except (RecursionError, TypeError, ValueError):
        raise DramaTtsAttemptError("TTS authorization was rejected") from None


def build_tts_attempt_spec(
    utterance: UtteranceSpec, capability: TtsProviderCapability,
    authorization: TtsAuthorization,
) -> TtsAttemptSpec:
    if len(utterance.text) > capability.max_text_characters:
        raise DramaTtsAttemptError("TTS utterance exceeds provider capability")
    if (
        utterance.provider_id != capability.provider_id
        or utterance.model_id != capability.model_id
    ):
        raise DramaTtsAttemptError("TTS capability does not match utterance voice")
    payload = {
        "schema_version": 1, "episode_no": utterance.episode_no,
        "utterance_id": utterance.utterance_id,
        "utterance_spec_fingerprint": utterance.spec_fingerprint,
        "provider_id": utterance.provider_id, "model_id": utterance.model_id,
        "text_sha256": hashlib.sha256(utterance.text.encode("utf-8")).hexdigest(),
        "output_path": (
            f"outputs/drama/audio/episode_{utterance.episode_no:03d}/"
            f"{utterance.utterance_id}.wav"
        ),
        "capability": model_to_dict(capability),
        "authorization": model_to_dict(authorization),
    }
    return _build(TtsAttemptSpec, payload, "input_fingerprint")


def _record(spec: TtsAttemptSpec, *, status: str,
            submission: TtsSubmissionReceipt | None = None,
            artifact: TtsAudioArtifact | None = None) -> TtsAttemptRecord:
    payload = {"schema_version": 1, "spec": model_to_dict(spec), "status": status,
               "submission": model_to_dict(submission) if submission else None,
               "artifact": model_to_dict(artifact) if artifact else None}
    fingerprint = _canonical_sha256(payload)
    return TtsAttemptRecord(
        attempt_id=f"ttsattempt_{spec.input_fingerprint[:24]}",
        record_fingerprint=fingerprint, **payload,
    )


def start_tts_attempt(spec: TtsAttemptSpec) -> TtsAttemptRecord:
    return _record(spec, status="started")


def mark_tts_not_sent(record: TtsAttemptRecord) -> TtsAttemptRecord:
    if record.status != "started":
        raise DramaTtsAttemptError("TTS not-sent transition was rejected")
    return _record(record.spec, status="not_sent")


def mark_tts_submission_unknown(record: TtsAttemptRecord) -> TtsAttemptRecord:
    if record.status != "started":
        raise DramaTtsAttemptError("TTS unknown transition was rejected")
    return _record(record.spec, status="submission_unknown")


def record_tts_submission(record: TtsAttemptRecord, provider_request_id: str) -> TtsAttemptRecord:
    if record.status != "started":
        raise DramaTtsAttemptError("TTS submission transition was rejected")
    receipt = _build(TtsSubmissionReceipt, {
        "schema_version": 1, "provider_request_id": provider_request_id,
    }, "receipt_fingerprint")
    return _record(record.spec, status="submitted", submission=receipt)


def record_tts_provider_failed(
    record: TtsAttemptRecord, provider_request_id: str
) -> TtsAttemptRecord:
    submitted = record_tts_submission(record, provider_request_id)
    return _record(
        record.spec, status="provider_failed", submission=submitted.submission
    )


def record_tts_artifact(record: TtsAttemptRecord, artifact: TtsAudioArtifact) -> TtsAttemptRecord:
    if record.status != "submitted" or record.submission is None:
        raise DramaTtsAttemptError("TTS artifact transition was rejected")
    if artifact.path != record.spec.output_path:
        raise DramaTtsAttemptError("TTS artifact belongs to another attempt")
    return _record(record.spec, status="artifact_received",
                   submission=record.submission, artifact=artifact)


def complete_tts_attempt(record: TtsAttemptRecord) -> TtsAttemptRecord:
    if record.status != "artifact_received":
        raise DramaTtsAttemptError("TTS completion transition was rejected")
    return _record(record.spec, status="succeeded",
                   submission=record.submission, artifact=record.artifact)
