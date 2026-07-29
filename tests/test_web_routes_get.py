"""iter 025: WebUI route dispatcher (pure functions, no HTTP server)."""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

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

    def test_landing_is_root(self) -> None:
        status, _ct, body = routes.dispatch("GET", "/")
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        self.assertIn("创建小说作品", html)
        self.assertIn("打开已有作品", html)
        self.assertIn("进入短剧作品", html)
        self.assertIn('window.PAGE_KIND = "landing"', html)
        self.assertIn('href="/wizard"', html)
        self.assertIn('href="/library"', html)     # hero "打开已有作品"
        # removed / renamed surfaces must be gone from the landing.
        # NB: scope to the hero anchor markup — bare "开始续写" also appears in the
        # embedded READINESS_CATALOG JSON ("…之后开始续写…"), present on every page.
        self.assertNotIn(">开始续写</a>", html)      # hero CTA renamed to 开始创作
        self.assertNotIn("lp-secondary", html)      # duplicate bookshelf link removed
        self.assertNotIn("＋ 新建", html)           # topbar trimmed to ⚙ 设置 only
        # landing topbar cluster hidden via page_kind=="landing" gate
        self.assertIn("lp-chrome", html)

    def test_trash_page_renders(self) -> None:
        status, _ct, body = routes.dispatch("GET", "/trash")
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        self.assertIn("已删除的作品", html)
        self.assertIn('id="trash-list"', html)
        self.assertIn('window.PAGE_KIND = "trash"', html)

    def test_wizard_renders_type_choice_panels(self) -> None:
        status, _ct, body = routes.dispatch("GET", "/wizard")
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        self.assertIn('id="panel-type"', html)
        self.assertIn('name="ws_type" value="novel"', html)
        self.assertIn('name="ws_type" value="drama"', html)
        self.assertIn('name="ws_type" value="premise"', html)   # iter069: 3rd type
        self.assertIn('id="panel-upload" hidden', html)
        self.assertIn('id="panel-drama" hidden', html)
        self.assertIn('id="panel-premise" hidden', html)        # premise extracted to own panel
        self.assertIn('id="wizard-mode-card"', html)
        self.assertIn('name="budget_cny"', html)
        self.assertIn('name="timeout_minutes"', html)
        self.assertIn('name="extract_limit"', html)
        self.assertIn("会发生什么", html)
        self.assertIn("复仇 → 救赎", html)
        self.assertIn("data-back-to-type", html)
        self.assertIn("从本地原文创建", html)
        self.assertIn("创建原创故事", html)
        self.assertIn("创建短剧作品", html)
        # 真实生成入口说明使用面向用户的中文，不暴露配置字段名。
        self.assertIn("需要使用真实生成服务时", html)
        self.assertIn("完成连接配置并重启", html)
        self.assertNotIn("API key", html)
        self.assertIn('href="/settings"', html)
        # both error containers exist, each scoped to its own panel
        self.assertIn('id="upload-error"', html)    # stays in upload panel (novelForm uses it)
        self.assertIn('id="premise-error"', html)   # new, in premise panel
        # wizard is NOT landing → must not inherit the lp-chrome topbar hide
        self.assertNotIn("lp-chrome", html)
        # wizard JS wiring for the premise panel
        self.assertIn("/api/preflight", routes.static.JS_WIZARD)
        self.assertIn("panelPremise", routes.static.JS_WIZARD)
        self.assertIn("premiseErrBox", routes.static.JS_WIZARD)
        self.assertIn('getElementById("premise-error")', routes.static.JS_WIZARD)
        self.assertIn('t === "premise"', routes.static.JS_WIZARD)
        # three-panel mutual exclusion: premise sits in the show() switch array
        self.assertIn("panelPremise, panelProgress", routes.static.JS_WIZARD)

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
        self.assertNotIn("API_KEY", json.dumps(data))

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

    def test_phase_e_novel_apis_fail_closed_for_drama_workspace(self) -> None:
        workspace_meta.write("beta", type="drama", created_at="2026-07-29T00:00:00+00:00")
        for path in (
            "/api/workspace/beta/plan",
            "/api/workspace/beta/reviews",
            "/api/workspace/beta/search?q=人物",
            "/api/workspace/beta/readiness?chapters=1&resume_from=1&replan_every=0",
        ):
            with self.subTest(path=path):
                status, data = self._get_json(path)
                self.assertEqual(status, 409, data)
                self.assertIn("card", data)

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
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        self.assertIn("作品类型待确认", html)
        self.assertNotIn('window.PAGE_KIND = "jobs"', html)

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

    def test_api_workspaces_overview_includes_drama_type(self) -> None:
        workspace_meta.write("beta", type="drama", created_at="2026-06-03T00:00:00+00:00")
        status, data = self._get_json("/api/workspaces/overview")
        self.assertEqual(status, 200)
        by_name = {item["name"]: item for item in data["workspaces"]}
        self.assertEqual(by_name["beta"]["type"], "drama")

    def test_overview_cache_key_includes_workspace_json_mtime(self) -> None:
        key1 = routes._overview_cache_key(["beta"])
        workspace_meta.write("beta", type="drama", created_at="2026-06-03T00:00:00+00:00")
        meta_path = paths.WORKSPACE_DIR / "beta" / "data" / "workspace.json"
        now = time.time() + 10
        os.utime(meta_path, (now, now))
        key2 = routes._overview_cache_key(["beta"])
        self.assertNotEqual(key1, key2)

    def test_drama_sidebar_exposes_overview_write_episodes_jobs(self) -> None:
        # Updated iter 037: drama sidebar now includes "write" for stations 1 and 2.
        workspace_meta.write("beta", type="drama", created_at="2026-06-03T00:00:00+00:00")
        status, _ct, body = routes.dispatch("GET", "/w/beta/")
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        self.assertIn("作品 · 短剧", html)
        self.assertIn('href="/w/beta/"', html)
        self.assertIn('href="/w/beta/write"', html)
        self.assertIn('href="/w/beta/episodes"', html)
        self.assertIn('href="/w/beta/jobs"', html)
        self.assertIn('id="delete-workspace-btn"', html)
        self.assertNotIn('href="/w/beta/continue"', html)
        self.assertNotIn('href="/w/beta/plan"', html)
        for element_id in (
            "overview-summary",
            "overview-next-action",
            "overview-blockers",
            "overview-detail-status",
            "overview-detail-cost",
        ):
            self.assertNotIn(f'id="{element_id}"', html)

    def test_drama_write_page_renders_five_station_tabs(self) -> None:
        workspace_meta.write("beta", type="drama", created_at="2026-06-03T00:00:00+00:00")
        status, _ct, body = routes.dispatch("GET", "/w/beta/write")
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        self.assertIn('window.PAGE_KIND = "drama_write"', html)
        for tab in ("setup", "hook", "storyboard", "characters", "review"):
            self.assertIn(f'data-tab="{tab}"', html)
            self.assertIn(f'data-station-pane="{tab}"', html)
        self.assertIn("分镜脚本", html)
        self.assertIn("评审与组装", html)
        self.assertNotIn("分镜表尚未开放", html)
        self.assertNotIn("角色设定表尚未开放", html)

    def test_drama_write_storyboard_step_renders_empty_state_not_404(self) -> None:
        workspace_meta.write("beta", type="drama", created_at="2026-06-03T00:00:00+00:00")
        status, _ct, body = routes.dispatch("GET", "/w/beta/write?step=storyboard")
        self.assertEqual(status, 200)
        self.assertIn("分镜脚本", body.decode("utf-8"))

    def test_novel_workspace_write_page_404(self) -> None:
        status, _ct, body = routes.dispatch("GET", "/w/alpha/write")
        self.assertEqual(status, 404)
        self.assertIn("drama workspaces only", body.decode("utf-8"))

    def test_drama_novel_only_pages_render_shell_empty_state(self) -> None:
        workspace_meta.write("beta", type="drama", created_at="2026-06-03T00:00:00+00:00")
        for path in (
            "/w/beta/continue",
            "/w/beta/plan",
            "/w/beta/chapters",
            "/w/beta/chapter/1",
            "/w/beta/reviews",
        ):
            status, _ct, body = routes.dispatch("GET", path)
            html = body.decode("utf-8")
            self.assertEqual(status, 200, f"{path}: {html}")
            self.assertIn("此页面属于小说模块", html)
            self.assertIn('window.PAGE_KIND = "workspace_empty"', html)
            self.assertIn('href="/w/beta/write"', html)

    def test_drama_jobs_page_still_renders(self) -> None:
        workspace_meta.write("beta", type="drama", created_at="2026-06-03T00:00:00+00:00")
        status, _ct, body = routes.dispatch("GET", "/w/beta/jobs")
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        self.assertIn("<h1>任务</h1>", html)
        self.assertIn('class="jobs-filter drama-jobs-filter"', html)

    def test_drama_episode_pages_render(self) -> None:
        workspace_meta.write("beta", type="drama", created_at="2026-06-03T00:00:00+00:00")
        status, _ct, body = routes.dispatch("GET", "/w/beta/episodes")
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        self.assertIn('window.PAGE_KIND = "drama_episodes"', html)
        self.assertIn('id="episodes-panel"', html)
        status, _ct, body = routes.dispatch("GET", "/w/beta/episode/1")
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        self.assertIn('window.PAGE_KIND = "drama_episode_detail"', html)
        self.assertIn('data-tab="script"', html)
        self.assertIn('data-tab="export"', html)

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

    def test_api_logs_tail_does_not_project_provider_error_or_fingerprint(self) -> None:
        log_path = Path(self._tmp.name) / "alpha" / "logs" / "llm_calls.jsonl"
        log_path.write_text(
            json.dumps({
                "task": "drama_plan",
                "status": "retry_error",
                "model": "openai/example",
                "duration_ms": 1250,
                "error": "upstream failed at https://signed.example/secret?token=abc",
                "request_hash": "private-fingerprint",
            }) + "\n",
            encoding="utf-8",
        )
        status, data = self._get_json("/api/workspace/alpha/logs/tail?n=10")
        self.assertEqual(status, 200)
        self.assertEqual(
            data["lines"],
            [{
                "task": "drama_plan",
                "status": "retry_error",
                "model": "openai/example",
                "duration_ms": 1250,
            }],
        )

    def test_api_logs_tail_rejects_secret_shaped_model_and_bad_field_types(self) -> None:
        log_path = Path(self._tmp.name) / "alpha" / "logs" / "llm_calls.jsonl"
        log_path.write_text(
            json.dumps({
                "task": "drama_plan",
                "status": {"bad": "shape"},
                "model": "https://user:pass@example.test/model?token=secret",
                "duration_ms": 1250,
                "prompt_tokens": -1,
            }) + "\n" + json.dumps({
                "task": "drama_hooks",
                "status": "ok",
                "model": "openai/sk-" + "A" * 32,
                "duration_ms": 2500,
            }) + "\n",
            encoding="utf-8",
        )
        status, data = self._get_json("/api/workspace/alpha/logs/tail?n=10")
        self.assertEqual(status, 200)
        self.assertEqual(data["lines"], [
            {"task": "drama_plan", "duration_ms": 1250},
            {"task": "drama_hooks", "status": "ok", "duration_ms": 2500},
        ])

    def test_jobs_ui_formats_times_and_renders_llm_summary_table(self) -> None:
        js = routes.static.JS_DASHBOARD
        self.assertIn("function formatJobTimestamp", js)
        self.assertIn("function renderLlmCallSummary", js)
        self.assertIn("escapeHtml(stepLabel(job.step))", js)
        self.assertIn('"drama_plan": "短剧站①核心设定"', js)
        self.assertIn('return icon + " 已完成"', js)
        self.assertIn('class="job-record-card"', js)
        self.assertIn("从创作工作台开始一个阶段后", js)
        self.assertIn("function initDramaJobsLegacy", js)
        self.assertNotIn("lines.map((l) => escapeHtml(JSON.stringify(l)))", js)

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
        for sel in (".error-card", ".stepbar", ".tab.locked", ".home-btn", ".badge-soon"):
            self.assertIn(sel, css)

    def test_shell_has_topbar_home_button(self) -> None:
        status, _ct, body = routes.dispatch("GET", "/library")
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        # iter070: ⌂ now goes to the landing home (/), not the bookshelf, and is
        # a leave-guard exit. The bookshelf stays reachable via the brand below.
        self.assertIn('class="btn btn-icon home-btn" href="/" data-leave-guard', html)
        self.assertIn('<span class="here" aria-current="page">书架</span>', html)

    def test_iter154_landing_routes_to_public_tasks(self) -> None:
        """Phase C keeps one general novel choice and a separate drama entry."""
        status, _ct, body = routes.dispatch("GET", "/")
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        self.assertIn('href="/wizard"', html)
        self.assertIn('href="/wizard?type=drama"', html)
        self.assertIn('href="/library"', html)

    def test_iter070_library_populated_shelf_has_no_epub_copy(self) -> None:
        """iter070/iter071 (codex F4): this route runs with alpha/beta fixtures,
        so `names` is non-empty and the empty-shelf hint never renders — it only
        guards against an 'epub' assumption leaking onto a POPULATED shelf. The
        actual empty-shelf copy is exercised by the unit test below."""
        status, _ct, body = routes.dispatch("GET", "/library")
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        self.assertNotIn("epub", html)

    def test_iter071_empty_shelf_renders_neutral_hint(self) -> None:
        """iter071 (codex F4): render an empty shelf directly (no fixtures) so the
        empty-shelf branch is actually taken (it emits the hint into the
        data-empty attribute the client reads), and assert that copy carries no
        novel/epub-only assumption. The iter070 route test above could not reach
        this branch."""
        html = templates.render_index([])
        self.assertIn("还没有作品", html)  # the empty hint reached the DOM (data-empty=…)
        self.assertIn("可以创建小说作品，也可以创建短剧作品", html)
        self.assertNotIn("epub", html)
        self.assertNotIn("第一本书", html)  # old novel-only phrasing gone

    def test_iter070_workspace_shell_marks_leave_guard_exits(self) -> None:
        """iter070: ⌂, the sidebar brand, and the first breadcrumb crumb are the
        in-app 'leave this workspace' exits tagged for the leave-guard."""
        status, _ct, body = routes.dispatch("GET", "/w/alpha/")
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        self.assertIn('class="btn btn-icon home-btn" href="/" data-leave-guard', html)
        self.assertIn('class="brand" href="/library" data-leave-guard', html)
        self.assertIn('<a href="/library" data-leave-guard>', html)  # first crumb

    def test_iter070_static_js_has_leave_guard(self) -> None:
        """iter070: leave-guard delegate + modal; active = pending/running only
        (not the succeeded-omitting helper); drama badge carries its 🎬 marker."""
        status, _ct, body = routes.dispatch("GET", "/static/app.js")
        self.assertEqual(status, 200)
        js = body.decode("utf-8")
        self.assertIn("ensureLeaveGuardDelegate", js)
        self.assertIn("showLeaveGuardModal", js)
        self.assertIn('j.status === "pending" || j.status === "running"', js)
        self.assertIn("🎬 短剧", js)

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

    def test_iter070_static_css_drama_badge_border(self) -> None:
        """iter070: drama badge gets a solid --amber border so it stops
        colliding with the running/pending status pill colour."""
        status, _ct, body = routes.dispatch("GET", "/static/app.css")
        self.assertEqual(status, 200)
        css = body.decode("utf-8")
        self.assertIn("border-color: var(--amber); }", css)
        self.assertIn(".badge-drama", css)

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
            "setup",
            "hook",
            "storyboard",
            "characters",
            "script",
            "storyboard-view",
            "characters-view",
            "export",
        ):
            self.assertIn(f'"{kw}"', js)

    def test_static_js_has_drama_write_identifiers(self) -> None:
        status, _ct, body = routes.dispatch("GET", "/static/app.js")
        self.assertEqual(status, 200)
        js = body.decode("utf-8")
        for kw in (
            "initDramaWrite",
            "loadStationSetup",
            "loadStationHooks",
            "loadStationStoryboard",
            "loadDramaProgress",
            "/drama/storyboard",
            "/drama/episodes",
            "/drama/review",
            "drama-review-assemble",
            "resumeDramaActiveJob",
            "initDramaEpisodes",
            "initDramaEpisodeDetail",
            "data-station-pane",
            "bindHookPickDelegate",
            "__hooks",
        ):
            self.assertIn(kw, js)

    def test_static_js_hook_picker_uses_single_delegate_and_disables_buttons(self) -> None:
        status, _ct, body = routes.dispatch("GET", "/static/app.js")
        self.assertEqual(status, 200)
        js = body.decode("utf-8")
        self.assertIn("bindHookPickDelegate", js)
        self.assertIn("pane.__hooks = hooks", js)
        self.assertNotIn('pane.addEventListener("click"', js)
        self.assertIn("forEach((b) => { b.disabled = true; })", js)

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

    def test_static_js_restores_local_demo_from_server_validated_target(self) -> None:
        status, _ct, body = routes.dispatch("GET", "/static/app.js")
        self.assertEqual(status, 200)
        js = body.decode("utf-8")
        self.assertIn("function restoreLocalDemoJob", js)
        self.assertIn("function localDemoTargetHref", js)
        self.assertIn("__local_demo_job_v1:", js)
        self.assertIn('wsUrl("/jobs/active")', js)
        self.assertIn('wsUrl("/jobs/recent?n=20")', js)
        self.assertIn("root.__localDemoHistory = null;\n      render();", js)
        self.assertIn("target_workspace", js)
        self.assertIn("打开演练交付", js)
        self.assertNotIn("localStorage.setItem(localDemoPendingKey(targetEpisode), demoWorkspace", js)

    def test_static_js_has_type_badge(self) -> None:
        status, _ct, body = routes.dispatch("GET", "/static/app.js")
        self.assertEqual(status, 200)
        js = body.decode("utf-8")
        self.assertIn("function typeBadge", js)
        self.assertIn("badge-drama", js)
        self.assertIn("badge-novel", js)

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

    def test_wizard_js_has_drama_path(self) -> None:
        status, _ct, body = routes.dispatch("GET", "/static/wizard.js")
        self.assertEqual(status, 200)
        js = body.decode("utf-8")
        self.assertIn("/api/wizard/drama-start", js)
        self.assertIn("/api/preflight", js)
        self.assertIn("/cancel", js)
        self.assertIn("renderWizardActions", js)
        self.assertIn("data-back-to-type", js)
        self.assertIn("window.setPendingToastAndNavigate", js)
        self.assertIn('msg: "短剧作品已创建：" + data.name', js)

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


class DramaUserFacingCopyTests(unittest.TestCase):
    def test_drama_ui_uses_human_labels_and_keeps_large_shelf_navigable(self) -> None:
        source = Path("src/web/static.py").read_text(encoding="utf-8")
        self.assertIn('const statusLabel = { done: "已完成"', source)
        self.assertIn('const labels = { approve: "通过"', source)
        self.assertIn('class="drama-episode-card"', source)
        self.assertIn("/write?episode=", source)
        self.assertIn('编辑本集', source)
        self.assertIn(".sidebar-library-list", source)
        self.assertNotIn('<span class="badge ready">fresh</span>', source)
        self.assertIn('return /[.]png$/i.test', source)

    def test_drama_episode_detail_has_direct_edit_link(self) -> None:
        html = templates.render_workspace_episode_detail("drama", ["drama"], 2)
        self.assertIn('href="/w/drama/write?episode=2">编辑本集</a>', html)

    def test_example_config_pins_video_provider_without_enabling_paid_video(self) -> None:
        source = Path(".env.example").read_text(encoding="utf-8")
        self.assertIn("SD_VIDEO_MODE=mock", source)
        self.assertIn("SD_API_BASE_URL=https://model.service-inference.ai", source)
        self.assertIn("SD_VIDEO_MODEL=dreamina-seedance-2-0-hc", source)
        self.assertIn("SD_API_KEY=\n", source)
        self.assertIn(
            "workspaces/.*.drama_multimodal_smoke.lock",
            Path(".gitignore").read_text(encoding="utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
