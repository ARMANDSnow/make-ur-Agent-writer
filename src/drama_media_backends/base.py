"""Pure conversions from existing C/D/E capabilities into G3 descriptors.

The registry deliberately stores no adapter callable, module path, endpoint,
credential, prompt, provider response, or paid receipt.  Network execution is
owned by a later iteration.
"""

from __future__ import annotations

from typing import Any

from ..drama_schemas import (
    DramaMediaBackendCapability,
    DramaMediaBackendRegistration,
    ShotImageProviderCapability,
    ShotVideoProviderCapability,
    TtsProviderCapability,
    _canonical_sha256,
)
from ..schemas import model_to_dict


class DramaMediaBackendError(ValueError):
    """Bounded failure for invalid static backend declarations."""


def _build_capability(payload: dict[str, Any]) -> DramaMediaBackendCapability:
    try:
        payload["capability_fingerprint"] = _canonical_sha256(payload)
        return DramaMediaBackendCapability(**payload)
    except (RecursionError, TypeError, ValueError):
        raise DramaMediaBackendError(
            "media backend capability was rejected"
        ) from None


def _build_registration(
    *,
    provider_id: str,
    model_id: str,
    provider_fingerprint: str,
    model_fingerprint: str,
    capability: DramaMediaBackendCapability,
) -> DramaMediaBackendRegistration:
    try:
        payload: dict[str, Any] = {
            "schema_version": 1,
            "provider_id": provider_id,
            "media_kind": capability.media_kind,
            "model_id": model_id,
            "provider_fingerprint": provider_fingerprint,
            "model_fingerprint": model_fingerprint,
            "backend_id": capability.backend_id,
            "capability": capability.model_dump(mode="json"),
        }
        payload["registration_fingerprint"] = _canonical_sha256(payload)
        return DramaMediaBackendRegistration(**payload)
    except (RecursionError, TypeError, ValueError):
        raise DramaMediaBackendError(
            "media backend registration was rejected"
        ) from None


def registration_from_shot_image_capability(
    capability: ShotImageProviderCapability,
    *,
    provider_id: str,
    model_id: str,
    provider_fingerprint: str,
    model_fingerprint: str,
) -> DramaMediaBackendRegistration:
    """Normalize C3 without mutating or replacing its original fingerprint."""

    if not isinstance(capability, ShotImageProviderCapability):
        raise DramaMediaBackendError("shot image capability was rejected")
    try:
        capability = ShotImageProviderCapability(**model_to_dict(capability))
    except (RecursionError, TypeError, ValueError):
        raise DramaMediaBackendError("shot image capability was rejected") from None
    generic = _build_capability(
        {
            "schema_version": 1,
            "backend_id": capability.backend_id,
            "capability_version": capability.capability_version,
            "media_kind": "image",
            "stage": "image-generate",
            "submission_mode": "synchronous",
            "supports_poll": False,
            "supports_resume": False,
            "supports_download": False,
            "supports_tail_frame": False,
            "max_reference_images": capability.max_reference_images,
            "supported_modes": ["image_generation"],
            "supported_durations_seconds": [],
            "supported_resolutions": [],
            "output_media_types": list(capability.supported_media_types),
            "sample_rates": [],
            "max_text_characters": None,
            "source_capability_fingerprint": capability.capability_fingerprint,
        }
    )
    return _build_registration(
        provider_id=provider_id,
        model_id=model_id,
        provider_fingerprint=provider_fingerprint,
        model_fingerprint=model_fingerprint,
        capability=generic,
    )


def registration_from_shot_video_capability(
    capability: ShotVideoProviderCapability,
    *,
    provider_id: str,
    model_id: str,
    provider_fingerprint: str,
    model_fingerprint: str,
) -> DramaMediaBackendRegistration:
    """Normalize D3 while retaining its exact source capability identity."""

    if not isinstance(capability, ShotVideoProviderCapability):
        raise DramaMediaBackendError("shot video capability was rejected")
    try:
        capability = ShotVideoProviderCapability(**model_to_dict(capability))
    except (RecursionError, TypeError, ValueError):
        raise DramaMediaBackendError("shot video capability was rejected") from None
    generic = _build_capability(
        {
            "schema_version": 1,
            "backend_id": capability.backend_id,
            "capability_version": capability.capability_version,
            "media_kind": "video",
            "stage": "video-generate",
            "submission_mode": "asynchronous",
            "supports_poll": capability.supports_async_submission,
            "supports_resume": capability.supports_poll_resume,
            "supports_download": True,
            "supports_tail_frame": capability.supports_tail_frame,
            "max_reference_images": capability.max_reference_images,
            "supported_modes": list(capability.supported_modes),
            "supported_durations_seconds": list(
                capability.supported_durations_seconds
            ),
            "supported_resolutions": [
                model_to_dict(item)
                for item in capability.supported_resolutions
            ],
            "output_media_types": [capability.output_media_type],
            "sample_rates": [],
            "max_text_characters": None,
            "source_capability_fingerprint": capability.capability_fingerprint,
        }
    )
    return _build_registration(
        provider_id=provider_id,
        model_id=model_id,
        provider_fingerprint=provider_fingerprint,
        model_fingerprint=model_fingerprint,
        capability=generic,
    )


def registration_from_tts_capability(
    capability: TtsProviderCapability,
    *,
    provider_fingerprint: str,
    model_fingerprint: str,
) -> DramaMediaBackendRegistration:
    """Normalize E2 using the provider/model already frozen by its capability."""

    if not isinstance(capability, TtsProviderCapability):
        raise DramaMediaBackendError("TTS capability was rejected")
    try:
        capability = TtsProviderCapability(**model_to_dict(capability))
    except (RecursionError, TypeError, ValueError):
        raise DramaMediaBackendError("TTS capability was rejected") from None
    generic = _build_capability(
        {
            "schema_version": 1,
            "backend_id": capability.backend_id,
            "capability_version": capability.capability_version,
            "media_kind": "audio",
            "stage": "tts-synthesize",
            "submission_mode": "synchronous",
            "supports_poll": False,
            "supports_resume": False,
            "supports_download": True,
            "supports_tail_frame": False,
            "max_reference_images": 0,
            "supported_modes": ["text_to_speech"],
            "supported_durations_seconds": [],
            "supported_resolutions": [],
            "output_media_types": [capability.output_media_type],
            "sample_rates": [capability.sample_rate],
            "max_text_characters": capability.max_text_characters,
            "source_capability_fingerprint": capability.capability_fingerprint,
        }
    )
    return _build_registration(
        provider_id=capability.provider_id,
        model_id=capability.model_id,
        provider_fingerprint=provider_fingerprint,
        model_fingerprint=model_fingerprint,
        capability=generic,
    )
