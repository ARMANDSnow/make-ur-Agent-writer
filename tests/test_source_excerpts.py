"""Iter 023 P1: tests for src/source_excerpts.py.

Covers:
* load_excerpts gracefully returns [] when excerpts.json absent
* select_for_chapter returns [] for None / empty plan / k<=0
* select_for_chapter ranks by scene_type match + character_focus
* format_excerpts_for_prompt produces structured block
* Empty / malformed excerpts handled
"""

import json
import os
import shutil
import unittest
from pathlib import Path


class SourceExcerptsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_ws = os.environ.get("WORKSPACE_NAME")
        os.environ["WORKSPACE_NAME"] = "iter023excerpts"
        repo_root = Path(__file__).resolve().parent.parent
        self.ws_root = repo_root / "workspaces" / "iter023excerpts"
        (self.ws_root / "data" / "source_excerpts").mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        if self.ws_root.exists():
            shutil.rmtree(self.ws_root)
        if self._old_ws is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._old_ws

    def _write_excerpts(self, items):
        (self.ws_root / "data" / "source_excerpts" / "excerpts.json").write_text(
            json.dumps({"version": 1, "excerpts": items}, ensure_ascii=False),
            encoding="utf-8",
        )

    def test_load_excerpts_missing_returns_empty(self) -> None:
        from src import source_excerpts
        self.assertEqual(source_excerpts.load_excerpts(), [])

    def test_select_for_chapter_none_or_empty(self) -> None:
        from src import source_excerpts
        self._write_excerpts([
            {"id": "ex_001", "scene_type": "战斗", "excerpt_text": "x", "tags": [], "character_focus": []}
        ])
        self.assertEqual(source_excerpts.select_for_chapter(None), [])
        self.assertEqual(source_excerpts.select_for_chapter({}, k=3), [])
        self.assertEqual(source_excerpts.select_for_chapter({"key_events": ["事件"]}, k=0), [])

    def test_select_ranks_by_scene_type_match(self) -> None:
        from src import source_excerpts
        self._write_excerpts([
            {"id": "battle", "scene_type": "战斗", "character_focus": ["路明非"],
             "tags": ["对决"], "excerpt_text": "battle text"},
            {"id": "talk", "scene_type": "对话", "character_focus": ["诺诺"],
             "tags": ["图书馆"], "excerpt_text": "talk text"},
            {"id": "psyche", "scene_type": "心理", "character_focus": ["路明非"],
             "tags": ["梦"], "excerpt_text": "psyche text"},
        ])
        plan = {
            "opening_scene": "路明非站在高架路上瞄准奥丁",
            "key_events": ["路明非用火箭筒射击", "奥丁的银色面具"],
        }
        selected = source_excerpts.select_for_chapter(plan, k=2)
        # battle scene + 路明非 character match → top1
        self.assertEqual(selected[0]["id"], "battle")
        self.assertEqual(len(selected), 2)

    def test_character_focus_weighting(self) -> None:
        from src import source_excerpts
        self._write_excerpts([
            {"id": "ex_A", "scene_type": "心理", "character_focus": ["路明非"],
             "tags": [], "excerpt_text": "A"},
            {"id": "ex_B", "scene_type": "心理", "character_focus": [],
             "tags": [], "excerpt_text": "B"},
        ])
        plan = {"key_events": ["路明非梦见康斯坦丁"]}
        selected = source_excerpts.select_for_chapter(plan, k=2)
        # ex_A wins because 路明非 in plan + character_focus
        self.assertEqual(selected[0]["id"], "ex_A")

    def test_format_excerpts_block(self) -> None:
        from src import source_excerpts
        excerpts = [
            {"id": "ex1", "scene_type": "战斗", "source_chapter_id": "ch_005",
             "description": "first fight", "excerpt_text": "battle prose"},
            {"id": "ex2", "scene_type": "情感", "source_chapter_id": "ch_010",
             "description": "", "excerpt_text": "tender scene"},
        ]
        out = source_excerpts.format_excerpts_for_prompt(excerpts)
        self.assertIn("### 战斗 | 来自 ch_005", out)
        self.assertIn("battle prose", out)
        self.assertIn("### 情感 | 来自 ch_010", out)
        self.assertIn("first fight", out)
        # Separator between excerpts
        self.assertIn("---", out)

    def test_format_empty_returns_empty_string(self) -> None:
        from src import source_excerpts
        self.assertEqual(source_excerpts.format_excerpts_for_prompt([]), "")


if __name__ == "__main__":
    unittest.main()
