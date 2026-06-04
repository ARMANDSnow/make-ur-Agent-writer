from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

from src.book_runner import run_write_book
from src.chapter_status import chapter_status
from src.web import jobs


class PartialWriteError(RuntimeError):
    def __init__(self, message: str, partial_draft: str) -> None:
        super().__init__(message)
        self.partial_draft = partial_draft


def _agent_config(**overrides: Any) -> Dict[str, Any]:
    cfg: Dict[str, Any] = {
        "max_review_attempts": 1,
        "polish_pass": False,
        "review_during_lint_block": True,
        "continuation_anchor": "",
    }
    cfg.update(overrides)
    return cfg


def _status(chapter_no: int, *, exists: bool, approved: bool) -> Dict[str, Any]:
    return {
        "chapter_no": chapter_no,
        "exists": exists,
        "approved": approved,
        "needs_review": False,
        "failure": False,
        "verdict": "Approve" if approved else None,
        "rewrite_count": 0,
        "strict_failures": [],
    }


class BookRunnerPartialArtifactTests(unittest.TestCase):
    def test_write_exception_saves_partial_and_returns_failed_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            drafts = root / "outputs" / "drafts"
            drafts.mkdir(parents=True)
            (root / "outputs" / "debate").mkdir(parents=True)
            (root / "outputs" / "debate" / "outline.md").write_text("# outline", encoding="utf-8")
            (root / "data" / "knowledge_base").mkdir(parents=True)
            (root / "data" / "knowledge_base" / "global_knowledge.md").write_text("# kb", encoding="utf-8")
            (root / "data" / "knowledge_base" / "knowledge_index.json").write_text("{}", encoding="utf-8")
            (root / "logs").mkdir(parents=True)

            statuses = [
                _status(1, exists=False, approved=False),
                _status(1, exists=True, approved=True),
                _status(2, exists=False, approved=False),
            ]
            err = PartialWriteError("stream interrupted", "第二章已经生成的半截正文")

            def fake_load_config(name: str):
                if name == "agents.yaml":
                    return _agent_config()
                raise AssertionError(name)

            with patch("src.book_runner.paths.workspace_name", return_value="unit"), patch(
                "src.book_runner.paths.workspace_root", return_value=root
            ), patch("src.book_runner.paths.drafts_dir", return_value=drafts), patch(
                "src.book_runner.paths.llm_calls_log_path", return_value=root / "logs" / "llm_calls.jsonl"
            ), patch(
                "src.book_runner.paths.entity_graph_path", return_value=root / "data" / "entity_graph.json"
            ), patch(
                "src.book_runner.run_preflight", return_value={"status": "ok", "fatal": [], "warn": [], "info": []}
            ), patch(
                "src.book_runner.chapter_status", side_effect=statuses
            ), patch(
                "src.book_runner._snapshot", side_effect=lambda status, payload: {"status": status, **payload}
            ), patch(
                "src.writer.paths.outline_path", return_value=root / "outputs" / "debate" / "outline.md"
            ), patch(
                "src.writer.paths.kb_path", return_value=root / "data" / "knowledge_base" / "global_knowledge.md"
            ), patch(
                "src.writer.paths.index_path", return_value=root / "data" / "knowledge_base" / "knowledge_index.json"
            ), patch(
                "src.writer.paths.chapter_plan_path", return_value=root / "outputs" / "debate" / "chapter_plan.json"
            ), patch(
                "src.writer.load_config", side_effect=fake_load_config
            ), patch(
                "src.writer.NovelLinter"
            ) as linter_cls, patch(
                "src.writer.review_text",
                return_value={"verdict": "Approve", "lint_issues": [], "agent_reviews": []},
            ), patch(
                "src.writer._complete_write_text", side_effect=["第一章正文", err]
            ), patch(
                "src.writer._summarize_chapter",
                return_value={"summary": "摘要", "key_events": ["事件"], "ending_state": "结尾"},
            ), patch(
                "src.writer._propose_entity_advance", return_value=[]
            ), patch(
                "src.writer.load_entity_graph", return_value={}
            ):
                linter_cls.return_value.lint.return_value = []
                result = run_write_book(
                    chapters=2,
                    max_retries=0,
                    auto_advance=False,
                    require_start_point=False,
                    require_plan=False,
                    require_external_review=False,
                )

            partial_path = drafts / "chapter_02.partial.md"
            failure_path = drafts / "chapter_02.failure.json"
            self.assertEqual(result["status"], "failed")
            self.assertTrue(partial_path.exists())
            self.assertTrue(failure_path.exists())
            self.assertIn("第二章已经生成的半截正文", partial_path.read_text(encoding="utf-8"))
            failure = json.loads(failure_path.read_text(encoding="utf-8"))
            self.assertEqual(failure["attempt"], 1)
            self.assertEqual(failure["stage"], "write")
            self.assertIn("stream interrupted", failure["last_error"])
            self.assertEqual(result["partial"]["chapter"], 2)
            self.assertEqual(result["partial"]["attempt"], 1)
            self.assertEqual(result["partial"]["draft_path"], str(partial_path))
            self.assertEqual(chapter_status(2, drafts)["exists"], False)

            summary = jobs._summarize_result("write-book", result)
            self.assertEqual(summary["partial"]["chapter"], 2)


if __name__ == "__main__":
    unittest.main()
