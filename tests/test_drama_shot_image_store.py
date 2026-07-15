"""iter111: strict shot image plan persistence, freshness, and CAS."""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from unittest.mock import patch

from src import (
    drama_asset_versions,
    drama_assets,
    drama_shot_image,
    drama_shot_image_store,
    paths,
)
from src.schemas import model_to_dict
from src.web.workspace_ctx import use_workspace
from src.workspace_lock import acquire_write_lock
from tests._drama_shot_image_base import DramaShotImageFixture


class DramaShotImageStoreTests(DramaShotImageFixture):
    def _create(self, name: str, sources: dict):
        return drama_shot_image_store.create_episode_shot_image_plan(
            name,
            shot_character_ids=sources["character_mapping"],
            reference_policy=sources["policy"],
        )

    def test_state_matrix_create_load_and_idempotent_bytes(self) -> None:
        self._make_drama_workspace("states", "霸总")
        self.assertEqual(
            drama_shot_image_store.inspect_episode_shot_image_plan("states").state,
            "blocked_source",
        )
        sources = self._seed_shot_image_sources("store")
        self.assertEqual(
            drama_shot_image_store.inspect_episode_shot_image_plan("store").state,
            "needs_shot_image_plan",
        )
        with patch.object(socket, "socket", side_effect=AssertionError("network")):
            first = self._create("store", sources)
            path = drama_shot_image_store.shot_image_plan_path("store")
            before = path.read_bytes()
            mtime = path.stat().st_mtime_ns
            second = self._create("store", sources)
        self.assertEqual(first, second)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(path.stat().st_mtime_ns, mtime)
        self.assertEqual(
            drama_shot_image_store.inspect_episode_shot_image_plan("store").state,
            "fresh",
        )
        self.assertEqual(
            drama_shot_image_store.load_fresh_episode_shot_image_plan("store"),
            first,
        )

    def test_mapping_change_requires_double_cas_and_increments_revision(self) -> None:
        sources = self._seed_shot_image_sources("mapping")
        first = self._create("mapping", sources)
        changed_mapping = {
            key: list(value) for key, value in sources["character_mapping"].items()
        }
        first_shot_id = next(iter(changed_mapping))
        changed_mapping[first_shot_id] = []
        with self.assertRaisesRegex(ValueError, "explicit confirmation"):
            drama_shot_image_store.create_episode_shot_image_plan(
                "mapping",
                shot_character_ids=changed_mapping,
                reference_policy=sources["policy"],
            )
        with self.assertRaisesRegex(ValueError, "refresh before replacement"):
            drama_shot_image_store.create_episode_shot_image_plan(
                "mapping",
                shot_character_ids=changed_mapping,
                reference_policy=sources["policy"],
                replace_stale=True,
                expected_plan_fingerprint="0" * 64,
            )
        second = drama_shot_image_store.create_episode_shot_image_plan(
            "mapping",
            shot_character_ids=changed_mapping,
            reference_policy=sources["policy"],
            replace_stale=True,
            expected_plan_fingerprint=first.plan_fingerprint,
        )
        self.assertEqual(second.character_binding_revision, 1)
        self.assertEqual(
            drama_shot_image.shot_image_affected_ids(first, second),
            [first_shot_id],
        )
        self.assertEqual(
            drama_shot_image_store.inspect_episode_shot_image_plan("mapping").state,
            "fresh",
        )

    def test_reference_policy_change_is_explicit_and_fingerprinted(self) -> None:
        sources = self._seed_shot_image_sources(
            "policy",
            prop_count=2,
            max_reference_images=4,
        )
        first = self._create("policy", sources)
        policy = drama_shot_image.build_shot_image_reference_policy(
            max_reference_images=2,
        )
        second = drama_shot_image_store.create_episode_shot_image_plan(
            "policy",
            shot_character_ids=sources["character_mapping"],
            reference_policy=policy,
            replace_stale=True,
            expected_plan_fingerprint=first.plan_fingerprint,
        )
        self.assertNotEqual(
            first.reference_policy.policy_fingerprint,
            second.reference_policy.policy_fingerprint,
        )
        self.assertEqual(second.character_binding_revision, 0)
        self.assertTrue(drama_shot_image.shot_image_affected_ids(first, second))

    def test_unselected_or_unused_asset_changes_do_not_stale_plan(self) -> None:
        sources = self._seed_shot_image_sources("unused")
        self._create("unused", sources)
        unused = drama_assets.build_prop_or_clue_asset_version(
            asset_id="p099",
            spec=self._prop_spec(99),
            source_kind="identity_snapshot",
        )
        drama_asset_versions.add_prop_or_clue_asset(
            "unused",
            version=unused,
            expected_catalog_fingerprint=sources["prop_catalog"].catalog_fingerprint,
        )
        self.assertEqual(
            drama_asset_versions.inspect_episode_prop_or_clue_asset_manifest(
                "unused"
            ).state,
            "fresh",
        )
        self.assertEqual(
            drama_shot_image_store.inspect_episode_shot_image_plan("unused").state,
            "fresh",
        )

    def test_unused_frozen_character_selection_does_not_stale_plan(self) -> None:
        sources = self._seed_shot_image_sources("unused-frozen")
        unused_mapping = {
            shot_id: [] for shot_id in sources["character_mapping"]
        }
        first = drama_shot_image_store.create_episode_shot_image_plan(
            "unused-frozen",
            shot_character_ids=unused_mapping,
            reference_policy=sources["policy"],
        )
        asset = sources["character_catalog"].assets[0]
        candidate = drama_assets.build_asset_version(
            asset_id=asset.asset_id,
            identity_fingerprint=asset.identity_fingerprint,
            source_kind="appended_candidate",
            derived_from=asset.selected_version_id,
        )
        appended = drama_asset_versions.append_character_asset_version(
            "unused-frozen",
            character_id=asset.asset_id,
            version=candidate,
            expected_catalog_fingerprint=sources[
                "character_catalog"
            ].catalog_fingerprint,
        )
        drama_asset_versions.select_character_asset_version(
            "unused-frozen",
            character_id=asset.asset_id,
            asset_version_id=candidate.asset_version_id,
            expected_selection_revision=0,
            expected_selected_version_id=asset.selected_version_id,
        )
        self.assertEqual(
            drama_asset_versions.inspect_episode_asset_manifest(
                "unused-frozen"
            ).state,
            "stale",
        )
        inspection = drama_shot_image_store.inspect_episode_shot_image_plan(
            "unused-frozen"
        )
        self.assertEqual(inspection.state, "fresh")
        self.assertEqual(inspection.plan.plan_fingerprint, first.plan_fingerprint)

    def test_used_character_selection_is_blocked_until_manifest_rebuild(self) -> None:
        sources = self._seed_shot_image_sources("used-character-stale")
        first = self._create("used-character-stale", sources)
        asset = sources["character_catalog"].assets[0]
        candidate = drama_assets.build_asset_version(
            asset_id=asset.asset_id,
            identity_fingerprint=asset.identity_fingerprint,
            source_kind="appended_candidate",
            derived_from=asset.selected_version_id,
        )
        appended = drama_asset_versions.append_character_asset_version(
            "used-character-stale",
            character_id=asset.asset_id,
            version=candidate,
            expected_catalog_fingerprint=sources[
                "character_catalog"
            ].catalog_fingerprint,
        )
        drama_asset_versions.select_character_asset_version(
            "used-character-stale",
            character_id=asset.asset_id,
            asset_version_id=candidate.asset_version_id,
            expected_selection_revision=0,
            expected_selected_version_id=asset.selected_version_id,
        )
        self.assertEqual(
            drama_shot_image_store.inspect_episode_shot_image_plan(
                "used-character-stale"
            ).state,
            "blocked_source",
        )
        drama_asset_versions.create_episode_asset_manifest(
            "used-character-stale",
            replace_stale=True,
        )
        inspection = drama_shot_image_store.inspect_episode_shot_image_plan(
            "used-character-stale"
        )
        self.assertEqual(inspection.state, "stale")
        self.assertEqual(
            set(inspection.affected_shot_ids),
            {item.shot_id for item in sources["render_plan"].shots},
        )
        rebuilt = drama_shot_image_store.create_episode_shot_image_plan(
            "used-character-stale",
            shot_character_ids=sources["character_mapping"],
            reference_policy=sources["policy"],
            replace_stale=True,
            expected_plan_fingerprint=first.plan_fingerprint,
        )
        self.assertEqual(rebuilt.character_binding_revision, 0)
        self.assertNotEqual(rebuilt.used_character_fingerprint, first.used_character_fingerprint)

    def test_used_scene_selection_blocks_then_precisely_stales_after_rebuild(self) -> None:
        sources = self._seed_shot_image_sources("scene-stale")
        first = self._create("scene-stale", sources)
        root_version = sources["scene_catalog"].assets[0].versions[0]
        record = self._write_artifact(
            "scene-stale",
            "data/scene_refs/s001/candidate.png",
            "scene-candidate",
        )
        candidate = drama_assets.build_scene_asset_version(
            scene_id="s001",
            spec={**self._scene_spec(), "weather": "雨"},
            source_kind="appended_candidate",
            artifact=record,
            derived_from=root_version.scene_version_id,
        )
        catalog = drama_asset_versions.append_scene_asset_version(
            "scene-stale",
            scene_id="s001",
            version=candidate,
            expected_catalog_fingerprint=sources["scene_catalog"].catalog_fingerprint,
        )
        drama_asset_versions.select_scene_asset_version(
            "scene-stale",
            scene_id="s001",
            scene_version_id=candidate.scene_version_id,
            expected_selection_revision=0,
            expected_selected_version_id=root_version.scene_version_id,
        )
        self.assertEqual(
            drama_shot_image_store.inspect_episode_shot_image_plan(
                "scene-stale"
            ).state,
            "blocked_source",
        )
        scene_mapping = {
            item.shot_id: item.scene_ref.scene_id
            for item in sources["scene_manifest"].shot_scene_refs
        }
        drama_asset_versions.create_episode_scene_asset_manifest(
            "scene-stale",
            shot_scene_ids=scene_mapping,
            replace_stale=True,
            expected_manifest_fingerprint=sources[
                "scene_manifest"
            ].manifest_fingerprint,
        )
        inspection = drama_shot_image_store.inspect_episode_shot_image_plan(
            "scene-stale"
        )
        self.assertEqual(inspection.state, "stale")
        self.assertEqual(
            set(inspection.affected_shot_ids),
            {item.shot_id for item in sources["render_plan"].shots},
        )
        rebuilt = drama_shot_image_store.create_episode_shot_image_plan(
            "scene-stale",
            shot_character_ids=sources["character_mapping"],
            reference_policy=sources["policy"],
            replace_stale=True,
            expected_plan_fingerprint=first.plan_fingerprint,
        )
        self.assertNotEqual(rebuilt.plan_fingerprint, first.plan_fingerprint)
        self.assertEqual(
            drama_shot_image_store.inspect_episode_shot_image_plan(
                "scene-stale"
            ).state,
            "fresh",
        )

    def test_invalid_special_and_oversized_targets_are_preserved(self) -> None:
        sources = self._seed_shot_image_sources("invalid")
        path = drama_shot_image_store.shot_image_plan_path("invalid")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
        self.assertEqual(
            drama_shot_image_store.inspect_episode_shot_image_plan("invalid").state,
            "invalid",
        )
        before = path.read_bytes()
        with self.assertRaisesRegex(ValueError, "repaired explicitly"):
            self._create("invalid", sources)
        self.assertEqual(path.read_bytes(), before)

        sources = self._seed_shot_image_sources("directory")
        directory = drama_shot_image_store.shot_image_plan_path("directory")
        directory.mkdir(parents=True)
        self.assertEqual(
            drama_shot_image_store.inspect_episode_shot_image_plan("directory").state,
            "invalid",
        )
        with self.assertRaisesRegex(ValueError, "repaired explicitly"):
            self._create("directory", sources)

        sources = self._seed_shot_image_sources("oversized")
        oversized = drama_shot_image_store.shot_image_plan_path("oversized")
        oversized.parent.mkdir(parents=True, exist_ok=True)
        oversized.write_bytes(
            b"{" + b" " * (drama_shot_image_store.MAX_SHOT_IMAGE_PLAN_BYTES + 1)
        )
        self.assertEqual(
            drama_shot_image_store.inspect_episode_shot_image_plan("oversized").state,
            "invalid",
        )

    def test_symlink_fifo_deep_and_nonfinite_targets_are_invalid(self) -> None:
        sources = self._seed_shot_image_sources("symlink-target")
        target = drama_shot_image_store.shot_image_plan_path("symlink-target")
        target.parent.mkdir(parents=True, exist_ok=True)
        outside = Path(self._tmp.name) / "outside.json"
        outside.write_text("{}", encoding="utf-8")
        target.symlink_to(outside)
        self.assertEqual(
            drama_shot_image_store.inspect_episode_shot_image_plan(
                "symlink-target"
            ).state,
            "invalid",
        )
        with self.assertRaisesRegex(ValueError, "repaired explicitly"):
            self._create("symlink-target", sources)
        self.assertTrue(target.is_symlink())

        self._seed_shot_image_sources("fifo-target")
        fifo = drama_shot_image_store.shot_image_plan_path("fifo-target")
        fifo.parent.mkdir(parents=True, exist_ok=True)
        os.mkfifo(fifo)
        self.assertEqual(
            drama_shot_image_store.inspect_episode_shot_image_plan(
                "fifo-target"
            ).state,
            "invalid",
        )

        for name, payload in (
            ("deep-target", "[" * 1100 + "]" * 1100),
            ("nan-target", '{"value":NaN}'),
            ("infinity-target", '{"value":Infinity}'),
        ):
            self._seed_shot_image_sources(name)
            path = drama_shot_image_store.shot_image_plan_path(name)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(payload, encoding="utf-8")
            self.assertEqual(
                drama_shot_image_store.inspect_episode_shot_image_plan(name).state,
                "invalid",
            )

    def test_parent_symlink_and_workspace_lock_fail_closed(self) -> None:
        sources = self._seed_shot_image_sources("parent-symlink")
        root = paths.workspace_root("parent-symlink")
        outside = Path(self._tmp.name) / "outside-parent"
        outside.mkdir()
        linked = root / "linked-output"
        linked.symlink_to(outside, target_is_directory=True)
        escaped_target = linked / "episode_01.shot_image_plan.json"
        with patch.object(
            drama_shot_image_store,
            "shot_image_plan_path",
            return_value=escaped_target,
        ):
            self.assertEqual(
                drama_shot_image_store.inspect_episode_shot_image_plan(
                    "parent-symlink"
                ).state,
                "invalid",
            )
            with self.assertRaisesRegex(ValueError, "repaired explicitly"):
                self._create("parent-symlink", sources)
        self.assertFalse((outside / escaped_target.name).exists())

        sources = self._seed_shot_image_sources("lock-contention")
        with use_workspace("lock-contention"), acquire_write_lock(source="holder"):
            with self.assertRaisesRegex(ValueError, "creation was rejected"):
                self._create("lock-contention", sources)
        self.assertFalse(
            drama_shot_image_store.shot_image_plan_path("lock-contention").exists()
        )

    def test_preexisting_temp_entry_is_never_deleted(self) -> None:
        sources = self._seed_shot_image_sources("temp-owner")
        target = drama_shot_image_store.shot_image_plan_path("temp-owner")
        target.parent.mkdir(parents=True, exist_ok=True)
        token = "a" * 32
        preexisting = target.with_name(f".{target.name}.tmp.{token}")
        preexisting.write_text("attacker-owned", encoding="utf-8")
        with patch(
            "src.drama_shot_image_store.secrets.token_hex",
            return_value=token,
        ):
            with self.assertRaisesRegex(ValueError, "written safely"):
                self._create("temp-owner", sources)
        self.assertEqual(preexisting.read_text(encoding="utf-8"), "attacker-owned")
        self.assertFalse(target.exists())

    def test_replaced_temp_entry_is_never_deleted_by_cleanup(self) -> None:
        sources = self._seed_shot_image_sources("temp-race-owner")
        target = drama_shot_image_store.shot_image_plan_path("temp-race-owner")
        target.parent.mkdir(parents=True, exist_ok=True)
        token = "b" * 32
        temp = target.with_name(f".{target.name}.tmp.{token}")
        real_validate = drama_shot_image_store._validate_plan_artifacts
        calls = 0

        def replace_temp_on_precommit(workspace, plan):
            nonlocal calls
            calls += 1
            real_validate(workspace, plan)
            if calls == 2:
                temp.unlink()
                temp.write_text("replacement-owned", encoding="utf-8")

        with patch(
            "src.drama_shot_image_store.secrets.token_hex",
            return_value=token,
        ), patch(
            "src.drama_shot_image_store._validate_plan_artifacts",
            side_effect=replace_temp_on_precommit,
        ):
            with self.assertRaisesRegex(ValueError, "temporary file changed"):
                self._create("temp-race-owner", sources)
        self.assertEqual(temp.read_text(encoding="utf-8"), "replacement-owned")
        self.assertFalse(target.exists())

    def test_target_and_source_precommit_races_leave_no_partial_plan(self) -> None:
        sources = self._seed_shot_image_sources("target-race")
        with patch(
            "src.drama_shot_image_store._target_token_at",
            side_effect=[("missing",), ("file", 1, "changed")],
        ):
            with self.assertRaisesRegex(ValueError, "changed concurrently"):
                self._create("target-race", sources)
        self.assertFalse(
            drama_shot_image_store.shot_image_plan_path("target-race").exists()
        )

        sources = self._seed_shot_image_sources("source-race")
        real_build = drama_shot_image_store._build_from_sources
        calls = 0

        def changing_build(source_snapshot, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                return real_build(source_snapshot, **kwargs)
            changed_policy = drama_shot_image.build_shot_image_reference_policy(
                max_reference_images=1,
            )
            return real_build(
                source_snapshot,
                **{**kwargs, "reference_policy": changed_policy},
            )

        with patch(
            "src.drama_shot_image_store._build_from_sources",
            side_effect=changing_build,
        ):
            with self.assertRaisesRegex(ValueError, "sources changed concurrently"):
                self._create("source-race", sources)
        self.assertFalse(
            drama_shot_image_store.shot_image_plan_path("source-race").exists()
        )

        sources = self._seed_shot_image_sources("artifact-race")
        with patch(
            "src.drama_shot_image_store._validate_plan_artifacts",
            side_effect=[None, drama_shot_image_store.DramaShotImageStoreError(
                "shot image artifact bytes changed"
            )],
        ):
            with self.assertRaisesRegex(ValueError, "artifact bytes changed"):
                self._create("artifact-race", sources)
        self.assertFalse(
            drama_shot_image_store.shot_image_plan_path("artifact-race").exists()
        )

    def test_public_errors_are_redacted(self) -> None:
        sources = self._seed_shot_image_sources("redacted")
        secret = "SECRET_SHOT_IMAGE_111"
        bad_mapping = dict(sources["character_mapping"])
        bad_mapping[secret] = []
        with self.assertRaises(drama_shot_image_store.DramaShotImageStoreError) as caught:
            drama_shot_image_store.create_episode_shot_image_plan(
                "redacted",
                shot_character_ids=bad_mapping,
                reference_policy=sources["policy"],
            )
        rendered = f"{caught.exception!s} {caught.exception!r}"
        self.assertNotIn(secret, rendered)
        self.assertNotIn(str(paths.workspace_root("redacted")), rendered)
        inspection = drama_shot_image_store.inspect_episode_shot_image_plan(
            f"../{secret}"
        )
        self.assertEqual(inspection.state, "invalid")
        self.assertNotIn(secret, " ".join(inspection.reasons))
        with self.assertRaises(drama_shot_image_store.DramaShotImageStoreError) as load:
            drama_shot_image_store.load_fresh_episode_shot_image_plan(
                f"../{secret}"
            )
        self.assertNotIn(secret, str(load.exception))


if __name__ == "__main__":
    import unittest

    unittest.main()
