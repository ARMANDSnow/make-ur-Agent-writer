"""Iteration 161: short-drama Phase D Web UIUX contracts."""

from __future__ import annotations

import unittest

from src.web import routes, static
from tests._drama_base import DramaTestBase


def _function_source(name: str, next_name: str) -> str:
    body = static.JS_DASHBOARD
    start = body.index(f"  async function {name}(")
    end = body.index(f"  async function {next_name}(", start)
    return body[start:end]


class DramaWebUiuxPhaseDTests(DramaTestBase):
    def setUp(self) -> None:
        super().setUp()
        self._make_drama_workspace("phase-d")

    def _html(self, path: str) -> str:
        status, content_type, body = routes.dispatch("GET", path)
        self.assertEqual(status, 200)
        self.assertIn("text/html", content_type)
        return body.decode("utf-8")

    def test_phase_d_pages_reuse_drama_shell_and_have_live_roots(self) -> None:
        pages = {
            "/w/phase-d/compose": ("drama_compose", "drama-compose-page"),
            "/w/phase-d/episodes": ("drama_episodes", "drama-episodes-page"),
            "/w/phase-d/insights": ("drama_insights", "drama-insights-page"),
            "/w/phase-d/jobs": ("jobs", "drama-jobs-page"),
        }
        for path, (kind, marker) in pages.items():
            with self.subTest(path=path):
                html = self._html(path)
                self.assertIn('class="app ui-drama"', html)
                self.assertIn(f'window.PAGE_KIND = "{kind}"', html)
                self.assertIn(marker, html)

    def test_phase_d_css_keeps_touch_focus_and_three_layouts(self) -> None:
        css = static.CSS_BODY
        self.assertIn("outline: 3px solid var(--ui-focus-ring)", css)
        self.assertIn("min-height: 44px", css)
        self.assertIn(".ui-drama .drama-compose-layout", css)
        self.assertIn(".ui-drama .drama-episode-card", css)
        self.assertIn(".ui-drama .drama-insights-grid", css)
        self.assertIn(".ui-drama .drama-jobs-layout", css)
        self.assertIn("@media (min-width: 768px) and (max-width: 1199px)", css)
        self.assertIn("@media (max-width: 767px)", css)

    def test_compose_ui_uses_safe_exact_delivery_projection(self) -> None:
        source = static.JS_DASHBOARD[
            static.JS_DASHBOARD.index("  function renderComposeOverview("):
            static.JS_DASHBOARD.index("  async function initDramaCompose(")
        ]
        self.assertIn("QA 与 Exact 交付", source)
        self.assertIn("下载时重新验证", source)
        self.assertIn("data-compose-mobile-start", source)
        self.assertIn("未知或丢失状态不会自动重试", source)
        self.assertNotIn("output_sha256", source)
        self.assertNotIn("timeline_fingerprint", source)
        self.assertNotIn("qa_fingerprint", source)
        self.assertIn('composeUiStates[state] || "unknown"', source)
        self.assertIn("actionable && !jobActive", source)
        self.assertIn("剪辑工程", source)
        self.assertNotIn("TimelineManifest", source)

        init_source = static.JS_DASHBOARD[
            static.JS_DASHBOARD.index("  async function initDramaCompose("):
            static.JS_DASHBOARD.index("  let accessibleControlSeq", static.JS_DASHBOARD.index("  async function initDramaCompose("))
        ]
        self.assertIn("refreshTimer = setTimeout(load, 1000)", init_source)
        self.assertIn("data-compose-cancel", init_source)
        self.assertNotIn("pollJob(", init_source)

    def test_episode_cards_preserve_episode_scoped_routes_and_freshness(self) -> None:
        source = _function_source("initDramaEpisodes", "initDramaEpisodeDetail")
        self.assertIn("drama-episode-card", source)
        self.assertIn("ep.stale", source)
        self.assertIn("/episode/", source)
        self.assertIn("/write?episode=", source)
        self.assertIn("data-start-next-episode", source)
        self.assertIn("data-leave-guard", source)
        self.assertIn("snapshot", source)
        self.assertIn("master", source)

    def test_insights_unknowns_are_not_folded_into_known_totals(self) -> None:
        source = _function_source("initDramaInsights", "initDramaJobsLegacy")
        self.assertIn("unknown_submission_count", source)
        self.assertIn("mediaKnownCurrencies", source)
        self.assertIn("分币种列示，不跨币种合并", source)
        self.assertIn('llm.status === "ok" && meta.status === "ok"', source)
        self.assertIn("时长来源待核对", source)
        self.assertIn("暂无可确认金额", source)
        self.assertIn("未知或无效记录不纳入", source)
        self.assertIn('mediaMetrics.status === "ok"', source)
        self.assertIn('duration.status === "ok"', source)
        self.assertIn("指标来源待核对", source)
        self.assertNotIn(".reduce(function (sum, row)", source)
        self.assertNotIn("unknown_submission_count || 0) +", source)

    def test_drama_jobs_hide_internal_identifiers_and_do_not_read_raw_logs(self) -> None:
        source = _function_source("initDramaJobsLegacy", "initJobs")
        self.assertIn("data-drama-job-index", source)
        self.assertIn("先查询已提交任务与账单", source)
        self.assertIn("不会自动重试", source)
        self.assertNotIn("trace_id", source)
        self.assertNotIn("/logs/tail", source)
        self.assertNotIn("任务编号", source)
        self.assertNotIn("问题编号", source)
        self.assertIn("data-leave-guard", source)
        self.assertIn('suffix === "/write" ? "episode" : "episode_no"', source)
        self.assertIn("persistence_degraded", source)
        self.assertIn("前往合成页恢复", source)
        self.assertIn('aria-controls="drama-job-detail"', source)
        self.assertIn('token === "submission_unknown" ? "unknown"', static.JS_DASHBOARD)

    def test_drama_job_filters_expose_pressed_state(self) -> None:
        html = self._html("/w/phase-d/jobs")
        self.assertIn('aria-pressed="true" data-job-filter="all"', html)
        self.assertIn('data-job-filter="attention"', html)
        self.assertIn("未知和丢失状态不会自动重试", html)
        self.assertIn('id="jobs-filter-status"', html)


if __name__ == "__main__":
    unittest.main()
