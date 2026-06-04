import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.book_runner import run_write_book
from src.utils import read_json, sha256_text, write_json


class BookRunnerTierFlowTests(unittest.TestCase):
    def test_env_tier_flows_to_writer_external_review_and_meta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"WRITE_REVIEW_TIER": "low"}, clear=False):
            root = Path(tmp)
            drafts = root / "outputs" / "drafts"
            reviews = root / "outputs" / "reviews"
            drafts.mkdir(parents=True)
            reviews.mkdir(parents=True)
            draft = "body\n"
            draft_sha = sha256_text(draft)
            seen: dict[str, str] = {}

            def fake_write_chapters(**kwargs):
                seen["writer_tier"] = kwargs.get("tier")
                (drafts / "chapter_01.md").write_text(draft, encoding="utf-8")
                write_json(
                    drafts / "chapter_01.meta.json",
                    {
                        "verdict": "Reject",
                        "needs_human_review": True,
                        "agent_reviews": [],
                        "run_context": {},
                        "draft_sha256": draft_sha,
                        "rewrite_count": 0,
                    },
                )
                return []

            def fake_review_target(_path, **kwargs):
                seen["external_tier"] = kwargs.get("tier")
                write_json(
                    reviews / "chapter_01.review.json",
                    {
                        "verdict": "Approve",
                        "needs_human_review": False,
                        "agent_reviews": [],
                        "tier": kwargs.get("tier"),
                        "panel_score": 6.8,
                        "approve_count": 3,
                        "tier_thresholds": {"min_approve_count": 3, "min_panel_score": 6.5},
                        "run_context": {},
                        "draft_sha256": draft_sha,
                    },
                )
                return []

            ready = {"status": "ready", "blockers": [], "warnings": [], "recommended_commands": []}
            with patch("src.book_runner.check_write_readiness", return_value=ready), patch(
                "src.book_runner._load_chapter_plan", return_value=None
            ), patch("src.book_runner.paths.workspace_name", return_value="unit"), patch(
                "src.book_runner.paths.drafts_dir", return_value=drafts
            ), patch("src.book_runner._llm_log_line_count", return_value=0), patch(
                "src.book_runner.write_chapters", side_effect=fake_write_chapters
            ), patch("src.book_runner.review_target", side_effect=fake_review_target), patch(
                "src.book_runner._snapshot", side_effect=lambda status, payload: {"status": status, **payload}
            ):
                result = run_write_book(
                    chapters=1,
                    require_start_point=False,
                    require_plan=False,
                    require_external_review=True,
                    auto_advance=False,
                )

            meta = read_json(drafts / "chapter_01.meta.json", {})
            self.assertEqual(result["status"], "succeeded")
            self.assertEqual(seen["writer_tier"], "low")
            self.assertEqual(seen["external_tier"], "low")
            self.assertEqual(meta["tier"], "low")
            self.assertEqual(meta["panel_score"], 6.8)
            self.assertEqual(meta["approve_count"], 3)
            self.assertEqual(meta["tier_thresholds"], {"min_approve_count": 3, "min_panel_score": 6.5})


if __name__ == "__main__":
    unittest.main()
