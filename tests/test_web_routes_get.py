"""iter 025: WebUI route dispatcher (pure functions, no HTTP server)."""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from src import paths
from src.plot_planner import chapter_plan_item_fingerprint, plan_fingerprint
from src.web import jobs
from src.web import routes
from src.web import templates
from src.web import workspace_meta
from src.web.workspace_ctx import use_workspace


def _stub_workspace(root: Path, name: str) -> Path:
    """Create a minimal workspace tree under ``root`` so route handlers
    return realistic JSON instead of 404."""

    ws = root / name
    (ws / "data").mkdir(parents=True)
    (ws / "outputs" / "debate").mkdir(parents=True)
    (ws / "outputs" / "drafts").mkdir(parents=True)
    (ws / "outputs" / "reviews").mkdir(parents=True)
    (ws / "logs").mkdir(parents=True)
    (ws / "小说txt").mkdir(parents=True)
    # chapter_manifest is enough to make collect_status report "split done"
    (ws / "data" / "chapter_manifest.json").write_text(
        json.dumps(
            [
                {
                    "chapter_id": f"{name}_ch001",
                    "volume_id": f"{name}_v1",
                    "chapter_index": 1,
                    "title": "t",
                    "source_file": "sample.txt",
                    "start_line": 1,
                    "end_line": 2,
                    "char_count": 100,
                }
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    meta = {
        "target": "outputs/drafts/chapter_01.md",
        "verdict": "Approve",
        "rewrite_count": 0,
        "rewrite_round": 0,
        "chinese_char_count": 4000,
        "needs_human_review": False,
        "polish_applied": False,
        "lint_issues": [],
        "agent_reviews": [
            {"agent_name": "PlotMaster", "verdict": "Approve", "score": 7, "issues": [], "suggestions": [], "comparison_checklist": []}
        ],
        "rewrite_suggestions": [{"section": "intro", "type": "rewrite", "guidance": "..."}],
    }
    (ws / "outputs" / "drafts" / "chapter_01.md").write_text(
        "# chapter 1\n\nmock draft", encoding="utf-8"
    )
    (ws / "outputs" / "drafts" / "chapter_01.meta.json").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8"
    )
    (ws / "outputs" / "reviews" / "chapter_01.review.json").write_text(
        json.dumps({"verdict": "Approve", "agent_reviews": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    (ws / "logs" / "llm_calls.jsonl").write_text(
        '{"task":"review","model":"mock","prompt_tokens":10,"response_tokens":5}\n',
        encoding="utf-8",
    )
    return ws


def _write_strict_plan(root: Path, name: str, chapters: int = 1) -> None:
    with use_workspace(name):
        from src import start_point

        start_point.set_start_point(f"{name}_ch001")
        start_fp = start_point.start_point_fingerprint()
    plan = {
        "target_chapters": chapters,
        "overall_arc": "arc",
        "start_chapter_id": f"{name}_ch001",
        "start_point_fingerprint": start_fp,
        "schema_version": 1,
        "chapters": [
            {
                "chapter_no": i,
                "title": f"第 {i} 章",
                "opening_scene": "开场",
                "key_events": ["事件一", "事件二"],
                "relationships_in_play": [],
                "ending_hook": "钩子",
                "target_chinese_chars": 4000,
                "plot_purpose": "用途",
            }
            for i in range(1, chapters + 1)
        ],
    }
    for item in plan["chapters"]:
        item["chapter_plan_item_fingerprint"] = chapter_plan_item_fingerprint(item)
    plan["plan_fingerprint"] = plan_fingerprint(plan)
    (root / name / "outputs" / "debate" / "chapter_plan.json").write_text(
        json.dumps(plan, ensure_ascii=False), encoding="utf-8"
    )


class RoutesGetTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._saved_ws_dir = paths.WORKSPACE_DIR
        self._saved_env = os.environ.get("WORKSPACE_NAME")
        os.environ.pop("WORKSPACE_NAME", None)
        root = Path(self._tmp.name)
        paths.WORKSPACE_DIR = root
        _stub_workspace(root, "alpha")
        _stub_workspace(root, "beta")

    def tearDown(self) -> None:
        paths.WORKSPACE_DIR = self._saved_ws_dir
        if self._saved_env is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._saved_env
        self._tmp.cleanup()

    def _get_json(self, path: str) -> tuple[int, dict]:
        status, ct, body = routes.dispatch("GET", path)
        self.assertIn("json", ct)
        return status, json.loads(body.decode("utf-8"))

    def test_library_lists_workspaces(self) -> None:
        status, _ct, body = routes.dispatch("GET", "/library")
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        self.assertIn("作品列表", html)
        self.assertIn('href="/trash"', html)
        self.assertLess(html.index("♻ 回收站"), html.index("⚙ 设置"))
        self.assertIn("/api/workspaces/overview", routes.static.JS_DASHBOARD)
        self.assertNotIn("iter 026", html)


    def test_trash_page_renders(self) -> None:
        status, _ct, body = routes.dispatch("GET", "/trash")
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        self.assertIn("已删除的作品", html)
        self.assertIn('id="trash-list"', html)
        self.assertIn('window.PAGE_KIND = "trash"', html)


    def test_api_preflight_reports_runtime_mode_without_settings_secrets(self) -> None:
        saved = os.environ.get("OPENAI_MODEL")
        os.environ["OPENAI_MODEL"] = "mock"
        try:
            status, data = self._get_json("/api/preflight")
        finally:
            if saved is None:
                os.environ.pop("OPENAI_MODEL", None)
            else:
                os.environ["OPENAI_MODEL"] = saved
        self.assertEqual(status, 200)
        self.assertEqual(data["model"], "mock")
        self.assertTrue(data["is_mock"])
        self.assertTrue(data["pricing_known"])
        self.assertFalse(data["real_ready"])
        self.assertNotIn("API_KEY", json.dumps(data))

    def test_api_preflight_blocks_real_model_without_trusted_pricing(self) -> None:
        with patch(
            "src.web.routes.get_model_config",
            return_value={"model": "openai/synthetic-unpriced-model"},
        ):
            status, data = self._get_json("/api/preflight")
        self.assertEqual(status, 200)
        self.assertFalse(data["is_mock"])
        self.assertFalse(data["pricing_known"])
        self.assertFalse(data["real_ready"])

    def test_workspace_legacy_url_301s_to_new_ia(self) -> None:
        """Iter 032: the iter 025 ``/workspace/<name>/`` URL still
        resolves but now 301-redirects to the new ``/w/<name>/``
        information architecture."""

        status, _ct, body = routes.dispatch("GET", "/workspace/alpha/")
        self.assertEqual(status, 301)
        # body carries the Location URL for the server's header sniffer.
        self.assertIn(b'data-redirect-to="/w/alpha/"', body)

    def test_workspace_overview_renders(self) -> None:
        """Iter 032: ``/w/<name>/`` is the new overview page — replaces
        the old all-in-one workspace page."""
        status, _ct, body = routes.dispatch("GET", "/w/alpha/")
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        self.assertIn("data-sidebar-toggle", html)
        self.assertIn("sidebar-overlay", html)
        self.assertIn("data-topbar-menu-toggle", html)

        status, _ct, body = routes.dispatch("GET", "/w/alpha/")
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        self.assertIn("alpha", html)
        # sidebar lists the workspace and the new sections
        self.assertIn("续写", html)
        self.assertIn("计划", html)
        self.assertIn("章节", html)
        self.assertIn("内容检查", html)
        self.assertIn("任务", html)
        # overview shows status + next-action shell
        self.assertIn("overview-summary", html)
        self.assertIn("overview-next-action", html)
        self.assertIn("overview-blockers", html)
        self.assertIn("delete-workspace-btn", html)
        self.assertIn('id="toast-stack"', html)

    def test_workspace_continue_renders_cockpit_forms(self) -> None:
        """Iter 032: the continue page preserves the iter 026 cockpit
        forms (start-point-form, plan-form, write-book-form) so the
        end-to-end smoke flow keeps working."""

        status, _ct, body = routes.dispatch("GET", "/w/alpha/continue")
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        self.assertIn("批量续写", html)
        self.assertIn("设置批量续写", html)
        self.assertIn("重新生成并覆盖计划", html)
        self.assertIn('id="plan-submit" class="btn btn-paid"', html)
        self.assertIn("start-point-form", html)
        self.assertIn("write-book-form", html)
        self.assertIn("plan-form", html)
        self.assertIn("write-preset-toggle", html)
        self.assertIn('name="tier"', html)
        self.assertIn("本次可用额度（人民币）", html)
        self.assertIn("高级参数", html)
        self.assertNotIn("draft-once-dev", html)


    def test_workspace_plan_page_renders(self) -> None:
        status, _ct, body = routes.dispatch("GET", "/w/alpha/plan")
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        self.assertIn('data-plan-pane="chapters"', html)
        self.assertIn('data-plan-pane="outline"', html)
        self.assertIn('data-plan-pane="decisions"', html)
        self.assertIn('<span class="sidebar-item active" aria-current="page"><span><span class="dot"></span> 故事规划</span></span>', html)
        self.assertIn('window.PAGE_KIND = "plan"', html)

    def test_workspace_chapters_renders(self) -> None:
        status, _ct, body = routes.dispatch("GET", "/w/alpha/chapters")
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        self.assertIn("chapters-table", html)
        self.assertIn("chapter-search", html)

    def test_workspace_chapter_detail_renders(self) -> None:
        status, _ct, body = routes.dispatch("GET", "/w/alpha/chapter/1")
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        self.assertIn("第 1 章", html)
        for tab in ("body", "edit", "review", "lint", "style", "advisor", "history"):
            self.assertIn(f'data-tab="{tab}"', html)
        # JS gets the chapter number via window.CHAPTER_NO
        self.assertIn("window.CHAPTER_NO = 1", html)

    def test_workspace_chapter_detail_bad_chapter(self) -> None:
        status, _ct, _body = routes.dispatch("GET", "/w/alpha/chapter/99999")
        self.assertEqual(status, 400)

    def test_workspace_reviews_page(self) -> None:
        status, _ct, body = routes.dispatch("GET", "/w/alpha/reviews")
        self.assertEqual(status, 200)
        self.assertIn(b"reviews-panel", body)

    def test_workspace_insights_page(self) -> None:
        status, _ct, body = routes.dispatch("GET", "/w/alpha/insights")
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        self.assertIn("insights-cost", html)
        self.assertIn("insights-cache", html)
        self.assertIn("insights-subscores", html)

    def test_workspace_jobs_page(self) -> None:
        status, _ct, body = routes.dispatch("GET", "/w/alpha/jobs")
        self.assertEqual(status, 200)
        self.assertIn(b"jobs-recent", body)
        self.assertIn(b"jobs-logs", body)

    def test_workspace_jobs_page_fails_closed_for_corrupt_type(self) -> None:
        meta_path = paths.WORKSPACE_DIR / "alpha" / "data" / "workspace.json"
        meta_path.write_text('{"type":"mystery"}', encoding="utf-8")
        status, _ct, body = routes.dispatch("GET", "/w/alpha/jobs")
        self.assertEqual(status, 404)
        self.assertNotIn(b'window.PAGE_KIND = "jobs"', body)

    def test_workspace_new_ia_404(self) -> None:
        for path in (
            "/w/__missing__/",
            "/w/__missing__/continue",
            "/w/__missing__/chapters",
            "/w/__missing__/chapter/1",
        ):
            status, _ct, _body = routes.dispatch("GET", path)
            self.assertEqual(status, 404, f"path {path} should 404")

    def test_workspace_page_404(self) -> None:
        status, _ct, _body = routes.dispatch("GET", "/workspace/__missing__/")
        self.assertEqual(status, 404)

    def test_api_workspaces(self) -> None:
        status, data = self._get_json("/api/workspaces")
        self.assertEqual(status, 200)
        self.assertEqual(sorted(data["workspaces"]), ["alpha", "beta"])

    def test_api_workspaces_overview_blocked_and_ready_shapes(self) -> None:
        _write_strict_plan(Path(self._tmp.name), "alpha", chapters=1)
        status, data = self._get_json("/api/workspaces/overview")
        self.assertEqual(status, 200)
        by_name = {item["name"]: item for item in data["workspaces"]}
        self.assertEqual(by_name["alpha"]["type"], "novel")
        self.assertIn(by_name["alpha"]["readiness"]["status"], {"ready", "warn", "blocked"})
        self.assertEqual(by_name["alpha"]["chapter_count"], 1)
        self.assertEqual(by_name["alpha"]["draft_count"], 1)
        self.assertIn("plan", by_name["alpha"])
        self.assertIn("recent_job", by_name["alpha"])
        self.assertRegex(by_name["alpha"]["updated_at"], r"^\d{4}-\d{2}-\d{2}T")
        self.assertNotIn("path", by_name["alpha"])
        self.assertEqual(by_name["beta"]["readiness"]["status"], "blocked")
        self.assertIn("start_point_missing", by_name["beta"]["readiness"]["blockers"])



    def test_overview_cache_key_tracks_legacy_seed_upload_without_following_links(self) -> None:
        raw = paths.WORKSPACE_DIR / "beta" / "小说txt"
        key0 = routes._overview_cache_key(["beta"])
        seed = raw / "seed.txt"
        seed.write_text("placeholder", encoding="utf-8")
        key1 = routes._overview_cache_key(["beta"])
        self.assertNotEqual(key0, key1)

        upload = raw / "upload.txt"
        upload.symlink_to(paths.WORKSPACE_DIR / "does-not-exist")
        key2 = routes._overview_cache_key(["beta"])
        self.assertNotEqual(key1, key2)
        # A broken symlink is represented by its own directory entry.  The
        # cache probe must not follow it or collapse it into "missing".
        self.assertIn("entry", repr(key2))








    def test_api_workspaces_overview_bad_plan_blocks_only_that_workspace(self) -> None:
        _write_strict_plan(Path(self._tmp.name), "alpha", chapters=1)
        (Path(self._tmp.name) / "beta" / "outputs" / "debate" / "chapter_plan.json").write_text(
            "{not-json", encoding="utf-8"
        )
        status, data = self._get_json("/api/workspaces/overview")
        self.assertEqual(status, 200)
        by_name = {item["name"]: item for item in data["workspaces"]}
        self.assertIn(by_name["alpha"]["readiness"]["status"], {"ready", "warn", "blocked"})
        self.assertEqual(by_name["beta"]["readiness"]["status"], "blocked")
        self.assertIn("error", by_name["beta"]["plan"])
        # iter062: the plan read error is now a friendly card (code=bad_json),
        # and the raw Python exception type name never reaches the client.
        plan_err = by_name["beta"]["plan"]["error"]
        self.assertIsInstance(plan_err, dict)
        self.assertEqual(plan_err.get("code"), "bad_json")
        self.assertNotIn("JSONDecodeError", json.dumps(data, ensure_ascii=False))
        # iter059 #4: a corrupt chapter_plan.json now surfaces a clean
        # chapter_plan_invalid blocker instead of leaking the raw
        # readiness_error:JSONDecodeError. Still blocks only beta, not alpha.
        beta_blockers = by_name["beta"]["readiness"]["blockers"]
        self.assertIn("chapter_plan_invalid", beta_blockers)
        self.assertFalse(
            any("readiness_error" in item for item in beta_blockers),
            beta_blockers,
        )

    def test_api_status_404_for_unknown(self) -> None:
        status, data = self._get_json("/api/workspace/nope/status")
        self.assertEqual(status, 404)
        self.assertIn("not found", data["error"])

    def test_api_manifest_returns_chapters(self) -> None:
        status, data = self._get_json("/api/workspace/alpha/manifest")
        self.assertEqual(status, 200)
        self.assertEqual(data["chapters"][0]["chapter_id"], "alpha_ch001")

    def test_symlink_workspace_is_hidden_and_never_read(self) -> None:
        with tempfile.TemporaryDirectory() as outside_tmp:
            outside = Path(outside_tmp)
            marker = outside / "data" / "chapter_manifest.json"
            marker.parent.mkdir()
            marker.write_text('[{"chapter_id":"external-marker"}]', encoding="utf-8")
            (paths.WORKSPACE_DIR / "linked").symlink_to(outside, target_is_directory=True)

            status, data = self._get_json("/api/workspace/linked/manifest")
            self.assertEqual(status, 404)
            self.assertNotIn("external-marker", json.dumps(data))
            status, _ct, body = routes.dispatch("GET", "/w/linked/")
            self.assertEqual(status, 404)
            self.assertNotIn(b"external-marker", body)
            status, data = self._get_json("/api/workspaces")
            self.assertNotIn("linked", data["workspaces"])

    def test_symlink_canonical_subdirs_are_rejected_before_read(self) -> None:
        with tempfile.TemporaryDirectory() as outside_tmp:
            outside = Path(outside_tmp)
            (outside / "chapter_manifest.json").write_text(
                '[{"chapter_id":"external-marker"}]', encoding="utf-8"
            )
            alpha = paths.WORKSPACE_DIR / "alpha"
            original_data = alpha / "data"
            saved_data = alpha / "data.safe"
            original_data.rename(saved_data)
            original_data.symlink_to(outside, target_is_directory=True)
            try:
                status, data = self._get_json("/api/workspace/alpha/manifest")
                self.assertEqual(status, 404)
                self.assertNotIn("external-marker", json.dumps(data))
                status, data = self._get_json("/api/workspaces")
                self.assertNotIn("alpha", data["workspaces"])
            finally:
                original_data.unlink()
                saved_data.rename(original_data)

            outside_outputs = outside / "outputs"
            outside_outputs.mkdir()
            (outside_outputs / "drafts").mkdir()
            (outside_outputs / "drafts" / "chapter_01.md").write_text(
                "external-marker", encoding="utf-8"
            )
            original_outputs = alpha / "outputs"
            saved_outputs = alpha / "outputs.safe"
            original_outputs.rename(saved_outputs)
            original_outputs.symlink_to(outside_outputs, target_is_directory=True)
            try:
                status, data = self._get_json("/api/workspace/alpha/drafts")
                self.assertEqual(status, 404)
                self.assertNotIn("external-marker", json.dumps(data))
            finally:
                original_outputs.unlink()
                saved_outputs.rename(original_outputs)

    def test_api_start_point_can_be_set_and_rejects_invalid_id(self) -> None:
        status, _ct, body = routes.dispatch(
            "POST",
            "/api/workspace/alpha/start-point",
            json.dumps({"start_point": "alpha_ch001"}).encode("utf-8"),
        )
        self.assertEqual(status, 200, body.decode("utf-8"))
        data = json.loads(body)
        self.assertEqual(data["start_point"]["start_chapter_id"], "alpha_ch001")

        status, _ct, body = routes.dispatch(
            "POST",
            "/api/workspace/alpha/start-point",
            json.dumps({"start_point": "missing_chapter"}).encode("utf-8"),
        )
        self.assertEqual(status, 400)
        self.assertIn("matches neither", json.loads(body)["error"])

    def test_api_reviews_full_shape(self) -> None:
        status, data = self._get_json("/api/workspace/alpha/reviews")
        self.assertEqual(status, 200)
        self.assertEqual(data["stats"]["total"], 1)
        self.assertEqual(data["stats"]["accepted"], 1)
        self.assertEqual(data["stats"]["advisor_suggestions_total"], 1)
        # full agent_reviews preserved
        self.assertEqual(data["chapters"][0]["agent_reviews"][0]["agent_name"], "PlotMaster")

    def test_api_workspace_plan_returns_aggregates(self) -> None:
        status, data = self._get_json("/api/workspace/alpha/plan")
        self.assertEqual(status, 200)
        for key in ("plan", "outline_md", "decisions", "draft_chapters"):
            self.assertIn(key, data)

    def test_api_insights_returns_aggregates(self) -> None:
        status, data = self._get_json("/api/workspace/alpha/insights")
        self.assertEqual(status, 200)
        for key in ("cost_by_chapter", "cache_by_model", "subscores"):
            self.assertIn(key, data)

    def test_api_drafts_list_and_preview_are_read_only(self) -> None:
        status, data = self._get_json("/api/workspace/alpha/drafts")
        self.assertEqual(status, 200)
        self.assertEqual(data["drafts"][0]["chapter"], 1)
        self.assertEqual(data["drafts"][0]["variant"], "final")
        self.assertEqual(data["drafts"][0]["verdict"], "Approve")

        status, data = self._get_json("/api/workspace/alpha/draft/1")
        self.assertEqual(status, 200)
        self.assertEqual(data["variant"], "final")
        self.assertIn("mock draft", data["content"])
        self.assertEqual(data["review"]["verdict"], "Approve")
        # iter076（codex 低风险 + 审查 B L1）：path 投影必须是 workspace 相对路径，
        # 且在 use_workspace 块内计算（否则跨书浏览时绝对路径泄露复活）。
        self.assertEqual(data["path"], "outputs/drafts/chapter_01.md")
        # 列表端同口径
        status, data = self._get_json("/api/workspace/alpha/drafts")
        self.assertEqual(data["drafts"][0]["path"], "outputs/drafts/chapter_01.md")

        status, data = self._get_json("/api/workspace/alpha/draft/99999")
        self.assertEqual(status, 400)
        self.assertIn("out of range", data["error"])

    def test_api_partial_draft_variant_is_readable_and_listed(self) -> None:
        drafts = Path(self._tmp.name) / "alpha" / "outputs" / "drafts"
        (drafts / "chapter_02.partial.md").write_text("partial body", encoding="utf-8")
        (drafts / "chapter_02.failure.json").write_text(
            json.dumps(
                {
                    "attempt": 1,
                    "stage": "write",
                    "last_error": "RuntimeError: stream interrupted",
                    "draft_sha256": "abc",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        status, data = self._get_json("/api/workspace/alpha/drafts")
        self.assertEqual(status, 200)
        partial = [item for item in data["drafts"] if item["variant"] == "partial"][0]
        self.assertEqual(partial["chapter"], 2)
        self.assertEqual(partial["verdict"], "failure")
        self.assertEqual(partial["failure_stage"], "write")

        status, data = self._get_json("/api/workspace/alpha/draft/2?variant=partial")
        self.assertEqual(status, 200)
        self.assertEqual(data["variant"], "partial")
        self.assertEqual(data["content"], "partial body")
        self.assertEqual(data["meta"]["stage"], "write")

        status, data = self._get_json("/api/workspace/alpha/draft/2?variant=unknown")
        self.assertEqual(status, 400)
        self.assertIn("variant", data["error"])

    def test_static_js_surfaces_blocked_reason_and_partial_link(self) -> None:
        js = routes.static.JS_DASHBOARD
        self.assertIn("function jobBlockedDetail", js)
        self.assertIn("function jobFailureLine", js)
        self.assertIn("result_summary.partial", js)
        self.assertIn("variant=partial", js)
        self.assertIn("已保留临时草稿", js)

    def test_api_recent_jobs_reads_persisted_jsonl(self) -> None:
        job = {
            "job_id": "a" * 32,
            "workspace": "alpha",
            "step": "write-book",
            "status": "succeeded",
            "started_at": 1.0,
            "finished_at": 2.0,
        }
        (Path(self._tmp.name) / "alpha" / "logs" / "web_jobs.jsonl").write_text(
            json.dumps(job) + "\n", encoding="utf-8"
        )
        status, data = self._get_json("/api/workspace/alpha/jobs/recent?n=5")
        self.assertEqual(status, 200)
        self.assertEqual(data["jobs"][0]["job_id"], "a" * 32)
        self.assertEqual(data["jobs"][0]["status"], "succeeded")

    def test_api_recent_jobs_hides_giant_integer_parser_failure(self) -> None:
        log = Path(self._tmp.name) / "alpha" / "logs" / "web_jobs.jsonl"
        log.write_bytes(b'{"progress":' + (b"9" * 5000) + b"}\n")

        status, data = self._get_json("/api/workspace/alpha/jobs/recent?n=5")

        self.assertEqual(status, 200)
        self.assertEqual(data["jobs"], [])
        rendered = json.dumps(data, ensure_ascii=False)
        self.assertNotIn("digits", rendered)
        self.assertNotIn("set_int_max_str_digits", rendered)

    def test_api_logs_tail(self) -> None:
        status, data = self._get_json("/api/workspace/alpha/logs/tail?n=10")
        self.assertEqual(status, 200)
        self.assertEqual(len(data["lines"]), 1)
        self.assertEqual(data["lines"][0]["task"], "review")
        self.assertEqual(
            set(data["lines"][0]),
            {"task", "model", "prompt_tokens", "response_tokens"},
        )




    def test_api_cost_runs(self) -> None:
        status, data = self._get_json("/api/workspace/alpha/cost")
        self.assertEqual(status, 200)
        self.assertIn("chapters", data)

    def test_api_readiness_returns_json(self) -> None:
        status, data = self._get_json("/api/workspace/alpha/readiness?chapters=1&resume_from=1")
        self.assertEqual(status, 200)
        self.assertIn(data["status"], {"ready", "warn", "blocked"})
        self.assertIn("recommended_commands", data)
        self.assertTrue(
            any("--book alpha" in command for command in data["recommended_commands"]),
            data["recommended_commands"],
        )

    def test_invalid_workspace_name_400(self) -> None:
        status, data = self._get_json("/api/workspace/..%2Fescape/status")
        # urlsplit hands ``..%2Fescape`` straight through; our regex rejects /
        # because of [^/]+; the % escape stays literal and fails the name re.
        self.assertIn(status, (400, 404))
        self.assertIn("error", data)

    def test_unknown_api_path_404_json(self) -> None:
        status, ct, body = routes.dispatch("GET", "/api/nothing")
        self.assertEqual(status, 404)
        self.assertIn("json", ct)
        self.assertIn("error", json.loads(body))

    def test_unknown_html_path_404(self) -> None:
        status, ct, _body = routes.dispatch("GET", "/no-such-thing")
        self.assertEqual(status, 404)
        self.assertIn("html", ct)

    def test_static_css_served(self) -> None:
        status, ct, body = routes.dispatch("GET", "/static/app.css")
        self.assertEqual(status, 200)
        self.assertIn("text/css", ct)
        self.assertIn(b"body", body)

    def test_static_js_served(self) -> None:
        status, ct, body = routes.dispatch("GET", "/static/app.js")
        self.assertEqual(status, 200)
        self.assertIn("javascript", ct)
        self.assertIn(b"fetch", body)
        js = body.decode("utf-8")
        self.assertIn("loadTabPanel", js)
        self.assertNotIn("loadSecondaryPanels", js)
        self.assertIn("scheduleReadiness", js)
        self.assertIn("writeBookJobRunning", js)
        self.assertIn("readinessRequestSeq", js)
        self.assertIn("submit.disabled = writeBookJobRunning || data.status === 'blocked'", js)
        self.assertIn("readinessTimer = null", js)

    def test_static_js_iter062_error_and_nav(self) -> None:
        """iter062: friendly error cards, fetch classification, global
        boundary, workbench step rail — and no bare traceback dumps left."""
        status, _ct, body = routes.dispatch("GET", "/static/app.js")
        self.assertEqual(status, 200)
        js = body.decode("utf-8")
        self.assertIn("renderErrorCard", js)
        self.assertIn("_normalizeErrorCard", js)
        self.assertIn("FRONT_ERROR_CATALOG", js)
        self.assertIn("unhandledrejection", js)
        self.assertIn("readinessReasonText", js)
        self.assertIn("renderStepbar", js)
        self.assertIn("workbench-stepbar", js)
        # iter026 locked expression must survive the readiness rewrite
        self.assertIn("submit.disabled = writeBookJobRunning || data.status === 'blocked'", js)
        # the bare "alert error + raw err.message" dump pattern is gone
        self.assertNotIn("escapeHtml(err.message)", js)
        # iter063 A1/A2: terminal job failures render a friendly card; error
        # toasts prefer the card title.
        self.assertIn("renderJobFailureCard", js)
        self.assertIn("failure_reason", js)
        self.assertIn("模型响应超时，结果未确认", js)
        self.assertIn("function errTitle", js)
        # iter063 Part C: CTA_ACTIONS is derived from the injected catalog, not a
        # hardcoded literal (outline_stale etc. now come from window.READINESS_CATALOG).
        self.assertIn("window.READINESS_CATALOG", js)
        # the raw "reason · error" failure line is no longer dumped verbatim.
        self.assertNotIn("jobFailureLine(job).slice(0, 80)", js)

    def test_static_wizard_js_has_error_card(self) -> None:
        status, _ct, body = routes.dispatch("GET", "/static/wizard.js")
        self.assertEqual(status, 200)
        js = body.decode("utf-8")
        self.assertIn("renderErrorCard", js)
        self.assertNotIn("escapeHtml(String(err))", js)

    def test_static_css_iter062(self) -> None:
        status, _ct, body = routes.dispatch("GET", "/static/app.css")
        self.assertEqual(status, 200)
        css = body.decode("utf-8")
        for sel in (".error-card", ".stepbar", ".home-btn"):
            self.assertIn(sel, css)

    def test_shell_has_topbar_home_button(self) -> None:
        status, _ct, body = routes.dispatch("GET", "/library")
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        # iter070: ⌂ now goes to the landing home (/), not the bookshelf, and is
        # a leave-guard exit. The bookshelf stays reachable via the brand below.
        self.assertIn('class="btn btn-icon home-btn" href="/" data-leave-guard', html)
        self.assertIn('<span class="here" aria-current="page">书架</span>', html)


    def test_iter070_library_populated_shelf_has_no_epub_copy(self) -> None:
        """iter070/iter071 (codex F4): this route runs with alpha/beta fixtures,
        so `names` is non-empty and the empty-shelf hint never renders — it only
        guards against an 'epub' assumption leaking onto a POPULATED shelf. The
        actual empty-shelf copy is exercised by the unit test below."""
        status, _ct, body = routes.dispatch("GET", "/library")
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        self.assertNotIn("epub", html)


    def test_iter070_workspace_shell_marks_leave_guard_exits(self) -> None:
        """iter070: ⌂, the sidebar brand, and the first breadcrumb crumb are the
        in-app 'leave this workspace' exits tagged for the leave-guard."""
        status, _ct, body = routes.dispatch("GET", "/w/alpha/")
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        self.assertIn('class="btn btn-icon home-btn" href="/" data-leave-guard', html)
        self.assertIn('class="brand" href="/library" data-leave-guard', html)
        self.assertIn('<a href="/library" data-leave-guard>', html)  # first crumb


    def test_iter071_topbar_actions_carry_leave_guard(self) -> None:
        """iter071 (codex F1): 回收站/设置/新建 also LEAVE the workspace, so on a
        workspace page they must carry data-leave-guard like ⌂/brand/first-crumb,
        otherwise a running job is abandoned silently when exiting via them."""
        status, _ct, body = routes.dispatch("GET", "/w/alpha/")
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        self.assertIn('href="/trash" data-leave-guard', html)
        self.assertIn('href="/settings" data-leave-guard', html)
        self.assertIn('href="/wizard" data-leave-guard', html)

    def test_iter071_static_js_leave_guard_uses_active_endpoint_and_focuses(self) -> None:
        """iter071 (codex F2 + F3): the guard checks /jobs/active (untruncated
        in-memory source) instead of /jobs/recent?n=10, and the modal moves focus
        to the safe 留在本页 button. iter072 (#6): the focus now flows through the
        shared mountModal helper via initialFocus: stayBtn."""
        status, _ct, body = routes.dispatch("GET", "/static/app.js")
        self.assertEqual(status, 200)
        js = body.decode("utf-8")
        self.assertIn('wsUrl("/jobs/active")', js)
        self.assertNotIn('wsUrl("/jobs/recent?n=10")', js)  # old truncatable source gone
        # iter073 (codex E): the call gained an onClose arg + multi-line form, so
        # assert the focus intent (initialFocus: stayBtn) rather than the exact
        # one-line signature.
        self.assertIn("initialFocus: stayBtn", js)

    def test_iter071_api_active_jobs_endpoint(self) -> None:
        """iter071 (codex F2): /jobs/active returns the live pending/running jobs
        from the in-memory pool, untruncated — a just-enqueued pending job
        (started_at=None) is always reported."""
        jobs.reset_for_tests()
        try:
            with jobs._JOBS_LOCK:
                jobs._JOBS["a" * 32] = {
                    "job_id": "a" * 32,
                    "workspace": "alpha",
                    "step": "write-book",
                    "status": "pending",
                    "started_at": None,
                }
            status, data = self._get_json("/api/workspace/alpha/jobs/active")
            self.assertEqual(status, 200)
            self.assertEqual([j["job_id"] for j in data["jobs"]], ["a" * 32])
            self.assertEqual(data["jobs"][0]["status"], "pending")
        finally:
            jobs.reset_for_tests()

    def test_iter071_modal_localizes_step_names(self) -> None:
        """iter071 (codex F5): the leave-guard modal must show Chinese step names
        (续写正文…), never raw ids like write-book, via the stepLabel() helper that
        covers every jobs.py STEP_HANDLERS key."""
        status, _ct, body = routes.dispatch("GET", "/static/app.js")
        self.assertEqual(status, 200)
        js = body.decode("utf-8")
        self.assertIn("function stepLabel", js)
        self.assertIn('"write-book": "续写正文"', js)
        self.assertIn("stepLabel(j.step)", js)  # modal renders via the localizer
        self.assertNotIn('return j.step || "任务"', js)  # raw-id path removed
        # every known backend step has a Chinese label (no raw id can leak)
        for step in jobs.STEP_HANDLERS:
            self.assertIn(f'"{step}":', js)

    def test_iter071_modal_footer_is_equal_width_and_labels_short(self) -> None:
        """iter071 (codex F6): the 3-way footer uses modal-footer-equal (equal,
        single-line buttons) and short labels, replacing the ragged content-sized
        buttons that wrapped at different points."""
        _s, _c, jbody = routes.dispatch("GET", "/static/app.js")
        js = jbody.decode("utf-8")
        self.assertIn("modal-footer modal-footer-equal", js)
        self.assertIn("取消并离开", js)
        self.assertNotIn("取消任务并离开", js)  # long label shortened
        self.assertNotIn("（后台继续）", js)  # caveat moved to body copy
        _s2, _c2, cbody = routes.dispatch("GET", "/static/app.css")
        css = cbody.decode("utf-8")
        self.assertIn(".modal-footer-equal .btn", css)
        self.assertIn("flex: 1 1 0", css)


    def test_iter072_sidebar_switch_workspace_carries_leave_guard(self) -> None:
        """iter072 (#1): switching to *another* workspace leaves the current one,
        so non-active sidebar items must carry data-leave-guard. The active item
        just re-opens the current overview (same context) and stays unguarded."""
        html = templates._sidebar(["alpha", "beta"], active_workspace="alpha")
        # non-active workspace → guarded
        self.assertIn('href="/w/beta/" data-leave-guard>', html)
        # active shelf item stays unguarded; section navigation is guarded so
        # an unsaved chapter edit gets the three-choice leave dialog.
        self.assertIn('class="sidebar-item active" href="/w/alpha/">', html)
        self.assertIn('class="sidebar-item" href="/w/alpha/" data-leave-guard>', html)

    def test_iter072_active_endpoint_excludes_internal_fields(self) -> None:
        """iter072 (#4): /jobs/active is projected through public_job_view, so the
        user's POST params + internal diagnostics never leak off-box."""
        jobs.reset_for_tests()
        try:
            with jobs._JOBS_LOCK:
                jobs._JOBS["a" * 32] = {
                    "job_id": "a" * 32,
                    "workspace": "alpha",
                    "step": "write-book",
                    "params": {"secret": "do-not-leak"},
                    "status": "running",
                    "started_at": 10.0,
                    "trace_id": "tid",
                    "result_summary": {"x": 1},
                    "cancel_requested": False,
                }
            status, data = self._get_json("/api/workspace/alpha/jobs/active")
            self.assertEqual(status, 200)
            job = data["jobs"][0]
            self.assertEqual(job["job_id"], "a" * 32)
            self.assertEqual(job["status"], "running")
            self.assertNotIn("params", job)
            self.assertNotIn("trace_id", job)
            self.assertNotIn("result_summary", job)
            self.assertNotIn("cancel_requested", job)
        finally:
            jobs.reset_for_tests()

    def test_iter072_static_js_residual_fixes(self) -> None:
        """iter072: destination-aware leave label, shared mountModal focus-trap,
        clipboard fallback, and no leaked CLI command."""
        status, _ct, body = routes.dispatch("GET", "/static/app.js")
        self.assertEqual(status, 200)
        js = body.decode("utf-8")
        # #2 destination-aware label replaces the binary 回首页/去书架 split
        self.assertIn("function leaveDestinationLabel", js)
        self.assertIn("去回收站", js)
        self.assertIn("去设置", js)
        self.assertIn("切到《", js)
        self.assertNotIn('href === "/" ? "回首页" : "去书架"', js)
        # #6 shared focus-trap helper applied to the modals
        self.assertIn("function mountModal", js)
        self.assertIn("previousActive.focus()", js)
        self.assertIn("_activeModalTeardown", js)
        # #7 clipboard non-secure-context fallback
        self.assertIn("function copyText", js)
        self.assertIn('document.execCommand("copy")', js)
        # #8 no raw CLI command leaked to web users
        self.assertNotIn("debate（--force）", js)

    def test_static_js_includes_lint_jump_helpers(self) -> None:
        status, _ct, body = routes.dispatch("GET", "/static/app.js")
        self.assertEqual(status, 200)
        js = body.decode("utf-8")
        self.assertIn("jumpToParagraph", js)
        self.assertIn("data-jump-line", js)
        self.assertIn("_extractIssueLine", js)
        self.assertIn("issue && issue.line", js)
        self.assertIn("jump-highlight", js)
        self.assertIn('data-line="', js)
        self.assertIn("split(/\\n/)", js)

    def test_static_js_includes_toast_helper(self) -> None:
        status, _ct, body = routes.dispatch("GET", "/static/app.js")
        self.assertEqual(status, 200)
        js = body.decode("utf-8")
        self.assertIn("function showToast", js)
        self.assertIn("toast-dismiss", js)
        self.assertIn("toast-stack", js)

    def test_static_js_has_array_isarray_guards(self) -> None:
        """A2 - Plan renderer must not blow up on malformed-but-truthy JSON."""
        status, _ct, body = routes.dispatch("GET", "/static/app.js")
        self.assertEqual(status, 200)
        js = body.decode("utf-8")
        self.assertGreaterEqual(js.count("Array.isArray("), 6)
        self.assertIn("Array.isArray(draftChapters)", js)

    def test_static_js_has_tab_whitelist(self) -> None:
        """A3 - bindHashTabs must filter against a whitelist."""
        status, _ct, body = routes.dispatch("GET", "/static/app.js")
        self.assertEqual(status, 200)
        js = body.decode("utf-8")
        self.assertIn("_ALLOWED_TAB_KEYS", js)
        for kw in (
            "body",
            "review",
            "lint",
            "advisor",
            "history",
            "chapters",
            "outline",
            "decisions",
        ):
            self.assertIn(f'"{kw}"', js)


    def test_static_js_load_tab_panel_is_async(self) -> None:
        status, _ct, body = routes.dispatch("GET", "/static/app.js")
        self.assertEqual(status, 200)
        js = body.decode("utf-8")
        self.assertIn("async function loadTabPanel", js)
        # iter062: non-JSON responses are now surfaced via the shared fetch
        # wrapper's bad_json card instead of an inline "not valid JSON" string.
        self.assertIn("bad_json", js)

    def test_static_js_has_pending_toast_cleanup(self) -> None:
        status, _ct, body = routes.dispatch("GET", "/static/app.js")
        self.assertEqual(status, 200)
        js = body.decode("utf-8")
        self.assertIn("setPendingToastAndNavigate", js)
        self.assertIn('sessionStorage.removeItem("__pending_toast")', js)
        self.assertIn('msg: "已将《" + name + "》移到回收站"', js)

    def test_static_assets_have_mobile_drawer_hooks(self) -> None:
        status, _ct, body = routes.dispatch("GET", "/static/app.css")
        self.assertEqual(status, 200)
        css = body.decode("utf-8")
        self.assertIn(".sidebar.open", css)
        self.assertIn(".sidebar-overlay.open", css)
        self.assertIn(".topbar-actions.open", css)
        self.assertIn(".table-scroll", css)

        status, _ct, body = routes.dispatch("GET", "/static/app.js")
        self.assertEqual(status, 200)
        js = body.decode("utf-8")
        self.assertIn("function initShellControls", js)
        self.assertIn("data-sidebar-toggle", js)
        self.assertIn("data-topbar-menu-toggle", js)
        self.assertIn("function tableScroll", js)


    def test_cjk_workspace_url_decoded(self) -> None:
        """Iter 025 code-review #8: percent-encoded CJK in path must
        match the on-disk workspace name after URL-decoding."""
        _stub_workspace(Path(self._tmp.name), "龙族")
        # urllib's quote of '龙族' = %E9%BE%99%E6%97%8F
        status, ct, body = routes.dispatch(
            "GET", "/api/workspace/%E9%BE%99%E6%97%8F/manifest"
        )
        self.assertEqual(status, 200, body.decode("utf-8"))
        self.assertIn("json", ct)

    def test_legacy_workspace_rejected(self) -> None:
        """Iter 025 code-review #5: 'legacy' is a paths sentinel that
        silently falls back to repo root; reject it at the API edge."""
        status, data = self._get_json("/api/workspace/legacy/status")
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_leading_or_trailing_hyphen_rejected(self) -> None:
        """Iter 025 code-review #9: '-foo' / 'foo-' collide with argparse
        and shell-flag parsing in iter 026 wizard / settings paths."""
        for bad in ("-foo", "foo-", "-", "--"):
            status, _data = self._get_json(f"/api/workspace/{bad}/status")
            self.assertEqual(status, 400, f"name {bad!r} should be rejected")


class Iter073LeaveGuardRaceTests(unittest.TestCase):
    """iter073 (codex E): the leave-guard JS must carry a request-sequence token
    + single-modal guard so a slow /jobs/active response can't navigate to a
    stale destination, and a second click while a modal is open can't silently
    change the destination or jump to the wrong page. String assertions over the
    served bundle (no jsdom); JS syntax is gated separately by ``node --check``."""

    def test_leave_guard_has_sequence_and_modal_guards(self) -> None:
        from src.web import static

        js = static.JS_DASHBOARD
        # module-level race state
        self.assertIn("let leaveGuardSeq = 0;", js)
        self.assertIn("let leaveGuardModalOpen = false;", js)
        # second click while a modal is open is a no-op (keeps original dest)
        self.assertIn("if (leaveGuardModalOpen) return;", js)
        # each click captures a seq and the async handler honors only the latest
        self.assertIn("const seq = ++leaveGuardSeq;", js)
        self.assertIn("if (seq !== leaveGuardSeq) return;", js)
        # the open guard is reset on every non-navigating close (stay/backdrop/Esc)
        self.assertIn("onClose", js)
        self.assertIn("leaveGuardModalOpen = false;", js)


class Iter073JobApiDetailTests(unittest.TestCase):
    """iter073 (codex D1+D3): /job/<id> returns a finite-safe detail projection
    — non-finite floats become null (valid JSON), a future internal field can't
    auto-leak, and the frontend-needed params survive."""

    def setUp(self) -> None:
        os.environ["OPENAI_MODEL"] = "mock"
        self._tmp = tempfile.TemporaryDirectory()
        self._saved_ws_dir = paths.WORKSPACE_DIR
        self._saved_env = os.environ.get("WORKSPACE_NAME")
        os.environ.pop("WORKSPACE_NAME", None)
        paths.WORKSPACE_DIR = Path(self._tmp.name)
        _stub_workspace(paths.WORKSPACE_DIR, "alpha")
        jobs.reset_for_tests()

    def tearDown(self) -> None:
        jobs.reset_for_tests()
        paths.WORKSPACE_DIR = self._saved_ws_dir
        if self._saved_env is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._saved_env
        self._tmp.cleanup()

    def test_job_status_finite_safe_detail_projection(self) -> None:
        rec = jobs._new_job_record("alpha", "write-book", {"chapters": 1})
        rec["status"] = "succeeded"
        rec["progress"] = float("nan")
        rec["result_summary"] = {"cost_cny": float("inf")}
        rec["trace_id"] = "tid"
        rec["_secret"] = "nope"
        with jobs._JOBS_LOCK:
            jobs._JOBS[rec["job_id"]] = rec
        status, ct, body = routes.dispatch(
            "GET", f"/api/workspace/alpha/job/{rec['job_id']}"
        )
        self.assertEqual(status, 200, body.decode("utf-8"))
        text = body.decode("utf-8")
        # bare NaN/Infinity tokens would be invalid JSON for a strict parser
        self.assertNotIn("NaN", text)
        self.assertNotIn("Infinity", text)
        data = json.loads(text)
        self.assertIsNone(data["progress"])
        self.assertIsNone(data["result_summary"]["cost_cny"])
        self.assertIn("params", data)  # detail keeps params (frontend retry)
        self.assertNotIn("_secret", data)  # future internal field not leaked


if __name__ == "__main__":
    unittest.main()
