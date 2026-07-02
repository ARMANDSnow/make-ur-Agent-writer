"""iter065 #6a: 计划履约 reviewer（确定性、非阻断的建议级信号）测试。

设计（iter065 收官审查 P2 改正后）：plan-compliance 是 **建议级** 信号，把"在
正文中几乎找不到"的计划 beat 作为 advisor 风格 rewrite_suggestion 暴露——写进
review.json、仅在本就要重写时喂回写手，**绝不翻转 verdict / 不硬 block**（粗略
bigram 词法探针不能硬拒"忠实但戏剧化"的好稿，= 我们推迟 (b) 想避免的误报风险）。

两层：
1. 纯函数 `_plan_compliance_misses` / `_beat_coverage` —— 覆盖度判定 + 自跳过。
2. 集成（经 `review_text`）—— 建议是否进 rewrite_suggestions、是否 **不** 翻转
   verdict、chapter_plan_item=None 时是否字节级自跳过。
"""

import unittest
from unittest.mock import patch

from src.reviewer import (
    COVER_THRESHOLD,
    _beat_coverage,
    _plan_compliance_misses,
    review_text,
)


# 把 beat 内容嵌进正文 → 高覆盖（即便换序/加字）。
_COVERED_DRAFT = (
    "路明非在青铜与火之歌的余烬里缓缓苏醒过来，四下一片死寂。"
    "良久，绘梨衣的白色裙摆在风中消散成灰烬，像一句没说完的话。"
)
# 与下面两个 beat 几乎无公共字符的无关正文 → 近零覆盖 → 判 miss。
_UNRELATED_DRAFT = "今天天气晴朗，几个同学坐在食堂边喝奶茶边闲聊周末打算去哪。"

_BEAT_A = "路明非在青铜与火之歌里苏醒"
_BEAT_B = "绘梨衣的白色裙摆消散成灰烬"


class BeatCoverageTests(unittest.TestCase):
    def test_empty_beat_treated_as_covered(self) -> None:
        self.assertEqual(_beat_coverage("", "任意正文"), 1.0)

    def test_present_beat_high_coverage(self) -> None:
        self.assertGreaterEqual(_beat_coverage(_BEAT_A, _COVERED_DRAFT), 0.8)

    def test_absent_beat_below_threshold(self) -> None:
        self.assertLess(_beat_coverage(_BEAT_A, _UNRELATED_DRAFT), COVER_THRESHOLD)


class PlanComplianceMissesTests(unittest.TestCase):
    def test_none_plan_item_self_skips(self) -> None:
        self.assertEqual(_plan_compliance_misses("正文", None), [])

    def test_empty_key_events_self_skips(self) -> None:
        self.assertEqual(_plan_compliance_misses("正文", {"key_events": []}), [])

    def test_non_list_key_events_self_skips(self) -> None:
        # LLM 误发字符串而非 list 时，必须整体跳过，不能逐字符误判（P3 footgun）。
        self.assertEqual(
            _plan_compliance_misses("路明非杀死白王", {"key_events": "路明非杀死白王"}), []
        )

    def test_all_beats_covered_no_miss(self) -> None:
        plan = {"key_events": [_BEAT_A, _BEAT_B]}
        self.assertEqual(_plan_compliance_misses(_COVERED_DRAFT, plan), [])

    def test_absent_beats_reported(self) -> None:
        plan = {"key_events": [_BEAT_A, _BEAT_B]}
        misses = _plan_compliance_misses(_UNRELATED_DRAFT, plan)
        self.assertEqual(set(misses), {_BEAT_A, _BEAT_B})

    def test_partial_miss_reports_only_the_absent_one(self) -> None:
        # _BEAT_A 写出、_BEAT_B 缺席 → 只报 _BEAT_B（建议级，逐 beat，不需多数）。
        draft = "路明非在青铜与火之歌的余烬里缓缓苏醒过来，独自走了很远。"
        misses = _plan_compliance_misses(draft, {"key_events": [_BEAT_A, _BEAT_B]})
        self.assertEqual(misses, [_BEAT_B])


class PlanComplianceIntegrationTests(unittest.TestCase):
    """经 review_text：建议入 rewrite_suggestions、**enabled=false 时不翻转
    verdict**、自跳过。

    iter073 (codex B): hard-block now ships default-ON. These advisory tests pin
    the iter065 contract (advisory-only, no verdict flip) by explicitly running
    with the block disabled — the blocking behavior gets its own test class
    below.
    """

    @staticmethod
    def _approve(self, messages):  # noqa: ANN001 - mock signature
        return '{"agent_name":"agent","verdict":"Approve","plot":8,"prose":8,"fidelity":8,"issues":[],"suggestions":[]}'

    def _run(self, draft, chapter_plan_item, block_cfg=(False, 1.0)):
        with patch(
            "src.reviewer.load_review_agents",
            return_value=[{"name": "agent", "system_prompt": "review"}],
        ), patch("src.reviewer.load_advisor_agents", return_value=[]), patch(
            "src.reviewer._plan_compliance_block_cfg", return_value=block_cfg
        ), patch(
            "src.llm_client.LLMClient.complete_text", self._approve
        ):
            return review_text(
                draft,
                "plan_compliance_case.md",
                precomputed_lint_issues=[],
                chapter_plan_item=chapter_plan_item,
            )

    def _plan_suggestions(self, report):
        return [
            s
            for s in report.get("rewrite_suggestions", [])
            if isinstance(s, dict) and s.get("_advisor") == "plan_compliance"
        ]

    def test_none_plan_item_adds_no_suggestion(self) -> None:
        report = self._run(_COVERED_DRAFT, None)
        self.assertEqual(self._plan_suggestions(report), [])
        self.assertEqual(report["verdict"], "Approve")

    def test_covered_adds_no_suggestion(self) -> None:
        report = self._run(_COVERED_DRAFT, {"key_events": [_BEAT_A, _BEAT_B]})
        self.assertEqual(self._plan_suggestions(report), [])
        self.assertEqual(report["verdict"], "Approve")

    def test_missing_beats_surface_as_advisory_without_blocking(self) -> None:
        # iter065 review P2 (preserved under block-disabled): missing beats add
        # an advisor-style suggestion but DO NOT flip an otherwise-Approving
        # panel to Reject.
        report = self._run(_UNRELATED_DRAFT, {"key_events": [_BEAT_A, _BEAT_B]})
        suggs = self._plan_suggestions(report)
        self.assertTrue(suggs)
        self.assertEqual(suggs[0]["section"], "本章计划")
        self.assertEqual(report["verdict"], "Approve")  # disabled → never blocks


class PlanComplianceBlockTests(unittest.TestCase):
    """iter073 (codex B): with the hard-block enabled, a chapter that abandons
    its planned key_events (all beats essentially absent at miss_ratio=1.0) flips
    to Reject via a synthetic review; partial / covered chapters never block."""

    @staticmethod
    def _approve(self, messages):  # noqa: ANN001 - mock signature
        return '{"agent_name":"agent","verdict":"Approve","plot":8,"prose":8,"fidelity":8,"issues":[],"suggestions":[]}'

    def _run(self, draft, chapter_plan_item, block_cfg=(True, 1.0)):
        with patch(
            "src.reviewer.load_review_agents",
            return_value=[{"name": "agent", "system_prompt": "review"}],
        ), patch("src.reviewer.load_advisor_agents", return_value=[]), patch(
            "src.reviewer._plan_compliance_block_cfg", return_value=block_cfg
        ), patch(
            "src.llm_client.LLMClient.complete_text", self._approve
        ):
            return review_text(
                draft,
                "plan_compliance_block_case.md",
                precomputed_lint_issues=[],
                chapter_plan_item=chapter_plan_item,
            )

    @staticmethod
    def _has_block_review(report) -> bool:
        return any(
            isinstance(r, dict)
            and r.get("agent_name") == "plan_compliance"
            and r.get("verdict") == "Reject"
            for r in report.get("agent_reviews", [])
        )

    def test_all_beats_missing_blocks(self) -> None:
        report = self._run(_UNRELATED_DRAFT, {"key_events": [_BEAT_A, _BEAT_B]})
        self.assertEqual(report["verdict"], "Reject")
        self.assertTrue(self._has_block_review(report))

    def test_partial_miss_does_not_block(self) -> None:
        # only _BEAT_B missing → 1 < ceil(2*1.0)=2 → no whole-plan abandonment
        draft = "路明非在青铜与火之歌的余烬里缓缓苏醒过来，独自走了很远。"
        report = self._run(draft, {"key_events": [_BEAT_A, _BEAT_B]})
        self.assertEqual(report["verdict"], "Approve")
        self.assertFalse(self._has_block_review(report))

    def test_covered_does_not_block(self) -> None:
        report = self._run(_COVERED_DRAFT, {"key_events": [_BEAT_A, _BEAT_B]})
        self.assertEqual(report["verdict"], "Approve")
        self.assertFalse(self._has_block_review(report))

    def test_disabled_does_not_block_even_when_all_missing(self) -> None:
        report = self._run(
            _UNRELATED_DRAFT, {"key_events": [_BEAT_A, _BEAT_B]}, block_cfg=(False, 1.0)
        )
        self.assertEqual(report["verdict"], "Approve")
        self.assertFalse(self._has_block_review(report))

    def test_ratio_half_blocks_on_partial(self) -> None:
        # miss_ratio=0.5 → ceil(2*0.5)=1 → a single missing beat is enough
        draft = "路明非在青铜与火之歌的余烬里缓缓苏醒过来，独自走了很远。"
        report = self._run(
            draft, {"key_events": [_BEAT_A, _BEAT_B]}, block_cfg=(True, 0.5)
        )
        self.assertEqual(report["verdict"], "Reject")
        self.assertTrue(self._has_block_review(report))

    def test_none_plan_item_self_skips_block(self) -> None:
        report = self._run(_UNRELATED_DRAFT, None)
        self.assertEqual(report["verdict"], "Approve")
        self.assertFalse(self._has_block_review(report))

    def test_report_hard_reject_field_reflects_synthetic_block(self) -> None:
        # iter076 HIGH#1：report 顶层 hard_reject 与 synthetic 硬拦一致——
        # panel_block_policy 靠它区分 hard/soft。
        blocked = self._run(_UNRELATED_DRAFT, {"key_events": [_BEAT_A, _BEAT_B]})
        self.assertTrue(blocked["hard_reject"])
        clean = self._run(_COVERED_DRAFT, {"key_events": [_BEAT_A, _BEAT_B]})
        self.assertFalse(clean["hard_reject"])

    def test_has_hard_synthetic_reject_helper(self) -> None:
        # 新 artifact 走顶层字段；老 artifact 从 agent_reviews 派生；坏形状 False。
        from src.reviewer import has_hard_synthetic_reject

        self.assertTrue(has_hard_synthetic_reject({"hard_reject": True}))
        self.assertFalse(has_hard_synthetic_reject({"hard_reject": False, "agent_reviews": [
            {"_synthetic": True, "verdict": "Reject"}]}))   # 顶层字段优先
        legacy = {"agent_reviews": [{"_synthetic": True, "verdict": "Reject"}]}
        self.assertTrue(has_hard_synthetic_reject(legacy))
        soft = {"agent_reviews": [{"agent_name": "a", "verdict": "Reject"}]}
        self.assertFalse(has_hard_synthetic_reject(soft))
        self.assertFalse(has_hard_synthetic_reject(None))
        self.assertFalse(has_hard_synthetic_reject({"agent_reviews": "oops"}))


if __name__ == "__main__":
    unittest.main()
