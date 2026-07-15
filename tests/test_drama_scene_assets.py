"""iter109: pure scene asset versioning and explicit shot bindings."""

from __future__ import annotations

import hashlib
import json
import unittest

from pydantic import ValidationError

from src import drama_assets
from src.drama_schemas import (
    EpisodeSceneAssetManifest,
    SceneAssetCatalog,
    SceneAssetVersion,
    SceneSpec,
)
from src.schemas import model_to_dict


def _spec(name: str = "雨夜天台") -> dict:
    return {
        "display_name": name,
        "location": "城市写字楼天台",
        "time_of_day": "夜",
        "weather": "小雨",
        "spatial_anchors": ["东侧水箱", "西侧安全门"],
        "visual_tokens": ["冷蓝色", "湿地反光"],
    }


def _canonical_sha(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


class DramaSceneAssetPureTests(unittest.TestCase):
    def test_catalog_append_select_and_aba_are_explicit(self) -> None:
        first = drama_assets.build_scene_asset_version(
            scene_id="s001",
            spec=_spec(),
            source_kind="identity_snapshot",
        )
        catalog = drama_assets.build_scene_asset_catalog(first)
        self.assertEqual(catalog.assets[0].selected_version_id, first.scene_version_id)
        self.assertEqual(catalog.assets[0].selection_revision, 0)

        second_scene = drama_assets.build_scene_asset_version(
            scene_id="s002",
            spec=_spec("办公室"),
            source_kind="identity_snapshot",
        )
        catalog = drama_assets.add_scene_asset(
            catalog,
            version=second_scene,
            expected_catalog_fingerprint=catalog.catalog_fingerprint,
        )
        candidate = drama_assets.build_scene_asset_version(
            scene_id="s001",
            spec={**_spec(), "weather": "暴雨"},
            source_kind="appended_candidate",
            derived_from=first.scene_version_id,
        )
        appended = drama_assets.append_scene_asset_version(
            catalog,
            scene_id="s001",
            version=candidate,
            expected_catalog_fingerprint=catalog.catalog_fingerprint,
        )
        self.assertEqual(appended.assets[0].selected_version_id, first.scene_version_id)
        self.assertEqual(
            drama_assets.append_scene_asset_version(
                appended,
                scene_id="s001",
                version=candidate,
                expected_catalog_fingerprint=appended.catalog_fingerprint,
            ),
            appended,
        )
        selected = drama_assets.select_scene_asset_version(
            appended,
            scene_id="s001",
            scene_version_id=candidate.scene_version_id,
            expected_selection_revision=0,
            expected_selected_version_id=first.scene_version_id,
        )
        self.assertEqual(selected.assets[0].selection_revision, 1)
        returned = drama_assets.select_scene_asset_version(
            selected,
            scene_id="s001",
            scene_version_id=first.scene_version_id,
            expected_selection_revision=1,
            expected_selected_version_id=candidate.scene_version_id,
        )
        self.assertEqual(returned.assets[0].selection_revision, 2)
        with self.assertRaisesRegex(ValueError, "scene asset selection was rejected"):
            drama_assets.select_scene_asset_version(
                returned,
                scene_id="s001",
                scene_version_id=candidate.scene_version_id,
                expected_selection_revision=0,
                expected_selected_version_id=first.scene_version_id,
            )

    def test_schema_rejects_tamper_extra_bool_cross_scene_and_bad_lists(self) -> None:
        with self.assertRaises(ValidationError):
            SceneSpec(**{**_spec(), "extra": "no"})
        with self.assertRaises(ValidationError):
            SceneSpec(**{**_spec(), "location": " 天台"})
        with self.assertRaises(ValidationError):
            SceneSpec(**{**_spec(), "visual_tokens": ["blue", "blue"]})

        version = drama_assets.build_scene_asset_version(
            scene_id="s001",
            spec=_spec(),
            source_kind="identity_snapshot",
        )
        raw = model_to_dict(version)
        raw["version_fingerprint"] = "0" * 64
        with self.assertRaises(ValidationError):
            SceneAssetVersion(**raw)
        with self.assertRaisesRegex(
            drama_assets.SceneAssetError,
            "version build was rejected",
        ):
            drama_assets.build_scene_asset_version(
                scene_id="s001",
                spec=_spec(),
                source_kind="identity_snapshot",
                artifact={
                    "path": "data/scene_refs/s002/wrong.png",
                    "sha256": "1" * 64,
                    "size_bytes": 10,
                },
            )
        catalog = drama_assets.build_scene_asset_catalog(version)
        raw_catalog = model_to_dict(catalog)
        raw_catalog["assets"][0]["selection_revision"] = True
        raw_catalog["catalog_fingerprint"] = _canonical_sha(
            {key: value for key, value in raw_catalog.items() if key != "catalog_fingerprint"}
        )
        with self.assertRaises(ValidationError):
            SceneAssetCatalog(**raw_catalog)

    def test_public_pure_errors_redact_private_inputs_without_exception_chain(self) -> None:
        secret = "SECRET_VISUAL_TOKEN_109"
        with self.assertRaises(drama_assets.SceneAssetError) as caught:
            drama_assets.build_scene_asset_version(
                scene_id="s001",
                spec={**_spec(), "visual_tokens": [secret, secret]},
                source_kind="identity_snapshot",
                artifact={
                    "path": "data/scene_refs/s001/SECRET_PATH.png",
                    "sha256": "1" * 64,
                    "size_bytes": 1,
                },
            )
        rendered = f"{caught.exception!s} {caught.exception!r}"
        self.assertNotIn(secret, rendered)
        self.assertNotIn("SECRET_PATH", rendered)
        self.assertIsNone(caught.exception.__cause__)
        self.assertIsNone(caught.exception.__context__)

    def test_scene_usage_index_rejects_manifest_tamper(self) -> None:
        raw = {
            "schema_version": 1,
            "season_no": 1,
            "episode_no": 1,
            "render_plan_fingerprint": "1" * 64,
            "binding_revision": 0,
            "usage_fingerprint": "2" * 64,
            "shot_scene_refs": [],
            "manifest_fingerprint": "3" * 64,
        }
        with self.assertRaises(ValidationError):
            EpisodeSceneAssetManifest(**raw)


if __name__ == "__main__":
    unittest.main()
