"""Iteration 154: production contracts for the five public Web pages."""

from __future__ import annotations

import os
import re
import tempfile
import time
import unittest
from html.parser import HTMLParser
from pathlib import Path
from unittest import mock

from src.web import routes, static, templates


class _VisibleText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.hidden = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag in {"script", "style"}:
            self.hidden += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data: str) -> None:
        if not self.hidden:
            self.parts.append(data)


def _visible(html: str) -> str:
    parser = _VisibleText()
    parser.feed(html)
    return " ".join(parser.parts)


class PublicPhaseCTests(unittest.TestCase):
    def _pages(self) -> dict[str, str]:
        return {
            "/": templates.render_landing(),
            "/library": templates.render_index(["synthetic"]),
            "/wizard": templates.render_wizard(),
            "/settings": templates.render_settings(),
            "/trash": templates.render_trash(["synthetic"]),
        }

    def test_five_pages_share_public_namespace_and_one_current_item(self) -> None:
        for route, html in self._pages().items():
            with self.subTest(route=route):
                self.assertIn("ui-public", html)
                self.assertEqual(html.count('aria-current="page"'), 1)
                self.assertNotRegex(html, r"<a[^>]+aria-current=\"page\"")

    def test_visible_copy_avoids_internal_english_terms(self) -> None:
        forbidden = (
            "Mock", "Beta", "Lint", "Advisor", "Job", "Provider", "Workspace",
            "Pipeline", "Preflight", "cost", "budget", "stale", "lost", "CNY",
            "token", "write-book", "partial draft", "Insights",
        )
        for route, html in self._pages().items():
            visible = _visible(html)
            for word in forbidden:
                with self.subTest(route=route, word=word):
                    self.assertIsNone(re.search(rf"(?i)(?<![a-z]){re.escape(word)}(?![a-z])", visible))


    def test_library_uses_safe_card_projection_and_recoverable_states(self) -> None:
        html = templates.render_index(["synthetic"])
        self.assertIn('id="library-search"', html)
        self.assertIn('id="workspace-shelf" class="workspace-list"', html)
        self.assertNotIn('<aside class="sidebar">', html)
        js = static.JS_DASHBOARD
        for marker in (
            'class="public-work-card"', "最近更新", "当前进度", "作品类型",
            "作品列表没有读取成功", "已有本地作品不会因此改变", "publicDateLabel",
        ):
            self.assertIn(marker, js)
        self.assertNotIn("w.path", js)
        self.assertIn('statusBadge(status || "unknown")', js)
        self.assertIn('type === "novel" ? "novel" : "unknown"', js)
        self.assertIn("确认前不会打开作品", js)


    def test_settings_projects_only_safe_editable_preferences(self) -> None:
        html = templates.render_settings()
        visible = _visible(html)
        self.assertIn("使用设置", visible)
        self.assertIn("离线模式", visible)
        self.assertIn("尚未开始", visible)
        self.assertIn('id="settings-form"', html)
        js = static.JS_SETTINGS
        self.assertIn("逐步显示生成内容", js)
        self.assertIn("每次重新准备上下文", js)
        self.assertIn("单章文字量上限", js)
        self.assertIn("连接设置（高级）", js)
        self.assertIn("页面不会回显已保存内容", js)
        self.assertNotIn("secretKeys", js)
        self.assertNotIn("默认文字生成密钥", js)
        self.assertIn('form.setAttribute("aria-busy", "true")', js)
        self.assertIn("没有需要保存的修改", js)
        self.assertIn("设置没有保存；当前输入已保留", js)
        self.assertIn("if (submit) submit.disabled = true", js)

    def test_trash_actions_have_distinct_confirmation_semantics(self) -> None:
        html = templates.render_trash(["synthetic"])
        self.assertNotIn('<aside class="sidebar">', html)
        js = static.JS_DASHBOARD
        self.assertIn("function showRestoreModal", js)
        self.assertIn("确认恢复", js)
        self.assertIn("function showPurgeModal", js)
        self.assertIn("确认永久删除", js)
        self.assertIn("input.value !== originalName", js)
        self.assertIn("{ confirm: entry }", js)
        self.assertIn("其他作品不会受到影响", js)
        self.assertIn("作品内容仍保留在回收站中", js)
        self.assertIn("canClose: function () { return !committed; }", js)
        self.assertIn("cancel.disabled = true", js)
        self.assertNotIn("<table class=\"table\"", js[js.index("async function reloadTrashList"):js.index("function showRestoreModal")])

    def test_public_controls_and_narrow_layout_keep_44px_targets(self) -> None:
        css = static.CSS_BODY
        self.assertRegex(css, r"\.ui-novel\) \.btn \{[^}]*min-height: 44px;[^}]*min-width: 44px;")
        self.assertIn(".ui-public .public-work-card", css)
        self.assertIn(".ui-public .trash-card", css)
        self.assertIn("@media (max-width: 1199px)", css)
        self.assertIn("@media (max-width: 767px)", css)
        self.assertIn("flex-direction: column; align-items: stretch", css)
        self.assertIn(".ui-public .field-check", css)
        self.assertIn(".ui-public .breadcrumb a", css)

    @mock.patch("src.web.workspace_meta.read", return_value={"type": "novel"})
    def test_phase_d_e_pages_and_leave_guard_hooks_remain(self, _read) -> None:
        workbench = templates.render_workspace_workbench("synthetic", ["synthetic"])
        chapter = templates.render_workspace_chapter_detail("synthetic", 1, ["synthetic"])
        self.assertIn('id="stage-prepare-card"', workbench)
        self.assertIn('data-leave-guard', workbench)
        self.assertIn('id="draft-save"', chapter)
        self.assertIn("readinessRequestSeq", static.JS_DASHBOARD)
        self.assertIn("writeBookJobRunning", static.JS_DASHBOARD)

    def test_public_updated_time_reads_artifact_without_following_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "work"
            outputs = root / "outputs"
            outputs.mkdir(parents=True)
            target = Path(tmp) / "outside"
            target.mkdir()
            plan = target / "chapter_plan.json"
            plan.write_text("{}", encoding="utf-8")
            (outputs / "debate").symlink_to(target, target_is_directory=True)
            future = 4_102_444_800
            os.utime(plan, (future, future))
            self.assertNotEqual(
                routes._workspace_updated_at(root),
                time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(future)),
            )

    def test_public_updated_time_includes_existing_draft_edits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "work"
            drafts = root / "outputs" / "drafts"
            drafts.mkdir(parents=True)
            draft = drafts / "chapter_01.md"
            draft.write_text("first", encoding="utf-8")
            edited = int(time.time()) + 10
            os.utime(draft, (edited, edited))
            self.assertEqual(
                routes._workspace_updated_at(root),
                time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(edited)),
            )

    def test_public_updated_time_includes_existing_plan_edits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "work"
            debate = root / "outputs" / "debate"
            debate.mkdir(parents=True)
            plan = debate / "chapter_plan.json"
            plan.write_text("{}", encoding="utf-8")
            edited = int(time.time()) + 20
            os.utime(plan, (edited, edited))
            self.assertEqual(
                routes._workspace_updated_at(root),
                time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(edited)),
            )


    def test_unknown_workspace_type_blocks_direct_domain_reads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            workspace_root = Path(tmp) / "workspaces"
            bad_data = workspace_root / "bad" / "data"
            bad_data.mkdir(parents=True)
            (bad_data / "workspace.json").write_text("not-json", encoding="utf-8")
            with mock.patch.object(routes.paths, "WORKSPACE_DIR", workspace_root):
                status, _ct, body = routes.render_workspace_overview("bad")
                self.assertEqual(status, 404)
                status, _ct, body = routes.api_workspace_insights("bad")
                self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
