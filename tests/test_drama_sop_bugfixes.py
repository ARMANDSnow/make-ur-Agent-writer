"""Cross-layer regressions from the full short-drama SOP user audit."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from src import character_designer, drama_reviewer, paths, storyboard_builder
from src.drama_schemas import character_paths, episode_paths
from src.web import jobs, routes
from tests._drama_base import DramaTestBase


class DramaSopBugfixTests(DramaTestBase):
    def test_all_wire_drama_mutations_require_json_and_explicit_intent(self) -> None:
        path = "/api/workspace/missing/drama/plan"
        status, _ct, body = routes.dispatch(
            "POST",
            path,
            b"{}",
            {"content-type": "text/plain", "host": "127.0.0.1:8765"},
        )
        self.assertEqual(status, 415, body.decode())

        status, _ct, body = routes.dispatch(
            "POST",
            path,
            b"{}",
            {"content-type": "application/json", "host": "127.0.0.1:8765"},
        )
        self.assertEqual(status, 403, body.decode())

        status, _ct, body = routes.dispatch(
            "POST",
            path,
            b"{}",
            {
                "content-type": "application/json",
                "x-drama-mutation-intent": "mutate-v1",
                "sec-fetch-site": "cross-site",
                "origin": "https://evil.example",
                "host": "127.0.0.1:8765",
            },
        )
        self.assertEqual(status, 403, body.decode())

    def test_wire_drama_mutation_accepts_same_origin_intent_then_reaches_handler(self) -> None:
        status, _ct, body = routes.dispatch(
            "POST",
            "/api/workspace/missing/drama/plan",
            b"{}",
            {
                "content-type": "application/json",
                "x-drama-mutation-intent": "mutate-v1",
                "sec-fetch-site": "same-origin",
                "origin": "http://127.0.0.1:8765",
                "host": "127.0.0.1:8765",
            },
        )
        self.assertEqual(status, 404, body.decode())

    def test_generic_run_cannot_start_a_drama_job(self) -> None:
        self._make_drama_workspace("guarded-run")
        with patch("src.web.routes.jobs.start_job") as start_job:
            for step in (
                "drama-plan",
                "drama-hooks",
                "drama-storyboard",
                "drama-characters",
                "drama-review-assemble",
                "drama-compose",
                "drama-video",
                "drama-local-demo",
            ):
                body = json.dumps({
                    "step": step,
                    "params": {
                        "episode_no": 1,
                        "confirm_real_text": True,
                        "budget_cny": 10,
                        "timeout_minutes": 10,
                    },
                }).encode()
                status, _ct, response = routes.dispatch(
                    "POST",
                    "/api/workspace/guarded-run/run",
                    body,
                    {
                        "content-type": "text/plain",
                        "sec-fetch-site": "cross-site",
                        "origin": "https://evil.example",
                    },
                )
                self.assertEqual(status, 400, (step, response.decode()))
        start_job.assert_not_called()

    def test_character_reference_rejects_symlinked_character_directory(self) -> None:
        self._make_drama_workspace("refs")
        refs = paths.WORKSPACE_DIR / "refs" / "data" / "character_refs"
        refs.mkdir(parents=True)
        with tempfile.TemporaryDirectory() as external_dir:
            external = Path(external_dir)
            (external / "portrait_neutral.png").write_bytes(b"outside")
            (refs / "c001").symlink_to(external, target_is_directory=True)
            status, _ct, body = routes.dispatch(
                "GET",
                "/api/workspace/refs/character-ref/c001/portrait_neutral.png",
            )
        self.assertIn(status, {400, 404}, body.decode())

    def test_text_attempt_ledger_rejects_symlinked_parent_and_oversize_source(self) -> None:
        self._make_drama_workspace("text-ledger")
        ledger_path = jobs._drama_text_attempt_path("text-ledger")
        ledger_path.parent.rmdir()
        with tempfile.TemporaryDirectory() as external_dir:
            external = Path(external_dir)
            ledger_path.parent.symlink_to(external, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "written safely"):
                jobs._save_drama_text_attempts(
                    "text-ledger", {"schema_version": 1, "attempts": {}}
                )
            self.assertFalse((external / ledger_path.name).exists())

        ledger_path.parent.unlink()
        ledger_path.parent.mkdir()
        ledger_path.write_bytes(b"{" + b" " * jobs.MAX_DRAMA_TEXT_LEDGER_BYTES + b"}")
        with self.assertRaisesRegex(ValueError, "unreadable"):
            jobs._load_drama_text_attempts("text-ledger")

    def test_mock_storyboard_retimes_every_advertised_duration_exactly(self) -> None:
        for duration in (30, 60, 90, 120):
            with self.subTest(duration=duration):
                name = f"duration-{duration}"
                self._make_drama_workspace(name, episode_duration_seconds=duration)
                self._write_setup(name, hook=True)
                board = storyboard_builder.run(name, mock=True)
                self.assertEqual(board["target_duration_seconds"], duration)
                self.assertEqual(sum(item["duration_seconds"] for item in board["shots"]), duration)

    def test_reviewer_rejects_large_duration_mismatch_without_model_call(self) -> None:
        self._make_drama_workspace("duration-review")
        self._write_setup("duration-review", hook=True)
        board = storyboard_builder.run("duration-review", mock=True)
        board["shots"][1]["duration_seconds"] = 1
        episode_paths("duration-review").storyboard_path.write_text(
            json.dumps(board, ensure_ascii=False), encoding="utf-8"
        )
        sheet = character_designer.run("duration-review", mock=True)
        sheet_path = character_paths("duration-review").sheet_path
        sheet_path.parent.mkdir(parents=True, exist_ok=True)
        sheet_path.write_text(json.dumps(sheet, ensure_ascii=False), encoding="utf-8")

        review = drama_reviewer.run("duration-review", mock=False)

        self.assertEqual(review["verdict"], "Reject")
        self.assertTrue(any(item.startswith("duration_delta:") for item in review["issues"]))

    def test_frontend_does_not_silently_fallback_episode_or_call_sample_a_movie(self) -> None:
        source = Path("src/web/static.py").read_text(encoding="utf-8")
        self.assertIn("集数必须是 1 到 100 的整数；未发送任何请求", source)
        self.assertIn("hydrateDramaEpisodeInput(episodeInput)", source)
        self.assertNotIn("下载成片", source)
        self.assertIn("下载 5 秒高光样片", source)
        self.assertIn(".badge.success", source)
        self.assertIn(".badge.danger", source)
        self.assertNotIn("border: 1px solid var(--line)", source)
        self.assertIn("beforeunload", source)
        self.assertIn("confirmDramaRegenerate", source)
        self.assertIn("associateFormLabels", source)
        self.assertIn("requestRealTextAuthorization", source)
        self.assertNotIn("window.prompt", source)
        self.assertIn("开始本地 A-F 演练", source)
        self.assertIn("markDramaDirty(pane)", source)
        self.assertIn("const targetEpisode = episodeNo()", source)
        self.assertIn('aria-label="镜头 \' + num + \' 景别"', source)
        self.assertIn("width: 44px; min-height: 44px", source)
        self.assertIn("button, .btn { min-height: 44px; }", source)
        self.assertIn("质检与交付", source)
        self.assertIn("本地全流程通过", source)
        self.assertIn("只展示服务端已保存状态", source)
        self.assertNotIn("QA / Exact delivery", source)
        self.assertNotIn('时间线 / QA', source)
        self.assertNotIn("escapeHtml(timeline.qa.acceptance_level", source)
        self.assertNotIn("typed edges", source)
        self.assertNotIn("durable state", source)
        template_source = Path("src/web/templates.py").read_text(encoding="utf-8")
        self.assertIn("本地 A-F 演练", template_source)
        self.assertIn("新建隔离验收项目", template_source)
        self.assertNotIn("此页不会生成媒体", template_source)

    def test_workspace_overview_does_not_claim_ready_before_review_assembly(self) -> None:
        self._make_drama_workspace("overview-not-ready")
        self._write_setup("overview-not-ready", hook=True)
        board = storyboard_builder.run("overview-not-ready", mock=True)
        board_path = episode_paths("overview-not-ready").storyboard_path
        board_path.parent.mkdir(parents=True, exist_ok=True)
        board_path.write_text(json.dumps(board, ensure_ascii=False), encoding="utf-8")
        character_designer.run("overview-not-ready", mock=True)

        routes._clear_overview_cache()
        overview = routes._workspace_overview("overview-not-ready")

        self.assertEqual(overview["readiness"]["status"], "warn")
        self.assertEqual(len(overview["drama_progress"]), 5)
        self.assertEqual(overview["drama_progress"]["station5"]["id"], "review")


if __name__ == "__main__":
    import unittest

    unittest.main()
