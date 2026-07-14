"""Iteration 105 episode-scoped character projection contracts."""

from __future__ import annotations

import copy
import io
import json
import zipfile
from unittest.mock import patch

from src import (
    drama_reviewer,
    drama_season_export,
    drama_store,
    drama_video,
    drama_video_smoke,
    storyboard_builder,
)
from src.comfy_workflow_exporter import build_workflow
from src.drama_schemas import DramaEpisodeMeta, character_paths, episode_paths
from src.utils import read_json, write_json
from tests._drama_base import DramaTestBase


def _character(number: int, *, appearances: list[int]) -> dict:
    return {
        "id": f"c{number:03d}",
        "name": "本集主角" if number == 1 else f"未来角色{number}",
        "role": "主角" if number == 1 else "未来角色",
        "lora_token": f"role_{number}",
        "visual_signature": f"signature-{number}",
        "prompt_template_sd": f"PRIVATE_PROMPT_{number}",
        "appearances": appearances,
        "manual_override": number == 1,
        "agent_suggestions": [{"private": f"PRIVATE_NOTE_{number}"}],
    }


def _nine_character_sheet() -> dict:
    lead = _character(1, appearances=[1])
    lead["visual_contrast_with"] = {
        "target_id": "c002",
        "rules": {"silhouette": "opposite"},
    }
    return {
        "schema_version": 1,
        "season_no": 1,
        "episode_no": 2,
        "track": "霸总",
        "characters": [
            lead,
            *[_character(number, appearances=[2]) for number in range(2, 10)],
        ],
    }


class DramaEpisodeCharacterProjectionTests(DramaTestBase):
    def test_projection_is_strict_bounded_and_does_not_mutate_input(self) -> None:
        sheet = _nine_character_sheet()
        original = copy.deepcopy(sheet)

        projected = drama_store.episode_character_projection(
            sheet,
            episode_no=1,
            character_ids=["c001", "c009"],
        )

        self.assertEqual(
            [row["id"] for row in projected["characters"]],
            ["c001", "c009"],
        )
        self.assertTrue(
            all(row["appearances"] == [1] for row in projected["characters"])
        )
        self.assertNotIn("manual_override", projected["characters"][0])
        self.assertNotIn("agent_suggestions", projected["characters"][0])
        self.assertEqual(projected["characters"][0]["visual_contrast_with"], {})
        self.assertEqual(sheet, original)

        for invalid, message in (
            ([], "must not be empty"),
            (["c001", "c001"], "must be unique"),
            (["c999"], "not found"),
            ([f"c{number:03d}" for number in range(1, 10)], "at most 8"),
        ):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(ValueError, message):
                    drama_store.episode_character_projection(
                        sheet,
                        episode_no=1,
                        character_ids=invalid,
                    )

        with self.assertRaisesRegex(ValueError, "must be unique"):
            DramaEpisodeMeta(
                episode_no=1,
                verdict="Approve",
                duration_estimate_vs_target={"target": 60, "estimate": 60, "delta": 0},
                character_fingerprint_ids=["c001", "c001"],
            )

    def test_ambiguous_later_episode_never_falls_back_to_season_library(self) -> None:
        sheet = _nine_character_sheet()
        for row in sheet["characters"]:
            row["appearances"] = [1]

        with self.assertRaisesRegex(ValueError, "cast is ambiguous"):
            drama_store.episode_character_projection(sheet, episode_no=2)

        episode = self._minimal_episode(episode_no=2)
        with self.assertRaisesRegex(ValueError, "projection is empty"):
            build_workflow(episode, sheet)

        for row in sheet["characters"]:
            row["appearances"] = [2]
        with self.assertRaisesRegex(ValueError, "at most 8"):
            build_workflow(episode, sheet)

    def test_episode_one_legacy_fallback_excludes_future_only_rows(self) -> None:
        future_only = {
            "characters": [_character(2, appearances=[2])],
        }
        with self.assertRaisesRegex(ValueError, "cast is ambiguous"):
            drama_store.episode_character_projection(
                future_only,
                episode_no=1,
            )

        legacy_default = _character(1, appearances=[])
        mixed = {
            "characters": [legacy_default, _character(2, appearances=[2])],
        }
        projected = drama_store.episode_character_projection(
            mixed,
            episode_no=1,
        )
        self.assertEqual(
            [row["id"] for row in projected["characters"]],
            ["c001"],
        )

        name = "future-only-review"
        self._make_drama_workspace(name, "霸总")
        self._write_setup(name, hook=True)
        write_json(
            episode_paths(name).storyboard_path,
            storyboard_builder.run(name, mock=True),
        )
        write_json(character_paths(name).sheet_path, future_only)

        class NoProviderClient:
            is_mock = False

            def __init__(self, _task: str) -> None:
                pass

            def complete_json(self, *_args, **_kwargs):
                raise AssertionError("provider must not be called")

        with patch.object(drama_reviewer, "LLMClient", NoProviderClient):
            with self.assertRaisesRegex(ValueError, "cast is ambiguous"):
                drama_reviewer.run(name, mock=False)

    def test_reviewer_assembly_and_exports_share_frozen_cast(self) -> None:
        name = "projection-chain"
        self._make_drama_workspace(name, "霸总", episode_count=1)
        self._write_setup(name, hook=True)
        storyboard = storyboard_builder.run(name, mock=True)
        write_json(episode_paths(name).storyboard_path, storyboard)
        sheet = _nine_character_sheet()
        write_json(character_paths(name).sheet_path, sheet)

        prompt = drama_reviewer.build_system_prompt(name, episode_no=1)
        self.assertIn("本集主角", prompt)
        self.assertNotIn("未来角色2", prompt)
        self.assertNotIn("PRIVATE_PROMPT_1", prompt)
        self.assertNotIn("PRIVATE_NOTE_1", prompt)

        review = drama_reviewer.run(name, mock=True)
        write_json(episode_paths(name).review_path, review)
        assembled = drama_store.assemble_episode(name)
        self.assertEqual(
            assembled["episode"]["ai_friendly_constraints"]["main_character_count"],
            1,
        )
        self.assertEqual(assembled["meta"]["character_fingerprint_ids"], ["c001"])

        standalone = json.loads(
            drama_store.export_episode(name, format="comfy").body
        )
        standalone_text = json.dumps(standalone, ensure_ascii=False)
        self.assertIn("role_1.safetensors", standalone_text)
        self.assertNotIn("role_2.safetensors", standalone_text)

        package = drama_season_export.export_season(name, mode="master")
        with zipfile.ZipFile(io.BytesIO(package.body)) as archive:
            packaged_workflow = archive.read("episodes/episode_01.comfy.json")
            packaged_characters = archive.read("characters/season_01.json")
        self.assertIn(b"role_1.safetensors", packaged_workflow)
        self.assertNotIn(b"role_2.safetensors", packaged_workflow)
        self.assertIn("未来角色9", packaged_characters.decode("utf-8"))

        meta_path = episode_paths(name).meta_path
        invalid_meta = read_json(meta_path)
        invalid_meta["character_fingerprint_ids"] = []
        write_json(meta_path, invalid_meta)
        self.assertTrue(drama_store.is_episode_stale(name))

    def test_episode_one_video_requires_only_frozen_cast_references(self) -> None:
        name = "projection-video"
        drama_video_smoke._prepare_mock_inputs(name)
        before = drama_video.load_video_inputs(name)
        sheet_path = character_paths(name).sheet_path
        sheet = read_json(sheet_path)
        sheet["characters"].append(
            {
                "id": "c099",
                "name": "未冻结角色",
                "lora_token": "unfrozen_role",
                "appearances": [],
                "reference_images": [],
            }
        )
        write_json(sheet_path, sheet)

        after = drama_video.load_video_inputs(name)
        self.assertEqual(after.fingerprint, before.fingerprint)
        self.assertNotIn(
            "c099", [row["id"] for row in after.characters["characters"]]
        )

    def test_skipped_episode_uses_previous_frozen_cast_across_exports(self) -> None:
        name = "projection-skip"
        self._prepare_episode_one(name, episode_count=2)
        sheet_path = character_paths(name).sheet_path
        season_sheet_before = sheet_path.read_bytes()

        setup_path = self._write_setup(name, hook=True, episode_no=2)
        setup = read_json(setup_path)
        setup["introduces_new_characters"] = False
        write_json(setup_path, setup)
        write_json(
            episode_paths(name, episode_no=2).storyboard_path,
            storyboard_builder.run(name, mock=True, episode_no=2),
        )
        job = self._dispatch_drama_job(name, "review", {"episode_no": 2})
        self.assertEqual(job["status"], "succeeded", job)
        self.assertEqual(sheet_path.read_bytes(), season_sheet_before)

        meta_two = read_json(episode_paths(name, episode_no=2).meta_path)
        self.assertEqual(meta_two["character_fingerprint_ids"], ["c001"])
        standalone = drama_store.export_episode(
            name, episode_no=2, format="comfy"
        ).body
        self.assertIn(b"role_1.safetensors", standalone)
        self.assertNotIn(b"role_2.safetensors", standalone)

        package = drama_season_export.export_season(name, mode="master")
        with zipfile.ZipFile(io.BytesIO(package.body)) as archive:
            episode_two_workflow = archive.read("episodes/episode_02.comfy.json")
            season_characters = archive.read("characters/season_01.json")
        self.assertIn(b"role_1.safetensors", episode_two_workflow)
        self.assertNotIn(b"role_2.safetensors", episode_two_workflow)
        self.assertIn("未来角色9", season_characters.decode("utf-8"))

        # A v1 episode can still have a matching historical whole-sheet hash,
        # but without appearances/frozen ids its single-episode cast is not
        # provable. Readiness must exclude it before export rendering begins.
        ep_two = episode_paths(name, episode_no=2)
        legacy_meta = read_json(ep_two.meta_path)
        legacy_meta["input_fingerprint_version"] = 1
        legacy_meta["character_fingerprint_ids"] = []
        legacy_meta["input_fingerprint"] = drama_store.input_fingerprint(
            setup=read_json(ep_two.setup_path),
            storyboard=read_json(ep_two.storyboard_path),
            characters=read_json(sheet_path),
            review=read_json(ep_two.review_path),
            version=1,
        )
        write_json(ep_two.meta_path, legacy_meta)
        readiness = drama_season_export.public_season_export_readiness(name)
        self.assertEqual(
            readiness["excluded"],
            [{"episode_no": 2, "reason": "stale"}],
        )
        self.assertFalse(readiness["master_ready"])
        self.assertTrue(readiness["snapshot_ready"])
        with self.assertRaises(drama_season_export.SeasonExportConflict):
            drama_season_export.export_season(name, mode="master")

    def test_skip_rejects_misfiled_previous_episode_meta(self) -> None:
        name = "projection-misfiled"
        self._prepare_episode_one(name, episode_count=2)
        setup_path = self._write_setup(name, hook=True, episode_no=2)
        setup = read_json(setup_path)
        setup["introduces_new_characters"] = False
        write_json(setup_path, setup)
        write_json(
            episode_paths(name, episode_no=2).storyboard_path,
            storyboard_builder.run(name, mock=True, episode_no=2),
        )
        previous_meta_path = episode_paths(name).meta_path
        previous_meta = read_json(previous_meta_path)
        previous_meta["episode_no"] = 2
        write_json(previous_meta_path, previous_meta)

        job = self._dispatch_drama_job(name, "review", {"episode_no": 2})
        self.assertEqual(job["status"], "blocked", job)
        self.assertFalse(episode_paths(name, episode_no=2).episode_path.exists())

    def _prepare_episode_one(self, name: str, *, episode_count: int) -> None:
        self._make_drama_workspace(name, "霸总", episode_count=episode_count)
        self._write_setup(name, hook=True)
        write_json(
            episode_paths(name).storyboard_path,
            storyboard_builder.run(name, mock=True),
        )
        sheet = _nine_character_sheet()
        for row in sheet["characters"][1:]:
            row["appearances"] = [3]
        write_json(character_paths(name).sheet_path, sheet)
        write_json(
            episode_paths(name).review_path,
            drama_reviewer.run(name, mock=True),
        )
        drama_store.assemble_episode(name)

    @staticmethod
    def _minimal_episode(*, episode_no: int) -> dict:
        return {
            "schema_version": 1,
            "episode_no": episode_no,
            "season_no": 1,
            "title": "投影测试",
            "logline": "验证单集角色投影",
            "track": "霸总",
            "target_duration_seconds": 60,
            "estimated_duration_seconds": 6,
            "core_setup": {"protagonist": "测试角色"},
            "ai_friendly_constraints": {},
            "narrative": "测试",
            "storyboard": [
                {
                    "shot_no": 1,
                    "shot_size": "特写",
                    "camera_move": "固定",
                    "duration_seconds": 6,
                    "visual_content": "测试画面",
                    "voiceover": "",
                    "dialogue": "",
                    "ai_draw_prompt": "test",
                    "motion_prompt": None,
                    "camera_movement_for_video": None,
                    "is_highlight": True,
                }
            ],
            "ending_hook": {"type": "悬念钩", "content": "测试钩子"},
            "self_check": {"duration_within_tolerance": False},
        }


if __name__ == "__main__":
    import unittest

    unittest.main()
