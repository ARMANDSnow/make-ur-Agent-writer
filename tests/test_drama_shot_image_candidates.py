"""iter113: pure C2 candidate, selection, lineage, and coverage behavior."""

from __future__ import annotations

import hashlib

from src import drama_shot_image, drama_shot_image_candidates
from src.drama_schemas import (
    EpisodeShotImageCandidateManifest,
    EpisodeShotImagePlan,
    ShotImageCandidate,
    ShotImageCoverageReport,
)
from src.schemas import model_to_dict
from tests._drama_shot_image_candidate_base import DramaShotImageCandidateFixture


class DramaShotImageCandidatePureTests(DramaShotImageCandidateFixture):
    def _candidate(self, plan, shot_id: str, *, rgba: bytes = b"\x11\x22\x33\xff"):
        payload = self._png(rgba=rgba)
        return drama_shot_image_candidates.build_shot_image_candidate(
            plan,
            shot_id=shot_id,
            artifact_sha256=hashlib.sha256(payload).hexdigest(),
            artifact_size_bytes=len(payload),
            width=1,
            height=1,
        )

    def test_manifest_and_candidate_are_byte_stable_strict_round_trips(self) -> None:
        sources = self._seed_candidate_sources("pure-roundtrip")
        plan = sources["shot_image_plan"]
        manifest = drama_shot_image_candidates.build_episode_shot_image_candidate_manifest(plan)
        self.assertEqual(
            EpisodeShotImageCandidateManifest(**model_to_dict(manifest)),
            manifest,
        )
        self.assertTrue(all(pool.first_binding is None for pool in manifest.shots))
        self.assertTrue(all(pool.tail_binding.kind == "none" for pool in manifest.shots))
        candidate = self._candidate(plan, plan.shot_specs[0].shot_id)
        self.assertEqual(ShotImageCandidate(**model_to_dict(candidate)), candidate)
        tampered = model_to_dict(candidate)
        tampered["artifact"]["path"] = "outputs/episodes/episode_01.shot_images/shot_" + "0" * 24 + "/sic_" + "0" * 24 + ".png"
        with self.assertRaises(ValueError):
            ShotImageCandidate(**tampered)

    def test_append_is_idempotent_and_never_auto_selects(self) -> None:
        sources = self._seed_candidate_sources("pure-append")
        plan = sources["shot_image_plan"]
        manifest = drama_shot_image_candidates.build_episode_shot_image_candidate_manifest(plan)
        candidate = self._candidate(plan, plan.shot_specs[0].shot_id)
        appended = drama_shot_image_candidates.append_shot_image_candidate(
            manifest,
            plan,
            candidate,
            expected_manifest_fingerprint=manifest.manifest_fingerprint,
        )
        pool = appended.shots[0]
        self.assertEqual(pool.candidates, [candidate])
        self.assertIsNone(pool.first_binding)
        self.assertEqual(pool.tail_binding.kind, "none")
        self.assertEqual(pool.selection_revision, 0)
        replay = drama_shot_image_candidates.append_shot_image_candidate(
            appended,
            plan,
            candidate,
            expected_manifest_fingerprint=appended.manifest_fingerprint,
        )
        self.assertEqual(replay, appended)

    def test_direct_selection_requires_revision_current_binding_and_fresh_candidate(self) -> None:
        sources = self._seed_candidate_sources("pure-select")
        plan = sources["shot_image_plan"]
        manifest = drama_shot_image_candidates.build_episode_shot_image_candidate_manifest(plan)
        candidate = self._candidate(plan, plan.shot_specs[0].shot_id)
        manifest = drama_shot_image_candidates.append_shot_image_candidate(
            manifest,
            plan,
            candidate,
            expected_manifest_fingerprint=manifest.manifest_fingerprint,
        )
        binding = {
            "kind": "direct",
            "candidate_id": candidate.candidate_id,
            "candidate_fingerprint": candidate.candidate_fingerprint,
        }
        selected = drama_shot_image_candidates.select_shot_image_frame(
            manifest,
            plan,
            shot_id=candidate.shot_id,
            frame="first",
            binding=binding,
            expected_selection_revision=0,
            expected_current_binding=None,
            expected_manifest_fingerprint=manifest.manifest_fingerprint,
        )
        self.assertEqual(selected.shots[0].first_binding.kind, "direct")
        self.assertEqual(selected.shots[0].selection_revision, 1)
        with self.assertRaisesRegex(ValueError, "revision"):
            drama_shot_image_candidates.select_shot_image_frame(
                selected,
                plan,
                shot_id=candidate.shot_id,
                frame="tail",
                binding=binding,
                expected_selection_revision=0,
                expected_current_binding={"kind": "none"},
                expected_manifest_fingerprint=selected.manifest_fingerprint,
            )

    def test_lost_response_replay_accepts_original_append_and_selection_tokens(self) -> None:
        sources = self._seed_candidate_sources("pure-replay")
        plan = sources["shot_image_plan"]
        initial = drama_shot_image_candidates.build_episode_shot_image_candidate_manifest(plan)
        candidate = self._candidate(plan, plan.shot_specs[0].shot_id)
        appended = drama_shot_image_candidates.append_shot_image_candidate(
            initial,
            plan,
            candidate,
            expected_manifest_fingerprint=initial.manifest_fingerprint,
        )
        replay = drama_shot_image_candidates.append_shot_image_candidate(
            appended,
            plan,
            candidate,
            expected_manifest_fingerprint=initial.manifest_fingerprint,
        )
        self.assertEqual(replay, appended)
        binding = {
            "kind": "direct",
            "candidate_id": candidate.candidate_id,
            "candidate_fingerprint": candidate.candidate_fingerprint,
        }
        selected = drama_shot_image_candidates.select_shot_image_frame(
            appended,
            plan,
            shot_id=candidate.shot_id,
            frame="first",
            binding=binding,
            expected_selection_revision=0,
            expected_current_binding=None,
            expected_manifest_fingerprint=appended.manifest_fingerprint,
        )
        replayed_selection = drama_shot_image_candidates.select_shot_image_frame(
            selected,
            plan,
            shot_id=candidate.shot_id,
            frame="first",
            binding=binding,
            expected_selection_revision=0,
            expected_current_binding=None,
            expected_manifest_fingerprint=appended.manifest_fingerprint,
        )
        self.assertEqual(replayed_selection, selected)

        with self.assertRaisesRegex(ValueError, "changed"):
            drama_shot_image_candidates.select_shot_image_frame(
                selected,
                plan,
                shot_id=candidate.shot_id,
                frame="first",
                binding=binding,
                expected_selection_revision=0,
                expected_current_binding=binding,
                expected_manifest_fingerprint=appended.manifest_fingerprint,
            )

        empty = drama_shot_image_candidates.build_episode_shot_image_candidate_manifest(
            plan
        )
        with self.assertRaisesRegex(ValueError, "bounded"):
            drama_shot_image_candidates.select_shot_image_frame(
                empty,
                plan,
                shot_id=candidate.shot_id,
                frame="first",
                binding=None,
                expected_selection_revision=-1,
                expected_current_binding=None,
                expected_manifest_fingerprint=empty.manifest_fingerprint,
            )

    def test_previous_tail_lineage_breaks_without_automatic_rebinding(self) -> None:
        sources = self._seed_candidate_sources("pure-lineage")
        plan = sources["shot_image_plan"]
        manifest = drama_shot_image_candidates.build_episode_shot_image_candidate_manifest(plan)
        first_id = plan.shot_specs[0].shot_id
        second_id = plan.shot_specs[1].shot_id
        first = self._candidate(plan, first_id)
        manifest = drama_shot_image_candidates.append_shot_image_candidate(
            manifest,
            plan,
            first,
            expected_manifest_fingerprint=manifest.manifest_fingerprint,
        )
        direct = {
            "kind": "direct",
            "candidate_id": first.candidate_id,
            "candidate_fingerprint": first.candidate_fingerprint,
        }
        manifest = drama_shot_image_candidates.select_shot_image_frame(
            manifest,
            plan,
            shot_id=first_id,
            frame="tail",
            binding=direct,
            expected_selection_revision=0,
            expected_current_binding={"kind": "none"},
            expected_manifest_fingerprint=manifest.manifest_fingerprint,
        )
        lineage = {
            "kind": "previous_tail",
            "source_shot_id": first_id,
            "candidate_id": first.candidate_id,
            "candidate_fingerprint": first.candidate_fingerprint,
            "source_tail_revision": manifest.shots[0].tail_binding_revision,
            "target_request_fingerprint": plan.shot_specs[1].request_fingerprint,
        }
        manifest = drama_shot_image_candidates.select_shot_image_frame(
            manifest,
            plan,
            shot_id=second_id,
            frame="first",
            binding=lineage,
            expected_selection_revision=0,
            expected_current_binding=None,
            expected_manifest_fingerprint=manifest.manifest_fingerprint,
        )
        second_binding_before = model_to_dict(manifest.shots[1].first_binding)
        replacement = self._candidate(plan, first_id, rgba=b"\xaa\xbb\xcc\xff")
        manifest = drama_shot_image_candidates.append_shot_image_candidate(
            manifest,
            plan,
            replacement,
            expected_manifest_fingerprint=manifest.manifest_fingerprint,
        )
        replacement_binding = {
            "kind": "direct",
            "candidate_id": replacement.candidate_id,
            "candidate_fingerprint": replacement.candidate_fingerprint,
        }
        manifest = drama_shot_image_candidates.select_shot_image_frame(
            manifest,
            plan,
            shot_id=first_id,
            frame="tail",
            binding=replacement_binding,
            expected_selection_revision=1,
            expected_current_binding=direct,
            expected_manifest_fingerprint=manifest.manifest_fingerprint,
        )
        self.assertEqual(model_to_dict(manifest.shots[1].first_binding), second_binding_before)
        coverage = drama_shot_image_candidates.shot_image_coverage(manifest, plan)
        self.assertIn(second_id, coverage.broken_lineage_shot_ids)
        self.assertEqual(coverage.status, "stale")
        manifest = drama_shot_image_candidates.select_shot_image_frame(
            manifest,
            plan,
            shot_id=first_id,
            frame="tail",
            binding=direct,
            expected_selection_revision=2,
            expected_current_binding=replacement_binding,
            expected_manifest_fingerprint=manifest.manifest_fingerprint,
        )
        self.assertEqual(manifest.shots[0].tail_binding_revision, 3)
        coverage = drama_shot_image_candidates.shot_image_coverage(manifest, plan)
        self.assertIn(second_id, coverage.broken_lineage_shot_ids)

    def test_first_change_does_not_stale_previous_tail_lineage(self) -> None:
        sources = self._seed_candidate_sources("pure-lineage-first-change")
        plan = sources["shot_image_plan"]
        manifest = drama_shot_image_candidates.build_episode_shot_image_candidate_manifest(plan)
        first_id, second_id = [item.shot_id for item in plan.shot_specs[:2]]
        candidate = self._candidate(plan, first_id)
        manifest = drama_shot_image_candidates.append_shot_image_candidate(
            manifest,
            plan,
            candidate,
            expected_manifest_fingerprint=manifest.manifest_fingerprint,
        )
        direct = {
            "kind": "direct",
            "candidate_id": candidate.candidate_id,
            "candidate_fingerprint": candidate.candidate_fingerprint,
        }
        manifest = drama_shot_image_candidates.select_shot_image_frame(
            manifest,
            plan,
            shot_id=first_id,
            frame="tail",
            binding=direct,
            expected_selection_revision=0,
            expected_current_binding={"kind": "none"},
            expected_manifest_fingerprint=manifest.manifest_fingerprint,
        )
        lineage = {
            "kind": "previous_tail",
            "source_shot_id": first_id,
            "candidate_id": candidate.candidate_id,
            "candidate_fingerprint": candidate.candidate_fingerprint,
            "source_tail_revision": 1,
            "target_request_fingerprint": plan.shot_specs[1].request_fingerprint,
        }
        manifest = drama_shot_image_candidates.select_shot_image_frame(
            manifest,
            plan,
            shot_id=second_id,
            frame="first",
            binding=lineage,
            expected_selection_revision=0,
            expected_current_binding=None,
            expected_manifest_fingerprint=manifest.manifest_fingerprint,
        )
        manifest = drama_shot_image_candidates.select_shot_image_frame(
            manifest,
            plan,
            shot_id=first_id,
            frame="first",
            binding=direct,
            expected_selection_revision=1,
            expected_current_binding=None,
            expected_manifest_fingerprint=manifest.manifest_fingerprint,
        )
        self.assertEqual(manifest.shots[0].tail_binding_revision, 1)
        coverage = drama_shot_image_candidates.shot_image_coverage(manifest, plan)
        self.assertNotIn(second_id, coverage.broken_lineage_shot_ids)

    def test_reconcile_preserves_history_and_only_marks_changed_request(self) -> None:
        sources = self._seed_candidate_sources("pure-reconcile")
        plan = sources["shot_image_plan"]
        manifest = drama_shot_image_candidates.build_episode_shot_image_candidate_manifest(plan)
        first_id = plan.shot_specs[0].shot_id
        candidate = self._candidate(plan, first_id)
        manifest = drama_shot_image_candidates.append_shot_image_candidate(
            manifest,
            plan,
            candidate,
            expected_manifest_fingerprint=manifest.manifest_fingerprint,
        )
        changed_mapping = {
            key: list(value) for key, value in sources["character_mapping"].items()
        }
        changed_mapping[first_id] = []
        sources["character_mapping"] = changed_mapping
        new_plan = self._build_pure(sources, binding_revision=1)
        self.assertEqual(
            drama_shot_image_candidates.shot_image_candidate_affected_ids(
                manifest, new_plan
            ),
            [first_id],
        )
        reconciled = drama_shot_image_candidates.reconcile_shot_image_candidate_manifest(
            manifest,
            new_plan,
            expected_manifest_fingerprint=manifest.manifest_fingerprint,
        )
        self.assertEqual(reconciled.shots[0].candidates, [candidate])
        self.assertEqual(
            reconciled.shots[1].pool_fingerprint,
            manifest.shots[1].pool_fingerprint,
        )

    def test_reconcile_keeps_target_request_drifted_lineage_stale(self) -> None:
        sources = self._seed_candidate_sources("pure-target-request-drift")
        plan = sources["shot_image_plan"]
        manifest = drama_shot_image_candidates.build_episode_shot_image_candidate_manifest(plan)
        first_id, second_id = [item.shot_id for item in plan.shot_specs[:2]]
        candidate = self._candidate(plan, first_id)
        manifest = drama_shot_image_candidates.append_shot_image_candidate(
            manifest,
            plan,
            candidate,
            expected_manifest_fingerprint=manifest.manifest_fingerprint,
        )
        direct = {
            "kind": "direct",
            "candidate_id": candidate.candidate_id,
            "candidate_fingerprint": candidate.candidate_fingerprint,
        }
        manifest = drama_shot_image_candidates.select_shot_image_frame(
            manifest,
            plan,
            shot_id=first_id,
            frame="tail",
            binding=direct,
            expected_selection_revision=0,
            expected_current_binding={"kind": "none"},
            expected_manifest_fingerprint=manifest.manifest_fingerprint,
        )
        lineage = {
            "kind": "previous_tail",
            "source_shot_id": first_id,
            "candidate_id": candidate.candidate_id,
            "candidate_fingerprint": candidate.candidate_fingerprint,
            "source_tail_revision": 1,
            "target_request_fingerprint": plan.shot_specs[1].request_fingerprint,
        }
        manifest = drama_shot_image_candidates.select_shot_image_frame(
            manifest,
            plan,
            shot_id=second_id,
            frame="first",
            binding=lineage,
            expected_selection_revision=0,
            expected_current_binding=None,
            expected_manifest_fingerprint=manifest.manifest_fingerprint,
        )
        changed_mapping = {
            key: list(value) for key, value in sources["character_mapping"].items()
        }
        changed_mapping[second_id] = []
        sources["character_mapping"] = changed_mapping
        changed_plan = self._build_pure(sources, binding_revision=1)
        reconciled = drama_shot_image_candidates.reconcile_shot_image_candidate_manifest(
            manifest,
            changed_plan,
            expected_manifest_fingerprint=manifest.manifest_fingerprint,
        )
        coverage = drama_shot_image_candidates.shot_image_coverage(
            reconciled,
            changed_plan,
        )
        self.assertIn(second_id, coverage.broken_lineage_shot_ids)
        self.assertEqual(coverage.status, "stale")

    def test_reconcile_preserves_but_breaks_lineage_after_shot_reorder(self) -> None:
        sources = self._seed_candidate_sources("pure-reorder")
        plan = sources["shot_image_plan"]
        self.assertGreaterEqual(len(plan.shot_specs), 3)
        manifest = drama_shot_image_candidates.build_episode_shot_image_candidate_manifest(plan)
        first_id, second_id = [item.shot_id for item in plan.shot_specs[:2]]
        candidate = self._candidate(plan, first_id)
        manifest = drama_shot_image_candidates.append_shot_image_candidate(
            manifest,
            plan,
            candidate,
            expected_manifest_fingerprint=manifest.manifest_fingerprint,
        )
        direct = {
            "kind": "direct",
            "candidate_id": candidate.candidate_id,
            "candidate_fingerprint": candidate.candidate_fingerprint,
        }
        manifest = drama_shot_image_candidates.select_shot_image_frame(
            manifest,
            plan,
            shot_id=first_id,
            frame="tail",
            binding=direct,
            expected_selection_revision=0,
            expected_current_binding={"kind": "none"},
            expected_manifest_fingerprint=manifest.manifest_fingerprint,
        )
        manifest = drama_shot_image_candidates.select_shot_image_frame(
            manifest,
            plan,
            shot_id=second_id,
            frame="first",
            binding={
                "kind": "previous_tail",
                "source_shot_id": first_id,
                "candidate_id": candidate.candidate_id,
                "candidate_fingerprint": candidate.candidate_fingerprint,
                "source_tail_revision": 1,
                "target_request_fingerprint": plan.shot_specs[1].request_fingerprint,
            },
            expected_selection_revision=0,
            expected_current_binding=None,
            expected_manifest_fingerprint=manifest.manifest_fingerprint,
        )
        payload = model_to_dict(plan)
        order = [0, 2, 1, *range(3, len(plan.shot_specs))]
        payload["shot_specs"] = [payload["shot_specs"][index] for index in order]
        payload["character_bindings"] = [
            payload["character_bindings"][index] for index in order
        ]
        fingerprint_payload = dict(payload)
        fingerprint_payload.pop("plan_fingerprint")
        payload["plan_fingerprint"] = drama_shot_image._sha256(fingerprint_payload)
        reordered = EpisodeShotImagePlan(**payload)
        reconciled = drama_shot_image_candidates.reconcile_shot_image_candidate_manifest(
            manifest,
            reordered,
            expected_manifest_fingerprint=manifest.manifest_fingerprint,
        )
        self.assertIn(
            second_id,
            drama_shot_image_candidates.shot_image_candidate_affected_ids(
                manifest,
                reordered,
            ),
        )
        coverage = drama_shot_image_candidates.shot_image_coverage(
            reconciled,
            reordered,
        )
        self.assertIn(second_id, coverage.broken_lineage_shot_ids)

    def test_inserted_shot_only_affects_new_shot_and_changed_predecessor(self) -> None:
        sources = self._seed_candidate_sources("pure-insert-affected")
        plan = sources["shot_image_plan"]
        manifest = drama_shot_image_candidates.build_episode_shot_image_candidate_manifest(
            plan
        )
        inserted_id = f"shot_{'f' * 24}"
        inserted = plan.shot_specs[0].model_copy(update={"shot_id": inserted_id})
        changed = plan.model_copy(
            update={"shot_specs": [plan.shot_specs[0], inserted, *plan.shot_specs[1:]]}
        )
        self.assertEqual(
            drama_shot_image_candidates.shot_image_candidate_affected_ids(
                manifest,
                changed,
            ),
            sorted([inserted_id, plan.shot_specs[1].shot_id]),
        )

    def test_coverage_schema_rejects_overlap_and_status_spoofing(self) -> None:
        sources = self._seed_candidate_sources("pure-coverage-schema")
        plan = sources["shot_image_plan"]
        manifest = drama_shot_image_candidates.build_episode_shot_image_candidate_manifest(plan)
        report = drama_shot_image_candidates.shot_image_coverage(manifest, plan)
        payload = model_to_dict(report)
        payload["covered_shot_ids"] = [payload["required_shot_ids"][0]]
        payload["missing_first_shot_ids"] = list(payload["required_shot_ids"])
        payload["status"] = "ready"
        fingerprint_payload = dict(payload)
        fingerprint_payload.pop("coverage_fingerprint")
        payload["coverage_fingerprint"] = drama_shot_image_candidates._sha256(
            fingerprint_payload
        )
        with self.assertRaises(ValueError):
            ShotImageCoverageReport(**payload)

    def test_blocked_source_is_distinct_from_missing_first(self) -> None:
        sources = self._seed_candidate_sources(
            "pure-blocked",
            character_artifacts=False,
        )
        plan = sources["shot_image_plan"]
        manifest = drama_shot_image_candidates.build_episode_shot_image_candidate_manifest(plan)
        coverage = drama_shot_image_candidates.shot_image_coverage(manifest, plan)
        self.assertEqual(coverage.status, "blocked_source")
        self.assertEqual(
            coverage.blocked_source_shot_ids,
            [item.shot_id for item in plan.shot_specs],
        )
        self.assertEqual(coverage.missing_first_shot_ids, [])

    def test_every_assembled_shot_needs_fresh_first_but_tail_none_is_valid(self) -> None:
        sources = self._seed_candidate_sources("pure-coverage-ready")
        plan = sources["shot_image_plan"]
        manifest = drama_shot_image_candidates.build_episode_shot_image_candidate_manifest(plan)
        for spec in plan.shot_specs:
            candidate = self._candidate(plan, spec.shot_id)
            manifest = drama_shot_image_candidates.append_shot_image_candidate(
                manifest,
                plan,
                candidate,
                expected_manifest_fingerprint=manifest.manifest_fingerprint,
            )
            pool = next(item for item in manifest.shots if item.shot_id == spec.shot_id)
            manifest = drama_shot_image_candidates.select_shot_image_frame(
                manifest,
                plan,
                shot_id=spec.shot_id,
                frame="first",
                binding={
                    "kind": "direct",
                    "candidate_id": candidate.candidate_id,
                    "candidate_fingerprint": candidate.candidate_fingerprint,
                },
                expected_selection_revision=pool.selection_revision,
                expected_current_binding=None,
                expected_manifest_fingerprint=manifest.manifest_fingerprint,
            )
        coverage = drama_shot_image_candidates.shot_image_coverage(manifest, plan)
        self.assertEqual(coverage.status, "ready")
        self.assertEqual(coverage.covered_shot_ids, coverage.required_shot_ids)
        self.assertTrue(all(pool.tail_binding.kind == "none" for pool in manifest.shots))
