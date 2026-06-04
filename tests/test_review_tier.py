import os
import unittest
from unittest.mock import patch

from src import review_tier


class ReviewTierTests(unittest.TestCase):
    def test_thresholds_table(self) -> None:
        high = review_tier.thresholds_for("high")
        mid = review_tier.thresholds_for("mid")
        low = review_tier.thresholds_for("low")

        self.assertEqual(high.min_approve_count, 5)
        self.assertEqual(high.min_panel_score, 8.5)
        self.assertEqual(mid.min_approve_count, 4)
        self.assertEqual(mid.min_panel_score, 7.5)
        self.assertEqual(low.min_approve_count, 3)
        self.assertEqual(low.min_panel_score, 6.5)

    def test_default_and_env_resolution(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(review_tier.resolve_tier(), "mid")
        with patch.dict(os.environ, {"WRITE_REVIEW_TIER": "LOW"}, clear=True):
            self.assertEqual(review_tier.resolve_tier(), "low")
        with patch.dict(os.environ, {"WRITE_REVIEW_TIER": "high"}, clear=True):
            self.assertEqual(review_tier.resolve_tier("mid"), "mid")

    def test_invalid_tier_rejected(self) -> None:
        with self.assertRaises(ValueError):
            review_tier.resolve_tier("strict")

    def test_threshold_snapshot(self) -> None:
        self.assertEqual(
            review_tier.thresholds_snapshot("low"),
            {"min_approve_count": 3, "min_panel_score": 6.5},
        )


if __name__ == "__main__":
    unittest.main()
