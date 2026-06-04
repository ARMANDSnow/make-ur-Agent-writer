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


if __name__ == "__main__":
    unittest.main()
