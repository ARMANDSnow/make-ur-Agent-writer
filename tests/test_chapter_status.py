"""Iter 019: chapter_status helper regression tests.

The unattended write loop (scripts/write_book.sh) reads this helper's
output via the `chapter-status` subcommand to decide skip / retry /
gave-up. The contract is the dict shape and the four state combinations.
"""

import json
import tempfile
import unittest
from pathlib import Path

from src.chapter_status import chapter_status
from src.utils import sha256_text


class ChapterStatusTests(unittest.TestCase):
    def test_missing_chapter_reports_not_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status = chapter_status(7, Path(tmp))
        self.assertEqual(status["chapter_no"], 7)
        self.assertFalse(status["exists"])
        self.assertFalse(status["approved"])
        self.assertFalse(status["failure"])
        self.assertIsNone(status["verdict"])

    def test_approve_meta_without_failure_file_is_approved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            drafts = Path(tmp)
            (drafts / "chapter_03.md").write_text("body\n", encoding="utf-8")
            (drafts / "chapter_03.meta.json").write_text(
                json.dumps(
                    {
                        "verdict": "Approve",
                        "needs_human_review": False,
                        "rewrite_count": 0,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            status = chapter_status(3, drafts)
        self.assertTrue(status["exists"])
        self.assertTrue(status["approved"])
        self.assertFalse(status["failure"])
        self.assertEqual(status["verdict"], "Approve")

    def test_failure_file_marks_not_approved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            drafts = Path(tmp)
            (drafts / "chapter_05.md").write_text("draft body\n", encoding="utf-8")
            (drafts / "chapter_05.meta.json").write_text(
                json.dumps(
                    {
                        "verdict": "Reject",
                        "needs_human_review": True,
                        "rewrite_count": 3,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (drafts / "chapter_05.failure.json").write_text("{}", encoding="utf-8")
            status = chapter_status(5, drafts)
        self.assertTrue(status["exists"])
        self.assertTrue(status["failure"])
        self.assertTrue(status["needs_review"])
        self.assertFalse(status["approved"])
        self.assertEqual(status["verdict"], "Reject")
        self.assertEqual(status["rewrite_count"], 3)

    def test_strict_mode_rejects_legacy_approved_meta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            drafts = Path(tmp)
            (drafts / "chapter_01.md").write_text("body\n", encoding="utf-8")
            (drafts / "chapter_01.meta.json").write_text(
                json.dumps({"verdict": "Approve", "needs_human_review": False}),
                encoding="utf-8",
            )
            status = chapter_status(
                1,
                drafts,
                validate_context=True,
                require_start_point=True,
                require_plan=True,
            )
        self.assertFalse(status["approved"])
        self.assertIn("legacy_missing_context", status["strict_failures"])

    def test_strict_mode_requires_matching_hash_and_external_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            drafts = root / "drafts"
            reviews = root / "reviews"
            drafts.mkdir()
            reviews.mkdir()
            draft = "body\n"
            ctx = {
                "start_chapter_id": "v1_ch003",
                "start_point_fingerprint": "start-fp",
                "chapter_plan_item_fingerprint": "item-fp",
                "plan_fingerprint": "plan-fp",
            }
            (drafts / "chapter_02.md").write_text(draft, encoding="utf-8")
            (drafts / "chapter_02.meta.json").write_text(
                json.dumps(
                    {
                        "verdict": "Approve",
                        "needs_human_review": False,
                        "run_context": ctx,
                        "draft_sha256": sha256_text(draft),
                    }
                ),
                encoding="utf-8",
            )
            (reviews / "chapter_02.review.json").write_text(
                json.dumps(
                    {
                        "verdict": "Approve",
                        "run_context": ctx,
                        "draft_sha256": sha256_text(draft),
                    }
                ),
                encoding="utf-8",
            )
            status = chapter_status(
                2,
                drafts,
                validate_context=True,
                require_start_point=True,
                require_plan=True,
                require_external_review=True,
                expected_context=ctx,
            )
        self.assertTrue(status["approved"])
        self.assertEqual(status["strict_failures"], [])


if __name__ == "__main__":
    unittest.main()
