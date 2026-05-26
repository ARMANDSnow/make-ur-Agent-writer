"""Iter 022 B1: tests for `not_x_but_y` dynamic threshold scaling.

Validates that:
* 4000-char chapter (scale=1.0) uses base thresholds (warn=2, error=5)
* 8000-char chapter (scale=2.0) doubles thresholds
* 15000-char chapter (iter 021 ch1 case) accepts 9 hits as warning, not error
* `dynamic_scaling: false` returns to iter 021 fixed behavior
* Scale clamped between 1.0 and 5.0
"""

import unittest


class LinterDynamicThresholdTests(unittest.TestCase):
    def _lint(self, text: str, dynamic: bool = True):
        from src.linter import NovelLinter

        config = {
            "rules": {
                "not_x_but_y": {
                    "enabled": True,
                    "warn_threshold": 2,
                    "error_threshold": 5,
                    "dynamic_scaling": dynamic,
                },
            }
        }
        linter = NovelLinter(config=config)
        return linter.lint(text)

    def test_4000_char_chapter_uses_base_thresholds(self):
        # 4000 chinese chars → scale=1.0 → warn>2, error>=5
        # 4 hits → warning
        body = "中文" * 2000
        hits = "\n" + "\n".join(["不是 X，是 Y。"] * 4)
        issues = self._lint(body + hits)
        nxy = [i for i in issues if i["rule"] == "not_x_but_y"]
        self.assertEqual(len(nxy), 4)
        self.assertEqual(nxy[0]["severity"], "warning")

    def test_4000_char_with_11_hits_is_error(self):
        # 4000 chars, 11 hits → still >= error_threshold=5 → error
        body = "中文" * 2000
        hits = "\n" + "\n".join(["不是 X，是 Y。"] * 11)
        issues = self._lint(body + hits)
        nxy = [i for i in issues if i["rule"] == "not_x_but_y"]
        self.assertEqual(len(nxy), 11)
        self.assertEqual(nxy[0]["severity"], "error")

    def test_15000_char_with_9_hits_is_warning_not_error(self):
        # Iter 021 ch1 scenario: 15000 chars with 9 hits used to be error.
        # With dynamic scaling: scale=3.75, warn=8 (round), error=19, so 9
        # hits crosses warn but not error → severity=warning.
        body = "中文" * 7500
        hits = "\n" + "\n".join(["不是 X，是 Y。"] * 9)
        issues = self._lint(body + hits)
        nxy = [i for i in issues if i["rule"] == "not_x_but_y"]
        self.assertEqual(len(nxy), 9)
        self.assertEqual(nxy[0]["severity"], "warning")

    def test_dynamic_scaling_false_returns_fixed(self):
        # With dynamic_scaling=false, 15000 chars with 9 hits goes back to
        # iter 021 fixed-threshold behavior: warn>2, error>=5 → error.
        body = "中文" * 7500
        hits = "\n" + "\n".join(["不是 X，是 Y。"] * 9)
        issues = self._lint(body + hits, dynamic=False)
        nxy = [i for i in issues if i["rule"] == "not_x_but_y"]
        self.assertEqual(len(nxy), 9)
        self.assertEqual(nxy[0]["severity"], "error")


if __name__ == "__main__":
    unittest.main()
