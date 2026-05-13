import tempfile
import unittest
from pathlib import Path

from src.cost_estimator import estimate_cost, render_cost_estimate


class CostEstimatorTests(unittest.TestCase):
    def test_estimate_cost_runs_without_api_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "data").mkdir()
            (root / "data" / "chapter_manifest.json").write_text(
                '[{"chapter_id":"c1","char_count":160},{"chapter_id":"c2","char_count":160}]',
                encoding="utf-8",
            )
            estimate = estimate_cost(root)
        self.assertEqual(estimate["chapters"], 2)
        self.assertEqual(estimate["estimated_source_tokens"], 200)
        self.assertIn("extract_calls: 2", render_cost_estimate(estimate))


if __name__ == "__main__":
    unittest.main()
