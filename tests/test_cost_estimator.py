import tempfile
import unittest
from pathlib import Path

from src.cost_estimator import (
    estimate_cost,
    estimate_next_chapter_cost,
    render_cost_estimate,
)


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


class EstimateNextChapterCostTests(unittest.TestCase):
    """iter076 HIGH#2：costs 是**累计值**序列——先差分还原单章成本再取滑动均值。"""

    def test_empty_history_falls_back_to_default(self) -> None:
        self.assertEqual(estimate_next_chapter_cost([], 2.0), 2.0)
        self.assertEqual(estimate_next_chapter_cost(None, 1.5), 1.5)

    def test_cumulative_costs_are_diffed(self) -> None:
        costs = [
            {"chapter": 1, "cost_cny": 1.0},   # 单章 1.0
            {"chapter": 2, "cost_cny": 3.0},   # 单章 2.0
            {"chapter": 3, "cost_cny": 6.0},   # 单章 3.0
        ]
        # 近 3 章均值 = (1+2+3)/3 = 2.0
        self.assertAlmostEqual(estimate_next_chapter_cost(costs, 9.9), 2.0)

    def test_moving_window_uses_recent_chapters(self) -> None:
        costs = [
            {"cost_cny": 10.0},   # 单章 10（应被窗口滑出）
            {"cost_cny": 11.0},   # 单章 1
            {"cost_cny": 12.0},   # 单章 1
            {"cost_cny": 13.0},   # 单章 1
        ]
        self.assertAlmostEqual(estimate_next_chapter_cost(costs, 9.9, window=3), 1.0)

    def test_garbage_entries_skipped_and_negative_deltas_dropped(self) -> None:
        costs = [
            "not-a-dict",
            {"no_cost_field": 1},
            {"cost_cny": "oops"},        # float() 失败 → 整体 fail-open default
        ]
        self.assertEqual(estimate_next_chapter_cost(costs, 2.5), 2.5)
        # 累计值倒退（脏账本）产生的负差分被丢弃，不污染均值。
        costs = [{"cost_cny": 5.0}, {"cost_cny": 3.0}, {"cost_cny": 7.0}]
        # 差分：+5、-2（丢弃）、+4 → 均值 (5+4)/2 = 4.5
        self.assertAlmostEqual(estimate_next_chapter_cost(costs, 9.9), 4.5)

    def test_default_clamped_non_negative(self) -> None:
        self.assertEqual(estimate_next_chapter_cost([], -3.0), 0.0)


if __name__ == "__main__":
    unittest.main()
