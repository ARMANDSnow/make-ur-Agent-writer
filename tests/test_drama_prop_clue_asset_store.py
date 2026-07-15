"""iter110: strict prop/clue catalog and episode manifest persistence."""

from __future__ import annotations

import hashlib
import json
import os
import socket
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
from src.drama_schemas import character_paths, episode_paths
from src.schemas import model_to_dict
from src.utils import write_json
from tests._drama_base import DramaTestBase


class DramaPropClueAssetStoreTests(DramaTestBase):
    def _seed(self, name: str = "props", *, assembled: bool = True) -> None:
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
    def _spec(kind: str, name: str, *, state_label: str = "完好") -> dict:
        return {
            "kind": kind,
            "display_name": name,
            "owner_character_id": "c001",
            "state_label": state_label,
            "first_seen_episode_no": 1,
            "visual_tokens": ["特写", "低饱和"],
        }

    def _version(
        self,
        workspace: str,
        asset_id: str,
        kind: str,
        name: str,
        *,
        state_label: str = "完好",
        derived_from: str | None = None,
        artifact: bool = False,
    ):
        record = None
        if artifact:
            root = paths.workspace_root(workspace)
            filename = hashlib.sha256(name.encode("utf-8")).hexdigest()[:12]
            rel = f"data/prop_clue_refs/{asset_id}/ref_{filename}.png"
            path = root / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = f"prop-clue:{asset_id}:{name}".encode("utf-8")
            path.write_bytes(payload)
            record = {
                "path": rel,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "size_bytes": len(payload),
            }
        return drama_assets.build_prop_or_clue_asset_version(
            asset_id=asset_id,
            spec=self._spec(kind, name, state_label=state_label),
            source_kind=(
                "identity_snapshot" if derived_from is None else "appended_candidate"
            ),
            artifact=record,
            derived_from=derived_from,
        )

    def _catalog_with_two(self, name: str = "props"):
        catalog = drama_asset_versions.create_prop_or_clue_asset_catalog(name)
        prop = self._version(name, "p001", "prop", "旧怀表")
        catalog = drama_asset_versions.add_prop_or_clue_asset(
            name,
            version=prop,
            expected_catalog_fingerprint=catalog.catalog_fingerprint,
        )
        clue = self._version(name, "l001", "clue", "密室钥匙")
        catalog = drama_asset_versions.add_prop_or_clue_asset(
            name,
            version=clue,
            expected_catalog_fingerprint=catalog.catalog_fingerprint,
        )
        return catalog, prop, clue

    @staticmethod
    def _catalog_bytes(catalog) -> bytes:
        return (
            json.dumps(
                {
                    "schema_version": 1,
                    "artifact_type": "drama_prop_clue_asset_catalog",
                    "catalog_fingerprint": catalog.catalog_fingerprint,
                    "catalog": model_to_dict(catalog),
                },
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")

    def test_empty_catalog_and_all_empty_manifest_are_valid_and_offline(self) -> None:
        self._seed("empty")
        with patch.object(socket, "socket", side_effect=AssertionError("network")):
            catalog = drama_asset_versions.create_prop_or_clue_asset_catalog("empty")
            self.assertEqual(catalog.assets, [])
            plan = drama_render_store.load_fresh_render_plan("empty")
            mapping = {shot.shot_id: [] for shot in plan.shots}
            manifest = (
                drama_asset_versions.create_episode_prop_or_clue_asset_manifest(
                    "empty",
                    shot_asset_ids=mapping,
                )
            )
        self.assertTrue(all(not item.asset_refs for item in manifest.shot_asset_refs))
        self.assertEqual(drama_assets.prop_or_clue_usage_index(manifest), {})
        self.assertEqual(
            drama_asset_versions.inspect_episode_prop_or_clue_asset_manifest(
                "empty"
            ).state,
            "fresh",
        )

    def test_catalog_store_is_idempotent_append_only_and_double_cas(self) -> None:
        self._seed("catalog", assembled=False)
        catalog = drama_asset_versions.create_prop_or_clue_asset_catalog("catalog")
        path = drama_asset_versions.prop_or_clue_asset_catalog_path("catalog")
        before = path.read_bytes()
        mtime = path.stat().st_mtime_ns
        self.assertEqual(
            drama_asset_versions.create_prop_or_clue_asset_catalog("catalog"),
            catalog,
        )
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(path.stat().st_mtime_ns, mtime)

        first = self._version("catalog", "p001", "prop", "旧怀表", artifact=True)
        catalog = drama_asset_versions.add_prop_or_clue_asset(
            "catalog",
            version=first,
            expected_catalog_fingerprint=catalog.catalog_fingerprint,
        )
        candidate = self._version(
            "catalog",
            "p001",
            "prop",
            "旧怀表",
            state_label="停走",
            derived_from=first.asset_version_id,
        )
        appended = drama_asset_versions.append_prop_or_clue_asset_version(
            "catalog",
            asset_id="p001",
            version=candidate,
            expected_catalog_fingerprint=catalog.catalog_fingerprint,
        )
        self.assertEqual(appended.assets[0].selected_version_id, first.asset_version_id)
        selected = drama_asset_versions.select_prop_or_clue_asset_version(
            "catalog",
            asset_id="p001",
            asset_version_id=candidate.asset_version_id,
            expected_selection_revision=0,
            expected_selected_version_id=first.asset_version_id,
        )
        returned = drama_asset_versions.select_prop_or_clue_asset_version(
            "catalog",
            asset_id="p001",
            asset_version_id=first.asset_version_id,
            expected_selection_revision=1,
            expected_selected_version_id=candidate.asset_version_id,
        )
        self.assertEqual(returned.assets[0].selection_revision, 2)
        evolved_bytes = path.read_bytes()
        evolved_mtime = path.stat().st_mtime_ns
        self.assertEqual(
            drama_asset_versions.add_prop_or_clue_asset(
                "catalog",
                version=first,
                expected_catalog_fingerprint=returned.catalog_fingerprint,
            ),
            returned,
        )
        self.assertEqual(path.read_bytes(), evolved_bytes)
        self.assertEqual(path.stat().st_mtime_ns, evolved_mtime)
        with self.assertRaisesRegex(ValueError, "selection was rejected"):
            drama_asset_versions.select_prop_or_clue_asset_version(
                "catalog",
                asset_id="p001",
                asset_version_id=candidate.asset_version_id,
                expected_selection_revision=0,
                expected_selected_version_id=first.asset_version_id,
            )
        self.assertEqual(selected.assets[0].selection_revision, 1)

    def test_manifest_zero_to_many_used_by_and_precise_stale(self) -> None:
        self._seed("manifest")
        catalog, prop, clue = self._catalog_with_two("manifest")
        plan = drama_render_store.load_fresh_render_plan("manifest")
        mapping = {shot.shot_id: [] for shot in plan.shots}
        mapping[plan.shots[0].shot_id] = ["p001", "l001"]
        if len(plan.shots) > 1:
            mapping[plan.shots[1].shot_id] = ["p001"]
        manifest = drama_asset_versions.create_episode_prop_or_clue_asset_manifest(
            "manifest",
            shot_asset_ids=mapping,
        )
        usage = drama_assets.prop_or_clue_usage_index(manifest)
        self.assertEqual(usage["p001"][0], plan.shots[0].shot_id)
        self.assertEqual(usage["l001"], [plan.shots[0].shot_id])

        candidate = self._version(
            "manifest",
            "p001",
            "prop",
            "旧怀表",
            state_label="停走",
            derived_from=prop.asset_version_id,
        )
        catalog = drama_asset_versions.append_prop_or_clue_asset_version(
            "manifest",
            asset_id="p001",
            version=candidate,
            expected_catalog_fingerprint=catalog.catalog_fingerprint,
        )
        self.assertEqual(
            drama_asset_versions.inspect_episode_prop_or_clue_asset_manifest(
                "manifest"
            ).state,
            "fresh",
        )

        unused = self._version("manifest", "p002", "prop", "旧雨伞")
        catalog = drama_asset_versions.add_prop_or_clue_asset(
            "manifest",
            version=unused,
            expected_catalog_fingerprint=catalog.catalog_fingerprint,
        )
        unused_candidate = self._version(
            "manifest",
            "p002",
            "prop",
            "旧雨伞",
            state_label="折断",
            derived_from=unused.asset_version_id,
        )
        catalog = drama_asset_versions.append_prop_or_clue_asset_version(
            "manifest",
            asset_id="p002",
            version=unused_candidate,
            expected_catalog_fingerprint=catalog.catalog_fingerprint,
        )
        catalog = drama_asset_versions.select_prop_or_clue_asset_version(
            "manifest",
            asset_id="p002",
            asset_version_id=unused_candidate.asset_version_id,
            expected_selection_revision=0,
            expected_selected_version_id=unused.asset_version_id,
        )
        self.assertEqual(
            drama_asset_versions.inspect_episode_prop_or_clue_asset_manifest(
                "manifest"
            ).state,
            "fresh",
        )

        drama_asset_versions.select_prop_or_clue_asset_version(
            "manifest",
            asset_id="p001",
            asset_version_id=candidate.asset_version_id,
            expected_selection_revision=0,
            expected_selected_version_id=prop.asset_version_id,
        )
        self.assertEqual(
            drama_asset_versions.inspect_episode_prop_or_clue_asset_manifest(
                "manifest"
            ).state,
            "stale",
        )
        self.assertEqual(drama_render_store.inspect_render_plan("manifest").state, "fresh")
        refreshed = (
            drama_asset_versions.create_episode_prop_or_clue_asset_manifest(
                "manifest",
                replace_stale=True,
                expected_manifest_fingerprint=manifest.manifest_fingerprint,
            )
        )
        self.assertEqual(refreshed.binding_revision, manifest.binding_revision)
        self.assertEqual(
            drama_asset_versions.inspect_episode_prop_or_clue_asset_manifest(
                "manifest"
            ).state,
            "fresh",
        )
        self.assertEqual(
            refreshed.shot_asset_refs[0].asset_refs[1].asset_version_id,
            clue.asset_version_id,
        )

    def test_manifest_requires_complete_bounded_mapping_and_replacement_cas(self) -> None:
        self._seed("binding")
        self._catalog_with_two("binding")
        plan = drama_render_store.load_fresh_render_plan("binding")
        with self.assertRaisesRegex(ValueError, "explicit shot prop/clue bindings"):
            drama_asset_versions.create_episode_prop_or_clue_asset_manifest("binding")
        with self.assertRaisesRegex(ValueError, "manifest update was rejected"):
            drama_asset_versions.create_episode_prop_or_clue_asset_manifest(
                "binding",
                shot_asset_ids={plan.shots[0].shot_id: ["p001"]},
            )
        tuple_mapping = {shot.shot_id: [] for shot in plan.shots}
        tuple_mapping[plan.shots[0].shot_id] = ("p001",)
        with self.assertRaisesRegex(ValueError, "manifest update was rejected"):
            drama_asset_versions.create_episode_prop_or_clue_asset_manifest(
                "binding",
                shot_asset_ids=tuple_mapping,
            )

        class OversizedMapping(dict):
            def __len__(self) -> int:
                return 101

            def items(self):
                raise AssertionError("oversized mapping must be rejected before iteration")

        with self.assertRaisesRegex(ValueError, "manifest update was rejected"):
            drama_asset_versions.create_episode_prop_or_clue_asset_manifest(
                "binding",
                shot_asset_ids=OversizedMapping(),
            )
        mapping = {shot.shot_id: [] for shot in plan.shots}
        mapping[plan.shots[0].shot_id] = ["p001", "l001"]
        manifest = drama_asset_versions.create_episode_prop_or_clue_asset_manifest(
            "binding",
            shot_asset_ids=mapping,
        )
        duplicate = {key: list(value) for key, value in mapping.items()}
        duplicate[plan.shots[0].shot_id] = ["p001", "p001"]
        with self.assertRaisesRegex(ValueError, "manifest update was rejected"):
            drama_asset_versions.create_episode_prop_or_clue_asset_manifest(
                "binding",
                shot_asset_ids=duplicate,
                replace_stale=True,
                expected_manifest_fingerprint=manifest.manifest_fingerprint,
            )
        too_many = {key: list(value) for key, value in mapping.items()}
        too_many[plan.shots[0].shot_id] = [f"p{index:03d}" for index in range(1, 18)]
        with self.assertRaises(ValueError):
            drama_asset_versions.create_episode_prop_or_clue_asset_manifest(
                "binding",
                shot_asset_ids=too_many,
                replace_stale=True,
                expected_manifest_fingerprint=manifest.manifest_fingerprint,
            )
        changed = {key: list(value) for key, value in mapping.items()}
        changed[plan.shots[0].shot_id] = ["l001"]
        with self.assertRaisesRegex(ValueError, "replacement must be explicit"):
            drama_asset_versions.create_episode_prop_or_clue_asset_manifest(
                "binding",
                shot_asset_ids=changed,
            )
        replaced = drama_asset_versions.create_episode_prop_or_clue_asset_manifest(
            "binding",
            shot_asset_ids=changed,
            replace_stale=True,
            expected_manifest_fingerprint=manifest.manifest_fingerprint,
        )
        self.assertEqual(replaced.binding_revision, 1)
        with self.assertRaisesRegex(ValueError, "changed; refresh"):
            drama_asset_versions.create_episode_prop_or_clue_asset_manifest(
                "binding",
                shot_asset_ids=mapping,
                replace_stale=True,
                expected_manifest_fingerprint=manifest.manifest_fingerprint,
            )

    def test_used_artifact_tamper_stales_and_idempotent_add_revalidates(self) -> None:
        self._seed("artifact")
        catalog = drama_asset_versions.create_prop_or_clue_asset_catalog("artifact")
        version = self._version(
            "artifact",
            "p001",
            "prop",
            "旧怀表",
            artifact=True,
        )
        catalog = drama_asset_versions.add_prop_or_clue_asset(
            "artifact",
            version=version,
            expected_catalog_fingerprint=catalog.catalog_fingerprint,
        )
        plan = drama_render_store.load_fresh_render_plan("artifact")
        mapping = {shot.shot_id: [] for shot in plan.shots}
        mapping[plan.shots[0].shot_id] = ["p001"]
        drama_asset_versions.create_episode_prop_or_clue_asset_manifest(
            "artifact",
            shot_asset_ids=mapping,
        )
        target = paths.workspace_root("artifact") / version.artifact.path
        target.write_bytes(b"tampered")
        self.assertEqual(
            drama_asset_versions.inspect_episode_prop_or_clue_asset_manifest(
                "artifact"
            ).state,
            "stale",
        )
        with self.assertRaisesRegex(ValueError, "artifact does not match"):
            drama_asset_versions.add_prop_or_clue_asset(
                "artifact",
                version=version,
                expected_catalog_fingerprint=catalog.catalog_fingerprint,
            )

    def test_art_direction_change_propagates_via_render_plan(self) -> None:
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
        catalog = drama_asset_versions.create_prop_or_clue_asset_catalog(name)
        prop = self._version(name, "p001", "prop", "旧怀表")
        drama_asset_versions.add_prop_or_clue_asset(
            name,
            version=prop,
            expected_catalog_fingerprint=catalog.catalog_fingerprint,
        )
        plan = drama_render_store.load_fresh_render_plan(name)
        mapping = {shot.shot_id: [] for shot in plan.shots}
        mapping[plan.shots[0].shot_id] = ["p001"]
        manifest = drama_asset_versions.create_episode_prop_or_clue_asset_manifest(
            name,
            shot_asset_ids=mapping,
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
            drama_asset_versions.inspect_episode_prop_or_clue_asset_manifest(name).state,
            "stale",
        )
        drama_render_store.create_render_plan(name, replace_stale=True)
        drama_asset_versions.create_episode_prop_or_clue_asset_manifest(
            name,
            replace_stale=True,
            expected_manifest_fingerprint=manifest.manifest_fingerprint,
        )
        self.assertEqual(
            drama_asset_versions.inspect_episode_prop_or_clue_asset_manifest(name).state,
            "fresh",
        )

    def test_invalid_duplicate_json_symlink_and_late_cas_fail_closed(self) -> None:
        self._seed("invalid", assembled=False)
        path = drama_asset_versions.prop_or_clue_asset_catalog_path("invalid")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            '{"schema_version":1,"schema_version":1}',
            encoding="utf-8",
        )
        self.assertEqual(
            drama_asset_versions.inspect_prop_or_clue_asset_catalog("invalid").state,
            "invalid",
        )
        with self.assertRaisesRegex(ValueError, "repaired explicitly"):
            drama_asset_versions.create_prop_or_clue_asset_catalog("invalid")

        self._seed("symlink", assembled=False)
        target = drama_asset_versions.prop_or_clue_asset_catalog_path("symlink")
        target.parent.mkdir(parents=True, exist_ok=True)
        external = paths.workspace_root("symlink") / "external.json"
        external.write_text("outside", encoding="utf-8")
        target.symlink_to(external)
        with self.assertRaises(ValueError):
            drama_asset_versions.create_prop_or_clue_asset_catalog("symlink")
        self.assertEqual(external.read_text(encoding="utf-8"), "outside")

        self._seed("late-cas", assembled=False)
        with patch(
            "src.drama_asset_versions._target_token_at",
            side_effect=[("missing",), ("file", 1, "changed")],
        ):
            with self.assertRaisesRegex(ValueError, "changed concurrently"):
                drama_asset_versions.create_prop_or_clue_asset_catalog("late-cas")
        self.assertFalse(
            drama_asset_versions.prop_or_clue_asset_catalog_path("late-cas").exists()
        )

    def test_nonfinite_deep_and_oversize_catalog_json_are_invalid(self) -> None:
        self._seed("json-matrix", assembled=False)
        path = drama_asset_versions.prop_or_clue_asset_catalog_path("json-matrix")
        path.parent.mkdir(parents=True, exist_ok=True)
        payloads = [
            b'{"schema_version":1,"value":NaN}',
            ("[" * 300 + "0" + "]" * 300).encode("utf-8"),
            b"x" * (drama_asset_versions.MAX_PROP_CLUE_CATALOG_BYTES + 1),
        ]
        for payload in payloads:
            path.write_bytes(payload)
            self.assertEqual(
                drama_asset_versions.inspect_prop_or_clue_asset_catalog(
                    "json-matrix"
                ).state,
                "invalid",
            )

    def test_artifact_symlink_fifo_directory_and_oversize_are_rejected(self) -> None:
        cases = ("symlink", "fifo", "directory", "oversize")
        for case in cases:
            name = f"artifact-{case}"
            self._seed(name, assembled=False)
            catalog = drama_asset_versions.create_prop_or_clue_asset_catalog(name)
            root = paths.workspace_root(name)
            rel = "data/prop_clue_refs/p001/ref.png"
            target = root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            if case == "symlink":
                external = root / "external.png"
                payload = b"external"
                external.write_bytes(payload)
                target.symlink_to(external)
                record = {
                    "path": rel,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "size_bytes": len(payload),
                }
            elif case == "fifo":
                os.mkfifo(target)
                record = {
                    "path": rel,
                    "sha256": hashlib.sha256(b"x").hexdigest(),
                    "size_bytes": 1,
                }
            elif case == "directory":
                target.mkdir()
                record = {
                    "path": rel,
                    "sha256": hashlib.sha256(b"x").hexdigest(),
                    "size_bytes": 1,
                }
            else:
                payload = b"x" * (
                    drama_asset_versions.MAX_PROP_CLUE_ARTIFACT_BYTES + 1
                )
                target.write_bytes(payload)
                record = {
                    "path": rel,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "size_bytes": drama_asset_versions.MAX_PROP_CLUE_ARTIFACT_BYTES,
                }
            version = drama_assets.build_prop_or_clue_asset_version(
                asset_id="p001",
                spec=self._spec("prop", "旧怀表"),
                source_kind="identity_snapshot",
                artifact=record,
            )
            with self.assertRaises(ValueError):
                drama_asset_versions.add_prop_or_clue_asset(
                    name,
                    version=version,
                    expected_catalog_fingerprint=catalog.catalog_fingerprint,
                )
            self.assertEqual(
                drama_asset_versions.load_fresh_prop_or_clue_asset_catalog(name),
                catalog,
            )

    def test_invalid_manifest_and_nonregular_targets_are_preserved(self) -> None:
        self._seed("manifest-invalid")
        drama_asset_versions.create_prop_or_clue_asset_catalog("manifest-invalid")
        plan = drama_render_store.load_fresh_render_plan("manifest-invalid")
        mapping = {shot.shot_id: [] for shot in plan.shots}
        manifest = drama_asset_versions.create_episode_prop_or_clue_asset_manifest(
            "manifest-invalid",
            shot_asset_ids=mapping,
        )
        path = drama_asset_versions.episode_prop_or_clue_asset_manifest_path(
            "manifest-invalid"
        )
        invalid = (
            b'{"schema_version":1,"schema_version":1,'
            b'"artifact_type":"drama_episode_prop_clue_asset_manifest"}'
        )
        path.write_bytes(invalid)
        self.assertEqual(
            drama_asset_versions.inspect_episode_prop_or_clue_asset_manifest(
                "manifest-invalid"
            ).state,
            "invalid",
        )
        with self.assertRaisesRegex(ValueError, "repaired explicitly"):
            drama_asset_versions.create_episode_prop_or_clue_asset_manifest(
                "manifest-invalid",
                shot_asset_ids=mapping,
                replace_stale=True,
                expected_manifest_fingerprint=manifest.manifest_fingerprint,
            )
        self.assertEqual(path.read_bytes(), invalid)

        for kind in ("fifo", "directory"):
            name = f"manifest-{kind}"
            self._seed(name)
            drama_asset_versions.create_prop_or_clue_asset_catalog(name)
            target = drama_asset_versions.episode_prop_or_clue_asset_manifest_path(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            if kind == "fifo":
                os.mkfifo(target)
            else:
                target.mkdir()
            self.assertEqual(
                drama_asset_versions.inspect_episode_prop_or_clue_asset_manifest(
                    name
                ).state,
                "invalid",
            )
            with self.assertRaises(ValueError):
                drama_asset_versions.create_episode_prop_or_clue_asset_manifest(
                    name,
                    shot_asset_ids={
                        shot.shot_id: []
                        for shot in drama_render_store.load_fresh_render_plan(name).shots
                    },
                )

    def test_manifest_source_and_target_precommit_races_leave_no_output(self) -> None:
        self._seed("source-race")
        catalog = drama_asset_versions.create_prop_or_clue_asset_catalog(
            "source-race"
        )
        first = self._version("source-race", "p001", "prop", "旧怀表")
        catalog = drama_asset_versions.add_prop_or_clue_asset(
            "source-race",
            version=first,
            expected_catalog_fingerprint=catalog.catalog_fingerprint,
        )
        candidate = self._version(
            "source-race",
            "p001",
            "prop",
            "旧怀表",
            state_label="停走",
            derived_from=first.asset_version_id,
        )
        catalog = drama_asset_versions.append_prop_or_clue_asset_version(
            "source-race",
            asset_id="p001",
            version=candidate,
            expected_catalog_fingerprint=catalog.catalog_fingerprint,
        )
        changed = drama_assets.select_prop_or_clue_asset_version(
            catalog,
            asset_id="p001",
            asset_version_id=candidate.asset_version_id,
            expected_selection_revision=0,
            expected_selected_version_id=first.asset_version_id,
        )
        plan = drama_render_store.load_fresh_render_plan("source-race")
        mapping = {shot.shot_id: [] for shot in plan.shots}
        mapping[plan.shots[0].shot_id] = ["p001"]
        catalog_path = drama_asset_versions.prop_or_clue_asset_catalog_path(
            "source-race"
        )
        manifest_path = (
            drama_asset_versions.episode_prop_or_clue_asset_manifest_path(
                "source-race"
            )
        )
        original_write = drama_asset_versions._write_envelope

        def mutate_catalog_then_write(*args, **kwargs):
            catalog_path.write_bytes(self._catalog_bytes(changed))
            return original_write(*args, **kwargs)

        with patch(
            "src.drama_asset_versions._write_envelope",
            side_effect=mutate_catalog_then_write,
        ):
            with self.assertRaisesRegex(ValueError, "sources changed concurrently"):
                drama_asset_versions.create_episode_prop_or_clue_asset_manifest(
                    "source-race",
                    shot_asset_ids=mapping,
                )
        self.assertFalse(manifest_path.exists())

        self._seed("manifest-late-cas")
        drama_asset_versions.create_prop_or_clue_asset_catalog("manifest-late-cas")
        late_plan = drama_render_store.load_fresh_render_plan("manifest-late-cas")
        late_mapping = {shot.shot_id: [] for shot in late_plan.shots}
        with patch(
            "src.drama_asset_versions._target_token_at",
            side_effect=[("missing",), ("file", 1, "changed")],
        ):
            with self.assertRaisesRegex(ValueError, "changed concurrently"):
                drama_asset_versions.create_episode_prop_or_clue_asset_manifest(
                    "manifest-late-cas",
                    shot_asset_ids=late_mapping,
                )
        self.assertFalse(
            drama_asset_versions.episode_prop_or_clue_asset_manifest_path(
                "manifest-late-cas"
            ).exists()
        )

    def test_state_matrix_and_public_error_redaction(self) -> None:
        self._seed("states")
        self.assertEqual(
            drama_asset_versions.inspect_prop_or_clue_asset_catalog("states").state,
            "needs_prop_clue_catalog",
        )
        self.assertEqual(
            drama_asset_versions.inspect_episode_prop_or_clue_asset_manifest(
                "states"
            ).state,
            "blocked_source",
        )
        drama_asset_versions.create_prop_or_clue_asset_catalog("states")
        self.assertEqual(
            drama_asset_versions.inspect_episode_prop_or_clue_asset_manifest(
                "states"
            ).state,
            "needs_prop_clue_manifest",
        )

        secret = "SECRET_STORE_PROP_110"
        with self.assertRaises(drama_asset_versions.DramaAssetStoreError) as caught:
            drama_asset_versions.add_prop_or_clue_asset(
                "states",
                version={
                    "asset_id": "p001",
                    "secret": secret,
                },
                expected_catalog_fingerprint="0" * 64,
            )
        rendered = f"{caught.exception!s} {caught.exception!r}"
        self.assertNotIn(secret, rendered)
        self.assertNotIn(str(paths.workspace_root("states")), rendered)


if __name__ == "__main__":
    import unittest

    unittest.main()
