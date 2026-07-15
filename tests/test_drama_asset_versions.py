"""iter107: strict asset store, selection CAS, and episode manifests."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from src import (
    character_designer,
    drama_asset_versions,
    drama_assets,
    drama_render_store,
    drama_reviewer,
    drama_store,
    paths,
    storyboard_builder,
)
from src.drama_schemas import character_paths, episode_paths
from src.schemas import model_to_dict
from src.utils import read_json, write_json
from tests._drama_base import DramaTestBase


class DramaAssetVersionStoreTests(DramaTestBase):
    def _seed(self, name: str = "assets", *, assembled: bool = False) -> None:
        self._make_drama_workspace(name, "霸总", episode_count=2)
        self._write_setup(name, hook=True)
        write_json(
            episode_paths(name).storyboard_path,
            storyboard_builder.run(name, mock=True),
        )
        sheet = character_designer.run(name, mock=True)
        first = sheet["characters"][0]
        first["reference_images"] = [
            {"path": f"data/character_refs/{first['id']}/a.svg"},
            {"path": f"data/character_refs/{first['id']}/b.svg"},
        ]
        extra = dict(sheet["characters"][0])
        extra.update(
            {
                "id": "c099",
                "name": "下一集角色",
                "lora_token": "future_character",
                "reference_images": [],
                "appearances": [2],
                "visual_contrast_with": {},
            }
        )
        sheet["characters"].append(extra)
        sheet_path = character_paths(name).sheet_path
        write_json(sheet_path, sheet)
        root = paths.workspace_root(name)
        for suffix, payload in (("a.svg", b"<svg>A</svg>"), ("b.svg", b"<svg>B</svg>")):
            path = root / "data" / "character_refs" / first["id"] / suffix
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
        if assembled:
            write_json(
                episode_paths(name).review_path,
                drama_reviewer.run(name, mock=True),
            )
            drama_store.assemble_episode(name)
            drama_render_store.create_render_plan(name)

    @staticmethod
    def _catalog_bytes(catalog) -> bytes:
        return (
            json.dumps(
                {
                    "schema_version": 1,
                    "artifact_type": "drama_character_asset_catalog",
                    "catalog_fingerprint": catalog.catalog_fingerprint,
                    "catalog": model_to_dict(catalog),
                },
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")

    def test_catalog_create_is_byte_stable_and_preserves_sources(self) -> None:
        self._seed()
        sheet_path = character_paths("assets").sheet_path
        sheet_before = sheet_path.read_bytes()
        self.assertEqual(
            drama_asset_versions.inspect_character_asset_catalog("assets").state,
            "needs_asset_catalog",
        )
        with patch.object(socket, "socket", side_effect=AssertionError("network")):
            first = drama_asset_versions.create_character_asset_catalog("assets")
            path = drama_asset_versions.character_asset_catalog_path("assets")
            before = path.read_bytes()
            mtime = path.stat().st_mtime_ns
            second = drama_asset_versions.create_character_asset_catalog("assets")
            self.assertEqual(
                drama_asset_versions.inspect_character_asset_catalog("assets").state,
                "fresh",
            )
        self.assertEqual(first, second)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(path.stat().st_mtime_ns, mtime)
        self.assertEqual(sheet_path.read_bytes(), sheet_before)
        selected = first.assets[0]
        self.assertEqual(len(selected.versions), 2)
        self.assertEqual(selected.selected_version_id, selected.versions[0].asset_version_id)
        metadata_only = next(asset for asset in first.assets if asset.asset_id == "c099")
        self.assertIsNone(metadata_only.versions[0].artifact)

    def test_refresh_ignores_bookkeeping_and_appends_identity_versions(self) -> None:
        self._seed("refresh")
        original = drama_asset_versions.create_character_asset_catalog("refresh")
        path = character_paths("refresh").sheet_path
        sheet = read_json(path)
        sheet["generated_episode_nos"] = [1, 2]
        sheet["characters"][0]["manual_override"] = True
        sheet["characters"][0]["agent_suggestions"] = [{"field": "wardrobe"}]
        write_json(path, sheet)
        self.assertEqual(
            drama_asset_versions.inspect_character_asset_catalog("refresh").state,
            "fresh",
        )

        sheet["characters"][0]["visual_signature"] = "更新后的外观"
        write_json(path, sheet)
        self.assertEqual(
            drama_asset_versions.inspect_character_asset_catalog("refresh").state,
            "stale",
        )
        with self.assertRaisesRegex(
            drama_asset_versions.DramaAssetStoreError,
            "explicit refresh",
        ):
            drama_asset_versions.create_character_asset_catalog("refresh")
        refreshed = drama_asset_versions.refresh_character_asset_catalog("refresh")
        self.assertEqual(refreshed.assets[0].selected_version_id, original.assets[0].selected_version_id)
        self.assertGreater(len(refreshed.assets[0].versions), len(original.assets[0].versions))

    def test_append_selection_cas_and_idempotent_mtime(self) -> None:
        self._seed("cas")
        catalog = drama_asset_versions.create_character_asset_catalog("cas")
        asset = catalog.assets[0]
        candidate = drama_assets.build_asset_version(
            asset_id=asset.asset_id,
            identity_fingerprint=asset.identity_fingerprint,
            source_kind="appended_candidate",
            derived_from=asset.selected_version_id,
        )
        appended = drama_asset_versions.append_character_asset_version(
            "cas",
            character_id=asset.asset_id,
            version=candidate,
            expected_catalog_fingerprint=catalog.catalog_fingerprint,
        )
        self.assertEqual(appended.assets[0].selected_version_id, asset.selected_version_id)
        path = drama_asset_versions.character_asset_catalog_path("cas")
        mtime = path.stat().st_mtime_ns
        replay = drama_asset_versions.append_character_asset_version(
            "cas",
            character_id=asset.asset_id,
            version=candidate,
            expected_catalog_fingerprint=appended.catalog_fingerprint,
        )
        self.assertEqual(replay, appended)
        self.assertEqual(path.stat().st_mtime_ns, mtime)

        selected = drama_asset_versions.select_character_asset_version(
            "cas",
            character_id=asset.asset_id,
            asset_version_id=candidate.asset_version_id,
            expected_selection_revision=0,
            expected_selected_version_id=asset.selected_version_id,
        )
        current_asset = selected.assets[0]
        self.assertEqual(current_asset.selection_revision, 1)
        mtime = path.stat().st_mtime_ns
        self.assertEqual(
            drama_asset_versions.select_character_asset_version(
                "cas",
                character_id=asset.asset_id,
                asset_version_id=candidate.asset_version_id,
                expected_selection_revision=1,
                expected_selected_version_id=candidate.asset_version_id,
            ),
            selected,
        )
        self.assertEqual(path.stat().st_mtime_ns, mtime)
        with self.assertRaisesRegex(ValueError, "selection changed"):
            drama_asset_versions.select_character_asset_version(
                "cas",
                character_id=asset.asset_id,
                asset_version_id=asset.selected_version_id,
                expected_selection_revision=0,
                expected_selected_version_id=asset.selected_version_id,
            )

        returned = drama_asset_versions.select_character_asset_version(
            "cas",
            character_id=asset.asset_id,
            asset_version_id=asset.selected_version_id,
            expected_selection_revision=1,
            expected_selected_version_id=candidate.asset_version_id,
        )
        self.assertEqual(returned.assets[0].selection_revision, 2)
        self.assertEqual(returned.assets[0].selected_version_id, asset.selected_version_id)
        with self.assertRaisesRegex(ValueError, "selection changed"):
            drama_asset_versions.select_character_asset_version(
                "cas",
                character_id=asset.asset_id,
                asset_version_id=candidate.asset_version_id,
                expected_selection_revision=0,
                expected_selected_version_id=asset.selected_version_id,
            )

    def test_precommit_source_change_aborts_without_catalog_overwrite(self) -> None:
        self._seed("source-race")
        catalog = drama_asset_versions.create_character_asset_catalog("source-race")
        asset = catalog.assets[0]
        candidate = drama_assets.build_asset_version(
            asset_id=asset.asset_id,
            identity_fingerprint=asset.identity_fingerprint,
            source_kind="appended_candidate",
        )
        catalog_path = drama_asset_versions.character_asset_catalog_path("source-race")
        before = catalog_path.read_bytes()
        original_write = drama_asset_versions._write_envelope

        def mutate_source_then_write(*args, **kwargs):
            sheet_path = character_paths("source-race").sheet_path
            sheet = read_json(sheet_path)
            sheet["characters"][0]["visual_signature"] = "并发变化"
            write_json(sheet_path, sheet)
            return original_write(*args, **kwargs)

        with patch(
            "src.drama_asset_versions._write_envelope",
            side_effect=mutate_source_then_write,
        ):
            with self.assertRaisesRegex(
                drama_asset_versions.DramaAssetStoreError,
                "source changed concurrently",
            ):
                drama_asset_versions.append_character_asset_version(
                    "source-race",
                    character_id=asset.asset_id,
                    version=candidate,
                    expected_catalog_fingerprint=catalog.catalog_fingerprint,
                )
        self.assertEqual(catalog_path.read_bytes(), before)

    def test_append_precommit_artifact_change_aborts_without_catalog_overwrite(self) -> None:
        self._seed("append-artifact-race")
        catalog = drama_asset_versions.create_character_asset_catalog(
            "append-artifact-race"
        )
        asset = catalog.assets[0]
        root = paths.workspace_root("append-artifact-race")
        rel = f"data/character_refs/{asset.asset_id}/candidate.svg"
        artifact_path = root / rel
        artifact_path.write_bytes(b"<svg>candidate</svg>")
        candidate = drama_assets.build_asset_version(
            asset_id=asset.asset_id,
            identity_fingerprint=asset.identity_fingerprint,
            source_kind="appended_candidate",
            artifact={
                "path": rel,
                "sha256": hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
                "size_bytes": artifact_path.stat().st_size,
            },
        )
        catalog_path = drama_asset_versions.character_asset_catalog_path(
            "append-artifact-race"
        )
        before = catalog_path.read_bytes()
        original_expected = drama_asset_versions._expected_catalog
        calls = 0

        def mutate_during_final_source_read(*args, **kwargs):
            nonlocal calls
            result = original_expected(*args, **kwargs)
            calls += 1
            if calls == 2:
                artifact_path.write_bytes(b"changed during precommit")
            return result

        with patch(
            "src.drama_asset_versions._expected_catalog",
            side_effect=mutate_during_final_source_read,
        ):
            with self.assertRaisesRegex(
                drama_asset_versions.DramaAssetStoreError,
                "artifact",
            ):
                drama_asset_versions.append_character_asset_version(
                    "append-artifact-race",
                    character_id=asset.asset_id,
                    version=candidate,
                    expected_catalog_fingerprint=catalog.catalog_fingerprint,
                )
        self.assertEqual(catalog_path.read_bytes(), before)

    def test_select_precommit_artifact_change_aborts_without_catalog_overwrite(self) -> None:
        self._seed("select-artifact-race")
        catalog = drama_asset_versions.create_character_asset_catalog(
            "select-artifact-race"
        )
        asset = catalog.assets[0]
        root = paths.workspace_root("select-artifact-race")
        rel = f"data/character_refs/{asset.asset_id}/candidate.svg"
        artifact_path = root / rel
        artifact_path.write_bytes(b"<svg>candidate</svg>")
        candidate = drama_assets.build_asset_version(
            asset_id=asset.asset_id,
            identity_fingerprint=asset.identity_fingerprint,
            source_kind="appended_candidate",
            artifact={
                "path": rel,
                "sha256": hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
                "size_bytes": artifact_path.stat().st_size,
            },
        )
        catalog = drama_asset_versions.append_character_asset_version(
            "select-artifact-race",
            character_id=asset.asset_id,
            version=candidate,
            expected_catalog_fingerprint=catalog.catalog_fingerprint,
        )
        catalog_path = drama_asset_versions.character_asset_catalog_path(
            "select-artifact-race"
        )
        before = catalog_path.read_bytes()
        original_expected = drama_asset_versions._expected_catalog
        calls = 0

        def mutate_during_final_source_read(*args, **kwargs):
            nonlocal calls
            result = original_expected(*args, **kwargs)
            calls += 1
            if calls == 2:
                artifact_path.write_bytes(b"changed during precommit")
            return result

        with patch(
            "src.drama_asset_versions._expected_catalog",
            side_effect=mutate_during_final_source_read,
        ):
            with self.assertRaisesRegex(
                drama_asset_versions.DramaAssetStoreError,
                "artifact",
            ):
                drama_asset_versions.select_character_asset_version(
                    "select-artifact-race",
                    character_id=asset.asset_id,
                    asset_version_id=candidate.asset_version_id,
                    expected_selection_revision=0,
                    expected_selected_version_id=asset.selected_version_id,
                )
        self.assertEqual(catalog_path.read_bytes(), before)

    def test_target_token_is_captured_before_catalog_baseline_read(self) -> None:
        self._seed("token-race")
        catalog = drama_asset_versions.create_character_asset_catalog("token-race")
        asset = catalog.assets[0]
        injected_version = drama_assets.build_asset_version(
            asset_id=asset.asset_id,
            identity_fingerprint=asset.identity_fingerprint,
            source_kind="appended_candidate",
            derived_from=asset.versions[0].asset_version_id,
        )
        requested_version = drama_assets.build_asset_version(
            asset_id=asset.asset_id,
            identity_fingerprint=asset.identity_fingerprint,
            source_kind="appended_candidate",
            derived_from=asset.versions[1].asset_version_id,
        )
        injected = drama_assets.append_asset_version(
            catalog,
            asset_id=asset.asset_id,
            version=injected_version,
            expected_catalog_fingerprint=catalog.catalog_fingerprint,
        )
        injected_bytes = self._catalog_bytes(injected)
        path = drama_asset_versions.character_asset_catalog_path("token-race")

        def inject_before_read(_root, _path, *, maximum):
            self.assertEqual(_path, path)
            self.assertGreater(maximum, len(injected_bytes))
            path.write_bytes(injected_bytes)
            return (
                "file",
                len(injected_bytes),
                hashlib.sha256(injected_bytes).hexdigest(),
            )

        with patch(
            "src.drama_asset_versions._target_token",
            side_effect=inject_before_read,
        ):
            with self.assertRaisesRegex(ValueError, "catalog changed"):
                drama_asset_versions.append_character_asset_version(
                    "token-race",
                    character_id=asset.asset_id,
                    version=requested_version,
                    expected_catalog_fingerprint=catalog.catalog_fingerprint,
                )
        persisted = drama_asset_versions.load_fresh_character_asset_catalog("token-race")
        persisted_ids = {
            version.asset_version_id for version in persisted.assets[0].versions
        }
        self.assertIn(injected_version.asset_version_id, persisted_ids)
        self.assertNotIn(requested_version.asset_version_id, persisted_ids)

        current = persisted
        current_asset = current.assets[0]
        late_version = drama_assets.build_asset_version(
            asset_id=current_asset.asset_id,
            identity_fingerprint=current_asset.identity_fingerprint,
            source_kind="appended_candidate",
            derived_from=injected_version.asset_version_id,
        )
        late = drama_assets.append_asset_version(
            current,
            asset_id=current_asset.asset_id,
            version=late_version,
            expected_catalog_fingerprint=current.catalog_fingerprint,
        )
        late_bytes = self._catalog_bytes(late)
        current_bytes = path.read_bytes()
        expected_token = (
            "file",
            len(current_bytes),
            hashlib.sha256(current_bytes).hexdigest(),
        )
        calls = 0

        def inject_before_replace(_fd, _name, *, maximum):
            nonlocal calls
            calls += 1
            if calls == 1:
                return expected_token
            path.write_bytes(late_bytes)
            return (
                "file",
                len(late_bytes),
                hashlib.sha256(late_bytes).hexdigest(),
            )

        with patch(
            "src.drama_asset_versions._target_token_at",
            side_effect=inject_before_replace,
        ):
            with self.assertRaisesRegex(
                drama_asset_versions.DramaAssetStoreError,
                "changed concurrently",
            ):
                drama_asset_versions.append_character_asset_version(
                    "token-race",
                    character_id=current_asset.asset_id,
                    version=requested_version,
                    expected_catalog_fingerprint=current.catalog_fingerprint,
                )
        persisted = drama_asset_versions.load_fresh_character_asset_catalog("token-race")
        persisted_ids = {
            version.asset_version_id for version in persisted.assets[0].versions
        }
        self.assertIn(late_version.asset_version_id, persisted_ids)
        self.assertNotIn(requested_version.asset_version_id, persisted_ids)

    def test_manifest_stale_is_exact_to_active_selection_and_render_plan(self) -> None:
        self._seed("manifest", assembled=True)
        catalog = drama_asset_versions.create_character_asset_catalog("manifest")
        manifest = drama_asset_versions.create_episode_asset_manifest("manifest")
        path = drama_asset_versions.episode_asset_manifest_path("manifest")
        before = path.read_bytes()
        self.assertEqual(
            drama_asset_versions.inspect_episode_asset_manifest("manifest").state,
            "fresh",
        )

        active = catalog.assets[0]
        candidate = drama_assets.build_asset_version(
            asset_id=active.asset_id,
            identity_fingerprint=active.identity_fingerprint,
            source_kind="appended_candidate",
        )
        catalog = drama_asset_versions.append_character_asset_version(
            "manifest",
            character_id=active.asset_id,
            version=candidate,
            expected_catalog_fingerprint=catalog.catalog_fingerprint,
        )
        self.assertEqual(
            drama_asset_versions.inspect_episode_asset_manifest("manifest").state,
            "fresh",
        )
        self.assertEqual(path.read_bytes(), before)

        future = next(asset for asset in catalog.assets if asset.asset_id == "c099")
        future_candidate = drama_assets.build_asset_version(
            asset_id=future.asset_id,
            identity_fingerprint=future.identity_fingerprint,
            source_kind="appended_candidate",
        )
        catalog = drama_asset_versions.append_character_asset_version(
            "manifest",
            character_id=future.asset_id,
            version=future_candidate,
            expected_catalog_fingerprint=catalog.catalog_fingerprint,
        )
        catalog = drama_asset_versions.select_character_asset_version(
            "manifest",
            character_id=future.asset_id,
            asset_version_id=future_candidate.asset_version_id,
            expected_selection_revision=0,
            expected_selected_version_id=future.selected_version_id,
        )
        self.assertEqual(
            drama_asset_versions.inspect_episode_asset_manifest("manifest").state,
            "fresh",
        )

        catalog = drama_asset_versions.select_character_asset_version(
            "manifest",
            character_id=active.asset_id,
            asset_version_id=candidate.asset_version_id,
            expected_selection_revision=0,
            expected_selected_version_id=active.selected_version_id,
        )
        self.assertEqual(
            drama_asset_versions.inspect_episode_asset_manifest("manifest").state,
            "stale",
        )
        with self.assertRaisesRegex(
            drama_asset_versions.DramaAssetStoreError,
            "explicit replacement",
        ):
            drama_asset_versions.create_episode_asset_manifest("manifest")
        replaced = drama_asset_versions.create_episode_asset_manifest(
            "manifest",
            replace_stale=True,
        )
        self.assertNotEqual(replaced.selection_fingerprint, manifest.selection_fingerprint)
        self.assertEqual(
            drama_asset_versions.load_fresh_episode_asset_manifest("manifest"),
            replaced,
        )

    def test_non_active_source_damage_does_not_stale_existing_manifest(self) -> None:
        self._seed("non-active", assembled=True)
        drama_asset_versions.create_character_asset_catalog("non-active")
        manifest = drama_asset_versions.create_episode_asset_manifest("non-active")
        manifest_path = drama_asset_versions.episode_asset_manifest_path("non-active")
        before = manifest_path.read_bytes()
        mtime = manifest_path.stat().st_mtime_ns

        sheet_path = character_paths("non-active").sheet_path
        sheet = read_json(sheet_path)
        future = next(row for row in sheet["characters"] if row["id"] == "c099")
        future["visual_signature"] = "只影响下一集"
        future["reference_images"] = [
            {"path": "data/character_refs/c099/missing.svg"}
        ]
        write_json(sheet_path, sheet)
        self.assertEqual(
            drama_asset_versions.inspect_character_asset_catalog("non-active").state,
            "blocked_source",
        )
        self.assertEqual(
            drama_render_store.inspect_render_plan("non-active").state,
            "fresh",
        )
        self.assertEqual(
            drama_asset_versions.load_fresh_episode_asset_manifest("non-active"),
            manifest,
        )
        self.assertEqual(manifest_path.read_bytes(), before)
        self.assertEqual(manifest_path.stat().st_mtime_ns, mtime)

    def test_manifest_needs_and_invalid_envelope_states(self) -> None:
        self._seed("manifest-states", assembled=True)
        drama_asset_versions.create_character_asset_catalog("manifest-states")
        self.assertEqual(
            drama_asset_versions.inspect_episode_asset_manifest("manifest-states").state,
            "needs_asset_manifest",
        )
        drama_asset_versions.create_episode_asset_manifest("manifest-states")
        path = drama_asset_versions.episode_asset_manifest_path("manifest-states")
        path.write_text(
            '{"schema_version":1,"schema_version":1}',
            encoding="utf-8",
        )
        self.assertEqual(
            drama_asset_versions.inspect_episode_asset_manifest("manifest-states").state,
            "invalid",
        )

    def test_active_selected_artifact_damage_blocks_until_valid_candidate_selected(self) -> None:
        self._seed("artifact-damage", assembled=True)
        catalog = drama_asset_versions.create_character_asset_catalog("artifact-damage")
        drama_asset_versions.create_episode_asset_manifest("artifact-damage")
        active = catalog.assets[0]
        selected = next(
            version
            for version in active.versions
            if version.asset_version_id == active.selected_version_id
        )
        self.assertIsNotNone(selected.artifact)
        artifact_path = paths.workspace_root("artifact-damage") / selected.artifact.path
        artifact_path.write_bytes(b"<svg>changed</svg>")
        inspection = drama_asset_versions.inspect_episode_asset_manifest("artifact-damage")
        self.assertEqual(inspection.state, "stale")
        self.assertIn("selected_artifact_mismatch", inspection.reasons)

        refreshed = drama_asset_versions.refresh_character_asset_catalog("artifact-damage")
        active = refreshed.assets[0]
        self.assertEqual(active.selected_version_id, selected.asset_version_id)
        new_sha = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        replacement = next(
            version
            for version in active.versions
            if version.artifact is not None and version.artifact.sha256 == new_sha
        )
        with self.assertRaisesRegex(
            (ValueError, drama_asset_versions.DramaAssetStoreError),
            "artifact|sources",
        ):
            drama_asset_versions.create_episode_asset_manifest(
                "artifact-damage",
                replace_stale=True,
            )
        refreshed = drama_asset_versions.select_character_asset_version(
            "artifact-damage",
            character_id=active.asset_id,
            asset_version_id=replacement.asset_version_id,
            expected_selection_revision=active.selection_revision,
            expected_selected_version_id=active.selected_version_id,
        )
        self.assertEqual(
            drama_asset_versions.inspect_episode_asset_manifest("artifact-damage").state,
            "stale",
        )
        rebuilt = drama_asset_versions.create_episode_asset_manifest(
            "artifact-damage",
            replace_stale=True,
        )
        self.assertEqual(
            rebuilt.asset_refs[0].artifact_sha256,
            replacement.artifact.sha256,
        )

    def test_select_revalidates_target_artifact(self) -> None:
        self._seed("select-artifact")
        catalog = drama_asset_versions.create_character_asset_catalog("select-artifact")
        asset = catalog.assets[0]
        root = paths.workspace_root("select-artifact")
        rel = f"data/character_refs/{asset.asset_id}/candidate.svg"
        artifact_path = root / rel
        artifact_path.write_bytes(b"<svg>candidate</svg>")
        candidate = drama_assets.build_asset_version(
            asset_id=asset.asset_id,
            identity_fingerprint=asset.identity_fingerprint,
            source_kind="appended_candidate",
            artifact={
                "path": rel,
                "sha256": hashlib.sha256(artifact_path.read_bytes()).hexdigest(),
                "size_bytes": artifact_path.stat().st_size,
            },
        )
        catalog = drama_asset_versions.append_character_asset_version(
            "select-artifact",
            character_id=asset.asset_id,
            version=candidate,
            expected_catalog_fingerprint=catalog.catalog_fingerprint,
        )
        artifact_path.write_bytes(b"changed")
        current = catalog.assets[0]
        with self.assertRaisesRegex(
            (ValueError, drama_asset_versions.DramaAssetStoreError),
            "artifact",
        ):
            drama_asset_versions.select_character_asset_version(
                "select-artifact",
                character_id=asset.asset_id,
                asset_version_id=candidate.asset_version_id,
                expected_selection_revision=current.selection_revision,
                expected_selected_version_id=current.selected_version_id,
            )

    def test_invalid_duplicate_symlink_and_target_cas_fail_closed(self) -> None:
        self._seed("boundary")
        drama_asset_versions.create_character_asset_catalog("boundary")
        path = drama_asset_versions.character_asset_catalog_path("boundary")
        valid = path.read_bytes()
        path.write_text(
            '{"schema_version":1,"schema_version":1}',
            encoding="utf-8",
        )
        self.assertEqual(
            drama_asset_versions.inspect_character_asset_catalog("boundary").state,
            "invalid",
        )
        path.write_bytes(valid)

        target = path.with_name("outside.json")
        target.write_bytes(valid)
        path.unlink()
        path.symlink_to(target)
        self.assertEqual(
            drama_asset_versions.inspect_character_asset_catalog("boundary").state,
            "invalid",
        )
        path.unlink()
        path.write_bytes(valid)

        with patch(
            "src.drama_asset_versions._target_token_at",
            return_value=("file", 1, "changed"),
        ):
            sheet = read_json(character_paths("boundary").sheet_path)
            sheet["characters"][0]["visual_signature"] = "变化"
            write_json(character_paths("boundary").sheet_path, sheet)
            with self.assertRaisesRegex(
                drama_asset_versions.DramaAssetStoreError,
                "changed concurrently",
            ):
                drama_asset_versions.refresh_character_asset_catalog("boundary")

        path.write_bytes(valid)
        path.write_text('{"x":NaN}', encoding="utf-8")
        self.assertEqual(
            drama_asset_versions.inspect_character_asset_catalog("boundary").state,
            "invalid",
        )
        path.write_text('{"x":' * 1100 + "0" + "}" * 1100, encoding="utf-8")
        self.assertEqual(
            drama_asset_versions.inspect_character_asset_catalog("boundary").state,
            "invalid",
        )
        path.write_bytes(b"{" + b" " * (drama_asset_versions.MAX_ASSET_CATALOG_BYTES + 1))
        self.assertEqual(
            drama_asset_versions.inspect_character_asset_catalog("boundary").state,
            "invalid",
        )
        path.unlink()
        path.mkdir()
        self.assertEqual(
            drama_asset_versions.inspect_character_asset_catalog("boundary").state,
            "invalid",
        )
        path.rmdir()
        path.write_bytes(valid)

        assets_dir = path.parent
        real_assets = assets_dir.with_name("assets-real")
        assets_dir.rename(real_assets)
        assets_dir.symlink_to(real_assets, target_is_directory=True)
        self.assertEqual(
            drama_asset_versions.inspect_character_asset_catalog("boundary").state,
            "invalid",
        )
        assets_dir.unlink()
        real_assets.rename(assets_dir)

    def test_fifo_targets_fail_without_blocking(self) -> None:
        base = paths.WORKSPACE_DIR
        root = base / "fifo"
        target = root / "data/assets/season_01.character_assets.json"
        target.parent.mkdir(parents=True)
        os.mkfifo(target)
        code = """
import os, sys
from pathlib import Path
from src import drama_asset_versions, paths
paths.WORKSPACE_DIR = Path(sys.argv[1])
state = drama_asset_versions.inspect_character_asset_catalog('fifo').state
parent = drama_asset_versions.character_asset_catalog_path('fifo').parent
fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
try:
    token = drama_asset_versions._target_token_at(fd, 'season_01.character_assets.json', maximum=100)
finally:
    os.close(fd)
raise SystemExit(0 if state == 'invalid' and token == ('invalid',) else 3)
"""
        completed = subprocess.run(
            [sys.executable, "-c", code, str(base)],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_all_asset_mutations_are_socket_free(self) -> None:
        self._seed("offline", assembled=True)
        with patch.object(socket, "socket", side_effect=AssertionError("network")):
            catalog = drama_asset_versions.create_character_asset_catalog("offline")
            asset = catalog.assets[0]
            candidate = drama_assets.build_asset_version(
                asset_id=asset.asset_id,
                identity_fingerprint=asset.identity_fingerprint,
                source_kind="appended_candidate",
            )
            catalog = drama_asset_versions.append_character_asset_version(
                "offline",
                character_id=asset.asset_id,
                version=candidate,
                expected_catalog_fingerprint=catalog.catalog_fingerprint,
            )
            catalog = drama_asset_versions.select_character_asset_version(
                "offline",
                character_id=asset.asset_id,
                asset_version_id=candidate.asset_version_id,
                expected_selection_revision=0,
                expected_selected_version_id=asset.selected_version_id,
            )
            manifest = drama_asset_versions.create_episode_asset_manifest("offline")
            self.assertEqual(manifest.asset_refs[0].asset_version_id, candidate.asset_version_id)
            self.assertEqual(
                drama_asset_versions.load_fresh_episode_asset_manifest("offline"),
                manifest,
            )

    def test_missing_reference_and_stale_render_block_without_overwrite(self) -> None:
        self._seed("blocked")
        ref = paths.workspace_root("blocked") / "data/character_refs/c001/a.svg"
        ref.unlink()
        self.assertEqual(
            drama_asset_versions.inspect_character_asset_catalog("blocked").state,
            "blocked_source",
        )

        self._seed("render-stale", assembled=True)
        drama_asset_versions.create_character_asset_catalog("render-stale")
        drama_asset_versions.create_episode_asset_manifest("render-stale")
        manifest_path = drama_asset_versions.episode_asset_manifest_path("render-stale")
        before = manifest_path.read_bytes()
        storyboard_path = episode_paths("render-stale").storyboard_path
        storyboard = read_json(storyboard_path)
        storyboard["title"] = "创作改动"
        write_json(storyboard_path, storyboard)
        self.assertEqual(
            drama_asset_versions.inspect_episode_asset_manifest("render-stale").state,
            "blocked_source",
        )
        self.assertEqual(manifest_path.read_bytes(), before)
        write_json(
            episode_paths("render-stale").review_path,
            drama_reviewer.run("render-stale", mock=True),
        )
        drama_store.assemble_episode("render-stale")
        self.assertEqual(
            drama_render_store.inspect_render_plan("render-stale").state,
            "stale",
        )
        stale = drama_asset_versions.inspect_episode_asset_manifest("render-stale")
        self.assertEqual(stale.state, "stale")
        self.assertIn("render_plan_stale", stale.reasons)
