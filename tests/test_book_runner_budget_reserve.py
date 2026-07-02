"""iter076 HIGH#2：章前预算预留闸——不足则干净收场，不留半成品。

打桩模式同 tests/test_book_runner_panel_policy.py：estimate_cost_since 控制
「已花」，reserve 配置固定 safety=1.5 / default=2.0（预留 = 3.0）。
"""

from __future__ import annotations

import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from src.book_runner import _budget_reserve_cfg, run_write_book


def _status(chapter_no: int, *, exists: bool, approved: bool) -> dict:
    return {
        "chapter_no": chapter_no,
        "exists": exists,
        "approved": approved,
        "needs_review": False,
        "failure": False,
        "verdict": "Approve" if approved else None,
        "rewrite_count": 0,
        "strict_failures": [],
        "hard_reject": False,
        "caveat_approved": False,
    }


RESERVE_CFG = {"safety_factor": 1.5, "default_chapter_cost_cny": 2.0}


class BudgetReserveTests(unittest.TestCase):
    def _run(
        self,
        statuses: list,
        *,
        budget_cny: float,
        spent_cny: float,
        require_external_review: bool = False,
        seed_draft: bool = False,
    ) -> tuple[dict, list]:
        write_calls: list = []

        def fake_write_chapters(**kwargs):
            write_calls.append(kwargs["resume_from"])
            return [{"chapter": kwargs["resume_from"], "written": True}]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            drafts = root / "outputs" / "drafts"
            drafts.mkdir(parents=True)
            if seed_draft:
                (drafts / "chapter_01.md").write_text("既有稿\n", encoding="utf-8")
            with ExitStack() as stack:
                for target, kw in [
                    ("src.book_runner.review_target", {"return_value": None}),
                    ("src.book_runner._sync_meta_with_external_review", {"return_value": None}),
                    ("src.book_runner._build_review_context", {"return_value": {}}),
                    ("src.book_runner._enforce_checklist_for_plan", {"return_value": True}),
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
                    ("src.book_runner._budget_reserve_cfg", {"return_value": dict(RESERVE_CFG)}),
                    (
                        "src.book_runner.estimate_cost_since",
                        {"return_value": {"cost_cny": spent_cny}},
                    ),
                    (
                        "src.book_runner._snapshot",
                        {"side_effect": lambda status, payload: {"status": status, **payload}},
                    ),
                ]:
                    stack.enter_context(patch(target, **kw))
                result = run_write_book(
                    chapters=1,
                    max_retries=0,
                    budget_cny=budget_cny,
                    auto_advance=False,
                    require_start_point=False,
                    require_plan=False,
                    require_external_review=require_external_review,
                )
        return result, write_calls

    def test_insufficient_reserve_stops_cleanly_before_writing(self) -> None:
        # 预算 10、已花 9.5 → 剩 0.5 < 预留 3.0（1.5×default 2.0）→ 动笔前干净停。
        statuses = [_status(1, exists=False, approved=False)]
        result, write_calls = self._run(statuses, budget_cny=10.0, spent_cny=9.5)
        self.assertEqual(result["status"], "budget_exceeded")
        self.assertTrue(result["reserve_stop"])
        self.assertEqual(result["remaining_cny"], 0.5)
        self.assertEqual(result["reserve_needed_cny"], 3.0)
        self.assertEqual(write_calls, [])              # 零写作、零半成品
        self.assertEqual(result["chapters"], [])

    def test_sufficient_reserve_writes_normally(self) -> None:
        statuses = [
            _status(1, exists=False, approved=False),
            _status(1, exists=True, approved=True),
        ]
        result, write_calls = self._run(statuses, budget_cny=10.0, spent_cny=1.0)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(write_calls, [1])
        self.assertNotIn("reserve_stop", result)

    def test_zero_budget_disables_reserve_gate(self) -> None:
        # budget=0（无上限）→ 预留闸不生效，照常写。
        statuses = [
            _status(1, exists=False, approved=False),
            _status(1, exists=True, approved=True),
        ]
        result, write_calls = self._run(statuses, budget_cny=0.0, spent_cny=999.0)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(write_calls, [1])

    def test_skip_approved_chapter_does_not_consume_reserve(self) -> None:
        # 已 approve 的章（resume 场景）零花费——即使剩余预算 < 预留也应跳过成功，
        # 预留闸只拦「真正要写」的章。
        statuses = [_status(1, exists=True, approved=True)]
        result, write_calls = self._run(statuses, budget_cny=10.0, spent_cny=9.5)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["chapters"][0]["action"], "skipped_approved")
        self.assertEqual(write_calls, [])

    def test_reviewed_existing_not_blocked_by_full_chapter_reserve(self) -> None:
        # 审查 A3：既有面板 Approve 稿只差补外审（花外审零头）——不得被整章额度的
        # 预留闸误停。剩余 0.5 < 预留 3.0 也要走 reviewed_existing 并收口 succeeded。
        pre = _status(1, exists=True, approved=False)
        pre["verdict"] = "Approve"
        pre["strict_failures"] = ["external_review_missing"]
        post = _status(1, exists=True, approved=True)
        result, write_calls = self._run(
            [pre, post],
            budget_cny=10.0,
            spent_cny=9.5,
            require_external_review=True,
            seed_draft=True,
        )
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["chapters"][0]["action"], "reviewed_existing")
        self.assertNotIn("reserve_stop", result)
        self.assertEqual(write_calls, [])   # 零整章重写


class BudgetReserveCfgTests(unittest.TestCase):
    def test_negative_default_falls_back_not_clamped(self) -> None:
        # 审查 B L4：负 default = 坏值回落 2.0（与 yaml note 口径一致），
        # 不是 clamp 成 0（0 是合法显式值）。
        from unittest.mock import patch

        with patch(
            "src.book_runner.load_config",
            return_value={"budget_reserve": {"default_chapter_cost_cny": -5}},
        ):
            cfg = _budget_reserve_cfg()
        self.assertEqual(cfg["default_chapter_cost_cny"], 2.0)
        with patch(
            "src.book_runner.load_config",
            return_value={"budget_reserve": {"default_chapter_cost_cny": 0}},
        ):
            cfg = _budget_reserve_cfg()
        self.assertEqual(cfg["default_chapter_cost_cny"], 0.0)


if __name__ == "__main__":
    unittest.main()
