"""iter129: strict drama asset Web projection and governed mutations."""

from __future__ import annotations

import json
from typing import Any

from src import (
    character_designer,
    drama_art_direction_scope,
    drama_art_direction_store,
    drama_asset_versions,
    drama_assets,
    drama_render_store,
    drama_reviewer,
    drama_store,
    storyboard_builder,
)
from src.drama_schemas import _canonical_sha256, character_paths, episode_paths
from src.schemas import model_to_dict
from src.utils import write_json
from src.web import routes
from tests._drama_base import DramaTestBase


def _spec(preset: str) -> dict[str, Any]:
    return {
        "preset": preset,
        "positive_tokens": ["ink wash"],
        "negative_tokens": ["watermark"],
        "palette": ["#112233"],
        "aspect_ratio": "9:16",
    }


class DramaAssetWebTests(DramaTestBase):
    _HEADERS = {
        "content-type": "application/json",
        "x-drama-asset-intent": "mutate-v1",
        "sec-fetch-site": "same-origin",
        "origin": "http://127.0.0.1:8765",
        "host": "127.0.0.1:8765",
    }

    def _workspace(self, name: str) -> None:
        self._make_drama_workspace(name, episode_count=2)

    @staticmethod
    def _decode(response: tuple) -> tuple[int, dict[str, Any]]:
        status, content_type, body = response[:3]
        assert "application/json" in content_type
        return status, json.loads(body)

    def _post(
        self,
        name: str,
        suffix: str,
        payload: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, Any]]:
        return self._decode(
            routes.dispatch(
                "POST",
                f"/api/workspace/{name}/drama/assets/{suffix}",
                json.dumps(payload).encode(),
                headers if headers is not None else self._HEADERS,
            )
        )

    def test_page_and_missing_optional_catalogs_degrade_cleanly(self) -> None:
        self._workspace("asset-web-empty")
        status, _content_type, body = routes.dispatch(
            "GET",
            "/w/asset-web-empty/assets",
        )
        self.assertEqual(status, 200)
        html = body.decode()
        self.assertIn("资产治理", html)
        self.assertIn('window.PAGE_KIND = "drama_assets"', html)
        self.assertIn("assets-page-root", html)
        js = routes.static.JS_DASHBOARD
        self.assertGreaterEqual(js.count("view_episode_no: episodeNo()"), 3)
        self.assertIn('class="table table-wide"', js)
        self.assertIn("if (err && err.status === 409)", js)
        self.assertIn("await load();", js)
        self.assertIn("跨季不可选择", js)
        self.assertIn("当前季 lifecycle 已停用", js)

        status, data = self._decode(
            routes.dispatch(
                "GET",
                "/api/workspace/asset-web-empty/drama/assets?season_no=1&episode_no=2",
            )
        )
        self.assertEqual(status, 200)
        self.assertEqual(data["episode_no"], 2)
        self.assertEqual(len(data["sections"]), 6)
        self.assertTrue(
            all(section["state"] != "invalid" for section in data["sections"])
        )
        encoded = json.dumps(data)
        for forbidden in (
            "positive_tokens",
            "negative_tokens",
            "artifact",
            "provider",
            "prompt",
            "local_path",
        ):
            self.assertNotIn(forbidden, encoded)

    def test_all_four_asset_families_project_exact_selected_usage(self) -> None:
        name = "asset-web-complete"
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
        art = drama_art_direction_store.create_art_direction_catalog(
            name,
            art_direction_id="visual_bible",
            spec=_spec("series"),
            source_kind="manual",
        )
        global_art = (
            drama_art_direction_scope.create_scoped_art_direction_catalog(
                name,
                scope="global",
                art_direction_id="visual_bible",
                spec=_spec("series"),
                source_kind="manual",
            )
        )
        self.assertEqual(
            global_art.selected_version_id,
            art.selected_version_id,
        )
        plan = drama_render_store.create_render_plan(name)
        characters = drama_asset_versions.create_character_asset_catalog(name)
        drama_asset_versions.create_episode_asset_manifest(name)
        scene_version = drama_assets.build_scene_asset_version(
            scene_id="s001",
            spec={
                "display_name": "天台",
                "location": "旧楼天台",
                "time_of_day": "夜",
                "weather": "晴",
                "spatial_anchors": ["入口"],
                "visual_tokens": ["冷色"],
            },
            source_kind="identity_snapshot",
        )
        drama_asset_versions.create_scene_asset_catalog(
            name,
            version=scene_version,
        )
        drama_asset_versions.create_episode_scene_asset_manifest(
            name,
            shot_scene_ids={shot.shot_id: "s001" for shot in plan.shots},
        )
        props = drama_asset_versions.create_prop_or_clue_asset_catalog(name)
        prop_version = drama_assets.build_prop_or_clue_asset_version(
            asset_id="p001",
            spec={
                "kind": "prop",
                "display_name": "旧怀表",
                "owner_character_id": "c001",
                "state_label": "完好",
                "first_seen_episode_no": 1,
                "visual_tokens": ["特写"],
            },
            source_kind="identity_snapshot",
        )
        drama_asset_versions.add_prop_or_clue_asset(
            name,
            version=prop_version,
            expected_catalog_fingerprint=props.catalog_fingerprint,
        )
        prop_mapping = {shot.shot_id: [] for shot in plan.shots}
        prop_mapping[plan.shots[0].shot_id] = ["p001"]
        drama_asset_versions.create_episode_prop_or_clue_asset_manifest(
            name,
            shot_asset_ids=prop_mapping,
        )

        status, data = self._decode(
            routes.dispatch(
                "GET",
                f"/api/workspace/{name}/drama/assets",
            )
        )
        self.assertEqual(status, 200)
        items = [
            item
            for section in data["sections"]
            for item in section["items"]
        ]
        self.assertTrue(
            {"character", "art_direction", "scene", "prop"}
            <= {item["kind"] for item in items}
        )
        selected = {
            (item["kind"], item["asset_id"]): next(
                version
                for version in item["versions"]
                if version["selected"]
            )
            for item in items
        }
        self.assertEqual(
            selected[("art_direction", art.art_direction_id)]["version_id"],
            art.selected_version_id,
        )
        self.assertEqual(
            selected[("scene", "s001")]["version_id"],
            scene_version.scene_version_id,
        )
        self.assertEqual(
            selected[("prop", "p001")]["version_id"],
            prop_version.asset_version_id,
        )
        character = characters.assets[0]
        self.assertEqual(
            selected[("character", character.asset_id)]["version_id"],
            character.selected_version_id,
        )
        self.assertTrue(
            all(
                selected[key]["references"]
                for key in (
                    ("art_direction", art.art_direction_id),
                    ("character", character.asset_id),
                    ("scene", "s001"),
                    ("prop", "p001"),
                )
            )
        )
        series_item = next(
            section["items"][0]
            for section in data["sections"]
            if section["key"] == "art_direction_series"
        )
        global_item = next(
            section["items"][0]
            for section in data["sections"]
            if section["key"] == "art_direction_global"
        )
        self.assertTrue(series_item["stale_references"])
        self.assertEqual(global_item["stale_references"], [])
        self.assertTrue(
            next(
                version
                for version in global_item["versions"]
                if version["selected"]
            )["references"]
        )

    def test_series_selection_is_cas_and_impact_is_server_owned(self) -> None:
        self._workspace("asset-web-select")
        original = drama_art_direction_store.create_art_direction_catalog(
            "asset-web-select",
            art_direction_id="visual_bible",
            spec=_spec("first"),
            source_kind="manual",
        )
        candidates = drama_art_direction_store.append_art_direction_candidate(
            "asset-web-select",
            spec=_spec("second"),
            source_kind="manual",
            expected_catalog_fingerprint=original.catalog_fingerprint,
            derived_from=original.selected_version_id,
        )
        target = next(
            version.version_id
            for version in candidates.versions
            if version.version_id != candidates.selected_version_id
        )
        payload = {
            "kind": "art_direction",
            "asset_id": "visual_bible",
            "version_id": target,
            "expected_selection_revision": 0,
            "expected_selected_version_id": original.selected_version_id,
            "season_no": 1,
            "scope": "series",
        }
        no_op = dict(payload)
        no_op["version_id"] = original.selected_version_id
        no_op["view_episode_no"] = 2
        status, data = self._post("asset-web-select", "select", no_op)
        self.assertEqual(status, 200)
        self.assertFalse(data["changed"])
        self.assertEqual(data["affected_references"], [])
        self.assertEqual(data["overview"]["episode_no"], 2)

        status, data = self._post("asset-web-select", "select", payload)
        self.assertEqual(status, 200)
        self.assertTrue(data["changed"])
        self.assertEqual(data["affected_references"], [])

        status, data = self._post("asset-web-select", "select", payload)
        self.assertEqual(status, 409)
        self.assertEqual(data["error"], "asset state changed; refresh and retry")

        forged = dict(payload)
        forged["affected_shot_ids"] = ["forged"]
        status, data = self._post("asset-web-select", "select", forged)
        self.assertEqual(status, 400)
        self.assertNotIn("forged", json.dumps(data))

    def test_status_change_and_exact_current_noop_are_non_destructive(self) -> None:
        self._workspace("asset-web-status")
        first = drama_art_direction_store.create_art_direction_catalog(
            "asset-web-status",
            art_direction_id="visual_bible",
            spec=_spec("first"),
            source_kind="manual",
        )
        catalog = drama_art_direction_store.append_art_direction_candidate(
            "asset-web-status",
            spec=_spec("unused"),
            source_kind="manual",
            expected_catalog_fingerprint=first.catalog_fingerprint,
            derived_from=first.selected_version_id,
        )
        unused = next(
            version.version_id
            for version in catalog.versions
            if version.version_id != catalog.selected_version_id
        )
        payload = {
            "kind": "art_direction",
            "asset_id": "visual_bible",
            "version_id": unused,
            "status": "disabled",
            "expected_revision": 0,
            "expected_current_status": "active",
            "season_no": 1,
        }
        status, data = self._post("asset-web-status", "status", payload)
        self.assertEqual(status, 200)
        self.assertTrue(data["changed"])
        self.assertEqual(data["overview"]["retirement_revision"], 1)

        payload.update(
            expected_revision=1,
            expected_current_status="disabled",
        )
        status, data = self._post("asset-web-status", "status", payload)
        self.assertEqual(status, 200)
        self.assertFalse(data["changed"])
        self.assertEqual(data["affected_references"], [])
        self.assertEqual(data["overview"]["retirement_revision"], 1)

    def test_disabled_selected_version_preserves_exact_selection_noop(self) -> None:
        self._workspace("asset-web-disabled-noop")
        catalog = drama_art_direction_store.create_art_direction_catalog(
            "asset-web-disabled-noop",
            art_direction_id="visual_bible",
            spec=_spec("selected"),
            source_kind="manual",
        )
        status, data = self._post(
            "asset-web-disabled-noop",
            "status",
            {
                "kind": "art_direction",
                "asset_id": catalog.art_direction_id,
                "version_id": catalog.selected_version_id,
                "status": "disabled",
                "expected_revision": 0,
                "expected_current_status": "active",
                "season_no": 1,
            },
        )
        self.assertEqual(status, 200)
        self.assertTrue(data["changed"])

        status, data = self._post(
            "asset-web-disabled-noop",
            "select",
            {
                "kind": "art_direction",
                "asset_id": catalog.art_direction_id,
                "version_id": catalog.selected_version_id,
                "expected_selection_revision": 0,
                "expected_selected_version_id": catalog.selected_version_id,
                "season_no": 1,
                "scope": "series",
            },
        )
        self.assertEqual(status, 200)
        self.assertFalse(data["changed"])
        self.assertEqual(data["affected_references"], [])

    def test_scope_clear_reenable_and_request_provenance(self) -> None:
        self._workspace("asset-web-scope")
        catalog = drama_art_direction_scope.create_scoped_art_direction_catalog(
            "asset-web-scope",
            scope="global",
            art_direction_id="visual_bible",
            spec=_spec("global"),
            source_kind="manual",
        )
        payload = {
            "scope": "global",
            "enabled": False,
            "expected_scope_revision": catalog.scope_revision,
            "expected_enabled": True,
        }
        no_op = dict(payload)
        no_op["enabled"] = True
        status, data = self._post(
            "asset-web-scope",
            "art-direction-scope",
            no_op,
        )
        self.assertEqual(status, 200)
        self.assertFalse(data["changed"])
        self.assertEqual(data["affected_references"], [])

        status, data = self._post(
            "asset-web-scope",
            "art-direction-scope",
            payload,
            headers={"content-type": "application/json"},
        )
        self.assertEqual(status, 403)
        self.assertIn("intent", data["error"])

        cross_origin = dict(self._HEADERS)
        cross_origin["origin"] = "https://evil.example"
        status, data = self._post(
            "asset-web-scope",
            "art-direction-scope",
            payload,
            headers=cross_origin,
        )
        self.assertEqual(status, 403)
        self.assertIn("origin", data["error"])

        status, data = self._post(
            "asset-web-scope",
            "art-direction-scope",
            payload,
        )
        self.assertEqual(status, 200)
        self.assertTrue(data["changed"])
        global_item = next(
            section["items"][0]
            for section in data["overview"]["sections"]
            if section["key"] == "art_direction_global"
        )
        self.assertFalse(global_item["enabled"])

        payload.update(
            enabled=True,
            expected_scope_revision=1,
            expected_enabled=False,
        )
        status, data = self._post(
            "asset-web-scope",
            "art-direction-scope",
            payload,
        )
        self.assertEqual(status, 200)
        self.assertTrue(data["changed"])

    def test_global_selectability_respects_another_season_ledger(self) -> None:
        self._workspace("asset-web-global-seasons")
        catalog = drama_art_direction_scope.create_scoped_art_direction_catalog(
            "asset-web-global-seasons",
            scope="global",
            art_direction_id="visual_bible",
            spec=_spec("global"),
            source_kind="manual",
        )
        status, data = self._post(
            "asset-web-global-seasons",
            "status",
            {
                "kind": "art_direction",
                "asset_id": catalog.art_direction_id,
                "version_id": catalog.selected_version_id,
                "status": "disabled",
                "expected_revision": 0,
                "expected_current_status": "active",
                "season_no": 2,
            },
        )
        self.assertEqual(status, 200)

        status, data = self._decode(
            routes.dispatch(
                "GET",
                "/api/workspace/asset-web-global-seasons/drama/assets?season_no=1",
            )
        )
        self.assertEqual(status, 200)
        global_item = next(
            section["items"][0]
            for section in data["sections"]
            if section["key"] == "art_direction_global"
        )
        selected = next(
            version
            for version in global_item["versions"]
            if version["selected"]
        )
        self.assertEqual(selected["status"], "active")
        self.assertFalse(selected["selection_allowed"])

        status, data = self._post(
            "asset-web-global-seasons",
            "art-direction-scope",
            {
                "scope": "global",
                "enabled": False,
                "expected_scope_revision": 0,
                "expected_enabled": True,
            },
        )
        self.assertEqual(status, 200)
        status, data = self._post(
            "asset-web-global-seasons",
            "art-direction-scope",
            {
                "scope": "global",
                "enabled": True,
                "expected_scope_revision": 1,
                "expected_enabled": False,
            },
        )
        self.assertEqual(status, 400)
        self.assertEqual(data["error"], "invalid asset mutation request")

    def test_global_scope_impact_covers_all_stored_plan_seasons(self) -> None:
        name = "asset-web-global-impact"
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
        drama_art_direction_scope.create_scoped_art_direction_catalog(
            name,
            scope="global",
            art_direction_id="visual_bible",
            spec=_spec("global"),
            source_kind="manual",
        )
        plan_one = drama_render_store.create_render_plan(name)
        payload = plan_one.model_dump()
        payload["season_no"] = 2
        payload["episode_no"] = 2
        resolution = payload["art_direction_resolution"]
        resolution["season_no"] = 2
        resolution["episode_no"] = 2
        resolution["resolution_fingerprint"] = _canonical_sha256(
            {
                key: value
                for key, value in resolution.items()
                if key != "resolution_fingerprint"
            }
        )
        payload["plan_fingerprint"] = _canonical_sha256(
            {
                key: value
                for key, value in payload.items()
                if key != "plan_fingerprint"
            }
        )
        plan_two = type(plan_one)(**payload)
        write_json(
            drama_render_store.render_plan_path(name, episode_no=2),
            {
                "schema_version": 1,
                "artifact_type": "drama_render_plan",
                "plan_fingerprint": plan_two.plan_fingerprint,
                "plan": model_to_dict(plan_two),
            },
        )

        status, data = self._post(
            name,
            "art-direction-scope",
            {
                "scope": "global",
                "enabled": False,
                "expected_scope_revision": 0,
                "expected_enabled": True,
            },
        )
        self.assertEqual(status, 200)
        self.assertEqual(
            {
                (reference["season_no"], reference["episode_no"])
                for reference in data["affected_references"]
            },
            {(1, 1), (2, 2)},
        )

    def test_series_impact_binds_season_and_current_selection_revision(self) -> None:
        name = "asset-web-series-impact"
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
        series_one = drama_art_direction_store.create_art_direction_catalog(
            name,
            art_direction_id="visual_bible",
            spec=_spec("series"),
            source_kind="manual",
            season_no=1,
        )
        series_two = drama_art_direction_store.create_art_direction_catalog(
            name,
            art_direction_id="visual_bible",
            spec=_spec("series"),
            source_kind="manual",
            season_no=2,
        )
        self.assertEqual(
            series_one.selected_version_id,
            series_two.selected_version_id,
        )
        candidates = drama_art_direction_store.append_art_direction_candidate(
            name,
            spec=_spec("candidate"),
            source_kind="manual",
            expected_catalog_fingerprint=series_one.catalog_fingerprint,
            derived_from=series_one.selected_version_id,
            season_no=1,
        )
        candidate_id = next(
            version.version_id
            for version in candidates.versions
            if version.version_id != candidates.selected_version_id
        )
        plan_one = drama_render_store.create_render_plan(name)
        payload = plan_one.model_dump()
        payload["season_no"] = 2
        payload["episode_no"] = 2
        resolution = payload["art_direction_resolution"]
        resolution["season_no"] = 2
        resolution["episode_no"] = 2
        resolution["source_selection_fingerprint"] = _canonical_sha256(
            {
                "scope": "series",
                "season_no": 2,
                "episode_no": None,
                "ref": resolution["ref"],
                "selection_revision": 0,
                "scope_revision": None,
            }
        )
        resolution["resolution_fingerprint"] = _canonical_sha256(
            {
                key: value
                for key, value in resolution.items()
                if key != "resolution_fingerprint"
            }
        )
        payload["plan_fingerprint"] = _canonical_sha256(
            {
                key: value
                for key, value in payload.items()
                if key != "plan_fingerprint"
            }
        )
        plan_two = type(plan_one)(**payload)
        write_json(
            drama_render_store.render_plan_path(name, episode_no=2),
            {
                "schema_version": 1,
                "artifact_type": "drama_render_plan",
                "plan_fingerprint": plan_two.plan_fingerprint,
                "plan": model_to_dict(plan_two),
            },
        )

        status, data = self._decode(
            routes.dispatch(
                "GET",
                f"/api/workspace/{name}/drama/assets?season_no=1",
            )
        )
        self.assertEqual(status, 200)
        series_item = next(
            section["items"][0]
            for section in data["sections"]
            if section["key"] == "art_direction_series"
        )
        self.assertEqual(
            {
                (reference["season_no"], reference["episode_no"])
                for reference in series_item["stale_references"]
            },
            {(1, 1)},
        )

        selected_candidate = (
            drama_art_direction_store.select_art_direction_version(
                name,
                version_id=candidate_id,
                expected_selection_revision=0,
                expected_selected_version_id=series_one.selected_version_id,
                season_no=1,
            )
        )
        drama_art_direction_store.select_art_direction_version(
            name,
            version_id=series_one.selected_version_id,
            expected_selection_revision=1,
            expected_selected_version_id=selected_candidate.selected_version_id,
            season_no=1,
        )
        status, data = self._decode(
            routes.dispatch(
                "GET",
                f"/api/workspace/{name}/drama/assets?season_no=1",
            )
        )
        self.assertEqual(status, 200)
        series_item = next(
            section["items"][0]
            for section in data["sections"]
            if section["key"] == "art_direction_series"
        )
        self.assertEqual(series_item["selection_revision"], 2)
        self.assertEqual(series_item["stale_references"], [])

    def test_stored_render_plan_in_wrong_episode_slot_blocks_impact(self) -> None:
        name = "asset-web-plan-slot"
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
        drama_art_direction_scope.create_scoped_art_direction_catalog(
            name,
            scope="global",
            art_direction_id="visual_bible",
            spec=_spec("global"),
            source_kind="manual",
        )
        plan = drama_render_store.create_render_plan(name)
        write_json(
            drama_render_store.render_plan_path(name, episode_no=2),
            {
                "schema_version": 1,
                "artifact_type": "drama_render_plan",
                "plan_fingerprint": plan.plan_fingerprint,
                "plan": model_to_dict(plan),
            },
        )
        inspection = drama_render_store.inspect_stored_render_plan(
            name,
            episode_no=2,
        )
        self.assertEqual(inspection.state, "invalid")
        self.assertEqual(inspection.reasons, ("episode_identity_mismatch",))

        status, data = self._decode(
            routes.dispatch(
                "GET",
                f"/api/workspace/{name}/drama/assets",
            )
        )
        self.assertEqual(status, 200)
        self.assertIn(
            {
                "source": "render_plan",
                "code": "scope_resolution_invalid",
                "season_no": None,
                "episode_no": 2,
            },
            data["blockers"],
        )
        global_item = next(
            section["items"][0]
            for section in data["sections"]
            if section["key"] == "art_direction_global"
        )
        self.assertFalse(global_item["impact_complete"])

    def test_invalid_catalog_fails_closed_without_raw_error(self) -> None:
        self._workspace("asset-web-invalid")
        path = drama_art_direction_scope.scoped_art_direction_catalog_path(
            "asset-web-invalid",
            scope="global",
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"secret_prompt":"do not leak","value":NaN}', encoding="utf-8")

        status, data = self._decode(
            routes.dispatch(
                "GET",
                "/api/workspace/asset-web-invalid/drama/assets",
            )
        )
        self.assertEqual(status, 200)
        self.assertFalse(data["mutation_allowed"])
        global_section = next(
            section
            for section in data["sections"]
            if section["key"] == "art_direction_global"
        )
        self.assertEqual(global_section["state"], "invalid")
        self.assertNotIn("secret_prompt", json.dumps(data))

    def test_novel_workspace_is_rejected(self) -> None:
        from src.cli_workspace import init_workspace

        init_workspace("not-drama", type="novel")
        status, data = self._decode(
            routes.dispatch(
                "GET",
                "/api/workspace/not-drama/drama/assets",
            )
        )
        self.assertEqual(status, 400)
        self.assertEqual(data["error"], "drama-only endpoint")
