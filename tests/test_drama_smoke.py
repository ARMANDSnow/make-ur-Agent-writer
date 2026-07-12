"""Iteration 090 drama smoke orchestration tests."""

from __future__ import annotations

import io
import json
import os
import sys
from unittest.mock import patch

from src import drama_smoke
from tests._drama_base import DramaTestBase


class DramaSmokeTests(DramaTestBase):
    def test_default_mock_smoke_runs_five_jobs_exports_and_insights(self) -> None:
        result = drama_smoke.run_smoke("smoke", real_text=False, real_image=False, timeout_seconds=10)
        self.assertTrue(result["ok"])
        self.assertEqual([row["step"] for row in result["steps"]], [
            "drama-plan", "drama-hooks", "drama-storyboard", "drama-characters", "drama-review-assemble",
        ])
        self.assertEqual(set(result["exports"]), {"json", "md", "csv", "comfy"})
        self.assertTrue(all(row["bytes"] > 0 for row in result["exports"].values()))
        self.assertEqual(result["llm_calls"], 0)
        self.assertEqual(result["cost_cny"], 0.0)
        self.assertEqual(result["video_requests"], 0)

    def test_non_finite_budgets_are_rejected(self) -> None:
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.assertRaises(SystemExit):
                drama_smoke.run_smoke("bad_budget", budget_cny=value)

    def test_real_image_rejects_custom_draw_endpoint(self) -> None:
        with patch.dict(os.environ, {
            "CONFIRM_REAL_IMAGE_SMOKE": "可以跑生图",
            "AI_DRAW_ENDPOINT": "https://example.test/draw",
        }, clear=False), patch("src.drama_smoke.load_dotenv_if_available"), \
                patch("src.drama_smoke.redraw_character_reference") as redraw:
            with self.assertRaisesRegex(RuntimeError, "OpenAI-compatible"):
                drama_smoke.run_smoke("custom_endpoint", real_image=True, timeout_seconds=10)
        redraw.assert_not_called()

    def test_text_timeout_has_text_error_code(self) -> None:
        argv = ["drama_smoke", "--book", "timeout"]
        with patch.object(sys, "argv", argv), \
                patch("src.drama_smoke.run_smoke", side_effect=drama_smoke.DramaSmokeTimeout("text")), \
                patch("sys.stdout", new_callable=io.StringIO) as stdout:
            self.assertEqual(drama_smoke.main(), 1)
        self.assertEqual(json.loads(stdout.getvalue())["error_code"], "drama_text_timeout")


if __name__ == "__main__":
    import unittest

    unittest.main()
