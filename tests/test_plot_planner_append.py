"""Iter 024 P2: tests for plot_planner.generate_chapter_plan(append_count, from_chapter).

Verifies append mode preserves existing chapters 1..from_chapter,
appends K new ones, updates target_chapters total, and preserves the
top-level overall_arc from existing (doesn't let LLM rewrite global
arc on every re-plan).
"""

import json
import os
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch


def _make_plan(n: int, arc: str = "原始 arc") -> dict:
    return {
        "target_chapters": n,
        "overall_arc": arc,
        "chapters": [
            {
                "chapter_no": i,
                "title": f"原章 {i}",
                "opening_scene": f"开场 {i}",
                "key_events": [f"事件 {i}.1", f"事件 {i}.2"],
                "relationships_in_play": [],
                "ending_hook": f"hook {i}",
                "target_chinese_chars": 4000,
                "plot_purpose": f"用途 {i}",
            }
            for i in range(1, n + 1)
        ],
        "generated_by": "test_seed",
    }


class PlotPlannerAppendTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_ws = os.environ.get("WORKSPACE_NAME")
        os.environ["WORKSPACE_NAME"] = "iter024append"
        repo_root = Path(__file__).resolve().parent.parent
        self.ws_root = repo_root / "workspaces" / "iter024append"
        (self.ws_root / "outputs" / "debate").mkdir(parents=True, exist_ok=True)
        (self.ws_root / "data" / "knowledge_base").mkdir(parents=True, exist_ok=True)
        # Stub outline so generate_chapter_plan precondition is met
        (self.ws_root / "outputs" / "debate" / "outline.md").write_text(
            "stub outline", encoding="utf-8"
        )

    def tearDown(self) -> None:
        if self.ws_root.exists():
            shutil.rmtree(self.ws_root)
        if self._old_ws is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._old_ws

    def _seed_plan(self, n: int) -> None:
        (self.ws_root / "outputs" / "debate" / "chapter_plan.json").write_text(
            json.dumps(_make_plan(n), ensure_ascii=False),
            encoding="utf-8",
        )

    def test_append_preserves_existing_head(self) -> None:
        """append +5 from ch10 should keep ch1-10 byte-identical and
        produce ch11-15 with continuous chapter_no."""
        from src import plot_planner

        self._seed_plan(10)
        # Mock LLM to return 5 new chapters numbered 1-5 (renumbering test)
        fake_new = {
            "target_chapters": 5,
            "overall_arc": "新 arc (会被原 arc 覆盖)",
            "chapters": [
                {
                    "chapter_no": i,
                    "title": f"新章 {i}",
                    "opening_scene": f"新开场 {i}",
                    "key_events": [f"新事件 {i}.1", f"新事件 {i}.2"],
                    "relationships_in_play": [],
                    "ending_hook": f"新 hook {i}",
                    "target_chinese_chars": 4000,
                    "plot_purpose": f"新用途 {i}",
                }
                for i in range(1, 6)
            ],
            "generated_by": "test_mock",
        }

        from src.schemas import ChapterPlan
        with patch.object(
            plot_planner.LLMClient,
            "complete_json",
            lambda self, msgs, model: ChapterPlan(**fake_new),
        ):
            result = plot_planner.generate_chapter_plan(
                target_chapters=5, append_count=5, from_chapter=10
            )

        # Should have 15 total chapters
        self.assertEqual(len(result["chapters"]), 15)
        self.assertEqual(result["target_chapters"], 15)
        # ch1-10 preserved byte-identical (title format = "原章 N")
        for i in range(10):
            self.assertEqual(result["chapters"][i]["title"], f"原章 {i + 1}")
            self.assertEqual(result["chapters"][i]["chapter_no"], i + 1)
        # ch11-15 are renumbered new ones (LLM returned 1-5, we renumber to 11-15)
        for i in range(5):
            self.assertEqual(result["chapters"][10 + i]["chapter_no"], 11 + i)
            self.assertEqual(result["chapters"][10 + i]["title"], f"新章 {i + 1}")
        # overall_arc preserved from existing, not from LLM
        self.assertEqual(result["overall_arc"], "原始 arc")

    def test_no_append_mode_unchanged(self) -> None:
        """Default mode (append_count=0) requires force when plan exists."""
        from src import plot_planner

        self._seed_plan(8)
        with self.assertRaises(FileExistsError):
            plot_planner.generate_chapter_plan(target_chapters=5, force=False)


if __name__ == "__main__":
    unittest.main()
