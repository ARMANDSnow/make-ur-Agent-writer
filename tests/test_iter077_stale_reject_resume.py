"""iter077 P0-5：「中断期拒稿残迹」resume 消化回归。

六方审查双方独立确认（A1#2 / A3-F4）：kill 落在「主审 Reject 落盘、下一 attempt
归档未发生」的窗口（含分钟级外审调用期间）时，盘面留下完整非 approved 产物；
fresh resume 的 attempt 0 此前直接 BookRunBlocked → exit 4 → supervisor 终态，
iter076 的「step 超时→自动 resume」恢复链自我终结。修复：指纹与当前 run 一致的
残迹走 attempt>0 同款归档+重写；readiness 同口径豁免为 warning。附带修复
reviewed_existing 补外审被拒绕过 panel_block_policy 的旁路（A3-F4）。

全部 mock（铁律③）。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from src.book_runner import _is_resumable_stale_reject, run_write_book
from src.utils import sha256_file

from tests.test_iter077_caveat_readiness import _WorkspaceHarness


def _status(
    *,
    exists: bool = True,
    approved: bool = False,
    verdict: str | None = "Reject",
    strict_failures: list | None = None,
    hard_reject: bool = False,
    failure: bool = False,
    panel_halted: bool = False,
) -> dict:
    return {
        "chapter_no": 1,
        "exists": exists,
        "approved": approved,
        "needs_review": not approved,
        "failure": failure,
        "verdict": verdict,
        "rewrite_count": 1,
        "strict_failures": strict_failures or [],
        "hard_reject": hard_reject,
        "caveat_approved": False,
        "panel_halted": panel_halted,
    }


class IsResumableStaleRejectTests(unittest.TestCase):
    def test_clean_reject_is_resumable(self) -> None:
        self.assertTrue(_is_resumable_stale_reject(_status()))

    def test_in_flight_external_review_shapes_are_resumable(self) -> None:
        for failures in (
            ["external_review_missing"],
            ["external_review_reject", "external_review_needs_human"],
            ["external_review_stale"],
        ):
            self.assertTrue(
                _is_resumable_stale_reject(_status(strict_failures=failures)),
                msg=failures,
            )

    def test_approve_overruled_by_external_reject_is_resumable(self) -> None:
        self.assertTrue(
            _is_resumable_stale_reject(
                _status(verdict="Approve", strict_failures=["external_review_reject"])
            )
        )

    def test_identity_unverifiable_or_mismatch_stays_blocked(self) -> None:
        for failures in (
            ["legacy_missing_context"],
            ["meta_missing", "legacy_missing_context"],
            ["draft_hash_mismatch"],
            ["draft_hash_missing"],
            ["chapter_plan_item_fingerprint_mismatch"],
            ["start_chapter_id_mismatch"],
            ["human_review_present"],
            ["external_review_reject", "plan_fingerprint_mismatch"],  # 混入 mismatch 即整体拒
        ):
            self.assertFalse(
                _is_resumable_stale_reject(_status(strict_failures=failures)),
                msg=failures,
            )

    def test_missing_verdict_or_absent_or_approved_not_resumable(self) -> None:
        self.assertFalse(_is_resumable_stale_reject(_status(verdict=None)))
        self.assertFalse(_is_resumable_stale_reject(_status(exists=False)))
        self.assertFalse(_is_resumable_stale_reject(_status(approved=True, verdict="Approve")))

    def test_lint_failure_marker_not_resumable(self) -> None:
        # 铁律⑨审查修复：lint 终败章（failure.json 在盘、指纹齐全、strict_failures
        # 恰在白名单内）是「未分诊硬失败」——不得被判可续接自动重写，否则每次
        # resume 重烧一轮注定再终败的重试。
        self.assertFalse(_is_resumable_stale_reject(_status(failure=True)))
        self.assertFalse(
            _is_resumable_stale_reject(
                _status(failure=True, strict_failures=["external_review_missing"])
            )
        )

    def test_panel_halted_marker_not_resumable(self) -> None:
        # 铁律⑨审查修复：重试耗尽后按 halt 停机的章带 panel_halted 落盘标记——
        # 「停下等人」跨进程存活，resume 不得静默重写。
        self.assertFalse(_is_resumable_stale_reject(_status(panel_halted=True)))


HALT_ALL = {"on_soft_reject": "halt", "max_panel_rejections": 0, "on_hard_reject": "halt"}
CAVEAT_SOFT = {"on_soft_reject": "caveat_continue", "max_panel_rejections": 2, "on_hard_reject": "halt"}


class _RunHarness(unittest.TestCase):
    """照 test_book_runner_panel_policy 的 fixture 模式，另落盘 md/meta 供归档。"""

    def _run(
        self,
        statuses: list,
        *,
        policy: dict,
        require_external_review: bool = False,
        seed_files: dict | None = None,
        patches: list | None = None,
    ) -> tuple[dict, list, Path]:
        write_calls: list = []

        def fake_write_chapters(**kwargs):
            write_calls.append(kwargs["resume_from"])
            return [{"chapter": kwargs["resume_from"], "written": True, "seed": kwargs.get("seed_feedback", "")}]

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        drafts = root / "outputs" / "drafts"
        drafts.mkdir(parents=True)
        (root / "outputs" / "reviews").mkdir(parents=True)
        for name, content in (seed_files or {}).items():
            text = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
            (drafts / name).write_text(text, encoding="utf-8")
        with ExitStack() as stack:
            for target, kw in [
                ("src.book_runner.paths.workspace_name", {"return_value": "unit"}),
                ("src.book_runner.paths.workspace_root", {"return_value": root}),
                ("src.book_runner.paths.drafts_dir", {"return_value": drafts}),
                (
                    "src.book_runner.paths.llm_calls_log_path",
                    {"return_value": root / "logs" / "llm_calls.jsonl"},
                ),
                (
                    "src.book_runner.run_preflight",
                    {"return_value": {"status": "ok", "fatal": [], "warn": [], "info": []}},
                ),
                ("src.book_runner._load_raw_chapter_plan", {"return_value": {}}),
                ("src.book_runner._load_chapter_plan", {"return_value": None}),
                ("src.book_runner.chapter_status", {"side_effect": statuses}),
                ("src.book_runner.write_chapters", {"side_effect": fake_write_chapters}),
                ("src.book_runner.prune_from_chapter", {"return_value": None}),
                ("src.book_runner._panel_block_policy", {"return_value": policy}),
                (
                    "src.book_runner._snapshot",
                    {"side_effect": lambda status, payload: {"status": status, **payload}},
                ),
            ] + (patches or []):
                stack.enter_context(patch(target, **kw))
            result = run_write_book(
                chapters=1,
                max_retries=1,
                auto_advance=False,
                require_start_point=False,
                require_plan=False,
                require_external_review=require_external_review,
            )
        return result, write_calls, drafts


class StaleRejectRewriteTests(_RunHarness):
    def test_stale_reject_archived_and_rewritten_not_blocked(self) -> None:
        # 中断期残迹：attempt 0 归档+重写（不 BookRunBlocked），归档 reason 留痕。
        statuses = [
            _status(),                     # 循环入口：Reject 残迹在盘
            _status(approved=True, verdict="Approve"),  # 重写后：Approve
        ]
        result, write_calls, drafts = self._run(
            statuses,
            policy=HALT_ALL,
            seed_files={
                "chapter_01.md": "旧稿正文……",
                "chapter_01.meta.json": {"verdict": "Reject", "needs_human_review": True},
            },
        )
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(write_calls, [1])
        self.assertEqual(result["chapters"][0]["action"], "written")
        # 残迹进 snapshots 且 reason 可溯
        snap_dirs = list((drafts / "snapshots").glob("stale_chapter_01_*"))
        self.assertEqual(len(snap_dirs), 1)
        reason = json.loads((snap_dirs[0] / "archive_reason.json").read_text(encoding="utf-8"))
        self.assertEqual(reason["reason"], "stale_reject_resume")
        self.assertTrue((snap_dirs[0] / "chapter_01.md").exists())

    def test_mismatched_chapter_still_raises(self) -> None:
        # fail-closed 保持：指纹 mismatch 的旧产物照旧 BookRunBlocked。
        from src.book_runner import BookRunBlocked

        statuses = [_status(strict_failures=["chapter_plan_item_fingerprint_mismatch"])]
        with self.assertRaises(BookRunBlocked):
            self._run(
                statuses,
                policy=HALT_ALL,
                seed_files={"chapter_01.md": "旧稿", "chapter_01.meta.json": {"verdict": "Reject"}},
            )

    def test_halted_chapter_resume_stays_blocked(self) -> None:
        # 铁律⑨审查修复端到端：上一 run 按 halt 收场的章（panel_halted 在 meta），
        # 新 run resume 必须 BookRunBlocked——不是归档重写。
        from src.book_runner import BookRunBlocked

        statuses = [_status(panel_halted=True)]
        with self.assertRaises(BookRunBlocked):
            self._run(
                statuses,
                policy=HALT_ALL,
                seed_files={
                    "chapter_01.md": "旧稿",
                    "chapter_01.meta.json": {"verdict": "Reject", "panel_halted": {"reason": "retry_exhausted"}},
                },
            )

    def test_halt_writes_panel_halted_marker(self) -> None:
        # 铁律⑨审查修复：重试耗尽 halt 时把分诊结论落盘（marker 供下次 resume 消费）。
        statuses = [
            _status(exists=False),
            _status(verdict="Reject"),
            _status(verdict="Reject"),
        ]
        result, _, drafts = self._run(statuses, policy=HALT_ALL)
        self.assertEqual(result["status"], "blocked")
        meta = json.loads((drafts / "chapter_01.meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["panel_halted"]["reason"], "retry_exhausted")


class ReviewedExistingPolicyTests(_RunHarness):
    def _reviewed_existing_run(self, policy: dict) -> tuple[dict, list, Path]:
        statuses = [
            dict(_status(verdict="Approve", strict_failures=["external_review_missing"]), needs_review=False),
            _status(verdict="Reject", strict_failures=["external_review_reject"]),
        ]
        return self._run(
            statuses,
            policy=policy,
            require_external_review=True,
            seed_files={
                "chapter_01.md": "正文……",
                "chapter_01.meta.json": {"verdict": "Approve"},
            },
            patches=[
                ("src.book_runner.review_target", {"return_value": {}}),
                ("src.book_runner._sync_meta_with_external_review", {"return_value": {}}),
            ],
        )

    def test_reviewed_existing_reject_goes_through_panel_policy(self) -> None:
        # A3-F4 旁路修复：补外审被拒 + caveat_continue → 放行继续，不再 blocked。
        result, write_calls, drafts = self._reviewed_existing_run(CAVEAT_SOFT)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["blocked"], [])
        self.assertEqual([c["chapter"] for c in result["caveats"]], [1])
        self.assertEqual(result["chapters"][0]["action"], "reviewed_existing_with_caveats")
        self.assertEqual(write_calls, [])  # 只补审，零重写
        meta = json.loads((drafts / "chapter_01.meta.json").read_text(encoding="utf-8"))
        self.assertTrue(meta["caveat_approved"])

    def test_reviewed_existing_reject_halts_under_default_policy(self) -> None:
        # 默认保守策略回归：无 caveat 预算 → blocked（原行为），且 reason 可辨。
        result, _, _ = self._reviewed_existing_run(HALT_ALL)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["blocked"][0]["reason"], "external_review_reject")
        self.assertEqual(result["caveats"], [])


class StaleRejectReadinessTests(_WorkspaceHarness):
    def _seed_reject_with_context(self, *, break_fingerprint: bool = False) -> None:
        from src import book_runner

        self._write_plan()
        md = self.drafts / "chapter_01.md"
        md.write_text("正文……\n", encoding="utf-8")
        plan = book_runner._load_chapter_plan()
        item = book_runner._chapter_plan_item(plan, 1)
        run_context = book_runner._run_context(item, chapter_no=1)
        if break_fingerprint:
            run_context = dict(run_context, chapter_plan_item_fingerprint="deadbeef")
        meta = {
            "verdict": "Reject",
            "needs_human_review": True,
            "rewrite_count": 2,
            "run_context": run_context,
            "draft_sha256": sha256_file(md),
        }
        (self.drafts / "chapter_01.meta.json").write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8"
        )

    def test_fingerprint_matched_stale_reject_warns_not_blocks(self) -> None:
        self._seed_reject_with_context()
        r = self._readiness()
        self.assertNotEqual(r["status"], "blocked")
        self.assertIn("chapter_01:stale_reject_will_rewrite", r["warnings"])

    def test_fingerprint_mismatch_still_blocks(self) -> None:
        self._seed_reject_with_context(break_fingerprint=True)
        r = self._readiness()
        self.assertTrue(
            any("existing_output_not_strict_approved" in b for b in r["blockers"]),
            msg=f"blockers={r['blockers']}",
        )


if __name__ == "__main__":
    unittest.main()
