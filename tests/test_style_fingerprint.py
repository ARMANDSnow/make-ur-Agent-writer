from __future__ import annotations

import json
import math
import tempfile
import unittest
from pathlib import Path

import main
from src import style_fingerprint


class StyleFingerprintTests(unittest.TestCase):
    def test_build_baseline_gracefully_degrades_without_samples(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = root / "data" / "style_fingerprint" / "baseline.json"
            result = style_fingerprint.build_baseline(
                style_examples_dir=root / "data" / "style_examples",
                output_path=out,
            )

            self.assertEqual(result["status"], "insufficient_source")
            self.assertEqual(result["baseline_quality"]["sample_count"], 0)
            self.assertEqual(result["baseline_quality"]["insufficient_reason"], "sample_count<1")
            self.assertEqual(result["metrics"], {})
            self.assertTrue(out.exists())

    def test_synthetic_baseline_is_stable_and_omits_source_text(self) -> None:
        sample_text = (
            "风吹过空教室，灯光落在桌面上。少年停了一下，听见雨声从窗外压过来。"
            "“你真的要走吗？”她问。不是害怕而是迟疑，声音很轻。"
            "于是他把伞放在门边，玻璃上映出一点冷光。\n\n"
        ) * 10
        forbidden_fragment = "风吹过空教室，灯光落在桌面上。少年停了一下"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            examples = root / "data" / "style_examples"
            examples.mkdir(parents=True)
            (examples / "sample_a.md").write_text(sample_text, encoding="utf-8")
            (examples / "sample_b.md").write_text(sample_text.replace("雨声", "脚步声"), encoding="utf-8")
            out = root / "data" / "style_fingerprint" / "baseline.json"

            first = style_fingerprint.build_baseline(style_examples_dir=examples, output_path=out)
            first_json = out.read_text(encoding="utf-8")
            second = style_fingerprint.build_baseline(style_examples_dir=examples, output_path=out)
            second_json = out.read_text(encoding="utf-8")

            self.assertEqual(first["status"], "ok")
            self.assertEqual(first["baseline_hash"], second["baseline_hash"])
            self.assertEqual(first_json, second_json)
            self.assertNotIn(forbidden_fragment, first_json)
            self.assertEqual(first["sample_count"], 2)
            self.assertIn("avg_sentence_length", first["metrics"])
            self.assertIn("sentence_p50", first["metrics"])
            self.assertIn("sentence_p90", first["metrics"])
            self.assertIn("ai_cliche_density", first["metrics"])
            self.assertIn("sensory_imagery_density", first["metrics"])
            self.assertIn("exposition_connector_density", first["metrics"])
            self.assertIn("avg_sentence_length", first["tolerance"])
            self.assertNotIn("source_labels", first)
            self.assertNotIn("source_hashes", first)
            self.assertEqual(first["fingerprint_version"], "local-stat-v2")

    def test_inspect_draft_outputs_same_metric_shape_for_synthetic_draft(self) -> None:
        draft_text = (
            "雨停以后，街灯一盏盏亮起来。她靠在门边，看见水痕沿着台阶往下流。"
            "“现在呢？”少年问。她没有立刻回答，只把旧钥匙放进掌心。"
        )
        with tempfile.TemporaryDirectory() as tmp:
            drafts = Path(tmp) / "outputs" / "drafts"
            drafts.mkdir(parents=True)
            (drafts / "chapter_03.md").write_text(draft_text, encoding="utf-8")

            result = style_fingerprint.inspect_draft(3, drafts_dir=drafts)

            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["chapter"], 3)
            self.assertEqual(set(result["metrics"].keys()), set(style_fingerprint.METRIC_KEYS))
            self.assertGreater(result["metrics"]["sentence_count"], 0)
            self.assertIn("dialogue_line_ratio", result["metrics"])

    def test_cli_parser_accepts_style_fingerprint_commands(self) -> None:
        parser = main.build_parser()

        build_args = parser.parse_args(["style-fingerprint", "build-baseline"])
        inspect_args = parser.parse_args(["style-fingerprint", "inspect-draft", "--chapter", "7"])

        self.assertEqual(build_args.command, "style-fingerprint")
        self.assertEqual(build_args.style_fingerprint_command, "build-baseline")
        self.assertEqual(inspect_args.style_fingerprint_command, "inspect-draft")
        self.assertEqual(inspect_args.chapter, 7)

    def test_baseline_json_contains_no_text_fields(self) -> None:
        sample_text = "冷光落在玻璃上。于是脚步声停住。不是退让而是等待。" * 20
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            examples = root / "data" / "style_examples"
            examples.mkdir(parents=True)
            (examples / "sample.md").write_text(sample_text, encoding="utf-8")
            out = root / "data" / "style_fingerprint" / "baseline.json"

            style_fingerprint.build_baseline(style_examples_dir=examples, output_path=out)
            payload = json.loads(out.read_text(encoding="utf-8"))

            self.assertNotIn("text", json.dumps(payload, ensure_ascii=False))
            self.assertNotIn(sample_text[:30], json.dumps(payload, ensure_ascii=False))
            self.assertNotIn("sample.md", json.dumps(payload, ensure_ascii=False))

    def test_single_sample_reliability_boundaries_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            examples = root / "examples"
            examples.mkdir()
            sample = examples / "private-name.md"

            for char_count in (500, 3999):
                sample.write_text("文" * char_count, encoding="utf-8")
                result = style_fingerprint.build_baseline(
                    style_examples_dir=examples,
                    output_path=root / f"baseline_{char_count}.json",
                )
                self.assertEqual(result["status"], "insufficient_source")
                self.assertEqual(result["baseline_quality"]["insufficient_reason"], "low_reliability")
                self.assertEqual(result["metrics"], {})
                self.assertEqual(result["dimension_stats"], {})
                self.assertEqual(result["dimension_reliability"], {})

            sample.write_text("文" * 4000, encoding="utf-8")
            result = style_fingerprint.build_baseline(
                style_examples_dir=examples,
                output_path=root / "baseline_4000.json",
            )
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["dimension_reliability"]["avg_sentence_length"]["level"], "medium")

    def test_below_minimum_and_two_short_samples_have_distinct_outcomes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            examples = root / "examples"
            examples.mkdir()
            (examples / "a.md").write_text("甲" * 499, encoding="utf-8")
            below = style_fingerprint.build_baseline(
                style_examples_dir=examples,
                output_path=root / "below.json",
            )
            self.assertEqual(below["status"], "insufficient_source")
            self.assertEqual(below["baseline_quality"]["insufficient_reason"], "total_sample_chars<500")

            (examples / "a.md").write_text("甲" * 250, encoding="utf-8")
            (examples / "b.md").write_text("乙" * 250, encoding="utf-8")
            two_samples = style_fingerprint.build_baseline(
                style_examples_dir=examples,
                output_path=root / "two.json",
            )
            self.assertEqual(two_samples["status"], "ok")
            self.assertEqual(two_samples["baseline_quality"]["sample_count"], 2)
            self.assertEqual(two_samples["baseline_quality"]["confidence"], 0.65)

    def test_single_physical_newlines_define_paragraphs(self) -> None:
        lf = style_fingerprint.calculate_metrics("甲甲\n乙乙乙\n\n丙")
        crlf = style_fingerprint.calculate_metrics("甲甲\r\n乙乙乙\r\n\r\n丙")

        self.assertEqual(lf["paragraph_count"], 3)
        self.assertEqual(lf["avg_paragraph_chars"], 2.0)
        self.assertEqual(crlf["paragraph_count"], 3)
        self.assertEqual(crlf["avg_paragraph_chars"], 2.0)

    def test_nonfinite_integer_config_degrades_to_defaults(self) -> None:
        config = {
            **style_fingerprint.DEFAULT_CONFIG,
            "source": {
                **style_fingerprint.DEFAULT_CONFIG["source"],
                "min_samples": math.inf,
                "min_total_chars": "Infinity",
                "good_sample_count": -math.inf,
                "good_total_chars": float("nan"),
            },
            "sentence": {"short_chars_max": math.inf, "long_chars_min": "-Infinity"},
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            examples = root / "examples"
            examples.mkdir()
            (examples / "a.md").write_text("甲" * 250, encoding="utf-8")
            (examples / "b.md").write_text("乙" * 250, encoding="utf-8")

            result = style_fingerprint.build_baseline(
                style_examples_dir=examples,
                output_path=root / "baseline.json",
                config=config,
            )
            inspected = style_fingerprint.calculate_metrics("甲。乙！", config)

            self.assertEqual(result["status"], "ok")
            self.assertEqual(inspected["sentence_count"], 2)

    def test_validate_baseline_hash_requires_both_aliases_and_rejects_corruption(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            examples = root / "examples"
            examples.mkdir()
            (examples / "a.md").write_text("甲" * 250, encoding="utf-8")
            (examples / "b.md").write_text("乙" * 250, encoding="utf-8")
            baseline = style_fingerprint.build_baseline(
                style_examples_dir=examples,
                output_path=root / "baseline.json",
            )

            self.assertEqual(style_fingerprint.validate_baseline_hash(baseline), "ok")
            for alias in ("baseline_hash", "hash"):
                single_alias = dict(baseline)
                single_alias.pop(alias)
                self.assertEqual(style_fingerprint.validate_baseline_hash(single_alias), "invalid_hash")

            missing = dict(baseline)
            missing.pop("baseline_hash")
            missing.pop("hash")
            self.assertEqual(style_fingerprint.validate_baseline_hash(missing), "invalid_hash")

            divergent = dict(baseline)
            divergent["hash"] = "0" * 64
            self.assertEqual(style_fingerprint.validate_baseline_hash(divergent), "invalid_hash")

            tampered = dict(baseline)
            tampered["sample_count"] = 99
            self.assertEqual(style_fingerprint.validate_baseline_hash(tampered), "invalid_hash")

            malformed = dict(baseline)
            malformed["bad"] = {object()}
            self.assertEqual(style_fingerprint.validate_baseline_hash(malformed), "invalid_hash")

            for nonfinite in (math.nan, math.inf, -math.inf):
                with self.subTest(nonfinite=nonfinite):
                    malformed_number = dict(baseline)
                    malformed_number["bad_number"] = nonfinite
                    # Even a caller that tries to re-hash the corrupt artifact
                    # cannot create a valid strict-JSON baseline identity.
                    self.assertEqual(
                        style_fingerprint.validate_baseline_hash(malformed_number),
                        "invalid_hash",
                    )

    def test_extreme_integer_float_config_degrades_to_default(self) -> None:
        huge = 10 ** 10000
        self.assertEqual(style_fingerprint._safe_float(huge, 1.0), 1.0)

    def test_v1_hash_can_be_validated_but_version_remains_explicit(self) -> None:
        artifact = {"status": "ok", "fingerprint_version": "local-stat-v1", "metrics": {}}
        digest = style_fingerprint._baseline_hash(artifact)
        artifact["baseline_hash"] = digest
        artifact["hash"] = digest

        self.assertEqual(style_fingerprint.validate_baseline_hash(artifact), "ok")
        self.assertNotEqual(artifact["fingerprint_version"], style_fingerprint.FINGERPRINT_VERSION)
