"""iter076 HIGH#1：panel_block_policy——面板拒稿不再无条件 halt 整书。

覆盖：soft/hard 分诊、caveat_continue 放行与预算上限回落、force_once bonus 重写、
caveat 章 resume 跳过、策略加载器坏值回落。全部 mock（铁律③）：chapter_status /
write_chapters 打桩，照 tests/test_book_runner_retry_progress.py 的 fixture 模式。
mock reviewer 永远 Approve，拒稿路径只能靠打桩 status 构造。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

from src import book_runner
from src.book_runner import _panel_block_policy, run_write_book


def _status(
    chapter_no: int,
    *,
    exists: bool,
    approved: bool,
    verdict: str | None = None,
    hard_reject: bool = False,
    caveat_approved: bool = False,
) -> dict:
    return {
        "chapter_no": chapter_no,
        "exists": exists,
        "approved": approved,
        "needs_review": False,
        "failure": False,
        "verdict": verdict or ("Approve" if approved else None),
        "rewrite_count": 0,
        "strict_failures": [],
        "hard_reject": hard_reject,
        "caveat_approved": caveat_approved,
    }


class _RunnerHarness(unittest.TestCase):
    """公共打桩：真实 tmp drafts 目录 + chapter_status 剧本 + write_chapters 计数。"""

    def _run(
        self,
        statuses: list,
        *,
        policy: dict,
        chapters: int = 1,
        max_retries: int = 1,
        seed_metas: dict | None = None,
    ) -> tuple[dict, list, Path]:
        write_calls: list = []

        def fake_write_chapters(**kwargs):
            write_calls.append(kwargs["resume_from"])
            return [{"chapter": kwargs["resume_from"], "written": True}]

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            drafts = root / "outputs" / "drafts"
            drafts.mkdir(parents=True)
            for name, meta in (seed_metas or {}).items():
                (drafts / name).write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
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
                ]:
                    stack.enter_context(patch(target, **kw))
                result = run_write_book(
                    chapters=chapters,
                    max_retries=max_retries,
                    auto_advance=False,
                    require_start_point=False,
                    require_plan=False,
                    require_external_review=False,
                )
            # meta 文件在 tmp 清理前读出，供 caveat 断言。
            metas = {}
            for meta_path in drafts.glob("chapter_*.meta.json"):
                metas[meta_path.name] = json.loads(meta_path.read_text(encoding="utf-8"))
        return result, write_calls, metas


HALT_ALL = {"on_soft_reject": "halt", "max_panel_rejections": 0, "on_hard_reject": "halt"}
CAVEAT_SOFT = {"on_soft_reject": "caveat_continue", "max_panel_rejections": 2, "on_hard_reject": "halt"}


class PanelPolicyRunTests(_RunnerHarness):
    def test_default_policy_halts_on_soft_reject(self) -> None:
        # 现行为回归：重试耗尽（soft）→ blocked + 停全书。
        statuses = [
            _status(1, exists=False, approved=False),
            _status(1, exists=True, approved=False, verdict="Reject"),
            _status(1, exists=True, approved=False, verdict="Reject"),
        ]
        result, write_calls, _ = self._run(statuses, policy=HALT_ALL, max_retries=1)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["blocked"][0]["reason"], "retry_exhausted")
        self.assertEqual(result["caveats"], [])
        self.assertEqual(write_calls, [1, 1])   # 原始 + 1 次重试
        # iter077 P0-3：每个快照回显生效策略——从任何 run 产物可见实际生效值。
        self.assertEqual(result["panel_policy"], HALT_ALL)

    def test_soft_reject_caveat_continue_marks_and_continues(self) -> None:
        # ch1 soft 拒稿耗尽 → caveat 放行；ch2 照常写并 Approve → 整书 succeeded。
        statuses = [
            _status(1, exists=False, approved=False),
            _status(1, exists=True, approved=False, verdict="Reject"),
            _status(1, exists=True, approved=False, verdict="Reject"),
            _status(2, exists=False, approved=False),
            _status(2, exists=True, approved=True),
        ]
        result, write_calls, metas = self._run(
            statuses, policy=CAVEAT_SOFT, chapters=2, max_retries=1
        )
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["blocked"], [])
        self.assertEqual([c["chapter"] for c in result["caveats"]], [1])
        self.assertFalse(result["caveats"][0]["hard_reject"])
        actions = [w["action"] for w in result["chapters"]]
        self.assertEqual(actions, ["written_with_caveats", "written"])
        self.assertEqual(write_calls, [1, 1, 2])
        meta = metas["chapter_01.meta.json"]
        self.assertTrue(meta["caveat_approved"])
        self.assertEqual(meta["caveat_reason"], "panel_soft_reject")
        self.assertIn("caveat_at", meta)

    def test_caveat_budget_exhausted_falls_back_to_halt(self) -> None:
        # max_panel_rejections=1：第 2 章 soft 拒稿时预算用尽 → 回落 halt。
        policy = dict(CAVEAT_SOFT, max_panel_rejections=1)
        statuses = [
            _status(1, exists=False, approved=False),
            _status(1, exists=True, approved=False, verdict="Reject"),
            _status(1, exists=True, approved=False, verdict="Reject"),
            _status(2, exists=False, approved=False),
            _status(2, exists=True, approved=False, verdict="Reject"),
            _status(2, exists=True, approved=False, verdict="Reject"),
        ]
        result, _, _ = self._run(statuses, policy=policy, chapters=2, max_retries=1)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual([c["chapter"] for c in result["caveats"]], [1])
        self.assertEqual(result["blocked"][0]["chapter"], 2)
        self.assertEqual(result["blocked"][0]["reason"], "retry_exhausted")

    def test_hard_reject_halts_even_with_soft_caveat_policy(self) -> None:
        # hard（synthetic 硬拦）不吃 soft 的 caveat 预算：on_hard_reject=halt → 必停。
        statuses = [
            _status(1, exists=False, approved=False),
            _status(1, exists=True, approved=False, verdict="Reject", hard_reject=True),
            _status(1, exists=True, approved=False, verdict="Reject", hard_reject=True),
        ]
        result, _, _ = self._run(statuses, policy=CAVEAT_SOFT, max_retries=1)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["blocked"][0]["reason"], "hard_reject")
        self.assertEqual(result["caveats"], [])

    def test_hard_reject_force_once_grants_single_bonus_attempt(self) -> None:
        # max_retries=0 + force_once：attempt0 hard 拒 → bonus 一轮 → Approve。
        policy = dict(HALT_ALL, on_hard_reject="force_once")
        statuses = [
            _status(1, exists=False, approved=False),
            _status(1, exists=True, approved=False, verdict="Reject", hard_reject=True),
            _status(1, exists=True, approved=True),
        ]
        result, write_calls, _ = self._run(statuses, policy=policy, max_retries=0)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(write_calls, [1, 1])   # 原始 + bonus
        attempts = result["chapters"][0]["attempts"]
        self.assertTrue(any(a.get("bonus_granted") for a in attempts))

    def test_hard_reject_force_once_still_blocks_after_bonus(self) -> None:
        # bonus 用掉仍 hard 拒 → 只给一次，按 hard_reject halt 收场。
        policy = dict(HALT_ALL, on_hard_reject="force_once")
        statuses = [
            _status(1, exists=False, approved=False),
            _status(1, exists=True, approved=False, verdict="Reject", hard_reject=True),
            _status(1, exists=True, approved=False, verdict="Reject", hard_reject=True),
        ]
        result, write_calls, _ = self._run(statuses, policy=policy, max_retries=0)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["blocked"][0]["reason"], "hard_reject")
        self.assertEqual(write_calls, [1, 1])   # 原始 + bonus，无第三次

    def test_caveat_budget_counts_preexisting_caveats_across_runs(self) -> None:
        # 审查 A2a：resume/supervisor 重启后配额不得重置——盘面已有 1 章 caveat +
        # max=1 → 本 run 的 soft 拒稿必须回落 halt（而不是再放行 1 章）。
        policy = dict(CAVEAT_SOFT, max_panel_rejections=1)
        statuses = [
            _status(2, exists=False, approved=False),
            _status(2, exists=True, approved=False, verdict="Reject"),
            _status(2, exists=True, approved=False, verdict="Reject"),
        ]
        result, _, _ = self._run(
            statuses,
            policy=policy,
            max_retries=1,
            seed_metas={
                "chapter_01.meta.json": {
                    "verdict": "Reject",
                    "caveat_approved": True,
                    "caveat_reason": "panel_soft_reject",
                }
            },
        )
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["caveats"], [])   # 本 run 零新放行
        self.assertEqual(result["blocked"][0]["reason"], "retry_exhausted")

    def test_caveat_chapter_skipped_on_resume(self) -> None:
        # resume：盘面存在非 approved 但 caveat_approved 的章 → 跳过不重写，
        # 也不得撞上「存在未 approve 旧产物 → BookRunBlocked」。
        statuses = [
            _status(1, exists=True, approved=False, verdict="Reject", caveat_approved=True),
            _status(2, exists=False, approved=False),
            _status(2, exists=True, approved=True),
        ]
        result, write_calls, _ = self._run(statuses, policy=HALT_ALL, chapters=2, max_retries=0)
        self.assertEqual(result["status"], "succeeded")
        actions = [w["action"] for w in result["chapters"]]
        self.assertEqual(actions, ["skipped_caveat", "written"])
        self.assertEqual(write_calls, [2])   # ch1 零写作


class PanelPolicyLoaderTests(unittest.TestCase):
    def test_missing_config_falls_back_conservative(self) -> None:
        with patch("src.book_runner.load_config", return_value={}):
            policy = _panel_block_policy(emit_stderr=False)
        self.assertEqual(policy["on_soft_reject"], "halt")
        self.assertEqual(policy["max_panel_rejections"], 0)
        self.assertEqual(policy["on_hard_reject"], "halt")
        # iter077 P0-3：键缺失走默认不是手滑——零告警。
        self.assertEqual(policy["config_warnings"], [])

    def test_values_parsed_case_and_dash_tolerant(self) -> None:
        cfg = {
            "panel_block_policy": {
                "on_soft_reject": "CAVEAT-CONTINUE",
                "max_panel_rejections": "2",
                "on_hard_reject": "Force_Once",
            }
        }
        with patch("src.book_runner.load_config", return_value=cfg):
            policy = _panel_block_policy()
        self.assertEqual(policy["on_soft_reject"], "caveat_continue")
        self.assertEqual(policy["max_panel_rejections"], 2)
        self.assertEqual(policy["on_hard_reject"], "force_once")

    def test_garbage_values_fall_back(self) -> None:
        cfg = {
            "panel_block_policy": {
                "on_soft_reject": "bogus",
                "max_panel_rejections": "not-a-number",
                "on_hard_reject": ["halt"],
            }
        }
        with patch("src.book_runner.load_config", return_value=cfg):
            policy = _panel_block_policy(emit_stderr=False)
        self.assertEqual(policy["on_soft_reject"], "halt")
        self.assertEqual(policy["max_panel_rejections"], 0)
        self.assertEqual(policy["on_hard_reject"], "halt")
        # iter077 P0-3：显式给出但解析失败 → 三条告警（不再静默回落）。
        self.assertEqual(len(policy["config_warnings"]), 3)

    def test_non_dict_block_falls_back(self) -> None:
        with patch("src.book_runner.load_config", return_value={"panel_block_policy": "halt"}):
            policy = _panel_block_policy(emit_stderr=False)
        self.assertEqual(policy["on_soft_reject"], "halt")
        self.assertTrue(policy["config_warnings"])

    # ---- iter077 P0-3：配置手滑不再静默失效 ----

    def test_typo_caveat_continue_warns(self) -> None:
        # 六方审查实测场景：少写 caveat_ 前缀 → 静默回落 halt，凌晨第一章软拒
        # 即全书 halt。现在必须有告警可循。
        cfg = {"panel_block_policy": {"on_soft_reject": "continue", "max_panel_rejections": 2}}
        with patch("src.book_runner.load_config", return_value=cfg):
            policy = _panel_block_policy(emit_stderr=False)
        self.assertEqual(policy["on_soft_reject"], "halt")
        self.assertTrue(any("on_soft_reject" in w for w in policy["config_warnings"]))

    def test_bool_max_rejections_warns_and_falls_to_zero(self) -> None:
        # yaml 裸 true 被 int() 静默变 1——是手误不是配额：回落 0 + 告警。
        cfg = {"panel_block_policy": {"max_panel_rejections": True}}
        with patch("src.book_runner.load_config", return_value=cfg):
            policy = _panel_block_policy(emit_stderr=False)
        self.assertEqual(policy["max_panel_rejections"], 0)
        self.assertTrue(any("布尔" in w for w in policy["config_warnings"]))

    def test_caveat_continue_with_zero_budget_warns(self) -> None:
        # 自相矛盾组合：caveat_continue + max<=0 = caveat 永不触发（等效 halt）。
        cfg = {"panel_block_policy": {"on_soft_reject": "caveat_continue"}}
        with patch("src.book_runner.load_config", return_value=cfg):
            policy = _panel_block_policy(emit_stderr=False)
        self.assertEqual(policy["on_soft_reject"], "caveat_continue")
        self.assertTrue(any("永不触发" in w for w in policy["config_warnings"]))

    def test_valid_capstone_config_no_warnings(self) -> None:
        # iter077 capstone 推荐配置：合法组合零告警。
        cfg = {
            "panel_block_policy": {
                "on_soft_reject": "caveat_continue",
                "max_panel_rejections": 2,
                "on_hard_reject": "halt",
            }
        }
        with patch("src.book_runner.load_config", return_value=cfg):
            policy = _panel_block_policy(emit_stderr=False)
        self.assertEqual(policy["config_warnings"], [])

    def test_preflight_surfaces_policy_warnings(self) -> None:
        # preflight 前置校验：解析告警进 warn、生效值进 info（跑之前就能看见）。
        from src.preflight import _check_panel_block_policy

        cfg = {"panel_block_policy": {"on_soft_reject": "continue", "max_panel_rejections": 2}}
        warn: list = []
        info: list = []
        with patch("src.book_runner.load_config", return_value=cfg):
            _check_panel_block_policy(warn, info)
        self.assertTrue(any("on_soft_reject" in w for w in warn))
        self.assertTrue(any("生效值" in i and "on_soft_reject=halt" in i for i in info))


if __name__ == "__main__":
    unittest.main()
