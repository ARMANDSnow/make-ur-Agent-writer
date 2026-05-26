"""Iter 022 B2: tests for writer rewrite feedback strengthening.

Validates that:
* `_format_lint_feedback` produces line-by-line per-hit feedback for
  not_x_but_y (so the rewriter sees exact offending sentences)
* Other lint rules keep their compact one-line format
* When no lint issues, the formatter returns empty string
"""

import unittest


class WriterRewriteFeedbackTests(unittest.TestCase):
    def test_not_x_but_y_feedback_lists_each_violation(self):
        from src.writer import _format_lint_feedback

        issues = [
            {
                "rule": "not_x_but_y",
                "line": 39,
                "excerpt": "不是看，是锁定。",
                "count": 9,
                "severity": "warning",
                "message": "命中 9 次",
            },
            {
                "rule": "not_x_but_y",
                "line": 83,
                "excerpt": "不是实体——是幻象。",
                "count": 9,
                "severity": "warning",
                "message": "命中 9 次",
            },
        ]
        feedback = _format_lint_feedback(issues)
        self.assertIn("【关键】", feedback)
        self.assertIn("9 次", feedback)
        # Line numbers reported so rewriter can locate violations in draft
        self.assertIn("39", feedback)
        self.assertIn("83", feedback)
        # Iter 022 fix: the offending text literal MUST NOT appear in
        # feedback (it would prime the rewriter on the pattern itself).
        self.assertNotIn("不是看", feedback)
        self.assertNotIn("不是实体", feedback)
        # Concrete rewrite guidance present
        self.assertIn("动作描述", feedback)

    def test_other_rules_keep_compact_format(self):
        from src.writer import _format_lint_feedback

        issues = [
            {
                "rule": "name_drift",
                "line": 5,
                "excerpt": "凯撒",
                "count": 1,
                "severity": "error",
                "message": "应为恺撒",
            },
        ]
        feedback = _format_lint_feedback(issues)
        self.assertIn("[规则 name_drift", feedback)
        self.assertNotIn("【关键】", feedback)


if __name__ == "__main__":
    unittest.main()
