"""iter153: production public/novel design-system and copy contracts."""

from __future__ import annotations

import re
import subprocess
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


    def test_current_step_dynamic_matrix_uses_safe_fallback(self) -> None:
        js = static.JS_DASHBOARD
        start = js.index("function currentStepLabel(")
        end = js.index("  const PAID_NOVEL_JOB_STEPS", start)
        function_source = js[start:end]
        script = function_source + r'''
const STEP_LABELS = {"write-book": "顶层写作", "expand-premise": "顶层扩写"};
function statusLabel(value) { return value === "succeeded" ? "已完成" : "终态"; }
const cases = [
  ["expand", "expand-premise", "running", "扩写故事设定"],
  ["extract:synthetic-secret", "extract", "running", "抽取章节设定"],
  ["compress:part-2", "compress", "running", "构建作品知识库"],
  ["bootstrap:persona", "bootstrap", "running", "生成实体提案"],
  ["debate-round-3", "debate", "running", "生成故事大纲"],
  ["chapter-1/write-attempt-1", "write-book", "running", "撰写章节正文"],
  ["chapter-1/retry-2/review-attempt-3", "write-book", "running", "评审章节"],
  ["chapter-1/style-rewrite", "write-book", "running", "润色章节"],
  ["chapter-1/finalize", "write-book", "running", "整理评审结果"],
  ["internal/secret/token", "write-book", "running", "顶层写作"],
  ["internal/secret/token", "future-step", "running", "任务处理中"],
  ["internal/secret/token", "write-book", "succeeded", "已完成"],
];
for (const [current, parent, status, expected] of cases) {
  const actual = currentStepLabel(current, parent, status);
  if (actual !== expected || actual.includes("secret")) {
    throw new Error(JSON.stringify({current, parent, status, expected, actual}));
  }
}
'''
        result = subprocess.run(
            ["node", "-e", script], text=True, capture_output=True, check=False
        )
        self.assertEqual(result.returncode, 0, result.stderr)

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
