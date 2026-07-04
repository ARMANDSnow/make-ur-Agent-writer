"""iter077 P0-4：孤儿 write-book 收割回归。

六方审查交叉确认（A1#3 / A3-F1 / codex HIGH）：child 以 start_new_session 自成
会话，driver 被 SIGKILL（watchdog TERM 无效后升级）时 child 存活继续烧钱；
supervisor 的自动重启只走 resume，而 cmd_resume/cmd_start 此前完全不看
state["child_pid"] → 新旧双写者并发写同一 drafts。另两条独立成孤路径（A5#2/#3）：
_run_step 编排层 OSError 绕过 _terminate_child；TERM 落在 Popen 前窗口。

用真实进程组（sleep 子进程）验证收割/不误杀；全部 mock（铁律③），零 LLM 调用。
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import unittest
from unittest.mock import patch

from src import book_driver
from src.utils import write_json

from tests.test_book_driver import _WorkspaceMixin, _driver_args


def _proc_dead_within(proc: subprocess.Popen, seconds: float) -> bool:
    # 孤儿在测试里是测试进程的直接子进程：死后变僵尸（os.kill(pid,0) 仍成功），
    # 必须 poll() 收割后再判活——生产里孤儿由 init 收割，无此问题。
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return True
        time.sleep(0.1)
    return proc.poll() is not None


def _pid_dead_within(pid: int, seconds: float) -> bool:
    # _run_step 内部已 child.wait() 收割，直接按 pid 判活即可。
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not book_driver._pid_alive(pid):
            return True
        time.sleep(0.1)
    return not book_driver._pid_alive(pid)


class _SpawnMixin(_WorkspaceMixin):
    def _spawn(self, *, marker: bool) -> subprocess.Popen:
        # marker=True 时在 argv 尾部挂一个 step 子命令关键字（python -c 忽略
        # 多余 argv），让 `ps -o command=` 的判别式命中；False = 无关进程。
        argv = [sys.executable, "-c", "import time; time.sleep(60)"]
        if marker:
            argv.append("write-book")
        proc = subprocess.Popen(
            argv,
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if hasattr(self, "_cmdlines"):
            self._cmdlines[proc.pid] = " ".join(argv)
        self.addCleanup(self._kill_quiet, proc)
        return proc

    @staticmethod
    def _kill_quiet(proc: subprocess.Popen) -> None:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            proc.wait(timeout=5)
        except Exception:
            pass


class ReapOrphanChildTests(_SpawnMixin, unittest.TestCase):
    def setUp(self) -> None:
        self.ws = self._make_workspace("iter077orphan_")
        self._cmdlines = {}
        cmdline = patch("src.book_driver._child_cmdline", side_effect=lambda pid: self._cmdlines.get(int(pid), ""))
        cmdline.start()
        self.addCleanup(cmdline.stop)
        # 僵尸子进程在宽限循环里显示为「活」（见 _proc_dead_within 注释）——
        # 缩短宽限让测试不用干等 30s；升级路径的 EPERM 兜底同样被覆盖到。
        grace = patch.object(book_driver, "_KILL_GRACE_SECONDS", 1)
        grace.start()
        self.addCleanup(grace.stop)

    def test_reaps_live_step_process_group(self) -> None:
        proc = self._spawn(marker=True)
        state = {"run_id": "t", "child_pid": proc.pid}
        self.assertTrue(book_driver._reap_orphan_child(state))
        self.assertTrue(_proc_dead_within(proc, 10))
        self.assertIsNone(state["child_pid"])

    def test_does_not_kill_unrelated_process(self) -> None:
        # pid 复用保险：命令行不含 step 子命令（如 main.py web dashboard）→
        # 不杀，只清 stale 指针。
        proc = self._spawn(marker=False)
        state = {"run_id": "t", "child_pid": proc.pid}
        self.assertFalse(book_driver._reap_orphan_child(state))
        self.assertTrue(book_driver._pid_alive(proc.pid))
        self.assertIsNone(state["child_pid"])

    def test_recorded_argv_mismatch_not_killed(self) -> None:
        # 铁律⑨审查修复：state 记录了启动 argv（iter077 起）时按精确比对——
        # marker 命中但 argv 不同（pid 复用给另一 workspace 的 step）不杀。
        proc = self._spawn(marker=True)  # cmdline 含 "write-book" marker
        state = {
            "run_id": "t",
            "child_pid": proc.pid,
            "child_cmd": ["python", "main.py", "--book", "other_book", "write-book"],
        }
        self.assertFalse(book_driver._reap_orphan_child(state))
        self.assertTrue(book_driver._pid_alive(proc.pid))
        self.assertIsNone(state["child_pid"])
        self.assertIsNone(state["child_cmd"])

    def test_recorded_argv0_reexec_still_reaped(self) -> None:
        # iter078 收官审查修复：macOS framework Python 自我 re-exec 后 ps 的
        # argv[0] 变成 Python.app 路径，与记录的 sys.executable 永不相等——
        # 旧整串精确比对把每个真孤儿判成 pid 复用放行。比对改 argv[1:] 尾部，
        # argv[0] 不同的真孤儿必须照常收割。
        proc = self._spawn(marker=True)
        self._cmdlines[proc.pid] = "/System/Python.app/Contents/MacOS/Python -c import time; time.sleep(60) write-book"
        state = {
            "run_id": "t",
            "child_pid": proc.pid,
            "child_cmd": ["/nonexistent/venv/bin/python3", "-c", "import time; time.sleep(60)", "write-book"],
        }
        self.assertTrue(book_driver._reap_orphan_child(state))
        self.assertTrue(_proc_dead_within(proc, 10))
        self.assertIsNone(state["child_pid"])
        self.assertIsNone(state["child_cmd"])

    def test_ps_failure_reaps_unverified_without_cmdline_crash(self) -> None:
        # 当前 Codex 沙箱会拒绝 ps；生产策略是不要清指针放行第二写者，而是
        # 按 state 记录的 child_pid 保守收割。这里钉住 None 分支不再崩溃。
        proc = self._spawn(marker=False)
        self._cmdlines[proc.pid] = None
        state = {"run_id": "t", "child_pid": proc.pid}
        self.assertTrue(book_driver._reap_orphan_child(state))
        self.assertTrue(_proc_dead_within(proc, 10))
        self.assertIsNone(state["child_pid"])

    def test_cmd_stop_reaps_with_escalation(self) -> None:
        # 铁律⑨审查修复：cmd_stop 的孤儿收割改走 _reap_orphan_child——获得
        # cmdline 判别 + KILL 升级（旧内联版一枪 TERM 后就走人）。
        import io
        from contextlib import redirect_stdout

        proc = self._spawn(marker=True)
        book_driver.driver_dir().mkdir(parents=True, exist_ok=True)
        write_json(
            book_driver.state_path(),
            {
                "run_id": "t",
                "book": os.environ["WORKSPACE_NAME"],
                "params": {},
                "status": "running",
                "segments": [],
                "child_pid": proc.pid,
                "child_cmd": [sys.executable, "-c", "import time; time.sleep(60)", "write-book"],
            },
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = book_driver.cmd_stop(type("A", (), {"json": False})())
        self.assertEqual(rc, 0)
        self.assertIn("stopped", buf.getvalue())
        self.assertTrue(_proc_dead_within(proc, 10))
        state = book_driver.load_state()
        self.assertIsNone(state.get("child_pid"))
        self.assertIsNone(state.get("child_cmd"))

    def test_noop_without_child_pid_or_dead_pid(self) -> None:
        self.assertFalse(book_driver._reap_orphan_child({"run_id": "t", "child_pid": None}))
        proc = self._spawn(marker=True)
        self._kill_quiet(proc)
        self.assertTrue(_proc_dead_within(proc, 10))
        self.assertFalse(book_driver._reap_orphan_child({"run_id": "t", "child_pid": proc.pid}))

    def test_resume_reaps_orphan_before_launch(self) -> None:
        # supervisor 自动重启的真实路径：盘面 state 带活孤儿 → resume 必须先
        # 收割再 _launch。
        proc = self._spawn(marker=True)
        book_driver.driver_dir().mkdir(parents=True, exist_ok=True)
        write_json(
            book_driver.state_path(),
            {
                "run_id": "t",
                "book": os.environ["WORKSPACE_NAME"],
                "params": {},
                "status": "running",
                "child_pid": proc.pid,
                "attempt": 1,
                "step_seq": 1,
            },
        )
        with patch("src.book_driver._launch", return_value=0) as launch:
            rc = book_driver.main(_driver_args(action="resume", cmd_prefix=None))
        self.assertEqual(rc, 0)
        self.assertTrue(launch.called)
        self.assertTrue(_proc_dead_within(proc, 10))

    def test_start_reaps_orphan_from_previous_state(self) -> None:
        proc = self._spawn(marker=True)
        book_driver.driver_dir().mkdir(parents=True, exist_ok=True)
        write_json(
            book_driver.state_path(),
            {"run_id": "old", "book": os.environ["WORKSPACE_NAME"], "params": {}, "child_pid": proc.pid},
        )
        with patch("src.book_driver._launch", return_value=0):
            rc = book_driver.main(_driver_args(action="start", cmd_prefix=None))
        self.assertEqual(rc, 0)
        self.assertTrue(_proc_dead_within(proc, 10))


class RunStepStopWindowTests(_SpawnMixin, unittest.TestCase):
    def setUp(self) -> None:
        self.ws = self._make_workspace("iter077stopw_")
        self.addCleanup(setattr, book_driver, "_STOP_REQUESTED", False)

    def test_stop_requested_before_popen_skips_launch(self) -> None:
        # TERM 落在「上次检查后、Popen 前」窗口：不再启动新子进程。
        marker = self.ws / "spawned.txt"
        state = {
            "run_id": "t",
            "attempt": 1,
            "step_seq": 1,
            "params": {"cmd_prefix": [sys.executable, "-c", f"open({str(marker)!r}, 'w').write('x')"]},
        }
        book_driver._STOP_REQUESTED = True
        res = book_driver._run_step(state, "win", ["preflight"], timeout_minutes=1)
        self.assertEqual(res.exit_code, 143)
        self.assertFalse(res.timed_out)
        self.assertFalse(marker.exists(), "child must not be spawned after stop request")

    def test_stop_requested_mid_wait_kills_child(self) -> None:
        # handler 竞态兜底：flag 在等待切片之间被置位（模拟 TERM 到达时
        # _CURRENT_CHILD 尚未赋值、子进程没吃到 killpg）→ 切片轮询补杀。
        calls = {"n": 0}

        def hb(*args, **kwargs):
            calls["n"] += 1
            if calls["n"] >= 2:
                book_driver._STOP_REQUESTED = True

        state = {
            "run_id": "t",
            "attempt": 1,
            "step_seq": 1,
            "params": {"cmd_prefix": [sys.executable, "-c", "import time; time.sleep(30)"]},
        }
        started = time.monotonic()
        with patch.object(book_driver, "_HEARTBEAT_INTERVAL_SECONDS", 0.3), patch(
            "src.book_driver._write_heartbeat", side_effect=hb
        ):
            res = book_driver._run_step(state, "midstop", ["preflight"], timeout_minutes=5)
        elapsed = time.monotonic() - started
        self.assertLess(elapsed, 20.0)
        self.assertFalse(res.timed_out)
        self.assertNotEqual(res.exit_code, 0)
        child_pid = None if state["child_pid"] is None else state["child_pid"]
        if child_pid:
            self.assertTrue(_pid_dead_within(child_pid, 10))

    def test_emit_oserror_on_timeout_still_reaps_child(self) -> None:
        # A5#2：磁盘满时 _emit(step_timeout) 抛 OSError——先杀后 emit + finally
        # 无条件收割，超时子进程不再成为永生孤儿。
        real_emit = book_driver._emit

        def emit(state, event, **payload):
            if event == "step_timeout":
                raise OSError("disk full")
            return real_emit(state, event, **payload)

        state = {
            "run_id": "t",
            "attempt": 1,
            "step_seq": 1,
            "params": {"cmd_prefix": [sys.executable, "-c", "import time; time.sleep(30)"]},
        }
        with patch("src.book_driver._emit", side_effect=emit):
            with self.assertRaises(OSError):
                book_driver._run_step(state, "boom", ["preflight"], timeout_minutes=1 / 60)
        child_pid = state.get("child_pid")
        self.assertIsNotNone(child_pid, "child_pid should have been persisted before the crash")
        self.assertTrue(_pid_dead_within(int(child_pid), 10), "timed-out child must not survive the emit crash")


if __name__ == "__main__":
    unittest.main()
