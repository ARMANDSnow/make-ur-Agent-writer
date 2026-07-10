from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import main
from src import style_drift, style_fingerprint


def _baseline(metrics: dict[str, float | int] | None = None) -> dict:
    base_metrics = metrics or {
        key: 0.1 for key in style_fingerprint.METRIC_KEYS
    }
    base_metrics.update(
        {
            "char_count": 1000,
            "chinese_char_count": 900,
            "sentence_count": 30,
            "paragraph_count": 8,
            "avg_sentence_length": 20.0,
            "sentence_p50": 18.0,
            "sentence_p90": 35.0,
            "short_sentence_ratio": 0.2,
            "long_sentence_ratio": 0.1,
            "avg_paragraph_chars": 120.0,
            "dialogue_line_ratio": 0.3,
            "quote_span_ratio": 0.2,
            "punctuation_density": 0.16,
            "question_exclaim_density": 0.02,
            "ellipsis_density": 0.01,
            "contrast_sentence_density": 0.05,
            "ai_cliche_density": 0.001,
            "sensory_imagery_density": 0.02,
            "exposition_connector_density": 0.01,
        }
    )
    return {
        "status": "ok",
        "schema_version": 1,
        "fingerprint_version": "local-stat-v1",
        "language": "zh",
        "baseline_hash": "baseline-test-hash",
        "sample_count": 2,
        "metrics": base_metrics,
        "tolerance": {key: 1.0 for key in style_fingerprint.DRIFT_METRIC_KEYS},
        "weights": {key: 1.0 for key in style_fingerprint.DRIFT_METRIC_KEYS},
        "dimension_reliability": {
            key: {"level": "medium", "confidence": 0.65}
            for key in style_fingerprint.DRIFT_METRIC_KEYS
        },
        "baseline_quality": {"status": "ok", "confidence": 0.65, "sample_count": 2},
    }


class StyleDriftTests(unittest.TestCase):
    def test_similar_synthetic_draft_is_ok(self) -> None:
        baseline = _baseline()
        report = style_drift.compare_to_baseline(dict(baseline["metrics"]), baseline)

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["severity"], "ok")
        self.assertEqual(report["style_drift_score"], 0.0)
        self.assertEqual(report["basis"]["baseline_hash"], "baseline-test-hash")

    def test_exposition_long_sentence_draft_is_red(self) -> None:
        baseline = _baseline()
        current = dict(baseline["metrics"])
        for key in style_fingerprint.DRIFT_METRIC_KEYS:
            current[key] = float(current[key]) + 100.0

        report = style_drift.compare_to_baseline(current, baseline)

        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["severity"], "red")
        self.assertGreaterEqual(report["style_drift_score"], 0.55)
        self.assertEqual(report["top_dimensions"][0]["normalized_delta"], 3.0)

    def test_missing_or_insufficient_baseline_skips_without_zero_score(self) -> None:
        metrics = dict(_baseline()["metrics"])

        empty = style_drift.compare_to_baseline(metrics, {})
        missing = style_drift.compare_to_baseline(metrics, {"status": "missing"})
        insufficient = style_drift.compare_to_baseline(metrics, {"status": "insufficient_source"})

        self.assertEqual(empty["reason"], "baseline_missing")
        self.assertEqual(missing["status"], "skipped")
        self.assertEqual(missing["severity"], "skipped")
        self.assertIsNone(missing["style_drift_score"])
        self.assertEqual(missing["reason"], "baseline_missing")
        self.assertEqual(insufficient["reason"], "baseline_insufficient_source")

    def test_corrupt_baseline_sample_count_does_not_crash(self) -> None:
        metrics = dict(_baseline()["metrics"])
        baseline = {
            "status": "insufficient_source",
            "sample_count": float("inf"),
            "baseline_quality": {"sample_count": "also-bad", "confidence": "nan"},
        }

        report = style_drift.compare_to_baseline(metrics, baseline)

        self.assertEqual(report["status"], "skipped")
        self.assertEqual(report["basis"]["sample_count"], 0)
        self.assertIsNone(report["basis"]["baseline_quality_confidence"])

    def test_missing_and_low_reliability_dimensions_are_skipped(self) -> None:
        baseline = _baseline()
        baseline["tolerance"].pop("sentence_p50")
        baseline["dimension_reliability"]["sentence_p90"] = {"level": "low", "confidence": 0.45}
        baseline["weights"].pop("long_sentence_ratio")

        report = style_drift.compare_to_baseline(dict(baseline["metrics"]), baseline)

        skipped = {item["dimension"]: item["reason"] for item in report["skipped_dimensions"]}
        self.assertEqual(report["status"], "ok")
        self.assertEqual(skipped["sentence_p50"], "tolerance_missing_or_nonpositive")
        self.assertEqual(skipped["sentence_p90"], "low_reliability")
        self.assertEqual(skipped["long_sentence_ratio"], "weight_missing_or_nonpositive")

    def test_analyze_chapter_merges_existing_meta_without_source_text(self) -> None:
        draft_text = "冷光落在玻璃上。少年停了一下，听见雨声从窗外压过来。" * 12
        metrics = style_fingerprint.calculate_metrics(draft_text)
        baseline = _baseline(metrics)
        forbidden_fragment = draft_text[:30]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            drafts = root / "outputs" / "drafts"
            drafts.mkdir(parents=True)
            baseline_path = root / "data" / "style_fingerprint" / "baseline.json"
            baseline_path.parent.mkdir(parents=True)
            baseline_path.write_text(json.dumps(baseline, ensure_ascii=False), encoding="utf-8")
            (drafts / "chapter_01.md").write_text(draft_text, encoding="utf-8")
            (drafts / "chapter_01.meta.json").write_text(
                json.dumps(
                    {
                        "verdict": "Approve",
                        "needs_human_review": False,
                        "rewrite_count": 2,
                        "draft_sha256": "draft-hash",
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = style_drift.analyze_chapter(1, drafts_dir=drafts, baseline_path=baseline_path)
            meta = json.loads((drafts / "chapter_01.meta.json").read_text(encoding="utf-8"))
            meta_json = json.dumps(meta, ensure_ascii=False)

        self.assertTrue(result["meta_written"])
        self.assertEqual(meta["verdict"], "Approve")
        self.assertFalse(meta["needs_human_review"])
        self.assertEqual(meta["rewrite_count"], 2)
        self.assertEqual(meta["draft_sha256"], "draft-hash")
        self.assertEqual(meta["style_fingerprint"]["status"], "ok")
        self.assertEqual(meta["style_drift"]["severity"], "ok")
        self.assertEqual(meta["baseline_hash"], "baseline-test-hash")
        self.assertNotIn(forbidden_fragment, meta_json)

    def test_analyze_chapter_does_not_create_half_meta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            drafts = Path(tmp) / "outputs" / "drafts"
            drafts.mkdir(parents=True)
            (drafts / "chapter_02.md").write_text("风停了。", encoding="utf-8")

            result = style_drift.analyze_chapter(2, drafts_dir=drafts, baseline_path=Path(tmp) / "missing.json")

            self.assertFalse(result["meta_written"])
            self.assertEqual(result["status"], "skipped")
            self.assertEqual(result["style_drift"]["reason"], "baseline_missing")
            self.assertFalse((drafts / "chapter_02.meta.json").exists())

    def test_skipped_reanalysis_clears_stale_baseline_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            drafts = Path(tmp) / "outputs" / "drafts"
            drafts.mkdir(parents=True)
            (drafts / "chapter_03.md").write_text("风停了。", encoding="utf-8")
            (drafts / "chapter_03.meta.json").write_text(
                json.dumps(
                    {
                        "verdict": "Approve",
                        "baseline_hash": "old-hash",
                        "style_drift": {"status": "ok", "basis": {"baseline_hash": "old-hash"}},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            result = style_drift.analyze_chapter(3, drafts_dir=drafts, baseline_path=Path(tmp) / "missing.json")
            meta = json.loads((drafts / "chapter_03.meta.json").read_text(encoding="utf-8"))
            report = style_drift.style_drift_report(limit=1, drafts_dir=drafts)

        self.assertTrue(result["meta_written"])
        self.assertEqual(meta["style_drift"]["status"], "skipped")
        self.assertNotIn("baseline_hash", meta)
        self.assertEqual(report["chapters"][0]["baseline_hash"], "")

    def test_report_uses_latest_chapters_not_earliest_window(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            drafts = Path(tmp) / "outputs" / "drafts"
            drafts.mkdir(parents=True)
            for chapter in range(1, 13):
                (drafts / f"chapter_{chapter:02d}.meta.json").write_text(
                    json.dumps(
                        {
                            "style_drift": {
                                "status": "ok",
                                "severity": "warn" if chapter % 2 else "ok",
                                "style_drift_score": 0.4 if chapter % 2 else 0.1,
                                "basis": {"baseline_hash": f"h{chapter}"},
                                "top_dimensions": [],
                            }
                        },
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )

            report = style_drift.style_drift_report(limit=5, drafts_dir=drafts)

        self.assertEqual(report["window_order"], "chapter_no_desc")
        self.assertEqual(report["chapters_considered"], [12, 11, 10, 9, 8])
        self.assertEqual([row["chapter"] for row in report["chapters"]], [12, 11, 10, 9, 8])

    def test_cli_parser_accepts_style_drift_commands(self) -> None:
        parser = main.build_parser()

        drift_args = parser.parse_args(["style-drift", "--chapter", "3"])
        report_args = parser.parse_args(["style-drift-report", "--limit", "7"])

        self.assertEqual(drift_args.command, "style-drift")
        self.assertEqual(drift_args.chapter, 3)
        self.assertEqual(report_args.command, "style-drift-report")
        self.assertEqual(report_args.limit, 7)


if __name__ == "__main__":
    unittest.main()
