"""Iteration 088: local-only drama Insights aggregation tests."""

from __future__ import annotations

import os
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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
                "status": "ok",
                "calls": 0,
                "prompt_tokens": 0,
                "response_tokens": 0,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
                "cost_cny": 0.0,
                "dirty_lines": 0,
            },
        )
        self.assertEqual(
            data["episode_meta_cost"],
            {"status": "ok", "cost_cny": 0.0, "episodes": 0, "invalid": 0},
        )
        self.assertEqual(
            data["media_pricing"],
            {
                "schema_version": 1,
                "status": "ok",
                "ledger_count": 0,
                "invalid_ledgers": 0,
                "fact_count": 0,
                "task_count": 0,
                "currencies": [],
                "rows": [],
            },
        )
        self.assertEqual(data["media_metrics"]["status"], "ok")
        self.assertEqual(data["media_metrics"]["task_count"], 0)
        self.assertIsNone(data["media_metrics"]["success_rate"])
        self.assertIsNone(
            data["media_metrics"]["queue_wait_average_ms"]
        )
        self.assertEqual(data["media_metrics"]["rows"], [])
        self.assertEqual(
            data["duration"],
            {
                "status": "ok",
                "total": 0,
                "within_tolerance": 0,
                "rate": 0.0,
                "tolerance_seconds": 3,
                "invalid": 0,
            },
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
        self.assertEqual(
            data["episode_meta_cost"],
            {"status": "ok", "cost_cny": 1.5, "episodes": 3, "invalid": 0},
        )
        self.assertEqual(
            data["duration"],
            {
                "status": "ok",
                "total": 3,
                "within_tolerance": 2,
                "rate": 0.6667,
                "tolerance_seconds": 3,
                "invalid": 0,
            },
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

        self.assertEqual(data["llm_cost"]["status"], "degraded")
        self.assertEqual(data["llm_cost"]["calls"], 0)
        self.assertEqual(data["llm_cost"]["prompt_tokens"], 0)
        self.assertEqual(data["llm_cost"]["response_tokens"], 0)
        self.assertEqual(data["llm_cost"]["dirty_lines"], 1)
        self.assertEqual(data["llm_cost"]["cost_cny"], 0.0)
        self.assertEqual(
            data["episode_meta_cost"],
            {"status": "degraded", "cost_cny": 0.0, "episodes": 0, "invalid": 1},
        )
        self.assertEqual(
            data["duration"],
            {
                "status": "degraded",
                "total": 0,
                "within_tolerance": 0,
                "rate": 0.0,
                "tolerance_seconds": 3,
                "invalid": 1,
            },
        )
        self.assertEqual(data["hook_types"], [])
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

        self.assertEqual(
            data["episode_meta_cost"],
            {"status": "degraded", "cost_cny": 0.0, "episodes": 0, "invalid": 1},
        )
        self.assertEqual(data["duration"]["total"], 0)
        self.assertEqual(data["duration"]["status"], "degraded")
        self.assertEqual(data["duration"]["invalid"], 1)
        self.assertEqual(data["hook_types"], [])

    def test_symlinked_sources_degrade_empty_without_following(self) -> None:
        outside = Path(self._tmp.name) / "outside"
        outside.mkdir()
        (outside / "episode_01.json").write_text(
            json.dumps(
                {
                    "episode_no": 1,
                    "target_duration_seconds": 60,
                    "estimated_duration_seconds": 60,
                    "ending_hook": {"type": "OUTSIDE_HOOK"},
                }
            ),
            encoding="utf-8",
        )
        episodes = self.root / "outputs" / "episodes"
        episodes.parent.mkdir(parents=True)
        episodes.symlink_to(outside, target_is_directory=True)
        log_outside = outside / "llm_calls.jsonl"
        log_outside.write_text(
            json.dumps({"task": "drama_plan", "model": "mock", "prompt_tokens": 7}),
            encoding="utf-8",
        )
        logs = self.root / "logs"
        logs.mkdir()
        (logs / "llm_calls.jsonl").symlink_to(log_outside)

        data = collect_drama_insights("drama")

        self.assertEqual(data["llm_cost"]["status"], "degraded")
        self.assertEqual(data["llm_cost"]["calls"], 0)
        self.assertEqual(data["duration"]["total"], 0)
        self.assertEqual(data["hook_types"], [])
        self.assertNotIn("OUTSIDE_HOOK", json.dumps(data, ensure_ascii=False))

    def test_episode_namespace_change_degrades_without_partial_totals(self) -> None:
        self._write_meta(1, {"cost_cny": 1})
        self._write_meta(2, {"cost_cny": 2})
        from src.web import drama_insights

        original = drama_insights._read_json_object
        changed = False

        def mutate_after_first(path, **kwargs):
            nonlocal changed
            result = original(path, **kwargs)
            if path.name == "episode_01.meta.json" and not changed:
                changed = True
                (path.parent / "episode_02.meta.json").unlink()
            return result

        with patch.object(
            drama_insights,
            "_read_json_object",
            side_effect=mutate_after_first,
        ):
            data = collect_drama_insights("drama")

        self.assertEqual(data["episode_meta_cost"]["status"], "degraded")
        self.assertEqual(data["episode_meta_cost"]["episodes"], 0)
        self.assertEqual(data["episode_meta_cost"]["cost_cny"], 0.0)

    def test_episode_file_aba_uses_frozen_token(self) -> None:
        self._write_episode(
            1,
            {
                "target_duration_seconds": 60,
                "estimated_duration_seconds": 60,
                "ending_hook": {"type": "SAFE_HOOK"},
            },
        )
        from src.web import drama_insights

        original_read = drama_insights._read_workspace_file
        swapped = False

        def swap_before_open(path, **kwargs):
            nonlocal swapped
            if path.name == "episode_01.json" and not swapped:
                swapped = True
                original_path = path.with_suffix(".original")
                path.rename(original_path)
                path.write_text(
                    json.dumps(
                        {
                            "episode_no": 1,
                            "target_duration_seconds": 60,
                            "estimated_duration_seconds": 60,
                            "ending_hook": {"type": "OUTSIDE_HOOK"},
                        }
                    ),
                    encoding="utf-8",
                )
            return original_read(path, **kwargs)

        with patch.object(
            drama_insights,
            "_read_workspace_file",
            side_effect=swap_before_open,
        ):
            data = collect_drama_insights("drama")

        self.assertEqual(data["duration"]["status"], "degraded")
        self.assertEqual(data["duration"]["total"], 0)
        self.assertNotIn("OUTSIDE_HOOK", json.dumps(data, ensure_ascii=False))

    def test_same_inode_content_aba_is_rejected_by_frozen_hash(self) -> None:
        self._write_episode(
            1,
            {
                "target_duration_seconds": 60,
                "estimated_duration_seconds": 60,
                "ending_hook": {"type": "SAFE"},
            },
        )
        from src.web import drama_insights

        episode = self.root / "outputs" / "episodes" / "episode_01.json"
        files, invalid = drama_insights._matching_files(
            episode.parent, drama_insights._EPISODE_RE
        )
        self.assertEqual(invalid, 0)
        token = files[0][1]
        before = episode.stat()
        raw = episode.read_bytes()
        episode.write_bytes(raw.replace(b"SAFE", b"EVIL"))
        os.utime(
            episode,
            ns=(before.st_atime_ns, before.st_mtime_ns),
        )

        state, value = drama_insights._read_json_object(
            episode, expected_token=token
        )
        self.assertEqual(state, "invalid")
        self.assertIsNone(value)

    def test_episode_namespace_total_byte_budget_degrades_empty(self) -> None:
        self._write_episode(
            1,
            {
                "target_duration_seconds": 60,
                "estimated_duration_seconds": 60,
                "ending_hook": {"type": "SAFE"},
            },
        )
        from src.web import drama_insights

        with patch.object(
            drama_insights,
            "_MAX_EPISODE_NAMESPACE_BYTES",
            1,
        ):
            data = collect_drama_insights("drama")
        self.assertEqual(data["duration"]["status"], "degraded")
        self.assertEqual(data["duration"]["total"], 0)
        self.assertEqual(data["hook_types"], [])


if __name__ == "__main__":
    unittest.main()
