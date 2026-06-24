"""iter068 — rebuild-for-start Web job, prepare/rebuild budget (incl. the
fail-open guard), per-step progress sub-callbacks, and the new readiness kinds.

Mock-only. Cost is simulated by patching estimate_cost_since (mock cost ~0).
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import patch

from src import auto_bootstrap, readiness_catalog
from src.book_runner import BudgetExceeded
from src.extractor import ExtractionBatchFailure
from src.web import errors, jobs, routes


def _noop(*_a, **_k) -> None:
    return None


class RebuildForStartStepTests(unittest.TestCase):
    """jobs._step_rebuild_for_start: registration, start-point pre-check,
    budget wiring, and error mapping."""

    def test_registered_in_whitelist(self) -> None:
        self.assertIn("rebuild-for-start", jobs.STEP_HANDLERS)
        self.assertTrue(jobs.is_known_step("rebuild-for-start"))

    def test_no_start_point_blocks_without_running(self) -> None:
        with patch("src.web.jobs.start_point.get_start_chapter_id", return_value=None), \
                patch("src.web.jobs.auto_pipeline.rebuild_for_start") as rebuild:
            result = jobs._step_rebuild_for_start({}, _noop)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["blocked"][0]["reason"], "start_point_missing")
        rebuild.assert_not_called()

    def test_default_cap_passes_budget_check(self) -> None:
        with patch("src.web.jobs.start_point.get_start_chapter_id", return_value="v1_ch003"), \
                patch("src.web.jobs._default_budget_cny", return_value=10.0), \
                patch("src.book_runner._llm_log_line_count", return_value=0), \
                patch("src.cost_estimator.estimate_cost_since", return_value={"cost_cny": 0.0}), \
                patch(
                    "src.web.jobs.auto_pipeline.rebuild_for_start",
                    return_value={"start_chapter_id": "v1_ch003", "window_chapter_ids": ["a"], "steps": {}},
                ) as rebuild:
            jobs._step_rebuild_for_start({}, _noop)
        # omitted budget must inherit the default cap → a live budget_check.
        self.assertIsNotNone(rebuild.call_args.kwargs["budget_check"])

    def test_explicit_zero_is_uncapped(self) -> None:
        with patch("src.web.jobs.start_point.get_start_chapter_id", return_value="v1_ch003"), \
                patch("src.book_runner._llm_log_line_count", return_value=0), \
                patch("src.cost_estimator.estimate_cost_since", return_value={"cost_cny": 0.0}), \
                patch(
                    "src.web.jobs.auto_pipeline.rebuild_for_start",
                    return_value={"start_chapter_id": "v1_ch003", "window_chapter_ids": ["a"], "steps": {}},
                ) as rebuild:
            jobs._step_rebuild_for_start({"budget_cny": 0}, _noop)
        # explicit 0 = uncapped (CLI semantics) → no budget_check.
        self.assertIsNone(rebuild.call_args.kwargs["budget_check"])

    def test_budget_exceeded_maps_to_terminal(self) -> None:
        with patch("src.web.jobs.start_point.get_start_chapter_id", return_value="v1_ch003"), \
                patch("src.book_runner._llm_log_line_count", return_value=0), \
                patch("src.cost_estimator.estimate_cost_since", return_value={"cost_cny": 0.0}), \
                patch(
                    "src.web.jobs.auto_pipeline.rebuild_for_start",
                    side_effect=BudgetExceeded(budget_cny=3.0, cost_cny=4.2),
                ):
            result = jobs._step_rebuild_for_start({"budget_cny": 3.0}, _noop)
        self.assertEqual(result["status"], "budget_exceeded")
        self.assertEqual(result["cost_cny"], 4.2)
        self.assertEqual(result["budget_cny"], 3.0)

    def test_extraction_failure_blocks(self) -> None:
        with patch("src.web.jobs.start_point.get_start_chapter_id", return_value="v1_ch003"), \
                patch("src.book_runner._llm_log_line_count", return_value=0), \
                patch("src.cost_estimator.estimate_cost_since", return_value={"cost_cny": 0.0}), \
                patch(
                    "src.web.jobs.auto_pipeline.rebuild_for_start",
                    side_effect=ExtractionBatchFailure(["v1_ch002"], 0),
                ):
            result = jobs._step_rebuild_for_start({}, _noop)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["blocked"][0]["reason"], "extraction_failures")

    def test_real_valueerror_not_mislabeled_start_point_missing(self) -> None:
        # A genuine apply/bootstrap ValueError must propagate as failed, NOT be
        # swallowed and mislabeled start_point_missing (we pre-check instead of
        # blanket-catching ValueError).
        with patch("src.web.jobs.start_point.get_start_chapter_id", return_value="v1_ch003"), \
                patch("src.book_runner._llm_log_line_count", return_value=0), \
                patch("src.cost_estimator.estimate_cost_since", return_value={"cost_cny": 0.0}), \
                patch(
                    "src.web.jobs.auto_pipeline.rebuild_for_start",
                    side_effect=ValueError("apply_bootstrap exploded"),
                ):
            with self.assertRaises(ValueError):
                jobs._step_rebuild_for_start({}, _noop)

    def test_success_summary_surfaces_cost_and_window(self) -> None:
        summary = jobs._summarize_result(
            "rebuild-for-start",
            {
                "status": "succeeded",
                "cost_cny": 0.0,
                "budget_cny": 10.0,
                "start_chapter_id": "v1_ch003",
                "window_chapter_ids": ["a", "b", "c"],
                "steps": {"apply_entity_graph": {}, "apply_anchor": {}},
            },
        )
        self.assertEqual(summary["status"], "succeeded")
        self.assertEqual(summary["window"], 3)
        self.assertTrue(summary["applied"])
        self.assertEqual(summary["start_chapter_id"], "v1_ch003")


class PrepareGreenfieldBudgetTests(unittest.TestCase):
    """jobs._step_prepare_greenfield: the prepare step now wires budget_check —
    omitted budget must inherit the default cap (NOT run uncapped)."""

    def test_omitted_budget_inherits_default_cap(self) -> None:
        with patch("src.web.jobs._default_budget_cny", return_value=10.0), \
                patch("src.book_runner._llm_log_line_count", return_value=0), \
                patch("src.cost_estimator.estimate_cost_since", return_value={"cost_cny": 0.0}), \
                patch("src.web.jobs.auto_pipeline._run_prepare_steps", return_value={}) as run:
            jobs._step_prepare_greenfield({}, _noop)
        self.assertIsNotNone(run.call_args.kwargs["budget_check"])

    def test_explicit_zero_is_uncapped(self) -> None:
        with patch("src.web.jobs.auto_pipeline._run_prepare_steps", return_value={}) as run:
            jobs._step_prepare_greenfield({"budget_cny": 0}, _noop)
        self.assertIsNone(run.call_args.kwargs["budget_check"])

    def test_budget_exceeded_maps_to_terminal(self) -> None:
        with patch("src.web.jobs._default_budget_cny", return_value=10.0), \
                patch("src.book_runner._llm_log_line_count", return_value=0), \
                patch("src.cost_estimator.estimate_cost_since", return_value={"cost_cny": 0.0}), \
                patch(
                    "src.web.jobs.auto_pipeline._run_prepare_steps",
                    side_effect=BudgetExceeded(budget_cny=10.0, cost_cny=11.1),
                ):
            result = jobs._step_prepare_greenfield({}, _noop)
        self.assertEqual(result["status"], "budget_exceeded")
        self.assertEqual(result["cost_cny"], 11.1)


class ValidatePrepareParamsTests(unittest.TestCase):
    """routes._validate_prepare_params: the fail-open guard — omitted budget must
    NOT be normalized to budget_cny:0 (which jobs would treat as uncapped)."""

    def test_omitted_budget_field_absent(self) -> None:
        err, out = routes._validate_prepare_params("prepare-greenfield", {})
        self.assertIsNone(err)
        self.assertNotIn("budget_cny", out)

    def test_explicit_zero_kept(self) -> None:
        err, out = routes._validate_prepare_params("prepare-greenfield", {"budget_cny": 0})
        self.assertIsNone(err)
        self.assertEqual(out["budget_cny"], 0.0)

    def test_explicit_value_validated(self) -> None:
        err, out = routes._validate_prepare_params("rebuild-for-start", {"budget_cny": 2.5})
        self.assertIsNone(err)
        self.assertEqual(out["budget_cny"], 2.5)

    def test_window_validated_for_rebuild(self) -> None:
        err, out = routes._validate_prepare_params("rebuild-for-start", {"window": 20})
        self.assertIsNone(err)
        self.assertEqual(out["window"], 20)

    def test_bad_budget_rejected(self) -> None:
        err, _ = routes._validate_prepare_params("prepare-greenfield", {"budget_cny": "nope"})
        self.assertIsNotNone(err)

    def test_validated_run_params_routes_prepare(self) -> None:
        err, out = routes._validated_run_params("rebuild-for-start", {"window": 8})
        self.assertIsNone(err)
        self.assertEqual(out["window"], 8)


class BootstrapAllProgressTests(unittest.TestCase):
    """bootstrap_all: a progress checkpoint per proposal, fixed key order."""

    EXPECTED = [
        "global_facts",
        "entity_graph",
        "continuation_anchor",
        "style_examples",
        "personas",
        "source_excerpts",
    ]

    def test_step_order_is_pinned(self) -> None:
        names = [n for n, _ in auto_bootstrap._BOOTSTRAP_STEPS]
        self.assertEqual(names, self.EXPECTED)

    def test_progress_fires_per_proposal_and_keeps_key_order(self) -> None:
        seen: list = []
        targets = {
            "global_facts": "bootstrap_global_facts",
            "entity_graph": "bootstrap_entity_graph",
            "continuation_anchor": "bootstrap_continuation_anchor",
            "style_examples": "bootstrap_style_examples",
            "personas": "bootstrap_personas",
            "source_excerpts": "bootstrap_source_excerpts",
        }
        with patch("src.auto_bootstrap._resolve_root", return_value=Path(".")):
            stack = []
            for name, attr in targets.items():
                p = patch(f"src.auto_bootstrap.{attr}", return_value={"name": name})
                p.start()
                stack.append(p)
            try:
                out = auto_bootstrap.bootstrap_all(progress_cb=lambda label, frac: seen.append(label))
            finally:
                for p in stack:
                    p.stop()
        self.assertEqual(list(out.keys()), self.EXPECTED)
        self.assertEqual(seen, [f"bootstrap:{n}" for n in self.EXPECTED])


class PlanChaptersCoverageMappingTests(unittest.TestCase):
    """_step_plan_chapters maps the planner's start-window coverage gap to a
    structured extraction_coverage_missing card (not a generic failed job)."""

    def test_coverage_gap_blocks(self) -> None:
        with patch("src.web.jobs.start_point.get_start_chapter_id", return_value="v1_ch003"), \
                patch(
                    "src.web.jobs.generate_chapter_plan",
                    side_effect=ValueError(
                        "extraction coverage gap before start point: v1_ch001; run rebuild-for-start"
                    ),
                ):
            result = jobs._step_plan_chapters({"require_start_point": True}, _noop)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["blocked"][0]["reason"], "extraction_coverage_missing")


class ReadinessKindsTests(unittest.TestCase):
    """The new readiness kinds classify and render proper cards."""

    def test_new_kinds_present(self) -> None:
        for kind in ("kb_missing", "extraction_coverage_missing"):
            self.assertIn(kind, readiness_catalog.KINDS)
            self.assertTrue(readiness_catalog.fields_for(kind)["cta_action"])

    def test_classify_extraction_coverage(self) -> None:
        self.assertEqual(
            readiness_catalog.classify("extraction:start_window_unextracted:v1_ch001"),
            "extraction_coverage_missing",
        )
        self.assertEqual(
            readiness_catalog.classify("extraction coverage gap before start point: v1_ch001"),
            "extraction_coverage_missing",
        )

    def test_classify_kb_missing(self) -> None:
        self.assertEqual(readiness_catalog.classify("kb_missing"), "kb_missing")

    def test_outline_missing_cta_points_at_debate(self) -> None:
        self.assertEqual(readiness_catalog.fields_for("outline_missing")["cta_action"], "run_debate")

    def test_errors_card_for_extraction_coverage(self) -> None:
        card = errors.readiness_card("extraction:start_window_unextracted:v1_ch001")
        self.assertEqual(card["actions"][0]["action"], "run_rebuild_for_start")


if __name__ == "__main__":
    unittest.main()
