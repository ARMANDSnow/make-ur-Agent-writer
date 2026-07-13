"""iter 088: deterministic drama export contracts and safety boundaries."""

from __future__ import annotations

import csv
import io
import json

from src import character_designer, drama_reviewer, drama_store, storyboard_builder
from src.comfy_workflow_exporter import GENERATOR_VERSION, build_workflow
from src.drama_schemas import character_paths, episode_paths
from src.utils import write_json
from tests._drama_base import DramaTestBase


def _minimal_episode(*, episode_no: int = 1) -> dict:
    return {
        "schema_version": 1,
        "episode_no": episode_no,
        "season_no": 1,
        "title": "管道 | 里的雨",
        "logline": "一句话梳理故事",
        "track": "推理",
        "target_duration_seconds": 60,
        "estimated_duration_seconds": 6,
        "core_setup": {"protagonist": "调查员"},
        "ai_friendly_constraints": {},
        "narrative": "他沿着水声走进地下室。",
        "storyboard": [
            {
                "shot_no": 1,
                "shot_size": "特写",
                "camera_move": "固定",
                "duration_seconds": 6,
                "visual_content": '管道,锈迹 "A"\n水滴',
                "voiceover": "听。",
                "dialogue": "这不是雨。",
                "ai_draw_prompt": "rusted pipe, cold blue light",
                "motion_prompt": None,
                "camera_movement_for_video": None,
                "is_highlight": True,
            }
        ],
        "ending_hook": {"type": "悬念钩", "content": "管道里传来敲击声"},
        "self_check": {"duration_within_tolerance": False},
    }


def _minimal_characters(*, episode_no: int = 1) -> dict:
    return {
        "schema_version": 1,
        "season_no": 1,
        "episode_no": episode_no,
        "track": "推理",
        "source_storyboard_title": "管道里的雨",
        "characters": [
            {
                "id": "c001",
                "name": "林默",
                "lora_token": "lin_mo",
                "visual_signature": "左眼下疤痕",
                "prompt_template_sd": "Chinese detective, scar under left eye",
                "appearances": [episode_no],
            }
        ],
    }


class DramaExportTests(DramaTestBase):
    def _assembled_workspace(self, name: str = "exports") -> None:
        self._make_drama_workspace(name, "霸总")
        self._write_setup(name, hook=True)
        board = storyboard_builder.run(name, mock=True)
        write_json(episode_paths(name).storyboard_path, board)
        sheet = character_designer.run(name, mock=True)
        write_json(character_paths(name).sheet_path, sheet)
        review = drama_reviewer.run(name, mock=True)
        write_json(episode_paths(name).review_path, review)
        drama_store.assemble_episode(name)

    def test_markdown_and_csv_golden_contracts(self) -> None:
        episode = _minimal_episode()
        markdown = drama_store.to_markdown_table(episode)
        self.assertEqual(
            markdown,
            "# 管道 \\| 里的雨\n"
            "\n"
            "- episode_no: 1\n"
            "- season_no: 1\n"
            "- track: 推理\n"
            "- duration: 6s / 60s\n"
            "- ending_hook: 悬念钩 - 管道里传来敲击声\n"
            "\n"
            "## Narrative\n"
            "\n"
            "他沿着水声走进地下室。\n"
            "\n"
            "## Storyboard\n"
            "\n"
            "| shot_no | shot_size | camera_move | duration_seconds | visual_content | voiceover | dialogue | ai_draw_prompt | is_highlight |\n"
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n"
            "| 1 | 特写 | 固定 | 6 | 管道,锈迹 \"A\"<br>水滴 | 听。 | 这不是雨。 | rusted pipe, cold blue light | true |\n",
        )

        payload = drama_store.to_csv(episode)
        self.assertTrue(payload.startswith(b"\xef\xbb\xbf"))
        decoded = payload.decode("utf-8-sig")
        self.assertIn('"\u7ba1\u9053,\u9508\u8ff9 ""A""\n\u6c34\u6ef4"', decoded)
        rows = list(csv.DictReader(io.StringIO(decoded, newline="")))
        self.assertEqual(rows[0]["visual_content"], '管道,锈迹 "A"\n水滴')
        self.assertEqual(rows[0]["is_highlight"], "true")

    def test_csv_neutralizes_spreadsheet_formulas(self) -> None:
        episode = _minimal_episode()
        episode["storyboard"][0]["dialogue"] = '=HYPERLINK("https://example.invalid","x")'
        decoded = drama_store.to_csv(episode).decode("utf-8-sig")
        rows = list(csv.DictReader(io.StringIO(decoded, newline="")))
        self.assertTrue(rows[0]["dialogue"].startswith("'=HYPERLINK"))

    def test_markdown_neutralizes_raw_html(self) -> None:
        episode = _minimal_episode()
        episode["title"] = '<img src=x onerror="boom">'
        episode["narrative"] = "<script>alert(1)</script>"
        episode["storyboard"][0]["visual_content"] = "<svg onload=boom>"
        markdown = drama_store.to_markdown_table(episode)
        self.assertNotIn("<script>", markdown)
        self.assertNotIn("<img", markdown)
        self.assertNotIn("<svg", markdown)
        self.assertIn("&lt;script&gt;", markdown)
        self.assertIn("&lt;img", markdown)

    def test_all_exports_use_fixed_filenames_and_persist(self) -> None:
        self._assembled_workspace()
        source = episode_paths("exports").episode_path.read_bytes()
        expected = {
            "json": "episode_01.json",
            "md": "episode_01.storyboard.md",
            "csv": "episode_01.storyboard.csv",
            "comfy": "episode_01.comfy.json",
        }
        for export_format, filename in expected.items():
            with self.subTest(format=export_format):
                artifact = drama_store.export_episode(
                    "exports", episode_no=1, format=export_format
                )
                self.assertEqual(artifact.filename, filename)
                self.assertEqual(artifact.path.name, filename)
                self.assertEqual(artifact.path.read_bytes(), artifact.body)
                self.assertFalse(artifact.stale)
        self.assertEqual(source, drama_store.export_episode("exports", format="json").body)
        comfy = json.loads(
            (episode_paths("exports").episodes_dir / "episode_01.comfy.json").read_text(
                encoding="utf-8"
            )
        )
        episode = json.loads(source)
        classes = [
            node.get("class_type")
            for node in comfy.values()
            if isinstance(node, dict)
        ]
        shot_count = len(episode["storyboard"])
        self.assertEqual(comfy["_generator"], GENERATOR_VERSION)
        self.assertEqual(classes.count("CheckpointLoaderSimple"), shot_count)
        self.assertEqual(classes.count("KSampler"), shot_count)
        self.assertEqual(classes.count("VAEDecode"), shot_count)
        self.assertEqual(classes.count("SaveImage"), shot_count)
        self.assertFalse(list(episode_paths("exports").episodes_dir.glob("*.tmp.*")))

    def test_comfy_workflow_has_one_save_per_shot_and_active_character_prompt(self) -> None:
        episode = _minimal_episode()
        characters = _minimal_characters()
        characters["characters"].append(
            {
                "id": "c002",
                "name": "未出场角色",
                "lora_token": "absent_role",
                "prompt_template_sd": "THIS PROMPT MUST NOT APPEAR",
                "appearances": [2],
            }
        )
        workflow = build_workflow(episode, characters)
        self.assertEqual(workflow["_generator"], GENERATOR_VERSION)
        nodes = [value for key, value in workflow.items() if key.isdigit()]
        save_nodes = [node for node in nodes if node["class_type"] == "SaveImage"]
        self.assertEqual(len(save_nodes), len(episode["storyboard"]))
        encoded = json.dumps(workflow, ensure_ascii=False)
        self.assertIn("Chinese detective, scar under left eye", encoded)
        self.assertIn("lin_mo.safetensors", encoded)
        self.assertNotIn("THIS PROMPT MUST NOT APPEAR", encoded)
        self.assertNotIn("absent_role.safetensors", encoded)
        self.assertNotIn("http://", encoded)
        self.assertNotIn("https://", encoded)

    def test_episode_two_comfy_reuses_season_cast_when_station_four_skips(self) -> None:
        episode = _minimal_episode(episode_no=2)
        characters = _minimal_characters(episode_no=1)
        workflow = build_workflow(episode, characters)
        encoded = json.dumps(workflow, ensure_ascii=False)
        self.assertIn("Chinese detective, scar under left eye", encoded)
        self.assertIn("lin_mo.safetensors", encoded)

    def test_format_is_an_exact_whitelist(self) -> None:
        self._assembled_workspace()
        for invalid in ("../../", "JSON", "json/../csv", "", None, True):
            with self.subTest(format=invalid):
                with self.assertRaisesRegex(ValueError, "format must be one of"):
                    drama_store.export_episode("exports", format=invalid)  # type: ignore[arg-type]
        names = {path.name for path in episode_paths("exports").episodes_dir.iterdir()}
        self.assertNotIn("csv", names)

    def test_missing_episode_fails_without_creating_export(self) -> None:
        self._make_drama_workspace("missing", "霸总")
        for export_format in drama_store.EXPORT_FORMATS:
            with self.subTest(format=export_format):
                with self.assertRaises(FileNotFoundError):
                    drama_store.export_episode("missing", format=export_format)
        self.assertFalse(list(episode_paths("missing").episodes_dir.glob("episode_*")))

    def test_stale_episode_export_fails_closed(self) -> None:
        self._assembled_workspace()
        ep = episode_paths("exports")
        board = json.loads(ep.storyboard_path.read_text(encoding="utf-8"))
        board["title"] = "站点文件已修改"
        write_json(ep.storyboard_path, board)

        with self.assertRaisesRegex(ValueError, "stale or no longer approved"):
            drama_store.export_episode("exports", format="md")
        self.assertFalse((ep.episodes_dir / "episode_01.storyboard.md").exists())

    def test_list_episodes_uses_numeric_sort_and_skips_dirty_numbers(self) -> None:
        self._make_drama_workspace("listing", "霸总")
        ep_dir = episode_paths("listing").episodes_dir
        for number in (100, 10, 2):
            payload = _minimal_episode(episode_no=number)
            write_json(episode_paths("listing", episode_no=number).episode_path, payload)
        write_json(ep_dir / "episode_03.json", {"episode_no": "3"})
        write_json(ep_dir / "episode_04.json", {"episode_no": True})
        write_json(ep_dir / "episode_05.json", {"episode_no": 6})

        self.assertEqual(
            [item["episode_no"] for item in drama_store.list_episodes("listing")],
            [2, 10, 100],
        )


if __name__ == "__main__":
    import unittest

    unittest.main()
