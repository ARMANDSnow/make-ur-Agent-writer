"""Immutable G3 backend registry and attempt-frozen task resolution."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ..drama_schemas import (
    DramaMediaBackendBinding,
    DramaMediaBackendRegistration,
    DramaMediaBackendRegistrySnapshot,
    DramaMediaTask,
    _canonical_sha256,
)
from ..schemas import model_to_dict
from .base import DramaMediaBackendError


_PRE_SUBMISSION_STATES = frozenset({"planned", "ready", "claimed"})


def build_backend_registry(
    registrations: Sequence[DramaMediaBackendRegistration],
) -> DramaMediaBackendRegistrySnapshot:
    """Build a canonical snapshot from explicit in-process declarations only."""

    try:
        if (
            isinstance(registrations, (str, bytes, bytearray, Mapping))
            or not isinstance(registrations, Sequence)
            or not registrations
            or any(
                not isinstance(item, DramaMediaBackendRegistration)
                for item in registrations
            )
        ):
            raise ValueError("media backend declarations are invalid")
        validated = [
            DramaMediaBackendRegistration(**item.model_dump(mode="json"))
            for item in registrations
        ]
        ordered = sorted(
            validated,
            key=lambda item: (
                item.provider_id,
                item.media_kind,
                item.model_id,
            ),
        )
        payload: dict[str, Any] = {
            "schema_version": 1,
            "registrations": [
                item.model_dump(mode="json") for item in ordered
            ],
        }
        payload["registry_fingerprint"] = _canonical_sha256(payload)
        return DramaMediaBackendRegistrySnapshot(**payload)
    except DramaMediaBackendError:
        raise
    except (RecursionError, TypeError, ValueError):
        raise DramaMediaBackendError(
            "media backend registry was rejected"
        ) from None


def _binding_matches_task(
    binding: DramaMediaBackendBinding,
    task: DramaMediaTask,
    *,
    provider_fingerprint: str,
    model_fingerprint: str,
) -> bool:
    return (
        binding.task_id == task.task_id
        and binding.task_input_fingerprint == task.input_fingerprint
        and binding.backend_id == task.backend_id
        and binding.media_kind == task.media_kind
        and binding.provider_fingerprint == task.provider_fingerprint
        and binding.model_fingerprint == task.model_fingerprint
        and binding.provider_fingerprint == provider_fingerprint
        and binding.model_fingerprint == model_fingerprint
    )


def resolve_task_backend(
    registry: DramaMediaBackendRegistrySnapshot,
    task: DramaMediaTask,
    *,
    provider_id: str,
    model_id: str,
    provider_fingerprint: str,
    model_fingerprint: str,
    frozen_binding: DramaMediaBackendBinding | None = None,
) -> DramaMediaBackendBinding:
    """Resolve once before submission; later states require the exact snapshot."""

    try:
        if (
            not isinstance(registry, DramaMediaBackendRegistrySnapshot)
            or not isinstance(task, DramaMediaTask)
        ):
            raise ValueError("media backend resolution input is invalid")
        registry = DramaMediaBackendRegistrySnapshot(
            **registry.model_dump(mode="json")
        )
        task = DramaMediaTask(**model_to_dict(task))
        if frozen_binding is not None:
            if not isinstance(frozen_binding, DramaMediaBackendBinding):
                raise ValueError("frozen media backend binding changed")
            frozen_binding = DramaMediaBackendBinding(
                **frozen_binding.model_dump(mode="json")
            )
            if (
                not _binding_matches_task(
                    frozen_binding,
                    task,
                    provider_fingerprint=provider_fingerprint,
                    model_fingerprint=model_fingerprint,
                )
                or frozen_binding.provider_id != provider_id
                or frozen_binding.model_id != model_id
            ):
                raise ValueError("frozen media backend binding changed")
            return frozen_binding
        if task.state not in _PRE_SUBMISSION_STATES:
            raise ValueError(
                "submitted media task requires its frozen backend binding"
            )
        if (
            task.provider_fingerprint != provider_fingerprint
            or task.model_fingerprint != model_fingerprint
        ):
            raise ValueError("media task provider identity changed")
        matches = [
            item
            for item in registry.registrations
            if (
                item.provider_id,
                item.media_kind,
                item.model_id,
            )
            == (provider_id, task.media_kind, model_id)
        ]
        if len(matches) != 1:
            raise ValueError("media backend combination is not registered")
        registration = matches[0]
        if registration.backend_id != task.backend_id:
            raise ValueError("media task backend identity changed")
        if (
            registration.provider_fingerprint
            != task.provider_fingerprint
            or registration.model_fingerprint
            != task.model_fingerprint
        ):
            raise ValueError("registered media provider identity changed")
        payload: dict[str, Any] = {
            "schema_version": 1,
            "task_id": task.task_id,
            "task_input_fingerprint": task.input_fingerprint,
            "backend_id": task.backend_id,
            "provider_id": registration.provider_id,
            "media_kind": task.media_kind,
            "model_id": registration.model_id,
            "provider_fingerprint": registration.provider_fingerprint,
            "model_fingerprint": registration.model_fingerprint,
            "source_capability_fingerprint": (
                registration.capability.source_capability_fingerprint
            ),
            "capability_fingerprint": (
                registration.capability.capability_fingerprint
            ),
            "registration_fingerprint": (
                registration.registration_fingerprint
            ),
            "registry_fingerprint": registry.registry_fingerprint,
            "registration": registration.model_dump(mode="json"),
        }
        payload["binding_fingerprint"] = _canonical_sha256(payload)
        return DramaMediaBackendBinding(**payload)
    except DramaMediaBackendError:
        raise
    except (RecursionError, TypeError, ValueError):
        raise DramaMediaBackendError(
            "media backend resolution was rejected"
        ) from None


def build_backend_registry_projection(
    registry: DramaMediaBackendRegistrySnapshot,
) -> dict[str, Any]:
    """Return limits only; provider/model/source identities remain private."""

    try:
        if not isinstance(registry, DramaMediaBackendRegistrySnapshot):
            raise ValueError("media backend registry is invalid")
        registry = DramaMediaBackendRegistrySnapshot(
            **registry.model_dump(mode="json")
        )
        entries = [
            {
                "backend_id": item.backend_id,
                "media_kind": item.media_kind,
                "submission_mode": item.capability.submission_mode,
                "supports_poll": item.capability.supports_poll,
                "supports_resume": item.capability.supports_resume,
                "supports_download": item.capability.supports_download,
                "supports_tail_frame": item.capability.supports_tail_frame,
                "max_reference_images": (
                    item.capability.max_reference_images
                ),
                "supported_modes": list(item.capability.supported_modes),
                "supported_durations_seconds": list(
                    item.capability.supported_durations_seconds
                ),
                "supported_resolutions": [
                    model_to_dict(value)
                    for value in item.capability.supported_resolutions
                ],
                "output_media_types": list(
                    item.capability.output_media_types
                ),
                "sample_rates": list(item.capability.sample_rates),
                "max_text_characters": (
                    item.capability.max_text_characters
                ),
            }
            for item in registry.registrations
        ]
        return {
            "schema_version": 1,
            "backend_count": len(entries),
            "backends": entries,
        }
    except (RecursionError, TypeError, ValueError):
        raise DramaMediaBackendError(
            "media backend projection was rejected"
        ) from None
