import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

from src.writer import _write_prompt, write_chapters


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
        "polish_pass": True,
        "review_during_lint_block": True,
        "continuation_anchor": "",
    }
    cfg.update(overrides)
    return cfg


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

    def test_polish_pass_runs_after_final_reject_and_respects_disable(self) -> None:
        for enabled in (True, False):
            with self.subTest(polish_pass=enabled), tempfile.TemporaryDirectory() as tmp:
                tmp = Path(tmp)
                drafts, outline, kb, idx = _write_fixture(tmp)
                calls = []

                def fake_complete_text(self, messages, temperature=None, cache_segments=None):
                    calls.append("\n".join(message.get("content", "") for message in messages))
                    return "polished draft" if len(calls) > 1 else "first draft"

                def fake_load_config(name: str):
                    if name == "agents.yaml":
                        return _agent_config(polish_pass=enabled)
                    raise AssertionError(name)

                with patch("src.writer.DRAFTS_DIR", drafts), patch("src.writer.OUTLINE_PATH", outline), patch(
                    "src.writer.KB_PATH", kb
                ), patch("src.writer.INDEX_PATH", idx), patch("src.writer.load_config", side_effect=fake_load_config), patch(
                    "src.writer.NovelLinter"
                ) as linter_cls, patch(
                    "src.llm_client.LLMClient.complete_text", fake_complete_text
                ), patch(
                    "src.writer.review_text",
                    return_value={"verdict": "Reject", "lint_issues": [], "agent_reviews": []},
                ):
                    linter_cls.return_value.lint.return_value = []
                    write_chapters(chapters=1, force=True, max_attempts=1)

                meta = json.loads((drafts / "chapter_01.meta.json").read_text(encoding="utf-8"))
                draft = (drafts / "chapter_01.md").read_text(encoding="utf-8")
                self.assertEqual(meta["polish_applied"], enabled)
                self.assertEqual(("polished draft" in draft), enabled)
                if enabled:
                    self.assertEqual(meta["polish_diff_stats"]["pre_chars"], len("first draft"))

    def test_reviewer_runs_even_when_lint_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            drafts, outline, kb, idx = _write_fixture(tmp)

            def fake_load_config(name: str):
                if name == "agents.yaml":
                    return _agent_config(polish_pass=False, review_during_lint_block=True)
                raise AssertionError(name)

            shadow_report = {
                "verdict": "Reject",
                "lint_issues": [{"rule": "not_x_but_y", "severity": "error", "message": "bad", "line": 1, "anchor": "bad"}],
                "agent_reviews": [{"agent_name": "江南人格模拟", "verdict": "Reject", "issues": []}],
            }
            with patch("src.writer.DRAFTS_DIR", drafts), patch("src.writer.OUTLINE_PATH", outline), patch(
                "src.writer.KB_PATH", kb
            ), patch("src.writer.INDEX_PATH", idx), patch("src.writer.load_config", side_effect=fake_load_config), patch(
                "src.writer.NovelLinter"
            ) as linter_cls, patch(
                "src.writer.review_text", return_value=shadow_report
            ) as mock_review:
                linter_cls.return_value.lint.return_value = [
                    {"rule": "not_x_but_y", "severity": "error", "message": "bad", "line": 1, "anchor": "bad", "count": 5}
                ]
                write_chapters(chapters=1, force=True, max_attempts=1)

            meta = json.loads((drafts / "chapter_01.meta.json").read_text(encoding="utf-8"))
            self.assertTrue(meta["lint_blocked_reviews"])
            self.assertEqual(meta["lint_blocked_reviews"][0]["attempt"], 1)
            self.assertEqual(meta["lint_blocked_reviews"][0]["review"]["agent_reviews"][0]["agent_name"], "江南人格模拟")
            self.assertTrue(mock_review.call_args.kwargs["run_agents_on_lint_error"])


if __name__ == "__main__":
    unittest.main()
