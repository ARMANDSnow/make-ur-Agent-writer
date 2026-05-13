import tempfile
import unittest
from pathlib import Path

from src.observability import (
    build_manifest_markdown,
    check_manifest_integrity,
    check_report_snapshots,
    generate_manifest_report,
    render_manifest_check,
)


class ManifestReportTests(unittest.TestCase):
    def test_manifest_markdown_groups_and_flags_short_chapters(self) -> None:
        manifest = [
            {
                "chapter_id": "v1_ch001",
                "volume_id": "v1",
                "title": "楔子",
                "start_line": 1,
                "end_line": 2,
                "char_count": 100,
            },
            {
                "chapter_id": "v1_ch002",
                "volume_id": "v1",
                "title": "第一章",
                "start_line": 3,
                "end_line": 20,
                "char_count": 3000,
            },
        ]
        md = build_manifest_markdown(manifest)
        self.assertIn("## v1", md)
        self.assertIn("v1_ch001", md)
        self.assertIn("short", md)

    def test_generate_manifest_report_writes_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "data" / "chapter_manifest.json").write_text(
                '[{"chapter_id":"c1","volume_id":"v","title":"T","start_line":1,"end_line":2,"char_count":10}]',
                encoding="utf-8",
            )
            path = generate_manifest_report(root)
            self.assertTrue(path.exists())
            self.assertIn("c1", path.read_text(encoding="utf-8"))

    def test_check_report_snapshots_reports_and_updates_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "data"
            reviews = root / "outputs" / "reviews"
            data.mkdir(parents=True)
            reviews.mkdir(parents=True)
            (data / "chapter_manifest.json").write_text(
                '[{"chapter_id":"c1","volume_id":"v","title":"T","start_line":1,"end_line":2,"char_count":10}]',
                encoding="utf-8",
            )
            (data / "chapter_manifest.md").write_text("stale\n", encoding="utf-8")
            (reviews / "review_summary.md").write_text("# Review Summary\n", encoding="utf-8")

            result = check_report_snapshots(root)
            self.assertFalse(result["ok"])
            self.assertIn("data/chapter_manifest.md", result["mismatches"])
            self.assertIn("--- data/chapter_manifest.md (current)", result["mismatches"]["data/chapter_manifest.md"])

            updated = check_report_snapshots(root, update=True)
            self.assertTrue(updated["ok"])
            self.assertTrue(check_report_snapshots(root)["ok"])

    def test_check_manifest_integrity_lists_low_confidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "data"
            normalized = data / "normalized_texts"
            normalized.mkdir(parents=True)
            text_path = normalized / "v.txt"
            text_path.write_text("第一章\n正文\n", encoding="utf-8")
            (data / "chapter_manifest.json").write_text(
                f"""[
                  {{"chapter_id":"c1","volume_id":"v","normalized_file":"{text_path}","title":"T1","start_line":1,"end_line":2,"char_count":5000,"confidence":0.4}}
                ]""",
                encoding="utf-8",
            )
            result = check_manifest_integrity(root)
            rendered = render_manifest_check(result)
        self.assertEqual(len(result["low_confidence_chapters"]), 1)
        self.assertEqual(result["low_confidence_chapters"][0]["chapter_id"], "c1")
        self.assertIn("low_confidence_chapters: 1", rendered)
        self.assertIn("c1: confidence=0.4", rendered)

    def test_check_manifest_integrity_flags_duplicates_and_overlaps(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "data"
            normalized = data / "normalized_texts"
            normalized.mkdir(parents=True)
            text_path = normalized / "v.txt"
            text_path.write_text("第一章\n正文\n第二章\n正文\n", encoding="utf-8")
            (data / "chapter_manifest.json").write_text(
                f"""[
                  {{"chapter_id":"c1","volume_id":"v","normalized_file":"{text_path}","title":"T1","start_line":1,"end_line":3,"char_count":10}},
                  {{"chapter_id":"c1","volume_id":"v","normalized_file":"{text_path}","title":"T2","start_line":3,"end_line":4,"char_count":3000}}
                ]""",
                encoding="utf-8",
            )
            result = check_manifest_integrity(root)
            rendered = render_manifest_check(result)
            self.assertFalse(result["ok"])
            self.assertIn("duplicate chapter_id", rendered)
            self.assertIn("overlaps", rendered)
            self.assertIn("short chapter", rendered)


if __name__ == "__main__":
    unittest.main()
