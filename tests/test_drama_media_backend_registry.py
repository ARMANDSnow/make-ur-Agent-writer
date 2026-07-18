"""iter135 G3 static backend capability registry and frozen binding tests."""

from __future__ import annotations

import inspect
import socket
from unittest import TestCase
from unittest.mock import patch

from src import (
    drama_media_tasks,
    drama_shot_image_attempts,
    drama_shot_video_attempts,
    drama_tts_attempts,
)
from src.drama_media_backends import base, registry
from src.drama_media_backends.base import DramaMediaBackendError
from src.drama_schemas import (
    DramaMediaBackendCapability,
    DramaMediaBackendRegistration,
    DramaMediaBackendRegistrySnapshot,
    _canonical_sha256,
)
from src.schemas import model_to_dict


class DramaMediaBackendRegistryTests(TestCase):
    _PROVIDER_FP = "1" * 64
    _MODEL_FP = "2" * 64
    _VIDEO_PROVIDER_FP = "5" * 64
    _VIDEO_MODEL_FP = "6" * 64
    _AUDIO_PROVIDER_FP = "7" * 64
    _AUDIO_MODEL_FP = "8" * 64

    def setUp(self) -> None:
        self.image_source = (
            drama_shot_image_attempts.build_shot_image_provider_capability(
                backend_id="image-fixture",
                capability_version="v1",
                max_reference_images=4,
            )
        )
        self.video_source = (
            drama_shot_video_attempts.build_shot_video_provider_capability(
                backend_id="video-fixture",
                capability_version="v1",
                supported_modes=[
                    "image_to_video",
                    "reference_to_video",
                ],
                supports_tail_frame=True,
                max_reference_images=3,
                supported_durations_seconds=[3, 5],
                supported_resolutions=[(720, 1280), (1080, 1920)],
            )
        )
        self.audio_source = drama_tts_attempts.build_tts_provider_capability(
            backend_id="audio-fixture",
            capability_version="v1",
            provider_id="local-tts",
            model_id="local/voice-v1",
            sample_rate=16000,
            max_text_characters=220,
        )
        self.image = base.registration_from_shot_image_capability(
            self.image_source,
            provider_id="local-image",
            model_id="fixture-image-v1",
            provider_fingerprint=self._PROVIDER_FP,
            model_fingerprint=self._MODEL_FP,
        )
        self.video = base.registration_from_shot_video_capability(
            self.video_source,
            provider_id="local-video",
            model_id="fixture-video-v1",
            provider_fingerprint=self._VIDEO_PROVIDER_FP,
            model_fingerprint=self._VIDEO_MODEL_FP,
        )
        self.audio = base.registration_from_tts_capability(
            self.audio_source,
            provider_fingerprint=self._AUDIO_PROVIDER_FP,
            model_fingerprint=self._AUDIO_MODEL_FP,
        )

    def _registry(self):
        return registry.build_backend_registry(
            [self.video, self.audio, self.image]
        )

    def _task(
        self,
        *,
        media_kind: str = "image",
        stage: str = "image-generate",
        backend_id: str = "image-fixture",
        state: str = "ready",
        input_fingerprint: str = "a" * 64,
    ):
        return drama_media_tasks._build_task(
            episode_no=1,
            media_kind=media_kind,
            stage=stage,
            subject_id="shot_001",
            input_fingerprint=input_fingerprint,
            backend_id=backend_id,
            provider_fingerprint=self._PROVIDER_FP,
            model_fingerprint=self._MODEL_FP,
            account_fingerprint="3" * 64,
            endpoint_fingerprint="4" * 64,
            dependency_task_ids=(),
            attempt_no=1,
            state=state,
            revision=0,
            created_at_ms=1_700_000_000_000,
            updated_at_ms=1_700_000_000_000,
        )

    def test_existing_capabilities_are_not_mutated_and_identity_is_retained(
        self,
    ) -> None:
        originals = [
            model_to_dict(self.image_source),
            model_to_dict(self.video_source),
            model_to_dict(self.audio_source),
        ]
        registrations = [self.image, self.video, self.audio]
        self.assertEqual(
            [
                item.capability.source_capability_fingerprint
                for item in registrations
            ],
            [
                self.image_source.capability_fingerprint,
                self.video_source.capability_fingerprint,
                self.audio_source.capability_fingerprint,
            ],
        )
        self.assertEqual(
            originals,
            [
                model_to_dict(self.image_source),
                model_to_dict(self.video_source),
                model_to_dict(self.audio_source),
            ],
        )

    def test_mutated_source_capability_is_not_normalized(self) -> None:
        self.image_source.max_reference_images = 2
        with self.assertRaises(DramaMediaBackendError):
            base.registration_from_shot_image_capability(
                self.image_source,
                provider_id="local-image",
                model_id="fixture-image-v1",
                provider_fingerprint=self._PROVIDER_FP,
                model_fingerprint=self._MODEL_FP,
            )

    def test_media_specific_capabilities_are_normalized_without_guessing(
        self,
    ) -> None:
        self.assertEqual(self.image.capability.submission_mode, "synchronous")
        self.assertEqual(
            self.image.capability.supported_modes,
            ("image_generation",),
        )
        self.assertEqual(self.image.capability.max_reference_images, 4)
        self.assertEqual(self.video.capability.submission_mode, "asynchronous")
        self.assertTrue(self.video.capability.supports_poll)
        self.assertTrue(self.video.capability.supports_resume)
        self.assertEqual(
            [
                (item.width, item.height)
                for item in self.video.capability.supported_resolutions
            ],
            [(720, 1280), (1080, 1920)],
        )
        self.assertEqual(self.audio.capability.sample_rates, (16000,))
        self.assertEqual(self.audio.capability.max_text_characters, 220)
        self.assertTrue(self.audio.capability.supports_download)

    def test_registry_order_and_fingerprint_are_deterministic(self) -> None:
        first = self._registry()
        second = registry.build_backend_registry(
            [self.image, self.video, self.audio]
        )
        self.assertEqual(first, second)
        self.assertEqual(
            [
                (item.provider_id, item.media_kind, item.model_id)
                for item in first.registrations
            ],
            sorted(
                [
                    (item.provider_id, item.media_kind, item.model_id)
                    for item in first.registrations
                ]
            ),
        )

    def test_registry_rejects_empty_non_sequence_and_non_registration(
        self,
    ) -> None:
        for value in ([], {}, "image", [object()]):
            with self.subTest(value=type(value).__name__):
                with self.assertRaises(DramaMediaBackendError):
                    registry.build_backend_registry(value)  # type: ignore[arg-type]

    def test_registry_rejects_duplicate_key(self) -> None:
        with self.assertRaises(DramaMediaBackendError):
            registry.build_backend_registry([self.image, self.image])

    def test_registry_rejects_duplicate_backend_identity(self) -> None:
        payload = self.image.model_dump(
            mode="json", exclude={"registration_fingerprint"}
        )
        payload["model_id"] = "fixture-image-v2"
        payload["provider_id"] = "other-image"
        payload["registration_fingerprint"] = _canonical_sha256(payload)
        other = DramaMediaBackendRegistration(**payload)
        with self.assertRaises(DramaMediaBackendError):
            registry.build_backend_registry([self.image, other])

    def test_same_backend_can_declare_multiple_models_for_one_owner(self) -> None:
        payload = self.image.model_dump(
            mode="json", exclude={"registration_fingerprint"}
        )
        payload["model_id"] = "fixture-image-v2"
        payload["model_fingerprint"] = "8" * 64
        payload["registration_fingerprint"] = _canonical_sha256(payload)
        other = DramaMediaBackendRegistration(**payload)
        snapshot = registry.build_backend_registry([self.image, other])
        self.assertEqual(len(snapshot.registrations), 2)

    def test_different_model_ids_cannot_reuse_one_model_fingerprint(self) -> None:
        payload = self.image.model_dump(
            mode="json", exclude={"registration_fingerprint"}
        )
        payload["model_id"] = "fixture-image-v2"
        payload["registration_fingerprint"] = _canonical_sha256(payload)
        alias = DramaMediaBackendRegistration(**payload)
        with self.assertRaises(DramaMediaBackendError):
            registry.build_backend_registry([self.image, alias])

    def test_registration_rejects_case_and_path_ambiguity(self) -> None:
        for provider_id, model_id in (
            ("Local-image", "fixture-v1"),
            ("local-image", "../fixture-v1"),
            ("local-image", "owner//fixture-v1"),
            ("local-image", "owner/./fixture-v1"),
            ("local-image", "/fixture-v1"),
            ("local-image", "fixture-v1/"),
        ):
            with self.subTest(provider_id=provider_id, model_id=model_id):
                with self.assertRaises(DramaMediaBackendError):
                    base.registration_from_shot_image_capability(
                        self.image_source,
                        provider_id=provider_id,
                        model_id=model_id,
                        provider_fingerprint=self._PROVIDER_FP,
                        model_fingerprint=self._MODEL_FP,
                    )

    def test_schema_rejects_secret_extra_fields(self) -> None:
        payload = self.image.model_dump(mode="json")
        payload["api_key"] = "secret"
        with self.assertRaises(ValueError):
            DramaMediaBackendRegistration(**payload)

    def test_capability_strict_numeric_and_list_fields(self) -> None:
        original = self.image.capability.model_dump(
            mode="json", exclude={"capability_fingerprint"}
        )
        for field, value in (
            ("max_reference_images", True),
            ("supported_modes", ("image_generation",)),
            ("sample_rates", [16000, 16000]),
            ("supports_poll", 0),
        ):
            payload = dict(original)
            payload[field] = value
            payload["capability_fingerprint"] = _canonical_sha256(payload)
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    DramaMediaBackendCapability(**payload)

    def test_resolve_binds_exact_task_and_registry_identity(self) -> None:
        task = self._task()
        binding = registry.resolve_task_backend(
            self._registry(),
            task,
            provider_id="local-image",
            model_id="fixture-image-v1",
            provider_fingerprint=self._PROVIDER_FP,
            model_fingerprint=self._MODEL_FP,
        )
        self.assertEqual(binding.task_id, task.task_id)
        self.assertEqual(binding.backend_id, task.backend_id)
        self.assertEqual(
            binding.source_capability_fingerprint,
            self.image_source.capability_fingerprint,
        )

    def test_unknown_provider_media_model_combination_loud_fails(self) -> None:
        task = self._task()
        for provider_id, model_id in (
            ("unknown", "fixture-image-v1"),
            ("local-image", "unknown"),
            ("local-video", "fixture-video-v1"),
        ):
            with self.subTest(provider_id=provider_id, model_id=model_id):
                with self.assertRaises(DramaMediaBackendError):
                    registry.resolve_task_backend(
                        self._registry(),
                        task,
                        provider_id=provider_id,
                        model_id=model_id,
                        provider_fingerprint=self._PROVIDER_FP,
                        model_fingerprint=self._MODEL_FP,
                    )

    def test_task_backend_and_provider_fingerprint_drift_fail(self) -> None:
        wrong_backend = self._task(backend_id="other-backend")
        with self.assertRaises(DramaMediaBackendError):
            registry.resolve_task_backend(
                self._registry(),
                wrong_backend,
                provider_id="local-image",
                model_id="fixture-image-v1",
                provider_fingerprint=self._PROVIDER_FP,
                model_fingerprint=self._MODEL_FP,
            )
        task = self._task()
        with self.assertRaises(DramaMediaBackendError):
            registry.resolve_task_backend(
                self._registry(),
                task,
                provider_id="local-image",
                model_id="fixture-image-v1",
                provider_fingerprint="9" * 64,
                model_fingerprint=self._MODEL_FP,
            )

    def test_registered_model_fingerprint_cannot_cross_bind(self) -> None:
        payload = self.image.model_dump(
            mode="json", exclude={"registration_fingerprint"}
        )
        payload["model_id"] = "fixture-image-v2"
        payload["model_fingerprint"] = "8" * 64
        payload["registration_fingerprint"] = _canonical_sha256(payload)
        other = DramaMediaBackendRegistration(**payload)
        snapshot = registry.build_backend_registry([self.image, other])
        with self.assertRaises(DramaMediaBackendError):
            registry.resolve_task_backend(
                snapshot,
                self._task(),
                provider_id="local-image",
                model_id="fixture-image-v2",
                provider_fingerprint=self._PROVIDER_FP,
                model_fingerprint=self._MODEL_FP,
            )
    def test_submitting_task_requires_frozen_binding(self) -> None:
        ready = self._task()
        submitting = drama_media_tasks._replace_task(
            ready,
            state="submitting",
            now_ms=1_700_000_000_001,
        )
        with self.assertRaises(DramaMediaBackendError):
            registry.resolve_task_backend(
                self._registry(),
                submitting,
                provider_id="local-image",
                model_id="fixture-image-v1",
                provider_fingerprint=self._PROVIDER_FP,
                model_fingerprint=self._MODEL_FP,
            )

    def test_frozen_binding_survives_registry_drift_after_submission(
        self,
    ) -> None:
        ready = self._task()
        original_registry = self._registry()
        binding = registry.resolve_task_backend(
            original_registry,
            ready,
            provider_id="local-image",
            model_id="fixture-image-v1",
            provider_fingerprint=self._PROVIDER_FP,
            model_fingerprint=self._MODEL_FP,
        )
        source_v2 = (
            drama_shot_image_attempts.build_shot_image_provider_capability(
                backend_id="image-fixture",
                capability_version="v2",
                max_reference_images=2,
            )
        )
        image_v2 = base.registration_from_shot_image_capability(
            source_v2,
            provider_id="local-image",
            model_id="fixture-image-v1",
            provider_fingerprint=self._PROVIDER_FP,
            model_fingerprint=self._MODEL_FP,
        )
        drifted = registry.build_backend_registry(
            [image_v2, self.video, self.audio]
        )
        submitting = drama_media_tasks._replace_task(
            ready,
            state="submitting",
            now_ms=1_700_000_000_001,
        )
        replay = registry.resolve_task_backend(
            drifted,
            submitting,
            provider_id="local-image",
            model_id="fixture-image-v1",
            provider_fingerprint=self._PROVIDER_FP,
            model_fingerprint=self._MODEL_FP,
            frozen_binding=binding,
        )
        self.assertEqual(replay, binding)
        self.assertNotEqual(
            binding.registry_fingerprint,
            drifted.registry_fingerprint,
        )

    def test_frozen_binding_cannot_move_to_another_task_or_identity(self) -> None:
        task = self._task()
        binding = registry.resolve_task_backend(
            self._registry(),
            task,
            provider_id="local-image",
            model_id="fixture-image-v1",
            provider_fingerprint=self._PROVIDER_FP,
            model_fingerprint=self._MODEL_FP,
        )
        other = self._task(input_fingerprint="b" * 64)
        for target, provider_fp in (
            (other, self._PROVIDER_FP),
            (task, "9" * 64),
        ):
            with self.subTest(task_id=target.task_id, provider=provider_fp[:1]):
                with self.assertRaises(DramaMediaBackendError):
                    registry.resolve_task_backend(
                        self._registry(),
                        target,
                        provider_id="local-image",
                        model_id="fixture-image-v1",
                        provider_fingerprint=provider_fp,
                        model_fingerprint=self._MODEL_FP,
                        frozen_binding=binding,
                    )

    def test_projection_hides_provider_model_and_fingerprints(self) -> None:
        projection = registry.build_backend_registry_projection(
            self._registry()
        )
        self.assertEqual(projection["backend_count"], 3)
        serialized = repr(projection)
        for forbidden in (
            "provider_id",
            "model_id",
            "fingerprint",
            "local-image",
            "fixture-image-v1",
            self.image_source.capability_fingerprint,
        ):
            self.assertNotIn(forbidden, serialized)

    def test_registry_has_no_dynamic_code_loader_or_network_side_effect(
        self,
    ) -> None:
        source = inspect.getsource(registry)
        for forbidden in ("importlib", "__import__", "entry_points", "eval(", "exec("):
            self.assertNotIn(forbidden, source)
        with patch.object(
            socket, "socket", side_effect=AssertionError("network forbidden")
        ):
            snapshot = self._registry()
            registry.resolve_task_backend(
                snapshot,
                self._task(),
                provider_id="local-image",
                model_id="fixture-image-v1",
                provider_fingerprint=self._PROVIDER_FP,
                model_fingerprint=self._MODEL_FP,
            )

    def test_snapshot_fingerprint_tamper_is_rejected(self) -> None:
        payload = self._registry().model_dump(mode="json")
        payload["registry_fingerprint"] = "0" * 64
        with self.assertRaises(ValueError):
            DramaMediaBackendRegistrySnapshot(**payload)

    def test_registry_snapshot_is_deep_frozen(self) -> None:
        snapshot = self._registry()
        with self.assertRaises(AttributeError):
            snapshot.registrations.append(self.image)
        with self.assertRaises(AttributeError):
            snapshot.registrations[0].capability.supported_modes.append(
                "image_generation"
            )
        video = next(
            item for item in snapshot.registrations
            if item.media_kind == "video"
        )
        with self.assertRaises((AttributeError, TypeError, ValueError)):
            video.capability.supported_resolutions[0].width = 640
