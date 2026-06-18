"""Iter 024 P2: tests for plot_planner.generate_chapter_plan(append_count, from_chapter).

Verifies append mode preserves existing chapters 1..from_chapter,
appends K new ones, updates target_chapters total, and preserves the
top-level overall_arc from existing (doesn't let LLM rewrite global
arc on every re-plan).
"""

import json
import os
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch


def _make_plan(n: int, arc: str = "原始 arc") -> dict:
    return {
        "target_chapters": n,
        "overall_arc": arc,
        "chapters": [
            {
                "chapter_no": i,
                "title": f"原章 {i}",
                "opening_scene": f"开场 {i}",
                "key_events": [f"事件 {i}.1", f"事件 {i}.2"],
                "relationships_in_play": [],
                "ending_hook": f"hook {i}",
                "target_chinese_chars": 4000,
                "plot_purpose": f"用途 {i}",
            }
            for i in range(1, n + 1)
        ],
        "generated_by": "test_seed",
    }


class PlotPlannerAppendTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_ws = os.environ.get("WORKSPACE_NAME")
        os.environ["WORKSPACE_NAME"] = "iter024append"
        repo_root = Path(__file__).resolve().parent.parent
        self.ws_root = repo_root / "workspaces" / "iter024append"
        (self.ws_root / "outputs" / "debate").mkdir(parents=True, exist_ok=True)
        (self.ws_root / "data" / "knowledge_base").mkdir(parents=True, exist_ok=True)
        (self.ws_root / "data" / "manual_overrides").mkdir(parents=True, exist_ok=True)
        (self.ws_root / "data" / "chapter_manifest.json").write_text(
            json.dumps(
                [
                    {"chapter_id": "v1_ch001", "volume_id": "v1", "title": "一"},
                    {"chapter_id": "v1_ch002", "volume_id": "v1", "title": "二"},
                    {"chapter_id": "v1_ch003", "volume_id": "v1", "title": "三"},
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        # Stub outline so generate_chapter_plan precondition is met
        (self.ws_root / "outputs" / "debate" / "outline.md").write_text(
            "stub outline", encoding="utf-8"
        )
        # iter 054b: plan-chapters now hard-blocks on an extraction coverage
        # gap before the start. These tests set start=v1_ch003, so seed the
        # K-chapter window's extracted_jsons to satisfy the new闸.
        extracted = self.ws_root / "data" / "extracted_jsons"
        extracted.mkdir(parents=True, exist_ok=True)
        for cid in ("v1_ch001", "v1_ch002", "v1_ch003"):
            (extracted / f"{cid}.json").write_text(
                json.dumps({"chapter_id": cid, "summary": cid}, ensure_ascii=False),
                encoding="utf-8",
            )

    def tearDown(self) -> None:
        if self.ws_root.exists():
            shutil.rmtree(self.ws_root)
        if self._old_ws is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._old_ws

    def _seed_plan(self, n: int) -> None:
        (self.ws_root / "outputs" / "debate" / "chapter_plan.json").write_text(
            json.dumps(_make_plan(n), ensure_ascii=False),
            encoding="utf-8",
        )

    def test_append_preserves_existing_head(self) -> None:
        """append +5 from ch10 should keep ch1-10 byte-identical and
        produce ch11-15 with continuous chapter_no."""
        from src import plot_planner

        self._seed_plan(10)
        from src import start_point
        start_point.set_start_point("v1_ch003")
        plan_path = self.ws_root / "outputs" / "debate" / "chapter_plan.json"
        seeded = json.loads(plan_path.read_text(encoding="utf-8"))
        seeded["start_chapter_id"] = "v1_ch003"
        plan_path.write_text(json.dumps(seeded, ensure_ascii=False), encoding="utf-8")
        # Mock LLM to return 5 new chapters numbered 1-5 (renumbering test)
        fake_new = {
            "target_chapters": 5,
            "overall_arc": "新 arc (会被原 arc 覆盖)",
            "chapters": [
                {
                    "chapter_no": i,
                    "title": f"新章 {i}",
                    "opening_scene": f"新开场 {i}",
                    "key_events": [f"新事件 {i}.1", f"新事件 {i}.2"],
                    "relationships_in_play": [],
                    "ending_hook": f"新 hook {i}",
                    "target_chinese_chars": 4000,
                    "plot_purpose": f"新用途 {i}",
                }
                for i in range(1, 6)
            ],
            "generated_by": "test_mock",
        }

        from src.schemas import ChapterPlan
        with patch.object(
            plot_planner.LLMClient,
            "complete_json",
            lambda self, msgs, model: ChapterPlan(**fake_new),
        ):
            result = plot_planner.generate_chapter_plan(
                target_chapters=5, append_count=5, from_chapter=10
            )

        # Should have 15 total chapters
        self.assertEqual(len(result["chapters"]), 15)
        self.assertEqual(result["target_chapters"], 15)
        # ch1-10 preserved byte-identical (title format = "原章 N")
        for i in range(10):
            self.assertEqual(result["chapters"][i]["title"], f"原章 {i + 1}")
            self.assertEqual(result["chapters"][i]["chapter_no"], i + 1)
        # ch11-15 are renumbered new ones (LLM returned 1-5, we renumber to 11-15)
        for i in range(5):
            self.assertEqual(result["chapters"][10 + i]["chapter_no"], 11 + i)
            self.assertEqual(result["chapters"][10 + i]["title"], f"新章 {i + 1}")
        # overall_arc preserved from existing, not from LLM
        self.assertEqual(result["overall_arc"], "原始 arc")
        self.assertEqual(result["start_chapter_id"], "v1_ch003")

    def test_append_preserves_plan_fingerprint(self) -> None:
        """iter057 P0-A 核心回归: replan append 新章**不改变** plan_fingerprint。

        旧算法哈希 chapters 全列表 + target_chapters,append 后 plan_fingerprint 必变,
        已写章 meta 冻结的旧指纹 → plan_fingerprint_mismatch → 非 skipped_approved →
        下一段 resume 立刻 BookRunBlocked 卡死。新算法只哈希全局上下文(overall_arc/起点),
        append 仅延长尾巴、不动全局上下文 → 指纹稳定 → 已写章不误伤。修复前此测试红。"""
        from src import plot_planner, start_point

        self._seed_plan(10)
        start_point.set_start_point("v1_ch003")
        plan_path = self.ws_root / "outputs" / "debate" / "chapter_plan.json"
        seeded = json.loads(plan_path.read_text(encoding="utf-8"))
        seeded["start_chapter_id"] = "v1_ch003"
        # 模拟「plan 已生成」:按生产路径 attach 指纹,记录 append 前的全局指纹 + 各章 item 指纹。
        plot_planner._attach_plan_fingerprints(seeded, start_chapter_id="v1_ch003")
        plan_path.write_text(json.dumps(seeded, ensure_ascii=False), encoding="utf-8")
        before_fp = seeded["plan_fingerprint"]
        before_item_fps = [c["chapter_plan_item_fingerprint"] for c in seeded["chapters"]]

        fake_new = {
            "target_chapters": 5,
            "overall_arc": "新 arc (会被原 arc 覆盖)",
            "chapters": [
                {
                    "chapter_no": i,
                    "title": f"新章 {i}",
                    "opening_scene": f"新开场 {i}",
                    "key_events": [f"新事件 {i}.1", f"新事件 {i}.2"],
                    "relationships_in_play": [],
                    "ending_hook": f"新 hook {i}",
                    "target_chinese_chars": 4000,
                    "plot_purpose": f"新用途 {i}",
                }
                for i in range(1, 6)
            ],
            "generated_by": "test_mock",
        }
        from src.schemas import ChapterPlan
        with patch.object(
            plot_planner.LLMClient,
            "complete_json",
            lambda self, msgs, model: ChapterPlan(**fake_new),
        ):
            result = plot_planner.generate_chapter_plan(
                target_chapters=5, append_count=5, from_chapter=10
            )

        # 列表变长(15章)、target_chapters 变大 —— 但 plan_fingerprint 必须不变。
        self.assertEqual(len(result["chapters"]), 15)
        self.assertEqual(result["target_chapters"], 15)
        self.assertEqual(
            result["plan_fingerprint"], before_fp,
            "append 不得改变 plan_fingerprint(P0-A:否则已写章全 mismatch 卡死)",
        )
        # 已存在章(ch1-10)的 item 指纹 byte-identical(按章一致性仍由 item 指纹守护)。
        after_item_fps = [c["chapter_plan_item_fingerprint"] for c in result["chapters"][:10]]
        self.assertEqual(after_item_fps, before_item_fps)

    def test_extraction_coverage_gap_hard_blocks(self) -> None:
        # iter 054b: a gap in the K-chapter extraction window before the start
        # must hard-block plan-chapters (was readiness warn only — 053g).
        # setUp seeds the full window; drop one chapter to open a gap.
        from src import plot_planner, start_point

        start_point.set_start_point("v1_ch003")
        (self.ws_root / "data" / "extracted_jsons" / "v1_ch002.json").unlink()
        with self.assertRaises(ValueError) as ctx:
            plot_planner.generate_chapter_plan(target_chapters=1, force=True)
        self.assertIn("extraction coverage gap", str(ctx.exception))
        self.assertIn("v1_ch002", str(ctx.exception))

    def test_no_append_mode_unchanged(self) -> None:
        """Default mode (append_count=0) requires force when plan exists."""
        from src import plot_planner

        self._seed_plan(8)
        with self.assertRaises(FileExistsError):
            plot_planner.generate_chapter_plan(target_chapters=5, force=False)

    def test_require_start_point_fails_before_llm(self) -> None:
        from src import plot_planner

        with self.assertRaises(ValueError):
            plot_planner.generate_chapter_plan(
                target_chapters=2,
                force=True,
                require_start_point=True,
            )

    def test_fresh_plan_records_start_chapter_id(self) -> None:
        from src import plot_planner, start_point
        from src.schemas import ChapterPlan

        start_point.set_start_point("v1_ch003")
        fake_plan = {
            "target_chapters": 1,
            "overall_arc": "从第三部之后继续",
            "chapters": [
                {
                    "chapter_no": 1,
                    "title": "新起点",
                    "opening_scene": "起点之后的夜晚。",
                    "key_events": ["承接上一卷结尾", "引出新危机"],
                    "relationships_in_play": [],
                    "ending_hook": "门后传来新的声音。",
                    "target_chinese_chars": 4000,
                    "plot_purpose": "确认新起点。",
                }
            ],
            "generated_by": "test_mock",
        }
        with patch.object(
            plot_planner.LLMClient,
            "complete_json",
            lambda self, msgs, model: ChapterPlan(**fake_plan),
        ):
            result = plot_planner.generate_chapter_plan(
                target_chapters=1,
                force=True,
                require_start_point=True,
            )

        self.assertEqual(result["start_chapter_id"], "v1_ch003")
        saved = json.loads((self.ws_root / "outputs" / "debate" / "chapter_plan.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["start_chapter_id"], "v1_ch003")
        self.assertTrue(saved["start_point_fingerprint"])
        self.assertTrue(saved["plan_fingerprint"])
        self.assertTrue(saved["chapters"][0]["chapter_plan_item_fingerprint"])


if __name__ == "__main__":
    unittest.main()
