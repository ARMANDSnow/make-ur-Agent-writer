"""Static, secret-free G3 media backend contracts and registry."""

from .base import (
    DramaMediaBackendError,
    registration_from_shot_image_capability,
    registration_from_shot_video_capability,
    registration_from_tts_capability,
)
from .registry import (
    build_backend_registry,
    build_backend_registry_projection,
    resolve_task_backend,
)

__all__ = [
    "DramaMediaBackendError",
    "build_backend_registry",
    "build_backend_registry_projection",
    "registration_from_shot_image_capability",
    "registration_from_shot_video_capability",
    "registration_from_tts_capability",
    "resolve_task_backend",
]
