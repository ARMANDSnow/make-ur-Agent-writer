from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from src import paths
from src.web import static
from src.web.insights import collect_insights
from src.web.workspace_ctx import use_workspace


class StaticSubscoreCompatTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._saved_ws_dir = paths.WORKSPACE_DIR
        self._saved_env = os.environ.get("WORKSPACE_NAME")
        os.environ.pop("WORKSPACE_NAME", None)
        paths.WORKSPACE_DIR = Path(self._tmp.name)
        ws = paths.WORKSPACE_DIR / "alpha"
        (ws / "outputs" / "drafts").mkdir(parents=True)
        (ws / "outputs" / "reviews").mkdir(parents=True)
        (ws / "logs").mkdir(parents=True)
        (ws / "data").mkdir(parents=True)
        (ws / "小说txt").mkdir(parents=True)
        (ws / "outputs" / "drafts" / "chapter_01.md").write_text("draft", encoding="utf-8")
        (ws / "outputs" / "reviews" / "chapter_01.review.json").write_text(
            json.dumps(
                {
                    "verdict": "Approve",
                    "agent_reviews": [
                        {
                            "agent_name": "A",
                            "verdict": "Approve",
                            "score": 8,
                            "scores": {"plot": 9, "prose": 7, "fidelity": 8},
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        paths.WORKSPACE_DIR = self._saved_ws_dir
        if self._saved_env is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._saved_env
        self._tmp.cleanup()

    def test_chapter_detail_js_accepts_scores_and_legacy_sub_scores(self) -> None:
        self.assertIn("a.scores && Object.keys(a.scores).length", static.JS_DASHBOARD)
        self.assertIn(": a.sub_scores) || {}", static.JS_DASHBOARD)
        self.assertIn(".subscore-cell-approve", static.CSS_BODY)
        self.assertNotIn('td style="text-align:center;background:', static.JS_DASHBOARD)

    def test_chapter_detail_js_renders_style_drift_panel(self) -> None:
        self.assertIn("function styleDriftBadge", static.JS_DASHBOARD)
        self.assertIn("function renderStyleDriftPanel", static.JS_DASHBOARD)
        self.assertIn('document.getElementById("tab-style")', static.JS_DASHBOARD)
        self.assertIn("baseline_hash", static.JS_DASHBOARD)

    def test_advisor_renderer_filters_entries_and_escapes_source_projection(self) -> None:
        start = static.JS_DASHBOARD.index("// advisor tab")
        end = static.JS_DASHBOARD.index("// history tab", start)
        block = static.JS_DASHBOARD[start:end]
        self.assertIn("meta.rewrite_suggestions.filter(isPlainObject)", block)
        self.assertIn('escapeHtml(s.type || "rewrite")', block)
        self.assertIn('escapeHtml(s._advisor)', block)
        self.assertIn('escapeHtml(s.section || "(整段)")', block)
        self.assertIn('escapeHtml(s.guidance || "")', block)
        self.assertNotIn("target_range", block)
        self.assertNotIn("baseline", block)

    def test_style_rendering_rejects_missing_and_malformed_values(self) -> None:
        js = static.JS_DASHBOARD
        self.assertIn("function finiteStyleNumber", js)
        self.assertIn('value == null || typeof value === "boolean"', js)
        self.assertIn('typeof value === "object"', js)
        self.assertIn("const score = finiteStyleNumber(drift.style_drift_score)", js)
        self.assertIn("const n = finiteStyleNumber(value)", js)
        self.assertIn("drift.top_dimensions.filter(isPlainObject)", js)
        self.assertIn("drift.skipped_dimensions.filter(isPlainObject)", js)
        self.assertIn("文风未检测", js)
        self.assertIn("文风已跳过", js)

    def test_style_hash_deep_link_is_allowlisted(self) -> None:
        js = static.JS_DASHBOARD
        start = js.index("const _ALLOWED_TAB_KEYS")
        end = js.index("];", start)
        self.assertIn('"style"', js[start:end])

    def test_chapter_load_failure_populates_every_panel_and_disables_editor(self) -> None:
        js = static.JS_DASHBOARD
        start = js.index("function renderChapterDetailLoadError")
        end = js.index("// iter 050", start)
        block = js[start:end]
        for panel_id in (
            "chapter-body",
            "tab-review",
            "tab-lint",
            "tab-style",
            "tab-advisor",
            "tab-history",
        ):
            self.assertIn(f'"{panel_id}"', block)
        self.assertIn("area.disabled = true", block)
        self.assertIn("saveBtn.disabled = true", block)
        self.assertIn("saveReviewBtn.disabled = true", block)
        self.assertIn("statusBox.innerHTML = errorHtml", block)

    def test_shared_tabs_sync_aria_and_panel_visibility(self) -> None:
        js = static.JS_DASHBOARD
        start = js.index("function bindHashTabs")
        end = js.index("// ``loadTabPanel``", start)
        block = js[start:end]
        for marker in (
            'setAttribute("role", "tablist")',
            'setAttribute("role", "tab")',
            'setAttribute("aria-controls", target.id)',
            'target.setAttribute("role", "tabpanel")',
            'target.setAttribute("aria-labelledby", tab.id)',
            'setAttribute("aria-selected", selected ? "true" : "false")',
            "panel.hidden = !selected",
            'document.addEventListener("keydown"',
            'ev.key === "ArrowRight"',
            'ev.key === "ArrowLeft"',
            'ev.key === "Home"',
            'ev.key === "End"',
            "next.focus()",
        ):
            self.assertIn(marker, block)

    def test_insights_aggregates_scores_field(self) -> None:
        with use_workspace("alpha"):
            data = collect_insights()
        self.assertEqual(len(data["subscores"]), 1)
        row = data["subscores"][0]
        self.assertEqual(row["chapter"], 1)
        self.assertAlmostEqual(row["plot"], 9.0)
        self.assertAlmostEqual(row["prose"], 7.0)
        self.assertAlmostEqual(row["fidelity"], 8.0)
        self.assertEqual(row["agents"], 1)


if __name__ == "__main__":
    unittest.main()
