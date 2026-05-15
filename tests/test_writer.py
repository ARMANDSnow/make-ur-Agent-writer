import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.writer import _write_prompt, write_chapters


class WriterLintFailureTests(unittest.TestCase):
    def test_lint_error_writes_human_review_draft_and_failure_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            drafts = tmp / "drafts"
            drafts.mkdir(parents=True)
            outline = tmp / "outline.md"
            outline.write_text("# test outline", encoding="utf-8")
            kb = tmp / "global_knowledge.md"
            kb.write_text("# test knowledge", encoding="utf-8")
            idx = tmp / "knowledge_index.json"
            idx.write_text("{}", encoding="utf-8")

            with patch("src.writer.DRAFTS_DIR", drafts), patch("src.writer.OUTLINE_PATH", outline), patch(
                "src.writer.KB_PATH", kb
            ), patch("src.writer.INDEX_PATH", idx):
                # Mock linter to always return lint errors
                with patch("src.writer.NovelLinter") as mock_linter_cls:
                    mock_linter = mock_linter_cls.return_value
                    mock_linter.lint.return_value = [
                        {"rule": "meta_chapter_markers", "severity": "error", "message": "bad", "line": 1, "excerpt": "x"}
                    ]

                    reports = write_chapters(chapters=1, force=True, max_attempts=1)

            md_path = drafts / "chapter_01.md"
            meta_path = drafts / "chapter_01.meta.json"
            failure_path = drafts / "chapter_01.failure.json"
            self.assertTrue(md_path.exists())
            self.assertTrue(meta_path.exists())
            self.assertTrue(failure_path.exists())
            failure = json.loads(failure_path.read_text(encoding="utf-8"))
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            self.assertIn("lint_issues", failure)
            self.assertTrue(meta["needs_human_review"])
            self.assertEqual(meta["rewrite_count"], 0)
            self.assertEqual(meta["last_blocking_reasons"][0]["reviewer"], "deterministic_linter")
            self.assertEqual(reports[0]["written"], True)


class WriterRejectLintCleanTests(unittest.TestCase):
    def test_reject_lint_clean_writes_draft_with_human_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            drafts = tmp / "drafts"
            drafts.mkdir(parents=True)
            outline = tmp / "outline.md"
            outline.write_text("# test outline", encoding="utf-8")
            kb = tmp / "global_knowledge.md"
            kb.write_text("# test knowledge", encoding="utf-8")
            idx = tmp / "knowledge_index.json"
            idx.write_text("{}", encoding="utf-8")

            with patch("src.writer.DRAFTS_DIR", drafts), patch("src.writer.OUTLINE_PATH", outline), patch(
                "src.writer.KB_PATH", kb
            ), patch("src.writer.INDEX_PATH", idx):
                with patch("src.writer.NovelLinter") as mock_linter_cls:
                    mock_linter = mock_linter_cls.return_value
                    mock_linter.lint.return_value = []  # lint clean
                    with patch("src.writer.review_text") as mock_review:
                        mock_review.return_value = {
                            "verdict": "Reject",
                            "lint_issues": [],
                            "agent_reviews": [{"verdict": "Reject", "issues": ["bad pacing"]}],
                        }
                        reports = write_chapters(chapters=1, force=True, max_attempts=1)

            md_path = drafts / "chapter_01.md"
            meta_path = drafts / "chapter_01.meta.json"
            self.assertTrue(md_path.exists())
            self.assertTrue(meta_path.exists())
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            self.assertTrue(meta.get("needs_human_review"))
            self.assertEqual(reports[0]["written"], True)

    def test_writer_prompt_includes_style_examples_when_present(self) -> None:
        messages, cache_segments = _write_prompt(
            chapter_no=1,
            knowledge="knowledge",
            facts="facts",
            style_examples="### opening_rhythm\n\n风格样例",
            continuation_anchor="",
            index={},
            outline="outline",
            previous_state="",
            feedback="",
        )
        prompt = "\n".join(item["content"] for item in messages)
        cached_text = "\n".join(item["content"] for item in cache_segments if item.get("cache"))
        self.assertIn("opening_rhythm", prompt)
        self.assertIn("不要复制具体情节", prompt)
        self.assertIn("opening_rhythm", cached_text)

    def test_writer_prompt_includes_continuation_anchor(self) -> None:
        messages, _cache_segments = _write_prompt(
            chapter_no=1,
            knowledge="knowledge",
            facts="facts",
            style_examples="",
            continuation_anchor="第三部结局后三个月",
            index={},
            outline="outline",
            previous_state="",
            feedback="",
        )
        prompt = "\n".join(item["content"] for item in messages)
        self.assertIn("续写起点", prompt)
        self.assertIn("第三部结局后三个月", prompt)
        self.assertIn("中文正文 3500-5500 字", prompt)


if __name__ == "__main__":
    unittest.main()
