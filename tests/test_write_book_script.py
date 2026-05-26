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

    def test_snapshot_runs_on_both_success_and_failure_exit(self) -> None:
        """Iter 019 audit fix regression: the pre-fix script had its
        snapshot block AFTER the exit 2 line, so retry-exhausted runs
        skipped the snapshot and the user lost diagnostics. The fix
        extracts a ``take_snapshot`` helper called from BOTH paths.
        Verify the helper exists and is invoked from both code paths.
        """
        self.assertIn("take_snapshot()", self.text)
        # Failure path uses an _aborted_chNN suffix; success path uses "".
        self.assertIn("take_snapshot \"_aborted_ch", self.text)
        self.assertIn("take_snapshot \"\"", self.text)
        # And the call to take_snapshot in the failure path must happen
        # BEFORE the exit 2 statement, not after. We match the literal
        # `exit 2` STATEMENT (anchored at start of line, ignoring
        # whitespace) rather than substring search, which would hit any
        # comment that mentions "exit 2".
        import re

        giveup_idx = self.text.find("GAVE UP on chapter")
        exit2_match = re.search(r"^\s*exit\s+2\b", self.text[giveup_idx:], re.MULTILINE)
        self.assertIsNotNone(exit2_match, "couldn't find an exit 2 statement after GAVE UP")
        exit2_idx = giveup_idx + exit2_match.start()
        snap_idx = self.text.find("take_snapshot \"_aborted_ch", giveup_idx)
        self.assertGreater(snap_idx, giveup_idx, "snapshot call must follow the GAVE UP message")
        self.assertLess(snap_idx, exit2_idx, "snapshot must run BEFORE exit 2 or it's never executed")


    def test_clear_chapter_state_preserves_last_failure(self) -> None:
        """Debug fix: ``clear_chapter_state`` used to ``rm -f`` the meta /
        md / failure files between retries. After 3 retries all rejected,
        the user lost the most recent meta.json — so we never knew which
        reviewer agent flagged the chapter or why. Fix: rename the files
        to ``chapter_NN.last_failure_attemptN.{ext}`` instead of deleting.
        """
        # Helper accepts a second positional argument (the attempt number).
        self.assertRegex(
            self.text,
            r"clear_chapter_state\s*\(\s*\)\s*\{[^}]*local\s+attempt=",
            "clear_chapter_state must accept an 'attempt' positional arg",
        )
        # No more `rm -f` of the per-chapter outputs.
        self.assertNotRegex(
            self.text,
            r'rm\s+-f\s+"\$\{?prefix\}?\.md"',
            "clear_chapter_state must not rm -f the chapter outputs anymore",
        )
        # Files are moved to a last_failure_attemptN.* suffix.
        self.assertIn("last_failure_attempt", self.text)
        self.assertIn("mv -f", self.text)
        # The call site passes the attempt counter.
        self.assertIn('clear_chapter_state "$i" "$attempted"', self.text)

    def test_take_snapshot_includes_last_failure_files(self) -> None:
        """Debug fix companion: the snapshot helper must also copy the
        preserved ``last_failure_attempt*`` files, otherwise the
        post-mortem diagnostics disappear once the chapter eventually
        succeeds and the success snapshot overwrites the workspace state.
        """
        # take_snapshot must have a line copying last_failure_attempt* files.
        self.assertIn(
            'chapter_*.last_failure_attempt*.*',
            self.text,
            "take_snapshot must cp the preserved last_failure files into the snapshot",
        )

    def test_pipestatus_exit_code_propagation(self) -> None:
        """Iter 022 B6: write_book.sh must `exit "${PIPESTATUS[0]}"` after the
        main `{ ... } | tee` pipeline. Bare pipefail does not reliably
        propagate `exit 2` from inside the brace block on all platforms
        (iter 020/021 ch10 GAVE UP returned exit 0 to the harness despite
        the inner exit 2). PIPESTATUS captures the left stage explicitly.
        """
        self.assertIn(
            'exit "${PIPESTATUS[0]}"',
            self.text,
            "must capture left-pipe exit code via PIPESTATUS[0]",
        )

    def test_pipestatus_pattern_works_in_subshell(self) -> None:
        """Iter 022 B6: end-to-end verification that the PIPESTATUS pattern
        actually propagates a non-zero exit. Spawns bash with the same
        idiom write_book.sh uses and checks the returncode.
        """
        import subprocess

        result = subprocess.run(
            [
                "bash",
                "-c",
                '{ echo "hi"; exit 7; } 2>&1 | tee /dev/null; exit "${PIPESTATUS[0]}"',
            ],
            check=False,
            capture_output=True,
        )
        self.assertEqual(
            result.returncode,
            7,
            f"expected exit 7 propagated via PIPESTATUS; got {result.returncode}",
        )


if __name__ == "__main__":
    unittest.main()
