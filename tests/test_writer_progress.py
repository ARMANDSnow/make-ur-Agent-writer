from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

from src.writer import write_chapters


def _write_fixture(tmp: Path) -> tuple[Path, Path, Path, Path]:
    drafts = tmp / "drafts"
    drafts.mkdir(parents=True)
    outline = tmp / "outline.md"
    outline.write_text("# test outline", encoding="utf-8")
    kb = tmp / "global_knowledge.md"
    kb.write_text("# test knowledge", encoding="utf-8")
    idx = tmp / "knowledge_index.json"
    idx.write_text("{}", encoding="utf-8")
    return drafts, outline, kb, idx


def _agent_config(**overrides: Any) -> Dict[str, Any]:
    cfg: Dict[str, Any] = {
        "max_review_attempts": 3,
        "polish_pass": False,
        "review_during_lint_block": True,
        "continuation_anchor": "",
    }
    cfg.update(overrides)
    return cfg


class WriterProgressCallbackTests(unittest.TestCase):
    def test_single_write_review_flow_reports_monotonic_chapter_progress(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            drafts, outline, kb, idx = _write_fixture(tmp_path)
            calls: list[tuple[str, float]] = []

            def fake_load_config(name: str):
                if name == "agents.yaml":
                    return _agent_config()
                raise AssertionError(name)

            with patch("src.writer.DRAFTS_DIR", drafts), patch("src.writer.OUTLINE_PATH", outline), patch(
                "src.writer.KB_PATH", kb
            ), patch("src.writer.INDEX_PATH", idx), patch(
                "src.writer.load_config", side_effect=fake_load_config
            ), patch(
                "src.writer.NovelLinter"
            ) as linter_cls, patch(
                "src.writer.review_text",
                return_value={"verdict": "Approve", "lint_issues": [], "agent_reviews": []},
            ), patch(
                "src.writer._complete_write_text", return_value="干净正文"
            ), patch(
                "src.writer._summarize_chapter",
                return_value={"summary": "摘要", "key_events": ["事件"], "ending_state": "结尾"},
            ), patch(
                "src.writer._propose_entity_advance", return_value=[]
            ):
                linter_cls.return_value.lint.return_value = []
                write_chapters(
                    chapters=1,
                    force=True,
                    max_attempts=1,
                    progress_cb=lambda step, fraction: calls.append((step, fraction)),
                )

            self.assertEqual(
                [step for step, _fraction in calls],
                ["write-attempt-1", "review-attempt-1", "review-done-attempt-1", "finalize"],
            )
            fractions = [fraction for _step, fraction in calls]
            self.assertEqual(fractions, sorted(fractions))
            self.assertEqual(fractions[0], 0.05)
            self.assertEqual(fractions[-1], 0.95)
            self.assertTrue((drafts / "chapter_01.md").exists())
            meta = json.loads((drafts / "chapter_01.meta.json").read_text(encoding="utf-8"))
            self.assertEqual(meta["verdict"], "Approve")


if __name__ == "__main__":
    unittest.main()
