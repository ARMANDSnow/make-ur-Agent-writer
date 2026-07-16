"""iter115: pure provider-neutral shot-video plan assembly."""

from __future__ import annotations

from copy import deepcopy

from src import (
    drama_shot_image_candidate_store,
    drama_shot_image_store,
    drama_shot_video,
)
from src.drama_schemas import (
    EpisodeShotVideoPlan,
    ShotVideoFrameRef,
    ShotVideoRequestSpec,
)
from src.schemas import model_to_dict
from tests._drama_shot_video_base import DramaShotVideoFixture


class DramaShotVideoPlanTests(DramaShotVideoFixture):
    def test_builds_byte_stable_plan_with_exact_first_and_optional_tail(self) -> None:
        sources = self._seed_shot_video_sources("video-pure", with_tail=True)
        first = self._build_video_plan(sources)
        second = self._build_video_plan(sources)
        self.assertEqual(first, second)
        self.assertEqual(
            [item.shot_id for item in first.shot_specs],
            [item.shot_id for item in sources["render_plan"].shots],
        )
        self.assertEqual(first.shot_specs[0].first_frame.binding_kind, "direct")
        self.assertIsNotNone(first.shot_specs[0].tail_frame)
        self.assertIsNone(first.shot_specs[1].tail_frame)
        self.assertEqual(
            first.shot_specs[0].target_duration_seconds,
            sources["render_plan"].shots[0].target_duration_seconds,
        )
        self.assertEqual(
            [item.artifact_sha256 for item in first.shot_specs[0].ordered_references],
            [
                item.artifact_sha256
                for item in sources["shot_image_plan"].shot_specs[0].image_references
            ],
        )

    def test_previous_tail_freezes_exact_source_lineage(self) -> None:
        sources = self._seed_shot_video_sources("video-lineage", previous_tail=True)
        plan = self._build_video_plan(sources)
        first = plan.shot_specs[0]
        second = plan.shot_specs[1]
        self.assertEqual(second.first_frame.binding_kind, "previous_tail")
        self.assertEqual(second.first_frame.source_shot_id, first.shot_id)
        self.assertEqual(
            second.first_frame.candidate_id,
            first.tail_frame.candidate_id,
        )
        self.assertIsNotNone(second.first_frame.source_tail_revision)
        self.assertEqual(
            second.first_frame.target_request_fingerprint,
            second.shot_image_request_fingerprint,
        )

    def test_incomplete_coverage_and_broken_lineage_fail_closed(self) -> None:
        sources = self._seed_candidate_sources("video-incomplete")
        manifest = self._create_manifest("video-incomplete")
        with self.assertRaisesRegex(ValueError, "plan build"):
            drama_shot_video.build_episode_shot_video_plan(
                sources["render_plan"],
                sources["shot_image_plan"],
                manifest,
            )

        ready = self._seed_shot_video_sources("video-broken", previous_tail=True)
        tampered = model_to_dict(ready["candidate_manifest"])
        tampered["shots"][0]["tail_binding_revision"] += 1
        with self.assertRaisesRegex(ValueError, "plan build"):
            drama_shot_video.build_episode_shot_video_plan(
                ready["render_plan"],
                ready["shot_image_plan"],
                tampered,
            )

    def test_unselected_candidate_append_does_not_change_video_plan(self) -> None:
        sources = self._seed_shot_video_sources("video-unselected")
        before = self._build_video_plan(sources)
        first_id = sources["shot_image_plan"].shot_specs[0].shot_id
        manifest, _ = self._append_candidate(
            "video-unselected",
            sources["candidate_manifest"],
            first_id,
            rgba=b"\xaa\xbb\xcc\xff",
        )
        sources["candidate_manifest"] = manifest
        after = self._build_video_plan(sources)
        self.assertEqual(before, after)

    def test_selected_first_change_only_affects_its_shot(self) -> None:
        sources = self._seed_shot_video_sources("video-selected")
        before = self._build_video_plan(sources)
        shot_id = sources["shot_image_plan"].shot_specs[0].shot_id
        manifest, candidate = self._append_candidate(
            "video-selected",
            sources["candidate_manifest"],
            shot_id,
            rgba=b"\xde\xad\xbe\xff",
        )
        pool = next(item for item in manifest.shots if item.shot_id == shot_id)
        desired = {
            "kind": "direct",
            "candidate_id": candidate.candidate_id,
            "candidate_fingerprint": candidate.candidate_fingerprint,
        }
        manifest = drama_shot_image_candidate_store.select_episode_shot_image_frame(
            "video-selected",
            shot_id=shot_id,
            frame="first",
            binding=desired,
            expected_selection_revision=pool.selection_revision,
            expected_current_binding=model_to_dict(pool.first_binding),
            expected_manifest_fingerprint=manifest.manifest_fingerprint,
        )
        sources["candidate_manifest"] = manifest
        after = self._build_video_plan(sources)
        self.assertEqual(
            drama_shot_video.shot_video_plan_affected_ids(before, after),
            [shot_id],
        )

    def test_single_shot_c1_change_reuses_unchanged_historical_candidate(self) -> None:
        sources = self._seed_shot_video_sources("video-c1-reconcile")
        before = self._build_video_plan(sources)
        old_image_plan = sources["shot_image_plan"]
        changed_id = old_image_plan.shot_specs[0].shot_id
        unchanged_id = old_image_plan.shot_specs[1].shot_id
        mapping = {
            shot_id: list(character_ids)
            for shot_id, character_ids in sources["character_mapping"].items()
        }
        mapping[changed_id] = []
        image_plan = drama_shot_image_store.create_episode_shot_image_plan(
            "video-c1-reconcile",
            shot_character_ids=mapping,
            reference_policy=sources["policy"],
            replace_stale=True,
            expected_plan_fingerprint=old_image_plan.plan_fingerprint,
        )
        manifest = drama_shot_image_candidate_store.create_episode_shot_image_candidate_manifest(
            "video-c1-reconcile",
            replace_stale=True,
            expected_manifest_fingerprint=sources[
                "candidate_manifest"
            ].manifest_fingerprint,
        )
        changed_pool = next(item for item in manifest.shots if item.shot_id == changed_id)
        manifest, candidate = self._append_candidate(
            "video-c1-reconcile",
            manifest,
            changed_id,
            rgba=b"\xf1\xe2\xd3\xff",
        )
        changed_pool = next(item for item in manifest.shots if item.shot_id == changed_id)
        manifest = drama_shot_image_candidate_store.select_episode_shot_image_frame(
            "video-c1-reconcile",
            shot_id=changed_id,
            frame="first",
            binding={
                "kind": "direct",
                "candidate_id": candidate.candidate_id,
                "candidate_fingerprint": candidate.candidate_fingerprint,
            },
            expected_selection_revision=changed_pool.selection_revision,
            expected_current_binding=model_to_dict(changed_pool.first_binding),
            expected_manifest_fingerprint=manifest.manifest_fingerprint,
        )
        sources["shot_image_plan"] = image_plan
        sources["candidate_manifest"] = manifest
        after = self._build_video_plan(sources)
        unchanged = next(item for item in after.shot_specs if item.shot_id == unchanged_id)
        self.assertEqual(
            unchanged.first_frame.candidate_source_plan_fingerprint,
            old_image_plan.plan_fingerprint,
        )
        self.assertNotEqual(
            unchanged.first_frame.candidate_source_plan_fingerprint,
            image_plan.plan_fingerprint,
        )
        self.assertEqual(
            drama_shot_video.shot_video_plan_affected_ids(before, after),
            [changed_id],
        )

    def test_strict_schemas_reject_tampering_extra_and_bool(self) -> None:
        sources = self._seed_shot_video_sources("video-schema")
        plan = self._build_video_plan(sources)
        payload = model_to_dict(plan)
        self.assertEqual(EpisodeShotVideoPlan(**payload), plan)

        extra = deepcopy(payload)
        extra["unexpected"] = True
        with self.assertRaises(ValueError):
            EpisodeShotVideoPlan(**extra)

        bad_revision = model_to_dict(plan.shot_specs[0].first_frame)
        bad_revision["selection_revision"] = True
        with self.assertRaises(ValueError):
            ShotVideoFrameRef(**bad_revision)

        tampered = deepcopy(payload)
        tampered["shot_specs"][0]["target_duration_seconds"] += 1
        with self.assertRaises(ValueError):
            EpisodeShotVideoPlan(**tampered)

        forged_selected = deepcopy(payload)
        forged_selected["selected_bindings_fingerprint"] = "f" * 64
        forged_selected["plan_fingerprint"] = drama_shot_video._sha256(
            {key: value for key, value in forged_selected.items() if key != "plan_fingerprint"}
        )
        with self.assertRaisesRegex(ValueError, "selected bindings"):
            EpisodeShotVideoPlan(**forged_selected)

        forged_frame = model_to_dict(plan.shot_specs[0].first_frame)
        forged_frame["artifact"]["path"] = forged_frame["artifact"]["path"].replace(
            forged_frame["source_shot_id"],
            plan.shot_specs[1].shot_id,
        )
        forged_frame["frame_fingerprint"] = drama_shot_video._sha256(
            {key: value for key, value in forged_frame.items() if key != "frame_fingerprint"}
        )
        with self.assertRaisesRegex(ValueError, "path is not canonical"):
            ShotVideoFrameRef(**forged_frame)

        forged_candidate = model_to_dict(plan.shot_specs[0].first_frame)
        forged_candidate["candidate_fingerprint"] = "f" * 64
        forged_candidate["frame_fingerprint"] = drama_shot_video._sha256(
            {key: value for key, value in forged_candidate.items() if key != "frame_fingerprint"}
        )
        with self.assertRaisesRegex(ValueError, "candidate identity"):
            ShotVideoFrameRef(**forged_candidate)

        duplicate_refs = model_to_dict(plan.shot_specs[0])
        duplicate = deepcopy(duplicate_refs["ordered_references"][0])
        duplicate["position"] = len(duplicate_refs["ordered_references"]) + 1
        duplicate_refs["ordered_references"].append(duplicate)
        duplicate_refs["spec_fingerprint"] = drama_shot_video._sha256(
            {key: value for key, value in duplicate_refs.items() if key != "spec_fingerprint"}
        )
        with self.assertRaisesRegex(ValueError, "references must be unique"):
            ShotVideoRequestSpec(**duplicate_refs)

    def test_fully_rehashed_previous_tail_revision_forgery_is_rejected(self) -> None:
        sources = self._seed_shot_video_sources("video-lineage-forge", previous_tail=True)
        payload = model_to_dict(self._build_video_plan(sources))
        forged = payload["shot_specs"][1]["first_frame"]
        forged["source_tail_revision"] += 1
        forged["frame_fingerprint"] = drama_shot_video._sha256(
            {key: value for key, value in forged.items() if key != "frame_fingerprint"}
        )
        spec = payload["shot_specs"][1]
        spec["spec_fingerprint"] = drama_shot_video._sha256(
            {key: value for key, value in spec.items() if key != "spec_fingerprint"}
        )
        selected_payload = [
            {
                "shot_id": item["shot_id"],
                "selection_revision": item["selection_revision"],
                "first_frame_fingerprint": item["first_frame"]["frame_fingerprint"],
                "tail_frame_fingerprint": (
                    item["tail_frame"]["frame_fingerprint"]
                    if item["tail_frame"] is not None
                    else None
                ),
            }
            for item in payload["shot_specs"]
        ]
        payload["selected_bindings_fingerprint"] = drama_shot_video._sha256(
            selected_payload
        )
        payload["plan_fingerprint"] = drama_shot_video._sha256(
            {key: value for key, value in payload.items() if key != "plan_fingerprint"}
        )
        with self.assertRaisesRegex(ValueError, "previous-tail first frame lineage"):
            EpisodeShotVideoPlan(**payload)
