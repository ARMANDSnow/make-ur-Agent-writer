"""iter116: strict D2 video candidate store and artifact behavior."""

from __future__ import annotations

import os
import socket
from unittest.mock import patch

from src import (
    drama_shot_image_candidate_store,
    drama_shot_video_candidate_store,
    drama_shot_video_store,
    paths,
)
from src.schemas import model_to_dict
from src.web.workspace_ctx import use_workspace
from src.workspace_lock import acquire_write_lock
from tests._drama_shot_video_candidate_base import DramaShotVideoCandidateFixture


class DramaShotVideoCandidateStoreTests(DramaShotVideoCandidateFixture):
    def test_state_create_append_select_and_ready_coverage_are_zero_network(self) -> None:
        self._make_drama_workspace("video-assets-blocked", "霸总")
        self.assertEqual(
            drama_shot_video_candidate_store.inspect_episode_shot_video_candidates(
                "video-assets-blocked"
            ).state,
            "blocked_source",
        )
        sources = self._seed_video_candidate_sources("video-assets-ready")
        manifest = sources["video_candidate_manifest"]
        self.assertEqual(
            drama_shot_video_candidate_store.inspect_episode_shot_video_candidates(
                "video-assets-ready"
            ).coverage.status,
            "incomplete",
        )
        with patch.object(socket, "socket", side_effect=AssertionError("network")):
            for index, spec in enumerate(sources["video_plan"].shot_specs):
                manifest, candidate = self._append_video_candidate(
                    "video-assets-ready",
                    manifest,
                    spec.shot_id,
                    marker=index,
                )
                manifest = self._select_video_candidate(
                    "video-assets-ready",
                    manifest,
                    candidate,
                )
        inspection = drama_shot_video_candidate_store.inspect_episode_shot_video_candidates(
            "video-assets-ready"
        )
        self.assertEqual(inspection.state, "fresh")
        self.assertEqual(inspection.coverage.status, "ready")
        self.assertEqual(
            drama_shot_video_candidate_store.load_fresh_episode_shot_video_candidates(
                "video-assets-ready"
            ),
            manifest,
        )

    def test_append_is_content_addressed_idempotent_and_does_not_auto_select(self) -> None:
        sources = self._seed_video_candidate_sources("video-assets-append")
        manifest, candidate = self._append_video_candidate(
            "video-assets-append",
            sources["video_candidate_manifest"],
            sources["video_plan"].shot_specs[0].shot_id,
        )
        before = drama_shot_video_candidate_store.shot_video_candidate_manifest_path(
            "video-assets-append"
        ).read_bytes()
        replay, replay_candidate = drama_shot_video_candidate_store.append_local_shot_video_candidate(
            "video-assets-append",
            shot_id=candidate.shot_id,
            mp4_bytes=self._mp4_variant(),
            expected_manifest_fingerprint=sources[
                "video_candidate_manifest"
            ].manifest_fingerprint,
        )
        self.assertEqual(replay, manifest)
        self.assertEqual(replay_candidate, candidate)
        self.assertEqual(
            drama_shot_video_candidate_store.shot_video_candidate_manifest_path(
                "video-assets-append"
            ).read_bytes(),
            before,
        )
        self.assertIsNone(replay.shots[0].selected)

    def test_placeholder_selection_is_explicitly_not_production_ready(self) -> None:
        sources = self._seed_video_candidate_sources("video-assets-placeholder")
        manifest, candidate = self._append_video_candidate(
            "video-assets-placeholder",
            sources["video_candidate_manifest"],
            sources["video_plan"].shot_specs[0].shot_id,
            is_placeholder=True,
        )
        manifest = self._select_video_candidate(
            "video-assets-placeholder",
            manifest,
            candidate,
        )
        inspection = drama_shot_video_candidate_store.inspect_episode_shot_video_candidates(
            "video-assets-placeholder"
        )
        self.assertEqual(inspection.state, "fresh")
        self.assertEqual(inspection.coverage.status, "invalid")
        self.assertEqual(inspection.coverage.non_production_shot_ids, [candidate.shot_id])

    def test_bad_mp4_and_occupied_artifact_fail_closed(self) -> None:
        sources = self._seed_video_candidate_sources("video-assets-bad-mp4")
        with self.assertRaisesRegex(ValueError, "valid MP4"):
            drama_shot_video_candidate_store.append_local_shot_video_candidate(
                "video-assets-bad-mp4",
                shot_id=sources["video_plan"].shot_specs[0].shot_id,
                mp4_bytes=b"not-mp4",
                expected_manifest_fingerprint=sources[
                    "video_candidate_manifest"
                ].manifest_fingerprint,
            )
        forged_offset = bytearray(self._MOCK_MP4)
        forged_offset[-1] = 0
        with self.assertRaisesRegex(ValueError, "valid MP4"):
            drama_shot_video_candidate_store.append_local_shot_video_candidate(
                "video-assets-bad-mp4",
                shot_id=sources["video_plan"].shot_specs[0].shot_id,
                mp4_bytes=bytes(forged_offset),
                expected_manifest_fingerprint=sources[
                    "video_candidate_manifest"
                ].manifest_fingerprint,
            )
        box_bomb = b"\x00\x00\x00\x08free" * (
            drama_shot_video_candidate_store.MAX_MP4_BOXES_PER_LEVEL + 1
        )
        with self.assertRaisesRegex(ValueError, "valid MP4"):
            drama_shot_video_candidate_store.append_local_shot_video_candidate(
                "video-assets-bad-mp4",
                shot_id=sources["video_plan"].shot_specs[0].shot_id,
                mp4_bytes=box_bomb,
                expected_manifest_fingerprint=sources[
                    "video_candidate_manifest"
                ].manifest_fingerprint,
            )

        name = "video-assets-symlink-artifact"
        sources = self._seed_video_candidate_sources(name)
        data = self._mp4_variant()
        identity = drama_shot_video_candidate_store._candidate_payload_identity(data)
        from src import drama_shot_video_candidates

        candidate = drama_shot_video_candidates.build_shot_video_candidate(
            sources["video_plan"],
            shot_id=sources["video_plan"].shot_specs[0].shot_id,
            artifact_sha256=identity[0],
            artifact_size_bytes=identity[1],
            duration_milliseconds=identity[2],
            width=identity[3],
            height=identity[4],
            has_audio_track=identity[5],
        )
        target = paths.workspace_root(name) / candidate.artifact.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to("missing.mp4")
        with self.assertRaisesRegex(ValueError, "target is invalid"):
            drama_shot_video_candidate_store.append_local_shot_video_candidate(
                name,
                shot_id=candidate.shot_id,
                mp4_bytes=data,
                expected_manifest_fingerprint=sources[
                    "video_candidate_manifest"
                ].manifest_fingerprint,
            )

    def test_missing_artifact_invalidates_manifest_and_exact_repair_recovers(self) -> None:
        sources = self._seed_video_candidate_sources("video-assets-repair")
        manifest, candidate = self._append_video_candidate(
            "video-assets-repair",
            sources["video_candidate_manifest"],
            sources["video_plan"].shot_specs[0].shot_id,
        )
        artifact = paths.workspace_root("video-assets-repair") / candidate.artifact.path
        artifact.unlink()
        unselected = drama_shot_video_candidate_store.inspect_episode_shot_video_candidates(
            "video-assets-repair"
        )
        self.assertEqual(unselected.state, "fresh")
        self.assertEqual(unselected.coverage.status, "incomplete")
        repaired = drama_shot_video_candidate_store.repair_referenced_shot_video_candidate_artifact(
            "video-assets-repair",
            candidate_id=candidate.candidate_id,
            mp4_bytes=self._mp4_variant(),
            expected_manifest_fingerprint=manifest.manifest_fingerprint,
        )
        self.assertEqual(repaired, candidate)
        manifest = self._select_video_candidate(
            "video-assets-repair",
            manifest,
            candidate,
        )
        artifact.unlink()
        invalid = drama_shot_video_candidate_store.inspect_episode_shot_video_candidates(
            "video-assets-repair"
        )
        self.assertEqual(
            invalid.state,
            "invalid",
        )
        self.assertEqual(invalid.coverage.status, "invalid")
        self.assertEqual(invalid.coverage.invalid_artifact_shot_ids, [candidate.shot_id])
        repaired = drama_shot_video_candidate_store.repair_referenced_shot_video_candidate_artifact(
            "video-assets-repair",
            candidate_id=candidate.candidate_id,
            mp4_bytes=self._mp4_variant(),
            expected_manifest_fingerprint=manifest.manifest_fingerprint,
        )
        self.assertEqual(repaired, candidate)
        self.assertEqual(
            drama_shot_video_candidate_store.inspect_episode_shot_video_candidates(
                "video-assets-repair"
            ).state,
            "fresh",
        )

    def test_d1_change_stales_exact_shot_and_reconcile_preserves_other_selection(self) -> None:
        name = "video-assets-reconcile"
        sources = self._seed_video_candidate_sources(name)
        manifest = sources["video_candidate_manifest"]
        selected = {}
        for index, spec in enumerate(sources["video_plan"].shot_specs):
            manifest, candidate = self._append_video_candidate(
                name,
                manifest,
                spec.shot_id,
                marker=index,
            )
            manifest = self._select_video_candidate(name, manifest, candidate)
            selected[spec.shot_id] = candidate

        shot_id = sources["shot_image_plan"].shot_specs[0].shot_id
        image_manifest, image_candidate = self._append_candidate(
            name,
            sources["candidate_manifest"],
            shot_id,
            rgba=b"\x44\x55\x66\xff",
        )
        pool = next(item for item in image_manifest.shots if item.shot_id == shot_id)
        image_manifest = drama_shot_image_candidate_store.select_episode_shot_image_frame(
            name,
            shot_id=shot_id,
            frame="first",
            binding={
                "kind": "direct",
                "candidate_id": image_candidate.candidate_id,
                "candidate_fingerprint": image_candidate.candidate_fingerprint,
            },
            expected_selection_revision=pool.selection_revision,
            expected_current_binding=model_to_dict(pool.first_binding),
            expected_manifest_fingerprint=image_manifest.manifest_fingerprint,
        )
        old_d1 = sources["video_plan"]
        drama_shot_video_store.create_episode_shot_video_plan(
            name,
            replace_stale=True,
            expected_plan_fingerprint=old_d1.plan_fingerprint,
        )
        inspection = drama_shot_video_candidate_store.inspect_episode_shot_video_candidates(name)
        self.assertEqual(inspection.state, "stale")
        self.assertEqual(inspection.affected_shot_ids, (shot_id,))
        reconciled = drama_shot_video_candidate_store.create_episode_shot_video_candidate_manifest(
            name,
            replace_stale=True,
            expected_manifest_fingerprint=manifest.manifest_fingerprint,
        )
        unchanged_id = sources["video_plan"].shot_specs[1].shot_id
        unchanged = next(item for item in reconciled.shots if item.shot_id == unchanged_id)
        self.assertEqual(unchanged.selected.candidate_id, selected[unchanged_id].candidate_id)
        changed = next(item for item in reconciled.shots if item.shot_id == shot_id)
        self.assertEqual(changed.selected.candidate_id, selected[shot_id].candidate_id)
        coverage = drama_shot_video_candidate_store.inspect_episode_shot_video_candidates(name).coverage
        self.assertEqual(coverage.stale_candidate_shot_ids, [shot_id])

    def test_blocked_source_and_selected_artifact_return_per_shot_coverage(self) -> None:
        name = "video-assets-blocker-projection"
        sources = self._seed_video_candidate_sources(name)
        manifest, candidate = self._append_video_candidate(
            name,
            sources["video_candidate_manifest"],
            sources["video_plan"].shot_specs[0].shot_id,
        )
        manifest = self._select_video_candidate(name, manifest, candidate)
        artifact = paths.workspace_root(name) / candidate.artifact.path
        artifact.unlink()
        invalid = drama_shot_video_candidate_store.inspect_episode_shot_video_candidates(name)
        self.assertEqual(invalid.state, "invalid")
        self.assertEqual(invalid.affected_shot_ids, (candidate.shot_id,))
        self.assertEqual(invalid.coverage.invalid_artifact_shot_ids, [candidate.shot_id])
        artifact.write_bytes(self._mp4_variant())
        drama_shot_video_store.shot_video_plan_path(name).unlink()
        blocked = drama_shot_video_candidate_store.inspect_episode_shot_video_candidates(name)
        self.assertEqual(blocked.state, "blocked_source")
        self.assertEqual(
            blocked.coverage.blocked_source_shot_ids,
            [item.shot_id for item in manifest.shots],
        )
        self.assertEqual(blocked.affected_shot_ids, tuple(blocked.coverage.required_shot_ids))

    def test_bounded_write_recovery_removes_owned_temp_and_orphan(self) -> None:
        name = "video-assets-crash-residue"
        sources = self._seed_video_candidate_sources(name)
        shot_id = sources["video_plan"].shot_specs[0].shot_id
        directory = (
            paths.workspace_root(name)
            / f"outputs/episodes/episode_01.shot_videos/{shot_id}"
        )
        directory.mkdir(parents=True, exist_ok=True)
        temp = directory / (".svc_" + "a" * 24 + ".mp4.tmp." + "b" * 32)
        orphan = directory / ("svc_" + "c" * 24 + ".mp4")
        temp.write_bytes(b"residue")
        orphan.write_bytes(b"residue")
        self._append_video_candidate(
            name,
            sources["video_candidate_manifest"],
            shot_id,
        )
        self.assertFalse(temp.exists())
        self.assertFalse(orphan.exists())

    def test_invalid_manifest_special_files_lock_and_short_write_fail_closed(self) -> None:
        self._seed_video_candidate_sources("video-assets-invalid")
        path = drama_shot_video_candidate_store.shot_video_candidate_manifest_path(
            "video-assets-invalid"
        )
        path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
        self.assertEqual(
            drama_shot_video_candidate_store.inspect_episode_shot_video_candidates(
                "video-assets-invalid"
            ).state,
            "invalid",
        )
        with self.assertRaisesRegex(ValueError, "repaired explicitly"):
            drama_shot_video_candidate_store.create_episode_shot_video_candidate_manifest(
                "video-assets-invalid",
                replace_stale=True,
            )

        for suffix, create_special in (
            ("directory", lambda target: target.mkdir()),
            ("fifo", lambda target: os.mkfifo(target)),
        ):
            name = f"video-assets-{suffix}"
            self._seed_shot_video_sources(name)
            drama_shot_video_store.create_episode_shot_video_plan(name)
            target = drama_shot_video_candidate_store.shot_video_candidate_manifest_path(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            create_special(target)
            self.assertEqual(
                drama_shot_video_candidate_store.inspect_episode_shot_video_candidates(name).state,
                "invalid",
            )

        self._seed_video_candidate_sources("video-assets-lock")
        with use_workspace("video-assets-lock"), acquire_write_lock(source="test"):
            with self.assertRaises(ValueError):
                drama_shot_video_candidate_store.create_episode_shot_video_candidate_manifest(
                    "video-assets-lock"
                )

        self._seed_shot_video_sources("video-assets-short-write")
        drama_shot_video_store.create_episode_shot_video_plan("video-assets-short-write")
        real_write = os.write

        def short_write(fd, data):
            if b"drama_episode_shot_video_assets" in bytes(data):
                return 0
            return real_write(fd, data)

        with patch(
            "src.drama_shot_video_candidate_store.os.write",
            side_effect=short_write,
        ):
            with self.assertRaisesRegex(ValueError, "written safely"):
                drama_shot_video_candidate_store.create_episode_shot_video_candidate_manifest(
                    "video-assets-short-write"
                )
        parent = drama_shot_video_candidate_store.shot_video_candidate_manifest_path(
            "video-assets-short-write"
        ).parent
        self.assertEqual(
            list(parent.glob(".episode_01.shot_video_assets.json.tmp.*")),
            [],
        )

    def test_source_and_manifest_target_races_leave_no_committed_manifest(self) -> None:
        name = "video-assets-source-race"
        self._seed_shot_video_sources(name)
        plan = drama_shot_video_store.create_episode_shot_video_plan(name)
        changed = plan.model_copy(update={"plan_fingerprint": "f" * 64})
        target = drama_shot_video_candidate_store.shot_video_candidate_manifest_path(name)
        with patch.object(
            drama_shot_video_candidate_store,
            "load_fresh_episode_shot_video_plan",
            side_effect=[plan, changed],
        ):
            with self.assertRaisesRegex(ValueError, "plan changed"):
                drama_shot_video_candidate_store.create_episode_shot_video_candidate_manifest(
                    name
                )
        self.assertFalse(target.exists())

        name = "video-assets-target-race"
        self._seed_shot_video_sources(name)
        drama_shot_video_store.create_episode_shot_video_plan(name)
        real_token = drama_shot_video_candidate_store._target_token_at
        calls = 0

        def raced_token(directory_fd, filename):
            nonlocal calls
            calls += 1
            if calls == 2:
                return ("invalid",)
            return real_token(directory_fd, filename)

        with patch.object(
            drama_shot_video_candidate_store,
            "_target_token_at",
            side_effect=raced_token,
        ):
            with self.assertRaisesRegex(ValueError, "changed concurrently"):
                drama_shot_video_candidate_store.create_episode_shot_video_candidate_manifest(
                    name
                )
        self.assertFalse(
            drama_shot_video_candidate_store.shot_video_candidate_manifest_path(
                name
            ).exists()
        )

    def test_artifact_short_write_cleans_owned_temp_and_final(self) -> None:
        name = "video-assets-artifact-short"
        sources = self._seed_video_candidate_sources(name)
        data = self._mp4_variant()
        identity = drama_shot_video_candidate_store._candidate_payload_identity(data)
        from src import drama_shot_video_candidates

        candidate = drama_shot_video_candidates.build_shot_video_candidate(
            sources["video_plan"],
            shot_id=sources["video_plan"].shot_specs[0].shot_id,
            artifact_sha256=identity[0],
            artifact_size_bytes=identity[1],
            duration_milliseconds=identity[2],
            width=identity[3],
            height=identity[4],
            has_audio_track=identity[5],
        )
        real_write = os.write

        def short_write(fd, payload):
            if bytes(payload).startswith(b"\x00\x00\x00\x1cftyp"):
                return 0
            return real_write(fd, payload)

        with patch(
            "src.drama_shot_video_candidate_store.os.write",
            side_effect=short_write,
        ):
            with self.assertRaisesRegex(ValueError, "written safely"):
                drama_shot_video_candidate_store.append_local_shot_video_candidate(
                    name,
                    shot_id=candidate.shot_id,
                    mp4_bytes=data,
                    expected_manifest_fingerprint=sources[
                        "video_candidate_manifest"
                    ].manifest_fingerprint,
                )
        artifact = paths.workspace_root(name) / candidate.artifact.path
        self.assertFalse(artifact.exists())
        self.assertEqual(list(artifact.parent.glob(f".{candidate.candidate_id}.mp4.tmp.*")), [])

    def test_symlink_oversize_and_deep_manifests_are_invalid(self) -> None:
        name = "video-assets-manifest-symlink"
        self._seed_shot_video_sources(name)
        drama_shot_video_store.create_episode_shot_video_plan(name)
        target = drama_shot_video_candidate_store.shot_video_candidate_manifest_path(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to("missing.json")
        self.assertEqual(
            drama_shot_video_candidate_store.inspect_episode_shot_video_candidates(name).state,
            "invalid",
        )

        name = "video-assets-manifest-oversize"
        self._seed_shot_video_sources(name)
        drama_shot_video_store.create_episode_shot_video_plan(name)
        target = drama_shot_video_candidate_store.shot_video_candidate_manifest_path(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(
            b"x" * (drama_shot_video_candidate_store.MAX_SHOT_VIDEO_CANDIDATE_MANIFEST_BYTES + 1)
        )
        self.assertEqual(
            drama_shot_video_candidate_store.inspect_episode_shot_video_candidates(name).state,
            "invalid",
        )

        name = "video-assets-manifest-deep"
        self._seed_shot_video_sources(name)
        drama_shot_video_store.create_episode_shot_video_plan(name)
        target = drama_shot_video_candidate_store.shot_video_candidate_manifest_path(name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("[" * 300 + "]" * 300, encoding="utf-8")
        self.assertEqual(
            drama_shot_video_candidate_store.inspect_episode_shot_video_candidates(name).state,
            "invalid",
        )

    def test_selection_lost_response_replay_rechecks_target_token(self) -> None:
        name = "video-assets-selection-race"
        sources = self._seed_video_candidate_sources(name)
        before, candidate = self._append_video_candidate(
            name,
            sources["video_candidate_manifest"],
            sources["video_plan"].shot_specs[0].shot_id,
        )
        selected = self._select_video_candidate(name, before, candidate)
        desired = model_to_dict(selected.shots[0].selected)
        real_token = drama_shot_video_candidate_store._target_token
        calls = 0

        def raced_token(root, path):
            nonlocal calls
            calls += 1
            if calls == 2:
                return ("invalid",)
            return real_token(root, path)

        with patch.object(
            drama_shot_video_candidate_store,
            "_target_token",
            side_effect=raced_token,
        ):
            with self.assertRaisesRegex(ValueError, "changed concurrently"):
                drama_shot_video_candidate_store.select_episode_shot_video_candidate(
                    name,
                    shot_id=candidate.shot_id,
                    selection=desired,
                    expected_selection_revision=0,
                    expected_current_selection=None,
                    expected_manifest_fingerprint=before.manifest_fingerprint,
                )

    def test_episode_path_is_generic_and_bool_is_rejected(self) -> None:
        self.assertEqual(
            drama_shot_video_candidate_store.shot_video_candidate_manifest_path(
                "anything",
                episode_no=2,
            ).name,
            "episode_02.shot_video_assets.json",
        )
        self._seed_video_candidate_sources("video-assets-bool")
        with self.assertRaises(ValueError):
            drama_shot_video_candidate_store.create_episode_shot_video_candidate_manifest(
                "video-assets-bool",
                replace_stale=1,
            )

    def test_episode_two_create_append_select_and_coverage_are_isolated(self) -> None:
        name = "video-assets-episode-two"
        sources = self._seed_video_candidate_sources(name)
        plan = self._episode_plan_variant(sources["video_plan"], 2)
        with patch.object(
            drama_shot_video_candidate_store,
            "load_fresh_episode_shot_video_plan",
            return_value=plan,
        ):
            manifest = drama_shot_video_candidate_store.create_episode_shot_video_candidate_manifest(
                name,
                episode_no=2,
            )
            for index, spec in enumerate(plan.shot_specs):
                manifest, candidate = drama_shot_video_candidate_store.append_local_shot_video_candidate(
                    name,
                    episode_no=2,
                    shot_id=spec.shot_id,
                    mp4_bytes=self._mp4_variant(index),
                    expected_manifest_fingerprint=manifest.manifest_fingerprint,
                )
                self.assertIn("episode_02.shot_videos", candidate.artifact.path)
                pool = next(item for item in manifest.shots if item.shot_id == spec.shot_id)
                manifest = drama_shot_video_candidate_store.select_episode_shot_video_candidate(
                    name,
                    episode_no=2,
                    shot_id=spec.shot_id,
                    selection={
                        "candidate_id": candidate.candidate_id,
                        "candidate_fingerprint": candidate.candidate_fingerprint,
                    },
                    expected_selection_revision=pool.selection_revision,
                    expected_current_selection=None,
                    expected_manifest_fingerprint=manifest.manifest_fingerprint,
                )
            inspection = drama_shot_video_candidate_store.inspect_episode_shot_video_candidates(
                name,
                episode_no=2,
            )
        self.assertEqual(inspection.state, "fresh")
        self.assertEqual(inspection.coverage.status, "ready")
        self.assertTrue(
            drama_shot_video_candidate_store.shot_video_candidate_manifest_path(
                name,
                episode_no=2,
            ).exists()
        )
        self.assertFalse(
            drama_shot_video_candidate_store.shot_video_candidate_manifest_path(
                name,
                episode_no=1,
            ).samefile(
                drama_shot_video_candidate_store.shot_video_candidate_manifest_path(
                    name,
                    episode_no=2,
                )
            )
        )
