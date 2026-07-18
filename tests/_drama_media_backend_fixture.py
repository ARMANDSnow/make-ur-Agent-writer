"""Secret-free G3 registry fixtures shared by G1-G4 media tests."""

from __future__ import annotations

from src import (
    drama_shot_image_attempts,
    drama_shot_video_attempts,
    drama_tts_attempts,
)
from src.drama_media_backends import base, registry


PROVIDER_ID = "fixture-provider"
MODEL_ID = "fixture-model-v1"


def build_registry(
    *,
    media_kind: str,
    backend_id: str,
    provider_fingerprint: str,
    model_fingerprint: str,
):
    if media_kind == "image":
        source = (
            drama_shot_image_attempts.build_shot_image_provider_capability(
                backend_id=backend_id,
                capability_version="v1",
                max_reference_images=4,
            )
        )
        registration = base.registration_from_shot_image_capability(
            source,
            provider_id=PROVIDER_ID,
            model_id=MODEL_ID,
            provider_fingerprint=provider_fingerprint,
            model_fingerprint=model_fingerprint,
        )
    elif media_kind == "video":
        source = (
            drama_shot_video_attempts.build_shot_video_provider_capability(
                backend_id=backend_id,
                capability_version="v1",
                supported_modes=["image_to_video", "reference_to_video"],
                supports_tail_frame=True,
                max_reference_images=3,
                supported_durations_seconds=[3, 5],
                supported_resolutions=[(720, 1280)],
            )
        )
        registration = base.registration_from_shot_video_capability(
            source,
            provider_id=PROVIDER_ID,
            model_id=MODEL_ID,
            provider_fingerprint=provider_fingerprint,
            model_fingerprint=model_fingerprint,
        )
    elif media_kind == "audio":
        source = drama_tts_attempts.build_tts_provider_capability(
            backend_id=backend_id,
            capability_version="v1",
            provider_id=PROVIDER_ID,
            model_id=MODEL_ID,
            sample_rate=16000,
            max_text_characters=220,
        )
        registration = base.registration_from_tts_capability(
            source,
            provider_fingerprint=provider_fingerprint,
            model_fingerprint=model_fingerprint,
        )
    else:
        raise ValueError("unsupported fixture media kind")
    return registry.build_backend_registry([registration])
