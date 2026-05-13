import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.writer import write_chapters


class WriterRewriteLoopTests(unittest.TestCase):
    def test_reject_feedback_stops_at_max_review_attempts_and_records_reasons(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            drafts = tmp / "drafts"
            drafts.mkdir(parents=True)
            outline = tmp / "outline.md"
            outline.write_text("# outline", encoding="utf-8")
            kb = tmp / "global_knowledge.md"
            kb.write_text("# knowledge", encoding="utf-8")
            idx = tmp / "knowledge_index.json"
            idx.write_text("{}", encoding="utf-8")
            prompts = []

            def fake_complete_text(self, messages, temperature=None, cache_segments=None):
                prompts.append("\n".join(message.get("content", "") for message in messages))
                return "干净正文。"

            reject_report = {
                "verdict": "Reject",
                "lint_issues": [],
                "agent_reviews": [
                    {
                        "agent_name": "伏笔猎人",
                        "verdict": "Reject",
                        "issues": [
                            {
                                "message": "缺少伏笔回收",
                                "rule_id": "missing_payoff",
                                "severity": "block",
                                "anchor": "末尾",
                            }
                        ],
                        "suggestions": ["补回收"],
                    }
                ],
            }

            with patch("src.writer.DRAFTS_DIR", drafts), patch("src.writer.OUTLINE_PATH", outline), patch(
                "src.writer.KB_PATH", kb
            ), patch("src.writer.INDEX_PATH", idx), patch("src.writer.NovelLinter") as linter_cls, patch(
                "src.llm_client.LLMClient.complete_text", fake_complete_text
            ), patch(
                "src.writer.review_text", return_value=reject_report
            ):
                linter_cls.return_value.lint.return_value = []
                write_chapters(chapters=1, force=True, max_attempts=2)

            meta = json.loads((drafts / "chapter_01.meta.json").read_text(encoding="utf-8"))
            self.assertTrue(meta["needs_human_review"])
            self.assertEqual(meta["rewrite_count"], 1)
            self.assertEqual(meta["last_blocking_reasons"][0]["rule_id"], "missing_payoff")
            self.assertIn("missing_payoff", prompts[1])


if __name__ == "__main__":
    unittest.main()
