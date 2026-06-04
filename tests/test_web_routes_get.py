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
from src.web import routes
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

    def test_index_lists_workspaces(self) -> None:
        status, _ct, body = routes.dispatch("GET", "/")
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        self.assertIn("本地写作工作台", html)
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

    def test_wizard_renders_type_choice_panels(self) -> None:
        status, _ct, body = routes.dispatch("GET", "/wizard")
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        self.assertIn('id="panel-type"', html)
        self.assertIn('name="ws_type" value="novel"', html)
        self.assertIn('name="ws_type" value="drama"', html)
        self.assertIn('id="panel-upload" hidden', html)
        self.assertIn('id="panel-drama" hidden', html)
        self.assertIn("复仇 → 救赎", html)
        self.assertIn("data-back-to-type", html)

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
        self.assertIn("alpha", html)
        # sidebar lists the workspace and the new sections
        self.assertIn("续写", html)
        self.assertIn("计划", html)
        self.assertIn("章节", html)
        self.assertIn("评审", html)
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
        self.assertIn("准备续写", html)
        self.assertIn("继续写书", html)
        self.assertIn("重生成并覆盖计划", html)
        self.assertIn("start-point-form", html)
        self.assertIn("write-book-form", html)
        self.assertIn("plan-form", html)
        self.assertIn("write-preset-toggle", html)
        self.assertIn('name="tier"', html)
        self.assertIn("本次最多花费 CNY", html)
        self.assertIn("高级参数", html)
        self.assertNotIn("draft-once-dev", html)

    def test_workspace_plan_page_renders(self) -> None:
        status, _ct, body = routes.dispatch("GET", "/w/alpha/plan")
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        self.assertIn('data-plan-pane="chapters"', html)
        self.assertIn('data-plan-pane="outline"', html)
        self.assertIn('data-plan-pane="decisions"', html)
        self.assertIn('href="/w/alpha/plan"', html)
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
        self.assertIn("chapter_01", html)
        # 5 tabs
        for tab in ("body", "review", "lint", "advisor", "history"):
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

    def test_drama_sidebar_exposes_overview_write_jobs(self) -> None:
        # Updated iter 037: drama sidebar now includes "write" for stations 1 and 2.
        workspace_meta.write("beta", type="drama", created_at="2026-06-03T00:00:00+00:00")
        status, _ct, body = routes.dispatch("GET", "/w/beta/")
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        self.assertIn("作品 · 短剧", html)
        self.assertIn('href="/w/beta/"', html)
        self.assertIn('href="/w/beta/write"', html)
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

    def test_drama_write_page_renders_four_station_tabs(self) -> None:
        workspace_meta.write("beta", type="drama", created_at="2026-06-03T00:00:00+00:00")
        status, _ct, body = routes.dispatch("GET", "/w/beta/write")
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        self.assertIn('window.PAGE_KIND = "drama_write"', html)
        for tab in ("setup", "hook", "storyboard", "characters"):
            self.assertIn(f'data-tab="{tab}"', html)
            self.assertIn(f'data-station-pane="{tab}"', html)
        self.assertIn("分镜表尚未开放", html)
        self.assertIn("角色设定表尚未开放", html)

    def test_drama_write_storyboard_step_renders_empty_state_not_404(self) -> None:
        workspace_meta.write("beta", type="drama", created_at="2026-06-03T00:00:00+00:00")
        status, _ct, body = routes.dispatch("GET", "/w/beta/write?step=storyboard")
        self.assertEqual(status, 200)
        self.assertIn("分镜表", body.decode("utf-8"))

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
            "/w/beta/insights",
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
        self.assertIn("任务历史", body.decode("utf-8"))

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
        self.assertTrue(
            any("readiness_error" in item for item in by_name["beta"]["readiness"]["blockers"]),
            by_name["beta"]["readiness"]["blockers"],
        )

    def test_api_status_404_for_unknown(self) -> None:
        status, data = self._get_json("/api/workspace/nope/status")
        self.assertEqual(status, 404)
        self.assertIn("not found", data["error"])

    def test_api_manifest_returns_chapters(self) -> None:
        status, data = self._get_json("/api/workspace/alpha/manifest")
        self.assertEqual(status, 200)
        self.assertEqual(data["chapters"][0]["chapter_id"], "alpha_ch001")

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
        self.assertIn("partial draft saved", js)

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

    def test_api_logs_tail(self) -> None:
        status, data = self._get_json("/api/workspace/alpha/logs/tail?n=10")
        self.assertEqual(status, 200)
        self.assertEqual(len(data["lines"]), 1)
        self.assertEqual(data["lines"][0]["task"], "review")

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
            "loadDramaProgress",
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
        self.assertIn("response is not valid JSON", js)

    def test_static_js_has_pending_toast_cleanup(self) -> None:
        status, _ct, body = routes.dispatch("GET", "/static/app.js")
        self.assertEqual(status, 200)
        js = body.decode("utf-8")
        self.assertIn("setPendingToastAndNavigate", js)
        self.assertIn('sessionStorage.removeItem("__pending_toast")', js)
        self.assertIn('msg: "已删除 《" + name + "》', js)

    def test_static_js_has_type_badge(self) -> None:
        status, _ct, body = routes.dispatch("GET", "/static/app.js")
        self.assertEqual(status, 200)
        js = body.decode("utf-8")
        self.assertIn("function typeBadge", js)
        self.assertIn("badge-drama", js)
        self.assertIn("badge-novel", js)

    def test_wizard_js_has_drama_path(self) -> None:
        status, _ct, body = routes.dispatch("GET", "/static/wizard.js")
        self.assertEqual(status, 200)
        js = body.decode("utf-8")
        self.assertIn("/api/wizard/drama-start", js)
        self.assertIn("data-back-to-type", js)
        self.assertIn("window.setPendingToastAndNavigate", js)
        self.assertIn('msg: "短剧 workspace 已创建：" + data.name', js)

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


if __name__ == "__main__":
    unittest.main()
