"""iter 053b: 写手 canon 锚定增强。

* 时间锚定反剧透块 —— 条件注入三态：有起点注入（含起点坐标与"之前可用/
  之后禁用"两向条款）/ 无起点逐字节不变 / env 开关关闭逐字节不变（铁律④）；
* 回灌分层模板 —— block 禁令置顶（修复 block-but-Approve 漏灌）+ 必须处理
  + 改写顾问（节标题与 [:5] 截断为 iter024 既有契约）+ 可选优化；
* ``_blocking_reasons`` 同口径 —— Approve 评审的 block issue 进失败面，
  非 block 仍只取 Reject 评审（避免回灌与 last_failure 两套口径，审查 B2）；
* 跨 retry 周期反馈播种 —— book_runner 归档前收割上一周期拒因（审查 B3），
  经 write_chapters(seed_feedback=...) 喂进下一周期第一稿。
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.book_runner import _cross_cycle_seed_feedback
from src.writer import _blocking_reasons, _review_feedback, _write_prompt, write_chapters


def _prompt_kwargs(**overrides):
    base = dict(
        chapter_no=1,
        knowledge="知识",
        facts="事实",
        style_examples="",
        continuation_anchor="",
        index={},
        outline="# 大纲",
    )
    base.update(overrides)
    return base


class CanonAnchorInjectionTests(unittest.TestCase):
    def test_with_start_point_injects_time_anchor(self) -> None:
        with patch(
            "src.start_point.get_start_chapter_id", return_value="longzu_3_3_ch024"
        ), patch.dict(os.environ, {}, clear=False):
            os.environ.pop("WRITER_CANON_ANCHOR", None)
            messages, _ = _write_prompt(**_prompt_kwargs())
        system = messages[0]["content"]
        self.assertIn("原著时间线锚定", system)
        self.assertIn("longzu_3_3_ch024", system)
        # 时间锚定的两向条款都在：之后禁用 + 之前可用（审查 B1——只禁
        # "未注入"会误杀起点前合法 canon）。
        self.assertIn("才发生的事件", system)
        self.assertIn("禁止引用", system)
        self.assertIn("可以正常使用", system)

    def test_no_start_point_prompt_byte_identical(self) -> None:
        kwargs = _prompt_kwargs()
        with patch("src.start_point.get_start_chapter_id", return_value=None):
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("WRITER_CANON_ANCHOR", None)
                messages_default, cache_default = _write_prompt(**kwargs)
            with patch.dict(os.environ, {"WRITER_CANON_ANCHOR": "0"}, clear=False):
                messages_off, cache_off = _write_prompt(**kwargs)
        # 无起点（premise 自创书）：开关开/关 prompt 逐字节一致（铁律④）。
        self.assertEqual(messages_default, messages_off)
        self.assertEqual(cache_default, cache_off)
        self.assertNotIn("原著时间线锚定", messages_default[0]["content"])

    def test_env_kill_switch_disables_anchor_despite_start_point(self) -> None:
        kwargs = _prompt_kwargs()
        with patch("src.start_point.get_start_chapter_id", return_value="ch9"):
            with patch.dict(os.environ, {"WRITER_CANON_ANCHOR": "0"}, clear=False):
                messages_off, _ = _write_prompt(**kwargs)
        with patch("src.start_point.get_start_chapter_id", return_value=None):
            with patch.dict(os.environ, {}, clear=False):
                os.environ.pop("WRITER_CANON_ANCHOR", None)
                messages_no_start, _ = _write_prompt(**kwargs)
        # 053c 段一对照配方：开关关闭 == 完全没有锚定（与无起点输出一致）。
        self.assertEqual(messages_off, messages_no_start)


class ReviewFeedbackLayeringTests(unittest.TestCase):
    def _report(self) -> dict:
        return {
            "verdict": "Reject",
            "lint_issues": [],
            "agent_reviews": [
                {
                    "agent_name": "事实守门员",
                    "verdict": "Approve",  # block-but-Approve：整体因票数被拒
                    "issues": [
                        {
                            "rule_id": "gf_longzu_014",
                            "severity": "block",
                            "anchor": "第三段",
                            "message": "起点处该交易尚未发生",
                        }
                    ],
                    "suggestions": [],
                },
                {
                    "agent_name": "节奏评审",
                    "verdict": "Reject",
                    "issues": [
                        {
                            "rule_id": "pace_drag",
                            "severity": "major",
                            "anchor": "中段",
                            "message": "节奏拖沓",
                        },
                        {
                            "rule_id": "minor_typo",
                            "severity": "minor",
                            "anchor": "末段",
                            "message": "标点小问题",
                        },
                    ],
                    "suggestions": ["压缩中段"],
                },
            ],
            "rewrite_suggestions": [
                {"section": "开场", "type": "rewrite", "guidance": "延后登场", "_advisor": "改写顾问"}
            ],
        }

    def test_block_but_approve_issue_is_fed_back(self) -> None:
        feedback = _review_feedback(self._report())
        self.assertIn("block 级违例", feedback)
        self.assertIn("gf_longzu_014", feedback)
        self.assertIn("起点处该交易尚未发生", feedback)

    def test_layered_sections_in_order(self) -> None:
        feedback = _review_feedback(self._report())
        i_block = feedback.index("block 级违例")
        i_major = feedback.index("## 必须处理的修改建议")
        i_advisor = feedback.index("## 改写顾问建议")
        i_optional = feedback.index("## 可选优化")
        self.assertTrue(i_block < i_major < i_advisor < i_optional)
        # major 进必须处理；minor 与 suggestion 进可选优化。
        self.assertTrue(i_major < feedback.index("pace_drag") < i_advisor)
        self.assertTrue(feedback.index("minor_typo") > i_optional)
        self.assertTrue(feedback.index("suggestion: 压缩中段") > i_optional)

    def test_all_approve_without_block_yields_empty(self) -> None:
        # 整体 Approve 主路径零变化的代理断言：没有 block、评审全 Approve
        # → 不产生任何回灌内容（也根本不会被调用，writer.py 的 break 在前）。
        report = {
            "lint_issues": [],
            "agent_reviews": [
                {
                    "agent_name": "a",
                    "verdict": "Approve",
                    "issues": [
                        {"rule_id": "x", "severity": "major", "anchor": "", "message": "尚可"}
                    ],
                    "suggestions": ["可改"],
                }
            ],
            "rewrite_suggestions": [],
        }
        self.assertEqual(_review_feedback(report), "")

    def test_blocking_reasons_same_caliber(self) -> None:
        reasons = _blocking_reasons(self._report())
        rule_ids = [r.get("rule_id") for r in reasons]
        # Approve 评审的 block 进失败面（漏灌修复）……
        self.assertIn("gf_longzu_014", rule_ids)
        # ……Reject 评审行为不变（major/minor 照旧收录）。
        self.assertIn("pace_drag", rule_ids)
        self.assertIn("minor_typo", rule_ids)
        # Approve 评审的非 block 不收（与回灌同口径）。
        report = self._report()
        report["agent_reviews"][0]["issues"][0]["severity"] = "major"
        rule_ids_2 = [r.get("rule_id") for r in _blocking_reasons(report)]
        self.assertNotIn("gf_longzu_014", rule_ids_2)


class CrossCycleSeedTests(unittest.TestCase):
    def _layout(self, tmp: Path) -> Path:
        drafts = tmp / "outputs" / "drafts"
        drafts.mkdir(parents=True)
        (tmp / "outputs" / "reviews").mkdir(parents=True)
        return drafts

    def test_seed_harvests_review_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            drafts = self._layout(Path(tmp))
            review = {
                "verdict": "Reject",
                "agent_reviews": [
                    {
                        "agent_name": "事实守门员",
                        "verdict": "Reject",
                        "issues": [
                            {"rule_id": "gf_longzu_015", "severity": "block",
                             "anchor": "首段", "message": "时间线前置"}
                        ],
                        "suggestions": [],
                    }
                ],
            }
            (drafts.parent / "reviews" / "chapter_01.review.json").write_text(
                json.dumps(review, ensure_ascii=False), encoding="utf-8"
            )
            seed = _cross_cycle_seed_feedback(drafts, 1)
        self.assertIn("上一重试周期的评审拒因", seed)
        self.assertIn("gf_longzu_015", seed)

    def test_seed_falls_back_to_meta_agent_reviews(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            drafts = self._layout(Path(tmp))
            meta = {
                "verdict": "Reject",
                "agent_reviews": [
                    {
                        "agent_name": "评审",
                        "verdict": "Reject",
                        "issues": [
                            {"rule_id": "from_meta", "severity": "block",
                             "anchor": "", "message": "meta 兜底"}
                        ],
                    }
                ],
            }
            (drafts / "chapter_01.meta.json").write_text(
                json.dumps(meta, ensure_ascii=False), encoding="utf-8"
            )
            seed = _cross_cycle_seed_feedback(drafts, 1)
        self.assertIn("from_meta", seed)

    def test_seed_empty_when_no_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            drafts = self._layout(Path(tmp))
            self.assertEqual(_cross_cycle_seed_feedback(drafts, 1), "")

    def test_write_chapters_seeds_first_draft_prompt(self) -> None:
        # 集成断言：seed_feedback 必须出现在第一稿 prompt 里（052 断链修复的
        # 端到端面）；缺省 "" 时第一稿 prompt 不含播种段头。
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            drafts = tmp / "drafts"
            drafts.mkdir(parents=True)
            outline = tmp / "outline.md"
            outline.write_text("# outline", encoding="utf-8")
            kb = tmp / "global_knowledge.md"
            kb.write_text("# knowledge", encoding="utf-8")
            idx = tmp / "knowledge_index.json"
            idx.write_text("{}", encoding="utf-8")
            prompts: list = []

            def fake_complete_text(self, messages, temperature=None, cache_segments=None):
                prompts.append("\n".join(m.get("content", "") for m in messages))
                return "干净正文。"

            approve = {"verdict": "Approve", "lint_issues": [], "agent_reviews": []}
            with patch("src.writer.DRAFTS_DIR", drafts), patch(
                "src.writer.OUTLINE_PATH", outline
            ), patch("src.writer.KB_PATH", kb), patch("src.writer.INDEX_PATH", idx), patch(
                "src.writer.NovelLinter"
            ) as linter_cls, patch(
                "src.llm_client.LLMClient.complete_text", fake_complete_text
            ), patch(
                "src.writer.review_text", return_value=approve
            ):
                linter_cls.return_value.lint.return_value = []
                write_chapters(
                    chapters=1,
                    force=True,
                    max_attempts=1,
                    seed_feedback="## 上一重试周期的评审拒因\n[守门员] gf_longzu_014: 别再写交易",
                )
            self.assertIn("gf_longzu_014", prompts[0])
        self.assertIn("上一重试周期的评审拒因", prompts[0])


if __name__ == "__main__":
    unittest.main()
