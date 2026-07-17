"""iter128: workspace-local ArtDirection scope resolution and freezing."""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from unittest.mock import patch

from src import (
    character_designer,
    drama_art_direction_scope,
    drama_art_direction_store,
    drama_asset_usage,
    drama_assets,
    drama_render_store,
    drama_reviewer,
    drama_store,
    paths,
    storyboard_builder,
)
from src.drama_schemas import (
    AssetRetirementEntry,
    RenderPlan,
    _canonical_sha256,
    character_paths,
    episode_paths,
)
from src.schemas import model_to_dict
from src.utils import write_json
from tests._drama_base import DramaTestBase


def _spec(preset: str) -> dict:
    return {
        "preset": preset,
        "positive_tokens": ["ink wash", "soft rim light"],
        "negative_tokens": ["watermark"],
        "palette": ["#112233", "#aabbcc"],
        "aspect_ratio": "9:16",
    }


class DramaArtDirectionScopeTests(DramaTestBase):
    def _workspace(self, name: str, *, episode_count: int = 2) -> None:
        self._make_drama_workspace(name, "霸总", episode_count=episode_count)

    def _assembled(self, name: str) -> None:
        self._workspace(name)
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

    def _global(self, name: str, preset: str = "global"):
        return drama_art_direction_scope.create_scoped_art_direction_catalog(
            name,
            scope="global",
            art_direction_id="visual_bible",
            spec=_spec(preset),
            source_kind="manual",
        )

    def _series(self, name: str, preset: str = "series"):
        return drama_art_direction_store.create_art_direction_catalog(
            name,
            art_direction_id="visual_bible",
            spec=_spec(preset),
            source_kind="manual",
        )

    def _episode(self, name: str, preset: str = "episode"):
        return drama_art_direction_scope.create_scoped_art_direction_catalog(
            name,
            scope="episode",
            season_no=1,
            episode_no=1,
            art_direction_id="visual_bible",
            spec=_spec(preset),
            source_kind="manual",
        )

    @staticmethod
    def _write_disabled_version(
        name: str,
        *,
        season_no: int,
        art_direction_id: str,
        version_id: str,
    ) -> None:
        entry = AssetRetirementEntry(
            kind="art_direction",
            asset_id=art_direction_id,
            version_id=version_id,
            status="disabled",
            status_revision=1,
            usage_index_fingerprint="a" * 64,
        )
        state = drama_asset_usage.build_asset_retirement_state(
            season_no=season_no,
            revision=1,
            entries=[entry],
        )
        write_json(
            drama_asset_usage.asset_retirement_state_path(
                name,
                season_no=season_no,
            ),
            {
                "schema_version": 1,
                "artifact_type": "drama_asset_retirement",
                "state_fingerprint": state.state_fingerprint,
                "state": model_to_dict(state),
            },
        )

    @patch.object(socket, "socket", side_effect=AssertionError("network"))
    def test_precedence_and_explicit_clear_are_deterministic(self, _socket) -> None:
        self._workspace("scope-order")
        global_catalog = self._global("scope-order")
        resolved = drama_art_direction_scope.resolve_art_direction("scope-order")
        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.scope, "global")
        self.assertEqual(resolved.source_selection_revision, 0)
        self.assertEqual(resolved.source_scope_revision, 0)
        forged = resolved.model_dump()
        forged["source_selection_revision"] = 1
        forged["resolution_fingerprint"] = _canonical_sha256(
            {
                key: value
                for key, value in forged.items()
                if key != "resolution_fingerprint"
            }
        )
        with self.assertRaisesRegex(
            ValueError,
            "source selection fingerprint is invalid",
        ):
            type(resolved)(**forged)
        self.assertEqual(resolved.ref.version_id, global_catalog.selected_version_id)

        series_catalog = self._series("scope-order")
        resolved = drama_art_direction_scope.resolve_art_direction("scope-order")
        self.assertEqual(resolved.scope, "series")
        self.assertEqual(resolved.source_selection_revision, 0)
        self.assertIsNone(resolved.source_scope_revision)
        self.assertEqual(resolved.ref.version_id, series_catalog.selected_version_id)

        episode_catalog = self._episode("scope-order")
        resolved = drama_art_direction_scope.resolve_art_direction("scope-order")
        self.assertEqual(resolved.scope, "episode")
        self.assertEqual(resolved.source_scope_revision, 0)
        self.assertEqual(resolved.ref.version_id, episode_catalog.selected_version_id)

        cleared = drama_art_direction_scope.set_scoped_art_direction_enabled(
            "scope-order",
            scope="episode",
            season_no=1,
            episode_no=1,
            enabled=False,
            expected_scope_revision=0,
            expected_enabled=True,
        )
        self.assertFalse(cleared.enabled)
        self.assertEqual(cleared.scope_revision, 1)
        resolved = drama_art_direction_scope.resolve_art_direction("scope-order")
        self.assertEqual(resolved.scope, "series")

        disabled_global = drama_art_direction_scope.set_scoped_art_direction_enabled(
            "scope-order",
            scope="global",
            enabled=False,
            expected_scope_revision=0,
            expected_enabled=True,
        )
        self.assertFalse(disabled_global.enabled)
        self.assertEqual(
            drama_art_direction_scope.resolve_art_direction("scope-order").scope,
            "series",
        )

    def test_invalid_high_priority_scope_fails_closed(self) -> None:
        self._workspace("scope-invalid")
        self._global("scope-invalid")
        self._series("scope-invalid")
        self._episode("scope-invalid")
        path = drama_art_direction_scope.scoped_art_direction_catalog_path(
            "scope-invalid",
            scope="episode",
            season_no=1,
            episode_no=1,
        )
        path.write_text('{"x":NaN}', encoding="utf-8")
        with self.assertRaisesRegex(
            drama_art_direction_scope.DramaArtDirectionScopeError,
            "episode art direction source is invalid",
        ):
            drama_art_direction_scope.resolve_art_direction("scope-invalid")

    def test_resolution_rechecks_missing_higher_priority_token(self) -> None:
        self._workspace("scope-resolution-race")
        self._series("scope-resolution-race")
        real_inspect = (
            drama_art_direction_scope.inspect_scoped_art_direction_catalog
        )
        created = False

        def racing_inspect(workspace, *, scope, season_no=None, episode_no=None):
            nonlocal created
            result = real_inspect(
                workspace,
                scope=scope,
                season_no=season_no,
                episode_no=episode_no,
            )
            if scope == "episode" and result.state.startswith("needs") and not created:
                created = True
                with patch.object(
                    drama_art_direction_scope,
                    "inspect_scoped_art_direction_catalog",
                    side_effect=real_inspect,
                ):
                    self._episode("scope-resolution-race")
            return result

        with patch.object(
            drama_art_direction_scope,
            "inspect_scoped_art_direction_catalog",
            side_effect=racing_inspect,
        ):
            with self.assertRaisesRegex(
                drama_art_direction_scope.DramaArtDirectionScopeError,
                "changed concurrently",
            ):
                drama_art_direction_scope.resolve_art_direction(
                    "scope-resolution-race"
                )

    def test_scope_identity_is_strict_and_workspace_local(self) -> None:
        self._workspace("scope-one")
        self._workspace("scope-two")
        first = self._global("scope-one")
        second = self._global("scope-two", "other")
        first_path = drama_art_direction_scope.scoped_art_direction_catalog_path(
            "scope-one",
            scope="global",
        )
        second_path = drama_art_direction_scope.scoped_art_direction_catalog_path(
            "scope-two",
            scope="global",
        )
        self.assertNotEqual(first_path, second_path)
        self.assertNotEqual(first.catalog_fingerprint, second.catalog_fingerprint)
        with self.assertRaises(ValueError):
            drama_art_direction_scope.scoped_art_direction_catalog_path(
                "scope-one",
                scope="global",
                season_no=1,
            )
        with self.assertRaises(ValueError):
            drama_art_direction_scope.scoped_art_direction_catalog_path(
                "scope-one",
                scope="episode",
                season_no=True,
                episode_no=1,
            )
        with self.assertRaises(ValueError):
            drama_art_direction_scope.build_scoped_art_direction_catalog(
                scope="episode",
                season_no=1,
                episode_no=False,
                version=first.versions[0],
            )

    def test_append_select_clear_are_content_addressed_and_double_cas(self) -> None:
        self._workspace("scope-mutate")
        original = self._episode("scope-mutate")
        path = drama_art_direction_scope.scoped_art_direction_catalog_path(
            "scope-mutate",
            scope="episode",
            season_no=1,
            episode_no=1,
        )
        appended = drama_art_direction_scope.append_scoped_art_direction_candidate(
            "scope-mutate",
            scope="episode",
            season_no=1,
            episode_no=1,
            spec=_spec("candidate"),
            source_kind="manual",
            derived_from=original.selected_version_id,
            expected_catalog_fingerprint=original.catalog_fingerprint,
        )
        before = path.read_bytes()
        before_mtime = path.stat().st_mtime_ns
        repeated = drama_art_direction_scope.append_scoped_art_direction_candidate(
            "scope-mutate",
            scope="episode",
            season_no=1,
            episode_no=1,
            spec=_spec("candidate"),
            source_kind="manual",
            derived_from=original.selected_version_id,
            expected_catalog_fingerprint=appended.catalog_fingerprint,
        )
        self.assertEqual(repeated, appended)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(path.stat().st_mtime_ns, before_mtime)

        selected = drama_art_direction_scope.select_scoped_art_direction_version(
            "scope-mutate",
            scope="episode",
            season_no=1,
            episode_no=1,
            version_id=appended.versions[-1].version_id,
            expected_selection_revision=0,
            expected_selected_version_id=original.selected_version_id,
        )
        self.assertEqual(selected.selection_revision, 1)
        with self.assertRaisesRegex(
            drama_art_direction_scope.DramaArtDirectionScopeError,
            "selection changed",
        ):
            drama_art_direction_scope.select_scoped_art_direction_version(
                "scope-mutate",
                scope="episode",
                season_no=1,
                episode_no=1,
                version_id=original.selected_version_id,
                expected_selection_revision=0,
                expected_selected_version_id=original.selected_version_id,
            )

        cleared = drama_art_direction_scope.set_scoped_art_direction_enabled(
            "scope-mutate",
            scope="episode",
            season_no=1,
            episode_no=1,
            enabled=False,
            expected_scope_revision=0,
            expected_enabled=True,
        )
        clear_bytes = path.read_bytes()
        clear_mtime = path.stat().st_mtime_ns
        repeated_clear = drama_art_direction_scope.set_scoped_art_direction_enabled(
            "scope-mutate",
            scope="episode",
            season_no=1,
            episode_no=1,
            enabled=False,
            expected_scope_revision=1,
            expected_enabled=False,
        )
        self.assertEqual(repeated_clear, cleared)
        self.assertEqual(path.read_bytes(), clear_bytes)
        self.assertEqual(path.stat().st_mtime_ns, clear_mtime)

    def test_retirement_guard_binds_episode_season_and_all_global_ledgers(
        self,
    ) -> None:
        self._workspace("scope-retired-create")
        version = drama_assets.build_art_direction_version(
            art_direction_id="visual_bible",
            spec=_spec("retired"),
            source_kind="manual",
        )
        self._write_disabled_version(
            "scope-retired-create",
            season_no=2,
            art_direction_id=version.art_direction_id,
            version_id=version.version_id,
        )
        for scope, kwargs in (
            ("global", {}),
            ("episode", {"season_no": 2, "episode_no": 1}),
        ):
            with self.assertRaisesRegex(
                drama_art_direction_scope.DramaArtDirectionScopeError,
                "creation was rejected",
            ):
                drama_art_direction_scope.create_scoped_art_direction_catalog(
                    "scope-retired-create",
                    scope=scope,
                    art_direction_id=version.art_direction_id,
                    spec=_spec("retired"),
                    source_kind="manual",
                    **kwargs,
                )

        self._workspace("scope-retired-select")
        original = self._global("scope-retired-select")
        appended = (
            drama_art_direction_scope.append_scoped_art_direction_candidate(
                "scope-retired-select",
                scope="global",
                spec=_spec("retired-candidate"),
                source_kind="manual",
                derived_from=original.selected_version_id,
                expected_catalog_fingerprint=original.catalog_fingerprint,
            )
        )
        candidate = appended.versions[-1]
        self._write_disabled_version(
            "scope-retired-select",
            season_no=2,
            art_direction_id=appended.art_direction_id,
            version_id=candidate.version_id,
        )
        with self.assertRaisesRegex(
            drama_art_direction_scope.DramaArtDirectionScopeError,
            "selection was rejected",
        ):
            drama_art_direction_scope.select_scoped_art_direction_version(
                "scope-retired-select",
                scope="global",
                version_id=candidate.version_id,
                expected_selection_revision=0,
                expected_selected_version_id=original.selected_version_id,
            )

    def test_render_plan_freezes_scope_and_only_selected_change_stales(self) -> None:
        self._assembled("scope-render")
        series = self._series("scope-render")
        plan = drama_render_store.create_render_plan("scope-render")
        self.assertEqual(plan.art_direction_resolution.scope, "series")
        self.assertEqual(plan.art_direction_ref, plan.art_direction_resolution.ref)

        appended = drama_art_direction_store.append_art_direction_candidate(
            "scope-render",
            spec=_spec("unselected"),
            source_kind="manual",
            derived_from=series.selected_version_id,
            expected_catalog_fingerprint=series.catalog_fingerprint,
        )
        self.assertEqual(
            drama_render_store.inspect_render_plan("scope-render").state,
            "fresh",
        )
        drama_art_direction_store.select_art_direction_version(
            "scope-render",
            version_id=appended.versions[-1].version_id,
            expected_selection_revision=0,
            expected_selected_version_id=series.selected_version_id,
        )
        inspection = drama_render_store.inspect_render_plan("scope-render")
        self.assertEqual(inspection.state, "stale")
        self.assertIn("art_direction_ref_mismatch", inspection.reasons)
        rebuilt = drama_render_store.create_render_plan(
            "scope-render",
            replace_stale=True,
        )
        self.assertNotEqual(rebuilt.plan_fingerprint, plan.plan_fingerprint)
        drama_art_direction_store.select_art_direction_version(
            "scope-render",
            version_id=series.selected_version_id,
            expected_selection_revision=1,
            expected_selected_version_id=appended.versions[-1].version_id,
        )
        inspection = drama_render_store.inspect_render_plan("scope-render")
        self.assertEqual(inspection.state, "stale")
        self.assertIn("art_direction_resolution_mismatch", inspection.reasons)

    def test_episode_override_and_clear_stale_existing_render_plan(self) -> None:
        self._assembled("scope-clear")
        self._series("scope-clear")
        series_plan = drama_render_store.create_render_plan("scope-clear")
        episode = self._episode("scope-clear")
        self.assertEqual(
            drama_render_store.inspect_render_plan("scope-clear").state,
            "stale",
        )
        episode_plan = drama_render_store.create_render_plan(
            "scope-clear",
            replace_stale=True,
        )
        self.assertEqual(episode_plan.art_direction_resolution.scope, "episode")
        self.assertEqual(
            episode_plan.art_direction_ref.version_id,
            episode.selected_version_id,
        )
        drama_art_direction_scope.set_scoped_art_direction_enabled(
            "scope-clear",
            scope="episode",
            season_no=1,
            episode_no=1,
            enabled=False,
            expected_scope_revision=0,
            expected_enabled=True,
        )
        inspection = drama_render_store.inspect_render_plan("scope-clear")
        self.assertEqual(inspection.state, "stale")
        self.assertIn("art_direction_resolution_mismatch", inspection.reasons)
        restored = drama_render_store.create_render_plan(
            "scope-clear",
            replace_stale=True,
        )
        self.assertEqual(restored.art_direction_resolution.scope, "series")
        self.assertEqual(
            restored.art_direction_ref,
            series_plan.art_direction_ref,
        )
        drama_art_direction_scope.set_scoped_art_direction_enabled(
            "scope-clear",
            scope="episode",
            season_no=1,
            episode_no=1,
            enabled=True,
            expected_scope_revision=1,
            expected_enabled=False,
        )
        write_json(
            drama_render_store.render_plan_path("scope-clear"),
            {
                "schema_version": 1,
                "artifact_type": "drama_render_plan",
                "plan_fingerprint": episode_plan.plan_fingerprint,
                "plan": model_to_dict(episode_plan),
            },
        )
        inspection = drama_render_store.inspect_render_plan("scope-clear")
        self.assertEqual(inspection.state, "stale")
        self.assertEqual(
            inspection.plan.art_direction_ref,
            episode_plan.art_direction_ref,
        )
        self.assertIn("art_direction_resolution_mismatch", inspection.reasons)

    def test_legacy_series_plan_remains_readable_but_requires_migration(self) -> None:
        self._assembled("scope-legacy")
        self._series("scope-legacy")
        current = drama_render_store.create_render_plan("scope-legacy")
        legacy_payload = current.model_dump()
        legacy_payload.pop("art_direction_resolution")
        legacy_payload["plan_fingerprint"] = _canonical_sha256(
            {
                key: value
                for key, value in legacy_payload.items()
                if key != "plan_fingerprint"
            }
        )
        legacy = RenderPlan(**legacy_payload)
        path = drama_render_store.render_plan_path("scope-legacy")
        envelope = {
            "schema_version": 1,
            "artifact_type": "drama_render_plan",
            "plan_fingerprint": legacy.plan_fingerprint,
            "plan": model_to_dict(legacy),
        }
        path.write_text(json.dumps(envelope), encoding="utf-8")
        inspection = drama_render_store.inspect_render_plan("scope-legacy")
        self.assertEqual(inspection.state, "stale")
        self.assertIsNotNone(inspection.plan)
        self.assertIsNone(inspection.plan.art_direction_resolution)
        self.assertIn("art_direction_resolution_mismatch", inspection.reasons)
        migrated = drama_render_store.create_render_plan(
            "scope-legacy",
            replace_stale=True,
        )
        self.assertEqual(migrated.art_direction_resolution.scope, "series")

    def test_special_files_and_parent_symlink_fail_closed(self) -> None:
        self._workspace("scope-special")
        self._global("scope-special")
        path = drama_art_direction_scope.scoped_art_direction_catalog_path(
            "scope-special",
            scope="global",
        )
        valid = path.read_bytes()
        path.unlink()
        path.mkdir()
        self.assertEqual(
            drama_art_direction_scope.inspect_scoped_art_direction_catalog(
                "scope-special",
                scope="global",
            ).state,
            "invalid",
        )
        path.rmdir()
        path.write_bytes(valid)
        target = path.with_name("outside.json")
        target.write_bytes(valid)
        path.unlink()
        path.symlink_to(target)
        self.assertEqual(
            drama_art_direction_scope.inspect_scoped_art_direction_catalog(
                "scope-special",
                scope="global",
            ).state,
            "invalid",
        )

        self._workspace("scope-fifo")
        fifo = drama_art_direction_scope.scoped_art_direction_catalog_path(
            "scope-fifo",
            scope="global",
        )
        fifo.parent.mkdir(parents=True, exist_ok=True)
        os.mkfifo(fifo)
        self.assertEqual(
            drama_art_direction_scope.inspect_scoped_art_direction_catalog(
                "scope-fifo",
                scope="global",
            ).state,
            "invalid",
        )

        self._workspace("scope-parent-link")
        linked_path = drama_art_direction_scope.scoped_art_direction_catalog_path(
            "scope-parent-link",
            scope="global",
        )
        linked_path.parent.mkdir(parents=True, exist_ok=True)
        real_assets = linked_path.parent.with_name("assets-real")
        linked_path.parent.rename(real_assets)
        linked_path.parent.symlink_to(real_assets, target_is_directory=True)
        with self.assertRaises(
            drama_art_direction_scope.DramaArtDirectionScopeError
        ):
            self._global("scope-parent-link")

    def test_target_and_precommit_cas_preserve_existing_bytes(self) -> None:
        self._workspace("scope-race")
        original = self._global("scope-race")
        path = drama_art_direction_scope.scoped_art_direction_catalog_path(
            "scope-race",
            scope="global",
        )
        before = path.read_bytes()
        with patch(
            "src.drama_art_direction_scope._target_token_at",
            return_value=("file", 1, "changed"),
        ):
            with self.assertRaisesRegex(
                drama_art_direction_scope.DramaArtDirectionScopeError,
                "changed concurrently",
            ):
                drama_art_direction_scope.append_scoped_art_direction_candidate(
                    "scope-race",
                    scope="global",
                    spec=_spec("candidate"),
                    source_kind="manual",
                    derived_from=original.selected_version_id,
                    expected_catalog_fingerprint=original.catalog_fingerprint,
                )
        self.assertEqual(path.read_bytes(), before)

        token = drama_art_direction_scope._target_token(
            paths.workspace_root("scope-race"),
            path,
        )
        with patch(
            "src.drama_art_direction_scope._target_token_at",
            side_effect=[token, ("file", 1, "late-change")],
        ):
            with self.assertRaisesRegex(
                drama_art_direction_scope.DramaArtDirectionScopeError,
                "changed concurrently",
            ):
                drama_art_direction_scope.append_scoped_art_direction_candidate(
                    "scope-race",
                    scope="global",
                    spec=_spec("late-candidate"),
                    source_kind="manual",
                    derived_from=original.selected_version_id,
                    expected_catalog_fingerprint=original.catalog_fingerprint,
                )
        self.assertEqual(path.read_bytes(), before)


if __name__ == "__main__":
    import unittest

    unittest.main()
