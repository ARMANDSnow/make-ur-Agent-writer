"""iter127: cross-episode asset usage and retirement governance tests."""

from __future__ import annotations

import copy
import json
import socket
from unittest.mock import patch

from pydantic import ValidationError

from src import (
    character_designer,
    drama_art_direction_store,
    drama_asset_usage,
    drama_asset_versions,
    drama_assets,
    drama_render_store,
    drama_reviewer,
    drama_store,
    paths,
    storyboard_builder,
)
from src.drama_schemas import (
    AssetRetirementState,
    SeasonAssetUsageIndex,
    _canonical_sha256,
    character_paths,
    episode_paths,
)
from src.schemas import model_to_dict
from src.utils import write_json
from tests._drama_base import DramaTestBase


class DramaAssetUsageTests(DramaTestBase):
    @staticmethod
    def _art_spec(preset: str = "cinematic") -> dict:
        return {
            "preset": preset,
            "positive_tokens": ["ink wash"],
            "negative_tokens": ["watermark"],
            "palette": ["#112233"],
            "aspect_ratio": "9:16",
        }

    @staticmethod
    def _scene_version(
        scene_id: str,
        name: str,
        *,
        derived_from: str | None = None,
    ):
        return drama_assets.build_scene_asset_version(
            scene_id=scene_id,
            spec={
                "display_name": name,
                "location": f"{name}位置",
                "time_of_day": "夜",
                "weather": "晴",
                "spatial_anchors": ["入口"],
                "visual_tokens": ["冷色"],
            },
            source_kind=(
                "identity_snapshot"
                if derived_from is None
                else "appended_candidate"
            ),
            derived_from=derived_from,
        )

    @staticmethod
    def _prop_version(
        name: str,
        *,
        state_label: str = "完好",
        derived_from: str | None = None,
    ):
        return drama_assets.build_prop_or_clue_asset_version(
            asset_id="p001",
            spec={
                "kind": "prop",
                "display_name": name,
                "owner_character_id": "c001",
                "state_label": state_label,
                "first_seen_episode_no": 1,
                "visual_tokens": ["特写"],
            },
            source_kind=(
                "identity_snapshot"
                if derived_from is None
                else "appended_candidate"
            ),
            derived_from=derived_from,
        )

    def _ready(self, name: str = "asset-usage") -> dict:
        self._make_drama_workspace(name, "霸总", episode_count=2)
        self._write_setup(name, hook=True)
        write_json(
            episode_paths(name).storyboard_path,
            storyboard_builder.run(name, mock=True),
        )
        write_json(
            character_paths(name).sheet_path,
            character_designer.run(name, mock=True),
        )
        write_json(
            episode_paths(name).review_path,
            drama_reviewer.run(name, mock=True),
        )
        drama_store.assemble_episode(name)
        art_catalog = drama_art_direction_store.create_art_direction_catalog(
            name,
            art_direction_id="season_default",
            spec=self._art_spec(),
            source_kind="preset",
        )
        plan = drama_render_store.create_render_plan(name)
        character_catalog = (
            drama_asset_versions.create_character_asset_catalog(name)
        )
        character_manifest = (
            drama_asset_versions.create_episode_asset_manifest(name)
        )
        scene_version = self._scene_version("s001", "天台")
        scene_catalog = drama_asset_versions.create_scene_asset_catalog(
            name,
            version=scene_version,
        )
        scene_manifest = (
            drama_asset_versions.create_episode_scene_asset_manifest(
                name,
                shot_scene_ids={
                    shot.shot_id: "s001" for shot in plan.shots
                },
            )
        )
        prop_catalog = (
            drama_asset_versions.create_prop_or_clue_asset_catalog(name)
        )
        prop_version = self._prop_version("旧怀表")
        prop_catalog = drama_asset_versions.add_prop_or_clue_asset(
            name,
            version=prop_version,
            expected_catalog_fingerprint=prop_catalog.catalog_fingerprint,
        )
        prop_mapping = {shot.shot_id: [] for shot in plan.shots}
        prop_mapping[plan.shots[0].shot_id] = ["p001"]
        prop_manifest = (
            drama_asset_versions.create_episode_prop_or_clue_asset_manifest(
                name,
                shot_asset_ids=prop_mapping,
            )
        )
        return {
            "plan": plan,
            "art_catalog": art_catalog,
            "character_catalog": character_catalog,
            "character_manifest": character_manifest,
            "scene_catalog": scene_catalog,
            "scene_version": scene_version,
            "scene_manifest": scene_manifest,
            "prop_catalog": prop_catalog,
            "prop_version": prop_version,
            "prop_manifest": prop_manifest,
        }

    def _clone_episode_two_sources(self, name: str, ready: dict) -> None:
        plan_payload = ready["plan"].model_dump()
        plan_payload["episode_no"] = 2
        plan_payload["plan_fingerprint"] = _canonical_sha256(
            {
                key: value
                for key, value in plan_payload.items()
                if key != "plan_fingerprint"
            }
        )
        plan = type(ready["plan"])(**plan_payload)
        write_json(
            drama_render_store.render_plan_path(name, episode_no=2),
            {
                "schema_version": 1,
                "artifact_type": "drama_render_plan",
                "plan_fingerprint": plan.plan_fingerprint,
                "plan": model_to_dict(plan),
            },
        )
        manifest_specs = [
            (
                ready["character_manifest"],
                drama_asset_versions.episode_asset_manifest_path(
                    name,
                    episode_no=2,
                ),
                "drama_episode_asset_manifest",
            ),
            (
                ready["scene_manifest"],
                drama_asset_versions.episode_scene_asset_manifest_path(
                    name,
                    episode_no=2,
                ),
                "drama_episode_scene_asset_manifest",
            ),
            (
                ready["prop_manifest"],
                drama_asset_versions.episode_prop_or_clue_asset_manifest_path(
                    name,
                    episode_no=2,
                ),
                "drama_episode_prop_clue_asset_manifest",
            ),
        ]
        for original, path, artifact_type in manifest_specs:
            payload = original.model_dump()
            payload["episode_no"] = 2
            payload["render_plan_fingerprint"] = plan.plan_fingerprint
            payload["manifest_fingerprint"] = _canonical_sha256(
                {
                    key: value
                    for key, value in payload.items()
                    if key != "manifest_fingerprint"
                }
            )
            manifest = type(original)(**payload)
            write_json(
                path,
                {
                    "schema_version": 1,
                    "artifact_type": artifact_type,
                    "manifest_fingerprint": manifest.manifest_fingerprint,
                    "manifest": model_to_dict(manifest),
                },
            )

    def _append_candidates(self, name: str, ready: dict) -> dict:
        character_asset = ready["character_catalog"].assets[0]
        character_candidate = drama_assets.build_asset_version(
            asset_id=character_asset.asset_id,
            identity_fingerprint=character_asset.identity_fingerprint,
            source_kind="appended_candidate",
            derived_from=character_asset.selected_version_id,
        )
        character_catalog = (
            drama_asset_versions.append_character_asset_version(
                name,
                character_id=character_asset.asset_id,
                version=character_candidate,
                expected_catalog_fingerprint=ready[
                    "character_catalog"
                ].catalog_fingerprint,
            )
        )
        art_catalog = (
            drama_art_direction_store.append_art_direction_candidate(
                name,
                spec=self._art_spec("graphic-novel"),
                source_kind="manual",
                derived_from=ready["art_catalog"].selected_version_id,
                expected_catalog_fingerprint=ready[
                    "art_catalog"
                ].catalog_fingerprint,
            )
        )
        scene_candidate = self._scene_version(
            "s001",
            "暴雨天台",
            derived_from=ready["scene_version"].scene_version_id,
        )
        scene_catalog = drama_asset_versions.append_scene_asset_version(
            name,
            scene_id="s001",
            version=scene_candidate,
            expected_catalog_fingerprint=ready[
                "scene_catalog"
            ].catalog_fingerprint,
        )
        prop_candidate = self._prop_version(
            "旧怀表",
            state_label="停走",
            derived_from=ready["prop_version"].asset_version_id,
        )
        prop_catalog = (
            drama_asset_versions.append_prop_or_clue_asset_version(
                name,
                asset_id="p001",
                version=prop_candidate,
                expected_catalog_fingerprint=ready[
                    "prop_catalog"
                ].catalog_fingerprint,
            )
        )
        return {
            "character_asset": character_asset,
            "character_candidate": character_candidate,
            "character_catalog": character_catalog,
            "art_candidate": art_catalog.versions[-1],
            "art_catalog": art_catalog,
            "scene_candidate": scene_candidate,
            "scene_catalog": scene_catalog,
            "prop_candidate": prop_candidate,
            "prop_catalog": prop_catalog,
        }

    def test_cross_episode_index_covers_all_kinds_and_zero_use(self) -> None:
        ready = self._ready("usage-index")
        candidates = self._append_candidates("usage-index", ready)
        self._clone_episode_two_sources("usage-index", ready)
        with patch.object(
            socket,
            "socket",
            side_effect=AssertionError("network"),
        ):
            first = drama_asset_usage.build_season_asset_usage_index(
                "usage-index"
            )
            second = drama_asset_usage.build_season_asset_usage_index(
                "usage-index"
            )
        self.assertEqual(first, second)
        self.assertEqual(first.scanned_episode_nos, [1, 2])
        self.assertEqual(first.blockers, [])
        by_key = {
            (item.kind, item.asset_id, item.version_id): item
            for item in first.entries
        }
        character = candidates["character_asset"]
        current_character = by_key[
            (
                "character",
                character.asset_id,
                character.selected_version_id,
            )
        ]
        self.assertEqual(
            [item.episode_no for item in current_character.references],
            [1, 2],
        )
        self.assertTrue(
            all(not item.shot_ids for item in current_character.references)
        )
        art = by_key[
            (
                "art_direction",
                ready["art_catalog"].art_direction_id,
                ready["art_catalog"].selected_version_id,
            )
        ]
        self.assertTrue(all(item.shot_ids for item in art.references))
        scene = by_key[
            ("scene", "s001", ready["scene_version"].scene_version_id)
        ]
        self.assertEqual(
            {item.episode_no for item in scene.references},
            {1, 2},
        )
        prop = by_key[
            ("prop", "p001", ready["prop_version"].asset_version_id)
        ]
        self.assertEqual(
            {item.episode_no for item in prop.references},
            {1, 2},
        )
        for key in (
            (
                "character",
                character.asset_id,
                candidates["character_candidate"].asset_version_id,
            ),
            (
                "art_direction",
                ready["art_catalog"].art_direction_id,
                candidates["art_candidate"].version_id,
            ),
            (
                "scene",
                "s001",
                candidates["scene_candidate"].scene_version_id,
            ),
            (
                "prop",
                "p001",
                candidates["prop_candidate"].asset_version_id,
            ),
        ):
            self.assertEqual(by_key[key].references, [])

    def test_rehashed_index_tamper_is_rejected(self) -> None:
        self._ready("usage-tamper")
        index = drama_asset_usage.build_season_asset_usage_index(
            "usage-tamper"
        )
        payload = index.model_dump()
        payload["scanned_episode_nos"] = [2, 1]
        payload["index_fingerprint"] = _canonical_sha256(
            {
                key: value
                for key, value in payload.items()
                if key != "index_fingerprint"
            }
        )
        with self.assertRaises(ValidationError):
            SeasonAssetUsageIndex(**payload)

    def test_invalid_manifest_blocks_retirement_without_state_write(self) -> None:
        ready = self._ready("usage-blocked")
        candidates = self._append_candidates("usage-blocked", ready)
        path = drama_asset_versions.episode_scene_asset_manifest_path(
            "usage-blocked"
        )
        path.write_text("{broken", encoding="utf-8")
        index = drama_asset_usage.build_season_asset_usage_index(
            "usage-blocked"
        )
        self.assertTrue(index.blockers)
        decision = drama_asset_usage.build_asset_retirement_decision(
            "usage-blocked",
            kind="character",
            asset_id=candidates["character_asset"].asset_id,
            version_id=candidates[
                "character_candidate"
            ].asset_version_id,
            usage_index=index,
        )
        self.assertFalse(decision.can_disable)
        self.assertFalse(decision.can_physically_delete)
        with self.assertRaisesRegex(
            drama_asset_usage.DramaAssetUsageError,
            "index is incomplete",
        ):
            drama_asset_usage.set_asset_version_status(
                "usage-blocked",
                kind="character",
                asset_id=candidates["character_asset"].asset_id,
                version_id=candidates[
                    "character_candidate"
                ].asset_version_id,
                status="disabled",
                expected_revision=0,
                expected_current_status="active",
            )
        self.assertFalse(
            drama_asset_usage.asset_retirement_state_path(
                "usage-blocked"
            ).exists()
        )

    def test_symlink_source_is_a_blocker_not_zero_usage(self) -> None:
        self._ready("usage-symlink")
        path = drama_asset_versions.episode_asset_manifest_path(
            "usage-symlink"
        )
        external = path.with_name("external.json")
        external.write_bytes(path.read_bytes())
        path.unlink()
        path.symlink_to(external)
        index = drama_asset_usage.build_season_asset_usage_index(
            "usage-symlink"
        )
        self.assertIn(
            ("character_manifest", "source_invalid"),
            {(item.source, item.code) for item in index.blockers},
        )

    def test_wrong_embedded_episode_identity_is_a_blocker(self) -> None:
        ready = self._ready("usage-wrong-episode")
        payload = ready["plan"].model_dump()
        payload["episode_no"] = 2
        payload["plan_fingerprint"] = _canonical_sha256(
            {
                key: value
                for key, value in payload.items()
                if key != "plan_fingerprint"
            }
        )
        forged = type(ready["plan"])(**payload)
        write_json(
            drama_render_store.render_plan_path("usage-wrong-episode"),
            {
                "schema_version": 1,
                "artifact_type": "drama_render_plan",
                "plan_fingerprint": forged.plan_fingerprint,
                "plan": model_to_dict(forged),
            },
        )
        index = drama_asset_usage.build_season_asset_usage_index(
            "usage-wrong-episode"
        )
        self.assertIn(
            ("render_plan", 1, "episode_identity_mismatch"),
            {
                (item.source, item.episode_no, item.code)
                for item in index.blockers
            },
        )

    def test_missing_episode_source_is_a_blocker_not_zero_usage(self) -> None:
        self._ready("usage-missing-source")
        drama_asset_versions.episode_asset_manifest_path(
            "usage-missing-source"
        ).unlink()
        index = drama_asset_usage.build_season_asset_usage_index(
            "usage-missing-source"
        )
        self.assertIn(
            ("character_manifest", 1, "source_missing"),
            {
                (item.source, item.episode_no, item.code)
                for item in index.blockers
            },
        )

    def test_intermediate_episode_directory_symlink_is_a_blocker(self) -> None:
        self._ready("usage-directory-symlink")
        root = paths.workspace_root("usage-directory-symlink")
        outputs = root / "outputs"
        original = root / "outputs-original"
        outputs.rename(original)
        external = root / "external-empty"
        (external / "episodes").mkdir(parents=True)
        outputs.symlink_to(external, target_is_directory=True)
        index = drama_asset_usage.build_season_asset_usage_index(
            "usage-directory-symlink"
        )
        self.assertIn(
            ("episode_scan", "source_changed"),
            {(item.source, item.code) for item in index.blockers},
        )

    def test_disable_preserves_frozen_refs_and_blocks_reselection(self) -> None:
        ready = self._ready("usage-preserve")
        candidates = self._append_candidates("usage-preserve", ready)
        asset = candidates["character_asset"]
        original_id = asset.selected_version_id
        manifest_path = drama_asset_versions.episode_asset_manifest_path(
            "usage-preserve"
        )
        manifest_bytes = manifest_path.read_bytes()
        decision = drama_asset_usage.build_asset_retirement_decision(
            "usage-preserve",
            kind="character",
            asset_id=asset.asset_id,
            version_id=original_id,
        )
        self.assertTrue(decision.references)
        self.assertTrue(decision.can_disable)
        self.assertFalse(decision.can_physically_delete)
        state = drama_asset_usage.set_asset_version_status(
            "usage-preserve",
            kind="character",
            asset_id=asset.asset_id,
            version_id=original_id,
            status="disabled",
            expected_revision=0,
            expected_current_status="active",
        )
        self.assertEqual(state.revision, 1)
        self.assertEqual(manifest_path.read_bytes(), manifest_bytes)
        self.assertEqual(
            drama_asset_versions.select_character_asset_version(
                "usage-preserve",
                character_id=asset.asset_id,
                asset_version_id=original_id,
                expected_selection_revision=0,
                expected_selected_version_id=original_id,
            ),
            candidates["character_catalog"],
        )
        selected = drama_asset_versions.select_character_asset_version(
            "usage-preserve",
            character_id=asset.asset_id,
            asset_version_id=candidates[
                "character_candidate"
            ].asset_version_id,
            expected_selection_revision=0,
            expected_selected_version_id=original_id,
        )
        with self.assertRaisesRegex(ValueError, "disabled"):
            drama_asset_versions.select_character_asset_version(
                "usage-preserve",
                character_id=asset.asset_id,
                asset_version_id=original_id,
                expected_selection_revision=1,
                expected_selected_version_id=selected.assets[0].selected_version_id,
            )
        self.assertEqual(manifest_path.read_bytes(), manifest_bytes)

    def test_all_four_selection_entry_points_honor_disable_and_restore(self) -> None:
        ready = self._ready("usage-guards")
        values = self._append_candidates("usage-guards", ready)
        revision = 0

        def cycle(kind: str, asset_id: str, version_id: str, select) -> None:
            nonlocal revision
            drama_asset_usage.set_asset_version_status(
                "usage-guards",
                kind=kind,
                asset_id=asset_id,
                version_id=version_id,
                status="disabled",
                expected_revision=revision,
                expected_current_status="active",
            )
            revision += 1
            with self.assertRaises(ValueError):
                select()
            drama_asset_usage.set_asset_version_status(
                "usage-guards",
                kind=kind,
                asset_id=asset_id,
                version_id=version_id,
                status="active",
                expected_revision=revision,
                expected_current_status="disabled",
            )
            revision += 1
            select()

        character = values["character_asset"]
        character_candidate = values["character_candidate"]
        cycle(
            "character",
            character.asset_id,
            character_candidate.asset_version_id,
            lambda: drama_asset_versions.select_character_asset_version(
                "usage-guards",
                character_id=character.asset_id,
                asset_version_id=character_candidate.asset_version_id,
                expected_selection_revision=0,
                expected_selected_version_id=character.selected_version_id,
            ),
        )
        art_candidate = values["art_candidate"]
        cycle(
            "art_direction",
            ready["art_catalog"].art_direction_id,
            art_candidate.version_id,
            lambda: drama_art_direction_store.select_art_direction_version(
                "usage-guards",
                version_id=art_candidate.version_id,
                expected_selection_revision=0,
                expected_selected_version_id=ready[
                    "art_catalog"
                ].selected_version_id,
            ),
        )
        scene_candidate = values["scene_candidate"]
        cycle(
            "scene",
            "s001",
            scene_candidate.scene_version_id,
            lambda: drama_asset_versions.select_scene_asset_version(
                "usage-guards",
                scene_id="s001",
                scene_version_id=scene_candidate.scene_version_id,
                expected_selection_revision=0,
                expected_selected_version_id=ready[
                    "scene_version"
                ].scene_version_id,
            ),
        )
        prop_candidate = values["prop_candidate"]
        cycle(
            "prop",
            "p001",
            prop_candidate.asset_version_id,
            lambda: drama_asset_versions.select_prop_or_clue_asset_version(
                "usage-guards",
                asset_id="p001",
                asset_version_id=prop_candidate.asset_version_id,
                expected_selection_revision=0,
                expected_selected_version_id=ready[
                    "prop_version"
                ].asset_version_id,
            ),
        )
        self.assertEqual(
            drama_asset_usage.load_asset_retirement_state(
                "usage-guards"
            ).revision,
            8,
        )

    def test_disabled_selected_versions_block_new_materialization(self) -> None:
        ready = self._ready("usage-materialization")
        revision = 0

        def set_status(
            *,
            kind: str,
            asset_id: str,
            version_id: str,
            status: str,
        ) -> None:
            nonlocal revision
            current = "active" if status == "disabled" else "disabled"
            drama_asset_usage.set_asset_version_status(
                "usage-materialization",
                kind=kind,
                asset_id=asset_id,
                version_id=version_id,
                status=status,
                expected_revision=revision,
                expected_current_status=current,
            )
            revision += 1

        art = ready["art_catalog"]
        set_status(
            kind="art_direction",
            asset_id=art.art_direction_id,
            version_id=art.selected_version_id,
            status="disabled",
        )
        self.assertEqual(
            drama_render_store.create_render_plan("usage-materialization"),
            ready["plan"],
        )
        drama_render_store.render_plan_path("usage-materialization").unlink()
        with self.assertRaisesRegex(ValueError, "disabled"):
            drama_render_store.create_render_plan("usage-materialization")
        set_status(
            kind="art_direction",
            asset_id=art.art_direction_id,
            version_id=art.selected_version_id,
            status="active",
        )
        drama_render_store.create_render_plan("usage-materialization")

        character = ready["character_catalog"].assets[0]
        set_status(
            kind="character",
            asset_id=character.asset_id,
            version_id=character.selected_version_id,
            status="disabled",
        )
        self.assertEqual(
            drama_asset_versions.create_episode_asset_manifest(
                "usage-materialization"
            ),
            ready["character_manifest"],
        )
        drama_asset_versions.episode_asset_manifest_path(
            "usage-materialization"
        ).unlink()
        with self.assertRaisesRegex(ValueError, "disabled"):
            drama_asset_versions.create_episode_asset_manifest(
                "usage-materialization"
            )
        set_status(
            kind="character",
            asset_id=character.asset_id,
            version_id=character.selected_version_id,
            status="active",
        )
        drama_asset_versions.create_episode_asset_manifest(
            "usage-materialization"
        )

        scene = ready["scene_catalog"].assets[0]
        set_status(
            kind="scene",
            asset_id=scene.scene_id,
            version_id=scene.selected_version_id,
            status="disabled",
        )
        self.assertEqual(
            drama_asset_versions.create_episode_scene_asset_manifest(
                "usage-materialization"
            ),
            ready["scene_manifest"],
        )
        drama_asset_versions.episode_scene_asset_manifest_path(
            "usage-materialization"
        ).unlink()
        scene_mapping = {
            shot.shot_id: "s001" for shot in ready["plan"].shots
        }
        with self.assertRaises(ValueError):
            drama_asset_versions.create_episode_scene_asset_manifest(
                "usage-materialization",
                shot_scene_ids=scene_mapping,
            )
        set_status(
            kind="scene",
            asset_id=scene.scene_id,
            version_id=scene.selected_version_id,
            status="active",
        )
        drama_asset_versions.create_episode_scene_asset_manifest(
            "usage-materialization",
            shot_scene_ids=scene_mapping,
        )

        prop = ready["prop_catalog"].assets[0]
        set_status(
            kind=prop.kind,
            asset_id=prop.asset_id,
            version_id=prop.selected_version_id,
            status="disabled",
        )
        self.assertEqual(
            drama_asset_versions.create_episode_prop_or_clue_asset_manifest(
                "usage-materialization"
            ),
            ready["prop_manifest"],
        )
        drama_asset_versions.episode_prop_or_clue_asset_manifest_path(
            "usage-materialization"
        ).unlink()
        prop_mapping = {
            shot.shot_id: [] for shot in ready["plan"].shots
        }
        prop_mapping[ready["plan"].shots[0].shot_id] = ["p001"]
        with self.assertRaises(ValueError):
            drama_asset_versions.create_episode_prop_or_clue_asset_manifest(
                "usage-materialization",
                shot_asset_ids=prop_mapping,
            )
        set_status(
            kind=prop.kind,
            asset_id=prop.asset_id,
            version_id=prop.selected_version_id,
            status="active",
        )
        drama_asset_versions.create_episode_prop_or_clue_asset_manifest(
            "usage-materialization",
            shot_asset_ids=prop_mapping,
        )
        self.assertEqual(revision, 8)

    def test_retirement_double_cas_noop_and_invalid_state_fail_closed(self) -> None:
        ready = self._ready("usage-cas")
        candidates = self._append_candidates("usage-cas", ready)
        asset = candidates["character_asset"]
        version_id = candidates["character_candidate"].asset_version_id
        state = drama_asset_usage.set_asset_version_status(
            "usage-cas",
            kind="character",
            asset_id=asset.asset_id,
            version_id=version_id,
            status="disabled",
            expected_revision=0,
            expected_current_status="active",
        )
        path = drama_asset_usage.asset_retirement_state_path("usage-cas")
        before = path.read_bytes()
        repeated = drama_asset_usage.set_asset_version_status(
            "usage-cas",
            kind="character",
            asset_id=asset.asset_id,
            version_id=version_id,
            status="disabled",
            expected_revision=1,
            expected_current_status="disabled",
        )
        self.assertEqual(repeated, state)
        self.assertEqual(path.read_bytes(), before)
        with self.assertRaisesRegex(ValueError, "revision changed"):
            drama_asset_usage.set_asset_version_status(
                "usage-cas",
                kind="character",
                asset_id=asset.asset_id,
                version_id=version_id,
                status="active",
                expected_revision=0,
                expected_current_status="disabled",
            )
        with self.assertRaisesRegex(ValueError, "strict integer"):
            drama_asset_usage.set_asset_version_status(
                "usage-cas",
                kind="character",
                asset_id=asset.asset_id,
                version_id=version_id,
                status="active",
                expected_revision=True,  # type: ignore[arg-type]
                expected_current_status="disabled",
            )
        path.write_text("{broken", encoding="utf-8")
        self.assertEqual(
            drama_asset_usage.inspect_asset_retirement_state(
                "usage-cas"
            ).state,
            "invalid",
        )
        with self.assertRaisesRegex(ValueError, "state is invalid"):
            drama_asset_usage.assert_asset_version_selectable(
                "usage-cas",
                kind="character",
                asset_id=asset.asset_id,
                version_id=version_id,
            )

    def test_retirement_state_rejects_rehashed_noncanonical_entries(self) -> None:
        ready = self._ready("usage-state-forge")
        candidates = self._append_candidates("usage-state-forge", ready)
        asset = candidates["character_asset"]
        version_id = candidates["character_candidate"].asset_version_id
        state = drama_asset_usage.set_asset_version_status(
            "usage-state-forge",
            kind="character",
            asset_id=asset.asset_id,
            version_id=version_id,
            status="disabled",
            expected_revision=0,
            expected_current_status="active",
        )
        payload = state.model_dump()
        payload["entries"].append(copy.deepcopy(payload["entries"][0]))
        payload["state_fingerprint"] = _canonical_sha256(
            {
                key: value
                for key, value in payload.items()
                if key != "state_fingerprint"
            }
        )
        with self.assertRaises(ValidationError):
            AssetRetirementState(**payload)


if __name__ == "__main__":
    import unittest

    unittest.main()
