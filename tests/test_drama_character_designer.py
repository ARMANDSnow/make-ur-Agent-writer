"""iter 081: drama station 4 character designer tests."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from src import character_designer, storyboard_builder
from src.drama_schemas import CharacterSheet, character_paths, episode_paths
from tests._drama_base import DramaTestBase


TRACKS = ("霸总", "重生", "推理", "系统", "觉醒")


class CharacterDesignerTests(DramaTestBase):
    def _workspace(self, name: str, track: str = "霸总", *, storyboard: bool = True) -> None:
        self._make_drama_workspace(name, track)
        self._write_setup(name, hook=True)
        if storyboard:
            board = storyboard_builder.run(name, mock=True)
            p = episode_paths(name).storyboard_path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(board, ensure_ascii=False), encoding="utf-8")

    def test_mock_returns_valid_character_sheet_per_track(self) -> None:
        for idx, track in enumerate(TRACKS):
            with self.subTest(track=track):
                name = f"chars{idx}"
                self._workspace(name, track)
                result = character_designer.run(name, mock=True)
                sheet = CharacterSheet(**result)
                self.assertEqual(sheet.track, track)
                self.assertGreaterEqual(len(sheet.characters), 2)
                ids = {character.id for character in sheet.characters}
                self.assertIn("c001", ids)
                self.assertIn("c002", ids)
                self.assertTrue(all(character.lora_token.isascii() for character in sheet.characters))

    def test_requires_storyboard(self) -> None:
        self._workspace("missing_board", storyboard=False)
        with self.assertRaisesRegex(FileNotFoundError, "station 3"):
            character_designer.run("missing_board", mock=True)

    def test_merge_preserves_manual_override_and_appends_suggestion(self) -> None:
        self._workspace("merge_locked")
        incoming = character_designer.run("merge_locked", mock=True)
        existing = json.loads(json.dumps(incoming, ensure_ascii=False))
        existing["characters"][0]["manual_override"] = True
        existing["characters"][0]["name"] = "用户手改名"
        incoming["characters"][0]["name"] = "新 agent 名"

        merged = character_designer.merge_character_sheet(existing, incoming)

        self.assertEqual(merged["characters"][0]["name"], "用户手改名")
        self.assertTrue(merged["characters"][0]["manual_override"])
        self.assertEqual(merged["characters"][0]["agent_suggestions"][0]["character"]["name"], "新 agent 名")

    def test_merge_caps_locked_agent_suggestions(self) -> None:
        self._workspace("merge_suggestion_cap")
        incoming = character_designer.run("merge_suggestion_cap", mock=True)
        existing = json.loads(json.dumps(incoming, ensure_ascii=False))
        existing["characters"][0]["manual_override"] = True
        existing["characters"][0]["agent_suggestions"] = [
            {"source": "old", "character": {**incoming["characters"][0], "name": f"旧建议{i:02d}"}}
            for i in range(12)
        ]
        incoming["characters"][0]["name"] = "最新建议"

        merged = character_designer.merge_character_sheet(existing, incoming)

        suggestions = merged["characters"][0]["agent_suggestions"]
        self.assertEqual(len(suggestions), 12)
        self.assertEqual(suggestions[-1]["character"]["name"], "最新建议")
        self.assertEqual(suggestions[0]["character"]["name"], "旧建议01")

    def test_merge_overwrites_unlocked_and_appends_new_character(self) -> None:
        self._workspace("merge_open")
        incoming = character_designer.run("merge_open", mock=True)
        existing = json.loads(json.dumps(incoming, ensure_ascii=False))
        existing["characters"][0]["name"] = "旧名字"
        incoming["characters"][0]["name"] = "新名字"
        incoming["characters"].append({**incoming["characters"][0], "id": "c003", "name": "新增角色", "lora_token": "new_role"})

        merged = character_designer.merge_character_sheet(existing, incoming)

        self.assertEqual(merged["characters"][0]["name"], "新名字")
        self.assertIn("c003", {character["id"] for character in merged["characters"]})

    def test_merge_preserves_unlocked_reference_images(self) -> None:
        self._workspace("merge_refs")
        incoming = character_designer.run("merge_refs", mock=True)
        existing = json.loads(json.dumps(incoming, ensure_ascii=False))
        existing["characters"][0]["reference_images"] = [
            {
                "path": "data/character_refs/c001/portrait_neutral.svg",
                "generated_by": "placeholder_svg",
                "prompt": "旧参考图",
                "seed": 0,
            }
        ]
        incoming["characters"][0]["name"] = "新名字"

        merged = character_designer.merge_character_sheet(existing, incoming)

        self.assertEqual(merged["characters"][0]["name"], "新名字")
        self.assertEqual(
            merged["characters"][0]["reference_images"][0]["path"],
            "data/character_refs/c001/portrait_neutral.svg",
        )

    def test_merge_locked_character_still_updates_episode_appearances(self) -> None:
        self._workspace("merge_locked_appearances")
        existing = character_designer.run("merge_locked_appearances", mock=True)
        existing["characters"][0]["manual_override"] = True
        incoming = json.loads(json.dumps(existing, ensure_ascii=False))
        incoming["episode_no"] = 2
        incoming["characters"][0]["appearances"] = [1, 2]
        incoming["characters"][0]["visual_signature"] = "不应覆盖的 agent 新视觉"

        merged = character_designer.merge_character_sheet(existing, incoming)

        self.assertEqual(merged["characters"][0]["appearances"], [1, 2])
        self.assertNotEqual(
            merged["characters"][0]["visual_signature"],
            "不应覆盖的 agent 新视觉",
        )

    def test_merge_rejects_bad_ids(self) -> None:
        self._workspace("merge_bad")
        incoming = character_designer.run("merge_bad", mock=True)
        incoming["characters"][0]["id"] = "bad"
        with self.assertRaises(ValueError):
            character_designer.merge_character_sheet(None, incoming)

    def test_reuse_character_sheet_returns_episode_view_without_mutating_season_source(self) -> None:
        self._workspace("reuse_sheet")
        existing = character_designer.run("reuse_sheet", mock=True)
        before = json.dumps(existing, ensure_ascii=False, sort_keys=True)

        view = character_designer.reuse_character_sheet_for_episode(existing, episode_no=2)

        self.assertEqual(CharacterSheet(**view).episode_no, 2)
        self.assertTrue(all(row["appearances"] == [1, 2] for row in view["characters"]))
        self.assertTrue(all(row["appearances"] == [1] for row in existing["characters"]))
        self.assertEqual(existing["episode_no"], 1)
        self.assertEqual(json.dumps(existing, ensure_ascii=False, sort_keys=True), before)

    def test_real_episode_two_result_is_server_pinned(self) -> None:
        self._workspace("real_character_ep2", "重生")
        self._write_setup("real_character_ep2", hook=True, episode_no=2)
        second_board = storyboard_builder.run("real_character_ep2", mock=True, episode_no=2)
        episode_paths("real_character_ep2", episode_no=2).storyboard_path.write_text(
            json.dumps(second_board, ensure_ascii=False),
            encoding="utf-8",
        )
        expected = CharacterSheet(**character_designer.run("real_character_ep2", mock=True, episode_no=2))
        expected_data = expected.model_dump() if hasattr(expected, "model_dump") else expected.dict()
        expected = CharacterSheet(**{**expected_data, "episode_no": 1})

        class FakeClient:
            is_mock = False

            def __init__(self, task: str) -> None:
                self.task = task

            def complete_json(self, messages, response_model):
                return expected

        with patch.object(character_designer, "LLMClient", FakeClient):
            result = character_designer.run("real_character_ep2", mock=False, episode_no=2)
        self.assertEqual(result["episode_no"], 2)

    def test_real_prompt_uses_drama_character_task(self) -> None:
        self._workspace("real_character", "霸总")
        captured = {}
        expected = CharacterSheet(**character_designer.run("real_character", mock=True))

        class FakeClient:
            is_mock = False

            def __init__(self, task: str) -> None:
                captured["task"] = task

            def complete_json(self, messages, response_model):
                captured["messages"] = messages
                captured["response_model"] = response_model
                return expected

        with patch.object(character_designer, "LLMClient", FakeClient):
            result = character_designer.run("real_character", mock=False)

        self.assertEqual(captured["task"], "drama_character")
        self.assertIs(captured["response_model"], CharacterSheet)
        self.assertIn("已完成站③分镜", captured["messages"][0]["content"])
        self.assertEqual(result["characters"][0]["id"], "c001")


if __name__ == "__main__":
    unittest.main()
