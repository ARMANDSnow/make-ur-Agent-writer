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

    # --- iter 054a: start-point spoiler guard ---------------------------------

    def _setup_manifest_start(self, chapter_ids, start_id) -> None:
        data_dir = self.ws_root / "data"
        (data_dir / "manual_overrides").mkdir(parents=True, exist_ok=True)
        manifest = [
            {"chapter_id": cid, "volume_id": "v1", "title": cid} for cid in chapter_ids
        ]
        (data_dir / "chapter_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )
        (data_dir / "manual_overrides" / "start_chapter.json").write_text(
            json.dumps({"start_chapter_id": start_id}, ensure_ascii=False),
            encoding="utf-8",
        )

    def test_is_spoiler_excerpt_predicate(self) -> None:
        from src import source_excerpts
        self._setup_manifest_start(
            ["ch001", "ch002", "ch003", "ch004", "ch005"], "ch003"
        )
        # strictly after start → spoiler
        self.assertTrue(source_excerpts._is_spoiler_excerpt({"source_chapter_id": "ch004"}))
        self.assertTrue(source_excerpts._is_spoiler_excerpt({"source_chapter_id": "ch005"}))
        # before start / at start → not a spoiler (start chapter is legal context)
        self.assertFalse(source_excerpts._is_spoiler_excerpt({"source_chapter_id": "ch002"}))
        self.assertFalse(source_excerpts._is_spoiler_excerpt({"source_chapter_id": "ch003"}))
        # fail-open: missing id / not in manifest / non-dict
        self.assertFalse(source_excerpts._is_spoiler_excerpt({"source_chapter_id": ""}))
        self.assertFalse(source_excerpts._is_spoiler_excerpt({"source_chapter_id": "ch999"}))
        self.assertFalse(source_excerpts._is_spoiler_excerpt({}))
        self.assertFalse(source_excerpts._is_spoiler_excerpt("not a dict"))

    def test_select_drops_after_start_excerpts(self) -> None:
        from src import source_excerpts
        self._setup_manifest_start(
            ["ch001", "ch002", "ch003", "ch004", "ch005"], "ch003"
        )
        self._write_excerpts([
            {"id": "before", "scene_type": "战斗", "source_chapter_id": "ch002",
             "tags": [], "character_focus": [], "excerpt_text": "pre"},
            {"id": "at_start", "scene_type": "战斗", "source_chapter_id": "ch003",
             "tags": [], "character_focus": [], "excerpt_text": "at"},
            {"id": "after1", "scene_type": "战斗", "source_chapter_id": "ch004",
             "tags": [], "character_focus": [], "excerpt_text": "SPOILER one"},
            {"id": "after2", "scene_type": "战斗", "source_chapter_id": "ch005",
             "tags": [], "character_focus": [], "excerpt_text": "SPOILER two"},
        ])
        selected = source_excerpts.select_for_chapter({"key_events": ["一场战斗"]}, k=10)
        ids = {ex["id"] for ex in selected}
        # after-start dropped; start-inclusive + before-start kept
        self.assertEqual(ids, {"before", "at_start"})

    def test_select_no_start_keeps_all(self) -> None:
        # manifest present but NO start_chapter.json → is_after_start False for
        # all → byte-identical to pre-054 (greenfield fail-open).
        from src import source_excerpts
        data_dir = self.ws_root / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        manifest = [{"chapter_id": c} for c in ["ch001", "ch002", "ch003", "ch004"]]
        (data_dir / "chapter_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )
        self._write_excerpts([
            {"id": "deep", "scene_type": "战斗", "source_chapter_id": "ch004",
             "tags": [], "character_focus": [], "excerpt_text": "kept when no start"},
        ])
        selected = source_excerpts.select_for_chapter({"key_events": ["战斗"]}, k=10)
        self.assertEqual([ex["id"] for ex in selected], ["deep"])


if __name__ == "__main__":
    unittest.main()
