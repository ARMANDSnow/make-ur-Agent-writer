"""Iteration 088: local-only drama Insights aggregation tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src import paths
from src.cost_estimator import cost_cny
from src.web.drama_insights import collect_drama_insights


class DramaInsightsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._saved_workspace_dir = paths.WORKSPACE_DIR
        paths.WORKSPACE_DIR = Path(self._tmp.name)
        self.root = paths.WORKSPACE_DIR / "drama"

    def tearDown(self) -> None:
        paths.WORKSPACE_DIR = self._saved_workspace_dir
        self._tmp.cleanup()

    def _write_log(self, rows: list[object]) -> None:
        path = self.root / "logs" / "llm_calls.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = [row if isinstance(row, str) else json.dumps(row, ensure_ascii=False) for row in rows]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _write_episode(self, episode_no: int, payload: object) -> None:
        path = self.root / "outputs" / "episodes" / f"episode_{episode_no:02d}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(payload, dict) and "episode_no" not in payload:
            payload = {"episode_no": episode_no, **payload}
        path.write_text(
            payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )

    def _write_meta(self, episode_no: int, payload: object) -> None:
        path = self.root / "outputs" / "episodes" / f"episode_{episode_no:02d}.meta.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(payload, dict) and "episode_no" not in payload:
            payload = {"episode_no": episode_no, **payload}
        path.write_text(
            payload if isinstance(payload, str) else json.dumps(payload, ensure_ascii=False),
            encoding="utf-8",
        )

    def test_missing_workspace_is_zero_filled(self) -> None:
        data = collect_drama_insights("missing")

        self.assertEqual(
            data["llm_cost"],
            {
                "calls": 0,
                "prompt_tokens": 0,
                "response_tokens": 0,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
                "cost_cny": 0.0,
                "dirty_lines": 0,
            },
        )
        self.assertEqual(data["episode_meta_cost"], {"cost_cny": 0.0, "episodes": 0, "invalid": 0})
        self.assertEqual(
            data["duration"],
            {"total": 0, "within_tolerance": 0, "rate": 0.0, "tolerance_seconds": 3, "invalid": 0},
        )
        self.assertEqual(data["hook_types"], [])
        self.assertIn("真模型", data["cost_note"])

    def test_aggregates_only_drama_logs_and_episode_metrics(self) -> None:
        self._write_log(
            [
                {
                    "task": "drama_plan",
                    "model": "mock",
                    "prompt_tokens": 900,
                    "response_tokens": 100,
                    "cache_read_tokens": 0,
                    "cache_write_tokens": 12,
                },
                {
                    "task": "drama_review",
                    "model": "deepseek/deepseek-chat",
                    "prompt_tokens": 1000,
                    "response_tokens": 500,
                    "cache_read_tokens": 100,
                    "cache_write_tokens": 22,
                },
                {
                    "task": "writer",
                    "model": "deepseek/deepseek-chat",
                    "prompt_tokens": 9_999_999,
                    "response_tokens": 9_999_999,
                },
            ]
        )
        episodes = [
            (1, 60, 62, "反差钩", 1.25),
            (2, 60, 65, "反差钩", None),  # legacy meta: no cost_cny
            (3, 90, 87, "悬念钩", 0.25),
        ]
        for episode_no, target, estimate, hook_type, meta_cost in episodes:
            self._write_episode(
                episode_no,
                {
                    "episode_no": episode_no,
                    "target_duration_seconds": target,
                    "estimated_duration_seconds": estimate,
                    "ending_hook": {"type": hook_type},
                },
            )
            meta = {"episode_no": episode_no}
            if meta_cost is not None:
                meta["cost_cny"] = meta_cost
            self._write_meta(episode_no, meta)

        data = collect_drama_insights("drama")

        llm = data["llm_cost"]
        self.assertEqual(llm["calls"], 2)
        self.assertEqual(llm["prompt_tokens"], 1900)
        self.assertEqual(llm["response_tokens"], 600)
        self.assertEqual(llm["cache_read_tokens"], 100)
        self.assertEqual(llm["cache_write_tokens"], 34)
        self.assertEqual(llm["dirty_lines"], 0)
        self.assertAlmostEqual(
            llm["cost_cny"],
            round(cost_cny(1000, 100, 500, model="deepseek/deepseek-chat"), 4),
            places=4,
        )
        self.assertEqual(data["episode_meta_cost"], {"cost_cny": 1.5, "episodes": 3, "invalid": 0})
        self.assertEqual(
            data["duration"],
            {"total": 3, "within_tolerance": 2, "rate": 0.6667, "tolerance_seconds": 3, "invalid": 0},
        )
        self.assertEqual(
            data["hook_types"],
            [{"type": "反差钩", "count": 2}, {"type": "悬念钩", "count": 1}],
        )

    def test_dirty_lines_and_invalid_artifacts_degrade_without_leaking_raw_fields(self) -> None:
        self._write_log(
            [
                "{bad-json",
                "42",
                # Non-drama tasks are ignored before numeric validation.
                {"task": "writer", "prompt_tokens": False, "cost_cny": -999},
                {"task": "drama_plan", "model": "mock", "prompt_tokens": True},
                {"task": "drama_hooks", "model": "mock", "response_tokens": float("nan")},
                {"task": "drama_hooks", "model": "mock", "response_tokens": float("inf")},
                {"task": "drama_review", "model": "mock", "cache_read_tokens": -1},
                {"task": "drama_storyboard", "model": "mock", "cost_cny": -1},
                {
                    "task": "drama_review",
                    "model": "mock",
                    "prompt_tokens": "12",
                    "response_tokens": "3",
                    "cache_read_tokens": 0,
                    "cache_write_tokens": 0,
                    "prompt": "sensitive-token-must-not-appear",
                    "error": "private traceback",
                },
            ]
        )

        self._write_episode(
            1,
            {
                "target_duration_seconds": 60,
                "estimated_duration_seconds": 60,
                "ending_hook": {"type": "  反差钩  "},
                "prompt": "private episode prompt",
            },
        )
        self._write_episode(2, "{bad-json")
        self._write_episode(3, 7)
        self._write_episode(
            4,
            {
                "target_duration_seconds": True,
                "estimated_duration_seconds": 60,
                "ending_hook": {},
            },
        )
        self._write_episode(
            5,
            {
                "target_duration_seconds": 60,
                "estimated_duration_seconds": float("inf"),
                "ending_hook": {"type": ""},
            },
        )

        self._write_meta(1, "{bad-json")
        self._write_meta(2, 7)
        self._write_meta(3, {"cost_cny": True})
        self._write_meta(4, {"cost_cny": float("nan")})
        self._write_meta(5, {"cost_cny": -0.1})
        self._write_meta(6, {})  # legacy meta remains a valid zero-cost row
        self._write_meta(7, {"cost_cny": float("inf")})

        data = collect_drama_insights("drama")

        self.assertEqual(data["llm_cost"]["calls"], 1)
        self.assertEqual(data["llm_cost"]["prompt_tokens"], 12)
        self.assertEqual(data["llm_cost"]["response_tokens"], 3)
        self.assertEqual(data["llm_cost"]["dirty_lines"], 7)
        self.assertEqual(data["llm_cost"]["cost_cny"], 0.0)
        self.assertEqual(data["episode_meta_cost"], {"cost_cny": 0.0, "episodes": 1, "invalid": 6})
        self.assertEqual(
            data["duration"],
            {"total": 1, "within_tolerance": 1, "rate": 1.0, "tolerance_seconds": 3, "invalid": 4},
        )
        self.assertEqual(
            data["hook_types"],
            [{"type": "(未标注)", "count": 2}, {"type": "反差钩", "count": 1}],
        )
        serialized = json.dumps(data, ensure_ascii=False)
        self.assertNotIn("sensitive-token", serialized)
        self.assertNotIn("private traceback", serialized)
        self.assertNotIn("private episode prompt", serialized)

    def test_unbounded_token_numbers_are_rejected_before_pricing(self) -> None:
        self._write_log(
            [
                {
                    "task": "drama_storyboard",
                    "model": "deepseek/deepseek-chat",
                    "prompt_tokens": "9" * 10000,
                    "response_tokens": 1,
                }
            ]
        )
        data = collect_drama_insights("drama")
        self.assertEqual(data["llm_cost"]["calls"], 0)
        self.assertEqual(data["llm_cost"]["dirty_lines"], 1)
        self.assertEqual(data["llm_cost"]["cost_cny"], 0.0)

    def test_episode_identity_rejects_bool_float_and_noncanonical_files(self) -> None:
        self._write_episode(
            1,
            {
                "episode_no": True,
                "target_duration_seconds": 60,
                "estimated_duration_seconds": 60,
                "ending_hook": {"type": "伪造"},
            },
        )
        self._write_meta(1, {"episode_no": 1.0, "cost_cny": 99})
        odd = self.root / "outputs" / "episodes" / "episode_001.json"
        odd.write_text(
            json.dumps(
                {
                    "episode_no": 1,
                    "target_duration_seconds": 60,
                    "estimated_duration_seconds": 60,
                    "ending_hook": {"type": "非 canonical"},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        data = collect_drama_insights("drama")

        self.assertEqual(data["episode_meta_cost"], {"cost_cny": 0.0, "episodes": 0, "invalid": 1})
        self.assertEqual(data["duration"]["total"], 0)
        self.assertEqual(data["duration"]["invalid"], 2)
        self.assertEqual(data["hook_types"], [])


if __name__ == "__main__":
    unittest.main()
