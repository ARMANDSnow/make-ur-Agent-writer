"""Iter 024 P3: tests for estimate_cost_since + cost_cny shared helper.

Covers per-chapter cost delta computation (used by write_book.sh
--budget-cny ceiling check) and the now-shared deepseek pricing
constants.
"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path


class CostPerChapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_ws = os.environ.get("WORKSPACE_NAME")
        os.environ["WORKSPACE_NAME"] = "iter024costtest"
        repo_root = Path(__file__).resolve().parent.parent
        self.ws_root = repo_root / "workspaces" / "iter024costtest"
        (self.ws_root / "logs").mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        if self.ws_root.exists():
            shutil.rmtree(self.ws_root)
        if self._old_ws is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._old_ws

    def _write_calls(self, calls: list) -> None:
        path = self.ws_root / "logs" / "llm_calls.jsonl"
        with path.open("w", encoding="utf-8") as f:
            for call in calls:
                f.write(json.dumps(call) + "\n")

    def test_cost_cny_basic_math(self) -> None:
        """Iter 024 P3 shared helper. 10K prompt (5K cache hit) + 2K resp ≈ ¥0.028."""
        from src.cost_estimator import cost_cny
        c = cost_cny(10000, 5000, 2000)
        # non_cache=5000 * 0.27/1M + cache 5000 * 0.07/1M + resp 2000 * 1.1/1M
        # = 0.00135 + 0.00035 + 0.0022 = 0.0039 USD ≈ ¥0.0281
        self.assertAlmostEqual(c, 0.0281, places=3)

    def test_cost_cny_handles_negative_gracefully(self) -> None:
        from src.cost_estimator import cost_cny
        # If cache_read > prompt (data corruption), non_cache clamps to 0
        self.assertEqual(cost_cny(0, 0, 0), 0.0)
        c = cost_cny(1000, 5000, 0)  # cache > prompt
        # non_cache=max(1000-5000,0)=0, cache_read still costs
        # = 0 + 5000*0.07/1M + 0 = 0.00035 USD ≈ ¥0.00252
        self.assertGreater(c, 0)
        self.assertLess(c, 0.01)

    def test_estimate_cost_since_no_file(self) -> None:
        from src.cost_estimator import estimate_cost_since
        # Workspace exists but no llm_calls.jsonl yet
        (self.ws_root / "logs" / "llm_calls.jsonl").unlink(missing_ok=True)
        out = estimate_cost_since(0)
        self.assertEqual(out["calls"], 0)
        self.assertEqual(out["cost_cny"], 0.0)

    def test_estimate_cost_since_with_offset(self) -> None:
        from src.cost_estimator import estimate_cost_since
        self._write_calls([
            {"task": "write", "prompt_tokens": 1000, "response_tokens": 500,
             "cache_read_tokens": 0, "cache_write_tokens": 0},
            {"task": "review", "prompt_tokens": 2000, "response_tokens": 800,
             "cache_read_tokens": 1000, "cache_write_tokens": 0},
            {"task": "write", "prompt_tokens": 1500, "response_tokens": 600,
             "cache_read_tokens": 500, "cache_write_tokens": 0},
        ])
        # Full file
        full = estimate_cost_since(0)
        self.assertEqual(full["calls"], 3)
        self.assertEqual(full["prompt_tokens"], 4500)
        self.assertGreater(full["cost_cny"], 0)
        # Last call only
        last = estimate_cost_since(2)
        self.assertEqual(last["calls"], 1)
        self.assertEqual(last["prompt_tokens"], 1500)
        # Beyond end → empty
        beyond = estimate_cost_since(100)
        self.assertEqual(beyond["calls"], 0)


if __name__ == "__main__":
    unittest.main()
