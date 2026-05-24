"""Iter 019: write_book.sh structural tests.

The shell script orchestrates: per-chapter writer → reviewer → status
check → retry loop → auto-apply advance → snapshot. These tests verify
the *structure* of the script (flags, helper functions, removed gate)
rather than executing it end-to-end. The actual run-through is covered
by the iter 019 P5 real-model smoke and by the python-level
``test_chapter_status`` / ``test_apply_advance_auto`` unit tests for
the helpers it calls.
"""

import unittest
from pathlib import Path


SCRIPT_PATH = Path("scripts/write_book.sh")


class WriteBookScriptStructureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = SCRIPT_PATH.read_text(encoding="utf-8")

    def test_no_manual_apply_advance_gate_strings(self) -> None:
        """Iter 019: the old manual-gate reminders must be gone.

        Pre-iter-019 the script printed 'apply-advance --proposal-idx
        <comma-list>' instructions and 'Then re-run' messages and exited
        zero after every non-final chapter, breaking unattended runs.
        """
        forbidden = [
            "--proposal-idx <comma-list>",
            "Then re-run: bash scripts/write_book.sh",
            "=== Dry run:",
            "=== Apply:",
        ]
        for needle in forbidden:
            self.assertNotIn(
                needle,
                self.text,
                f"write_book.sh still contains pre-iter-019 manual-gate string: {needle!r}",
            )

    def test_declares_iter019_flags(self) -> None:
        """The three new flags must all be parsed by the script."""
        for flag in ("--max-retries", "--min-confidence", "--no-auto-advance"):
            self.assertIn(
                flag,
                self.text,
                f"write_book.sh missing iter 019 flag {flag!r}",
            )

    def test_invokes_auto_apply_apply_advance(self) -> None:
        """Per-chapter auto-apply call must use --auto-apply --allow-empty --confirm."""
        for fragment in ("apply-advance", "--auto-apply", "--allow-empty", "--confirm"):
            self.assertIn(
                fragment,
                self.text,
                f"write_book.sh missing apply-advance fragment {fragment!r}",
            )

    def test_has_retry_loop_and_giveup_exit(self) -> None:
        """Retry loop must be present and must exit 2 on exhaustion."""
        self.assertIn("MAX_RETRIES", self.text)
        self.assertIn("GAVE UP on chapter", self.text)
        # exit 2 = retry exhausted, distinct from infra errors.
        self.assertRegex(self.text, r"exit\s+2\b")
        # chapter-status query must be used to detect approval, not raw grep.
        self.assertIn("chapter-status", self.text)


if __name__ == "__main__":
    unittest.main()
