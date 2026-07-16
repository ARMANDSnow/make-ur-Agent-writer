"""Shared synthetic stage-D1 shot-video fixtures for iter115 tests."""

from __future__ import annotations

from src import (
    drama_shot_image_candidate_store,
    drama_shot_video,
)
from src.schemas import model_to_dict
from tests._drama_shot_image_candidate_base import DramaShotImageCandidateFixture


class DramaShotVideoFixture(DramaShotImageCandidateFixture):
    def _seed_shot_video_sources(
        self,
        name: str = "shot-video",
        *,
        with_tail: bool = False,
        previous_tail: bool = False,
    ):
        sources = self._seed_candidate_sources(name)
        plan = sources["shot_image_plan"]
        manifest = self._create_manifest(name)
        candidates = {}
        for index, spec in enumerate(plan.shot_specs, start=1):
            rgba = bytes((index, index + 1, index + 2, 255))
            manifest, candidate = self._append_candidate(
                name,
                manifest,
                spec.shot_id,
                rgba=rgba,
            )
            candidates[spec.shot_id] = candidate
            direct = {
                "kind": "direct",
                "candidate_id": candidate.candidate_id,
                "candidate_fingerprint": candidate.candidate_fingerprint,
            }
            pool = next(item for item in manifest.shots if item.shot_id == spec.shot_id)
            manifest = drama_shot_image_candidate_store.select_episode_shot_image_frame(
                name,
                shot_id=spec.shot_id,
                frame="first",
                binding=direct,
                expected_selection_revision=pool.selection_revision,
                expected_current_binding=None,
                expected_manifest_fingerprint=manifest.manifest_fingerprint,
            )

        if with_tail or previous_tail:
            first_id = plan.shot_specs[0].shot_id
            first_candidate = candidates[first_id]
            direct_tail = {
                "kind": "direct",
                "candidate_id": first_candidate.candidate_id,
                "candidate_fingerprint": first_candidate.candidate_fingerprint,
            }
            first_pool = next(item for item in manifest.shots if item.shot_id == first_id)
            manifest = drama_shot_image_candidate_store.select_episode_shot_image_frame(
                name,
                shot_id=first_id,
                frame="tail",
                binding=direct_tail,
                expected_selection_revision=first_pool.selection_revision,
                expected_current_binding={"kind": "none"},
                expected_manifest_fingerprint=manifest.manifest_fingerprint,
            )

        if previous_tail:
            first_id = plan.shot_specs[0].shot_id
            second_id = plan.shot_specs[1].shot_id
            first_pool = next(item for item in manifest.shots if item.shot_id == first_id)
            second_pool = next(item for item in manifest.shots if item.shot_id == second_id)
            first_candidate = candidates[first_id]
            second_current = model_to_dict(second_pool.first_binding)
            lineage = {
                "kind": "previous_tail",
                "source_shot_id": first_id,
                "candidate_id": first_candidate.candidate_id,
                "candidate_fingerprint": first_candidate.candidate_fingerprint,
                "source_tail_revision": first_pool.tail_binding_revision,
                "target_request_fingerprint": plan.shot_specs[1].request_fingerprint,
            }
            manifest = drama_shot_image_candidate_store.select_episode_shot_image_frame(
                name,
                shot_id=second_id,
                frame="first",
                binding=lineage,
                expected_selection_revision=second_pool.selection_revision,
                expected_current_binding=second_current,
                expected_manifest_fingerprint=manifest.manifest_fingerprint,
            )

        sources["candidate_manifest"] = manifest
        sources["candidates"] = candidates
        return sources

    @staticmethod
    def _build_video_plan(sources: dict):
        return drama_shot_video.build_episode_shot_video_plan(
            sources["render_plan"],
            sources["shot_image_plan"],
            sources["candidate_manifest"],
        )
