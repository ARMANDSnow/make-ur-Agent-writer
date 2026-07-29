"""Iteration 159 contracts for the five-station workbench and character library."""

from __future__ import annotations

import unittest
from unittest import mock

from src.web import routes, static, templates


class DramaWebUiuxPhaseBTests(unittest.TestCase):
    def _page(self, renderer, *args):
        with mock.patch("src.web.workspace_meta.read", return_value={"type": "drama"}):
            return renderer(*args)

    def test_write_renders_five_accessible_steps_and_episode_controls(self) -> None:
        html = self._page(
            templates.render_workspace_write,
            "synthetic-drama",
            ["synthetic-drama"],
            2,
        )
        self.assertEqual(html.count('data-station-pane="'), 5)
        for step, label in (
            ("setup", "故事设定"),
            ("hook", "钩子设计"),
            ("storyboard", "分镜脚本"),
            ("characters", "角色设计"),
            ("review", "评审与组装"),
        ):
            self.assertIn(f'data-tab="{step}"', html)
            self.assertIn(label, html)
        self.assertIn('aria-current="step"', html)
        self.assertIn('id="drama-write-episode"', html)
        self.assertIn('id="drama-write-refresh"', html)
        self.assertIn('id="drama-mobile-primary-action"', html)
        self.assertIn("data-leave-guard", html)

    def test_write_keeps_step_recovery_keyboard_and_dirty_contracts(self) -> None:
        js = static.JS_DASHBOARD
        for hook in (
            'url.searchParams.set("step", tabName)',
            'target.searchParams.set("episode", String(value))',
            'target.pathname.endsWith("/characters")',
            '"drama-review-assemble": "review"',
            'await loadStationReview()',
            'status.dataset.uiState = "dirty"',
            'writeStatus.dataset.uiState = "running"',
            'data-drama-dirty="1"',
            'ev.key === "ArrowRight"',
            'tab.setAttribute("aria-current", "step")',
            'pollJob(data.job_id',
        ):
            self.assertIn(hook, js)
        self.assertIn("submission_unknown", js)
        self.assertIn("不会自动重试", js)

    def test_character_library_partitions_current_and_season_roles(self) -> None:
        html = self._page(
            templates.render_workspace_characters,
            "synthetic-drama",
            ["synthetic-drama"],
            3,
        )
        self.assertIn('id="characters-episode-no"', html)
        self.assertIn("当前集角色", static.JS_DASHBOARD)
        self.assertIn("季角色库", static.JS_DASHBOARD)
        self.assertIn("锁定手工修改", static.JS_DASHBOARD)
        self.assertIn("出场集数", static.JS_DASHBOARD)
        self.assertIn("生成状态", static.JS_DASHBOARD)
        self.assertIn("真实参考图已保护", static.JS_DASHBOARD)
        self.assertNotIn("AI 绘画 prompt", html)
        self.assertNotIn("LoRA", html)
        self.assertNotIn("provider response", html)

    def test_character_route_restores_episode_context(self) -> None:
        with (
            mock.patch.object(routes, "_workspace_html_guard", return_value=None),
            mock.patch("src.web.workspace_meta.read", return_value={"type": "drama"}),
            mock.patch.object(routes, "list_workspaces", return_value=["synthetic-drama"]),
        ):
            status, content_type, body = routes.render_workspace_characters_page(
                "synthetic-drama", "2"
            )
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "text/html; charset=utf-8")
        text = body.decode("utf-8")
        self.assertIn('value="2"', text)
        self.assertIn('window.CHAPTER_NO = 2;', text)

    def test_phase_b_styles_remain_drama_scoped(self) -> None:
        css = static.CSS_BODY
        marker = "Iteration 159 · short-drama Phase B"
        self.assertIn(marker, css)
        phase_b = css.split(marker, 1)[1]
        self.assertNotIn(".ui-public", phase_b)
        self.assertNotIn(".ui-novel", phase_b)
        self.assertIn("min-height: 44px", css)
        self.assertIn("outline: 3px solid var(--ui-focus-ring)", css)
        self.assertIn(":is(a, button, input, select, textarea, [tabindex]):focus-visible", css)
        self.assertIn(":is(.btn, button, input, select, textarea, .sidebar-item", css)
        self.assertIn("grid-template-columns: 1fr", phase_b)

    def test_manual_and_paid_image_server_guards_remain_referenced(self) -> None:
        js = static.JS_DASHBOARD
        self.assertIn("manual_override", js)
        self.assertIn("isLocalPreviewImage", js)
        self.assertIn("真实参考图", js)
        self.assertIn("confirmDramaRegenerate", js)
        self.assertIn("当前有未保存修改", js)
        self.assertIn('skipped: "沿用季角色"', js)
        self.assertIn('stale: "内容已变化，需重做"', js)
        self.assertNotIn('条 agent 建议', js)

    def test_sensitive_generation_fields_are_not_rendered_as_edit_controls(self) -> None:
        js = static.JS_DASHBOARD
        self.assertNotIn('data-field="ai_draw_prompt"', js)
        self.assertNotIn('charHidden("prompt_template_sd"', js)
        self.assertNotIn('charHidden("lora_token"', js)
        self.assertIn('ai_draw_prompt: source.ai_draw_prompt || ""', js)
        self.assertIn('prompt_template_sd: get("prompt_template_sd", old.prompt_template_sd)', js)

    def test_character_collection_restores_original_order_after_visual_partition(self) -> None:
        js = static.JS_DASHBOARD
        self.assertIn('card.getAttribute("data-character-card")', js)
        self.assertIn('return left.sourceIndex - right.sourceIndex', js)
        self.assertIn('episodeNo === requestedEpisode', js)
        self.assertIn('requestedEpisode || sheet.episode_no', js)


if __name__ == "__main__":
    unittest.main()
