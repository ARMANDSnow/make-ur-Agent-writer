from __future__ import annotations

import math
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from src import style_drift
from src.schemas import StyleRewriteDirective, model_to_dict


def _report(*dimensions: dict, severity: str = "red") -> dict:
    return {"status": "ok", "severity": severity, "top_dimensions": list(dimensions)}


def _dimension(
    name: str,
    current: float,
    baseline: float,
    *,
    tolerance: float = 1.0,
    weighted_delta: float = 0.8,
) -> dict:
    return {
        "dimension": name,
        "current_value": current,
        "baseline_value": baseline,
        "tolerance": tolerance,
        "weighted_delta": weighted_delta,
    }


class StyleRewriteDirectiveTests(unittest.TestCase):
    def test_sentence_length_high_and_low_have_opposite_guidance(self) -> None:
        high = style_drift.build_rewrite_directives(
            _report(_dimension("avg_sentence_length", 30, 20, tolerance=2))
        )[0]
        low = style_drift.build_rewrite_directives(
            _report(_dimension("avg_sentence_length", 10, 20, tolerance=2))
        )[0]

        self.assertIn("拆分", high.guidance)
        self.assertIn("合并", low.guidance)
        self.assertEqual(model_to_dict(high)["target_range"], {"min": 18.0, "max": 22.0})
        self.assertEqual(high.target_metric, "avg_sentence_length")

    def test_short_sentence_density_high_maps_to_merge(self) -> None:
        directive = style_drift.build_rewrite_directives(
            _report(_dimension("short_sentence_ratio", 0.8, 0.3, tolerance=0.1))
        )[0]
        self.assertIn("合并", directive.guidance)
        self.assertEqual(directive.section_hint, "短句密集段落")

    def test_dialogue_low_and_high_have_opposite_guidance(self) -> None:
        low = style_drift.build_rewrite_directives(
            _report(_dimension("dialogue_line_ratio", 0.05, 0.3, tolerance=0.05))
        )[0]
        high = style_drift.build_rewrite_directives(
            _report(_dimension("quote_span_ratio", 0.7, 0.3, tolerance=0.05))
        )[0]
        self.assertIn("必要对话", low.guidance)
        self.assertIn("密集对白", high.guidance)

    def test_exposition_contrast_and_ai_density_map_when_high(self) -> None:
        report = _report(
            _dimension("exposition_connector_density", 0.05, 0.01, tolerance=0.005),
            _dimension("contrast_sentence_density", 0.5, 0.1, tolerance=0.05, weighted_delta=0.7),
            _dimension("ai_cliche_density", 0.04, 0.002, tolerance=0.001, weighted_delta=0.6),
        )
        directives = style_drift.build_rewrite_directives(report)
        by_dimension = {item.dimension: item for item in directives}
        self.assertIn("因此", by_dimension["exposition_connector_density"].guidance)
        self.assertIn("对比", by_dimension["contrast_sentence_density"].guidance)
        self.assertIn("AI 腔", by_dimension["ai_cliche_density"].guidance)

    def test_target_range_lower_bound_is_zero(self) -> None:
        directive = style_drift.build_rewrite_directives(
            _report(_dimension("ai_cliche_density", 0.2, 0.01, tolerance=0.05))
        )[0]
        self.assertEqual(model_to_dict(directive)["target_range"], {"min": 0.0, "max": 0.06})

    def test_target_range_overflow_is_skipped(self) -> None:
        report = _report(
            _dimension(
                "avg_sentence_length",
                1e307,
                1e308,
                tolerance=1e308,
            )
        )
        self.assertEqual(style_drift.build_rewrite_directives(report), [])

    def test_schema_rejects_nonfinite_incomplete_and_reversed_ranges(self) -> None:
        base = {
            "dimension": "avg_sentence_length",
            "severity": "red",
            "section_hint": "全文句式节奏",
            "target_metric": "avg_sentence_length",
            "current_value": 30.0,
            "target_range": {"min": 18.0, "max": 22.0},
            "guidance": "拆分长句。",
        }
        for bad in (
            {**base, "current_value": math.nan},
            {**base, "target_range": {"min": 18.0}},
            {**base, "target_range": {"min": 23.0, "max": 22.0}},
            {**base, "target_range": {"min": 0.0, "max": math.inf}},
        ):
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                StyleRewriteDirective(**bad)

    def test_order_is_stable_and_output_is_capped_at_five(self) -> None:
        dimensions = [
            _dimension("avg_sentence_length", 30, 20, weighted_delta=0.5),
            _dimension("short_sentence_ratio", 0.8, 0.3, tolerance=0.05, weighted_delta=0.5),
            _dimension("dialogue_line_ratio", 0.05, 0.3, tolerance=0.05, weighted_delta=0.9),
            _dimension("quote_span_ratio", 0.8, 0.3, tolerance=0.05, weighted_delta=0.8),
            _dimension("exposition_connector_density", 0.1, 0.01, tolerance=0.005, weighted_delta=0.7),
            _dimension("contrast_sentence_density", 0.5, 0.1, tolerance=0.05, weighted_delta=0.6),
            _dimension("ai_cliche_density", 0.05, 0.01, tolerance=0.005, weighted_delta=0.4),
        ]
        first = style_drift.build_rewrite_directives(_report(*reversed(dimensions)))
        second = style_drift.build_rewrite_directives(_report(*dimensions))

        self.assertEqual([item.dimension for item in first], [item.dimension for item in second])
        self.assertEqual(len(first), 5)
        self.assertEqual(first[0].dimension, "dialogue_line_ratio")
        self.assertEqual(first[-1].dimension, "avg_sentence_length")

    def test_transient_advisor_filters_before_top_five_cap(self) -> None:
        from src import style_fingerprint

        baseline_metrics = {key: 0.0 for key in style_fingerprint.DRIFT_METRIC_KEYS}
        current_metrics = dict(baseline_metrics)
        unsupported = (
            "sentence_p50",
            "sentence_p90",
            "long_sentence_ratio",
            "avg_paragraph_chars",
            "punctuation_density",
        )
        weights = {key: 0.1 for key in style_fingerprint.DRIFT_METRIC_KEYS}
        for key in unsupported:
            current_metrics[key] = 3.0
            weights[key] = 10.0
        current_metrics["ai_cliche_density"] = 0.3
        weights["ai_cliche_density"] = 1.0
        baseline = {
            "status": "ok",
            "metrics": baseline_metrics,
            "tolerance": {key: 0.1 for key in style_fingerprint.DRIFT_METRIC_KEYS},
            "weights": weights,
            "dimension_reliability": {
                key: {"level": "medium", "confidence": 0.8}
                for key in style_fingerprint.DRIFT_METRIC_KEYS
            },
        }

        with patch(
            "src.style_drift.fingerprint_text",
            return_value={"status": "ok", "metrics": current_metrics},
        ), patch("src.style_drift.load_baseline", return_value=baseline):
            directives = style_drift.rewrite_directives_for_text("ignored")

        self.assertEqual([item.dimension for item in directives], ["ai_cliche_density"])

    def test_ok_skipped_invalid_and_unsupported_produce_no_directives(self) -> None:
        valid = _dimension("avg_sentence_length", 30, 20)
        self.assertEqual(style_drift.build_rewrite_directives(_report(valid, severity="ok")), [])
        self.assertEqual(
            style_drift.build_rewrite_directives(
                {"status": "skipped", "severity": "red", "top_dimensions": [valid]}
            ),
            [],
        )
        for invalid in (
            {**valid, "current_value": math.inf},
            {**valid, "tolerance": 0},
            {**valid, "weighted_delta": "bad"},
            _dimension("punctuation_density", 0.5, 0.1),
        ):
            with self.subTest(invalid=invalid):
                self.assertEqual(style_drift.build_rewrite_directives(_report(invalid)), [])

    def test_low_one_sided_density_is_not_treated_as_a_problem(self) -> None:
        names = (
            "short_sentence_ratio",
            "exposition_connector_density",
            "contrast_sentence_density",
            "ai_cliche_density",
        )
        for name in names:
            with self.subTest(name=name):
                self.assertEqual(
                    style_drift.build_rewrite_directives(
                        _report(_dimension(name, 0.01, 0.2))
                    ),
                    [],
                )

    def test_values_inside_or_on_target_range_do_not_emit(self) -> None:
        for current in (0.31, 0.26, 0.34):
            with self.subTest(current=current):
                report = _report(
                    _dimension(
                        "dialogue_line_ratio",
                        current,
                        0.30,
                        tolerance=0.04,
                        weighted_delta=0.01,
                    )
                )
                self.assertEqual(style_drift.build_rewrite_directives(report), [])


if __name__ == "__main__":
    unittest.main()
