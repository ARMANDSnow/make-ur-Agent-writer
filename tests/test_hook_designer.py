"""iter 037: drama station 2 hook designer tests."""

from __future__ import annotations

import json
import unittest

from src import drama_planner, hook_designer, paths
from tests._drama_base import DramaTestBase


TRACKS = ("霸总", "重生", "推理", "系统", "觉醒")


class HookDesignerTests(DramaTestBase):
    def _workspace(self, name: str, track: str = "霸总", *, setup: bool = True, snapshot: bool = True) -> None:
        self._make_drama_workspace(name, track, snapshot=snapshot)
        if setup:
            out = paths.WORKSPACE_DIR / name / "outputs" / "episodes" / "episode_01.setup.json"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(drama_planner.run(name), ensure_ascii=False), encoding="utf-8")

    def test_mock_returns_three_hooks_per_track(self) -> None:
        for idx, track in enumerate(TRACKS):
            with self.subTest(track=track):
                name = f"h{idx}"
                self._workspace(name, track)
                result = hook_designer.run(name)
                self.assertEqual(len(result["hooks"]), 3)
                self.assertEqual([h["type"] for h in result["hooks"]], ["情绪钩", "悬念钩", "反差钩"])

    def test_requires_station_one_setup_file(self) -> None:
        self._workspace("no_setup", setup=False)
        with self.assertRaisesRegex(FileNotFoundError, "station 1"):
            hook_designer.run("no_setup")

    def test_hooks_raises_when_setup_missing_required_fields(self) -> None:
        self._make_drama_workspace("partial", "霸总")
        setup_path = paths.WORKSPACE_DIR / "partial" / "outputs" / "episodes" / "episode_01.setup.json"
        setup_path.parent.mkdir(parents=True, exist_ok=True)
        setup_path.write_text(json.dumps({"track": "霸总"}, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "core_setup"):
            hook_designer.run("partial")

    def test_missing_snapshot_raises(self) -> None:
        self._workspace("no_snapshot", snapshot=False, setup=False)
        setup_path = paths.WORKSPACE_DIR / "no_snapshot" / "outputs" / "episodes" / "episode_01.setup.json"
        setup_path.parent.mkdir(parents=True, exist_ok=True)
        setup_path.write_text(json.dumps({"core_setup": {"protagonist": "x"}}, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(FileNotFoundError, "creation_standard.snapshot"):
            hook_designer.run("no_snapshot")

    def test_unknown_track_raises_value_error(self) -> None:
        self._workspace("bad_track", "未知", setup=False)
        setup_path = paths.WORKSPACE_DIR / "bad_track" / "outputs" / "episodes" / "episode_01.setup.json"
        setup_path.parent.mkdir(parents=True, exist_ok=True)
        setup_path.write_text(json.dumps({"core_setup": {"protagonist": "x"}}, ensure_ascii=False), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "unknown track"):
            hook_designer.run("bad_track")

    def test_real_model_path_is_stubbed(self) -> None:
        self._workspace("stub")
        with self.assertRaisesRegex(NotImplementedError, "iter 040\\+"):
            hook_designer.run("stub", mock=False)

    def test_run_logs_hook_prompt_provenance(self) -> None:
        self._workspace("log_hook")
        hook_designer.run("log_hook")
        log_path = paths.WORKSPACE_DIR / "log_hook" / "logs" / "drama_prompts.jsonl"
        rows = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(rows[-1]["agent"], "hook_designer")
        self.assertGreater(rows[-1]["prompt_chars"], 0)

    def test_hook_designer_does_not_persist_selected_hook(self) -> None:
        self._workspace("read_only")
        hook_designer.run("read_only")
        setup = json.loads(
            (paths.WORKSPACE_DIR / "read_only" / "outputs" / "episodes" / "episode_01.setup.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertNotIn("hook", setup)


if __name__ == "__main__":
    unittest.main()
