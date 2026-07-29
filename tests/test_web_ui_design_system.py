"""iter153: production public/novel design-system and copy contracts."""

from __future__ import annotations

import re
import unittest
from html.parser import HTMLParser
from unittest import mock

from src.web import static, templates


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._hidden_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style"}:
            self._hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self._hidden_depth:
            self._hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._hidden_depth:
            self.parts.append(data)

    @property
    def text(self) -> str:
        return " ".join(self.parts)


def _visible_text(html: str) -> str:
    parser = _VisibleText()
    parser.feed(html)
    return parser.text


class WebDesignSystemTests(unittest.TestCase):
    def test_semantic_light_tokens_are_exact(self) -> None:
        css = static.CSS_BODY
        for name, value in {
            "--ui-page-bg": "#FBF7F0",
            "--ui-card-bg": "#FFFEFB",
            "--ui-primary-bg": "#E6EFE9",
            "--ui-paid-bg": "#F8E7D3",
            "--ui-danger-bg": "#F4DCD2",
            "--ui-text": "#2A2520",
            "--ui-text-muted": "#5C544A",
            "--ui-brand-text": "#2E5343",
            "--ui-danger-text": "#A8533D",
            "--ui-focus-ring": "#3F6B5A",
        }.items():
            self.assertIn(f"{name}: {value};", css)

    def test_public_novel_buttons_are_light_and_at_least_44px(self) -> None:
        css = static.CSS_BODY
        self.assertIn(":where(.ui-public, .ui-novel) .btn {", css)
        self.assertRegex(css, r"\.ui-novel\) \.btn \{[^}]*min-height: 44px;[^}]*min-width: 44px;")
        self.assertIn(":where(.ui-public, .ui-novel) button {\n  min-height: 44px;\n  min-width: 44px;", css)
        self.assertIn(".ui-novel) .btn-primary {\n  background: var(--ui-primary-bg);", css)
        self.assertIn(".ui-novel) .btn-paid {\n  background: var(--ui-paid-bg);", css)
        self.assertIn(".ui-novel) .btn-danger {\n  background: var(--ui-danger-bg);", css)
        self.assertIn(".ui-novel) .btn-icon {\n  width: 44px;\n  height: 44px;", css)
        self.assertIn(".ui-novel) a:focus-visible,", css)
        self.assertNotIn(".ui-novel) .btn-primary {\n  background: var(--amber);", css)

    def test_status_copy_is_centralized_and_unknown_fails_closed(self) -> None:
        expected = {
            "pending": "等待中",
            "running": "处理中",
            "succeeded": "已完成",
            "blocked": "需要补充",
            "failed": "未完成",
            "aborted": "已取消",
            "cancelled": "已取消",
            "budget_exceeded": "额度不足",
            "stale": "需要更新",
        }
        for raw, label in expected.items():
            self.assertEqual(static.user_status_label(raw), label)
            self.assertIn(f'{raw}: "{label}"', static.JS_DASHBOARD)
        self.assertEqual(static.user_status_label("new_internal_state"), "状态待确认")
        self.assertIn('return STATUS_LABELS[raw] || "状态待确认";', static.JS_DASHBOARD)
        self.assertIn('return STEP_LABELS[step] || "未识别步骤";', static.JS_DASHBOARD)
        self.assertIn('return labels[String(verdict || "").toLowerCase()] || "状态待确认";', static.JS_DASHBOARD)
        self.assertIn('SEARCH_SOURCE_LABELS[hit.source] || "来源待确认"', static.JS_DASHBOARD)
        self.assertIn('return named[k] || "有一项续写条件需要补充";', static.JS_DASHBOARD)
        self.assertIn('hint: hints[kind] || "请检查当前作品状态后再继续。"', static.JS_DASHBOARD)
        self.assertNotIn("config/agents.yaml", static.JS_DASHBOARD)
        self.assertIn('return "有一项建议需要确认";', static.JS_DASHBOARD)
        self.assertIn('if (document.querySelector(".ui-drama")) return (err && err.message)', static.JS_DASHBOARD)
        self.assertNotIn('"知识库尚未生成（" + err.message', static.JS_DASHBOARD)

    @mock.patch("src.web.workspace_meta.read", return_value={"type": "novel"})
    def test_paid_actions_follow_novel_generation_hooks(self, _read) -> None:
        pages = templates.render_workspace_continue("synthetic", ["synthetic"]) + templates.render_workspace_workbench(
            "synthetic", ["synthetic"]
        ) + templates.render_workspace_chapter_detail("synthetic", 1, ["synthetic"])
        for hook in (
            "plan-submit",
            "prepare-submit",
            "outline-submit",
            "plan-chapters-submit",
            "write-book-submit",
            "draft-save-review",
        ):
            self.assertRegex(pages, rf'id="{hook}" class="btn btn-paid(?: btn-sm)?"')
        self.assertIn('data-ui-action="paid"', pages)
        self.assertIn("function confirmPaidAction", static.JS_DASHBOARD)
        self.assertIn("window.uiConfirmPaidAction = confirmPaidAction", static.JS_DASHBOARD)
        self.assertIn("const PAID_NOVEL_JOB_STEPS = new Set", static.JS_DASHBOARD)
        self.assertIn('"extract", "compress", "bootstrap"', static.JS_DASHBOARD)
        self.assertIn('"auto-pipeline", "prepare-greenfield"', static.JS_DASHBOARD)
        self.assertIn('"auto-pipeline": "导入并初始化作品"', static.JS_DASHBOARD)
        self.assertIn("isPaidNovelJobStep(job.step)", static.JS_DASHBOARD)
        self.assertIn('paidRetry ? "btn-paid" : "btn-secondary"', static.JS_DASHBOARD)
        self.assertIn('paidRetry ? \' data-ui-action="paid"\' : ""', static.JS_DASHBOARD)

    @mock.patch("src.web.workspace_meta.read", return_value={"type": "novel"})
    def test_required_public_and_novel_pages_do_not_show_internal_terms(self, _read) -> None:
        pages = {
            "/": templates.render_landing(),
            "/library": templates.render_index(["synthetic"]),
            "/wizard": templates.render_wizard(),
            "/settings": templates.render_settings(),
            "/trash": templates.render_trash(["synthetic"]),
            "/workbench": templates.render_workspace_workbench("synthetic", ["synthetic"]),
            "/continue": templates.render_workspace_continue("synthetic", ["synthetic"]),
            "/jobs": templates.render_workspace_jobs("synthetic", ["synthetic"]),
            "/overview": templates.render_workspace_overview("synthetic", ["synthetic"]),
            "/plan": templates.render_workspace_plan("synthetic", ["synthetic"]),
            "/chapters": templates.render_workspace_chapters("synthetic", ["synthetic"]),
            "/search": templates.render_workspace_search("synthetic", ["synthetic"]),
            "/chapter/1": templates.render_workspace_chapter_detail("synthetic", 1, ["synthetic"]),
            "/reviews": templates.render_workspace_reviews("synthetic", ["synthetic"]),
            "/insights": templates.render_workspace_insights("synthetic", ["synthetic"]),
        }
        forbidden = (
            "Mock", "Beta", "Lint", "Advisor", "Job", "Provider", "Workspace",
            "Pipeline", "Preflight", "cost", "budget", "stale", "lost", "CNY",
            "token", "write-book", "partial draft", "Insights",
        )
        for route, html in pages.items():
            visible = _visible_text(html)
            with self.subTest(route=route):
                for word in forbidden:
                    self.assertIsNone(re.search(rf"(?i)(?<![a-z]){re.escape(word)}(?![a-z])", visible), visible)
                self.assertIn("ui-public" if route in {"/", "/library", "/wizard", "/settings", "/trash"} else "ui-novel", html)

    @mock.patch("src.web.workspace_meta.read", return_value={"type": "drama"})
    def test_drama_page_keeps_separate_namespace_and_existing_hooks(self, _read) -> None:
        html = templates.render_workspace_write("synthetic-drama", ["synthetic-drama"])
        self.assertIn('class="app ui-drama"', html)
        self.assertIn('data-tab="setup"', html)
        self.assertIn('data-station-pane="storyboard"', html)
        self.assertNotIn("ui-novel", html)

    def test_shared_busy_modal_and_accessibility_hooks_remain(self) -> None:
        js = static.JS_DASHBOARD
        for hook in (
            "data-leave-guard",
            "readinessRequestSeq",
            "writeBookJobRunning",
            "data-cancel-job",
            "data-job-retry",
            "data-job-partial",
            "aria-busy",
            "mountModal",
            'ev.key === "Escape"',
            'aria-label="展开任务详情"',
        ):
            self.assertIn(hook, js)
        self.assertIn("function setFormSubmitBusy", js)
        self.assertIn('backdrop.classList.add("ui-public")', js)
        self.assertIn('backdrop.classList.add("ui-novel")', js)
        self.assertIn('input.value !== originalName', js)
        self.assertIn('confirm: entry', js)
        self.assertIn("function renderNovelStatusDetails", js)
        self.assertIn("function renderNovelUsageDetails", js)
        self.assertNotIn("warnings.map(escapeHtml)", js)
        self.assertNotIn('escapeHtml(job.current_step || "?")', js)
        self.assertNotIn("rewrite ×", js)
        self.assertNotIn("JSON.stringify(it)", js)
        self.assertIn("有一项评审建议需要处理", js)
        self.assertRegex(
            js,
            r"writeBookJobRunning = false;\n        setFormSubmitBusy\(form, false\);\n      \}",
        )

    @mock.patch("src.web.workspace_meta.read", return_value={"type": "novel"})
    def test_current_sidebar_page_is_not_a_repeatable_link(self, _read) -> None:
        html = templates._sidebar(["synthetic"], active_workspace="synthetic", active_section="workbench")
        self.assertIn('<span class="sidebar-item active" aria-current="page">', html)
        self.assertNotIn('class="sidebar-item active" href="/w/synthetic/workbench"', html)


if __name__ == "__main__":
    unittest.main()
