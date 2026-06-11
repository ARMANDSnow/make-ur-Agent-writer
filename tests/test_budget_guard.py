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
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.web.jobs import _default_budget_cny, _review_budget_cny, _step_write_book


class DefaultBudgetTests(unittest.TestCase):
    def test_default_is_10_when_env_unset(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NOVEL_DEFAULT_BUDGET_CNY", None)
            self.assertEqual(_default_budget_cny(), 10.0)

    def test_env_overrides_default(self) -> None:
        with patch.dict(os.environ, {"NOVEL_DEFAULT_BUDGET_CNY": "3.5"}):
            self.assertEqual(_default_budget_cny(), 3.5)

    def test_garbage_env_falls_back(self) -> None:
        # iter 050d (L-3): nan compares False with everything (gate would
        # never trip); inf/negative are equally meaningless as caps.
        for bad in ("unlimited", "nan", "inf", "-inf", "-5"):
            with patch.dict(os.environ, {"NOVEL_DEFAULT_BUDGET_CNY": bad}):
                self.assertEqual(_default_budget_cny(), 10.0, bad)

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


class SharedBudgetHelperTests(unittest.TestCase):
    """iter 051b: config.budget_cny_from_env / parse_budget_cny are the single
    source of truth for the iter 050 L-3 validation rules — both env caps
    (write default + review) and preflight share them."""

    def test_parse_budget_cny_matrix(self) -> None:
        from src.config import parse_budget_cny

        self.assertEqual(parse_budget_cny("3.5"), 3.5)
        self.assertEqual(parse_budget_cny("0"), 0.0)  # explicit uncapped is VALID
        for bad in ("unlimited", "nan", "inf", "-inf", "-5", "", None):
            self.assertIsNone(parse_budget_cny(bad), bad)

    def test_env_unset_falls_back(self) -> None:
        from src.config import budget_cny_from_env

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("X_BUDGET_TEST", None)
            self.assertEqual(budget_cny_from_env("X_BUDGET_TEST", 7.0), 7.0)

    def test_env_value_and_zero_honored(self) -> None:
        from src.config import budget_cny_from_env

        with patch.dict(os.environ, {"X_BUDGET_TEST": "2.5"}):
            self.assertEqual(budget_cny_from_env("X_BUDGET_TEST", 7.0), 2.5)
        with patch.dict(os.environ, {"X_BUDGET_TEST": "0"}):
            self.assertEqual(budget_cny_from_env("X_BUDGET_TEST", 7.0), 0.0)

    def test_env_garbage_falls_back_not_uncapped(self) -> None:
        from src.config import budget_cny_from_env

        for bad in ("unlimited", "nan", "inf", "-inf", "-5"):
            with patch.dict(os.environ, {"X_BUDGET_TEST": bad}):
                self.assertEqual(budget_cny_from_env("X_BUDGET_TEST", 7.0), 7.0, bad)


class ReviewBudgetEnvTests(unittest.TestCase):
    """iter 051b: NOVEL_REVIEW_BUDGET_CNY — independent cap for the
    review-chapter job (same L-3 semantics, 5.0元 fallback)."""

    def test_default_is_5_when_env_unset(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NOVEL_REVIEW_BUDGET_CNY", None)
            self.assertEqual(_review_budget_cny(), 5.0)

    def test_env_overrides_default(self) -> None:
        with patch.dict(os.environ, {"NOVEL_REVIEW_BUDGET_CNY": "2.5"}):
            self.assertEqual(_review_budget_cny(), 2.5)

    def test_env_zero_means_uncapped(self) -> None:
        with patch.dict(os.environ, {"NOVEL_REVIEW_BUDGET_CNY": "0"}):
            self.assertEqual(_review_budget_cny(), 0.0)

    def test_garbage_env_falls_back(self) -> None:
        for bad in ("unlimited", "nan", "inf", "-inf", "-5"):
            with patch.dict(os.environ, {"NOVEL_REVIEW_BUDGET_CNY": bad}):
                self.assertEqual(_review_budget_cny(), 5.0, bad)

    def test_independent_from_write_default_env(self) -> None:
        # The two caps must not crowd each other out of one env knob.
        with patch.dict(
            os.environ,
            {"NOVEL_DEFAULT_BUDGET_CNY": "30", "NOVEL_REVIEW_BUDGET_CNY": "1.5"},
        ):
            self.assertEqual(_default_budget_cny(), 30.0)
            self.assertEqual(_review_budget_cny(), 1.5)


class ReviewChapterBudgetGateTests(unittest.TestCase):
    """iter 051b: _step_review_chapter settles cost after the review
    round-trip and returns the write-book-style ``budget_exceeded`` terminal
    status when over cap. Internals are patched at their source modules (the
    step imports them lazily), so this is a pure gate-semantics test."""

    def setUp(self) -> None:
        os.environ["OPENAI_MODEL"] = "mock"
        self._tmp = tempfile.TemporaryDirectory()
        self._old_ws_env = os.environ.get("WORKSPACE_NAME")
        os.environ["WORKSPACE_NAME"] = "ws051b"
        from src import paths

        self._paths = paths
        self._saved_ws_dir = paths.WORKSPACE_DIR
        paths.WORKSPACE_DIR = Path(self._tmp.name)
        drafts = Path(self._tmp.name) / "ws051b" / "outputs" / "drafts"
        drafts.mkdir(parents=True, exist_ok=True)
        (drafts / "chapter_01.md").write_text("# 第 1 章\n\n正文。\n", encoding="utf-8")

    def tearDown(self) -> None:
        self._paths.WORKSPACE_DIR = self._saved_ws_dir
        if self._old_ws_env is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._old_ws_env
        self._tmp.cleanup()

    def _run(self, params: dict, *, cost: float) -> dict:
        from src.web.jobs import _step_review_chapter

        with patch("src.writer._load_chapter_plan", return_value={1: {"chapter_no": 1}}), \
                patch("src.writer._run_context", return_value={}), \
                patch("src.book_runner._build_review_context", return_value={}), \
                patch("src.reviewer.review_target"), \
                patch(
                    "src.book_runner._sync_meta_with_external_review",
                    return_value={"verdict": "Reject"},
                ), \
                patch(
                    "src.chapter_status.chapter_status",
                    return_value={"approved": False, "strict_failures": []},
                ), \
                patch("src.book_runner._llm_log_line_count", return_value=0), \
                patch(
                    "src.cost_estimator.estimate_cost_since",
                    return_value={"cost_cny": cost},
                ) as est:
            result = _step_review_chapter(params, lambda *_a: None)
        # Settlement must measure from the offset recorded at job start.
        est.assert_called_once_with(0)
        return result

    def test_over_default_env_cap_returns_budget_exceeded(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NOVEL_REVIEW_BUDGET_CNY", None)
            result = self._run({"chapter": 1}, cost=7.5)
        self.assertEqual(result["status"], "budget_exceeded")
        self.assertEqual(result["cost_cny"], 7.5)
        self.assertEqual(result["budget_cny"], 5.0)
        # write-book parity: the worker maps this status to a terminal state.
        from src.web.jobs import TERMINAL_STATUSES

        self.assertIn("budget_exceeded", TERMINAL_STATUSES)

    def test_under_cap_succeeds_with_cost_fields(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NOVEL_REVIEW_BUDGET_CNY", None)
            result = self._run({"chapter": 1}, cost=0.42)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["cost_cny"], 0.42)
        self.assertEqual(result["budget_cny"], 5.0)

    def test_explicit_param_zero_is_uncapped(self) -> None:
        # params.budget_cny wins over env; 0 = no cap (CLI semantics).
        with patch.dict(os.environ, {"NOVEL_REVIEW_BUDGET_CNY": "1"}):
            result = self._run({"chapter": 1, "budget_cny": 0}, cost=99.0)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["budget_cny"], 0.0)

    def test_explicit_param_overrides_env(self) -> None:
        with patch.dict(os.environ, {"NOVEL_REVIEW_BUDGET_CNY": "100"}):
            result = self._run({"chapter": 1, "budget_cny": 2.0}, cost=3.0)
        self.assertEqual(result["status"], "budget_exceeded")
        self.assertEqual(result["budget_cny"], 2.0)
        self.assertEqual(result["cost_cny"], 3.0)

    def test_summary_carries_cost_fields(self) -> None:
        from src.web.jobs import _summarize_result

        summary = _summarize_result(
            "review-chapter",
            {
                "status": "budget_exceeded",
                "chapter": 1,
                "verdict": "Reject",
                "chapter_status": {"strict_failures": []},
                "cost_cny": 7.5,
                "budget_cny": 5.0,
            },
        )
        self.assertEqual(summary["status"], "budget_exceeded")
        self.assertEqual(summary["cost_cny"], 7.5)
        self.assertEqual(summary["budget_cny"], 5.0)


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
        for bad in ("abc", "nan", "inf", "-1"):
            warns = self._warns(mock_mode=False, env=bad)
            self.assertEqual(len(warns), 1, bad)
            self.assertIn("not a usable cap", warns[0])

    def test_workbench_form_prefills_env_default(self) -> None:
        # iter 050d (M-3): the form always submits budget_cny explicitly, so
        # the env default must reach the rendered input value or it would
        # never apply to workbench-started jobs.
        from src.web import templates

        with patch.dict(os.environ, {"NOVEL_DEFAULT_BUDGET_CNY": "5.5"}):
            html = templates.render_workspace_workbench("formws", ["formws"])
            self.assertIn('name="budget_cny"', html)
            self.assertIn('value="5.5"', html)
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NOVEL_DEFAULT_BUDGET_CNY", None)
            html = templates.render_workspace_workbench("formws", ["formws"])
            self.assertIn('value="10"', html)
        self.assertIn("0 = 不设上限", html)


if __name__ == "__main__":
    unittest.main()
