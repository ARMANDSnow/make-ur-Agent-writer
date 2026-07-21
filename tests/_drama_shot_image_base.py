"""Shared synthetic stage-C1 setup for iter111 tests."""

from __future__ import annotations

import hashlib
import zlib

from src import (
    character_designer,
    drama_art_direction_store,
    drama_asset_versions,
    drama_assets,
    drama_render_store,
    drama_reviewer,
    drama_shot_image,
    drama_store,
    paths,
    storyboard_builder,
)
from src.drama_schemas import character_paths, episode_paths
from src.utils import write_json
from tests._drama_base import DramaTestBase


class DramaShotImageFixture(DramaTestBase):
    @staticmethod
    def _art_spec() -> dict:
        return {
            "preset": "cinematic",
            "positive_tokens": ["ink wash"],
            "negative_tokens": ["watermark"],
            "palette": ["#112233"],
            "aspect_ratio": "9:16",
        }

    @staticmethod
    def _scene_spec() -> dict:
        return {
            "display_name": "天台",
            "location": "城市天台",
            "time_of_day": "夜",
            "weather": "晴",
            "spatial_anchors": ["入口", "护栏"],
            "visual_tokens": ["冷色"],
        }

    @staticmethod
    def _prop_spec(index: int) -> dict:
        return {
            "kind": "prop",
            "display_name": f"道具{index}",
            "owner_character_id": None,
            "state_label": "完好",
            "first_seen_episode_no": 1,
            "visual_tokens": [f"token-{index}"],
        }

    def _write_artifact(self, workspace: str, relative: str, label: str) -> dict:
        path = paths.workspace_root(workspace) / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        rgba = hashlib.sha256(f"iter111:{label}".encode("utf-8")).digest()[:3] + b"\xff"

        def chunk(kind: bytes, content: bytes) -> bytes:
            return (
                len(content).to_bytes(4, "big")
                + kind
                + content
                + (zlib.crc32(kind + content) & 0xFFFFFFFF).to_bytes(4, "big")
            )

        ihdr = (1).to_bytes(4, "big") * 2 + bytes([8, 6, 0, 0, 0])
        payload = (
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(b"\x00" + rgba))
            + chunk(b"IEND", b"")
        )
        path.write_bytes(payload)
        return {
            "path": relative,
            "sha256": hashlib.sha256(payload).hexdigest(),
            "size_bytes": len(payload),
        }

    def _seed_shot_image_sources(
        self,
        name: str = "shot-image",
        *,
        character_artifacts: bool = True,
        scene_artifact: bool = True,
        prop_count: int = 0,
        max_reference_images: int = 4,
    ):
        self._make_drama_workspace(name, "霸总", episode_count=2)
        self._write_setup(name, hook=True)
        write_json(
            episode_paths(name).storyboard_path,
            storyboard_builder.run(name, mock=True),
        )
        sheet = character_designer.run(name, mock=True)
        if character_artifacts:
            for character in sheet["characters"]:
                relative = (
                    f"data/character_refs/{character['id']}/portrait_neutral.png"
                )
                self._write_artifact(name, relative, character["id"])
                character["reference_images"] = [{"path": relative}]
        write_json(character_paths(name).sheet_path, sheet)
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
        render_plan = drama_render_store.create_render_plan(name)
        character_catalog = drama_asset_versions.create_character_asset_catalog(name)
        character_manifest = drama_asset_versions.create_episode_asset_manifest(name)

        scene_record = None
        if scene_artifact:
            scene_record = self._write_artifact(
                name,
                "data/scene_refs/s001/reference.png",
                "scene-s001",
            )
        scene_version = drama_assets.build_scene_asset_version(
            scene_id="s001",
            spec=self._scene_spec(),
            source_kind="identity_snapshot",
            artifact=scene_record,
        )
        scene_catalog = drama_asset_versions.create_scene_asset_catalog(
            name,
            version=scene_version,
        )
        scene_mapping = {shot.shot_id: "s001" for shot in render_plan.shots}
        scene_manifest = drama_asset_versions.create_episode_scene_asset_manifest(
            name,
            shot_scene_ids=scene_mapping,
        )

        prop_catalog = drama_asset_versions.create_prop_or_clue_asset_catalog(name)
        prop_ids: list[str] = []
        for index in range(1, prop_count + 1):
            asset_id = f"p{index:03d}"
            relative = f"data/prop_clue_refs/{asset_id}/reference.png"
            record = self._write_artifact(name, relative, asset_id)
            version = drama_assets.build_prop_or_clue_asset_version(
                asset_id=asset_id,
                spec=self._prop_spec(index),
                source_kind="identity_snapshot",
                artifact=record,
            )
            prop_catalog = drama_asset_versions.add_prop_or_clue_asset(
                name,
                version=version,
                expected_catalog_fingerprint=prop_catalog.catalog_fingerprint,
            )
            prop_ids.append(asset_id)
        prop_mapping = {shot.shot_id: list(prop_ids) for shot in render_plan.shots}
        prop_manifest = (
            drama_asset_versions.create_episode_prop_or_clue_asset_manifest(
                name,
                shot_asset_ids=prop_mapping,
            )
        )
        character_mapping = {
            shot.shot_id: [render_plan.frozen_character_ids[0]]
            for shot in render_plan.shots
        }
        policy = drama_shot_image.build_shot_image_reference_policy(
            max_reference_images=max_reference_images,
        )
        return {
            "render_plan": render_plan,
            "art_catalog": art_catalog,
            "character_catalog": character_catalog,
            "character_manifest": character_manifest,
            "scene_catalog": scene_catalog,
            "scene_manifest": scene_manifest,
            "prop_catalog": prop_catalog,
            "prop_manifest": prop_manifest,
            "character_mapping": character_mapping,
            "policy": policy,
        }

    @staticmethod
    def _build_pure(sources: dict, *, binding_revision: int = 0):
        return drama_shot_image.build_episode_shot_image_plan(
            sources["render_plan"],
            sources["character_catalog"],
            sources["character_manifest"],
            sources["scene_catalog"],
            sources["scene_manifest"],
            sources["prop_catalog"],
            sources["prop_manifest"],
            art_direction_catalog=sources["art_catalog"],
            shot_character_ids=sources["character_mapping"],
            reference_policy=sources["policy"],
            character_binding_revision=binding_revision,
        )
