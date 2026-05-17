import unittest

from src.linter import NovelLinter


class LinterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.linter = NovelLinter(
            {
                "rules": {
                    "meta_chapter_markers": {"enabled": True},
                    "not_x_but_y": {"enabled": True},
                    "short_sentence_openings": {"enabled": True, "threshold": 3, "window": 5},
                    "name_drift": {
                        "enabled": True,
                        "disallowed_terms": [{"wrong": "凯撒", "correct": "恺撒"}],
                    },
                    "ai_cliche_terms": {"enabled": True, "terms": ["命运的齿轮"]},
                }
            }
        )

    def test_flags_not_x_but_y_and_meta_marker(self) -> None:
        issues = self.linter.lint("第 1 章\n这不是雨，是命。")
        rules = {issue["rule"] for issue in issues}
        self.assertIn("meta_chapter_markers", rules)
        self.assertNotIn("not_x_but_y", rules)

    def test_flags_short_openings_name_drift_and_cliche(self) -> None:
        text = "雨停了。\n灯灭了。\n他走了。\n凯撒看着命运的齿轮。"
        issues = self.linter.lint(text)
        rules = {issue["rule"] for issue in issues}
        self.assertIn("short_sentence_openings", rules)
        self.assertIn("name_drift", rules)
        self.assertIn("ai_cliche_terms", rules)

    def test_short_chapter_length_error_triggers_rewrite(self) -> None:
        linter = NovelLinter(
            {
                "rules": {
                    "meta_chapter_markers": {"enabled": False},
                    "not_x_but_y": {"enabled": False},
                    "short_sentence_openings": {"enabled": False},
                    "name_drift": {"enabled": False},
                    "ai_cliche_terms": {"enabled": False},
                    "short_chapter_length": {"enabled": True},
                }
            }
        )
        issues = linter.lint("路明非" * 100)
        self.assertEqual(issues[0]["rule"], "short_chapter_length")
        self.assertEqual(issues[0]["severity"], "error")

    def test_not_x_but_y_under_threshold_no_issue(self) -> None:
        linter = NovelLinter(_only_not_x_config())
        text = "这不是雨，是命。\n那不是门，是影子。"
        issues = linter.lint(text)
        self.assertEqual([issue for issue in issues if issue["rule"] == "not_x_but_y"], [])

    def test_not_x_but_y_threshold_warn_when_3_to_4(self) -> None:
        linter = NovelLinter(_only_not_x_config())
        text = "\n".join(f"这不是雨，是命{i}。" for i in range(3))
        issues = [issue for issue in linter.lint(text) if issue["rule"] == "not_x_but_y"]
        self.assertEqual(len(issues), 3)
        self.assertTrue(all(issue["severity"] == "warning" for issue in issues))
        self.assertTrue(all(issue["count"] == 3 for issue in issues))

    def test_not_x_but_y_threshold_error_when_5_plus(self) -> None:
        linter = NovelLinter(_only_not_x_config())
        text = "\n".join(f"这不是雨，是命{i}。" for i in range(5))
        issues = [issue for issue in linter.lint(text) if issue["rule"] == "not_x_but_y"]
        self.assertEqual(len(issues), 5)
        self.assertTrue(all(issue["severity"] == "error" for issue in issues))
        self.assertTrue(all(issue["count"] == 5 for issue in issues))

    def test_lint_issue_contains_anchor_field(self) -> None:
        issues = self.linter.lint("雨停了。\n灯灭了。\n他走了。\n凯撒看着命运的齿轮。")
        self.assertTrue(issues)
        self.assertTrue(all("anchor" in issue for issue in issues))
        self.assertTrue(any(issue["anchor"] for issue in issues))


def _only_not_x_config() -> dict:
    return {
        "rules": {
            "meta_chapter_markers": {"enabled": False},
            "not_x_but_y": {"enabled": True, "warn_threshold": 2, "error_threshold": 5},
            "short_sentence_openings": {"enabled": False},
            "name_drift": {"enabled": False},
            "ai_cliche_terms": {"enabled": False},
            "short_chapter_length": {"enabled": False},
        }
    }


if __name__ == "__main__":
    unittest.main()
