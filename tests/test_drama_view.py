"""iter 037: drama progress aggregation tests."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from src import paths
from src.cli_workspace import init_workspace
from src.drama_schemas import episode_paths
from src.web.drama_view import collect_drama_progress


class DramaViewTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["OPENAI_MODEL"] = "mock"
        self._tmp = tempfile.TemporaryDirectory()
        self._saved_ws_dir = paths.WORKSPACE_DIR
        self._saved_env = os.environ.get("WORKSPACE_NAME")
        os.environ.pop("WORKSPACE_NAME", None)
        paths.WORKSPACE_DIR = Path(self._tmp.name)
        init_workspace("drama", type="drama")

    def tearDown(self) -> None:
        paths.WORKSPACE_DIR = self._saved_ws_dir
        if self._saved_env is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._saved_env
        self._tmp.cleanup()

    def _write_setup(self, payload: dict) -> None:
        p = episode_paths("drama").setup_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def _write_storyboard(self) -> None:
        p = episode_paths("drama").storyboard_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "season_no": 1,
                    "episode_no": 1,
                    "track": "霸总",
                    "title": "t",
                    "target_duration_seconds": 60,
                    "hook": {"type": "反差钩"},
                    "narrative": "n",
                    "shots": [
                        {
                            "shot_no": i,
                            "beat": "b",
                            "shot_size": "特写" if i == 1 else "中景",
                            "camera_movement": "固定",
                            "duration_seconds": 10 if i == 6 else (3 if i == 1 else 11),
                            "visual": "v",
                            "narration": "",
                            "dialogue": "",
                            "ai_draw_prompt": "",
                            "is_highlight": i == 4,
                        }
                        for i in range(1, 7)
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def _write_invalid_double_highlight_storyboard(self) -> None:
        self._write_storyboard()
        p = episode_paths("drama").storyboard_path
        data = json.loads(p.read_text(encoding="utf-8"))
        data["shots"][0]["is_highlight"] = True
        data["shots"][1]["is_highlight"] = True
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def test_empty_workspace_statuses(self) -> None:
        data = collect_drama_progress("drama")
        self.assertEqual([s["id"] for s in data["stations"]], ["setup", "hook", "storyboard", "characters"])
        self.assertEqual([s["status"] for s in data["stations"]], ["todo", "locked", "locked", "locked"])
        self.assertIsNone(data["wizard_input"])

    def test_wizard_input_is_returned_when_present(self) -> None:
        p = paths.WORKSPACE_DIR / "drama" / "data" / "wizard_input.json"
        p.write_text(json.dumps({"track": "霸总"}, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(collect_drama_progress("drama")["wizard_input"]["track"], "霸总")

    def test_setup_done_requires_protagonist(self) -> None:
        self._write_setup({"core_setup": {"antagonist": "x"}})
        self.assertEqual([s["status"] for s in collect_drama_progress("drama")["stations"][:2]], ["todo", "locked"])
        self._write_setup({"core_setup": {"protagonist": "p", "antagonist": "a"}})
        self.assertEqual([s["status"] for s in collect_drama_progress("drama")["stations"][:2]], ["done", "todo"])

    def test_hook_done_requires_hook_type(self) -> None:
        self._write_setup({"core_setup": {"protagonist": "p"}, "hook": {"content": "x"}})
        self.assertEqual(collect_drama_progress("drama")["stations"][1]["status"], "todo")
        self._write_setup({"core_setup": {"protagonist": "p"}, "hook": {"type": "情绪钩", "content": "x"}})
        self.assertEqual(collect_drama_progress("drama")["stations"][1]["status"], "done")

    def test_storyboard_todo_after_hook_and_done_after_file_exists(self) -> None:
        self._write_setup({"core_setup": {"protagonist": "p"}, "hook": {"type": "情绪钩"}})
        stations = collect_drama_progress("drama")["stations"]
        self.assertEqual(stations[2]["status"], "todo")
        self.assertEqual(stations[3]["status"], "locked")
        self._write_storyboard()
        stations = collect_drama_progress("drama")["stations"]
        self.assertEqual(stations[2]["status"], "done")
        self.assertEqual(stations[3]["status"], "locked")

    def test_storyboard_invalid_file_does_not_mark_done(self) -> None:
        self._write_setup({"core_setup": {"protagonist": "p"}, "hook": {"type": "情绪钩"}})
        self._write_invalid_double_highlight_storyboard()
        stations = collect_drama_progress("drama")["stations"]
        self.assertEqual(stations[2]["status"], "todo")

    def test_corrupt_optional_json_degrades_to_todo(self) -> None:
        p = episode_paths("drama").setup_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{bad", encoding="utf-8")
        self.assertEqual(collect_drama_progress("drama")["stations"][0]["status"], "todo")


if __name__ == "__main__":
    unittest.main()
