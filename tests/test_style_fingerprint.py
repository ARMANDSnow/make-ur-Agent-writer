from __future__ import annotations

import json
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
