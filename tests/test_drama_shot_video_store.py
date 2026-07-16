"""iter115: strict shot-video plan persistence, freshness, and CAS."""

from __future__ import annotations

import json
import os
import socket
from unittest.mock import patch

from src import (
    drama_shot_image_candidate_store,
    drama_shot_video_store,
    paths,
)
from src.schemas import model_to_dict
from src.web.workspace_ctx import use_workspace
from src.workspace_lock import acquire_write_lock
from tests._drama_shot_video_base import DramaShotVideoFixture


class DramaShotVideoStoreTests(DramaShotVideoFixture):
    def test_state_matrix_create_load_and_idempotent_bytes(self) -> None:
        self._make_drama_workspace("video-blocked", "霸总")
        self.assertEqual(
            drama_shot_video_store.inspect_episode_shot_video_plan(
                "video-blocked"
            ).state,
            "blocked_source",
        )
        self._seed_shot_video_sources("video-store")
        self.assertEqual(
            drama_shot_video_store.inspect_episode_shot_video_plan(
                "video-store"
            ).state,
            "needs_shot_video_plan",
        )
        with patch.object(socket, "socket", side_effect=AssertionError("network")):
            first = drama_shot_video_store.create_episode_shot_video_plan(
                "video-store"
            )
            path = drama_shot_video_store.shot_video_plan_path("video-store")
            before = path.read_bytes()
            mtime = path.stat().st_mtime_ns
            second = drama_shot_video_store.create_episode_shot_video_plan(
                "video-store"
            )
        self.assertEqual(first, second)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(path.stat().st_mtime_ns, mtime)
        self.assertEqual(
            drama_shot_video_store.inspect_episode_shot_video_plan(
                "video-store"
            ).state,
            "fresh",
        )
        self.assertEqual(
            drama_shot_video_store.load_fresh_episode_shot_video_plan(
                "video-store"
            ),
            first,
        )

    def test_incomplete_image_coverage_blocks_creation(self) -> None:
        self._seed_candidate_sources("video-store-incomplete")
        self._create_manifest("video-store-incomplete")
        self.assertEqual(
            drama_shot_video_store.inspect_episode_shot_video_plan(
                "video-store-incomplete"
            ).state,
            "blocked_source",
        )
        with self.assertRaisesRegex(ValueError, "creation was rejected"):
            drama_shot_video_store.create_episode_shot_video_plan(
                "video-store-incomplete"
            )

    def test_selection_change_requires_explicit_double_cas(self) -> None:
        sources = self._seed_shot_video_sources("video-store-cas")
        first = drama_shot_video_store.create_episode_shot_video_plan(
            "video-store-cas"
        )
        shot_id = sources["shot_image_plan"].shot_specs[0].shot_id
        manifest, candidate = self._append_candidate(
            "video-store-cas",
            sources["candidate_manifest"],
            shot_id,
            rgba=b"\x99\x88\x77\xff",
        )
        pool = next(item for item in manifest.shots if item.shot_id == shot_id)
        manifest = drama_shot_image_candidate_store.select_episode_shot_image_frame(
            "video-store-cas",
            shot_id=shot_id,
            frame="first",
            binding={
                "kind": "direct",
                "candidate_id": candidate.candidate_id,
                "candidate_fingerprint": candidate.candidate_fingerprint,
            },
            expected_selection_revision=pool.selection_revision,
            expected_current_binding=model_to_dict(pool.first_binding),
            expected_manifest_fingerprint=manifest.manifest_fingerprint,
        )
        inspection = drama_shot_video_store.inspect_episode_shot_video_plan(
            "video-store-cas"
        )
        self.assertEqual(inspection.state, "stale")
        self.assertEqual(inspection.affected_shot_ids, (shot_id,))
        with self.assertRaisesRegex(ValueError, "explicit confirmation"):
            drama_shot_video_store.create_episode_shot_video_plan(
                "video-store-cas"
            )
        with self.assertRaisesRegex(ValueError, "refresh before replacement"):
            drama_shot_video_store.create_episode_shot_video_plan(
                "video-store-cas",
                replace_stale=True,
                expected_plan_fingerprint="0" * 64,
            )
        replaced = drama_shot_video_store.create_episode_shot_video_plan(
            "video-store-cas",
            replace_stale=True,
            expected_plan_fingerprint=first.plan_fingerprint,
        )
        self.assertNotEqual(replaced.plan_fingerprint, first.plan_fingerprint)
        self.assertEqual(
            drama_shot_video_store.inspect_episode_shot_video_plan(
                "video-store-cas"
            ).state,
            "fresh",
        )

    def test_unselected_candidate_append_does_not_stale_persisted_plan(self) -> None:
        sources = self._seed_shot_video_sources("video-store-unselected")
        first = drama_shot_video_store.create_episode_shot_video_plan(
            "video-store-unselected"
        )
        path = drama_shot_video_store.shot_video_plan_path(
            "video-store-unselected"
        )
        before = path.read_bytes()
        shot_id = sources["shot_image_plan"].shot_specs[0].shot_id
        self._append_candidate(
            "video-store-unselected",
            sources["candidate_manifest"],
            shot_id,
            rgba=b"\x01\x02\x03\xff",
        )
        inspection = drama_shot_video_store.inspect_episode_shot_video_plan(
            "video-store-unselected"
        )
        self.assertEqual(inspection.state, "fresh")
        self.assertEqual(inspection.plan.plan_fingerprint, first.plan_fingerprint)
        self.assertEqual(path.read_bytes(), before)

    def test_missing_selected_artifact_blocks_without_overwriting_old_plan(self) -> None:
        sources = self._seed_shot_video_sources("video-store-missing-frame")
        plan = drama_shot_video_store.create_episode_shot_video_plan(
            "video-store-missing-frame"
        )
        plan_path = drama_shot_video_store.shot_video_plan_path(
            "video-store-missing-frame"
        )
        before = plan_path.read_bytes()
        selected = sources["candidates"][sources["shot_image_plan"].shot_specs[0].shot_id]
        (paths.workspace_root("video-store-missing-frame") / selected.artifact.path).unlink()
        inspection = drama_shot_video_store.inspect_episode_shot_video_plan(
            "video-store-missing-frame"
        )
        self.assertEqual(inspection.state, "blocked_source")
        with self.assertRaisesRegex(ValueError, "creation was rejected"):
            drama_shot_video_store.create_episode_shot_video_plan(
                "video-store-missing-frame",
                replace_stale=True,
                expected_plan_fingerprint=plan.plan_fingerprint,
            )
        self.assertEqual(plan_path.read_bytes(), before)

    def test_invalid_json_symlink_and_bool_replacement_fail_closed(self) -> None:
        self._seed_shot_video_sources("video-store-invalid")
        plan = drama_shot_video_store.create_episode_shot_video_plan(
            "video-store-invalid"
        )
        path = drama_shot_video_store.shot_video_plan_path("video-store-invalid")
        path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
        self.assertEqual(
            drama_shot_video_store.inspect_episode_shot_video_plan(
                "video-store-invalid"
            ).state,
            "invalid",
        )
        with self.assertRaisesRegex(ValueError, "repaired explicitly"):
            drama_shot_video_store.create_episode_shot_video_plan(
                "video-store-invalid",
                replace_stale=True,
                expected_plan_fingerprint=plan.plan_fingerprint,
            )

        self._seed_shot_video_sources("video-store-symlink")
        target = drama_shot_video_store.shot_video_plan_path("video-store-symlink")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to("missing.json")
        self.assertEqual(
            drama_shot_video_store.inspect_episode_shot_video_plan(
                "video-store-symlink"
            ).state,
            "invalid",
        )
        with self.assertRaises(ValueError):
            drama_shot_video_store.create_episode_shot_video_plan(
                "video-store-symlink",
                replace_stale=True,
            )
        with self.assertRaisesRegex(ValueError, "repaired explicitly"):
            drama_shot_video_store.create_episode_shot_video_plan(
                "video-store-symlink",
                replace_stale=True,
                expected_plan_fingerprint=None,
            )

        self._seed_shot_video_sources("video-store-bool")
        with self.assertRaisesRegex(ValueError, "creation was rejected"):
            drama_shot_video_store.create_episode_shot_video_plan(
                "video-store-bool",
                replace_stale=1,
            )

    def test_workspace_lock_and_precommit_source_change_are_rejected(self) -> None:
        self._seed_shot_video_sources("video-store-lock")
        with use_workspace("video-store-lock"), acquire_write_lock(source="test"):
            with self.assertRaisesRegex(ValueError, "creation was rejected"):
                drama_shot_video_store.create_episode_shot_video_plan(
                    "video-store-lock"
                )

        sources = self._seed_shot_video_sources("video-store-race")
        desired = self._build_video_plan(sources)
        changed = desired.model_copy(update={"plan_fingerprint": "f" * 64})
        with patch.object(
            drama_shot_video_store,
            "_build_from_sources",
            side_effect=[desired, changed],
        ):
            with self.assertRaisesRegex(ValueError, "sources changed concurrently"):
                drama_shot_video_store.create_episode_shot_video_plan(
                    "video-store-race"
                )
        self.assertFalse(
            drama_shot_video_store.shot_video_plan_path(
                "video-store-race"
            ).exists()
        )

    def test_target_token_race_and_special_files_fail_closed(self) -> None:
        self._seed_shot_video_sources("video-store-target-race")
        real_token = drama_shot_video_store._target_token_at
        calls = 0

        def raced_token(directory_fd, name):
            nonlocal calls
            calls += 1
            if calls == 2:
                return ("invalid",)
            return real_token(directory_fd, name)

        with patch.object(
            drama_shot_video_store,
            "_target_token_at",
            side_effect=raced_token,
        ):
            with self.assertRaisesRegex(ValueError, "changed concurrently"):
                drama_shot_video_store.create_episode_shot_video_plan(
                    "video-store-target-race"
                )
        self.assertFalse(
            drama_shot_video_store.shot_video_plan_path(
                "video-store-target-race"
            ).exists()
        )

        for suffix, create_special in (
            ("directory", lambda path: path.mkdir()),
            ("fifo", lambda path: os.mkfifo(path)),
        ):
            name = f"video-store-{suffix}"
            self._seed_shot_video_sources(name)
            path = drama_shot_video_store.shot_video_plan_path(name)
            path.parent.mkdir(parents=True, exist_ok=True)
            create_special(path)
            self.assertEqual(
                drama_shot_video_store.inspect_episode_shot_video_plan(name).state,
                "invalid",
            )
            with self.assertRaisesRegex(ValueError, "repaired explicitly"):
                drama_shot_video_store.create_episode_shot_video_plan(name)

    def test_idempotent_early_return_rechecks_target_token(self) -> None:
        self._seed_shot_video_sources("video-store-idempotent-race")
        drama_shot_video_store.create_episode_shot_video_plan(
            "video-store-idempotent-race"
        )
        real_token = drama_shot_video_store._target_token
        calls = 0

        def raced_token(root, path):
            nonlocal calls
            calls += 1
            if calls == 2:
                return ("invalid",)
            return real_token(root, path)

        with patch.object(
            drama_shot_video_store,
            "_target_token",
            side_effect=raced_token,
        ):
            with self.assertRaisesRegex(ValueError, "changed concurrently"):
                drama_shot_video_store.create_episode_shot_video_plan(
                    "video-store-idempotent-race"
                )

    def test_oversize_and_deep_json_are_invalid(self) -> None:
        self._seed_shot_video_sources("video-store-oversize")
        path = drama_shot_video_store.shot_video_plan_path("video-store-oversize")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * (drama_shot_video_store.MAX_SHOT_VIDEO_PLAN_BYTES + 1))
        self.assertEqual(
            drama_shot_video_store.inspect_episode_shot_video_plan(
                "video-store-oversize"
            ).state,
            "invalid",
        )

        self._seed_shot_video_sources("video-store-deep")
        deep_path = drama_shot_video_store.shot_video_plan_path("video-store-deep")
        deep_path.parent.mkdir(parents=True, exist_ok=True)
        deep_path.write_text("[" * 300 + "]" * 300, encoding="utf-8")
        self.assertEqual(
            drama_shot_video_store.inspect_episode_shot_video_plan(
                "video-store-deep"
            ).state,
            "invalid",
        )

    def test_short_write_cleans_owned_temp_and_episode_path_is_generic(self) -> None:
        self._seed_shot_video_sources("video-store-write")
        real_write = os.write
        def short_write(fd, data):
            if b"drama_episode_shot_video_plan" in bytes(data):
                return 0
            return real_write(fd, data)

        with patch("src.drama_shot_video_store.os.write", side_effect=short_write):
            with self.assertRaisesRegex(ValueError, "written safely"):
                drama_shot_video_store.create_episode_shot_video_plan(
                    "video-store-write"
                )
        parent = drama_shot_video_store.shot_video_plan_path(
            "video-store-write"
        ).parent
        self.assertEqual(list(parent.glob(".episode_01.shot_video_plan.json.tmp.*")), [])
        self.assertEqual(
            drama_shot_video_store.shot_video_plan_path(
                "video-store-write",
                episode_no=2,
            ).name,
            "episode_02.shot_video_plan.json",
        )
