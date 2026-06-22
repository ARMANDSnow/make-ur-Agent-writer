"""iter058 #1: the onboarding auto-pipeline now honors budget_cny.

Before this fix ``run_auto_pipeline`` had no budget parameter, so the wizard's
budget field (placed into job_params) was silently dropped — a real model ran
the full 9-step pipeline past any cap (audit §3.1: a ¥0.001 cap still made 9
real calls over 293s). The fix threads ``budget_cny`` through the pipeline,
settles cost between LLM-spending steps (reusing write-book's
``estimate_cost_since`` / ``BudgetExceeded``), and maps a breach to the
``budget_exceeded`` terminal status — and applies the same default cap as
write-book when the caller omits it.

Mock-only; cost is simulated by patching estimate_cost_since (mock model cost
is ~0, so a real-cost test would be non-deterministic).
"""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from src import auto_pipeline
from src.book_runner import BudgetExceeded
from src.web import jobs


def _noop(*_a, **_k) -> None:
    return None


class StepAutoPipelineWiringTests(unittest.TestCase):
    """jobs._step_auto_pipeline reads budget_cny and maps the terminal status.

    Mirrors test_budget_guard.DefaultBudgetTests for the write-book step.
    """

    def test_default_cap_passed_when_omitted(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NOVEL_DEFAULT_BUDGET_CNY", None)
            with patch("src.web.jobs.auto_pipeline.run_auto_pipeline", return_value={}) as run:
                jobs._step_auto_pipeline({}, _noop)
                self.assertEqual(run.call_args.kwargs["budget_cny"], 10.0)

    def test_explicit_zero_stays_uncapped(self) -> None:
        with patch("src.web.jobs.auto_pipeline.run_auto_pipeline", return_value={}) as run:
            jobs._step_auto_pipeline({"budget_cny": 0}, _noop)
            self.assertEqual(run.call_args.kwargs["budget_cny"], 0.0)

    def test_explicit_value_overrides_default(self) -> None:
        with patch("src.web.jobs.auto_pipeline.run_auto_pipeline", return_value={}) as run:
            jobs._step_auto_pipeline({"budget_cny": 2.5}, _noop)
            self.assertEqual(run.call_args.kwargs["budget_cny"], 2.5)

    def test_env_default_cap(self) -> None:
        with patch.dict(os.environ, {"NOVEL_DEFAULT_BUDGET_CNY": "5"}):
            with patch("src.web.jobs.auto_pipeline.run_auto_pipeline", return_value={}) as run:
                jobs._step_auto_pipeline({}, _noop)
                self.assertEqual(run.call_args.kwargs["budget_cny"], 5.0)

    def test_greenfield_inherits_budget(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NOVEL_DEFAULT_BUDGET_CNY", None)
            with patch("src.web.jobs.auto_pipeline.run_auto_pipeline", return_value={}) as run:
                jobs._step_auto_pipeline_greenfield({}, _noop)
                self.assertEqual(run.call_args.kwargs["budget_cny"], 10.0)
                # Greenfield forces require_start_point off.
                self.assertFalse(run.call_args.kwargs["require_start_point"])

    def test_budget_exceeded_maps_to_terminal_status(self) -> None:
        with patch(
            "src.web.jobs.auto_pipeline.run_auto_pipeline",
            side_effect=BudgetExceeded(budget_cny=10.0, cost_cny=12.5),
        ):
            result = jobs._step_auto_pipeline({}, _noop)
        self.assertEqual(result["status"], "budget_exceeded")
        self.assertEqual(result["cost_cny"], 12.5)
        self.assertEqual(result["budget_cny"], 10.0)
        self.assertIn("budget_exceeded", jobs.TERMINAL_STATUSES)

    def test_summary_surfaces_budget_fields(self) -> None:
        summary = jobs._summarize_result(
            "auto-pipeline-greenfield",
            {"status": "budget_exceeded", "cost_cny": 12.5, "budget_cny": 10.0},
        )
        self.assertEqual(summary["status"], "budget_exceeded")
        self.assertEqual(summary["cost_cny"], 12.5)
        self.assertEqual(summary["chapters_written"], 0)

    def test_summary_success_path_unchanged(self) -> None:
        # No "status" key (the normal step-keyed result) → summary unchanged.
        summary = jobs._summarize_result(
            "auto-pipeline-greenfield", {"write": [{"chapter": 1}], "debate": {}}
        )
        self.assertEqual(summary, {"chapters_written": 1})


class RunAutoPipelineEarlyStopTests(unittest.TestCase):
    """The gate fires between steps and aborts before the next one runs."""

    @staticmethod
    def _trackers(calls):
        def make(name, ret):
            def _fn(*_a, **_k):
                calls.append(name)
                return ret
            return _fn
        return {
            "src.auto_pipeline.normalize_all": make("normalize", []),
            "src.auto_pipeline.split_all": make("split", []),
            "src.auto_pipeline.extract_all": make("extract", []),
            "src.auto_pipeline.compress_all": make("compress", []),
            "src.auto_pipeline.bootstrap_all": make("bootstrap", {}),
            "src.auto_pipeline.run_debate": make("debate", {}),
            "src.auto_pipeline.generate_chapter_plan": make("plan", {}),
            "src.auto_pipeline.write_chapters": make("write", []),
        }

    def test_over_budget_after_extract_stops_before_compress(self) -> None:
        calls: list = []
        patches = [patch(target, fn) for target, fn in self._trackers(calls).items()]
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])
        with patch("src.book_runner._llm_log_line_count", return_value=0), \
                patch(
                    "src.cost_estimator.estimate_cost_since",
                    return_value={"cost_cny": 99.0},
                ):
            with self.assertRaises(BudgetExceeded):
                auto_pipeline.run_auto_pipeline(budget_cny=1.0)
        self.assertIn("extract", calls)
        self.assertNotIn("compress", calls)
        self.assertNotIn("debate", calls)
        self.assertNotIn("write", calls)

    def test_uncapped_runs_all_steps_without_cost_calls(self) -> None:
        calls: list = []
        patches = [patch(target, fn) for target, fn in self._trackers(calls).items()]
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])
        with patch("src.cost_estimator.estimate_cost_since") as est:
            auto_pipeline.run_auto_pipeline(budget_cny=0.0)
        # budget_cny<=0 → no settlement at all (legacy path byte-identical).
        est.assert_not_called()
        self.assertEqual(
            calls,
            ["normalize", "split", "extract", "compress", "bootstrap", "debate", "plan", "write"],
        )

    def test_under_budget_runs_to_completion(self) -> None:
        calls: list = []
        patches = [patch(target, fn) for target, fn in self._trackers(calls).items()]
        for p in patches:
            p.start()
        self.addCleanup(lambda: [p.stop() for p in patches])
        with patch("src.book_runner._llm_log_line_count", return_value=0), \
                patch(
                    "src.cost_estimator.estimate_cost_since",
                    return_value={"cost_cny": 0.01},
                ):
            result = auto_pipeline.run_auto_pipeline(budget_cny=100.0)
        self.assertEqual(calls[-1], "write")
        self.assertIn("write", result)


if __name__ == "__main__":
    unittest.main()
