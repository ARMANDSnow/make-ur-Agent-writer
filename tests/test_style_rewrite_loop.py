from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from typing import Any
from unittest.mock import patch

from src import style_drift
from src.utils import write_json
from src.writer import write_chapters


def _agent_config(*, polish: bool = False) -> dict[str, Any]:
    return {
        "max_review_attempts": 1,
        "polish_pass": polish,
        "review_during_lint_block": True,
        "segmented_write": False,
        "continuation_anchor": "",
    }


def _style_config(*, enabled: bool = True) -> dict[str, Any]:
    return {
        "fingerprint_version": "local-stat-v2",
        "language": "zh",
        "style_drift_rewrite": {
            "enabled": enabled,
            "trigger_severity": "red",
            "max_style_rewrites": 1,
            "min_improvement": 0.08,
        },
    }


def _analysis(score: float | None, severity: str, *, current: float = 20.0) -> dict[str, Any]:
    drift = {
        "status": "ok" if score is not None else "skipped",
        "schema_version": 1,
        "severity": severity,
        "style_drift_score": score,
        "top_dimensions": [
            {
                "dimension": "avg_sentence_length",
                "current_value": current,
                "baseline_value": 10.0,
                "tolerance": 2.0,
                "normalized_delta": 3.0,
                "dimension_score": 1.0,
                "weight": 1.0,
                "weighted_delta": 1.0,
            }
        ],
        "skipped_dimensions": [],
        "basis": {"status": "ok", "baseline_hash": "baseline-v2"},
    }
    return {
        "style_fingerprint": {
            "status": "ok",
            "schema_version": 1,
            "fingerprint_version": "local-stat-v2",
            "chapter": 1,
            "metrics": {"avg_sentence_length": current},
        },
        "style_drift": drift,
        "baseline_hash": "baseline-v2",
    }


class StyleRewriteLoopTests(unittest.TestCase):
    def _run(
        self,
        *,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        candidate: str = "候选稿。",
        candidate_lint: list[dict[str, Any]] | None = None,
        candidate_verdict: str = "Approve",
        enabled: bool = True,
        rewrite_error: Exception | None = None,
        review_error: Exception | None = None,
        baseline_error: Exception | None = None,
        candidate_analysis_error: Exception | None = None,
        candidate_lint_error: Exception | None = None,
        polish: bool = False,
        budget_fail_at: int | None = None,
        allow_budget_error: bool = False,
    ) -> tuple[Path, dict[str, Any], list[dict[str, Any]], int]:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        drafts = root / "outputs" / "drafts"
        reviews = root / "outputs" / "reviews"
        drafts.mkdir(parents=True)
        reviews.mkdir(parents=True)
        outline = root / "outline.md"
        outline.write_text("# outline", encoding="utf-8")
        kb = root / "knowledge.md"
        kb.write_text("# knowledge", encoding="utf-8")
        index = root / "index.json"
        index.write_text("{}", encoding="utf-8")

        before = before or _analysis(0.70, "red", current=24.0)
        after = after or _analysis(0.40, "warn", current=14.0)
        analysis_values = [before, after]
        analyze_calls = 0
        review_calls: list[dict[str, Any]] = []
        budget_checks = 0

        original_report = {
            "target": "chapter_01.md",
            "verdict": "Approve",
            "lint_issues": [],
            "agent_reviews": [],
            "rewrite_suggestions": [],
        }
        candidate_report = {
            "target": "chapter_01.md",
            "verdict": candidate_verdict,
            "lint_issues": [],
            "agent_reviews": [],
            "rewrite_suggestions": [],
        }

        def fake_review(_text: str, target_name: str, **kwargs: Any) -> dict[str, Any]:
            if review_calls and review_error is not None:
                raise review_error
            report = dict(original_report if not review_calls else candidate_report)
            report["draft_sha256"] = kwargs.get("draft_sha256", "")
            review_calls.append(dict(kwargs))
            if kwargs.get("persist", True):
                write_json(reviews / f"{Path(target_name).stem}.review.json", report)
            return report

        complete_calls = 0

        def fake_complete(*_args: Any, **_kwargs: Any) -> str:
            nonlocal complete_calls
            complete_calls += 1
            if complete_calls == 1:
                return "原批准稿。"
            if rewrite_error is not None:
                raise rewrite_error
            return candidate

        def fake_budget() -> None:
            nonlocal budget_checks
            budget_checks += 1
            if budget_fail_at is not None and budget_checks == budget_fail_at:
                raise RuntimeError("budget stop")

        def fake_analyze(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
            nonlocal analyze_calls
            analyze_calls += 1
            if candidate_analysis_error is not None and analyze_calls == 2:
                raise candidate_analysis_error
            if len(analysis_values) > 1:
                return analysis_values.pop(0)
            return analysis_values[0]

        with ExitStack() as stack:
            patches = [
                patch("src.writer.DRAFTS_DIR", drafts),
                patch("src.writer.OUTLINE_PATH", outline),
                patch("src.writer.KB_PATH", kb),
                patch("src.writer.INDEX_PATH", index),
                patch("src.writer.paths.reviews_dir", return_value=reviews),
                patch("src.writer.load_config", return_value=_agent_config(polish=polish)),
                patch("src.writer.style_fingerprint.load_style_fingerprint_config", return_value=_style_config(enabled=enabled)),
                patch(
                    "src.writer.style_drift.load_baseline",
                    side_effect=baseline_error,
                    return_value={"status": "ok"},
                ),
                patch("src.writer.style_drift.analyze_text", side_effect=fake_analyze),
                patch("src.writer.style_drift.compare_to_baseline", return_value=before["style_drift"]),
                patch("src.writer.review_text", side_effect=fake_review),
                patch("src.writer._complete_write_text", side_effect=fake_complete),
                patch("src.writer._polish_draft", return_value="未复审的润色稿。"),
                patch("src.writer._summarize_chapter", return_value={"summary": "s", "key_events": [], "ending_state": "e"}),
                patch("src.writer._propose_entity_advance", return_value=[]),
                patch("src.writer.save_entity_advance_proposals", return_value=root / "proposal.json"),
                patch("src.writer.load_entity_graph", return_value={}),
                patch("src.writer.load_style_examples", return_value=""),
                patch("src.writer.global_facts_summary", return_value=""),
                patch("src.writer.load_continuation_anchor", return_value=""),
                patch("src.writer.start_safe_knowledge", return_value="# knowledge"),
                patch("src.writer._load_chapter_plan", return_value=None),
            ]
            for item in patches:
                stack.enter_context(item)
            linter_cls = stack.enter_context(patch("src.writer.NovelLinter"))
            linter_cls.return_value.lint.side_effect = [
                [],
                *([[]] if polish else []),  # Polished text receives its own lint pass.
                candidate_lint_error if candidate_lint_error is not None else list(candidate_lint or []),
            ]
            try:
                write_chapters(
                    chapters=1,
                    force=True,
                    max_attempts=1,
                    budget_check_cb=fake_budget,
                )
            except RuntimeError:
                if not allow_budget_error:
                    raise

        result_path = drafts / (
            "chapter_01.meta.json" if (drafts / "chapter_01.meta.json").exists() else "chapter_01.failure.json"
        )
        meta = json.loads(result_path.read_text(encoding="utf-8"))
        return root, meta, review_calls, complete_calls

    def test_improved_approved_candidate_is_adopted_and_resolved(self) -> None:
        root, meta, review_calls, complete_calls = self._run()
        self.assertEqual((root / "outputs/drafts/chapter_01.md").read_text(encoding="utf-8"), "候选稿。\n")
        self.assertEqual(complete_calls, 2)
        self.assertEqual(len(review_calls), 2)
        self.assertFalse(review_calls[1]["persist"])
        self.assertEqual(meta["rewrite_count"], 0)
        self.assertEqual(meta["style_rewrite_count"], 1)
        self.assertTrue(meta["style_rewrite_applied"])
        self.assertEqual(meta["style_rewrite_status"], "accepted")
        self.assertAlmostEqual(meta["style_drift_improvement"], 0.3)
        self.assertFalse(meta["style_drift_unresolved"])
        self.assertEqual(meta["style_drift"]["style_drift_score"], 0.4)
        review = json.loads((root / "outputs/reviews/chapter_01.review.json").read_text(encoding="utf-8"))
        self.assertEqual(review["draft_sha256"], meta["draft_sha256"])

    def test_improved_candidate_can_be_adopted_but_remain_unresolved(self) -> None:
        _root, meta, _review_calls, _complete_calls = self._run(
            after=_analysis(0.66, "red", current=22.0)
        )
        self.assertTrue(meta["style_rewrite_applied"])
        self.assertAlmostEqual(meta["style_drift_improvement"], 0.04)
        self.assertTrue(meta["style_drift_unresolved"])

    def test_non_improving_candidate_reverts_without_candidate_panel(self) -> None:
        root, meta, review_calls, _complete_calls = self._run(
            after=_analysis(0.75, "red", current=26.0)
        )
        self.assertEqual((root / "outputs/drafts/chapter_01.md").read_text(encoding="utf-8"), "原批准稿。\n")
        self.assertEqual(len(review_calls), 1)
        self.assertEqual(meta["style_rewrite_status"], "reverted_not_improved")
        self.assertFalse(meta["style_rewrite_applied"])
        self.assertTrue(meta["style_drift_unresolved"])
        self.assertEqual(meta["style_drift"]["style_drift_score"], 0.7)

    def test_lint_or_panel_rejection_reverts_and_preserves_original_review(self) -> None:
        error = {"severity": "error", "rule": "synthetic", "message": "bad"}
        for kwargs, expected, calls in (
            ({"candidate_lint": [error]}, "reverted_lint", 1),
            ({"candidate_verdict": "Reject"}, "reverted_review", 2),
        ):
            with self.subTest(expected=expected):
                root, meta, review_calls, _complete_calls = self._run(**kwargs)
                self.assertEqual(meta["style_rewrite_status"], expected)
                self.assertFalse(meta["style_rewrite_applied"])
                self.assertEqual(len(review_calls), calls)
                review = json.loads((root / "outputs/reviews/chapter_01.review.json").read_text(encoding="utf-8"))
                self.assertEqual(review["verdict"], "Approve")

    def test_empty_and_rewrite_error_fail_open_to_original(self) -> None:
        for kwargs, expected in (
            ({"candidate": ""}, "reverted_empty"),
            ({"rewrite_error": RuntimeError("model failed")}, "rewrite_error"),
        ):
            with self.subTest(expected=expected):
                root, meta, review_calls, complete_calls = self._run(**kwargs)
                self.assertEqual(complete_calls, 2)
                self.assertEqual(len(review_calls), 1)
                self.assertEqual(meta["style_rewrite_status"], expected)
                self.assertEqual((root / "outputs/drafts/chapter_01.md").read_text(encoding="utf-8"), "原批准稿。\n")

    def test_candidate_analysis_linter_or_review_exception_reverts(self) -> None:
        for kwargs, expected in (
            ({"candidate_analysis_error": RuntimeError("analysis")}, "reverted_analysis_error"),
            ({"candidate_lint_error": RuntimeError("lint")}, "reverted_analysis_error"),
            ({"review_error": RuntimeError("review")}, "reverted_review_error"),
        ):
            with self.subTest(expected=expected, kwargs=sorted(kwargs)):
                root, meta, _review_calls, _complete_calls = self._run(**kwargs)
                self.assertEqual(meta["style_rewrite_status"], expected)
                self.assertFalse(meta["style_rewrite_applied"])
                self.assertEqual((root / "outputs/drafts/chapter_01.md").read_text(encoding="utf-8"), "原批准稿。\n")

    def test_prepare_analysis_failure_skips_optional_gate(self) -> None:
        _root, meta, review_calls, complete_calls = self._run(
            baseline_error=RuntimeError("baseline read")
        )
        self.assertEqual(complete_calls, 1)
        self.assertEqual(len(review_calls), 1)
        self.assertNotIn("style_rewrite_count", meta)

    def test_failed_style_candidate_after_polish_reverts_to_actually_approved_draft(self) -> None:
        root, meta, review_calls, _complete_calls = self._run(
            polish=True,
            candidate_verdict="Reject",
        )
        on_disk = (root / "outputs/drafts/chapter_01.md").read_text(encoding="utf-8")
        self.assertEqual(on_disk, "原批准稿。\n")
        self.assertFalse(meta["polish_applied"])
        review = json.loads((root / "outputs/reviews/chapter_01.review.json").read_text(encoding="utf-8"))
        self.assertEqual(review["draft_sha256"], meta["draft_sha256"])
        self.assertEqual(len(review_calls), 2)

    def test_warn_or_disabled_policy_makes_no_extra_model_call(self) -> None:
        skipped = _analysis(None, "skipped")
        skipped["style_drift"]["status"] = "skipped"
        skipped["style_drift"]["reason"] = "baseline_missing"
        for before, after, enabled in (
            (_analysis(0.4, "warn"), _analysis(0.4, "warn"), True),
            (_analysis(0.7, "red"), _analysis(0.7, "red"), False),
            (skipped, skipped, True),
        ):
            with self.subTest(severity=before["style_drift"]["severity"], enabled=enabled):
                _root, meta, review_calls, complete_calls = self._run(before=before, after=after, enabled=enabled)
                self.assertEqual(complete_calls, 1)
                self.assertEqual(len(review_calls), 1)
                self.assertNotIn("style_rewrite_count", meta)

    def test_budget_guard_runs_before_and_after_style_model_call(self) -> None:
        _root, failure, review_calls, complete_calls = self._run(
            budget_fail_at=3,
            allow_budget_error=True,
        )
        self.assertEqual(complete_calls, 1)
        self.assertEqual(len(review_calls), 1)
        self.assertEqual(failure["stage"], "budget_check_style_rewrite_pre")

        _root, failure, review_calls, complete_calls = self._run(
            budget_fail_at=4,
            allow_budget_error=True,
        )
        self.assertEqual(complete_calls, 2)
        self.assertEqual(len(review_calls), 1)
        self.assertEqual(failure["stage"], "budget_check_style_rewrite_post")

    def test_budget_guard_runs_before_and_after_candidate_panel(self) -> None:
        _root, failure, review_calls, complete_calls = self._run(
            budget_fail_at=5,
            allow_budget_error=True,
        )
        self.assertEqual(complete_calls, 2)
        self.assertEqual(len(review_calls), 1)
        self.assertEqual(failure["stage"], "budget_check_style_review_pre")

        _root, failure, review_calls, complete_calls = self._run(
            budget_fail_at=6,
            allow_budget_error=True,
        )
        self.assertEqual(complete_calls, 2)
        self.assertEqual(len(review_calls), 2)
        self.assertEqual(failure["stage"], "budget_check_style_review_post")


class StyleRewritePolicyTests(unittest.TestCase):
    def test_policy_accepts_only_bounded_finite_red_contract(self) -> None:
        policy, warnings = style_drift.parse_rewrite_policy(_style_config())
        self.assertEqual(warnings, [])
        self.assertTrue(policy["enabled"])
        invalid_values = [True, -1, 2, 1.5, float("nan"), float("inf")]
        for value in invalid_values:
            cfg = _style_config()
            cfg["style_drift_rewrite"]["max_style_rewrites"] = value
            parsed, warnings = style_drift.parse_rewrite_policy(cfg)
            self.assertFalse(parsed["enabled"])
            self.assertTrue(warnings)

    def test_missing_or_invalid_min_improvement_disables(self) -> None:
        policy, warnings = style_drift.parse_rewrite_policy({})
        self.assertFalse(policy["enabled"])
        self.assertTrue(warnings)
        for value in (True, "0.08", -0.1, 1.1, float("nan"), float("inf")):
            cfg = _style_config()
            cfg["style_drift_rewrite"]["min_improvement"] = value
            parsed, warnings = style_drift.parse_rewrite_policy(cfg)
            self.assertFalse(parsed["enabled"])
            self.assertTrue(warnings)


if __name__ == "__main__":
    unittest.main()
