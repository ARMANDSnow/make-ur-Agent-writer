"""iter078 P1-5：rolling summary 落盘顺序回归。

六方审查确认：旧顺序（summarize → rolling 落盘 → entity 提案 → persist
正文）被杀在窗口内会留下「rolling 已含本章摘要、正文不存在」的毒行——
resume 对该章 fresh write 时，写作 prompt 的 rolling_context 会注入被
丢弃稿的摘要（自我毒化；append 的替换语义只在写完后生效，救不了写前的
prompt 组装）。

本文件钉死：①新顺序（persist 正文+meta → summarize/rolling → 提案）的
杀点性质；②book_runner fresh-write 前 prune 在 **writer 调用前** 清毒行；
③readiness 的 rolling_summary_gap warning（只 WARN 不 block）；
④prune 无残迹时不重写文件。全部 mock（铁律③）。
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

from src.chapter_summary import append_chapter_summary, load_rolling_summary, prune_from_chapter
from src.writer import write_chapters

import tests.test_book_runner as tb


def _writer_fixture(tmp: Path) -> Path:
    drafts = tmp / "drafts"
    drafts.mkdir(parents=True)
    (tmp / "outline.md").write_text("# test outline", encoding="utf-8")
    (tmp / "global_knowledge.md").write_text("# test knowledge", encoding="utf-8")
    (tmp / "knowledge_index.json").write_text("{}", encoding="utf-8")
    return drafts


def _chapter_nos(rolling: Path) -> set:
    data = load_rolling_summary(rolling)
    return {
        int(item.get("chapter_no", 0))
        for lst in (data.get("chapters"), data.get("compressed_older"))
        for item in (lst or [])
        if isinstance(item, dict)
    }


class _WriterFixtureMixin(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.drafts = _writer_fixture(self.tmp)
        for name, target in (
            ("DRAFTS_DIR", self.drafts),
            ("OUTLINE_PATH", self.tmp / "outline.md"),
            ("KB_PATH", self.tmp / "global_knowledge.md"),
            ("INDEX_PATH", self.tmp / "knowledge_index.json"),
        ):
            p = patch(f"src.writer.{name}", target)
            p.start()
            self.addCleanup(p.stop)
        self.rolling = self.drafts / "rolling_chapter_summary.json"


class PersistBeforeRollingTests(_WriterFixtureMixin):
    def test_summarize_crash_leaves_body_persisted_rolling_clean_no_partial(self) -> None:
        # 杀点注入：进程死在 summarize 段 = 旧顺序的毒化窗口。
        with patch("src.writer._summarize_chapter", side_effect=RuntimeError("killed in window")):
            with self.assertRaises(RuntimeError):
                write_chapters(chapters=1, force=True)
        # 新顺序：正文+meta 已持久化（可被 resume 识别/跳过）……
        self.assertTrue((self.drafts / "chapter_01.md").exists())
        self.assertTrue((self.drafts / "chapter_01.meta.json").exists())
        # ……rolling 无本章条目（旧顺序在此已有毒行——反向断言钉死顺序）……
        self.assertNotIn(1, _chapter_nos(self.rolling))
        # ……且不写误导性 partial（正文已是完整产物）。
        self.assertFalse((self.drafts / "chapter_01.partial.md").exists())

    def test_crash_before_persist_still_writes_partial(self) -> None:
        # 对照组：死在 persist 之前（draft 已生成、needs_polish 计算段——
        # count_chinese_chars 首调点 :297）→ partial 语义保持旧行为。
        # （不能用 review_text：裸 fixture 的 mock 稿必然 lint 失败，主
        # review 不会被调，shadow review 的异常又被 try/except 吞掉。）
        with patch("src.writer.count_chinese_chars", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                write_chapters(chapters=1, force=True)
        self.assertFalse((self.drafts / "chapter_01.md").exists())
        self.assertTrue((self.drafts / "chapter_01.partial.md").exists())

    def test_success_path_appends_rolling_after_persist(self) -> None:
        # sanity：顺序调整没有丢 rolling——成功章正文与 rolling 条目双双在盘，
        # reports 仍带 proposal_path（reports.append 后移的回归）。
        reports = write_chapters(chapters=1, force=True)
        self.assertTrue((self.drafts / "chapter_01.md").exists())
        self.assertIn(1, _chapter_nos(self.rolling))
        self.assertTrue(reports and reports[0]["written"])
        self.assertIn("proposal_path", reports[0])


class PruneNoopTests(unittest.TestCase):
    def test_prune_skips_save_when_no_residue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rolling.json"
            append_chapter_summary(1, "s", ["e"], "end", path=path)
            before = path.read_text(encoding="utf-8")
            prune_from_chapter(5, path=path)  # 无残迹 → 不重写
            self.assertEqual(path.read_text(encoding="utf-8"), before)
            prune_from_chapter(1, path=path)  # 命中 → 正常剪除
            self.assertEqual(load_rolling_summary(path).get("chapters"), [])


class _RunnerFixture:
    """run_write_book / check_write_readiness 的最小打桩组（仿 test_book_runner）。"""

    def __init__(self, root: Path, *, plan_chapters: int, chapter_status_fn: Any) -> None:
        self.root = root
        self.drafts = root / "outputs" / "drafts"
        self.drafts.mkdir(parents=True, exist_ok=True)
        self.rolling = self.drafts / "rolling_chapter_summary.json"
        plan = tb._strict_plan(chapters=plan_chapters)
        parsed = {int(i["chapter_no"]): dict(i) for i in plan["chapters"]}
        self.patches = [
            patch("src.book_runner.start_point.get_start_chapter_id", return_value="v1_ch003"),
            patch("src.book_runner.start_point.start_point_fingerprint", return_value="start-fp"),
            patch("src.book_runner._load_raw_chapter_plan", return_value=plan),
            patch("src.book_runner._load_chapter_plan", return_value=parsed),
            patch("src.book_runner.paths.workspace_name", return_value="unit"),
            patch("src.book_runner.paths.workspace_root", return_value=root),
            patch("src.book_runner.paths.drafts_dir", return_value=self.drafts),
            patch("src.book_runner.paths.entity_graph_path", return_value=root / "data" / "entity_graph.json"),
            patch("src.book_runner.paths.llm_calls_log_path", return_value=root / "logs" / "llm_calls.jsonl"),
            patch(
                "src.book_runner.run_preflight",
                return_value={"status": "ok", "fatal": [], "warn": [], "info": []},
            ),
            patch("src.book_runner.chapter_status", side_effect=chapter_status_fn),
            patch("src.chapter_summary.paths.rolling_summary_path", return_value=self.rolling),
        ]

    def __enter__(self) -> "_RunnerFixture":
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        for p in reversed(self.patches):
            p.stop()


def _status(chapter_no: int, *, written: bool) -> Dict[str, Any]:
    return {
        "chapter_no": chapter_no,
        "exists": written,
        "approved": written,
        "needs_review": False,
        "failure": False,
        "verdict": "Approve" if written else None,
        "rewrite_count": 0,
        "strict_failures": [],
    }


class FreshWritePruneTests(unittest.TestCase):
    def test_fresh_write_prunes_poison_before_writer_runs(self) -> None:
        from src.book_runner import run_write_book

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            state: Dict[str, Any] = {"written": False, "rolling_at_write": None}

            def status_fn(chapter_no: int, *a: Any, **k: Any) -> Dict[str, Any]:
                return _status(chapter_no, written=state["written"])

            fx = _RunnerFixture(root, plan_chapters=1, chapter_status_fn=status_fn)
            # 毒行：ch1 的 rolling 条目在盘、正文不存在（旧序死亡窗口盘面）。
            append_chapter_summary(1, "被丢弃稿的摘要（毒）", ["毒"], "毒", path=fx.rolling)

            def fake_write_chapters(**kwargs: Any) -> list:
                # 记录 writer 被调用瞬间的 rolling 状态——prune 必须已发生。
                state["rolling_at_write"] = _chapter_nos(fx.rolling)
                (fx.drafts / "chapter_01.md").write_text("新稿\n", encoding="utf-8")
                state["written"] = True
                return [{"chapter": 1, "written": True, "review": {"verdict": "Approve"}}]

            with fx, patch("src.book_runner.write_chapters", side_effect=fake_write_chapters):
                result = run_write_book(
                    chapters=1,
                    auto_advance=False,
                    require_external_review=False,
                )

        self.assertEqual(result.get("status"), "succeeded")
        self.assertEqual(state["rolling_at_write"], set(), "writer 调用前毒行未被 prune")


class ReadinessRollingGapTests(unittest.TestCase):
    def _readiness(self, *, seed_rolling: bool) -> Dict[str, Any]:
        from src.book_runner import check_write_readiness

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)

            def status_fn(chapter_no: int, *a: Any, **k: Any) -> Dict[str, Any]:
                return _status(chapter_no, written=False)

            fx = _RunnerFixture(root, plan_chapters=3, chapter_status_fn=status_fn)
            (fx.drafts / "chapter_01.md").write_text("正文", encoding="utf-8")
            if seed_rolling:
                # rolling 非空（有 ch2 条目）但缺 ch1 → prev-chapter gap 命中
                append_chapter_summary(2, "s", [], "end", path=fx.rolling)
            with fx:
                return check_write_readiness(chapters=2, resume_from=2)

    def test_gap_warning_for_written_prev_chapter_missing_rolling(self) -> None:
        readiness = self._readiness(seed_rolling=True)
        self.assertIn("rolling_summary_gap:01", readiness["warnings"])
        self.assertEqual(readiness["status"], "warn")  # 只 WARN 不 block

    def test_no_gap_warning_when_rolling_entirely_empty(self) -> None:
        # 手工搭建/迁移 workspace 没有 rolling 属正常形态（铁律④）——不误报。
        readiness = self._readiness(seed_rolling=False)
        self.assertFalse(
            [w for w in readiness["warnings"] if w.startswith("rolling_summary_gap")]
        )


if __name__ == "__main__":
    unittest.main()
