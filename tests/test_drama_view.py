"""iter 037: drama progress aggregation tests."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from src import paths
from src.cli_workspace import init_workspace
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
        p = paths.WORKSPACE_DIR / "drama" / "outputs" / "episodes" / "episode_01.setup.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

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

    def test_later_stations_locked_in_iter_037(self) -> None:
        self._write_setup({"core_setup": {"protagonist": "p"}, "hook": {"type": "情绪钩"}})
        stations = collect_drama_progress("drama")["stations"]
        self.assertEqual(stations[2]["status"], "locked")
        self.assertEqual(stations[3]["status"], "locked")

    def test_corrupt_optional_json_degrades_to_todo(self) -> None:
        p = paths.WORKSPACE_DIR / "drama" / "outputs" / "episodes" / "episode_01.setup.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{bad", encoding="utf-8")
        self.assertEqual(collect_drama_progress("drama")["stations"][0]["status"], "todo")


if __name__ == "__main__":
    unittest.main()
