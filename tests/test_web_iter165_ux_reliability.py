"""Iter165 static contracts for navigation, dirty state and fail-closed UX."""

from __future__ import annotations

import unittest

from src.web.static import JS_DASHBOARD
from src.web.templates import render_workspace_workbench


class Iter165UxReliabilityTests(unittest.TestCase):
    def test_navigation_is_classified_before_active_job_lookup(self) -> None:
        self.assertIn("function classifyNavigation", JS_DASHBOARD)
        self.assertIn('return "same-document"', JS_DASHBOARD)
        self.assertIn('return "same-workspace"', JS_DASHBOARD)
        self.assertIn('return "switch-workspace"', JS_DASHBOARD)
        self.assertIn("continueNavigation(href, kind)", JS_DASHBOARD)
        self.assertIn('kind === "same-workspace"', JS_DASHBOARD)

    def test_dirty_registry_covers_all_novel_editors(self) -> None:
        for key in (
            '"draft"',
            '"plan-page"',
            '"workbench-kb"',
            '"workbench-expansion"',
            '"workbench-style"',
            '"workbench-outline"',
            '"workbench-entity-"',
            '"workbench-rel-"',
            '"workbench-inline-plan"',
        ):
            self.assertIn(key, JS_DASHBOARD)
        self.assertIn("保存全部并继续", JS_DASHBOARD)
        self.assertIn("failed.push(editor)", JS_DASHBOARD)
        self.assertIn("if (!stillDirty) continue", JS_DASHBOARD)
        self.assertIn('new Event("input", { bubbles: true })', JS_DASHBOARD)

    def test_workbench_starts_locked_and_hydration_is_fail_closed(self) -> None:
        html = render_workspace_workbench("alpha", ["alpha"])
        for control in (
            "prepare-submit",
            "outline-submit",
            "plan-chapters-submit",
            "write-book-submit",
            "kb-save",
            "outline-save",
        ):
            marker = f'id="{control}"'
            snippet = html[html.index(marker) : html.index(marker) + 220]
            self.assertIn("disabled", snippet, control)
        self.assertIn('fetchJson(wsUrl("/workbench"))', JS_DASHBOARD)
        self.assertIn('fetchJson(wsUrl("/jobs/active"))', JS_DASHBOARD)
        self.assertIn('fetchJson(wsUrl("/jobs/recent?n=1"))', JS_DASHBOARD)
        self.assertIn('recentJob.reconciliation_reason === "worker_restart"', JS_DASHBOARD)
        self.assertIn("状态读取失败，所有修改操作已锁定", JS_DASHBOARD)
        self.assertIn("watchRecoveredWorkbenchJob", JS_DASHBOARD)

    def test_notifications_and_mobile_menus_are_bounded_and_accessible(self) -> None:
        self.assertIn("toastRegistry", JS_DASHBOARD)
        self.assertIn("stack.children.length > 3", JS_DASHBOARD)
        self.assertIn('setAttribute("aria-expanded"', JS_DASHBOARD)
        self.assertIn("inertAppSiblings([sidebar, overlay], sidebarInerted)", JS_DASHBOARD)
        self.assertIn("inertMainSiblings([topbar], topbarInerted)", JS_DASHBOARD)
        self.assertIn("inertAppSiblings([main], topbarInerted)", JS_DASHBOARD)


if __name__ == "__main__":
    unittest.main()
