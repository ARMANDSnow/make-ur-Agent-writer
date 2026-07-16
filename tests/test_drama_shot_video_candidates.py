"""iter116: pure D2 video candidate, selection, and coverage behavior."""

from __future__ import annotations

from copy import deepcopy

from src import drama_shot_video, drama_shot_video_candidate_store, drama_shot_video_candidates
from src.drama_schemas import (
    EpisodeShotVideoCandidateManifest,
    EpisodeShotVideoPlan,
    ShotVideoArtifact,
    ShotVideoCandidate,
)
from src.schemas import model_to_dict
from tests._drama_shot_video_candidate_base import DramaShotVideoCandidateFixture


class DramaShotVideoCandidateTests(DramaShotVideoCandidateFixture):
    def _local_candidate(self, plan, shot_id, *, marker=0, placeholder=False):
        data = self._mp4_variant(marker)
        import hashlib

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
            is_placeholder=placeholder,
        )

    def test_manifest_and_candidate_are_byte_stable_and_append_does_not_select(self) -> None:
        sources = self._seed_shot_video_sources("video-candidate-pure")
        plan = self._build_video_plan(sources)
        first = drama_shot_video_candidates.build_episode_shot_video_candidate_manifest(plan)
        second = drama_shot_video_candidates.build_episode_shot_video_candidate_manifest(plan)
        self.assertEqual(first, second)
        shot_id = plan.shot_specs[0].shot_id
        candidate = self._local_candidate(plan, shot_id)
        appended = drama_shot_video_candidates.append_shot_video_candidate(
            first,
            plan,
            candidate,
            expected_manifest_fingerprint=first.manifest_fingerprint,
        )
        pool = appended.shots[0]
        self.assertEqual(pool.candidates, [candidate])
        self.assertIsNone(pool.selected)
        self.assertEqual(pool.selection_revision, 0)

    def test_guarded_selection_supports_only_exact_lost_response_replay(self) -> None:
        sources = self._seed_shot_video_sources("video-candidate-select")
        plan = self._build_video_plan(sources)
        manifest = drama_shot_video_candidates.build_episode_shot_video_candidate_manifest(plan)
        candidate = self._local_candidate(plan, plan.shot_specs[0].shot_id)
        manifest = drama_shot_video_candidates.append_shot_video_candidate(
            manifest,
            plan,
            candidate,
            expected_manifest_fingerprint=manifest.manifest_fingerprint,
        )
        desired = {
            "candidate_id": candidate.candidate_id,
            "candidate_fingerprint": candidate.candidate_fingerprint,
        }
        before = manifest.manifest_fingerprint
        selected = drama_shot_video_candidates.select_shot_video_candidate(
            manifest,
            plan,
            shot_id=candidate.shot_id,
            selection=desired,
            expected_selection_revision=0,
            expected_current_selection=None,
            expected_manifest_fingerprint=before,
        )
        replay = drama_shot_video_candidates.select_shot_video_candidate(
            selected,
            plan,
            shot_id=candidate.shot_id,
            selection=desired,
            expected_selection_revision=0,
            expected_current_selection=None,
            expected_manifest_fingerprint=before,
        )
        self.assertEqual(replay, selected)
        with self.assertRaises(ValueError):
            drama_shot_video_candidates.select_shot_video_candidate(
                selected,
                plan,
                shot_id=candidate.shot_id,
                selection=desired,
                expected_selection_revision=0,
                expected_current_selection=desired,
                expected_manifest_fingerprint=before,
            )

    def test_coverage_partitions_missing_ready_placeholder_and_invalid(self) -> None:
        sources = self._seed_shot_video_sources("video-candidate-coverage")
        plan = self._build_video_plan(sources)
        manifest = drama_shot_video_candidates.build_episode_shot_video_candidate_manifest(plan)
        self.assertEqual(
            drama_shot_video_candidates.shot_video_coverage(manifest, plan).status,
            "incomplete",
        )
        candidates = []
        for index, spec in enumerate(plan.shot_specs):
            candidate = self._local_candidate(
                plan,
                spec.shot_id,
                marker=index,
                placeholder=index == 0,
            )
            manifest = drama_shot_video_candidates.append_shot_video_candidate(
                manifest,
                plan,
                candidate,
                expected_manifest_fingerprint=manifest.manifest_fingerprint,
            )
            manifest = drama_shot_video_candidates.select_shot_video_candidate(
                manifest,
                plan,
                shot_id=spec.shot_id,
                selection={
                    "candidate_id": candidate.candidate_id,
                    "candidate_fingerprint": candidate.candidate_fingerprint,
                },
                expected_selection_revision=0,
                expected_current_selection=None,
                expected_manifest_fingerprint=manifest.manifest_fingerprint,
            )
            candidates.append(candidate)
        report = drama_shot_video_candidates.shot_video_coverage(manifest, plan)
        self.assertEqual(report.status, "invalid")
        self.assertEqual(report.non_production_shot_ids, [plan.shot_specs[0].shot_id])
        report = drama_shot_video_candidates.shot_video_coverage(
            manifest,
            plan,
            invalid_artifact_shot_ids=[plan.shot_specs[1].shot_id],
        )
        self.assertEqual(report.status, "invalid")
        self.assertEqual(report.invalid_artifact_shot_ids, [plan.shot_specs[1].shot_id])

    def test_reconcile_preserves_history_but_stales_only_changed_shot(self) -> None:
        sources = self._seed_shot_video_sources("video-candidate-reconcile")
        plan = self._build_video_plan(sources)
        manifest = drama_shot_video_candidates.build_episode_shot_video_candidate_manifest(plan)
        for index, spec in enumerate(plan.shot_specs):
            candidate = self._local_candidate(plan, spec.shot_id, marker=index)
            manifest = drama_shot_video_candidates.append_shot_video_candidate(
                manifest,
                plan,
                candidate,
                expected_manifest_fingerprint=manifest.manifest_fingerprint,
            )
            manifest = drama_shot_video_candidates.select_shot_video_candidate(
                manifest,
                plan,
                shot_id=spec.shot_id,
                selection={
                    "candidate_id": candidate.candidate_id,
                    "candidate_fingerprint": candidate.candidate_fingerprint,
                },
                expected_selection_revision=0,
                expected_current_selection=None,
                expected_manifest_fingerprint=manifest.manifest_fingerprint,
            )
        payload = model_to_dict(plan)
        payload["shot_specs"][0]["transition_hint"] = "cut"
        payload["shot_specs"][0]["spec_fingerprint"] = drama_shot_video._sha256(
            {
                key: value
                for key, value in payload["shot_specs"][0].items()
                if key != "spec_fingerprint"
            }
        )
        payload["plan_fingerprint"] = drama_shot_video._sha256(
            {key: value for key, value in payload.items() if key != "plan_fingerprint"}
        )
        changed = EpisodeShotVideoPlan(**payload)
        self.assertEqual(
            drama_shot_video_candidates.shot_video_candidate_affected_ids(
                manifest,
                changed,
            ),
            [plan.shot_specs[0].shot_id],
        )
        reconciled = drama_shot_video_candidates.reconcile_shot_video_candidate_manifest(
            manifest,
            changed,
            expected_manifest_fingerprint=manifest.manifest_fingerprint,
        )
        self.assertEqual(reconciled.shots[1], manifest.shots[1])
        report = drama_shot_video_candidates.shot_video_coverage(reconciled, changed)
        self.assertEqual(report.stale_candidate_shot_ids, [plan.shot_specs[0].shot_id])
        self.assertEqual(
            report.selected_fresh_shot_ids,
            [item.shot_id for item in plan.shot_specs[1:]],
        )

    def test_reconcile_moves_removed_shot_history_to_retired_audit_pool(self) -> None:
        sources = self._seed_shot_video_sources("video-candidate-retired")
        plan = self._build_video_plan(sources)
        manifest = drama_shot_video_candidates.build_episode_shot_video_candidate_manifest(plan)
        removed_spec = plan.shot_specs[-1]
        candidate = self._local_candidate(plan, removed_spec.shot_id)
        manifest = drama_shot_video_candidates.append_shot_video_candidate(
            manifest,
            plan,
            candidate,
            expected_manifest_fingerprint=manifest.manifest_fingerprint,
        )
        payload = model_to_dict(plan)
        payload["shot_specs"] = payload["shot_specs"][:-1]
        payload["selected_bindings_fingerprint"] = drama_shot_video._sha256(
            [
                {
                    "shot_id": spec["shot_id"],
                    "selection_revision": spec["selection_revision"],
                    "first_frame_fingerprint": spec["first_frame"]["frame_fingerprint"],
                    "tail_frame_fingerprint": (
                        spec["tail_frame"]["frame_fingerprint"]
                        if spec["tail_frame"] is not None
                        else None
                    ),
                }
                for spec in payload["shot_specs"]
            ]
        )
        payload["plan_fingerprint"] = drama_shot_video._sha256(
            {key: value for key, value in payload.items() if key != "plan_fingerprint"}
        )
        reduced = EpisodeShotVideoPlan(**payload)
        reconciled = drama_shot_video_candidates.reconcile_shot_video_candidate_manifest(
            manifest,
            reduced,
            expected_manifest_fingerprint=manifest.manifest_fingerprint,
        )
        self.assertNotIn(removed_spec.shot_id, [item.shot_id for item in reconciled.shots])
        retired = next(
            item
            for item in reconciled.retired_shots
            if item.shot_id == removed_spec.shot_id
        )
        self.assertEqual(retired.candidates, [candidate])

    def test_episode_two_candidate_identity_and_path_have_no_episode_one_literal(self) -> None:
        sources = self._seed_shot_video_sources("video-candidate-episode-two")
        payload = model_to_dict(self._build_video_plan(sources))
        payload["episode_no"] = 2
        for spec in payload["shot_specs"]:
            for frame_name in ("first_frame", "tail_frame"):
                frame = spec[frame_name]
                if frame is None:
                    continue
                frame["episode_no"] = 2
                frame["artifact"]["path"] = frame["artifact"]["path"].replace(
                    "episode_01",
                    "episode_02",
                )
                candidate_basis = {
                    "schema_version": 1,
                    "season_no": frame["season_no"],
                    "episode_no": 2,
                    "shot_id": frame["source_shot_id"],
                    "source_plan_fingerprint": frame[
                        "candidate_source_plan_fingerprint"
                    ],
                    "request_fingerprint": frame[
                        "candidate_request_fingerprint"
                    ],
                    "source_kind": "local_png",
                    "artifact": {
                        key: value
                        for key, value in frame["artifact"].items()
                        if key != "path"
                    },
                }
                candidate_fingerprint = drama_shot_video._sha256(candidate_basis)
                frame["candidate_fingerprint"] = candidate_fingerprint
                frame["candidate_id"] = f"sic_{candidate_fingerprint[:24]}"
                frame["artifact"]["path"] = (
                    f"outputs/episodes/episode_02.shot_images/"
                    f"{frame['source_shot_id']}/{frame['candidate_id']}.png"
                )
                frame["frame_fingerprint"] = drama_shot_video._sha256(
                    {
                        key: value
                        for key, value in frame.items()
                        if key != "frame_fingerprint"
                    }
                )
            spec["spec_fingerprint"] = drama_shot_video._sha256(
                {
                    key: value
                    for key, value in spec.items()
                    if key != "spec_fingerprint"
                }
            )
        payload["selected_bindings_fingerprint"] = drama_shot_video._sha256(
            [
                {
                    "shot_id": spec["shot_id"],
                    "selection_revision": spec["selection_revision"],
                    "first_frame_fingerprint": spec["first_frame"][
                        "frame_fingerprint"
                    ],
                    "tail_frame_fingerprint": (
                        spec["tail_frame"]["frame_fingerprint"]
                        if spec["tail_frame"] is not None
                        else None
                    ),
                }
                for spec in payload["shot_specs"]
            ]
        )
        payload["plan_fingerprint"] = drama_shot_video._sha256(
            {key: value for key, value in payload.items() if key != "plan_fingerprint"}
        )
        plan = EpisodeShotVideoPlan(**payload)
        candidate = self._local_candidate(plan, plan.shot_specs[0].shot_id)
        self.assertEqual(candidate.episode_no, 2)
        self.assertIn("episode_02.shot_videos", candidate.artifact.path)
        self.assertNotIn("episode_01", candidate.artifact.path)

    def test_strict_schema_rejects_extra_bool_path_and_rehashed_tampering(self) -> None:
        sources = self._seed_shot_video_sources("video-candidate-schema")
        plan = self._build_video_plan(sources)
        candidate = self._local_candidate(plan, plan.shot_specs[0].shot_id)
        payload = model_to_dict(candidate)
        self.assertEqual(ShotVideoCandidate(**payload), candidate)
        extra = deepcopy(payload)
        extra["provider"] = "fake"
        with self.assertRaises(ValueError):
            ShotVideoCandidate(**extra)
        bad_bool = model_to_dict(candidate.artifact)
        bad_bool["duration_milliseconds"] = True
        with self.assertRaises(ValueError):
            ShotVideoArtifact(**bad_bool)
        bad_path = model_to_dict(candidate.artifact)
        bad_path["path"] = "../candidate.mp4"
        with self.assertRaises(ValueError):
            ShotVideoArtifact(**bad_path)
        forged = deepcopy(payload)
        forged["artifact"]["width"] += 1
        with self.assertRaises(ValueError):
            ShotVideoCandidate(**forged)

        manifest = drama_shot_video_candidates.build_episode_shot_video_candidate_manifest(plan)
        manifest_payload = model_to_dict(manifest)
        manifest_payload["shots"][0]["current_request_fingerprint"] = "f" * 64
        manifest_payload["shots"][0]["pool_fingerprint"] = drama_shot_video._sha256(
            {
                key: value
                for key, value in manifest_payload["shots"][0].items()
                if key != "pool_fingerprint"
            }
        )
        manifest_payload["manifest_fingerprint"] = drama_shot_video._sha256(
            {
                key: value
                for key, value in manifest_payload.items()
                if key != "manifest_fingerprint"
            }
        )
        forged_manifest = EpisodeShotVideoCandidateManifest(**manifest_payload)
        with self.assertRaisesRegex(ValueError, "request is stale"):
            drama_shot_video_candidates.append_shot_video_candidate(
                forged_manifest,
                plan,
                candidate,
                expected_manifest_fingerprint=forged_manifest.manifest_fingerprint,
            )
