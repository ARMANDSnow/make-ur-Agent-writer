"""Iter 024 P1b: tests for writer._review_feedback() consumption of
advisor's RewriteSuggestion list.

Verifies that when reviewer report contains rewrite_suggestions, the
feedback string includes a dedicated "改写顾问建议" section. When
empty, behavior matches iter 023 (no extra section, byte-identical).
"""

import unittest


class WriterAdvisorFeedbackTests(unittest.TestCase):
    def test_no_rewrite_suggestions_no_advisor_section(self) -> None:
        """iter 023 backward-compat: empty rewrite_suggestions → no
        '改写顾问建议' section in feedback string."""
        from src.writer import _review_feedback
        report = {
            "lint_issues": [],
            "agent_reviews": [
                {
                    "agent_name": "test_agent",
                    "verdict": "Reject",
                    "issues": ["just an issue"],
                    "suggestions": [],
                }
            ],
            "rewrite_suggestions": [],
            "verdict": "Reject",
        }
        feedback = _review_feedback(report)
        self.assertIn("test_agent", feedback)
        self.assertNotIn("改写顾问建议", feedback)

    def test_rewrite_suggestions_appear_in_feedback(self) -> None:
        from src.writer import _review_feedback
        report = {
            "lint_issues": [],
            "agent_reviews": [],
            "rewrite_suggestions": [
                {
                    "section": "开场",
                    "type": "rewrite",
                    "guidance": "把奥丁登场延后两段",
                    "_advisor": "改写顾问",
                },
                {
                    "section": "第 5 段",
                    "type": "add",
                    "guidance": "加主角内心独白",
                    "_advisor": "改写顾问",
                },
            ],
            "verdict": "Reject",
        }
        feedback = _review_feedback(report)
        self.assertIn("改写顾问建议", feedback)
        self.assertIn("把奥丁登场延后两段", feedback)
        self.assertIn("加主角内心独白", feedback)
        # Format: "[advisor] [type] section: guidance"
        self.assertIn("[rewrite]", feedback)
        self.assertIn("[add]", feedback)
        self.assertIn("[改写顾问]", feedback)

    def test_suggestions_capped_at_5(self) -> None:
        from src.writer import _review_feedback
        # 7 suggestions, only 5 should appear
        report = {
            "lint_issues": [],
            "agent_reviews": [],
            "rewrite_suggestions": [
                {"section": f"s{i}", "type": "rewrite", "guidance": f"do thing {i}", "_advisor": "改写顾问"}
                for i in range(7)
            ],
            "verdict": "Reject",
        }
        feedback = _review_feedback(report)
        self.assertIn("do thing 0", feedback)
        self.assertIn("do thing 4", feedback)
        # Last 2 should be dropped
        self.assertNotIn("do thing 5", feedback)
        self.assertNotIn("do thing 6", feedback)

    def test_style_drift_advisor_guidance_uses_existing_channel(self) -> None:
        from src.writer import _review_feedback

        report = {
            "lint_issues": [],
            "agent_reviews": [],
            "rewrite_suggestions": [
                {
                    "section": "全文句式节奏",
                    "type": "rewrite",
                    "guidance": "拆分解释性长句，不改剧情事实。",
                    "_advisor": "style_drift_advisor",
                    "dimension": "avg_sentence_length",
                    "current_value": 42.0,
                    "target_range": {"min": 18.0, "max": 22.0},
                }
            ],
            "verdict": "Reject",
        }
        feedback = _review_feedback(report)
        self.assertIn("[style_drift_advisor]", feedback)
        self.assertIn("拆分解释性长句", feedback)


if __name__ == "__main__":
    unittest.main()
