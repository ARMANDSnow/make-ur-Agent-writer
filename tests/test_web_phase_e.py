"""Iteration 156: production contracts for the five novel Phase E pages."""

from __future__ import annotations

import re
import unittest
from unittest import mock

from src.web import static, templates


class NovelPhaseETests(unittest.TestCase):
    def _novel_meta(self):
        return mock.patch("src.web.workspace_meta.read", return_value={"type": "novel"})

    def test_five_pages_share_novel_namespace_and_unique_current_navigation(self) -> None:
        with self._novel_meta():
            pages = (
                templates.render_workspace_continue("alpha", ["alpha"]),
                templates.render_workspace_plan("alpha", ["alpha"]),
                templates.render_workspace_search("alpha", ["alpha"]),
                templates.render_workspace_reviews("alpha", ["alpha"]),
                templates.render_workspace_insights("alpha", ["alpha"]),
            )
        for html in pages:
            self.assertIn('class="app ui-novel"', html)
            self.assertEqual(html.count('aria-current="page"'), 1)

    def test_batch_continue_is_advanced_readiness_first_and_paid(self) -> None:
        with self._novel_meta():
            html = templates.render_workspace_continue("alpha", ["alpha"])
        for text in ("高级入口", "续写章节数", "续写起始章", "检查严格程度", "本次可用额度", "最长等待时间", "检查并继续"):
            self.assertIn(text, html)
        self.assertIn('id="write-book-form"', html)
        self.assertIn('data-ui-action="paid"', html)
        js = static.JS_DASHBOARD
        readiness_pos = js.index("const readiness = await refreshReadiness();")
        confirm_pos = js.index('title: "确认开始续写"', readiness_pos)
        run_pos = js.index('step: "write-book"', confirm_pos)
        self.assertLess(readiness_pos, confirm_pos)
        self.assertLess(confirm_pos, run_pos)
        self.assertIn('setFormSubmitBusy(form, true, "处理中")', js)
        self.assertIn('timeout_minutes: Number(form.elements.timeout_minutes', js)

    def test_plan_edit_is_bounded_and_readonly_sections_stay_readonly(self) -> None:
        with self._novel_meta():
            html = templates.render_workspace_plan("alpha", ["alpha"])
        self.assertIn("章节计划可以编辑", html)
        self.assertIn("全局大纲和创作决定仅供查看", html)
        self.assertNotIn("重新生成并覆盖", html)
        js = static.JS_DASHBOARD
        for hook in ("plan-page-editor", "plan-page-save", "plan-page-cancel", 'wsUrl("/chapter-plan/" + chapterNo)', "data-leave-guard"):
            self.assertIn(hook, js)
        self.assertIn("输入内容仍保留，请检查后重试", js)
        self.assertIn("相关内容检查状态需要更新", js)
        self.assertIn("safeOptionalCount(plan.target_chapters)", js)
        self.assertIn('editor.dataset.dirty !== "1"', js)

    def test_search_empty_query_does_not_fetch_and_results_have_textual_source_and_open(self) -> None:
        with self._novel_meta():
            html = templates.render_workspace_search("alpha", ["alpha"])
        for text in ("原文章节", "续写章节", "人物与故事资料", "清除筛选"):
            self.assertIn(text, html)
        js = static.JS_DASHBOARD
        empty_pos = js.index('if (!q) { showEmpty(')
        fetch_pos = js.index('data = await fetchJson(wsUrl("/search?q="', empty_pos)
        self.assertLess(empty_pos, fetch_pos)
        self.assertIn('action.textContent = "打开"', js)
        self.assertIn("SEARCH_SOURCE_LABELS[source]", js)
        self.assertIn("已有本地内容不受影响", js)

    def test_reviews_expose_only_location_and_no_fake_resolution_action(self) -> None:
        with self._novel_meta():
            html = templates.render_workspace_reviews("alpha", ["alpha"])
        self.assertIn("人物、时间、地点、设定与前后文问题", html)
        js = static.JS_DASHBOARD
        block = js[js.index("async function initReviews()"):js.index("// ===== page: insights")]
        for text in ("严重程度：", "状态待确认", "查看位置", "对应位置"):
            self.assertIn(text, block)
        for forbidden in ("标记已处理", "重新检查", "JSON.stringify", "escapeHtml(raw.rule_id", "agent_name"):
            self.assertNotIn(forbidden, block)
        self.assertIn("#review", block)

    def test_insights_are_readonly_and_unknown_cost_is_not_zero(self) -> None:
        with self._novel_meta():
            html = templates.render_workspace_insights("alpha", ["alpha"])
        self.assertIn("只读统计", html)
        self.assertIn("内容复用情况", html)
        self.assertIn("内容检查分项", html)
        js = static.JS_DASHBOARD
        block = js[js.index("async function initInsights()"):js.index("// ===== page: drama write")]
        self.assertIn("暂无可汇总记录", block)
        self.assertIn("费用待确认", block)
        self.assertNotIn("r.cost_cny || 0", block)
        self.assertIn('typeof r.cost_cny === "number"', block)
        for forbidden in ("data-insight-edit", "采用建议", "model)</td>", "cache_read_tokens"):
            self.assertNotIn(forbidden, block)

    def test_phase_e_responsive_and_shared_accessibility_contract(self) -> None:
        css = static.CSS_BODY
        self.assertIn("Iteration 156 · Phase E", css)
        for selector in (".ui-novel .plan-page-editor", ".ui-novel .search-hit", ".ui-novel .review-issue-card"):
            self.assertIn(selector, css)
        self.assertRegex(css, re.compile(r"\.ui-novel #search-clear,[\s\S]*width: 100%;"))
        self.assertIn("min-height: 44px", css)
        self.assertNotIn(".ui-drama .review-issue-card", css)

    def test_unknown_readiness_fails_closed_before_paid_confirmation(self) -> None:
        js = static.JS_DASHBOARD
        self.assertIn('["ready", "warn"].indexOf(readiness.status) === -1', js)
        self.assertIn('const canProceed = data.status === "ready" || data.status === "warn";', js)
        self.assertIn('return refreshReadiness();', js)


if __name__ == "__main__":
    unittest.main()
