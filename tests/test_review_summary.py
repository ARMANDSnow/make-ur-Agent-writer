import json
import tempfile
import unittest
from pathlib import Path

from src.observability import collect_review_summary, generate_review_summary, render_review_summary


class ReviewSummaryTests(unittest.TestCase):
    def test_review_summary_counts_rejects_and_linter_rules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reviews = root / "outputs" / "reviews"
            drafts = root / "outputs" / "drafts"
            reviews.mkdir(parents=True)
            drafts.mkdir(parents=True)
            (reviews / "a.review.json").write_text(
                json.dumps(
                    {
                        "verdict": "Reject",
                        "lint_issues": [{"rule": "not_x_but_y", "severity": "error"}],
                    }
                ),
                encoding="utf-8",
            )
            (drafts / "chapter_01.meta.json").write_text(
                json.dumps({"needs_human_review": True}), encoding="utf-8"
            )
            summary = collect_review_summary(root)
            out_summary, path = generate_review_summary(root)
            self.assertEqual(summary["rejects"], 1)
            self.assertEqual(summary["needs_human_review"], 1)
            self.assertEqual(summary["linter_rules"]["not_x_but_y"], 1)
            self.assertEqual(out_summary["rejects"], 1)
            self.assertTrue(path.exists())
            self.assertIn("needs_human_review: 1", render_review_summary(summary))


if __name__ == "__main__":
    unittest.main()
