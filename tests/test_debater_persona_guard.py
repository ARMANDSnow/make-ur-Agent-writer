"""Phase 6 fix: debate must not silently fall back to 龙族 personas.

Regression for the user-reported bug "debate agent 默认是龙族且无法自动修改":
a NEW novel run in workspace mode with no personas.json used to silently use
the legacy 龙族 validation-corpus agents. Now it fails closed with guidance,
the default topic is persona-driven / novel-agnostic, and the hardcoded
fallback outline is no longer 龙族-specific.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.debater import run_debate


def _kb_idx(tmp: Path):
    kb = tmp / "global_knowledge.md"
    kb.write_text("# kb", encoding="utf-8")
    idx = tmp / "knowledge_index.json"
    idx.write_text("{}", encoding="utf-8")
    return kb, idx


class DebatePersonaGuardTests(unittest.TestCase):
    def test_workspace_without_personas_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            kb, idx = _kb_idx(tmp)
            with patch("src.debater._kb_path", return_value=kb), patch(
                "src.debater._index_path", return_value=idx
            ), patch("src.debater._debate_dir", return_value=tmp), patch(
                "src.debater.paths.workspace_name", return_value="newbook"
            ), patch(
                "src.debater.load_personas", return_value=None
            ):
                with self.assertRaises(FileNotFoundError) as ctx:
                    run_debate()
        self.assertIn("personas.json", str(ctx.exception))
        self.assertIn("newbook", str(ctx.exception))

    def test_legacy_mode_without_personas_still_runs(self) -> None:
        # No active workspace → original validation-corpus fallback preserved.
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            kb, idx = _kb_idx(tmp)
            with patch("src.debater.KB_PATH", kb), patch(
                "src.debater.INDEX_PATH", idx
            ), patch("src.debater.DEBATE_DIR", tmp), patch(
                "src.debater.paths.workspace_name", return_value=None
            ):
                result = run_debate()  # mock, legacy, no personas → no raise
        self.assertIn("outline", result)


class DebateDefaultTopicTests(unittest.TestCase):
    def test_default_topic_is_novel_agnostic_without_personas(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            kb, idx = _kb_idx(tmp)
            with patch("src.debater.KB_PATH", kb), patch(
                "src.debater.INDEX_PATH", idx
            ), patch("src.debater.DEBATE_DIR", tmp), patch(
                "src.debater.paths.workspace_name", return_value=None
            ), patch(
                "src.debater.load_personas", return_value=None
            ):
                outline = run_debate()["outline"]
        self.assertIn("长篇小说续写结局方案", outline)
        self.assertNotIn("龙族一至四之后的长篇续写结局方案", outline)
        # de-龙族'd hardcoded consensus bullets AND mock vote questions:
        # the whole fallback outline must be free of 龙族-specific names.
        for leaked in ("路明非的选择必须改变结局", "路鸣泽", "楚子航", "夏弥", "江南"):
            self.assertNotIn(leaked, outline)

    def test_default_topic_uses_protagonist_when_personas_present(self) -> None:
        personas = {
            "protagonist_name": "段誉",
            "protagonist_role": "主角",
            "author_name": "金庸",
            "style_short_descriptor": "白话",
            "world_setting_brief": "骨架",
            "core_relationships": [],
            "core_setting_rules": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            kb, idx = _kb_idx(tmp)
            with patch("src.debater.KB_PATH", kb), patch(
                "src.debater.INDEX_PATH", idx
            ), patch("src.debater.DEBATE_DIR", tmp), patch(
                "src.debater.paths.workspace_name", return_value=None
            ), patch(
                "src.debater.load_personas", return_value=personas
            ):
                outline = run_debate()["outline"]
        self.assertIn("段誉线的长篇续写结局方案", outline)


if __name__ == "__main__":
    unittest.main()
