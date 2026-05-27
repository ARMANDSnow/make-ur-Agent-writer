"""Iter 023 P5: tests for the deterministic relationship auditor
integration into review_text.

Verifies that when entity_graph has hard-conflict relationships, the
review report gets a synthetic ``deterministic_relations`` agent_review
that forces a Reject verdict — without consuming any LLM calls.
"""

import json
import unittest
from unittest.mock import patch


class ReviewerDeterministicRelationsTests(unittest.TestCase):
    def test_no_conflict_no_synthetic_agent(self) -> None:
        from src.reviewer import review_text
        # All real agents return Approve via mock; no entity_graph conflict
        clean_response = '{"verdict":"Approve","plot":7,"prose":7,"fidelity":7,"issues":[],"suggestions":[]}'
        with patch(
            "src.reviewer.load_entity_graph",
            return_value={"entities": [], "relationships": []},
        ), patch(
            "src.llm_client.LLMClient.complete_text", return_value=clean_response
        ), patch(
            "src.reviewer.write_json"
        ):
            report = review_text("正常正文。", "t.md", precomputed_lint_issues=[])
        agent_names = [r.get("agent_name") for r in report["agent_reviews"]]
        self.assertNotIn("deterministic_relations", agent_names)
        self.assertEqual(report["verdict"], "Approve")

    def test_conflict_adds_synthetic_agent_and_rejects(self) -> None:
        from src.reviewer import review_text
        graph = {
            "entities": [
                {"id": "a", "name": "路明非"},
                {"id": "b", "name": "康斯坦丁"},
            ],
            "relationships": [
                {
                    "src_id": "a",
                    "dst_id": "b",
                    "timeline": [
                        {"active": True, "state": "康斯坦丁已死亡，仅记忆投影"}
                    ],
                }
            ],
        }
        clean_response = '{"verdict":"Approve","plot":8,"prose":8,"fidelity":8,"issues":[],"suggestions":[]}'
        draft = "路明非伸手抓住了康斯坦丁的肩膀。"
        with patch(
            "src.reviewer.load_entity_graph", return_value=graph
        ), patch(
            "src.llm_client.LLMClient.complete_text", return_value=clean_response
        ), patch(
            "src.reviewer.write_json"
        ):
            report = review_text(draft, "t.md", precomputed_lint_issues=[])
        agent_names = [r.get("agent_name") for r in report["agent_reviews"]]
        self.assertIn("deterministic_relations", agent_names)
        # Verdict should flip to Reject because deterministic_relations rejects
        self.assertEqual(report["verdict"], "Reject")


if __name__ == "__main__":
    unittest.main()
