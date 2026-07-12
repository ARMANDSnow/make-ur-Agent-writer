"""iter 037: drama station 1 planner tests."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from src import drama_planner, paths
from src.config import load_config
from src.cli_workspace import init_workspace
from src.drama_schemas import MAX_DRAMA_EPISODE_NO, episode_paths, normalize_episode_no
from tests._drama_base import DramaTestBase


TRACKS = ("霸总", "重生", "推理", "系统", "觉醒")


class DramaPlannerTests(DramaTestBase):
    def _workspace(self, name: str, track: str = "霸总", *, snapshot: bool = True) -> None:
        self._make_drama_workspace(name, track, snapshot=snapshot)

    def test_mock_returns_fixture_per_track(self) -> None:
        for idx, track in enumerate(TRACKS):
            with self.subTest(track=track):
                name = f"d{idx}"
                self._workspace(name, track)
                result = drama_planner.run(name, mock=True)
                self.assertEqual(result["track"], track)
                self.assertEqual(result["episode_no"], 1)
                self.assertIn("core_setup", result)

    def test_target_duration_follows_wizard_input(self) -> None:
        self._workspace("duration_case", "霸总")
        p = paths.WORKSPACE_DIR / "duration_case" / "data" / "wizard_input.json"
        data = json.loads(p.read_text(encoding="utf-8"))
        data["episode_duration_seconds"] = 90
        p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(drama_planner.run("duration_case")["target_duration_seconds"], 90)

    def test_episode_number_normalization_is_strict_and_bounded(self) -> None:
        self.assertEqual(MAX_DRAMA_EPISODE_NO, 100)
        self.assertEqual(normalize_episode_no(2), 2)
        self.assertEqual(normalize_episode_no("02"), 2)
        self.assertEqual(episode_paths("strict", episode_no="02").setup_path.name, "episode_02.setup.json")
        for value in (True, False, 1.0, float("nan"), " 2", "+2", "2.0", "", 0, -1, 101):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "episode_no"):
                    normalize_episode_no(value)

    def test_episode_two_inherits_previous_setup_without_prompt_or_mutation(self) -> None:
        self._workspace("inherit", "重生")
        first = drama_planner.run("inherit", mock=True)
        first["hook"] = {"type": "悬念钩", "content": "第一集已用钩子"}
        first_path = episode_paths("inherit").setup_path
        first_path.parent.mkdir(parents=True, exist_ok=True)
        first_path.write_text(json.dumps(first, ensure_ascii=False), encoding="utf-8")
        before = first_path.read_text(encoding="utf-8")

        with patch.object(drama_planner, "_log_prompt") as log_prompt:
            second = drama_planner.run("inherit", mock=False, episode_no=2)

        self.assertEqual(second["episode_no"], 2)
        self.assertEqual(second["track"], first["track"])
        self.assertEqual(second["target_duration_seconds"], first["target_duration_seconds"])
        self.assertEqual(second["core_setup"], first["core_setup"])
        self.assertNotIn("hook", second)
        self.assertEqual(first_path.read_text(encoding="utf-8"), before)
        log_prompt.assert_not_called()

    def test_episode_two_requires_previous_setup(self) -> None:
        self._workspace("missing_previous", "重生")
        with self.assertRaisesRegex(FileNotFoundError, "previous episode"):
            drama_planner.run("missing_previous", episode_no=2)

    def test_unknown_track_raises_value_error(self) -> None:
        self._workspace("bad_track", "未知")
        with self.assertRaisesRegex(ValueError, "unknown track"):
            drama_planner.run("bad_track")

    def test_missing_wizard_input_raises(self) -> None:
        init_workspace("no_input", type="drama")
        with self.assertRaisesRegex(FileNotFoundError, "wizard_input"):
            drama_planner.run("no_input")

    def test_missing_snapshot_raises(self) -> None:
        self._workspace("no_snapshot", snapshot=False)
        with self.assertRaisesRegex(FileNotFoundError, "creation_standard.snapshot"):
            drama_planner.run("no_snapshot")

    def test_real_model_path_is_stubbed(self) -> None:
        self._workspace("stub")
        with self.assertRaisesRegex(NotImplementedError, "iter 040\\+"):
            drama_planner.run("stub", mock=False)

    def test_prompt_contains_creation_standard_snapshot(self) -> None:
        self._workspace("prompt_case")
        prompt = drama_planner.build_system_prompt("prompt_case", "drama_planner")
        self.assertIn("3 秒法则", prompt)
        self.assertIn("60 秒的内部节奏", prompt)

    def test_run_logs_prompt_provenance_without_prompt_text(self) -> None:
        self._workspace("log_case")
        drama_planner.run("log_case")
        log_path = paths.WORKSPACE_DIR / "log_case" / "logs" / "drama_prompts.jsonl"
        rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(rows[-1]["agent"], "drama_planner")
        self.assertGreater(rows[-1]["prompt_chars"], 0)
        self.assertNotIn("prompt", rows[-1])

    def test_drama_agents_config_points_to_snapshot_not_global_doc(self) -> None:
        agents = load_config("agents.yaml")
        drama_agents = agents["drama_agents"]
        for agent in ("drama_planner", "hook_designer"):
            self.assertEqual(drama_agents[agent]["provider"], "mock_only")
            self.assertEqual(drama_agents[agent]["system_prompt_snapshot"], "data/creation_standard.snapshot.md")
            self.assertNotIn("system_prompt_base", drama_agents[agent])


if __name__ == "__main__":
    unittest.main()
