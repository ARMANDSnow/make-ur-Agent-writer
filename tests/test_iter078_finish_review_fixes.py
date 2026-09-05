"""iter078 收官铁律⑨审查修复批回归。

六项直修（发现来源：code-review high 8 finder + 2 独立视角 + verifier 确认）：

1. readiness tier 指纹不对称：check_write_readiness 无 tier 意图时不得拿
   DEFAULT_TIER 冒充期望值（--tier high 写出的章会被 review_tier_mismatch
   逐章误杀）；显式 tier / env 表达意图时仍严格比对。
2. SUPPLEMENT_EXTERNAL_REVIEW 出口缺 advance 补偿：补审通过的章与 SKIP
   分支同款 _compensate_missing_advance（否则本 run 后续章注入停滞实体状态）。
3. 补偿 recency 守门：目标关系已被更晚续写章推进时跳过迟到重放（legacy 章
   旧提案回放会灭活新状态、实体倒退）。
4. is_boundary_item 键缺失 fail-closed：planted_chapter 键缺失=出身不可知，
   与 unparseable 同款留在闸门内。
5. _env_float 负数回退：负 LLM_REQUEST_TIMEOUT 无合法语义，preflight 文案
   承诺「已回退默认」，实现此前却原样透传。
6. 账本标量残行：json.loads 成功但非 dict（null/123）按脏行计，不再
   AttributeError 击穿预算回调。

（第 7 项 reaper argv[0] re-exec 修复的回归在 test_iter077_orphan_reaping.py；
第 8 项 draft-once-dev / auto-pipeline 写锁覆盖为调用点包装，互斥语义由
test_iter078_workspace_lock.py 钉死。）全部 mock（铁律③）。
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

from tests.test_iter077_caveat_readiness import _WorkspaceHarness
from tests.test_iter078_rolling_order import _RunnerFixture, _status


class ReadinessTierIntentTests(_WorkspaceHarness):
    """修复 1：tier 意图未表达时 readiness 跳过 tier 指纹比对。"""

    def setUp(self) -> None:
        super().setUp()
        self._saved_tier = os.environ.pop("WRITE_REVIEW_TIER", None)
        self.addCleanup(self._restore_tier)

    def _restore_tier(self) -> None:
        if self._saved_tier is not None:
            os.environ["WRITE_REVIEW_TIER"] = self._saved_tier
        else:
            os.environ.pop("WRITE_REVIEW_TIER", None)

    def _seed_high_tier_chapter(self) -> None:
        (self.drafts / "chapter_01.md").write_text("正文……\n", encoding="utf-8")
        meta = {
            "verdict": "Approve",
            "needs_human_review": False,
            "rewrite_count": 0,
            "run_context": {"review_tier": "high"},
        }
        (self.drafts / "chapter_01.meta.json").write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8"
        )

    def _readiness_with_tier(self, tier: str | None):
        from src.book_runner import check_write_readiness

        return check_write_readiness(
            chapters=1,
            resume_from=1,
            require_start_point=False,
            require_plan=False,
            require_external_review=False,
            tier=tier,
        )

    def test_no_tier_intent_does_not_fake_default(self) -> None:
        # --tier high 写出的章：独立 write-readiness / Web readiness（不传
        # tier、env 未设）不得用 'mid' 冒充期望值把它 BLOCK。
        self._write_plan()
        self._seed_high_tier_chapter()
        r = self._readiness_with_tier(None)
        self.assertFalse(
            any("review_tier_mismatch" in b for b in r["blockers"]),
            msg=f"blockers={r['blockers']}",
        )

    def test_explicit_tier_still_guards(self) -> None:
        self._write_plan()
        self._seed_high_tier_chapter()
        r = self._readiness_with_tier("low")
        self.assertTrue(
            any("review_tier_mismatch" in b for b in r["blockers"]),
            msg=f"blockers={r['blockers']}",
        )

    def test_env_tier_intent_still_guards(self) -> None:
        self._write_plan()
        self._seed_high_tier_chapter()
        with patch.dict(os.environ, {"WRITE_REVIEW_TIER": "low"}):
            r = self._readiness_with_tier(None)
        self.assertTrue(
            any("review_tier_mismatch" in b for b in r["blockers"]),
            msg=f"blockers={r['blockers']}",
        )


def _graph() -> Dict[str, Any]:
    return {
        "entities": [{"id": "a", "name": "甲"}, {"id": "b", "name": "乙"}],
        "relationships": [
            {
                "src_id": "a",
                "dst_id": "b",
                "relation_type": "同盟",
                "timeline": [{"state": "旧状态", "active": True}],
            }
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


class SupplementBranchCompensationTests(unittest.TestCase):
    """修复 2：补外审通过出口与 SKIP 分支同款补偿。"""

    def test_supplement_pass_compensates_missing_advance(self) -> None:
        from src.book_runner import run_write_book
        from src.entity_advance import save_entity_advance_proposals

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            reviewed = {"done": False}

            def status_fn(chapter_no: int, *a: Any, **k: Any) -> Dict[str, Any]:
                if not reviewed["done"]:
                    # 补审前的盘面：正文在盘、主审 Approve、仅缺外审 →
                    # SUPPLEMENT_EXTERNAL_REVIEW（「落盘→外审」窗口被杀的形状）。
                    st = _status(chapter_no, written=True)
                    st["approved"] = False
                    st["strict_failures"] = ["external_review_incomplete"]
                    return st
                return _status(chapter_no, written=True)  # 补审后：strict approved

            def fake_review(*a: Any, **k: Any) -> None:
                reviewed["done"] = True

            fx = _RunnerFixture(root, plan_chapters=1, chapter_status_fn=status_fn)
            (fx.drafts / "chapter_01.md").write_text("正文\n", encoding="utf-8")
            graph_path = root / "data" / "entity_graph.json"
            graph_path.parent.mkdir(parents=True, exist_ok=True)
            graph_path.write_text(json.dumps(_graph(), ensure_ascii=False), encoding="utf-8")
            save_entity_advance_proposals(1, [_proposal()], drafts_dir=fx.drafts)

            with fx, patch("src.book_runner.write_chapters") as writer_spy, patch(
                "src.book_runner.review_target", side_effect=fake_review
            ) as review_spy, patch("src.book_runner._sync_meta_with_external_review"):
                result = run_write_book(chapters=1, require_external_review=True)

            self.assertEqual(writer_spy.call_count, 0, "补审章不得触发写作")
            self.assertEqual(review_spy.call_count, 1, "必须走补外审路径")
            entry = result["chapters"][0]
            self.assertEqual(entry["action"], "reviewed_existing")
            self.assertTrue(
                entry.get("advance_compensated"),
                msg=f"entry={entry}, advances={result.get('advances')}",
            )
            sidecar = fx.drafts / "chapter_01.advance_applied.json"
            self.assertTrue(sidecar.exists(), "补偿后必须落 sidecar 终止重查")
            graph_after = json.loads(graph_path.read_text(encoding="utf-8"))
            timeline = graph_after["relationships"][0]["timeline"]
            self.assertEqual(timeline[-1]["anchor_chapter"], "续写第01章")


class RecencyGuardTests(unittest.TestCase):
    """修复 3：更晚续写章已推进的关系跳过迟到补偿重放。"""

    def _graph_with_anchor(self, anchor: str) -> Dict[str, Any]:
        g = _graph()
        g["relationships"][0]["timeline"] = [
            {"state": "旧状态", "active": False},
            {"anchor_chapter": anchor, "state": "后来推进的状态", "active": True},
        ]
        return g

    def test_later_anchor_blocks_late_replay(self) -> None:
        from src.entity_advance import unapplied_auto_indexes

        graph = self._graph_with_anchor("续写第05章")
        chosen = unapplied_auto_indexes([_proposal()], graph, 2, min_confidence=0.7)
        self.assertEqual(chosen, [], "关系已被 ch5 推进，ch2 的迟到重放=状态倒退，必须跳过")

    def test_earlier_anchor_does_not_block(self) -> None:
        from src.entity_advance import unapplied_auto_indexes

        graph = self._graph_with_anchor("续写第01章")
        chosen = unapplied_auto_indexes([_proposal()], graph, 2, min_confidence=0.7)
        self.assertEqual(chosen, [0], "只有更晚锚点才构成倒退，更早锚点不拦真补偿")

    def test_source_anchor_ignored(self) -> None:
        from src.entity_advance import unapplied_auto_indexes

        graph = self._graph_with_anchor("第30章")  # 源书锚点，非续写格式
        chosen = unapplied_auto_indexes([_proposal()], graph, 2, min_confidence=0.7)
        self.assertEqual(chosen, [0])


class BoundaryMissingKeyTests(unittest.TestCase):
    """修复 4：planted_chapter 键缺失留在 fail-closed 闸门。"""

    def test_missing_planted_chapter_not_boundary(self) -> None:
        from src.foreshadowing import is_boundary_item

        self.assertFalse(is_boundary_item({"must_resolve": True, "status": "open"}))

    def test_explicit_zero_still_boundary(self) -> None:
        from src.foreshadowing import is_boundary_item

        self.assertTrue(
            is_boundary_item(
                {"planted_chapter": 0, "must_resolve": True, "status": "open"}
            )
        )


class EnvFloatNegativeTests(unittest.TestCase):
    """修复 5：负值与 inf/nan 同款回退默认。"""

    def test_negative_falls_back_to_default(self) -> None:
        from src.config import _env_float

        with patch.dict(os.environ, {"LLM_REQUEST_TIMEOUT": "-30"}):
            self.assertEqual(_env_float("LLM_REQUEST_TIMEOUT", 120.0), 120.0)

    def test_positive_passes_through(self) -> None:
        from src.config import _env_float

        with patch.dict(os.environ, {"LLM_REQUEST_TIMEOUT": "45.5"}):
            self.assertEqual(_env_float("LLM_REQUEST_TIMEOUT", 120.0), 45.5)


class ScalarDirtyLineTests(unittest.TestCase):
    """修复 6：合法标量 JSON 残行按脏行计，不炸预算回调。"""

    def test_scalar_lines_counted_dirty_not_crash(self) -> None:
        from src.cost_estimator import estimate_cost_since

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            logs = root / "logs"
            logs.mkdir(parents=True)
            (logs / "llm_calls.jsonl").write_text(
                "\n".join(
                    [
                        json.dumps(
                            {"prompt_tokens": 10, "response_tokens": 5, "model": "mock"}
                        ),
                        "null",
                        "123",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            out = estimate_cost_since(0, root=root)
        self.assertEqual(out["calls"], 1)
        self.assertEqual(out["dirty_lines"], 2)


if __name__ == "__main__":
    unittest.main()
