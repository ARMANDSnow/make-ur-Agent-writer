import unittest
from pathlib import Path
from unittest.mock import patch

from src.reviewer import review_text
from src.reviewer import load_review_agents


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

        def fake_complete_text(self, messages):
            captured["prompt"] = "\n".join(m.get("content", "") for m in messages)
            return '{"agent_name":"agent","verdict":"Approve","score":8,"issues":[],"suggestions":[]}'

        with patch("src.reviewer.global_facts_summary", return_value="FACT: 绘梨衣已死亡"), patch(
            "src.llm_client.LLMClient.complete_text", fake_complete_text
        ), patch("src.reviewer.load_review_agents", return_value=[{"name": "agent", "system_prompt": "review"}]):
            report = review_text("干净正文。", "clean.md", precomputed_lint_issues=[])
        self.assertEqual(report["verdict"], "Approve")
        self.assertIn("FACT: 绘梨衣已死亡", captured["prompt"])

    def test_missing_agent_name_is_repaired_from_config(self) -> None:
        def fake_complete_text(self, messages):
            return '{"verdict":"Approve","score":8,"issues":[],"suggestions":[]}'

        with patch("src.reviewer.load_review_agents", return_value=[{"name": "文本守门人", "system_prompt": "review"}]), patch(
            "src.llm_client.LLMClient.complete_text", fake_complete_text
        ):
            report = review_text("干净正文。", "missing_agent.md", precomputed_lint_issues=[])

        self.assertEqual(report["agent_reviews"][0]["agent_name"], "文本守门人")
        self.assertEqual(report["verdict"], "Approve")

    def test_relationship_consistency_agent_in_review_pipeline(self) -> None:
        graph = {
            "entities": [
                {"id": "a", "name": "甲", "type": "character", "key_facts": ["事实甲"]},
                {"id": "b", "name": "乙", "type": "character", "key_facts": ["事实乙"]},
            ],
            "relationships": [
                {
                    "src_id": "a",
                    "dst_id": "b",
                    "relation_type": "同盟",
                    "timeline": [{"anchor_chapter": "now", "state": "当前必须互相信任", "active": True}],
                }
            ],
        }
        captured = {}

        def fake_complete_text(self, messages):
            prompt = "\n".join(m.get("content", "") for m in messages)
            agent_name = prompt.split("agent_name: ", 1)[1].split("\n", 1)[0]
            captured[agent_name] = prompt
            return '{"verdict":"Approve","score":8,"issues":[],"suggestions":[]}'

        self.assertIn("关系一致性", [agent["name"] for agent in load_review_agents()])
        with patch("src.reviewer.load_entity_graph", return_value=graph), patch(
            "src.llm_client.LLMClient.complete_text", fake_complete_text
        ):
            report = review_text("干净正文。", "relationship.md", precomputed_lint_issues=[])

        self.assertEqual(report["verdict"], "Approve")
        self.assertIn("关系一致性", [item["agent_name"] for item in report["agent_reviews"]])
        self.assertIn("当前必须互相信任", captured["关系一致性"])
        self.assertIn("人工全局事实", captured["关系一致性"])


if __name__ == "__main__":
    unittest.main()
