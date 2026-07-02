"""iter076 HIGH#5：drive_book_supervised.sh 决策表单测。

SUPERVISE_CMD 注入 stub（照剧本写 driver_state.json / watchdog 标记 + exit code），
SUPERVISE_BACKOFF_BASE=0 零等待。覆盖：crash 重启、上限升级人工、blocked/budget
不重启、paused_reason 分诊、watchdog 标记消费、--resume-first、--detach 拒绝。
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from src.config import ROOT

WORKSPACES_DIR = ROOT / "workspaces"
SCRIPT = ROOT / "scripts" / "drive_book_supervised.sh"

_STUB_SOURCE = """\
import json, os, sys
queue_path = os.environ["SUPERVISE_STUB_QUEUE"]
calls_path = os.environ["SUPERVISE_STUB_CALLS"]
state_path = os.environ["SUPERVISE_STUB_STATE"]
marker_path = os.environ["SUPERVISE_STUB_MARKER"]
with open(calls_path, "a", encoding="utf-8") as fh:
    fh.write(json.dumps(sys.argv[1:], ensure_ascii=False) + "\\n")
with open(queue_path, "r", encoding="utf-8") as fh:
    queue = json.load(fh)
entry = queue.pop(0) if queue else {"exit": 97}
with open(queue_path, "w", encoding="utf-8") as fh:
    json.dump(queue, fh, ensure_ascii=False)
state = entry.get("state")
if state is not None:
    os.makedirs(os.path.dirname(state_path), exist_ok=True)
    with open(state_path, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False)
if entry.get("marker"):
    os.makedirs(os.path.dirname(marker_path), exist_ok=True)
    with open(marker_path, "w", encoding="utf-8") as fh:
        json.dump({"reason": "heartbeat_stale", "by": "stub"}, fh)
sys.exit(int(entry.get("exit", 0)))
"""


class SupervisorTests(unittest.TestCase):
    def setUp(self) -> None:
        WORKSPACES_DIR.mkdir(exist_ok=True)
        self.ws = Path(tempfile.mkdtemp(prefix="unit_supervise_", dir=WORKSPACES_DIR))
        self.addCleanup(shutil.rmtree, self.ws, True)
        self.driver_dir = self.ws / "logs" / "driver"
        self.driver_dir.mkdir(parents=True)
        self.stub = self.ws / "supervise_stub.py"
        self.stub.write_text(_STUB_SOURCE, encoding="utf-8")
        self.queue_path = self.ws / "stub_queue.json"
        self.calls_path = self.ws / "stub_calls.jsonl"
        self.calls_path.write_text("", encoding="utf-8")

    def _run(
        self,
        queue: list,
        *,
        extra_env: dict | None = None,
        script_args: list | None = None,
    ) -> subprocess.CompletedProcess:
        self.queue_path.write_text(json.dumps(queue, ensure_ascii=False), encoding="utf-8")
        env = dict(os.environ)
        env.update(
            {
                "OPENAI_MODEL": "mock",
                "SUPERVISE_CMD": f"{sys.executable} {self.stub}",
                "SUPERVISE_STUB_QUEUE": str(self.queue_path),
                "SUPERVISE_STUB_CALLS": str(self.calls_path),
                "SUPERVISE_STUB_STATE": str(self.driver_dir / "driver_state.json"),
                "SUPERVISE_STUB_MARKER": str(self.driver_dir / "watchdog_abort.json"),
                "SUPERVISE_BACKOFF_BASE": "0",
            }
        )
        env.pop("WORKSPACE_NAME", None)
        env.update(extra_env or {})
        cmd = ["bash", str(SCRIPT), "--book", self.ws.name]
        cmd += script_args if script_args is not None else ["--", "--chapters", "2"]
        return subprocess.run(cmd, cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=60)

    def _calls(self) -> list:
        return [
            json.loads(line)
            for line in self.calls_path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def test_crash_restarts_with_resume_then_succeeds(self) -> None:
        proc = self._run(
            [
                {"exit": 1, "state": {"status": "failed"}},
                {"exit": 0, "state": {"status": "succeeded"}},
            ]
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        calls = self._calls()
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][0], "start")
        self.assertIn("--chapters", calls[0])   # start 透传参数
        self.assertEqual(calls[1][0], "resume")

    def test_gives_up_after_max_restarts(self) -> None:
        queue = [{"exit": 1, "state": {"status": "failed"}} for _ in range(4)]
        proc = self._run(queue, extra_env={"SUPERVISE_MAX_RESTARTS": "2"})
        self.assertEqual(proc.returncode, 75, proc.stderr)
        self.assertIn("GIVING UP", proc.stderr)
        # 1 次 start + 2 次 resume = 3 轮后升级人工
        self.assertEqual(len(self._calls()), 3)

    def test_blocked_exit4_is_terminal_no_restart(self) -> None:
        proc = self._run([{"exit": 4, "state": {"status": "blocked"}}])
        self.assertEqual(proc.returncode, 4, proc.stderr)
        self.assertEqual(len(self._calls()), 1)

    def test_budget_exit3_is_terminal_no_restart(self) -> None:
        proc = self._run([{"exit": 3, "state": {"status": "budget_exceeded"}}])
        self.assertEqual(proc.returncode, 3, proc.stderr)
        self.assertEqual(len(self._calls()), 1)

    def test_paused_step_timeout_auto_resumes(self) -> None:
        proc = self._run(
            [
                {"exit": 0, "state": {"status": "paused", "paused_reason": "step_timeout"}},
                {"exit": 0, "state": {"status": "succeeded"}},
            ]
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        calls = self._calls()
        self.assertEqual([c[0] for c in calls], ["start", "resume"])

    def test_paused_after_segment_is_respected(self) -> None:
        proc = self._run(
            [{"exit": 0, "state": {"status": "paused", "paused_reason": "pause_after_segment"}}]
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(len(self._calls()), 1)
        self.assertIn("human intent", proc.stderr)

    def test_stopped_with_fresh_watchdog_marker_restarts_and_consumes(self) -> None:
        proc = self._run(
            [
                {"exit": 0, "state": {"status": "stopped"}, "marker": True},
                {"exit": 0, "state": {"status": "succeeded"}},
            ]
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual([c[0] for c in self._calls()], ["start", "resume"])
        # 标记被消费改名留证，不会再触发第二次重启
        self.assertFalse((self.driver_dir / "watchdog_abort.json").exists())
        self.assertTrue((self.driver_dir / "watchdog_abort.json.consumed").exists())

    def test_stopped_without_marker_is_human_stop(self) -> None:
        proc = self._run([{"exit": 0, "state": {"status": "stopped"}}])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(len(self._calls()), 1)
        self.assertIn("human stop", proc.stderr)

    def test_resume_first_skips_start(self) -> None:
        proc = self._run(
            [{"exit": 0, "state": {"status": "succeeded"}}],
            script_args=["--resume-first", "--", "--chapters", "2"],
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        calls = self._calls()
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], "resume")

    def test_detach_passthrough_rejected(self) -> None:
        proc = self._run([], script_args=["--", "--chapters", "2", "--detach"])
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertEqual(self._calls(), [])
        self.assertIn("--detach is incompatible", proc.stderr)

    def test_max_rounds_caps_slow_crash_loop(self) -> None:
        # 审查 B M1 / A5a：RESET_SECONDS=0 模拟「每轮都活得够久→计数归零」的慢崩环，
        # 没有总轮次硬顶就是无限循环；SUPERVISE_MAX_ROUNDS=3 → 3 轮后升级人工。
        queue = [{"exit": 1, "state": {"status": "failed"}} for _ in range(10)]
        proc = self._run(
            queue,
            extra_env={
                "SUPERVISE_RESET_SECONDS": "0",
                "SUPERVISE_MAX_ROUNDS": "3",
                "SUPERVISE_MAX_RESTARTS": "99",
            },
        )
        self.assertEqual(proc.returncode, 75, proc.stderr)
        self.assertIn("SUPERVISE_MAX_ROUNDS", proc.stderr)
        self.assertEqual(len(self._calls()), 3)

    def test_second_supervisor_refused_by_pid_mutex(self) -> None:
        # 审查 B L9：同 book 双 supervisor 互斥——supervise.pid 存活即拒启。
        (self.driver_dir / "supervise.pid").write_text(str(os.getpid()), encoding="utf-8")
        proc = self._run([{"exit": 0, "state": {"status": "succeeded"}}])
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("another supervisor is running", proc.stderr)
        self.assertEqual(self._calls(), [])

    def test_stale_supervisor_pid_is_ignored(self) -> None:
        # 死 pid 残留不阻塞（上一晚异常退出的残迹）。
        (self.driver_dir / "supervise.pid").write_text("99999999", encoding="utf-8")
        proc = self._run([{"exit": 0, "state": {"status": "succeeded"}}])
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(len(self._calls()), 1)


if __name__ == "__main__":
    unittest.main()
