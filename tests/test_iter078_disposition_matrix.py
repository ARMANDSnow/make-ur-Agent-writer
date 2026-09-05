"""iter078 技债-1：处置五分类单一真源（classify_disposition）矩阵。

背景（iter077 铁律⑨审查提名）：五分类（skip_approved / skip_caveat /
补外审 / stale 重写 / block）散在 run_write_book 与 check_write_readiness
两条平行链，已第三次同步手改——iter077 谓词漏 ``failure`` 正是平行维护的
实证。下沉后本矩阵按 status 形态 × force × require_external_review 全覆盖
钉死判定；readiness/run 消费同一函数由 import 级断言保证。
"""

from __future__ import annotations

import unittest
from typing import Any, Dict

from src.chapter_status import ChapterDisposition, classify_disposition


def _status(**overrides: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "chapter_no": 1,
        "exists": True,
        "approved": False,
        "caveat_approved": False,
        "needs_review": True,
        "failure": False,
        "panel_halted": None,
        "verdict": "Reject",
        "rewrite_count": 1,
        "strict_failures": ["external_review_reject"],
    }
    base.update(overrides)
    return base


class DispositionMatrixTests(unittest.TestCase):
    def _c(self, status: Dict[str, Any], *, force: bool = False, rer: bool = True):
        return classify_disposition(status, force=force, require_external_review=rer)

    # ---- force 全形态压倒 ----
    def test_force_always_fresh_write(self) -> None:
        shapes = [
            _status(approved=True, verdict="Approve", strict_failures=[]),
            _status(caveat_approved=True),
            _status(),  # stale reject 形态
            _status(strict_failures=["model_mismatch"]),  # 否则 BLOCK 的形态
            _status(exists=False),
        ]
        for status in shapes:
            with self.subTest(status=status):
                self.assertIs(
                    self._c(status, force=True), ChapterDisposition.FRESH_WRITE
                )

    # ---- skip 两类 ----
    def test_approved_skips(self) -> None:
        status = _status(approved=True, needs_review=False, verdict="Approve", strict_failures=[])
        self.assertIs(self._c(status), ChapterDisposition.SKIP_APPROVED)

    def test_caveat_skips(self) -> None:
        self.assertIs(self._c(_status(caveat_approved=True)), ChapterDisposition.SKIP_CAVEAT)

    def test_approved_wins_over_caveat_flag(self) -> None:
        # 与 run 循环判定顺序一致（approved 先于 caveat）；正常流程两旗标
        # 不会同真（caveat 章 verdict 保持 Reject → approved False）。
        status = _status(
            approved=True, caveat_approved=True, needs_review=False,
            verdict="Approve", strict_failures=[],
        )
        self.assertIs(self._c(status), ChapterDisposition.SKIP_APPROVED)

    # ---- 补外审 ----
    def test_supplement_external_review(self) -> None:
        status = _status(
            verdict="Approve", strict_failures=["external_review_missing"], needs_review=False
        )
        self.assertIs(self._c(status), ChapterDisposition.SUPPLEMENT_EXTERNAL_REVIEW)

    def test_supplement_requires_external_review_flag(self) -> None:
        status = _status(
            verdict="Approve", strict_failures=["external_review_missing"], needs_review=False
        )
        # require_external_review=False 时该 strict failure 本不会出现；若出现
        # （手工构造）也不走补外审——回落 stale 白名单判定
        self.assertIs(self._c(status, rer=False), ChapterDisposition.STALE_REJECT_REWRITE)

    def test_supplement_needs_exact_single_failure(self) -> None:
        status = _status(
            verdict="Approve",
            strict_failures=["external_review_missing", "external_review_stale"],
            needs_review=False,
        )
        # 多重失败不走补外审——但仍在 stale 白名单内 → 归档重写
        self.assertIs(self._c(status), ChapterDisposition.STALE_REJECT_REWRITE)

    # ---- stale reject 白名单（iter077 P0-5 语义原样） ----
    def test_stale_reject_whitelist_shapes(self) -> None:
        for failures in (
            ["external_review_missing"],
            ["external_review_reject"],
            ["external_review_needs_human"],
            ["external_review_stale"],
            ["external_review_reject", "external_review_stale"],
            [],
        ):
            with self.subTest(failures=failures):
                self.assertIs(
                    self._c(_status(strict_failures=failures)),
                    ChapterDisposition.STALE_REJECT_REWRITE,
                )

    def test_mismatch_and_legacy_block(self) -> None:
        for failures in (
            ["model_mismatch"],
            ["review_tier_mismatch"],
            ["plan_fingerprint_mismatch"],
            ["legacy_missing_context"],
            ["human_review_present"],
            ["external_review_reject", "draft_hash_mismatch"],
        ):
            with self.subTest(failures=failures):
                self.assertIs(
                    self._c(_status(strict_failures=failures)), ChapterDisposition.BLOCK
                )

    def test_failure_marker_blocks(self) -> None:
        # iter077 铁律⑨修复：lint 终败（failure.json 在盘）不得自动重写
        self.assertIs(self._c(_status(failure=True)), ChapterDisposition.BLOCK)

    def test_panel_halted_blocks(self) -> None:
        # iter077 铁律⑨修复：halt 分诊结论跨进程存活
        self.assertIs(
            self._c(_status(panel_halted={"reason": "retry_exhausted"})),
            ChapterDisposition.BLOCK,
        )

    def test_missing_verdict_blocks(self) -> None:
        self.assertIs(self._c(_status(verdict=None)), ChapterDisposition.BLOCK)

    # ---- fresh ----
    def test_absent_chapter_is_fresh_write(self) -> None:
        self.assertIs(
            self._c(_status(exists=False, verdict=None, strict_failures=[])),
            ChapterDisposition.FRESH_WRITE,
        )


class SingleSourceWiringTests(unittest.TestCase):
    def test_book_runner_consumes_chapter_status_function(self) -> None:
        # import 级断言：run/readiness 消费的就是 chapter_status 的那一个函数
        from src import book_runner, chapter_status

        self.assertIs(book_runner.classify_disposition, chapter_status.classify_disposition)
        self.assertIs(
            book_runner._is_resumable_stale_reject, chapter_status.is_resumable_stale_reject
        )
        self.assertIs(
            book_runner._RESUMABLE_REJECT_FAILURES, chapter_status.RESUMABLE_REJECT_FAILURES
        )


if __name__ == "__main__":
    unittest.main()
