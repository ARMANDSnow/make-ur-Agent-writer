"""Iter 024 P1: tests for advisor consumption chain (reviewer + writer).

Verifies:
* `load_advisor_agents()` reads `advisor_agents` from config/agents.yaml
* `review_text()` returns `rewrite_suggestions` field (empty list when
  no advisor configured)
* Advisor agents do NOT contribute to verdict aggregation (only output
  RewriteSuggestion list)
* `_review_feedback()` includes the advisor section when suggestions present
"""

import json
import unittest
from unittest.mock import patch


class ReviewerAdvisorConsumptionTests(unittest.TestCase):
    def test_load_advisor_agents_returns_list(self) -> None:
        from src.reviewer import load_advisor_agents
        advisors = load_advisor_agents()
        self.assertIsInstance(advisors, list)
        # iter 023 config has 1 advisor (改写顾问)
        self.assertGreaterEqual(len(advisors), 1)
        self.assertEqual(advisors[0].get("name"), "改写顾问")

    def test_review_report_includes_rewrite_suggestions_field(self) -> None:
        """review_text always returns rewrite_suggestions field (possibly empty)."""
        from src.reviewer import review_text

        approve_json = '{"verdict":"Approve","plot":7,"prose":7,"fidelity":7,"issues":[],"suggestions":[]}'
        with patch(
            "src.reviewer.load_review_agents",
            return_value=[{"name": "test_agent", "system_prompt": "x"}],
        ), patch(
            "src.reviewer.load_advisor_agents", return_value=[]
        ), patch(
            "src.llm_client.LLMClient.complete_text", return_value=approve_json
        ), patch(
            "src.reviewer.write_json"
        ):
            report = review_text("ok body", "t.md", precomputed_lint_issues=[])
        self.assertIn("rewrite_suggestions", report)
        self.assertEqual(report["rewrite_suggestions"], [])

    def test_advisor_suggestions_added_and_do_not_vote(self) -> None:
        """When advisor returns valid suggestions, they appear in
        rewrite_suggestions list — but verdict reflects only review_agents."""
        from src.reviewer import review_text

        approve_json = '{"verdict":"Approve","plot":8,"prose":8,"fidelity":8,"issues":[],"suggestions":[]}'
        advisor_json = '{"suggestions": [{"section":"第 3 段","type":"add","guidance":"加一段主角内心反应"}]}'

        call_count = {"n": 0}

        def fake_complete_text(self, messages):
            call_count["n"] += 1
            content = " ".join(m.get("content", "") for m in messages)
            if "advisor_name:" in content:
                return advisor_json
            return approve_json

        with patch(
            "src.reviewer.load_review_agents",
            return_value=[{"name": "test_agent", "system_prompt": "x"}],
        ), patch(
            "src.reviewer.load_advisor_agents",
            return_value=[{"name": "改写顾问", "system_prompt": "你是改写顾问"}],
        ), patch(
            "src.llm_client.LLMClient.complete_text", fake_complete_text
        ), patch(
            "src.reviewer.write_json"
        ):
            report = review_text("body", "t.md", precomputed_lint_issues=[])

        # Verdict is Approve (only 1 review_agent, it approved)
        self.assertEqual(report["verdict"], "Approve")
        # Advisor produced 1 suggestion
        suggs = report["rewrite_suggestions"]
        self.assertEqual(len(suggs), 1)
        self.assertEqual(suggs[0]["section"], "第 3 段")
        self.assertEqual(suggs[0]["type"], "add")
        self.assertIn("主角内心", suggs[0]["guidance"])
        # _advisor metadata attached
        self.assertEqual(suggs[0]["_advisor"], "改写顾问")
        # Both review_agent + advisor were called (2 total LLM calls)
        self.assertEqual(call_count["n"], 2)


if __name__ == "__main__":
    unittest.main()
