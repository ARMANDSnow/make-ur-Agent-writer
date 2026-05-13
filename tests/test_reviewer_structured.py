import unittest
from unittest.mock import patch

from src.reviewer import review_text


class ReviewerStructuredTests(unittest.TestCase):
    def test_structured_issue_fields_are_preserved(self) -> None:
        def fake_complete_json(self, messages, response_model):
            return response_model(
                agent_name="伏笔猎人",
                verdict="Reject",
                score=4,
                issues=[
                    {
                        "message": "没有回收尼伯龙根线索",
                        "rule_id": "foreshadowing_missing",
                        "severity": "block",
                        "anchor": "第 12 行",
                    }
                ],
                suggestions=["补一处可追溯回收"],
            )

        with patch("src.reviewer.load_review_agents", return_value=[{"name": "伏笔猎人", "system_prompt": "review"}]), patch(
            "src.llm_client.LLMClient.complete_json", fake_complete_json
        ):
            report = review_text("干净正文。", "structured.md", precomputed_lint_issues=[], rewrite_round=1)

        self.assertEqual(report["rewrite_round"], 1)
        issue = report["agent_reviews"][0]["issues"][0]
        self.assertEqual(issue["rule_id"], "foreshadowing_missing")
        self.assertEqual(issue["severity"], "block")
        self.assertEqual(issue["anchor"], "第 12 行")


if __name__ == "__main__":
    unittest.main()
