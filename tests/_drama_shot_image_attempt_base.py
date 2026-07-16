"""Shared synthetic C3 shot-image attempt fixtures for iter114 tests."""

from __future__ import annotations

from src import (
    drama_shot_image_attempts,
    drama_shot_image_candidate_store,
)
from tests._drama_shot_image_candidate_base import DramaShotImageCandidateFixture


class DramaShotImageAttemptFixture(DramaShotImageCandidateFixture):
    @staticmethod
    def _capability(max_reference_images: int = 8):
        return drama_shot_image_attempts.build_shot_image_provider_capability(
            backend_id="fake-shot-image",
            capability_version="v1",
            max_reference_images=max_reference_images,
        )

    def _seed_attempt_sources(self, name: str = "shot-attempts"):
        sources = self._seed_candidate_sources(name)
        manifest = drama_shot_image_candidate_store.create_episode_shot_image_candidate_manifest(
            name
        )
        sources["candidate_manifest"] = manifest
        sources["capability"] = self._capability()
        sources["provider_fingerprint"] = "a" * 64
        sources["shot_id"] = sources["shot_image_plan"].shot_specs[0].shot_id
        return sources
