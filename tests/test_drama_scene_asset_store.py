"""iter109: strict scene catalog and episode manifest persistence."""

from __future__ import annotations

import hashlib
import json
import os
import socket
from pathlib import Path
from unittest.mock import patch

from src import (
    character_designer,
    drama_art_direction_store,
    drama_asset_versions,
    drama_assets,
    drama_render_store,
    drama_reviewer,
    drama_store,
    paths,
    storyboard_builder,
)
from src.drama_schemas import RenderPlan, character_paths, episode_paths
from src.schemas import model_to_dict
from src.utils import write_json
from src.workspace_lock import WorkspaceLocked
from tests._drama_base import DramaTestBase


class DramaSceneAssetStoreTests(DramaTestBase):
    def _seed(self, name: str = "scenes", *, assembled: bool = True) -> None:
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
        if assembled:
            write_json(
                episode_paths(name).review_path,
                drama_reviewer.run(name, mock=True),
            )
            drama_store.assemble_episode(name)
            drama_render_store.create_render_plan(name)

    @staticmethod
    def _spec(name: str) -> dict:
        return {
            "display_name": name,
            "location": f"{name}位置",
            "time_of_day": "夜",
            "weather": "晴",
            "spatial_anchors": ["入口", "窗边"],
            "visual_tokens": ["冷色"],
        }

    def _version(
        self,
        workspace: str,
        scene_id: str,
        name: str,
        *,
        derived_from: str | None = None,
        artifact: bool = False,
    ):
        record = None
        if artifact:
            root = paths.workspace_root(workspace)
            filename = hashlib.sha256(name.encode("utf-8")).hexdigest()[:12]
            rel = f"data/scene_refs/{scene_id}/ref_{filename}.png"
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = f"scene:{scene_id}:{name}".encode("utf-8")
            path.write_bytes(payload)
            record = {
                "path": rel,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size_bytes": len(payload),
            }
        return drama_assets.build_scene_asset_version(
            scene_id=scene_id,
            spec=self._spec(name),
            source_kind=(
                "identity_snapshot" if derived_from is None else "appended_candidate"
            ),
            artifact=record,
            derived_from=derived_from,
        )

    def _catalog_with_two(self, name: str = "scenes"):
        first = self._version(name, "s001", "天台")
        catalog = drama_asset_versions.create_scene_asset_catalog(
            name,
            version=first,
        )
        second = self._version(name, "s002", "办公室")
        catalog = drama_asset_versions.add_scene_asset(
            name,
            version=second,
            expected_catalog_fingerprint=catalog.catalog_fingerprint,
        )
        return catalog, first, second

    @staticmethod
    def _catalog_bytes(catalog) -> bytes:
        return (
            json.dumps(
                {
                    "schema_version": 1,
                    "artifact_type": "drama_scene_asset_catalog",
                    "catalog_fingerprint": catalog.catalog_fingerprint,
                    "catalog": model_to_dict(catalog),
                },
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")

    def test_catalog_store_is_idempotent_append_only_and_double_cas(self) -> None:
        self._seed(assembled=False)
        first = self._version("scenes", "s001", "天台", artifact=True)
        with patch.object(socket, "socket", side_effect=AssertionError("network")):
            catalog = drama_asset_versions.create_scene_asset_catalog(
                "scenes",
                version=first,
            )
            path = drama_asset_versions.scene_asset_catalog_path("scenes")
            before = path.read_bytes()
            mtime = path.stat().st_mtime_ns
            self.assertEqual(
                drama_asset_versions.create_scene_asset_catalog(
                    "scenes",
                    version=first,
                ),
                catalog,
            )
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(path.stat().st_mtime_ns, mtime)
            second = self._version("scenes", "s002", "办公室")
            catalog = drama_asset_versions.add_scene_asset(
                "scenes",
                version=second,
                expected_catalog_fingerprint=catalog.catalog_fingerprint,
            )
            candidate = self._version(
                "scenes",
                "s001",
                "暴雨天台",
                derived_from=first.scene_version_id,
            )
            appended = drama_asset_versions.append_scene_asset_version(
                "scenes",
                scene_id="s001",
                version=candidate,
                expected_catalog_fingerprint=catalog.catalog_fingerprint,
            )
            self.assertEqual(
                appended.assets[0].selected_version_id,
                first.scene_version_id,
            )
            selected = drama_asset_versions.select_scene_asset_version(
                "scenes",
                scene_id="s001",
                scene_version_id=candidate.scene_version_id,
                expected_selection_revision=0,
                expected_selected_version_id=first.scene_version_id,
            )
            returned = drama_asset_versions.select_scene_asset_version(
                "scenes",
                scene_id="s001",
                scene_version_id=first.scene_version_id,
                expected_selection_revision=1,
                expected_selected_version_id=candidate.scene_version_id,
            )
        self.assertEqual(selected.assets[0].selection_revision, 1)
        self.assertEqual(returned.assets[0].selection_revision, 2)
        with self.assertRaisesRegex(ValueError, "scene asset selection was rejected"):
            drama_asset_versions.select_scene_asset_version(
                "scenes",
                scene_id="s001",
                scene_version_id=candidate.scene_version_id,
                expected_selection_revision=0,
                expected_selected_version_id=first.scene_version_id,
            )

    def test_manifest_binding_used_by_and_precise_stale(self) -> None:
        self._seed("manifest")
        catalog, first, _second = self._catalog_with_two("manifest")
        plan = drama_render_store.load_fresh_render_plan("manifest")
        mapping = {
            shot.shot_id: ("s001" if index % 2 == 0 else "s002")
            for index, shot in enumerate(plan.shots)
        }
        character_catalog = drama_asset_versions.create_character_asset_catalog(
            "manifest"
        )
        character_manifest = drama_asset_versions.create_episode_asset_manifest(
            "manifest"
        )
        with patch.object(socket, "socket", side_effect=AssertionError("network")):
            manifest = drama_asset_versions.create_episode_scene_asset_manifest(
                "manifest",
                shot_scene_ids=mapping,
            )
        usage = drama_assets.scene_usage_index(manifest)
        self.assertEqual(
            set(shot_id for values in usage.values() for shot_id in values),
            set(mapping),
        )
        self.assertEqual(
            drama_asset_versions.inspect_episode_scene_asset_manifest("manifest").state,
            "fresh",
        )

        candidate = self._version(
            "manifest",
            "s001",
            "候选天台",
            derived_from=first.scene_version_id,
        )
        catalog = drama_asset_versions.append_scene_asset_version(
            "manifest",
            scene_id="s001",
            version=candidate,
            expected_catalog_fingerprint=catalog.catalog_fingerprint,
        )
        self.assertEqual(
            drama_asset_versions.inspect_episode_scene_asset_manifest("manifest").state,
            "fresh",
        )

        unused = self._version("manifest", "s003", "地下室")
        catalog = drama_asset_versions.add_scene_asset(
            "manifest",
            version=unused,
            expected_catalog_fingerprint=catalog.catalog_fingerprint,
        )
        unused_candidate = self._version(
            "manifest",
            "s003",
            "废弃地下室",
            derived_from=unused.scene_version_id,
        )
        catalog = drama_asset_versions.append_scene_asset_version(
            "manifest",
            scene_id="s003",
            version=unused_candidate,
            expected_catalog_fingerprint=catalog.catalog_fingerprint,
        )
        catalog = drama_asset_versions.select_scene_asset_version(
            "manifest",
            scene_id="s003",
            scene_version_id=unused_candidate.scene_version_id,
            expected_selection_revision=0,
            expected_selected_version_id=unused.scene_version_id,
        )
        self.assertEqual(
            drama_asset_versions.inspect_episode_scene_asset_manifest("manifest").state,
            "fresh",
        )

        catalog = drama_asset_versions.select_scene_asset_version(
            "manifest",
            scene_id="s001",
            scene_version_id=candidate.scene_version_id,
            expected_selection_revision=0,
            expected_selected_version_id=first.scene_version_id,
        )
        self.assertEqual(
            drama_asset_versions.inspect_episode_scene_asset_manifest("manifest").state,
            "stale",
        )
        self.assertEqual(
            drama_render_store.inspect_render_plan("manifest").state,
            "fresh",
        )
        self.assertEqual(
            drama_asset_versions.inspect_episode_asset_manifest("manifest").state,
            "fresh",
        )
        refreshed = drama_asset_versions.create_episode_scene_asset_manifest(
            "manifest",
            replace_stale=True,
            expected_manifest_fingerprint=manifest.manifest_fingerprint,
        )
        self.assertEqual(refreshed.binding_revision, manifest.binding_revision)
        self.assertEqual(
            drama_asset_versions.inspect_episode_scene_asset_manifest("manifest").state,
            "fresh",
        )
        self.assertEqual(
            drama_asset_versions.load_fresh_episode_asset_manifest("manifest"),
            character_manifest,
        )
        self.assertEqual(
            drama_asset_versions.load_fresh_character_asset_catalog("manifest"),
            character_catalog,
        )

    def test_manifest_requires_complete_explicit_mapping_and_replacement_cas(self) -> None:
        self._seed("binding")
        self._catalog_with_two("binding")
        plan = drama_render_store.load_fresh_render_plan("binding")
        with self.assertRaisesRegex(
            drama_asset_versions.DramaAssetStoreError,
            "explicit shot scene bindings",
        ):
            drama_asset_versions.create_episode_scene_asset_manifest("binding")
        incomplete = {plan.shots[0].shot_id: "s001"}
        with self.assertRaisesRegex(ValueError, "manifest update was rejected"):
            drama_asset_versions.create_episode_scene_asset_manifest(
                "binding",
                shot_scene_ids=incomplete,
            )
        mapping = {shot.shot_id: "s001" for shot in plan.shots}
        manifest = drama_asset_versions.create_episode_scene_asset_manifest(
            "binding",
            shot_scene_ids=mapping,
        )
        changed = dict(mapping)
        changed[plan.shots[0].shot_id] = "s002"
        with self.assertRaisesRegex(
            drama_asset_versions.DramaAssetStoreError,
            "replacement must be explicit",
        ):
            drama_asset_versions.create_episode_scene_asset_manifest(
                "binding",
                shot_scene_ids=changed,
            )
        with self.assertRaisesRegex(
            drama_asset_versions.DramaAssetStoreError,
            "CAS is required",
        ):
            drama_asset_versions.create_episode_scene_asset_manifest(
                "binding",
                shot_scene_ids=changed,
                replace_stale=True,
            )
        replaced = drama_asset_versions.create_episode_scene_asset_manifest(
            "binding",
            shot_scene_ids=changed,
            replace_stale=True,
            expected_manifest_fingerprint=manifest.manifest_fingerprint,
        )
        self.assertEqual(replaced.binding_revision, 1)
        with self.assertRaisesRegex(
            drama_asset_versions.DramaAssetStoreError,
            "changed; refresh",
        ):
            drama_asset_versions.create_episode_scene_asset_manifest(
                "binding",
                shot_scene_ids=mapping,
                replace_stale=True,
                expected_manifest_fingerprint=manifest.manifest_fingerprint,
            )

    def test_used_artifact_tamper_stales_manifest_without_touching_render_plan(self) -> None:
        self._seed("artifact-stale")
        first = self._version(
            "artifact-stale",
            "s001",
            "天台",
            artifact=True,
        )
        drama_asset_versions.create_scene_asset_catalog(
            "artifact-stale",
            version=first,
        )
        plan = drama_render_store.load_fresh_render_plan("artifact-stale")
        mapping = {shot.shot_id: "s001" for shot in plan.shots}
        drama_asset_versions.create_episode_scene_asset_manifest(
            "artifact-stale",
            shot_scene_ids=mapping,
        )
        self.assertEqual(
            drama_asset_versions.inspect_episode_scene_asset_manifest(
                "artifact-stale"
            ).state,
            "fresh",
        )
        artifact_path = paths.workspace_root("artifact-stale") / first.artifact.path
        artifact_path.write_bytes(b"tampered")
        self.assertEqual(
            drama_asset_versions.inspect_episode_scene_asset_manifest(
                "artifact-stale"
            ).state,
            "stale",
        )
        self.assertEqual(
            drama_render_store.inspect_render_plan("artifact-stale").state,
            "fresh",
        )

    def test_idempotent_append_still_revalidates_artifact_bytes(self) -> None:
        self._seed("artifact-replay", assembled=False)
        first = self._version("artifact-replay", "s001", "天台")
        catalog = drama_asset_versions.create_scene_asset_catalog(
            "artifact-replay",
            version=first,
        )
        candidate = self._version(
            "artifact-replay",
            "s001",
            "候选天台",
            derived_from=first.scene_version_id,
            artifact=True,
        )
        catalog = drama_asset_versions.append_scene_asset_version(
            "artifact-replay",
            scene_id="s001",
            version=candidate,
            expected_catalog_fingerprint=catalog.catalog_fingerprint,
        )
        path = drama_asset_versions.scene_asset_catalog_path("artifact-replay")
        before = path.read_bytes()
        artifact_path = paths.workspace_root("artifact-replay") / candidate.artifact.path
        artifact_path.write_bytes(b"tampered")
        with self.assertRaisesRegex(
            drama_asset_versions.DramaAssetStoreError,
            "artifact",
        ):
            drama_asset_versions.append_scene_asset_version(
                "artifact-replay",
                scene_id="s001",
                version=candidate,
                expected_catalog_fingerprint=catalog.catalog_fingerprint,
            )
        self.assertEqual(path.read_bytes(), before)

    def test_idempotent_create_and_select_revalidate_artifact_bytes(self) -> None:
        self._seed("create-replay", assembled=False)
        first = self._version(
            "create-replay",
            "s001",
            "天台",
            artifact=True,
        )
        drama_asset_versions.create_scene_asset_catalog(
            "create-replay",
            version=first,
        )
        artifact_path = paths.workspace_root("create-replay") / first.artifact.path
        artifact_path.write_bytes(b"tampered")
        with self.assertRaisesRegex(
            drama_asset_versions.DramaAssetStoreError,
            "artifact",
        ):
            drama_asset_versions.create_scene_asset_catalog(
                "create-replay",
                version=first,
            )

        self._seed("select-replay", assembled=False)
        base = self._version("select-replay", "s001", "天台")
        catalog = drama_asset_versions.create_scene_asset_catalog(
            "select-replay",
            version=base,
        )
        candidate = self._version(
            "select-replay",
            "s001",
            "候选天台",
            derived_from=base.scene_version_id,
            artifact=True,
        )
        catalog = drama_asset_versions.append_scene_asset_version(
            "select-replay",
            scene_id="s001",
            version=candidate,
            expected_catalog_fingerprint=catalog.catalog_fingerprint,
        )
        catalog = drama_asset_versions.select_scene_asset_version(
            "select-replay",
            scene_id="s001",
            scene_version_id=candidate.scene_version_id,
            expected_selection_revision=0,
            expected_selected_version_id=base.scene_version_id,
        )
        candidate_path = paths.workspace_root("select-replay") / candidate.artifact.path
        candidate_path.write_bytes(b"tampered")
        with self.assertRaisesRegex(
            drama_asset_versions.DramaAssetStoreError,
            "artifact",
        ):
            drama_asset_versions.select_scene_asset_version(
                "select-replay",
                scene_id="s001",
                scene_version_id=candidate.scene_version_id,
                expected_selection_revision=1,
                expected_selected_version_id=candidate.scene_version_id,
            )

    def test_manifest_precommit_scene_selection_change_aborts_without_write(self) -> None:
        self._seed("source-race")
        catalog, first, _second = self._catalog_with_two("source-race")
        candidate = self._version(
            "source-race",
            "s001",
            "候选天台",
            derived_from=first.scene_version_id,
        )
        catalog = drama_asset_versions.append_scene_asset_version(
            "source-race",
            scene_id="s001",
            version=candidate,
            expected_catalog_fingerprint=catalog.catalog_fingerprint,
        )
        changed = drama_assets.select_scene_asset_version(
            catalog,
            scene_id="s001",
            scene_version_id=candidate.scene_version_id,
            expected_selection_revision=0,
            expected_selected_version_id=first.scene_version_id,
        )
        plan = drama_render_store.load_fresh_render_plan("source-race")
        mapping = {shot.shot_id: "s001" for shot in plan.shots}
        catalog_path = drama_asset_versions.scene_asset_catalog_path("source-race")
        manifest_path = drama_asset_versions.episode_scene_asset_manifest_path(
            "source-race"
        )
        original_write = drama_asset_versions._write_envelope

        def mutate_catalog_then_write(*args, **kwargs):
            catalog_path.write_bytes(self._catalog_bytes(changed))
            return original_write(*args, **kwargs)

        with patch(
            "src.drama_asset_versions._write_envelope",
            side_effect=mutate_catalog_then_write,
        ):
            with self.assertRaisesRegex(
                drama_asset_versions.DramaAssetStoreError,
                "sources changed concurrently",
            ):
                drama_asset_versions.create_episode_scene_asset_manifest(
                    "source-race",
                    shot_scene_ids=mapping,
                )
        self.assertFalse(manifest_path.exists())

    def test_duplicate_key_catalog_is_invalid_and_preserved(self) -> None:
        self._seed("duplicate", assembled=False)
        path = drama_asset_versions.scene_asset_catalog_path("duplicate")
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = (
            '{"schema_version":1,"schema_version":1,'
            '"artifact_type":"drama_scene_asset_catalog",'
            '"catalog_fingerprint":"' + ("0" * 64) + '","catalog":{}}'
        ).encode("utf-8")
        path.write_bytes(payload)
        before = path.read_bytes()
        self.assertEqual(
            drama_asset_versions.inspect_scene_asset_catalog("duplicate").state,
            "invalid",
        )
        version = self._version("duplicate", "s001", "天台")
        with self.assertRaisesRegex(
            drama_asset_versions.DramaAssetStoreError,
            "invalid scene catalog",
        ):
            drama_asset_versions.create_scene_asset_catalog(
                "duplicate",
                version=version,
            )
        self.assertEqual(path.read_bytes(), before)

    def test_invalid_scene_manifest_is_preserved_and_never_replaced(self) -> None:
        self._seed("invalid-manifest")
        version = self._version("invalid-manifest", "s001", "天台")
        drama_asset_versions.create_scene_asset_catalog(
            "invalid-manifest", version=version
        )
        path = drama_asset_versions.episode_scene_asset_manifest_path(
            "invalid-manifest"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = (
            '{"schema_version":1,"schema_version":1,'
            '"artifact_type":"drama_episode_scene_asset_manifest",'
            '"manifest_fingerprint":"' + ("0" * 64) + '","manifest":{}}'
        ).encode("utf-8")
        path.write_bytes(payload)
        before = path.read_bytes()
        self.assertEqual(
            drama_asset_versions.inspect_episode_scene_asset_manifest(
                "invalid-manifest"
            ).state,
            "invalid",
        )
        plan = drama_render_store.load_fresh_render_plan("invalid-manifest")
        mapping = {shot.shot_id: "s001" for shot in plan.shots}
        with self.assertRaisesRegex(
            drama_asset_versions.DramaAssetStoreError,
            "invalid scene manifest",
        ):
            drama_asset_versions.create_episode_scene_asset_manifest(
                "invalid-manifest",
                shot_scene_ids=mapping,
                replace_stale=True,
                expected_manifest_fingerprint="0" * 64,
            )
        self.assertEqual(path.read_bytes(), before)

    def test_shot_reorder_preserves_explicit_scene_identity(self) -> None:
        self._seed("reorder")
        catalog, _first, _second = self._catalog_with_two("reorder")
        plan = drama_render_store.load_fresh_render_plan("reorder")
        mapping = {
            shot.shot_id: ("s001" if index % 2 == 0 else "s002")
            for index, shot in enumerate(plan.shots)
        }
        original = drama_assets.build_episode_scene_asset_manifest(
            plan,
            catalog,
            shot_scene_ids=mapping,
        )
        raw = model_to_dict(plan)
        raw["shots"] = list(reversed(raw["shots"]))
        segments = {
            segment["segment_id"]: segment for segment in raw["spoken_segments"]
        }
        reordered_segments = []
        sequence = 1
        for shot in raw["shots"]:
            for segment_id in shot["spoken_segment_ids"]:
                segment = dict(segments[segment_id])
                segment["sequence"] = sequence
                reordered_segments.append(segment)
                sequence += 1
        raw["spoken_segments"] = reordered_segments
        unsigned = {key: value for key, value in raw.items() if key != "plan_fingerprint"}
        raw["plan_fingerprint"] = hashlib.sha256(
            json.dumps(
                unsigned,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        reordered = RenderPlan(**raw)
        rebound = drama_assets.build_episode_scene_asset_manifest(
            reordered,
            catalog,
            shot_scene_ids=mapping,
        )
        self.assertEqual(
            {
                row.shot_id: row.scene_ref.scene_id
                for row in original.shot_scene_refs
            },
            {
                row.shot_id: row.scene_ref.scene_id
                for row in rebound.shot_scene_refs
            },
        )
        self.assertEqual(
            [row.shot_id for row in rebound.shot_scene_refs],
            [shot.shot_id for shot in reordered.shots],
        )

    def test_artifact_symlink_and_catalog_target_symlink_are_rejected(self) -> None:
        self._seed("symlink", assembled=False)
        root = paths.workspace_root("symlink")
        outside = Path(self._tmp.name) / "outside.bin"
        outside.write_bytes(b"outside")
        artifact_path = root / "data" / "scene_refs" / "s001" / "ref.png"
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        artifact_path.symlink_to(outside)
        version = drama_assets.build_scene_asset_version(
            scene_id="s001",
            spec=self._spec("天台"),
            source_kind="identity_snapshot",
            artifact={
                "path": "data/scene_refs/s001/ref.png",
                "sha256": hashlib.sha256(outside.read_bytes()).hexdigest(),
                "size_bytes": outside.stat().st_size,
            },
        )
        with self.assertRaises((ValueError, OSError)):
            drama_asset_versions.create_scene_asset_catalog(
                "symlink",
                version=version,
            )
        self.assertEqual(outside.read_bytes(), b"outside")

        artifact_path.unlink()
        metadata = self._version("symlink", "s001", "天台")
        target = drama_asset_versions.scene_asset_catalog_path("symlink")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(outside)
        with self.assertRaises(drama_asset_versions.DramaAssetStoreError):
            drama_asset_versions.create_scene_asset_catalog(
                "symlink",
                version=metadata,
            )
        self.assertEqual(outside.read_bytes(), b"outside")

    def test_create_idempotence_is_only_the_original_root_version(self) -> None:
        self._seed("create-scope", assembled=False)
        first = self._version("create-scope", "s001", "天台")
        catalog = drama_asset_versions.create_scene_asset_catalog(
            "create-scope", version=first
        )
        second = self._version("create-scope", "s002", "办公室")
        catalog = drama_asset_versions.add_scene_asset(
            "create-scope",
            version=second,
            expected_catalog_fingerprint=catalog.catalog_fingerprint,
        )
        candidate = self._version(
            "create-scope",
            "s001",
            "暴雨天台",
            derived_from=first.scene_version_id,
        )
        drama_asset_versions.append_scene_asset_version(
            "create-scope",
            scene_id="s001",
            version=candidate,
            expected_catalog_fingerprint=catalog.catalog_fingerprint,
        )
        for replay in (second, candidate):
            with self.assertRaisesRegex(
                drama_asset_versions.DramaAssetStoreError,
                "already exists",
            ):
                drama_asset_versions.create_scene_asset_catalog(
                    "create-scope", version=replay
                )

    def test_same_artifact_path_cannot_be_reused_for_different_bytes(self) -> None:
        self._seed("path-reuse", assembled=False)
        first = self._version("path-reuse", "s001", "天台", artifact=True)
        catalog = drama_asset_versions.create_scene_asset_catalog(
            "path-reuse", version=first
        )
        artifact_path = paths.workspace_root("path-reuse") / first.artifact.path
        replacement = b"different immutable bytes"
        artifact_path.write_bytes(replacement)
        candidate = drama_assets.build_scene_asset_version(
            scene_id="s001",
            spec=self._spec("新天台"),
            source_kind="appended_candidate",
            derived_from=first.scene_version_id,
            artifact={
                "path": first.artifact.path,
                "sha256": hashlib.sha256(replacement).hexdigest(),
                "size_bytes": len(replacement),
            },
        )
        before = drama_asset_versions.scene_asset_catalog_path("path-reuse").read_bytes()
        with self.assertRaisesRegex(
            drama_asset_versions.DramaAssetStoreError,
            "candidate append was rejected",
        ):
            drama_asset_versions.append_scene_asset_version(
                "path-reuse",
                scene_id="s001",
                version=candidate,
                expected_catalog_fingerprint=catalog.catalog_fingerprint,
            )
        self.assertEqual(
            drama_asset_versions.scene_asset_catalog_path("path-reuse").read_bytes(),
            before,
        )

    def test_public_errors_redact_spec_path_lock_and_duplicate_pair_inputs(self) -> None:
        self._seed("redaction", assembled=False)
        secret = "SECRET_VISUAL_TOKEN_109"
        invalid = {
            "scene_id": "s001",
            "scene_version_id": "sv_" + "1" * 24,
            "derived_from": None,
            "source_kind": "identity_snapshot",
            "source_fingerprint": "1" * 64,
            "version_fingerprint": "2" * 64,
            "spec": {**self._spec("秘密"), "visual_tokens": [secret, secret]},
            "artifact": {
                "path": "data/scene_refs/s001/SECRET_PATH.png",
                "sha256": "3" * 64,
                "size_bytes": 1,
            },
        }
        with self.assertRaises(drama_asset_versions.DramaAssetStoreError) as caught:
            drama_asset_versions.create_scene_asset_catalog(
                "redaction", version=invalid
            )
        rendered = f"{caught.exception!s} {caught.exception!r}"
        self.assertNotIn(secret, rendered)
        self.assertNotIn("SECRET_PATH", rendered)
        self.assertIsNone(caught.exception.__cause__)
        self.assertIsNone(caught.exception.__context__)

        version = self._version("redaction", "s001", "天台")
        with patch(
            "src.drama_asset_versions.acquire_write_lock",
            side_effect=WorkspaceLocked("SECRET_HOLDER /SECRET/LOCK/PATH"),
        ):
            with self.assertRaises(drama_asset_versions.DramaAssetStoreError) as locked:
                drama_asset_versions.create_scene_asset_catalog(
                    "redaction", version=version
                )
        self.assertNotIn("SECRET", str(locked.exception))
        self.assertIsNone(locked.exception.__context__)

        self._seed("duplicate-pairs")
        drama_asset_versions.create_scene_asset_catalog(
            "duplicate-pairs",
            version=self._version("duplicate-pairs", "s001", "天台"),
        )
        plan = drama_render_store.load_fresh_render_plan("duplicate-pairs")
        pairs = [(shot.shot_id, "s001") for shot in plan.shots]
        pairs.append((plan.shots[0].shot_id, "s999"))
        with self.assertRaisesRegex(
            drama_asset_versions.DramaAssetStoreError,
            "manifest update was rejected",
        ):
            drama_asset_versions.create_episode_scene_asset_manifest(
                "duplicate-pairs", shot_scene_ids=pairs
            )

    def test_artifact_missing_fifo_directory_and_oversize_are_rejected(self) -> None:
        for kind in ("missing", "fifo", "directory", "oversize"):
            name = f"artifact-{kind}"
            self._seed(name, assembled=False)
            root = paths.workspace_root(name)
            rel = "data/scene_refs/s001/ref.png"
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            size = 1
            if kind == "fifo":
                os.mkfifo(target)
            elif kind == "directory":
                target.mkdir()
            elif kind == "oversize":
                target.write_bytes(
                    b"x" * (drama_asset_versions.MAX_SCENE_ARTIFACT_BYTES + 1)
                )
            version = drama_assets.build_scene_asset_version(
                scene_id="s001",
                spec=self._spec("天台"),
                source_kind="identity_snapshot",
                artifact={
                    "path": rel,
                    "sha256": "1" * 64,
                    "size_bytes": size,
                },
            )
            with self.assertRaises(drama_asset_versions.DramaAssetStoreError):
                drama_asset_versions.create_scene_asset_catalog(name, version=version)
            self.assertFalse(
                drama_asset_versions.scene_asset_catalog_path(name).exists()
            )

    def test_scene_missing_invalid_and_blocked_source_states(self) -> None:
        self._seed("states", assembled=False)
        self.assertEqual(
            drama_asset_versions.inspect_scene_asset_catalog("states").state,
            "needs_scene_catalog",
        )
        self.assertEqual(
            drama_asset_versions.inspect_episode_scene_asset_manifest("states").state,
            "blocked_source",
        )
        self._seed("states-ready")
        first = self._version("states-ready", "s001", "天台")
        drama_asset_versions.create_scene_asset_catalog("states-ready", version=first)
        self.assertEqual(
            drama_asset_versions.inspect_episode_scene_asset_manifest(
                "states-ready"
            ).state,
            "needs_scene_manifest",
        )
        path = drama_asset_versions.scene_asset_catalog_path("states-ready")
        for payload in (
            '{"x":NaN}',
            '{"x":Infinity}',
            '{"x":' * 1100 + "0" + "}" * 1100,
        ):
            path.write_text(payload, encoding="utf-8")
            self.assertEqual(
                drama_asset_versions.inspect_scene_asset_catalog(
                    "states-ready"
                ).state,
                "invalid",
            )
        self.assertEqual(
            drama_asset_versions.inspect_episode_scene_asset_manifest(
                "states-ready"
            ).state,
            "blocked_source",
        )

    def test_art_direction_change_propagates_through_render_plan_to_scene_manifest(self) -> None:
        name = "art-propagation"
        self._seed(name, assembled=False)
        write_json(
            episode_paths(name).review_path,
            drama_reviewer.run(name, mock=True),
        )
        drama_store.assemble_episode(name)
        art = drama_art_direction_store.create_art_direction_catalog(
            name,
            art_direction_id="season_default",
            spec={
                "preset": "cinematic",
                "positive_tokens": ["ink wash"],
                "negative_tokens": ["watermark"],
                "palette": ["#112233"],
                "aspect_ratio": "9:16",
            },
            source_kind="preset",
        )
        drama_render_store.create_render_plan(name)
        scene = self._version(name, "s001", "天台")
        drama_asset_versions.create_scene_asset_catalog(name, version=scene)
        plan = drama_render_store.load_fresh_render_plan(name)
        mapping = {shot.shot_id: "s001" for shot in plan.shots}
        manifest = drama_asset_versions.create_episode_scene_asset_manifest(
            name, shot_scene_ids=mapping
        )

        appended = drama_art_direction_store.append_art_direction_candidate(
            name,
            spec={
                "preset": "graphic-novel",
                "positive_tokens": ["ink wash"],
                "negative_tokens": ["watermark"],
                "palette": ["#112233"],
                "aspect_ratio": "9:16",
            },
            source_kind="manual",
            derived_from=art.selected_version_id,
            expected_catalog_fingerprint=art.catalog_fingerprint,
        )
        drama_art_direction_store.select_art_direction_version(
            name,
            version_id=appended.versions[-1].version_id,
            expected_selection_revision=0,
            expected_selected_version_id=art.selected_version_id,
        )
        self.assertEqual(drama_render_store.inspect_render_plan(name).state, "stale")
        self.assertEqual(
            drama_asset_versions.inspect_episode_scene_asset_manifest(name).state,
            "stale",
        )
        drama_render_store.create_render_plan(name, replace_stale=True)
        self.assertEqual(drama_render_store.inspect_render_plan(name).state, "fresh")
        self.assertEqual(
            drama_asset_versions.inspect_episode_scene_asset_manifest(name).state,
            "stale",
        )
        drama_asset_versions.create_episode_scene_asset_manifest(
            name,
            replace_stale=True,
            expected_manifest_fingerprint=manifest.manifest_fingerprint,
        )
        self.assertEqual(
            drama_asset_versions.inspect_episode_scene_asset_manifest(name).state,
            "fresh",
        )

    def test_late_target_cas_and_parent_symlink_preserve_external_bytes(self) -> None:
        self._seed("late-cas", assembled=False)
        version = self._version("late-cas", "s001", "天台")
        with patch(
            "src.drama_asset_versions._target_token_at",
            side_effect=[("missing",), ("file", 1, "changed")],
        ):
            with self.assertRaisesRegex(
                drama_asset_versions.DramaAssetStoreError,
                "changed concurrently",
            ):
                drama_asset_versions.create_scene_asset_catalog(
                    "late-cas", version=version
                )
        self.assertFalse(
            drama_asset_versions.scene_asset_catalog_path("late-cas").exists()
        )

        self._seed("parent-link", assembled=False)
        root = paths.workspace_root("parent-link")
        external = Path(self._tmp.name) / "external-assets"
        external.mkdir()
        marker = external / "marker"
        marker.write_bytes(b"outside")
        data_dir = root / "data"
        data_dir.mkdir(exist_ok=True)
        assets_dir = data_dir / "assets"
        assets_dir.symlink_to(external, target_is_directory=True)
        version = self._version("parent-link", "s001", "天台")
        with self.assertRaises(drama_asset_versions.DramaAssetStoreError):
            drama_asset_versions.create_scene_asset_catalog(
                "parent-link", version=version
            )
        self.assertEqual(marker.read_bytes(), b"outside")
        self.assertFalse((external / "season_01.scene_assets.json").exists())


if __name__ == "__main__":
    import unittest

    unittest.main()
