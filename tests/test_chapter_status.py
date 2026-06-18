"""Iter 019: chapter_status helper regression tests.

The unattended write loop (scripts/write_book.sh) reads this helper's
output via the `chapter-status` subcommand to decide skip / retry /
gave-up. The contract is the dict shape and the four state combinations.
"""

import json
import tempfile
import unittest
from pathlib import Path

from src.chapter_status import chapter_status
from src.utils import sha256_text


class ChapterStatusTests(unittest.TestCase):
    def test_missing_chapter_reports_not_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status = chapter_status(7, Path(tmp))
        self.assertEqual(status["chapter_no"], 7)
        self.assertFalse(status["exists"])
        self.assertFalse(status["approved"])
        self.assertFalse(status["failure"])
        self.assertIsNone(status["verdict"])

    def test_approve_meta_without_failure_file_is_approved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            drafts = Path(tmp)
            (drafts / "chapter_03.md").write_text("body\n", encoding="utf-8")
            (drafts / "chapter_03.meta.json").write_text(
                json.dumps(
                    {
                        "verdict": "Approve",
                        "needs_human_review": False,
                        "rewrite_count": 0,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            status = chapter_status(3, drafts)
        self.assertTrue(status["exists"])
        self.assertTrue(status["approved"])
        self.assertFalse(status["failure"])
        self.assertEqual(status["verdict"], "Approve")

    def test_failure_file_marks_not_approved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            drafts = Path(tmp)
            (drafts / "chapter_05.md").write_text("draft body\n", encoding="utf-8")
            (drafts / "chapter_05.meta.json").write_text(
                json.dumps(
                    {
                        "verdict": "Reject",
                        "needs_human_review": True,
                        "rewrite_count": 3,
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            (drafts / "chapter_05.failure.json").write_text("{}", encoding="utf-8")
            status = chapter_status(5, drafts)
        self.assertTrue(status["exists"])
        self.assertTrue(status["failure"])
        self.assertTrue(status["needs_review"])
        self.assertFalse(status["approved"])
        self.assertEqual(status["verdict"], "Reject")
        self.assertEqual(status["rewrite_count"], 3)

    def test_strict_mode_rejects_legacy_approved_meta(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            drafts = Path(tmp)
            (drafts / "chapter_01.md").write_text("body\n", encoding="utf-8")
            (drafts / "chapter_01.meta.json").write_text(
                json.dumps({"verdict": "Approve", "needs_human_review": False}),
                encoding="utf-8",
            )
            status = chapter_status(
                1,
                drafts,
                validate_context=True,
                require_start_point=True,
                require_plan=True,
            )
        self.assertFalse(status["approved"])
        self.assertIn("legacy_missing_context", status["strict_failures"])

    def test_strict_mode_requires_matching_hash_and_external_review(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            drafts = root / "drafts"
            reviews = root / "reviews"
            drafts.mkdir()
            reviews.mkdir()
            draft = "body\n"
            ctx = {
                "start_chapter_id": "v1_ch003",
                "start_point_fingerprint": "start-fp",
                "chapter_plan_item_fingerprint": "item-fp",
                "plan_fingerprint": "plan-fp",
            }
            (drafts / "chapter_02.md").write_text(draft, encoding="utf-8")
            (drafts / "chapter_02.meta.json").write_text(
                json.dumps(
                    {
                        "verdict": "Approve",
                        "needs_human_review": False,
                        "run_context": ctx,
                        "draft_sha256": sha256_text(draft),
                    }
                ),
                encoding="utf-8",
            )
            (reviews / "chapter_02.review.json").write_text(
                json.dumps(
                    {
                        "verdict": "Approve",
                        "run_context": ctx,
                        "draft_sha256": sha256_text(draft),
                    }
                ),
                encoding="utf-8",
            )
            status = chapter_status(
                2,
                drafts,
                validate_context=True,
                require_start_point=True,
                require_plan=True,
                require_external_review=True,
                expected_context=ctx,
            )
        self.assertTrue(status["approved"])
        self.assertEqual(status["strict_failures"], [])

    def test_replan_append_keeps_written_chapter_approved(self) -> None:
        """iter057 P0-A 真实校验链: replan append 后,已写章经**真实** chapter_status
        仍 approved、无 plan_fingerprint_mismatch。

        bug 真正触发的环节:expected(append 后 live plan 的 plan_fingerprint) vs
        stored(写章时冻结的 plan_fingerprint)。现有 book_runner replan 测试 mock 掉
        chapter_status,测不到这里(伪覆盖)。新算法只哈希全局上下文,故两个 plan_fingerprint
        必相等 → 不 mismatch。修复前(哈希全列表)ch1-3 与 ch1-8 指纹不同 → 此测试红。"""
        from src.plot_planner import plan_fingerprint

        globals_ctx = {
            "overall_arc": "原始 arc",
            "start_chapter_id": "v1_ch003",
            "start_point_fingerprint": "start-fp-abc",
        }
        with tempfile.TemporaryDirectory() as tmp:
            drafts = Path(tmp) / "drafts"
            drafts.mkdir()
            # 写 ch1 当时的 plan(ch1-3)→ 冻结进 meta 的 plan_fingerprint
            plan_at_write = {**globals_ctx, "target_chapters": 3,
                             "chapters": [{"chapter_no": i} for i in (1, 2, 3)]}
            fp_at_write = plan_fingerprint(plan_at_write)
            draft = "正文\n"
            ctx_frozen = {
                "start_chapter_id": "v1_ch003",
                "start_point_fingerprint": "start-fp-abc",
                "chapter_plan_item_fingerprint": "item-fp-ch1",
                "plan_fingerprint": fp_at_write,
            }
            (drafts / "chapter_01.md").write_text(draft, encoding="utf-8")
            (drafts / "chapter_01.meta.json").write_text(
                json.dumps({
                    "verdict": "Approve",
                    "needs_human_review": False,
                    "run_context": ctx_frozen,
                    "draft_sha256": sha256_text(draft),
                }),
                encoding="utf-8",
            )
            # replan append 5 章 → plan(ch1-8),全局上下文不变
            plan_after_replan = {**globals_ctx, "target_chapters": 8,
                                 "chapters": [{"chapter_no": i} for i in range(1, 9)]}
            fp_after_replan = plan_fingerprint(plan_after_replan)
            # P0-A 核心不变量:append 前后 plan_fingerprint 相等(只哈希全局上下文)
            self.assertEqual(fp_after_replan, fp_at_write)
            # expected = append 后 live plan 的指纹(_run_context 取 stored plan_fingerprint)
            expected = {**ctx_frozen, "plan_fingerprint": fp_after_replan}
            status = chapter_status(
                1, drafts, validate_context=True, expected_context=expected
            )
        self.assertEqual(status["strict_failures"], [])
        self.assertTrue(status["approved"])


if __name__ == "__main__":
    unittest.main()
