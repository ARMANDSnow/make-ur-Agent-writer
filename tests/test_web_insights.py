"""iter 033: Insights aggregation unit tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src import paths
from src.web.insights import collect_insights
from src.web.workspace_ctx import use_workspace


class InsightsAggregationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._saved = paths.WORKSPACE_DIR
        paths.WORKSPACE_DIR = Path(self._tmp.name)
        ws = paths.WORKSPACE_DIR / "alpha"
        (ws / "data").mkdir(parents=True)
        (ws / "outputs" / "drafts").mkdir(parents=True)
        (ws / "outputs" / "reviews").mkdir(parents=True)
        (ws / "logs").mkdir(parents=True)
        (ws / "logs" / "llm_calls.jsonl").write_text(
            "\n".join([
                json.dumps({"chapter": 1, "cost_cny": 0.10, "model": "mock",
                            "cache_read_tokens": 0, "cache_write_tokens": 200}),
                json.dumps({"chapter": 1, "cost_cny": 0.20, "model": "mock",
                            "cache_read_tokens": 150, "cache_write_tokens": 0}),
                json.dumps({"chapter": 2, "cost_cny": 0.40, "model": "mock",
                            "cache_read_tokens": 50, "cache_write_tokens": 50}),
            ]) + "\n",
            encoding="utf-8",
        )
        (ws / "outputs" / "drafts" / "chapter_01.md").write_text("body", encoding="utf-8")
        (ws / "outputs" / "drafts" / "chapter_01.meta.json").write_text(
            json.dumps({
                "agent_reviews": [
                    {"agent_name": "A", "verdict": "Approve", "score": 8,
                     "sub_scores": {"plot": 7, "prose": 8, "fidelity": 9}}
                ]
            }), encoding="utf-8",
        )

    def tearDown(self) -> None:
        paths.WORKSPACE_DIR = self._saved
        self._tmp.cleanup()

    def test_cost_by_chapter_aggregates(self) -> None:
        with use_workspace("alpha"):
            data = collect_insights()
        cost = {r["chapter"]: r for r in data["cost_by_chapter"]}
        self.assertAlmostEqual(cost[1]["cost_cny"], 0.30, places=3)
        self.assertEqual(cost[1]["calls"], 2)
        self.assertAlmostEqual(cost[2]["cost_cny"], 0.40, places=3)

    def test_cache_hit_ratio(self) -> None:
        with use_workspace("alpha"):
            data = collect_insights()
        row = next(r for r in data["cache_by_model"] if r["model"] == "mock")
        self.assertAlmostEqual(row["hit_ratio"], 0.444, places=2)
        self.assertEqual(row["cache_read_tokens"], 200)
        self.assertEqual(row["cache_write_tokens"], 250)

    def test_subscores(self) -> None:
        with use_workspace("alpha"):
            data = collect_insights()
        self.assertEqual(len(data["subscores"]), 1)
        row = data["subscores"][0]
        self.assertEqual(row["chapter"], 1)
        self.assertAlmostEqual(row["plot"], 7.0)
        self.assertAlmostEqual(row["prose"], 8.0)
        self.assertAlmostEqual(row["fidelity"], 9.0)
        self.assertEqual(row["agents"], 1)


if __name__ == "__main__":
    unittest.main()
