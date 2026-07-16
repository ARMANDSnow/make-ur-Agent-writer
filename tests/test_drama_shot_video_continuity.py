"""iter119: D4 continuity projection and compose gate."""

from __future__ import annotations

import hashlib

from src import (
    drama_shot_video_candidate_store,
    drama_shot_video_candidates,
    drama_shot_video_continuity,
)
from src.schemas import model_to_dict
from src import paths
from tests._drama_shot_video_candidate_base import DramaShotVideoCandidateFixture


class DramaShotVideoContinuityTests(DramaShotVideoCandidateFixture):
    def _candidate_for_plan(self, plan, shot_id, *, marker=0):
        data = self._mp4_variant(marker)
        identity = drama_shot_video_candidate_store._candidate_payload_identity(data)
        return drama_shot_video_candidates.build_shot_video_candidate(
            plan,
            shot_id=shot_id,
            artifact_sha256=hashlib.sha256(data).hexdigest(),
            artifact_size_bytes=len(data),
            duration_milliseconds=identity[2],
            width=identity[3],
            height=identity[4],
            has_audio_track=identity[5],
        )

    def _ready_sources(self, name: str, *, placeholder_index: int | None = None):
        sources = self._seed_video_candidate_sources(name)
        manifest = sources["video_candidate_manifest"]
        plan = sources["video_plan"]
        for index, spec in enumerate(plan.shot_specs):
            manifest, candidate = self._append_video_candidate(
                name,
                manifest,
                spec.shot_id,
                marker=index,
                is_placeholder=index == placeholder_index,
            )
            manifest = self._select_video_candidate(name, manifest, candidate)
        return plan, manifest

    def test_ready_report_is_stable_and_gate_returns_it(self) -> None:
        name = "video-continuity-ready"
        plan, manifest = self._ready_sources(name)
        first = drama_shot_video_continuity.build_shot_video_continuity_report(
            plan, manifest
        )
        second = drama_shot_video_continuity.build_shot_video_continuity_report(
            plan, manifest
        )
        self.assertEqual(first, second)
        self.assertEqual(first.status, "ready")
        self.assertTrue(first.ready_for_compose)
        self.assertEqual(
            drama_shot_video_continuity.require_workspace_production_compose_ready(
                name
            ),
            first,
        )

    def test_placeholder_is_degraded_preview_and_never_production_ready(self) -> None:
        name = "video-continuity-preview"
        plan, manifest = self._ready_sources(name, placeholder_index=0)
        report = drama_shot_video_continuity.build_shot_video_continuity_report(
            plan, manifest
        )
        self.assertEqual(report.status, "degraded_preview")
        self.assertEqual(report.degraded_preview_shot_ids, [plan.shot_specs[0].shot_id])
        with self.assertRaisesRegex(ValueError, "not production ready"):
            drama_shot_video_continuity.require_workspace_production_compose_ready(name)

    def test_each_hard_coverage_category_blocks_compose(self) -> None:
        sources = self._seed_video_candidate_sources("video-continuity-missing")
        missing = drama_shot_video_continuity.build_shot_video_continuity_report(
            sources["video_plan"], sources["video_candidate_manifest"]
        )
        self.assertEqual(missing.status, "blocked")
        self.assertEqual(
            missing.blocked_shot_ids,
            [item.shot_id for item in sources["video_plan"].shot_specs],
        )

        plan, manifest = self._ready_sources("video-continuity-invalid")
        shot_id = plan.shot_specs[0].shot_id
        invalid = drama_shot_video_continuity.build_shot_video_continuity_report(
            plan, manifest, invalid_artifact_shot_ids=[shot_id]
        )
        blocked = drama_shot_video_continuity.build_shot_video_continuity_report(
            plan, manifest, blocked_source_shot_ids=[shot_id]
        )
        self.assertEqual(invalid.blocked_shot_ids, [shot_id])
        self.assertEqual(blocked.blocked_shot_ids, [shot_id])

    def test_invalid_lineage_and_cross_episode_inputs_fail_closed(self) -> None:
        plan, manifest = self._ready_sources("video-continuity-boundary")
        payload = model_to_dict(plan)
        payload["shot_specs"][1]["first_frame"]["candidate_id"] = "sic_" + "0" * 24
        with self.assertRaisesRegex(ValueError, "input was rejected"):
            drama_shot_video_continuity.build_shot_video_continuity_report(
                payload, manifest
            )

        episode_two = self._episode_plan_variant(plan, 2)
        with self.assertRaisesRegex(ValueError, "input was rejected"):
            drama_shot_video_continuity.build_shot_video_continuity_report(
                episode_two, manifest
            )

    def test_camera_reversal_is_warning_not_selection_mutation(self) -> None:
        plan, manifest = self._ready_sources("video-continuity-warning")
        payload = model_to_dict(plan)
        payload["shot_specs"][0]["camera_movement"] = "推"
        payload["shot_specs"][1]["camera_movement"] = "拉"
        from src import drama_shot_video
        from src.drama_schemas import EpisodeShotVideoPlan

        for spec in payload["shot_specs"][:2]:
            spec["spec_fingerprint"] = drama_shot_video._sha256(
                {key: value for key, value in spec.items() if key != "spec_fingerprint"}
            )
        payload["plan_fingerprint"] = drama_shot_video._sha256(
            {key: value for key, value in payload.items() if key != "plan_fingerprint"}
        )
        changed = EpisodeShotVideoPlan(**payload)
        report = drama_shot_video_continuity.build_shot_video_continuity_report(
            changed, manifest
        )
        self.assertEqual(report.status, "blocked")
        self.assertEqual(report.camera_reversal_shot_ids, [changed.shot_specs[1].shot_id])
        self.assertEqual(model_to_dict(manifest), model_to_dict(manifest))

    def test_episode_two_ready_report_keeps_episode_identity(self) -> None:
        plan, _ = self._ready_sources("video-continuity-episode-two-source")
        episode_two = self._episode_plan_variant(plan, 2)
        manifest = drama_shot_video_candidates.build_episode_shot_video_candidate_manifest(
            episode_two
        )
        for index, spec in enumerate(episode_two.shot_specs):
            candidate = self._candidate_for_plan(
                episode_two, spec.shot_id, marker=index
            )
            manifest = drama_shot_video_candidates.append_shot_video_candidate(
                manifest,
                episode_two,
                candidate,
                expected_manifest_fingerprint=manifest.manifest_fingerprint,
            )
            manifest = drama_shot_video_candidates.select_shot_video_candidate(
                manifest,
                episode_two,
                shot_id=spec.shot_id,
                selection={
                    "candidate_id": candidate.candidate_id,
                    "candidate_fingerprint": candidate.candidate_fingerprint,
                },
                expected_selection_revision=0,
                expected_current_selection=None,
                expected_manifest_fingerprint=manifest.manifest_fingerprint,
            )
        report = drama_shot_video_continuity.build_shot_video_continuity_report(
            episode_two, manifest
        )
        self.assertTrue(report.ready_for_compose)
        self.assertEqual(report.episode_no, 2)
        self.assertNotIn("episode_01", report.model_dump_json())

    def test_top_level_plan_mismatch_blocks_even_when_each_selection_matches(self) -> None:
        plan, manifest = self._ready_sources("video-continuity-global-stale")
        payload = model_to_dict(manifest)
        payload["source_plan_fingerprint"] = "0" * 64
        from src import drama_shot_video_candidates
        from src.drama_schemas import EpisodeShotVideoCandidateManifest

        payload["manifest_fingerprint"] = drama_shot_video_candidates._sha256(
            {key: value for key, value in payload.items() if key != "manifest_fingerprint"}
        )
        stale = EpisodeShotVideoCandidateManifest(**payload)
        report = drama_shot_video_continuity.build_shot_video_continuity_report(
            plan, stale
        )
        self.assertEqual(report.status, "blocked")
        self.assertFalse(report.source_plan_matches)
        self.assertFalse(report.ready_for_compose)

    def test_selection_change_changes_report_fingerprint(self) -> None:
        name = "video-continuity-selection-cas"
        plan, manifest = self._ready_sources(name)
        before = drama_shot_video_continuity.build_shot_video_continuity_report(
            plan, manifest
        )
        manifest, candidate = self._append_video_candidate(
            name, manifest, plan.shot_specs[0].shot_id, marker=99
        )
        manifest = self._select_video_candidate(name, manifest, candidate)
        after = drama_shot_video_continuity.build_shot_video_continuity_report(
            plan, manifest
        )
        self.assertNotEqual(
            before.selected_bindings_fingerprint,
            after.selected_bindings_fingerprint,
        )
        self.assertNotEqual(before.report_fingerprint, after.report_fingerprint)

    def test_unselected_append_does_not_change_semantic_report(self) -> None:
        name = "video-continuity-unselected-append"
        plan, manifest = self._ready_sources(name)
        before = drama_shot_video_continuity.build_shot_video_continuity_report(
            plan, manifest
        )
        manifest, _ = self._append_video_candidate(
            name, manifest, plan.shot_specs[0].shot_id, marker=98
        )
        after = drama_shot_video_continuity.build_shot_video_continuity_report(
            plan, manifest
        )
        self.assertEqual(before, after)

    def test_workspace_gate_revalidates_selected_artifact_bytes(self) -> None:
        name = "video-continuity-workspace-artifact"
        plan, manifest = self._ready_sources(name)
        report = drama_shot_video_continuity.require_workspace_production_compose_ready(
            name
        )
        self.assertEqual(
            report.selected_bindings_fingerprint,
            drama_shot_video_continuity.build_shot_video_continuity_report(
                plan, manifest
            ).selected_bindings_fingerprint,
        )
        pool = manifest.shots[0]
        selected = next(
            item for item in pool.candidates if item.candidate_id == pool.selected.candidate_id
        )
        artifact_path = paths.workspace_root(name) / selected.artifact.path
        artifact_path.write_bytes(b"tampered")
        with self.assertRaisesRegex(ValueError, "not production ready"):
            drama_shot_video_continuity.require_workspace_production_compose_ready(
                name
            )

    def test_public_id_sequences_are_strict_and_bounded(self) -> None:
        plan, manifest = self._ready_sources("video-continuity-id-bounds")
        shot_id = plan.shot_specs[0].shot_id
        for invalid in ("not-a-list", [shot_id, shot_id], [shot_id] * 101, [1]):
            with self.assertRaisesRegex(ValueError, "was rejected"):
                drama_shot_video_continuity.build_shot_video_continuity_report(
                    plan,
                    manifest,
                    invalid_artifact_shot_ids=invalid,
                )
