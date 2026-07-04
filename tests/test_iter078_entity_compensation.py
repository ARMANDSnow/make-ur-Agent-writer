"""iter078 P1-4①/③：entity advance 补偿 + 第 5 注入点截断回归。

①（A 组审查确认）：正文+meta 落盘 → 分诊 → `_auto_apply_advances` 之间被
杀 → 章 approved、resume 跳过、advance 永久丢失。修复 = advance 处置后落
`chapter_NN.advance_applied.json` sidecar；resume 的 skip 分支对「sidecar
缺失 + 提案在盘」的章走补偿 apply（timeline 锚点去重保 legacy 存量章幂等，
零 LLM 调用）。

③：`_propose_entity_advance` 把 active_relationships 完整 dict（含无界
timeline）repr 进 prompt——iter073 的 16K 截断修复漏掉的第 5 注入点。
修复 = 四字段投影 + 条目边界截断 + 省略标记。

全部 mock（铁律③）。
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import patch

from src.entity_advance import save_entity_advance_proposals, unapplied_auto_indexes

from tests.test_iter078_rolling_order import _RunnerFixture, _status


def _graph(*, with_anchor_ch1: bool = False) -> Dict[str, Any]:
    timeline: List[Dict[str, Any]] = [{"state": "旧状态", "active": True}]
    if with_anchor_ch1:
        timeline = [
            {"state": "旧状态", "active": False},
            {
                "anchor_chapter": "续写第01章",
                "state": "已推进状态",
                "active": True,
            },
        ]
    return {
        "entities": [{"id": "a", "name": "甲"}, {"id": "b", "name": "乙"}],
        "relationships": [
            {"src_id": "a", "dst_id": "b", "relation_type": "同盟", "timeline": timeline}
        ],
    }


def _proposal(**overrides: Any) -> Dict[str, Any]:
    base = {
        "src_id": "a",
        "dst_id": "b",
        "new_state": "新状态",
        "trigger_event": "触发",
        "confidence": 0.9,
    }
    base.update(overrides)
    return base


class UnappliedIndexTests(unittest.TestCase):
    def test_excludes_proposal_whose_anchor_already_in_timeline(self) -> None:
        graph = _graph(with_anchor_ch1=True)
        self.assertEqual(
            unapplied_auto_indexes([_proposal()], graph, 1, min_confidence=0.7), []
        )

    def test_includes_proposal_without_anchor(self) -> None:
        graph = _graph()
        self.assertEqual(
            unapplied_auto_indexes([_proposal()], graph, 1, min_confidence=0.7), [0]
        )

    def test_other_chapter_anchor_does_not_dedupe(self) -> None:
        graph = _graph(with_anchor_ch1=True)
        # ch2 的补偿不受 ch1 锚点影响
        self.assertEqual(
            unapplied_auto_indexes([_proposal()], graph, 2, min_confidence=0.7), [0]
        )

    def test_low_confidence_still_filtered(self) -> None:
        graph = _graph()
        self.assertEqual(
            unapplied_auto_indexes(
                [_proposal(confidence=0.2)], graph, 1, min_confidence=0.7
            ),
            [],
        )


class _CompensationBase(unittest.TestCase):
    """approved 章 + skip 分支的补偿路径集成（run_write_book 全跑通）。"""

    def _run(
        self,
        *,
        seed_graph: Dict[str, Any] | None,
        seed_proposals: bool,
        seed_sidecar: bool,
    ) -> Dict[str, Any]:
        from src.book_runner import run_write_book

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def status_fn(chapter_no: int, *a: Any, **k: Any) -> Dict[str, Any]:
                return _status(chapter_no, written=True)  # 全部章 approved → skip

            fx = _RunnerFixture(root, plan_chapters=1, chapter_status_fn=status_fn)
            (fx.drafts / "chapter_01.md").write_text("正文\n", encoding="utf-8")
            graph_path = root / "data" / "entity_graph.json"
            graph_path.parent.mkdir(parents=True, exist_ok=True)
            if seed_graph is not None:
                graph_path.write_text(
                    json.dumps(seed_graph, ensure_ascii=False), encoding="utf-8"
                )
            if seed_proposals:
                save_entity_advance_proposals(1, [_proposal()], drafts_dir=fx.drafts)
            if seed_sidecar:
                (fx.drafts / "chapter_01.advance_applied.json").write_text(
                    json.dumps({"chapter": 1, "applied_count": 1}), encoding="utf-8"
                )

            with fx, patch("src.book_runner.write_chapters") as writer_spy:
                result = run_write_book(chapters=1, require_external_review=False)
            self.assertEqual(writer_spy.call_count, 0, "skip 章不得触发写作（零 LLM）")
            result["_graph_after"] = (
                json.loads(graph_path.read_text(encoding="utf-8"))
                if graph_path.exists()
                else {}
            )
            result["_sidecar"] = (
                json.loads(
                    (fx.drafts / "chapter_01.advance_applied.json").read_text(
                        encoding="utf-8"
                    )
                )
                if (fx.drafts / "chapter_01.advance_applied.json").exists()
                else None
            )
            return result


class CompensationTests(_CompensationBase):
    def test_missing_sidecar_with_proposals_compensates_and_marks(self) -> None:
        result = self._run(
            seed_graph=_graph(), seed_proposals=True, seed_sidecar=False
        )
        self.assertEqual(result["chapters"][0]["action"], "skipped_approved")
        self.assertTrue(result["chapters"][0].get("advance_compensated"))
        advances = result.get("advances") or []
        self.assertTrue(advances and advances[0].get("compensated"))
        self.assertEqual(advances[0].get("applied_count"), 1)
        # 图真的被推进了
        timeline = result["_graph_after"]["relationships"][0]["timeline"]
        self.assertEqual(timeline[-1]["state"], "新状态")
        self.assertEqual(timeline[-1]["anchor_chapter"], "续写第01章")
        # sidecar 已落盘（compensated 标记留痕）
        self.assertIsNotNone(result["_sidecar"])
        self.assertTrue(result["_sidecar"]["compensated"])

    def test_legacy_already_applied_is_idempotent_zero_op(self) -> None:
        # iter078 之前写完的存量章：无 sidecar 但 timeline 已含本章锚点——
        # 补偿必须零操作（不重复 append），并落 sidecar 终止后续重查。
        result = self._run(
            seed_graph=_graph(with_anchor_ch1=True),
            seed_proposals=True,
            seed_sidecar=False,
        )
        advances = result.get("advances") or []
        self.assertTrue(advances and advances[0].get("compensated"))
        self.assertEqual(advances[0].get("applied_count"), 0)
        timeline = result["_graph_after"]["relationships"][0]["timeline"]
        self.assertEqual(len(timeline), 2, "timeline 不得被重复 append")
        self.assertIsNotNone(result["_sidecar"])

    def test_sidecar_present_skips_compensation(self) -> None:
        result = self._run(
            seed_graph=_graph(), seed_proposals=True, seed_sidecar=True
        )
        self.assertFalse(result["chapters"][0].get("advance_compensated"))
        self.assertEqual(result.get("advances") or [], [])
        timeline = result["_graph_after"]["relationships"][0]["timeline"]
        self.assertEqual(len(timeline), 1, "已处置章不得再动图")

    def test_missing_proposals_no_compensation(self) -> None:
        result = self._run(seed_graph=_graph(), seed_proposals=False, seed_sidecar=False)
        self.assertFalse(result["chapters"][0].get("advance_compensated"))
        self.assertEqual(result.get("advances") or [], [])
        self.assertIsNone(result["_sidecar"])


class ArchiveIncludesSidecarTests(unittest.TestCase):
    def test_archive_moves_advance_sidecar(self) -> None:
        from src.book_runner import _archive_chapter_artifacts

        with tempfile.TemporaryDirectory() as tmp:
            drafts = Path(tmp) / "drafts"
            drafts.mkdir(parents=True)
            (drafts / "chapter_01.md").write_text("x", encoding="utf-8")
            sidecar = drafts / "chapter_01.advance_applied.json"
            sidecar.write_text("{}", encoding="utf-8")
            archive_dir = _archive_chapter_artifacts(drafts, 1, reason="test")
            self.assertFalse(sidecar.exists())
            self.assertTrue((archive_dir / sidecar.name).exists())


class InjectionTruncationTests(unittest.TestCase):
    """P1-4③：_propose_entity_advance 的 prompt 注入截断。"""

    def _capture_prompt(self, graph: Dict[str, Any]) -> str:
        from src.writer import _propose_entity_advance

        captured: List[str] = []

        class _FakeClient:
            is_mock = False

            def complete_json(self, messages: Any, schema: Any) -> Any:
                captured.append(messages[1]["content"])
                raise RuntimeError("stop after capture")

        with patch("src.writer.log_event"):
            result = _propose_entity_advance(_FakeClient(), 1, "正文", graph)
        self.assertEqual(result, [])  # 异常吞掉降级为空提案（既有行为）
        self.assertTrue(captured)
        return captured[0]

    @staticmethod
    def _relationships_section(prompt: str) -> str:
        start = prompt.index("# 当前 active relationships")
        end = prompt.index("# 本章正文")
        return prompt[start:end]

    def test_huge_timeline_not_injected_and_capped(self) -> None:
        # 单关系 500 条 timeline（含唯一标记）——旧代码整表 repr 进 prompt。
        timeline = [
            {"state": f"历史状态_{i}_UNIQUE_POISON_MARKER", "active": False}
            for i in range(500)
        ]
        timeline.append({"state": "当前状态", "active": True})
        graph = {
            "relationships": [
                {"src_id": "a", "dst_id": "b", "relation_type": "同盟", "timeline": timeline}
            ]
        }
        prompt = self._capture_prompt(graph)
        section = self._relationships_section(prompt)
        self.assertNotIn("UNIQUE_POISON_MARKER", section, "timeline 历史不得注入")
        self.assertIn('"old_active_state": "当前状态"', section)
        self.assertIn('"src_id": "a"', section)

    def test_many_relationships_capped_with_omission_marker(self) -> None:
        from src.entities import PROMPT_ENTITY_STATE_LIMIT

        graph = {
            "relationships": [
                {
                    "src_id": f"e{i}",
                    "dst_id": f"f{i}",
                    "relation_type": "同盟",
                    "timeline": [{"state": "状态" * 30, "active": True}],
                }
                for i in range(2000)
            ]
        }
        prompt = self._capture_prompt(graph)
        section = self._relationships_section(prompt)
        self.assertLess(len(section), PROMPT_ENTITY_STATE_LIMIT + 500)
        self.assertIn("因长度限制省略", section)

    def test_small_graph_no_omission_marker(self) -> None:
        prompt = self._capture_prompt(_graph())
        section = self._relationships_section(prompt)
        self.assertNotIn("省略", section)


if __name__ == "__main__":
    unittest.main()
