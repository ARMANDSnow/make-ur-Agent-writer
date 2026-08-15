"""Iteration 155: production contracts for the five novel Phase D pages."""

from __future__ import annotations

import unittest
from unittest import mock

from src.web import static, templates


class NovelPhaseDTests(unittest.TestCase):
    def _novel_meta(self):
        return mock.patch("src.web.workspace_meta.read", return_value={"type": "novel"})

    def test_five_pages_share_novel_namespace_and_unique_current_navigation(self) -> None:
        with self._novel_meta():
            pages = (
                templates.render_workspace_overview("alpha", ["alpha"]),
                templates.render_workspace_workbench("alpha", ["alpha"]),
                templates.render_workspace_chapters("alpha", ["alpha"]),
                templates.render_workspace_chapter_detail("alpha", 1, ["alpha"]),
                templates.render_workspace_jobs("alpha", ["alpha"]),
            )
        for html in pages:
            self.assertIn('class="app ui-novel"', html)
            self.assertEqual(html.count('aria-current="page"'), 1)

    def test_workbench_preserves_exact_four_stage_contract_and_paid_hooks(self) -> None:
        with self._novel_meta():
            html = templates.render_workspace_workbench("alpha", ["alpha"])
        for label in ("准备设定", "生成大纲", "生成细纲", "撰写正文"):
            self.assertIn(label, html)
        for hook in ("prepare-form", "outline-form", "plan-chapters-form", "write-book-form"):
            self.assertIn(f'id="{hook}"', html)
        self.assertEqual(html.count('class="card workbench-stage-card"'), 4)
        self.assertIn("任务开始后可以离开此页", html)
        self.assertIn('data-ui-action="paid"', html)

    def test_chapters_editor_and_jobs_expose_user_safe_phase_d_controls(self) -> None:
        with self._novel_meta():
            chapters = templates.render_workspace_chapters("alpha", ["alpha"])
            detail = templates.render_workspace_chapter_detail("alpha", 2, ["alpha"])
            jobs = templates.render_workspace_jobs("alpha", ["alpha"])
        for text in ("原文章节", "续写章节", "清除筛选", "最近更新"):
            self.assertIn(text, chapters)
        for text in ("正文", "编辑", "内容检查", "文字检查", "文风", "修改建议", "保存记录"):
            self.assertIn(text, detail)
        self.assertIn('data-leave-guard', detail)
        self.assertIn("overview-recent-chapter", templates.render_workspace_overview("alpha", ["alpha"]))
        for text in ("全部", "处理中", "已完成", "需要处理", "按已保存状态"):
            self.assertIn(text, jobs)
        for forbidden in ("任务编号", "问题编号", "最近生成调用"):
            self.assertNotIn(forbidden, jobs)

    def test_shared_js_keeps_recovery_guard_busy_and_safe_unknown_semantics(self) -> None:
        js = static.JS_DASHBOARD
        for hook in (
            "data-leave-guard",
            "data-cancel-job",
            "data-job-retry",
            "aria-busy",
            "confirmPaidRetry",
            "状态待确认",
            "不会自动重新开始任何任务",
            "正在检查是否可以继续",
            "write-book-open-chapter",
            "正在处理",
            "可以开始",
        ):
            self.assertIn(hook, js)
        self.assertIn("function bindJobFilters", js)
        self.assertIn("function bindChapterFilter", js)
        self.assertIn('saveState("没有保存成功。编辑内容仍保留，请重试。"', js)
        for choice in ("继续编辑", "放弃修改", "保存全部并继续"):
            self.assertIn(choice, js)
        self.assertIn("area._saveBeforeLeave", js)
        self.assertIn("dirtyEditorRegistry", js)
        self.assertIn("classifyNavigation", js)
        self.assertIn('form.setAttribute("aria-busy", "true")', js)
        self.assertIn("已保存，但检查没有开始", js)
        self.assertIn("safeOptionalCount", js)
        self.assertNotIn("评分 ' + (a.score == null", js)



if __name__ == "__main__":
    unittest.main()
