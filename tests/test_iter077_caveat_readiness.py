"""iter077 P0-2：caveat×resume 双断点回归。

六方审查确认的两处断点（iter076 caveat_continue 与自动恢复链自相矛盾）：
* 断点A：check_write_readiness 逐章循环不认 caveat_approved → caveat 章被判
  existing_output_not_strict_approved blocker → exit 4 → supervisor 终态。
  iter076 的测试把 _load_chapter_plan 打桩成 None，`if plan:` 循环从未执行，
  生产路径零覆盖——本文件的 readiness 测试**不打桩 plan**（真实 plan 落盘）。
* 断点B：lint 终败章带 failure.json；_mark_caveat_approved 不清理它，而
  chapter_status 要求 not failure 才认 caveat_approved，语义打架 → resume 时
  掉进 BookRunBlocked。修复：caveat 放行时把 marker 原子改名归档
  （*.failure.caveat.json，审计内容保留）。

全部 mock（铁律③）。
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path


VALID_PLAN = {
    "target_chapters": 1,
    "overall_arc": "测试弧线",
    "chapters": [
        {
            "chapter_no": 1,
            "title": "第一章",
            "opening_scene": "开场",
            "key_events": ["事件一", "事件二"],
            "ending_hook": "钩子",
            "plot_purpose": "推进",
        }
    ],
}


class _WorkspaceHarness(unittest.TestCase):
    """真实 tmp workspace：plan/drafts 直接落盘，不打桩 book_runner 内部。"""

    def setUp(self) -> None:
        from src import paths

        os.environ["OPENAI_MODEL"] = "mock"
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._saved_ws_dir = paths.WORKSPACE_DIR
        self._saved_env = os.environ.get("WORKSPACE_NAME")
        paths.WORKSPACE_DIR = Path(self._tmp.name)
        os.environ["WORKSPACE_NAME"] = "iter077cv"
        self.addCleanup(self._restore)
        self.root = paths.WORKSPACE_DIR / "iter077cv"
        for sub in ("小说txt", "data", "outputs/debate", "outputs/drafts", "outputs/reviews", "logs"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        self.drafts = self.root / "outputs" / "drafts"

    def _restore(self) -> None:
        from src import paths

        paths.WORKSPACE_DIR = self._saved_ws_dir
        if self._saved_env is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._saved_env

    def _write_plan(self) -> None:
        from src import paths

        paths.chapter_plan_path().write_text(
            json.dumps(VALID_PLAN, ensure_ascii=False), encoding="utf-8"
        )

    def _seed_chapter(self, *, caveat: bool, failure: bool = False) -> None:
        (self.drafts / "chapter_01.md").write_text("正文……\n", encoding="utf-8")
        meta = {
            "verdict": "Reject",
            "needs_human_review": True,
            "rewrite_count": 2,
        }
        if caveat:
            meta["caveat_approved"] = True
            meta["caveat_reason"] = "panel_soft_reject"
        (self.drafts / "chapter_01.meta.json").write_text(
            json.dumps(meta, ensure_ascii=False), encoding="utf-8"
        )
        if failure:
            (self.drafts / "chapter_01.failure.json").write_text(
                json.dumps({"chapter": 1, "lint_issues": ["x"]}, ensure_ascii=False),
                encoding="utf-8",
            )

    def _readiness(self):
        from src.book_runner import check_write_readiness

        # require_plan=False + 真实 plan 落盘：`if plan:` 逐章循环照样执行（这
        # 正是被 iter076 打桩测试漏掉的生产路径），且避开 plan 元数据 blocker。
        return check_write_readiness(
            chapters=1,
            resume_from=1,
            require_start_point=False,
            require_plan=False,
            require_external_review=False,
        )


class CaveatReadinessTests(_WorkspaceHarness):
    def test_readiness_loop_is_live_for_non_caveat_reject(self) -> None:
        # 对照组（防测试盲区复发）：普通 Reject 章必须仍打出 blocker——证明
        # 本 harness 真的走进了逐章循环，而不是像旧测试那样绕过它。
        self._write_plan()
        self._seed_chapter(caveat=False)
        r = self._readiness()
        self.assertTrue(
            any("existing_output_not_strict_approved" in b for b in r["blockers"]),
            msg=f"blockers={r['blockers']}",
        )

    def test_caveat_chapter_warns_not_blocks(self) -> None:
        # 断点A：caveat 放行章 resume 时 readiness 必须豁免为 warning。
        self._write_plan()
        self._seed_chapter(caveat=True)
        r = self._readiness()
        self.assertFalse(
            any("existing_output_not_strict_approved" in b for b in r["blockers"]),
            msg=f"blockers={r['blockers']}",
        )
        self.assertIn("chapter_01:caveat_approved_present", r["warnings"])
        self.assertNotEqual(r["status"], "blocked")

    def test_caveat_with_failure_marker_blocks_until_archived(self) -> None:
        # 断点B前半：failure.json 未归档时 chapter_status 不认 caveat（旧语义，
        # 保持——failure = 未分诊）；归档后（走 _mark_caveat_approved）放行。
        self._write_plan()
        self._seed_chapter(caveat=True, failure=True)
        r = self._readiness()
        self.assertTrue(any("existing_output" in b for b in r["blockers"]))


class MarkCaveatArchivesFailureTests(_WorkspaceHarness):
    def test_mark_caveat_archives_failure_marker(self) -> None:
        # 断点B：_mark_caveat_approved 必须归档 failure.json（原子改名，内容
        # 保留），否则 chapter_status.caveat_approved 恒 False、resume 永久撞墙。
        from src.book_runner import _mark_caveat_approved
        from src.chapter_status import chapter_status

        self._seed_chapter(caveat=False, failure=True)
        _mark_caveat_approved(self.drafts, 1, reason="panel_soft_reject")

        self.assertFalse((self.drafts / "chapter_01.failure.json").exists())
        archived = self.drafts / "chapter_01.failure.caveat.json"
        self.assertTrue(archived.exists())
        self.assertEqual(
            json.loads(archived.read_text(encoding="utf-8"))["lint_issues"], ["x"]
        )
        meta = json.loads((self.drafts / "chapter_01.meta.json").read_text(encoding="utf-8"))
        self.assertTrue(meta["caveat_approved"])
        self.assertEqual(meta["caveat_archived_failure"], "chapter_01.failure.caveat.json")

        status = chapter_status(1, self.drafts)
        self.assertTrue(status["caveat_approved"])
        self.assertFalse(status["failure"])

    def test_marked_lint_failure_chapter_passes_readiness(self) -> None:
        # 端到端：lint 终败章（md+meta+failure 三件）被 caveat 放行后，readiness
        # 必须给 warning 而非 blocker——过夜自动恢复链的完整闭环。
        from src.book_runner import _mark_caveat_approved

        self._write_plan()
        self._seed_chapter(caveat=False, failure=True)
        _mark_caveat_approved(self.drafts, 1, reason="panel_soft_reject")
        r = self._readiness()
        self.assertFalse(any("existing_output" in b for b in r["blockers"]))
        self.assertIn("chapter_01:caveat_approved_present", r["warnings"])

    def test_mark_caveat_without_failure_marker_unchanged(self) -> None:
        # 无 failure.json 的常规 caveat 路径不受影响（无归档字段）。
        from src.book_runner import _mark_caveat_approved

        self._seed_chapter(caveat=False)
        _mark_caveat_approved(self.drafts, 1, reason="panel_hard_reject")
        meta = json.loads((self.drafts / "chapter_01.meta.json").read_text(encoding="utf-8"))
        self.assertTrue(meta["caveat_approved"])
        self.assertNotIn("caveat_archived_failure", meta)

    def test_archive_sweeps_caveat_failure_artifact(self) -> None:
        # 铁律⑨审查修复：force/retry 归档必须连 *.failure.caveat.json 一起搬走，
        # 否则旧世代审计残片挂在新世代章名下、二次 caveat 时被 os.replace 覆写。
        from src.book_runner import _archive_chapter_artifacts, _mark_caveat_approved

        self._seed_chapter(caveat=False, failure=True)
        _mark_caveat_approved(self.drafts, 1, reason="panel_soft_reject")
        self.assertTrue((self.drafts / "chapter_01.failure.caveat.json").exists())
        archive_dir = _archive_chapter_artifacts(self.drafts, 1, reason="force_rewrite")
        self.assertFalse((self.drafts / "chapter_01.failure.caveat.json").exists())
        self.assertTrue((archive_dir / "chapter_01.failure.caveat.json").exists())


if __name__ == "__main__":
    unittest.main()
