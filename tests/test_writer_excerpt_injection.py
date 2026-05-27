"""Iter 023 P3: tests for writer prompt scene-matched excerpt injection.

Verifies that ``src.writer._write_prompt`` includes the new "原作 archetype"
block when source_excerpts.json has matching entries, and stays
byte-identical to iter 022 behavior when no excerpts file is present.
"""

import json
import os
import shutil
import unittest
from pathlib import Path


class WriterExcerptInjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_ws = os.environ.get("WORKSPACE_NAME")
        os.environ["WORKSPACE_NAME"] = "iter023writerexc"
        repo_root = Path(__file__).resolve().parent.parent
        self.ws_root = repo_root / "workspaces" / "iter023writerexc"
        (self.ws_root / "data" / "source_excerpts").mkdir(parents=True, exist_ok=True)
        # Minimal chapter_manifest so start_point doesn't barf
        (self.ws_root / "data").mkdir(parents=True, exist_ok=True)
        (self.ws_root / "data" / "chapter_manifest.json").write_text(
            "[]", encoding="utf-8"
        )

    def tearDown(self) -> None:
        if self.ws_root.exists():
            shutil.rmtree(self.ws_root)
        if self._old_ws is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._old_ws

    def _build_prompt(self, plan_item):
        from src.writer import _write_prompt
        msgs, _ = _write_prompt(
            chapter_no=1,
            knowledge="kb",
            facts="",
            style_examples="",
            continuation_anchor="",
            index={},
            outline="outline",
            chapter_plan_item=plan_item,
        )
        return msgs[1]["content"]

    def test_no_excerpts_file_no_block(self) -> None:
        """When data/source_excerpts/excerpts.json absent, prompt omits
        the archetype block — byte-identical to iter 022."""
        prompt = self._build_prompt({
            "key_events": ["战斗", "对决"],
            "opening_scene": "高架路"
        })
        self.assertNotIn("# 原作 archetype 参考", prompt)

    def test_excerpts_file_present_block_injected(self) -> None:
        (self.ws_root / "data" / "source_excerpts" / "excerpts.json").write_text(
            json.dumps({
                "excerpts": [
                    {"id": "ex_001", "scene_type": "战斗",
                     "character_focus": ["路明非"], "tags": ["对决"],
                     "source_chapter_id": "longzu_1_ch008",
                     "description": "首次战斗",
                     "excerpt_text": "战斗的原文片段示例"},
                ]
            }, ensure_ascii=False),
            encoding="utf-8",
        )
        prompt = self._build_prompt({
            "key_events": ["路明非战斗"], "opening_scene": "对决场面"
        })
        self.assertIn("# 原作 archetype 参考", prompt)
        self.assertIn("战斗的原文片段示例", prompt)


if __name__ == "__main__":
    unittest.main()
