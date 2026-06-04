import json
import unittest
from unittest.mock import patch

from src.reviewer import review_text


def _agents() -> list[dict[str, str]]:
    return [{"name": f"agent_{idx}", "system_prompt": "review"} for idx in range(1, 6)]


class ReviewerTierAggregationTests(unittest.TestCase):
    def test_four_approve_score_78_across_tiers(self) -> None:
        def fake_complete_text(self, messages):
            prompt = "\n".join(m.get("content", "") for m in messages)
            verdict = "Reject" if "agent_name: agent_5" in prompt else "Approve"
            return json.dumps(
                {
                    "verdict": verdict,
                    "plot": 9,
                    "prose": 7,
                    "fidelity": 7,
                    "issues": [{"message": "style concern", "severity": "major"}] if verdict == "Reject" else [],
                    "suggestions": [],
                },
                ensure_ascii=False,
            )

        for tier, expected in (("high", "Reject"), ("mid", "Approve"), ("low", "Approve")):
            with self.subTest(tier=tier), patch("src.reviewer.load_review_agents", return_value=_agents()), patch(
                "src.reviewer.load_advisor_agents", return_value=[]
            ), patch("src.reviewer.load_entity_graph", return_value={"entities": [], "relationships": []}), patch(
                "src.llm_client.LLMClient.complete_text", fake_complete_text
            ), patch("src.reviewer.write_json"):
                report = review_text("正文。", "tier.md", precomputed_lint_issues=[], tier=tier)

            self.assertEqual(report["tier"], tier)
            self.assertEqual(report["verdict"], expected)
            self.assertEqual(report["approve_count"], 4)
            self.assertAlmostEqual(report["panel_score"], 7.8)
            self.assertEqual(len(report["agent_reviews"]), 5)

    def test_deterministic_relation_reject_remains_hard_veto(self) -> None:
        clean_response = json.dumps(
            {"verdict": "Approve", "plot": 9, "prose": 9, "fidelity": 9, "issues": [], "suggestions": []},
            ensure_ascii=False,
        )
        graph = {
            "entities": [
                {"id": "a", "name": "甲"},
                {"id": "b", "name": "乙"},
            ],
            "relationships": [
                {"src_id": "a", "dst_id": "b", "timeline": [{"active": True, "state": "乙已死亡"}]},
            ],
        }
        with patch("src.reviewer.load_review_agents", return_value=_agents()), patch(
            "src.reviewer.load_advisor_agents", return_value=[]
        ), patch("src.reviewer.load_entity_graph", return_value=graph), patch(
            "src.llm_client.LLMClient.complete_text", return_value=clean_response
        ), patch("src.reviewer.write_json"):
            report = review_text("甲抓住乙。", "hard_veto.md", precomputed_lint_issues=[], tier="low")

        self.assertEqual(report["approve_count"], 5)
        self.assertGreaterEqual(report["panel_score"], 8.5)
        self.assertEqual(report["verdict"], "Reject")
        self.assertIn("deterministic_relations", [r.get("agent_name") for r in report["agent_reviews"]])


if __name__ == "__main__":
    unittest.main()
