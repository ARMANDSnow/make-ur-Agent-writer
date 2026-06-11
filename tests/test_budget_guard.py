"""iter 050 (F): cost-guard hardening.

Web-started write-book jobs used to default to ``budget_cny=0.0`` (no cap)
whenever the caller omitted the field — an open-ended spend with a real
model configured. Now the default comes from ``NOVEL_DEFAULT_BUDGET_CNY``
(else 10.0元), an explicit ``budget_cny`` (including 0 = uncapped) still
wins, and preflight WARNs when a real-model setup has no explicit ceiling.

Mock-only.
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from src.web.jobs import _default_budget_cny, _step_write_book


class DefaultBudgetTests(unittest.TestCase):
    def test_default_is_10_when_env_unset(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NOVEL_DEFAULT_BUDGET_CNY", None)
            self.assertEqual(_default_budget_cny(), 10.0)

    def test_env_overrides_default(self) -> None:
        with patch.dict(os.environ, {"NOVEL_DEFAULT_BUDGET_CNY": "3.5"}):
            self.assertEqual(_default_budget_cny(), 3.5)

    def test_garbage_env_falls_back(self) -> None:
        with patch.dict(os.environ, {"NOVEL_DEFAULT_BUDGET_CNY": "unlimited"}):
            self.assertEqual(_default_budget_cny(), 10.0)

    def test_step_write_book_applies_default_cap(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NOVEL_DEFAULT_BUDGET_CNY", None)
            with patch("src.web.jobs.run_write_book") as run:
                _step_write_book({}, lambda *_a: None)
                self.assertEqual(run.call_args.kwargs["budget_cny"], 10.0)

    def test_step_write_book_explicit_zero_stays_uncapped(self) -> None:
        # CLI semantics preserved: an explicit 0 means "no cap" and must not
        # be overwritten by the default.
        with patch("src.web.jobs.run_write_book") as run:
            _step_write_book({"budget_cny": 0}, lambda *_a: None)
            self.assertEqual(run.call_args.kwargs["budget_cny"], 0.0)

    def test_step_write_book_env_default(self) -> None:
        with patch.dict(os.environ, {"NOVEL_DEFAULT_BUDGET_CNY": "5"}):
            with patch("src.web.jobs.run_write_book") as run:
                _step_write_book({}, lambda *_a: None)
                self.assertEqual(run.call_args.kwargs["budget_cny"], 5.0)


class PreflightBudgetWarnTests(unittest.TestCase):
    def _warns(self, *, mock_mode: bool, env: str | None) -> list:
        from src.preflight import _check_budget_guard

        warn: list = []
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NOVEL_DEFAULT_BUDGET_CNY", None)
            if env is not None:
                os.environ["NOVEL_DEFAULT_BUDGET_CNY"] = env
            _check_budget_guard(warn, mock_mode)
        return warn

    def test_mock_mode_is_silent(self) -> None:
        self.assertEqual(self._warns(mock_mode=True, env=None), [])

    def test_real_model_without_env_warns(self) -> None:
        warns = self._warns(mock_mode=False, env=None)
        self.assertEqual(len(warns), 1)
        self.assertIn("NOVEL_DEFAULT_BUDGET_CNY", warns[0])

    def test_real_model_with_valid_env_is_silent(self) -> None:
        self.assertEqual(self._warns(mock_mode=False, env="15"), [])

    def test_real_model_with_garbage_env_warns(self) -> None:
        warns = self._warns(mock_mode=False, env="abc")
        self.assertEqual(len(warns), 1)
        self.assertIn("not a number", warns[0])


if __name__ == "__main__":
    unittest.main()
