import unittest
from pathlib import Path
from unittest.mock import patch

from src.reviewer import review_text


class ReviewerPrecomputedLintTests(unittest.TestCase):
    def test_uses_precomputed_lint_when_provided(self) -> None:
        precomputed = [
            {"rule": "meta_chapter_markers", "severity": "error", "message": "bad", "line": 1, "excerpt": "第 1 章"}
        ]
        # With precomputed error-level issue, should reject immediately without needing linter
        report = review_text("some text", "test_draft.md", precomputed_lint_issues=precomputed)
        self.assertEqual(report["verdict"], "Reject")
        self.assertEqual(report["lint_issues"], precomputed)

    def test_runs_linter_when_precomputed_not_provided(self) -> None:
        # Text with chapter marker triggers meta_chapter_markers rule
        report = review_text("第 1 章 开始", "test_draft.md")
        self.assertIn("verdict", report)
        # Linter was run internally — should detect the marker
        rules = {issue["rule"] for issue in report.get("lint_issues", [])}
        self.assertIn("meta_chapter_markers", rules)

    def test_review_prompt_includes_global_facts(self) -> None:
        captured = {}

        def fake_complete_json(self, messages, response_model):
            captured["prompt"] = "\n".join(m.get("content", "") for m in messages)
            return response_model(agent_name="agent", verdict="Approve", score=8, issues=[], suggestions=[])

        with patch("src.reviewer.global_facts_summary", return_value="FACT: 绘梨衣已死亡"), patch(
            "src.llm_client.LLMClient.complete_json", fake_complete_json
        ), patch("src.reviewer.load_review_agents", return_value=[{"name": "agent", "system_prompt": "review"}]):
            report = review_text("干净正文。", "clean.md", precomputed_lint_issues=[])
        self.assertEqual(report["verdict"], "Approve")
        self.assertIn("FACT: 绘梨衣已死亡", captured["prompt"])


if __name__ == "__main__":
    unittest.main()
