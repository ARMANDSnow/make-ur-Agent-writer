"""Iteration 160 contracts for asset governance and shot media pages."""

from __future__ import annotations

import unittest
from unittest import mock

from src.web import static, templates


class DramaWebUiuxPhaseCTests(unittest.TestCase):
    def _page(self, renderer):
        with mock.patch("src.web.workspace_meta.read", return_value={"type": "drama"}):
            return renderer("synthetic-drama", ["synthetic-drama"])

    def test_phase_c_pages_reuse_drama_shell_and_safe_public_copy(self) -> None:
        pages = (
            (templates.render_workspace_assets, "assets-page-root", "资产治理"),
            (templates.render_workspace_shot_images, "shot-images-page-root", "镜头图片候选"),
            (templates.render_workspace_shot_videos, "shot-videos-page-root", "镜头视频候选"),
        )
        for renderer, root_id, title in pages:
            html = self._page(renderer)
            self.assertIn('class="app ui-drama"', html)
            self.assertIn(f'id="{root_id}"', html)
            self.assertIn(title, html)
            self.assertIn('data-leave-guard', html)
            for forbidden in ("revision guard", "C2 已登记", "D1-D4", "provider task"):
                self.assertNotIn(forbidden, html)

    def test_assets_have_category_master_detail_and_guarded_mutations(self) -> None:
        js = static.JS_DASHBOARD
        css = static.CSS_BODY
        for text in ("角色", "场景", "道具 / 线索", "美术方向"):
            self.assertIn(text, js)
        for hook in (
            'class="asset-item-button"',
            'class="asset-version-row"',
            'data-asset-select',
            'data-asset-status',
            'data-art-scope-toggle',
            '"Content-Type": "application/json"',
            '"X-Drama-Asset-Intent": "mutate-v1"',
            'if (err && err.status === 409)',
        ):
            self.assertIn(hook, js)
        self.assertIn(".asset-section-layout", css)
        self.assertIn('aria-selected="', js)
        self.assertIn('role="group" aria-label="资产类型"', js)
        self.assertIn('aria-pressed="', js)
        self.assertIn('data-section-index="', js)
        self.assertNotIn('data-asset-id="', js)
        self.assertNotIn('data-version-id="', js)
        self.assertIn("项来源暂时无法安全读取；资产变更保持阻断", js)

    def test_shot_images_keep_exact_selection_and_read_only_history(self) -> None:
        js = static.JS_DASHBOARD
        for hook in (
            "历史候选 · 只读",
            "当前首帧",
            "当前尾帧",
            "沿用上一镜尾帧",
            'data-shot-image-select="first"',
            'data-shot-image-select="tail"',
            "data-shot-image-clear-tail",
            "expected_selection_revision",
            "expected_current_binding",
            "expected_manifest_fingerprint",
        ):
            self.assertIn(hook, js)
        self.assertIn("candidate.current", js)
        self.assertIn("overview.mutation_allowed", js)
        self.assertIn('wsHref("/write?episode="', js)
        self.assertIn("entry.issue || entry.selected", js)
        self.assertIn("URL.createObjectURL(await response.blob())", js)
        self.assertIn("data-shot-image-preview", js)
        self.assertNotIn('data-candidate-id="', js)

    def test_shot_videos_keep_selected_visible_safe_preview_and_zero_retry(self) -> None:
        js = static.JS_DASHBOARD
        for hook in (
            "安全派生预览：静音，最长 30 秒",
            "Web 暂不可预览",
            "降级预览 · 不可交付",
            "提交结果待核对，不会自动重试",
            "上一镜尾帧",
            "data-shot-video-load-preview",
            "data-shot-video-select",
            "data-shot-video-clear",
            "expected_current_selection",
            "expected_manifest_fingerprint",
        ):
            self.assertIn(hook, js)
        self.assertIn("entry.issue || !!entry.shot.selected", js)
        self.assertIn("绑定细节未包含在当前安全投影中", js)
        self.assertIn("function publicShotRefs(ids)", js)
        self.assertIn("data-shot-video-preview ", js)
        self.assertIn('fetch(candidate.preview_url, { credentials: "same-origin" })', js)
        self.assertNotIn("provider_task_id", self._page(templates.render_workspace_shot_videos))

    def test_phase_c_responsive_touch_focus_and_keyboard_contracts(self) -> None:
        css = static.CSS_BODY
        js = static.JS_DASHBOARD
        for hook in (
            "@media (max-width: 720px)",
            "@media (min-width: 721px) and (max-width: 1100px)",
            ".drama-media-browser",
            ".media-shot-list",
            ".media-candidate-grid",
            "min-height: 44px",
            "border: 3px solid var(--jade)",
        ):
            self.assertIn(hook, css)
        for hook in (
            "moveListboxSelection",
            'ev.key === "Home"',
            'ev.key === "End"',
            'aria-controls="image-shot-',
            'aria-controls="video-shot-',
            'setAttribute("aria-selected"',
        ):
            self.assertIn(hook, js)


if __name__ == "__main__":
    unittest.main()
