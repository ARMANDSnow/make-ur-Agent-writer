"""Iter 022 B4: tests for reviewer reading KB + source chapters.

Validates that:
* `review_text(knowledge=...)` injects KB block into per-agent prompt
* `review_text(source_chapters=...)` injects source block
* Empty defaults → no blocks (iter 021 byte-identical behavior)

Uses mock-only: patches LLMClient.complete_text to capture per-agent
prompts without making real API calls.
"""

import json
import unittest
from unittest.mock import patch


def _capture_prompts():
    captured: list[str] = []

    def fake_complete_text(self, messages, **kwargs):
        captured.append(messages[1]["content"] if len(messages) > 1 else "")
        return json.dumps({
            "verdict": "Approve",
            "plot": 7,
            "prose": 7,
            "fidelity": 7,
            "issues": [],
            "suggestions": [],
        })

    return captured, fake_complete_text


class ReviewerKBSourceInjectionTests(unittest.TestCase):
    def test_no_knowledge_no_source_no_injection(self):
        from src.llm_client import LLMClient
        from src.reviewer import review_text

        captured, fake = _capture_prompts()
        with patch.object(LLMClient, "complete_text", fake):
            review_text(
                text="测试章节正文 " * 100,
                target_name="iter022_no_injection",
                precomputed_lint_issues=[],  # skip lint, force agent calls
            )
        self.assertTrue(captured, "no LLM calls captured")
        for prompt in captured:
            self.assertNotIn("# 全局知识 (KB)", prompt)
            self.assertNotIn("# 原文风格参考", prompt)

    def test_kb_and_source_inject_into_prompt(self):
        from src.llm_client import LLMClient
        from src.reviewer import review_text

        captured, fake = _capture_prompts()
        # Iter 024 P1: advisor agents (改写顾问) added after review_agents.
        # advisor prompts do NOT include KB/source blocks (different
        # purpose). Patch advisor list to [] so this test only sees
        # review-agent prompts (matches iter 022/023 behavior).
        with patch.object(LLMClient, "complete_text", fake), patch(
            "src.reviewer.load_advisor_agents", return_value=[]
        ):
            review_text(
                text="测试章节正文 " * 100,
                target_name="iter022_with_injection",
                knowledge="KB-MARKER-TEST-12345",
                source_chapters="SOURCE-MARKER-TEST-67890",
                precomputed_lint_issues=[],  # skip lint, force agent calls
            )
        # All 5 review agents should see both blocks
        self.assertTrue(captured, "no LLM calls captured")
        for prompt in captured:
            self.assertIn("# 全局知识 (KB)", prompt)
            self.assertIn("KB-MARKER-TEST-12345", prompt)
            self.assertIn("# 原文风格参考", prompt)
            self.assertIn("SOURCE-MARKER-TEST-67890", prompt)
            # Anchor text instructing fidelity to use source
            self.assertIn("fidelity 评分", prompt)


if __name__ == "__main__":
    unittest.main()
