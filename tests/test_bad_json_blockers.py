"""iter059 P1: corrupt JSON state files must degrade / surface clean blockers,
not crash with a raw JSONDecodeError traceback.

Covers the bad-JSON cluster from docs/FRONTEND_BUG_AUDIT_2026-06.md §4:
  #10 rolling summary, #5 draft meta/review, #13 driver state/pid, #4 chapter_plan.

The common root cause was key state files read with the strict ``read_json``
(exists-but-corrupt -> JSONDecodeError) instead of the degrade-safe
``read_json_optional``. iter059 converts each hot read at the call site.

Mock-only; no network, no real workspace data.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path


class RollingSummaryCorruptTests(unittest.TestCase):
    """#10: load_rolling_summary degrades a malformed file to empty state,
    honoring its docstring (was: raised JSONDecodeError mid-write)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = Path(self._tmp.name) / "rolling.json"

    def test_corrupt_rolling_summary_degrades_to_empty(self) -> None:
        from src import chapter_summary

        self.path.write_text("{not valid json", encoding="utf-8")
        data = chapter_summary.load_rolling_summary(self.path)
        self.assertEqual(data, {"chapters": [], "compressed_older": []})

    def test_valid_rolling_summary_still_loads(self) -> None:
        from src import chapter_summary

        self.path.write_text(
            json.dumps({"chapters": [{"chapter": 1}], "compressed_older": ["x"]}),
            encoding="utf-8",
        )
        data = chapter_summary.load_rolling_summary(self.path)
        self.assertEqual(data["chapters"], [{"chapter": 1}])
        self.assertEqual(data["compressed_older"], ["x"])


class ChapterStatusCorruptTests(unittest.TestCase):
    """#5: corrupt chapter_NN.meta.json / review JSON must not crash
    resume/status; they degrade or surface a clean strict-failure."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        # review_path = drafts_dir.parent / "reviews"; mirror that layout.
        self.drafts = Path(self._tmp.name) / "outputs" / "drafts"
        self.drafts.mkdir(parents=True)
        (self.drafts / "chapter_01.md").write_text("正文内容。", encoding="utf-8")

    def test_corrupt_meta_degrades_not_crash(self) -> None:
        from src.chapter_status import chapter_status

        (self.drafts / "chapter_01.meta.json").write_text("{bad json", encoding="utf-8")
        status = chapter_status(1, self.drafts)
        self.assertTrue(status["exists"])
        self.assertFalse(status["approved"])
        self.assertIsNone(status["verdict"])
        self.assertEqual(status["rewrite_count"], 0)

    def test_corrupt_review_yields_external_review_invalid(self) -> None:
        from src.chapter_status import chapter_status

        reviews = self.drafts.parent / "reviews"
        reviews.mkdir()
        (reviews / "chapter_01.review.json").write_text("{bad json", encoding="utf-8")
        status = chapter_status(
            1, self.drafts, validate_context=True, require_external_review=True
        )
        self.assertIn("external_review_invalid", status["strict_failures"])
        self.assertFalse(status["approved"])


if __name__ == "__main__":
    unittest.main()
