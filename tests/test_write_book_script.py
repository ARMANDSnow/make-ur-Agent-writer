"""Iter 029: write_book.sh is a compatibility wrapper only."""

from __future__ import annotations

import unittest
from pathlib import Path


SCRIPT_PATH = Path("scripts/write_book.sh")


class WriteBookScriptWrapperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = SCRIPT_PATH.read_text(encoding="utf-8")

    def test_delegates_to_python_write_book(self) -> None:
        self.assertIn("main.py", self.text)
        self.assertIn("write-book", self.text)
        self.assertIn('exec "${cmd[@]}"', self.text)

    def test_accepts_legacy_production_flags(self) -> None:
        for flag in (
            "--book",
            "--chapters",
            "--resume-from",
            "--max-retries",
            "--min-confidence",
            "--no-auto-advance",
            "--replan-every",
            "--budget-cny",
            "--allow-missing-start-point",
            "--skip-external-review",
        ):
            self.assertIn(flag, self.text)

    def test_no_raw_chapter_loop_or_subcommands(self) -> None:
        forbidden = [
            "python3 main.py ${BOOK:+--book $BOOK} write",
            "review-chapter",
            "chapter-status",
            "for i in $(seq",
            "GAVE UP on chapter",
            "PIPESTATUS",
        ]
        for needle in forbidden:
            self.assertNotIn(needle, self.text)

    def test_missing_value_exits_64_with_clear_message(self) -> None:
        import subprocess

        result = subprocess.run(
            ["bash", str(SCRIPT_PATH), "--book"],
            check=False,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 64)
        self.assertIn("--book requires a value", result.stderr)


if __name__ == "__main__":
    unittest.main()
