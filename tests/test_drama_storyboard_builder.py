"""iter 080: drama station 3 storyboard builder tests."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from src import character_designer, storyboard_builder
from src.drama_schemas import (
    DramaStoryboard,
    StoryboardShot,
    character_paths,
    episode_paths,
    validate_storyboard_soft,
)
from tests._drama_base import DramaTestBase


TRACKS = ("霸总", "重生", "推理", "系统", "觉醒")


class StoryboardBuilderTests(DramaTestBase):
    def _workspace(self, name: str, track: str = "霸总", *, hook: bool = True) -> None:
        self._make_drama_workspace(name, track)
        self._write_setup(name, hook=hook)

    def _episode_two_workspace(self, name: str, track: str = "重生") -> dict:
        self._workspace(name, track)
        first_board = storyboard_builder.run(name, mock=True)
        first_paths = episode_paths(name)
        first_paths.storyboard_path.write_text(json.dumps(first_board, ensure_ascii=False), encoding="utf-8")
        sheet = character_designer.run(name, mock=True)
        cp = character_paths(name)
        cp.sheet_path.parent.mkdir(parents=True, exist_ok=True)
        cp.sheet_path.write_text(json.dumps(sheet, ensure_ascii=False), encoding="utf-8")
        self._write_setup(name, hook=True, episode_no=2)
        return sheet

    def test_mock_returns_valid_storyboard_per_track(self) -> None:
        for idx, track in enumerate(TRACKS):
            with self.subTest(track=track):
                name = f"sb{idx}"
                self._workspace(name, track)
                result = storyboard_builder.run(name, mock=True)
                board = DramaStoryboard(**result)
                self.assertEqual(board.track, track)
                self.assertEqual(len(board.shots), 6)
                self.assertEqual(sum(s.duration_seconds for s in board.shots), 60)
                self.assertEqual(sum(1 for s in board.shots if s.is_highlight), 1)
                self.assertEqual(result["soft_warnings"], [])
                self.assertNotIn("alt_shots", result)

    def test_requires_selected_hook(self) -> None:
        self._workspace("no_hook", hook=False)
        with self.assertRaisesRegex(ValueError, "station 2"):
            storyboard_builder.run("no_hook", mock=True)

    def test_missing_setup_raises_file_not_found(self) -> None:
        self._make_drama_workspace("no_setup", "霸总")
        with self.assertRaisesRegex(FileNotFoundError, "station 2"):
            storyboard_builder.run("no_setup", mock=True)

    def test_rewrite_shot_only_replaces_target(self) -> None:
        self._workspace("rewrite_case", "霸总")
        original = storyboard_builder.run("rewrite_case", mock=True)
        p = episode_paths("rewrite_case").storyboard_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")

        updated = storyboard_builder.rewrite_shot("rewrite_case", 3, mock=True)

        self.assertNotEqual(updated["shots"][2]["visual"], original["shots"][2]["visual"])
        before = [s for i, s in enumerate(original["shots"]) if i != 2]
        after = [s for i, s in enumerate(updated["shots"]) if i != 2]
        self.assertEqual(after, before)

    def test_real_rewrite_prompt_receives_current_storyboard_context(self) -> None:
        self._workspace("real_rewrite_context", "霸总")
        original = storyboard_builder.run("real_rewrite_context", mock=True)
        p = episode_paths("real_rewrite_context").storyboard_path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")
        captured = {}

        class FakeClient:
            is_mock = False

            def __init__(self, task: str) -> None:
                self.task = task

            def complete_json(self, messages, response_model):
                captured["messages"] = messages
                return StoryboardShot(
                    shot_no=3,
                    beat="真实重写",
                    shot_size="近景",
                    camera_movement="推",
                    duration_seconds=12,
                    visual="真实模型替换镜头",
                    narration="",
                    dialogue="证据到了。",
                    ai_draw_prompt="会议桌证据特写",
                    is_highlight=False,
                )

        with patch.object(storyboard_builder, "LLMClient", FakeClient):
            updated = storyboard_builder.rewrite_shot("real_rewrite_context", 3, mock=False)

        self.assertEqual(updated["shots"][2]["visual"], "真实模型替换镜头")
        user_msg = captured["messages"][1]["content"]
        self.assertIn("当前分镜上下文", user_msg)
        self.assertIn(original["shots"][2]["visual"], user_msg)

    def test_soft_warning_allows_missing_highlight(self) -> None:
        self._workspace("soft_case", "霸总")
        data = storyboard_builder.run("soft_case", mock=True)
        for shot in data["shots"]:
            shot["is_highlight"] = False
        self.assertIn("highlight_missing", validate_storyboard_soft(data))

    def test_prompt_contains_snapshot_and_setup(self) -> None:
        self._workspace("prompt_case", "霸总")
        prompt = storyboard_builder.build_system_prompt("prompt_case")
        self.assertIn("3 秒法则", prompt)
        self.assertIn("测试钩子", prompt)

    def test_episode_two_is_pinned_and_prompt_contains_season_visual_signatures(self) -> None:
        sheet = self._episode_two_workspace("episode_two_board")
        result = storyboard_builder.run("episode_two_board", mock=True, episode_no=2)
        self.assertEqual(result["episode_no"], 2)
        prompt = storyboard_builder.build_system_prompt("episode_two_board", episode_no=2)
        self.assertIn(sheet["characters"][0]["visual_signature"], prompt)
        self.assertIn("本季角色视觉签名", prompt)

    def test_real_result_episode_number_is_server_pinned(self) -> None:
        self._episode_two_workspace("real_episode_two")
        mock_result = storyboard_builder.run("real_episode_two", mock=True, episode_no=2)
        expected = DramaStoryboard(**{**mock_result, "episode_no": 1})

        class FakeClient:
            is_mock = False

            def __init__(self, task: str) -> None:
                self.task = task

            def complete_json(self, messages, response_model):
                return expected

        with patch.object(storyboard_builder, "LLMClient", FakeClient):
            result = storyboard_builder.run("real_episode_two", mock=False, episode_no=2)
        self.assertEqual(result["episode_no"], 2)


if __name__ == "__main__":
    unittest.main()
