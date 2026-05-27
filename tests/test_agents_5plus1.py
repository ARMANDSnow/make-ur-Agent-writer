"""Iter 023 P4: tests for agent simplification (8 → 5 reviewers + 1 advisor).

Verifies config/agents.yaml has the 5 expected review agents (with new
generic names) and 1 advisor, no Chinese-book-specific agent names
remaining at the legacy level.
"""

import unittest

from src.config import load_config


class Agents5Plus1Tests(unittest.TestCase):
    def setUp(self) -> None:
        # agents.yaml uses the project's standard loader (handles JSON-with-comments etc.)
        self.cfg = load_config("agents.yaml")

    def test_review_agents_count_and_names(self) -> None:
        reviews = self.cfg.get("review_agents", [])
        names = [a.get("name") for a in reviews]
        self.assertEqual(
            len(reviews), 5,
            f"iter 023 should have exactly 5 review agents, got {len(reviews)}: {names}",
        )
        # Generic names (no protagonist-specific 路明非本位, no author 江南人格模拟)
        for expected in (
            "主角本位",
            "角色关系一致性",
            "伏笔猎人",
            "世界观守门人",
            "原作风格模拟",
        ):
            self.assertIn(expected, names, f"missing review agent: {expected}")
        # Old book-specific names removed at the legacy level
        self.assertNotIn("路明非本位", names)
        self.assertNotIn("江南人格模拟", names)
        # Merged agents removed
        self.assertNotIn("情感关系", names)
        self.assertNotIn("连续性审阅", names)
        self.assertNotIn("关系一致性", names)
        self.assertNotIn("读者代言人", names)

    def test_advisor_agents_present(self) -> None:
        advisors = self.cfg.get("advisor_agents", [])
        self.assertEqual(len(advisors), 1, "iter 023 should have exactly 1 advisor")
        self.assertEqual(advisors[0].get("name"), "改写顾问")

    def test_persona_templates_still_present(self) -> None:
        """Iter 016 persona-rendering keeps working: each review agent
        still carries a `system_prompt_template` so per-book personas
        can render the agent prompt."""
        for agent in self.cfg.get("review_agents", []):
            self.assertIn(
                "system_prompt_template", agent,
                f"agent {agent.get('name')} missing system_prompt_template"
            )


if __name__ == "__main__":
    unittest.main()
