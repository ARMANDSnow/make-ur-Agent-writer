"""iter078 P1-7：workspace 写锁回归。

六方审查确认：Web job 的防重是进程内 ``_WORKSPACE_JOBS`` 内存 dict、CLI
driver 的防重是 ``driver.pid``，两套互不可见——同一 workspace 可同时被
Web 线程与 CLI 子进程写 drafts/。本文件钉死 src/workspace_lock.py 的
互斥语义（含真实跨进程 flock 与 SIGKILL 自动释放），以及 run_write_book
拿不到锁 → BookRunBlocked（零新退出码契约）。

全部 mock（铁律③），零 LLM 调用；跨进程用真实子进程（仿
test_iter077_orphan_reaping.py 的模式）。
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from src import paths, workspace_lock
from src.workspace_lock import WorkspaceLocked, acquire_write_lock

from tests.test_book_driver import _WorkspaceMixin


class LockContentionTests(_WorkspaceMixin, unittest.TestCase):
    def setUp(self) -> None:
        self.ws = self._make_workspace("iter078lock_")

    def test_lock_path_sits_in_workspace_root(self) -> None:
        self.assertEqual(
            workspace_lock.lock_path(), paths.workspace_root() / "write.lock"
        )

    def test_second_acquire_raises_with_holder_info(self) -> None:
        # 同进程两次独立 open() 也互斥（flock 按 open file description 计）。
        with acquire_write_lock(source="first-writer"):
            with self.assertRaises(WorkspaceLocked) as ctx:
                with acquire_write_lock(source="second-writer"):
                    pass
        msg = str(ctx.exception)
        self.assertIn("workspace_locked", msg)
        self.assertIn("first-writer", msg)
        self.assertIn(str(os.getpid()), msg)

    def test_lock_released_after_with_block(self) -> None:
        with acquire_write_lock(source="a"):
            pass
        with acquire_write_lock(source="b"):
            pass  # 不抛 = 已释放

    def test_lock_released_on_exception(self) -> None:
        with self.assertRaises(RuntimeError):
            with acquire_write_lock(source="a"):
                raise RuntimeError("boom")
        with acquire_write_lock(source="b"):
            pass

    def test_holder_file_written_and_cleaned(self) -> None:
        lock = workspace_lock.lock_path()
        holder = lock.with_name(lock.name + ".holder.json")
        with acquire_write_lock(source="probe"):
            self.assertTrue(holder.exists())
            self.assertIn("probe", holder.read_text(encoding="utf-8"))
        self.assertFalse(holder.exists())


class CrossProcessLockTests(_WorkspaceMixin, unittest.TestCase):
    def setUp(self) -> None:
        self.ws = self._make_workspace("iter078lockx_")

    def test_other_process_blocked_and_sigkill_auto_releases(self) -> None:
        sentinel = self.ws / "child_locked"
        child_code = (
            "import time\n"
            "from pathlib import Path\n"
            "from src.workspace_lock import acquire_write_lock\n"
            "with acquire_write_lock(source='child-holder'):\n"
            f"    Path({str(sentinel)!r}).write_text('1', encoding='utf-8')\n"
            "    time.sleep(60)\n"
        )
        proc = subprocess.Popen(
            [sys.executable, "-c", child_code],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self.addCleanup(self._kill_quiet, proc)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline and not sentinel.exists():
            time.sleep(0.05)
        self.assertTrue(sentinel.exists(), "child 未能在期限内拿到锁")

        with self.assertRaises(WorkspaceLocked) as ctx:
            with acquire_write_lock(source="parent"):
                pass
        self.assertIn("child-holder", str(ctx.exception))

        # SIGKILL（不给任何清理机会）后 flock 必须由内核自动释放——这是
        # 选 flock 而非 O_EXCL 守卫文件的全部理由。
        proc.kill()
        proc.wait(timeout=5)
        with acquire_write_lock(source="parent-after-kill"):
            pass  # 不抛 = 自动释放成立

    @staticmethod
    def _kill_quiet(proc: subprocess.Popen) -> None:
        try:
            proc.kill()
        except OSError:
            pass
        try:
            proc.wait(timeout=5)
        except Exception:
            pass


class RunWriteBookLockTests(_WorkspaceMixin, unittest.TestCase):
    def setUp(self) -> None:
        self.ws = self._make_workspace("iter078lockrb_")

    def test_run_write_book_blocked_when_lock_held(self) -> None:
        from src.book_runner import BookRunBlocked, run_write_book

        # 锁在 readiness 之前获取，所以裸 workspace 也能命中该分支。
        with acquire_write_lock(source="occupier"):
            with self.assertRaises(BookRunBlocked) as ctx:
                run_write_book(chapters=1)
        msg = str(ctx.exception)
        self.assertIn("workspace_locked", msg)
        self.assertIn("occupier", msg)

    def test_run_write_book_releases_lock_on_blocked_readiness(self) -> None:
        from src.book_runner import BookRunBlocked, run_write_book

        # 裸 workspace：readiness 必 blocked → BookRunBlocked，但锁必须已释放。
        with self.assertRaises(BookRunBlocked):
            run_write_book(chapters=1)
        with acquire_write_lock(source="after"):
            pass  # 不抛 = run_write_book 异常路径正确释放


class OtherWriteSurfaceLockTests(_WorkspaceMixin, unittest.TestCase):
    def setUp(self) -> None:
        self.ws = self._make_workspace("iter078locksurf_")

    def test_auto_pipeline_blocks_before_prepare_steps(self) -> None:
        from src.auto_pipeline import run_auto_pipeline

        with acquire_write_lock(source="occupier"):
            with patch("src.auto_pipeline.normalize_all", side_effect=AssertionError("must not run")):
                with self.assertRaises(WorkspaceLocked) as ctx:
                    run_auto_pipeline(target_chapters=1, extract_limit=1)
        self.assertIn("workspace_locked", str(ctx.exception))

    def test_web_review_chapter_blocks_when_writer_active(self) -> None:
        from src.web import jobs

        drafts = paths.drafts_dir()
        drafts.mkdir(parents=True, exist_ok=True)
        (drafts / "chapter_01.md").write_text("正文", encoding="utf-8")
        item = {"chapter_no": 1, "title": "一"}

        with acquire_write_lock(source="occupier"):
            with patch("src.writer._load_chapter_plan", return_value=[item]), patch(
                "src.writer._chapter_plan_item", return_value=item
            ), patch("src.reviewer.review_target", side_effect=AssertionError("must not review")):
                result = jobs._step_review_chapter({"chapter": 1}, lambda *_: None)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["blocked"][0]["reason"], "workspace_locked")


if __name__ == "__main__":
    unittest.main()
