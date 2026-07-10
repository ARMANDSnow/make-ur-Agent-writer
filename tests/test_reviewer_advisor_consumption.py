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
            "src.reviewer.style_drift.rewrite_directives_for_text", return_value=[]
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
            "src.reviewer.style_drift.rewrite_directives_for_text", return_value=[]
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

    def test_style_drift_directives_prepend_without_voting(self) -> None:
        """Deterministic style advice is first-class feedback, not a voter."""
        from src.reviewer import review_text
        from src.schemas import StyleRewriteDirective

        approve_json = '{"verdict":"Approve","plot":8,"prose":8,"fidelity":8,"issues":[],"suggestions":[]}'
        directive = StyleRewriteDirective(
            dimension="avg_sentence_length",
            severity="red",
            section_hint="全文句式节奏",
            target_metric="avg_sentence_length",
            current_value=42.0,
            target_range={"min": 18.0, "max": 22.0},
            guidance="拆分解释性长句，不改剧情事实。",
        )
        with patch(
            "src.reviewer.load_review_agents",
            return_value=[{"name": "test_agent", "system_prompt": "x"}],
        ), patch(
            "src.reviewer.load_advisor_agents", return_value=[]
        ), patch(
            "src.reviewer.style_drift.rewrite_directives_for_text", return_value=[directive]
        ), patch(
            "src.llm_client.LLMClient.complete_text", return_value=approve_json
        ) as complete_text, patch(
            "src.reviewer.write_json"
        ):
            report = review_text("正文。", "style.md", precomputed_lint_issues=[])

        self.assertEqual(report["verdict"], "Approve")
        self.assertFalse(report["hard_reject"])
        self.assertEqual(report["approve_count"], 1)
        self.assertEqual(len(report["agent_reviews"]), 1)
        suggestion = report["rewrite_suggestions"][0]
        self.assertEqual(suggestion["_advisor"], "style_drift_advisor")
        self.assertEqual(suggestion["section"], "全文句式节奏")
        self.assertEqual(suggestion["type"], "rewrite")
        self.assertEqual(suggestion["dimension"], "avg_sentence_length")
        self.assertEqual(suggestion["target_range"], {"min": 18.0, "max": 22.0})
        self.assertEqual(complete_text.call_count, 1)

    def test_style_merge_reserves_plan_and_existing_advisor_slots(self) -> None:
        from src.reviewer import _merge_style_advisor_suggestions

        existing = [
            {
                "section": "结尾",
                "type": "rewrite",
                "guidance": "保留原 advisor 建议",
                "_advisor": "改写顾问",
            }
        ]
        plan = [
            {
                "section": "本章计划",
                "type": "add",
                "guidance": "补足计划关键事件",
                "_advisor": "plan_compliance",
            }
        ]
        style = [
            {
                "section": f"style-{idx}",
                "type": "rewrite",
                "guidance": f"style guidance {idx}",
                "_advisor": "style_drift_advisor",
            }
            for idx in range(5)
        ]

        merged = _merge_style_advisor_suggestions(existing, plan, style)
        writer_visible = merged[:5]
        advisors = [item["_advisor"] for item in writer_visible]
        self.assertIn("plan_compliance", advisors)
        self.assertIn("改写顾问", advisors)
        self.assertEqual(advisors.count("style_drift_advisor"), 3)
        self.assertEqual(len(merged), 7)


if __name__ == "__main__":
    unittest.main()
