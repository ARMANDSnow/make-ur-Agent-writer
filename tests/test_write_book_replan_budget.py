"""Iter 024 P2c+P3c+P4b: structural tests for write_book.sh new flags.

Verifies:
* `--replan-every N` flag is parsed
* `--budget-cny N` flag is parsed
* Exit code 3 is documented for budget-ceiling exhaustion
* PIPESTATUS[0] propagation (from iter 022 B6) is preserved
* proposal_validator integration call is present in script source
"""

import unittest
from pathlib import Path


SCRIPT_PATH = Path("scripts/write_book.sh")


class WriteBookReplanBudgetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.text = SCRIPT_PATH.read_text(encoding="utf-8")

    def test_replan_every_flag_parsed(self) -> None:
        """--replan-every K + REPLAN_EVERY shell variable."""
        for needle in ("--replan-every", "REPLAN_EVERY="):
            self.assertIn(needle, self.text, f"missing {needle!r}")

    def test_budget_cny_flag_parsed(self) -> None:
        for needle in ("--budget-cny", "BUDGET_CNY="):
            self.assertIn(needle, self.text, f"missing {needle!r}")

    def test_exit_code_3_for_budget(self) -> None:
        """Budget exhaustion exits with code 3 (distinct from 0=success
        and 2=retry exhausted)."""
        # exit 3 statement must appear in a BUDGET context (within
        # ~20 lines after a [BUDGET] log line)
        budget_idx = self.text.find("[BUDGET]")
        self.assertGreater(budget_idx, 0, "no [BUDGET] marker in script")
        exit3_idx = self.text.find("exit 3", budget_idx)
        self.assertGreater(exit3_idx, budget_idx, "no 'exit 3' after [BUDGET]")
        # Should be close to the BUDGET section (within ~600 chars)
        self.assertLess(exit3_idx - budget_idx, 600)

    def test_pipestatus_propagation_preserved(self) -> None:
        """iter 022 B6 fix must survive iter 024 changes."""
        self.assertIn('exit "${PIPESTATUS[0]}"', self.text)

    def test_proposal_validator_integration(self) -> None:
        """write_book.sh runs validate_proposals_against_plan before
        each auto apply-advance."""
        for needle in ("proposal_validator", "validate_proposals_against_plan"):
            self.assertIn(needle, self.text, f"missing {needle!r}")

    def test_auto_replan_invokes_plan_chapters_append(self) -> None:
        """re-plan trigger calls main.py plan-chapters --append."""
        self.assertIn("plan-chapters", self.text)
        self.assertIn("--append", self.text)
        # The auto-replan log marker (for monitoring)
        self.assertIn("Auto re-plan", self.text)

    def test_per_chapter_cost_logging(self) -> None:
        """[cost] marker line so users see cumulative spend in log."""
        self.assertIn("[cost]", self.text)
        self.assertIn("cumulative", self.text)


if __name__ == "__main__":
    unittest.main()
