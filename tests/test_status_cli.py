import tempfile
import unittest
from pathlib import Path

from main import build_parser
from src.observability import collect_status, render_status


class StatusCliTests(unittest.TestCase):
    def test_parser_includes_observability_commands(self) -> None:
        for command in (
            "status",
            "manifest-report",
            "review-summary",
            "check-reports",
            "check-manifest",
            "retry-failures",
            "estimate-cost",
            "preflight",
        ):
            args = build_parser().parse_args([command])
            self.assertEqual(args.command, command)

    def test_status_report_counts_outputs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data" / "normalized_texts").mkdir(parents=True)
            (root / "data" / "normalized_texts" / "v.txt").write_text("x", encoding="utf-8")
            (root / "data" / "source_map").mkdir(parents=True)
            (root / "data" / "source_map" / "v.json").write_text("{}", encoding="utf-8")
            (root / "data" / "normalized_manifest.json").write_text("[]", encoding="utf-8")
            (root / "data" / "chapter_manifest.json").write_text(
                '[{"chapter_id":"c1","volume_id":"v"}]', encoding="utf-8"
            )
            (root / "outputs" / "reviews").mkdir(parents=True)
            (root / "outputs" / "reviews" / "x.review.json").write_text("{}", encoding="utf-8")
            status = collect_status(root)
        text = render_status(status)
        self.assertIn("normalize: done", text)
        self.assertIn("split: done", text)
        self.assertIn("review: 1 reports", text)


if __name__ == "__main__":
    unittest.main()
