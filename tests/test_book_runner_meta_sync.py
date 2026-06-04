import tempfile
import unittest
from pathlib import Path

from src.book_runner import _sync_meta_with_external_review
from src.chapter_status import chapter_status
from src.utils import read_json, sha256_text, write_json


class BookRunnerMetaSyncTests(unittest.TestCase):
    def test_external_review_sync_updates_meta_and_strict_status(self) -> None:
        ctx = {
            "start_chapter_id": "v1_ch003",
            "start_point_fingerprint": "start-fp",
            "chapter_plan_item_fingerprint": "item-fp",
            "plan_fingerprint": "plan-fp",
        }

        with self.subTest("external approve wins and preserves writer fields"):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                drafts = root / "drafts"
                reviews = root / "reviews"
                drafts.mkdir()
                reviews.mkdir()
                draft = "body\n"
                draft_sha = sha256_text(draft)
                (drafts / "chapter_02.md").write_text(draft, encoding="utf-8")
                write_json(
                    drafts / "chapter_02.meta.json",
                    {
                        "verdict": "Reject",
                        "needs_human_review": True,
                        "agent_reviews": [{"agent_name": "writer", "verdict": "Reject"}],
                        "last_blocking_reasons": [{"rule_id": "missing_payoff"}],
                        "run_context": ctx,
                        "draft_sha256": draft_sha,
                        "polish_applied": True,
                        "polish_diff_stats": {"pre_chars": 10, "post_chars": 12},
                        "lint_blocked_reviews": [{"attempt": 1}],
                        "chinese_char_count": 3200,
                        "rewrite_count": 2,
                    },
                )
                write_json(
                    reviews / "chapter_02.review.json",
                    {
                        "verdict": "Approve",
                        "agent_reviews": [{"agent_name": "external", "verdict": "Approve"}],
                        "run_context": ctx,
                        "draft_sha256": draft_sha,
                    },
                )

                synced = _sync_meta_with_external_review(drafts, 2)
                meta = read_json(drafts / "chapter_02.meta.json", {})

                self.assertEqual(synced["verdict"], "Approve")
                self.assertEqual(meta["verdict"], "Approve")
                self.assertFalse(meta["needs_human_review"])
                self.assertTrue(meta["external_synced_at"])
                self.assertEqual(meta["agent_reviews"], [{"agent_name": "external", "verdict": "Approve"}])
                self.assertEqual(meta["last_blocking_reasons"], [])
                self.assertEqual(meta["run_context"], ctx)
                self.assertEqual(meta["draft_sha256"], draft_sha)
                self.assertTrue(meta["polish_applied"])
                self.assertEqual(meta["polish_diff_stats"], {"pre_chars": 10, "post_chars": 12})
                self.assertEqual(meta["lint_blocked_reviews"], [{"attempt": 1}])
                self.assertEqual(meta["chinese_char_count"], 3200)
                self.assertEqual(meta["rewrite_count"], 2)

                status = chapter_status(
                    2,
                    drafts,
                    validate_context=True,
                    require_external_review=True,
                )
                self.assertTrue(status["approved"])
                self.assertEqual(status["strict_failures"], [])

        with self.subTest("external reject wins"):
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                drafts = root / "drafts"
                reviews = root / "reviews"
                drafts.mkdir()
                reviews.mkdir()
                draft = "body\n"
                draft_sha = sha256_text(draft)
                (drafts / "chapter_02.md").write_text(draft, encoding="utf-8")
                write_json(
                    drafts / "chapter_02.meta.json",
                    {
                        "verdict": "Approve",
                        "needs_human_review": False,
                        "agent_reviews": [{"agent_name": "writer", "verdict": "Approve"}],
                        "run_context": ctx,
                        "draft_sha256": draft_sha,
                        "rewrite_count": 0,
                    },
                )
                write_json(
                    reviews / "chapter_02.review.json",
                    {
                        "verdict": "Reject",
                        "needs_human_review": True,
                        "agent_reviews": [{"agent_name": "external", "verdict": "Reject"}],
                        "run_context": ctx,
                        "draft_sha256": draft_sha,
                    },
                )

                _sync_meta_with_external_review(drafts, 2)
                meta = read_json(drafts / "chapter_02.meta.json", {})

                self.assertEqual(meta["verdict"], "Reject")
                self.assertTrue(meta["needs_human_review"])
                self.assertEqual(meta["agent_reviews"], [{"agent_name": "external", "verdict": "Reject"}])


if __name__ == "__main__":
    unittest.main()
