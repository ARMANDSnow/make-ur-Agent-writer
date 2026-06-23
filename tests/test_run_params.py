"""iter064 #1: the core-level run-param validator (src/run_params.py) is the
single source of truth for the numeric caps + finite guards shared by the WebUI
and the CLI/driver.

Before iter064 only the WebUI (routes._int_value/_float_param/
_validate_write_book_params) validated these; the CLI used raw argparse
type=int/float, so `main.py write-book --chapters 999999999` reached
book_runner's list(range(...)) (OOM) and `--budget-cny nan` silently disabled
the cost gate (`current_cost > nan` is always False). These tests pin the
validator and the CLI dispatch guards.

Mock-only; no network, no real workspace data.
"""

from __future__ import annotations

import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

import main
from src import run_params


class ValidateIntTests(unittest.TestCase):
    def test_finite_in_range_passes(self) -> None:
        err, val = run_params.validate_int(5, "chapters", minimum=1, maximum=2000)
        self.assertIsNone(err)
        self.assertEqual(val, 5)

    def test_string_int_coerced(self) -> None:
        err, val = run_params.validate_int("12", "chapters", minimum=1, maximum=2000)
        self.assertIsNone(err)
        self.assertEqual(val, 12)

    def test_below_minimum_rejected(self) -> None:
        err, _ = run_params.validate_int(0, "chapters", minimum=1, maximum=2000)
        self.assertIsNotNone(err)
        self.assertIn(">= 1", err)

    def test_above_maximum_rejected(self) -> None:
        err, _ = run_params.validate_int(999999999, "chapters", minimum=1, maximum=2000)
        self.assertIsNotNone(err)
        self.assertIn("<= 2000", err)

    def test_native_float_infinity_rejected(self) -> None:
        # int(float('inf')) raises OverflowError — must be caught at the boundary.
        err, _ = run_params.validate_int(float("inf"), "chapters")
        self.assertIsNotNone(err)
        self.assertIn("finite", err)

    def test_native_float_nan_rejected(self) -> None:
        err, _ = run_params.validate_int(float("nan"), "chapters")
        self.assertIsNotNone(err)
        self.assertIn("finite", err)

    def test_non_numeric_string_rejected(self) -> None:
        err, _ = run_params.validate_int("inf", "chapters")
        self.assertIsNotNone(err)
        self.assertIn("integer", err)


class ValidateFloatTests(unittest.TestCase):
    def test_finite_in_range_passes(self) -> None:
        err, val = run_params.validate_float("3.5", "budget_cny", 0.0, minimum=0.0)
        self.assertIsNone(err)
        self.assertEqual(val, 3.5)

    def test_blank_allowed_returns_default(self) -> None:
        for blank in (None, ""):
            err, val = run_params.validate_float(blank, "timeout_minutes", 0.0, allow_blank=True)
            self.assertIsNone(err)
            self.assertEqual(val, 0.0)

    def test_blank_disallowed_is_error(self) -> None:
        err, _ = run_params.validate_float("", "budget_cny", 0.0, allow_blank=False)
        self.assertIsNotNone(err)
        self.assertIn("number", err)

    def test_nan_rejected(self) -> None:
        for bad in (float("nan"), float("inf"), "nan", "inf", "-inf"):
            err, _ = run_params.validate_float(bad, "budget_cny", 0.0)
            self.assertIsNotNone(err, bad)
            self.assertIn("finite", err)

    def test_over_maximum_rejected(self) -> None:
        err, _ = run_params.validate_float("1.1", "min_confidence", 0.7, minimum=0.0, maximum=1.0)
        self.assertIsNotNone(err)
        self.assertIn("<= 1.0", err)


class ValidateRunParamsTests(unittest.TestCase):
    def test_all_in_range_passes(self) -> None:
        err, out = run_params.validate_run_params(
            {"chapters": 5, "budget_cny": 1.5, "min_confidence": 0.8},
            fields=("chapters", "budget_cny", "min_confidence"),
        )
        self.assertIsNone(err)
        self.assertEqual(out["chapters"], 5)
        self.assertEqual(out["budget_cny"], 1.5)

    def test_missing_key_uses_table_default(self) -> None:
        err, out = run_params.validate_run_params({}, fields=("chapters", "max_retries"))
        self.assertIsNone(err)
        self.assertEqual(out["chapters"], run_params.INT_CAPS["chapters"][0])
        self.assertEqual(out["max_retries"], run_params.INT_CAPS["max_retries"][0])

    def test_oom_chapters_rejected(self) -> None:
        err, _ = run_params.validate_run_params({"chapters": 999999999}, fields=("chapters",))
        self.assertIsNotNone(err)
        self.assertIn("chapters", err)

    def test_nan_budget_rejected(self) -> None:
        err, _ = run_params.validate_run_params({"budget_cny": float("nan")}, fields=("budget_cny",))
        self.assertIsNotNone(err)
        self.assertIn("budget_cny", err)

    def test_target_chapters_capped_at_200(self) -> None:
        err, _ = run_params.validate_run_params({"target_chapters": 201}, fields=("target_chapters",))
        self.assertIsNotNone(err)
        self.assertIn("<= 200", err)

    def test_unknown_field_raises(self) -> None:
        with self.assertRaises(KeyError):
            run_params.validate_run_params({"bogus": 1}, fields=("bogus",))


class CliRunParamGuardTests(unittest.TestCase):
    """The CLI dispatch arms hard-reject out-of-range / non-finite numerics with
    SystemExit(2) before the runner ever sees them."""

    def _run_cli_expect_exit(self, argv, code) -> str:
        with patch("sys.argv", ["main.py"] + argv):
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                with self.assertRaises(SystemExit) as cm:
                    main.main()
            self.assertEqual(cm.exception.code, code, err.getvalue())
            return err.getvalue()

    def test_write_book_oom_chapters_exits_2(self) -> None:
        err = self._run_cli_expect_exit(["write-book", "--chapters", "999999999"], 2)
        self.assertIn("chapters", err)

    def test_write_book_nan_budget_exits_2(self) -> None:
        err = self._run_cli_expect_exit(["write-book", "--budget-cny", "nan"], 2)
        self.assertIn("budget_cny", err)

    def test_write_book_min_confidence_over_one_exits_2(self) -> None:
        err = self._run_cli_expect_exit(["write-book", "--min-confidence", "2"], 2)
        self.assertIn("min_confidence", err)

    def test_write_readiness_oom_chapters_exits_2(self) -> None:
        err = self._run_cli_expect_exit(["write-readiness", "--chapters", "999999999"], 2)
        self.assertIn("chapters", err)

    def test_plan_chapters_target_over_200_exits_2(self) -> None:
        err = self._run_cli_expect_exit(["plan-chapters", "--chapters", "999"], 2)
        self.assertIn("target_chapters", err)

    def test_helper_passes_valid_params(self) -> None:
        # A within-caps set must NOT raise (the guard is silent on the happy path).
        main._validate_cli_run_params(
            {"chapters": 3, "resume_from": 1, "budget_cny": 0.0, "min_confidence": 0.7},
            fields=("chapters", "resume_from", "budget_cny", "min_confidence"),
        )


if __name__ == "__main__":
    unittest.main()
