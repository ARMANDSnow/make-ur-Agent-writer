import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from src.book_runner import run_write_book
from src.utils import sha256_text, write_json


class BookRunnerReviewContextTests(unittest.TestCase):
    def test_external_review_receives_source_context(self) -> None:
        for existing in (True, False):
            with self.subTest(existing=existing), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                drafts = root / "outputs" / "drafts"
                reviews = root / "outputs" / "reviews"
                kb_path = root / "data" / "knowledge_base" / "global_knowledge.md"
                drafts.mkdir(parents=True)
                reviews.mkdir(parents=True)
                kb_path.parent.mkdir(parents=True)
                kb_path.write_text("KB-CONTEXT-MARKER", encoding="utf-8")

                draft = "chapter body\n"
                draft_sha = sha256_text(draft)
                run_context = {
                    "schema_version": 1,
                    "chapter_no": 2,
                    "start_chapter_id": "v1_ch003",
                    "start_point_fingerprint": "start-fp",
                    "chapter_plan_item_fingerprint": "item-fp",
                    "plan_fingerprint": "plan-fp",
                }
                plan_item = {
                    "chapter_no": 2,
                    "title": "第二章",
                    "opening_scene": "开场",
                    "key_events": ["事件"],
                    "relationships_in_play": [],
                    "ending_hook": "钩子",
                    "target_chinese_chars": 4000,
                    "plot_purpose": "用途",
                }

                if existing:
                    (drafts / "chapter_02.md").write_text(draft, encoding="utf-8")
                    write_json(
                        drafts / "chapter_02.meta.json",
                        {
                            "verdict": "Approve",
                            "needs_human_review": False,
                            "run_context": run_context,
                            "draft_sha256": draft_sha,
                            "rewrite_count": 0,
                        },
                    )

                captured = []

                def fake_write_chapters(**_kwargs):
                    (drafts / "chapter_02.md").write_text(draft, encoding="utf-8")
                    write_json(
                        drafts / "chapter_02.meta.json",
                        {
                            "verdict": "Reject",
                            "needs_human_review": True,
                            "run_context": run_context,
                            "draft_sha256": draft_sha,
                            "rewrite_count": 0,
                        },
                    )
                    return [{"chapter": 2, "path": str(drafts / "chapter_02.md")}]

                def fake_review_text(_text, _target_name, **kwargs):
                    captured.append(kwargs)
                    write_json(
                        reviews / "chapter_02.review.json",
                        {
                            "verdict": "Approve",
                            "needs_human_review": False,
                            "agent_reviews": [],
                            "run_context": kwargs.get("run_context") or {},
                            "draft_sha256": kwargs.get("draft_sha256") or "",
                        },
                    )
                    return {
                        "verdict": "Approve",
                        "agent_reviews": [],
                        "run_context": kwargs.get("run_context") or {},
                        "draft_sha256": kwargs.get("draft_sha256") or "",
                    }

                ready = {"status": "ready", "blockers": [], "warnings": [], "recommended_commands": []}
                with ExitStack() as stack:
                    stack.enter_context(patch("src.reviewer._reviews_dir", return_value=reviews))
                    stack.enter_context(patch("src.book_runner.check_write_readiness", return_value=ready))
                    stack.enter_context(patch("src.book_runner._load_chapter_plan", return_value={2: plan_item}))
                    stack.enter_context(patch("src.book_runner._run_context", return_value=run_context))
                    stack.enter_context(patch("src.book_runner.paths.workspace_name", return_value="unit"))
                    stack.enter_context(patch("src.book_runner.paths.drafts_dir", return_value=drafts))
                    stack.enter_context(patch("src.book_runner.paths.kb_path", return_value=kb_path))
                    stack.enter_context(patch("src.book_runner._llm_log_line_count", return_value=0))
                    stack.enter_context(patch("src.book_runner.write_chapters", side_effect=fake_write_chapters))
                    stack.enter_context(
                        patch("src.book_runner.start_point.format_chapters_before_start_for_anchor", return_value="SOURCE-CONTEXT-MARKER")
                    )
                    stack.enter_context(
                        patch("src.book_runner.source_excerpts.select_for_chapter", return_value=[{"id": "scene"}])
                    )
                    stack.enter_context(
                        patch("src.book_runner.source_excerpts.format_excerpts_for_prompt", return_value="SCENE-CONTEXT-MARKER")
                    )
                    stack.enter_context(patch("src.reviewer.review_text", side_effect=fake_review_text))
                    stack.enter_context(
                        patch("src.book_runner._snapshot", side_effect=lambda status, payload: {"status": status, **payload})
                    )

                    result = run_write_book(
                        chapters=1,
                        resume_from=2,
                        require_start_point=False,
                        require_plan=False,
                        require_external_review=True,
                        auto_advance=False,
                    )

                self.assertEqual(result["status"], "succeeded")
                self.assertEqual(len(captured), 1)
                self.assertIn("KB-CONTEXT-MARKER", captured[0]["knowledge"])
                self.assertEqual(captured[0]["source_chapters"], "SOURCE-CONTEXT-MARKER")
                self.assertEqual(captured[0]["scene_excerpts"], "SCENE-CONTEXT-MARKER")
                # iter073 (codex B3): external review now runs plan-compliance —
                # the plan item must reach review_text.
                self.assertEqual(captured[0].get("chapter_plan_item"), plan_item)
                # iter073 (codex A2): empty relationships_in_play → strict True
                # (≤4), derived from the plan rather than hardcoded.
                self.assertIs(captured[0].get("enforce_relationship_checklist"), True)


class Iter078FingerprintTests(unittest.TestCase):
    """iter078 P1-6：run_context 指纹补 model/review_tier。

    旧指纹不含配置面——mock 章与真模型章指纹完全相同，换 model/tier 后
    resume 把残迹静默当成品跳过（且 iter077 的 stale-reject 判定把它当
    「同配置」归档重写）。新语义：两键「双方都非空才比对」——旧 meta 缺键
    零迁移，双方都有且不同 → strict failure（不在 stale 白名单 → block）。
    """

    _BASE_CONTEXT = {
        "schema_version": 1,
        "chapter_no": 1,
        "start_chapter_id": "v1_ch003",
        "start_point_fingerprint": "start-fp",
        "chapter_plan_item_fingerprint": "item-fp",
        "plan_fingerprint": "plan-fp",
    }

    def _status_with(self, meta_context: dict, expected_context: dict) -> dict:
        from src.chapter_status import chapter_status

        with tempfile.TemporaryDirectory() as tmp:
            drafts = Path(tmp) / "drafts"
            drafts.mkdir(parents=True)
            draft = "正文\n"
            (drafts / "chapter_01.md").write_text(draft, encoding="utf-8")
            write_json(
                drafts / "chapter_01.meta.json",
                {
                    "verdict": "Approve",
                    "needs_human_review": False,
                    "run_context": meta_context,
                    "draft_sha256": sha256_text(draft),
                    "rewrite_count": 0,
                },
            )
            return chapter_status(
                1,
                drafts,
                validate_context=True,
                require_start_point=True,
                require_plan=True,
                require_external_review=False,
                expected_context=expected_context,
            )

    def test_run_context_carries_model_and_tier(self) -> None:
        from src.writer import _run_context

        with tempfile.TemporaryDirectory() as tmp, patch(
            "src.writer.start_point.get_start_chapter_id", return_value="v1_ch003"
        ), patch(
            "src.writer.start_point.start_point_fingerprint", return_value="start-fp"
        ), patch(
            "src.writer._chapter_plan_path", return_value=Path(tmp) / "absent.json"
        ):
            ctx = _run_context(
                None, chapter_no=3, model="deepseek/deepseek-chat", review_tier="mid"
            )
        self.assertEqual(ctx["model"], "deepseek/deepseek-chat")
        self.assertEqual(ctx["review_tier"], "mid")
        # 缺省调用两键为空串（比对侧跳过）——旧行为字节兼容
        with tempfile.TemporaryDirectory() as tmp, patch(
            "src.writer.start_point.get_start_chapter_id", return_value="v1_ch003"
        ), patch(
            "src.writer.start_point.start_point_fingerprint", return_value="start-fp"
        ), patch(
            "src.writer._chapter_plan_path", return_value=Path(tmp) / "absent.json"
        ):
            legacy = _run_context(None, chapter_no=3)
        self.assertEqual(legacy["model"], "")
        self.assertEqual(legacy["review_tier"], "")

    def test_legacy_meta_without_new_keys_not_mismatch(self) -> None:
        expected = dict(self._BASE_CONTEXT, model="deepseek/deepseek-chat", review_tier="mid")
        status = self._status_with(dict(self._BASE_CONTEXT), expected)
        self.assertTrue(status["approved"])
        self.assertEqual(status["strict_failures"], [])

    def test_model_mismatch_blocks(self) -> None:
        meta_ctx = dict(self._BASE_CONTEXT, model="mock", review_tier="mid")
        expected = dict(self._BASE_CONTEXT, model="deepseek/deepseek-chat", review_tier="mid")
        status = self._status_with(meta_ctx, expected)
        self.assertFalse(status["approved"])
        self.assertIn("model_mismatch", status["strict_failures"])

    def test_tier_mismatch_blocks(self) -> None:
        meta_ctx = dict(self._BASE_CONTEXT, model="mock", review_tier="low")
        expected = dict(self._BASE_CONTEXT, model="mock", review_tier="high")
        status = self._status_with(meta_ctx, expected)
        self.assertFalse(status["approved"])
        self.assertIn("review_tier_mismatch", status["strict_failures"])

    def test_expected_without_new_keys_skips_comparison(self) -> None:
        meta_ctx = dict(self._BASE_CONTEXT, model="mock", review_tier="mid")
        status = self._status_with(meta_ctx, dict(self._BASE_CONTEXT))
        self.assertTrue(status["approved"])

    def test_model_mismatch_not_stale_reject_resumable(self) -> None:
        # mismatch 章必须显式 block（人工裁决 / --force），不得走 iter077 的
        # 「同配置拒稿归档重写」自动路径。
        from src.book_runner import _is_resumable_stale_reject

        status = {
            "exists": True,
            "approved": False,
            "failure": False,
            "panel_halted": None,
            "verdict": "Reject",
            "strict_failures": ["model_mismatch", "external_review_reject"],
        }
        self.assertFalse(_is_resumable_stale_reject(status))


if __name__ == "__main__":
    unittest.main()
