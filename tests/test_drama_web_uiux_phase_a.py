"""Iteration 158 contracts for the drama shell, overview and production UI."""

from __future__ import annotations

import re
import unittest
from unittest import mock

from src.web import static, templates


class DramaWebUiuxPhaseATests(unittest.TestCase):
    def _page(self, renderer, *args):
        with mock.patch("src.web.workspace_meta.read", return_value={"type": "drama"}):
            return renderer(*args)

    def test_drama_shell_keeps_canonical_eleven_routes_and_active_state(self) -> None:
        html = self._page(
            templates.render_workspace_production,
            "synthetic-drama",
            ["synthetic-drama", "another-workspace"],
        )
        tablet = re.search(
            r'<nav class="drama-tablet-nav".*?<div class="drama-tablet-nav-scroll">(.*?)</div>',
            html,
            re.S,
        )
        self.assertIsNotNone(tablet)
        assert tablet is not None
        self.assertEqual(tablet.group(1).count("data-drama-nav-item="), 11)
        for label in (
            "概览", "创作台", "生产工作台", "角色库", "资产治理", "镜头图片",
            "镜头视频", "合成交付", "剧集", "数据", "任务",
        ):
            self.assertIn(label, tablet.group(1))
        self.assertIn('data-drama-nav-item="production">\u751f产工作台</span>', html)
        self.assertIn('class="drama-mobile-nav"', html)
        self.assertIn('aria-label="打开全部导航"', html)
        self.assertIn('querySelectorAll("[data-sidebar-toggle]")', static.JS_DASHBOARD)
        self.assertIn("navToggles.forEach", static.JS_DASHBOARD)
        self.assertIn('href="/w/another-workspace/" data-leave-guard', html)
        self.assertIn('class="app ui-drama"', html)

    def test_overview_has_six_explicit_page_states_and_recovery_hooks(self) -> None:
        html = self._page(
            templates.render_workspace_overview,
            "synthetic-drama",
            ["synthetic-drama"],
        )
        for element_id in (
            "drama-overview-summary",
            "drama-overview-progress",
            "drama-overview-next-action",
            "drama-next-headline",
            "drama-next-reason",
            "drama-next-actions",
            "drama-overview-recent-task",
        ):
            self.assertIn(f'id="{element_id}"', html)
        self.assertNotIn("workspace 元信息", html)
        self.assertNotIn("schema_version", html)
        js = static.JS_DASHBOARD
        for state in ("ready", "incomplete", "stale", "blocked"):
            self.assertIn(f'production.state === "{state}"' if state in {"stale", "blocked"} else state, js)
        self.assertIn("还没有创作进度", js)
        self.assertIn("概览没有读取成功", js)
        self.assertIn("data-drama-overview-retry", js)
        self.assertIn("productionReasonText", js)
        self.assertIn('const blocked = !todo && production.state === "blocked"', js)
        self.assertIn('fetchJson(wsUrl("/drama/production?episode_no=1")).catch', js)
        self.assertIn("const productionAvailable = optional[0] !== null", js)
        self.assertIn("已有任务不受影响", js)

    def test_production_list_and_canvas_share_projection_and_keep_hooks(self) -> None:
        html = self._page(
            templates.render_workspace_production,
            "synthetic-drama",
            ["synthetic-drama"],
        )
        for hook in (
            'id="production-episode-no"',
            'id="production-refresh"',
            'data-production-view="list"',
            'data-production-view="canvas"',
            'aria-selected="true" tabindex="0"',
            'aria-selected="false" tabindex="-1"',
        ):
            self.assertIn(hook, html)
        js = static.JS_DASHBOARD
        self.assertIn(
            "projection.list_projection_fingerprint !== projection.canvas_projection_fingerprint",
            js,
        )
        self.assertIn("productionShotReason", js)
        self.assertIn("production-actionable-only", js)
        self.assertIn("data-shot-entry", js)
        self.assertIn('.sidebar a,.drama-tablet-nav a,.drama-mobile-nav a', js)
        self.assertIn('target.searchParams.set("episode", String(value))', js)
        self.assertIn("syncDramaEpisodeLinks(Number(rawEpisode))", js)
        self.assertIn('const episodeKey = stage[3].indexOf("/write") === 0 ? "episode" : "episode_no"', js)
        for stage in ("创作", "资产", "图片", "视频", "时间线", "合成 QA"):
            self.assertIn(stage, js)
        self.assertIn("production-local-demo", js)
        self.assertIn("localdemo_", js)
        self.assertIn('data-local-demo-history', js)
        self.assertIn('["ArrowLeft", "ArrowRight", "Home", "End"]', js)

    def test_drama_styles_are_scoped_and_accessible(self) -> None:
        css = static.CSS_BODY
        self.assertIn("Iteration 158 · short-drama Phase A", css)
        self.assertIn(".ui-drama .drama-tablet-nav", css)
        self.assertIn(".ui-drama .drama-mobile-nav", css)
        self.assertIn("outline: 3px solid var(--ui-focus-ring)", css)
        self.assertIn("min-height: 44px", css)
        self.assertIn("overflow-x: clip", css)
        phase_a = css.split("Iteration 158 · short-drama Phase A", 1)[1]
        self.assertNotIn(".ui-public", phase_a)
        self.assertNotIn(".ui-novel", phase_a)

    def test_existing_leave_toast_and_job_recovery_contracts_remain(self) -> None:
        combined = templates._BASE_TPL.template + static.JS_DASHBOARD
        for hook in (
            "data-leave-guard",
            "toast-stack",
            "localDemoPendingKey",
            "restoreLocalDemoJob",
            "renderJobReconcile",
            "submission_unknown",
        ):
            self.assertIn(hook, combined)
        self.assertIn("不会自动重试", static.JS_DASHBOARD)


if __name__ == "__main__":
    unittest.main()
