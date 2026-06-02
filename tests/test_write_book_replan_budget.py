"""Iter 029: replan / budget flags are parsed by the wrapper and owned by Python."""

from __future__ import annotations

import unittest
from pathlib import Path


SCRIPT_PATH = Path("scripts/write_book.sh")
RUNNER_PATH = Path("src/book_runner.py")


class WriteBookReplanBudgetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.script = SCRIPT_PATH.read_text(encoding="utf-8")
        self.runner = RUNNER_PATH.read_text(encoding="utf-8")

    def test_replan_every_flag_forwarded(self) -> None:
        self.assertIn("--replan-every", self.script)
        self.assertIn("REPLAN_EVERY=", self.script)
        self.assertIn("append_count=replan_every", self.runner)

    def test_budget_cny_flag_forwarded(self) -> None:
        self.assertIn("--budget-cny", self.script)
        self.assertIn("BUDGET_CNY=", self.script)
        self.assertIn("budget_exceeded", self.runner)

    def test_proposal_validator_moved_to_runner(self) -> None:
        self.assertNotIn("proposal_validator", self.script)
        self.assertIn("validate_proposals_against_plan", self.runner)

    def test_per_chapter_cost_moved_to_runner(self) -> None:
        self.assertNotIn("[cost]", self.script)
        self.assertIn("estimate_cost_since", self.runner)


if __name__ == "__main__":
    unittest.main()
