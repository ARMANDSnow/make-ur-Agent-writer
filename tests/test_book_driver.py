"""iter 052a: long-run driver (src/book_driver.py) tests.

分三层：

* 纯函数单测（parse_last_json_line / plan_segments）；
* 状态机单测——用 ``--cmd-prefix`` 把子进程替换成照剧本退出的 stub 脚本，
  钉死段切分、resume 跳过、终态映射、预算双层、互斥与确认闸；
* mock 真管道 E2E（DriverE2ETests）——真 workspace + 真 main.py 子进程，
  断点续跑全链：pause → WRITER_FORCE_FAIL 注入 → resume 零重写 →
  清除注入 → resume 收口 succeeded。
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src import book_driver, paths
from src.config import ROOT
from src.llm_client import LLMClient
from src.utils import read_json, write_json

WORKSPACES_DIR = ROOT / "workspaces"

# stub 子进程：把收到的 argv 记账到 DRIVER_STUB_CALLS，然后按
# DRIVER_STUB_QUEUE 里第一条 cmd 命中的剧本输出/退出。未排剧本 → exit 97。
_STUB_SOURCE = """\
import json, os, sys
calls_path = os.environ["DRIVER_STUB_CALLS"]
queue_path = os.environ["DRIVER_STUB_QUEUE"]
with open(calls_path, "a", encoding="utf-8") as fh:
    fh.write(json.dumps(sys.argv[1:], ensure_ascii=False) + "\\n")
with open(queue_path, "r", encoding="utf-8") as fh:
    queue = json.load(fh)
for i, entry in enumerate(queue):
    if entry["cmd"] in sys.argv[1:]:
        queue.pop(i)
        with open(queue_path, "w", encoding="utf-8") as fh:
            json.dump(queue, fh, ensure_ascii=False)
        for line in entry.get("stdout", []):
            print(line)
        sys.exit(int(entry.get("exit", 0)))
print("unscripted stub call: " + " ".join(sys.argv[1:]), file=sys.stderr)
sys.exit(97)
"""


def _driver_args(**overrides):
    base = dict(
        action="start",
        chapters=2,
        resume_from=1,
        segment_size=1,
        replan_every=0,
        plan_target=2,
        budget_cny=None,
        tier=None,
        max_retries=2,
        skip_debate=True,
        require_start_point=False,
        allow_missing_start_point=True,
        allow_missing_plan=False,
        skip_external_review=False,
        pause_after_segment=None,
        step_timeout_minutes=None,
        on_blocked=None,
        detach=False,
        confirm_real_run=False,
        json=False,
        cmd_prefix=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


class _WorkspaceMixin:
    """临时 workspace（落在 workspaces/ 下，paths.py 的 ROOT 是写死的）。"""

    def _make_workspace(self, prefix: str) -> Path:
        WORKSPACES_DIR.mkdir(exist_ok=True)
        ws = Path(tempfile.mkdtemp(prefix=prefix, dir=WORKSPACES_DIR))
        self.addCleanup(shutil.rmtree, ws, True)
        env = patch.dict(os.environ, {"WORKSPACE_NAME": ws.name}, clear=False)
        env.start()
        self.addCleanup(env.stop)
        return ws

    def _install_stub(self, ws: Path, queue: list) -> tuple[str, Path, Path]:
        stub = ws / "driver_stub.py"
        stub.write_text(_STUB_SOURCE, encoding="utf-8")
        queue_path = ws / "stub_queue.json"
        calls_path = ws / "stub_calls.jsonl"
        queue_path.write_text(json.dumps(queue, ensure_ascii=False), encoding="utf-8")
        calls_path.write_text("", encoding="utf-8")
        env = patch.dict(
            os.environ,
            {"DRIVER_STUB_QUEUE": str(queue_path), "DRIVER_STUB_CALLS": str(calls_path)},
            clear=False,
        )
        env.start()
        self.addCleanup(env.stop)
        prefix = f"{shlex.quote(sys.executable)} {shlex.quote(str(stub))}"
        return prefix, queue_path, calls_path

    def _seed_plan(self, count: int) -> None:
        plan_path = paths.chapter_plan_path()
        plan_path.parent.mkdir(parents=True, exist_ok=True)
        write_json(plan_path, {"chapters": [{"chapter_no": i + 1} for i in range(count)]})

    def _calls(self, calls_path: Path) -> list:
        return [json.loads(line) for line in calls_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def _preserve_signals(self) -> None:
        for sig in (signal.SIGTERM, signal.SIGINT):
            original = signal.getsignal(sig)
            self.addCleanup(signal.signal, sig, original)


def _ready_json() -> str:
    return json.dumps({"status": "ready", "blockers": [], "warnings": []})


def _wb_json(*chapters: tuple[int, str, str], status: str = "succeeded", **extra) -> str:
    return json.dumps(
        {
            "status": status,
            "chapters": [
                {"chapter": no, "action": action, "status": {"verdict": verdict}}
                for no, action, verdict in chapters
            ],
            **extra,
        },
        ensure_ascii=False,
    )


class ParseLastJsonLineTests(unittest.TestCase):
    def test_finds_last_json_among_noise(self) -> None:
        text = "progress 10%\n{\"status\": \"old\"}\nnoise\n{\"status\": \"succeeded\"}\ntrailing noise\n"
        self.assertEqual(book_driver.parse_last_json_line(text), {"status": "succeeded"})

    def test_skips_invalid_and_non_dict_lines(self) -> None:
        text = "{broken json}\n[1, 2, 3]\n{\"ok\": true}\n{not json either\n"
        self.assertEqual(book_driver.parse_last_json_line(text), {"ok": True})

    def test_returns_none_when_no_json(self) -> None:
        self.assertIsNone(book_driver.parse_last_json_line("plain\nlines\nonly\n"))
        self.assertIsNone(book_driver.parse_last_json_line(""))


class PlanSegmentsTests(unittest.TestCase):
    def test_exact_split(self) -> None:
        self.assertEqual(book_driver.plan_segments(30, 1, 5), [(1, 5), (6, 10), (11, 15), (16, 20), (21, 25), (26, 30)])

    def test_remainder_segment(self) -> None:
        self.assertEqual(book_driver.plan_segments(7, 1, 3), [(1, 3), (4, 6), (7, 7)])

    def test_resume_from_offset(self) -> None:
        self.assertEqual(book_driver.plan_segments(4, 11, 2), [(11, 12), (13, 14)])

    def test_zero_chapters_is_empty(self) -> None:
        self.assertEqual(book_driver.plan_segments(0, 1, 5), [])

    def test_segment_size_floor_is_one(self) -> None:
        self.assertEqual(book_driver.plan_segments(2, 1, 0), [(1, 1), (2, 2)])


class DriverStateMachineTests(_WorkspaceMixin, unittest.TestCase):
    def setUp(self) -> None:
        self._preserve_signals()
        self.ws = self._make_workspace("unit_driver_sm_")
        self._seed_plan(4)

    def test_segments_split_and_succeed(self) -> None:
        prefix, _, calls_path = self._install_stub(
            self.ws,
            [
                {"cmd": "preflight", "exit": 0, "stdout": ["preflight ok"]},
                {"cmd": "write-readiness", "exit": 0, "stdout": [_ready_json()]},
                {
                    "cmd": "write-book",
                    "exit": 0,
                    "stdout": ["noise before", _wb_json((1, "written", "Approve"), (2, "written", "Approve"))],
                },
                {
                    "cmd": "write-book",
                    "exit": 0,
                    "stdout": [_wb_json((3, "written", "Approve"), (4, "written", "Approve")), "noise after json"],
                },
            ],
        )
        rc = book_driver.main(_driver_args(chapters=4, segment_size=2, cmd_prefix=prefix))
        self.assertEqual(rc, 0)
        state = book_driver.load_state()
        self.assertEqual(state["status"], "succeeded")
        self.assertEqual(state["segments_total"], 2)
        self.assertEqual([s["status"] for s in state["segments"]], ["succeeded", "succeeded"])
        write_calls = [c for c in self._calls(calls_path) if "write-book" in c]
        self.assertEqual(len(write_calls), 2)
        self.assertIn("--resume-from", write_calls[0])
        self.assertEqual(write_calls[0][write_calls[0].index("--resume-from") + 1], "1")
        self.assertEqual(write_calls[1][write_calls[1].index("--resume-from") + 1], "3")
        # chapters_result 抗噪音解析（JSON 后还有噪音行也要解出来）
        self.assertEqual(
            state["segments"][1]["chapters_result"],
            [
                {"chapter": 3, "action": "written", "verdict": "Approve"},
                {"chapter": 4, "action": "written", "verdict": "Approve"},
            ],
        )
        # 状态文件随时可解析（原子写）
        self.assertTrue(book_driver.state_path().exists())
        self.assertTrue(book_driver.events_path().exists())

    def test_blocked_exit4_stops_for_human(self) -> None:
        prefix, _, calls_path = self._install_stub(
            self.ws,
            [
                {"cmd": "preflight", "exit": 0, "stdout": []},
                {"cmd": "write-readiness", "exit": 0, "stdout": [_ready_json()]},
                {
                    "cmd": "write-book",
                    "exit": 4,
                    "stdout": [json.dumps({"status": "blocked", "error": "retry_exhausted ch1", "chapters": []})],
                },
            ],
        )
        rc = book_driver.main(_driver_args(chapters=4, segment_size=2, cmd_prefix=prefix))
        self.assertEqual(rc, 4)
        state = book_driver.load_state()
        self.assertEqual(state["status"], "blocked")
        self.assertIn("retry_exhausted", state["last_error"])
        # 默认不自动 --force：只有一次 write-book 调用且不含 --force
        write_calls = [c for c in self._calls(calls_path) if "write-book" in c]
        self.assertEqual(len(write_calls), 1)
        self.assertNotIn("--force", write_calls[0])

    def test_on_blocked_force_once_retries_with_force(self) -> None:
        prefix, _, calls_path = self._install_stub(
            self.ws,
            [
                {"cmd": "preflight", "exit": 0, "stdout": []},
                {"cmd": "write-readiness", "exit": 0, "stdout": [_ready_json()]},
                {"cmd": "write-book", "exit": 4, "stdout": [json.dumps({"status": "blocked", "error": "x"})]},
                {"cmd": "write-book", "exit": 0, "stdout": [_wb_json((1, "written", "Approve"), (2, "written", "Approve"))]},
            ],
        )
        rc = book_driver.main(
            _driver_args(chapters=2, segment_size=2, on_blocked="force-once", cmd_prefix=prefix)
        )
        self.assertEqual(rc, 0)
        write_calls = [c for c in self._calls(calls_path) if "write-book" in c]
        self.assertEqual(len(write_calls), 2)
        self.assertNotIn("--force", write_calls[0])
        self.assertIn("--force", write_calls[1])

    def test_budget_exceeded_exit3_passthrough(self) -> None:
        prefix, _, _ = self._install_stub(
            self.ws,
            [
                {"cmd": "preflight", "exit": 0, "stdout": []},
                {"cmd": "write-readiness", "exit": 0, "stdout": [_ready_json()]},
                {
                    "cmd": "write-book",
                    "exit": 3,
                    "stdout": [json.dumps({"status": "budget_exceeded", "cost_cny": 9.9, "budget_cny": 5.0})],
                },
            ],
        )
        rc = book_driver.main(_driver_args(chapters=2, segment_size=2, budget_cny=5.0, cmd_prefix=prefix))
        self.assertEqual(rc, 3)
        self.assertEqual(book_driver.load_state()["status"], "budget_exceeded")

    def test_driver_level_budget_blocks_before_spending(self) -> None:
        prefix, _, calls_path = self._install_stub(
            self.ws,
            [
                {"cmd": "preflight", "exit": 0, "stdout": []},
                {"cmd": "write-readiness", "exit": 0, "stdout": [_ready_json()]},
            ],
        )
        with patch("src.book_driver.estimate_cost_since", return_value={"cost_cny": 2.0}):
            rc = book_driver.main(_driver_args(chapters=2, segment_size=1, budget_cny=1.0, cmd_prefix=prefix))
        self.assertEqual(rc, 3)
        state = book_driver.load_state()
        self.assertEqual(state["status"], "budget_exceeded")
        # 驱动器级总账在段开始前强拦：没有任何 write-book 调用
        self.assertEqual([c for c in self._calls(calls_path) if "write-book" in c], [])

    def test_remaining_budget_passed_to_write_book(self) -> None:
        prefix, _, calls_path = self._install_stub(
            self.ws,
            [
                {"cmd": "preflight", "exit": 0, "stdout": []},
                {"cmd": "write-readiness", "exit": 0, "stdout": [_ready_json()]},
                {"cmd": "write-book", "exit": 0, "stdout": [_wb_json((1, "written", "Approve"), (2, "written", "Approve"))]},
            ],
        )
        with patch("src.book_driver.estimate_cost_since", return_value={"cost_cny": 1.5}):
            rc = book_driver.main(_driver_args(chapters=2, segment_size=2, budget_cny=10.0, cmd_prefix=prefix))
        self.assertEqual(rc, 0)
        write_call = [c for c in self._calls(calls_path) if "write-book" in c][0]
        budget_value = write_call[write_call.index("--budget-cny") + 1]
        self.assertAlmostEqual(float(budget_value), 8.5, places=3)

    def test_pause_after_segment_then_resume_rewalks_all_segments(self) -> None:
        prefix, queue_path, calls_path = self._install_stub(
            self.ws,
            [
                {"cmd": "preflight", "exit": 0, "stdout": []},
                {"cmd": "write-readiness", "exit": 0, "stdout": [_ready_json()]},
                {"cmd": "write-book", "exit": 0, "stdout": [_wb_json((1, "written", "Approve"))]},
            ],
        )
        rc = book_driver.main(_driver_args(chapters=2, segment_size=1, pause_after_segment=1, cmd_prefix=prefix))
        self.assertEqual(rc, 0)
        state = book_driver.load_state()
        self.assertEqual(state["status"], "paused")
        self.assertEqual(state["attempt"], 1)
        self.assertEqual(len(state["segments"]), 1)

        # resume：段 1 重走（盘面推导 → write-book 返回 skipped_approved 零成本），
        # 段 2 实写。readiness 只在 attempt 1 跑——这里不排 readiness 剧本，
        # 驱动器若误调 readiness 会吃到 stub exit 97 直接失败。
        queue_path.write_text(
            json.dumps(
                [
                    {"cmd": "preflight", "exit": 0, "stdout": []},
                    {"cmd": "write-book", "exit": 0, "stdout": [_wb_json((1, "skipped_approved", "Approve"))]},
                    {"cmd": "write-book", "exit": 0, "stdout": [_wb_json((2, "written", "Approve"))]},
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        rc = book_driver.main(_driver_args(action="resume", cmd_prefix=None))
        self.assertEqual(rc, 0)
        state = book_driver.load_state()
        self.assertEqual(state["status"], "succeeded")
        self.assertEqual(state["attempt"], 2)
        self.assertEqual(
            state["segments"][0]["chapters_result"],
            [{"chapter": 1, "action": "skipped_approved", "verdict": "Approve"}],
        )
        # pause_after_segment 在 resume 时默认清零，不会在段 1 再暂停
        self.assertEqual(state["params"]["pause_after_segment"], 0)
        readiness_calls = [c for c in self._calls(calls_path) if "write-readiness" in c]
        self.assertEqual(len(readiness_calls), 1)

    def test_step_timeout_terminates_child_and_pauses(self) -> None:
        state = {
            "run_id": "t",
            "attempt": 1,
            "step_seq": 1,
            "params": {"cmd_prefix": [sys.executable, "-c", "import time; time.sleep(20)"]},
        }
        started = time.monotonic()
        result = book_driver._run_step(state, "sleepy", ["preflight"], timeout_minutes=1 / 60)
        elapsed = time.monotonic() - started
        self.assertTrue(result.timed_out)
        self.assertLess(elapsed, 15.0)

    def test_refuses_second_driver_when_pid_alive(self) -> None:
        book_driver.driver_dir().mkdir(parents=True, exist_ok=True)
        write_json(book_driver.pid_path(), {"pid": os.getpid(), "pgid": os.getpgid(0), "run_id": "x"})
        rc = book_driver.main(_driver_args())
        self.assertEqual(rc, 2)

    def test_real_model_requires_confirm_flag(self) -> None:
        with patch.dict(os.environ, {"OPENAI_MODEL": "gpt-5.5-high"}, clear=False):
            rc = book_driver.main(_driver_args())
        self.assertEqual(rc, 64)

    def test_resume_without_state_errors(self) -> None:
        rc = book_driver.main(_driver_args(action="resume"))
        self.assertEqual(rc, 2)

    def test_resume_workspace_mismatch_errors(self) -> None:
        book_driver.driver_dir().mkdir(parents=True, exist_ok=True)
        write_json(book_driver.state_path(), {"run_id": "x", "book": "some_other_book", "params": {}})
        rc = book_driver.main(_driver_args(action="resume"))
        self.assertEqual(rc, 2)

    def test_driver_crash_lands_failed_terminal_state(self) -> None:
        prefix, _, _ = self._install_stub(
            self.ws,
            [{"cmd": "preflight", "exit": 0, "stdout": []}],
        )
        def _boom(state):
            raise RuntimeError("orchestrator bug")

        with patch("src.book_driver._run_steps", side_effect=_boom):
            rc = book_driver.main(_driver_args(cmd_prefix=prefix))
        self.assertEqual(rc, 1)
        state = book_driver.load_state()
        self.assertEqual(state["status"], "failed")
        self.assertIn("orchestrator bug", state["last_error"])

    def test_status_reports_lost_when_pid_gone(self) -> None:
        book_driver.driver_dir().mkdir(parents=True, exist_ok=True)
        write_json(
            book_driver.state_path(),
            {"run_id": "x", "book": paths.workspace_name(), "params": {}, "status": "running", "segments": []},
        )
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = book_driver.cmd_status(_driver_args(action="status", json=True))
        self.assertEqual(rc, 0)
        payload = json.loads(buf.getvalue().strip().splitlines()[-1])
        self.assertEqual(payload["status"], "lost")

    def test_stop_marks_running_state_stopped_when_driver_dead(self) -> None:
        book_driver.driver_dir().mkdir(parents=True, exist_ok=True)
        write_json(
            book_driver.state_path(),
            {"run_id": "x", "book": paths.workspace_name(), "params": {}, "status": "running", "segments": []},
        )
        rc = book_driver.cmd_stop(_driver_args(action="stop"))
        self.assertEqual(rc, 0)
        self.assertEqual(book_driver.load_state()["status"], "stopped")

    def test_stop_sends_sigterm_to_live_driver(self) -> None:
        book_driver.driver_dir().mkdir(parents=True, exist_ok=True)
        write_json(book_driver.pid_path(), {"pid": 424242, "pgid": 424242, "run_id": "x"})
        sent: list = []
        with patch("src.book_driver._pid_alive", side_effect=[True, False, False]), patch(
            "src.book_driver._send_signal", side_effect=lambda pid, sig: sent.append((pid, sig))
        ):
            rc = book_driver.cmd_stop(_driver_args(action="stop"))
        self.assertEqual(rc, 0)
        self.assertEqual(sent, [(424242, signal.SIGTERM)])


class MockWriterCharsHookTests(unittest.TestCase):
    """iter 052 mock-only hook：MOCK_WRITER_CHARS（不设 = 旧行为逐字节不变）。"""

    def test_unset_keeps_legacy_short_draft(self) -> None:
        client = LLMClient("write")
        text = client._mock_text([{"role": "user", "content": "请续写本章"}])
        self.assertIn("雨停在凌晨", text)
        self.assertLess(len(text), 200)

    def test_set_returns_long_draft_for_write_task(self) -> None:
        with patch.dict(os.environ, {"MOCK_WRITER_CHARS": "4000"}, clear=False):
            client = LLMClient("write")
            text = client._mock_text([{"role": "user", "content": "请续写本章"}])
        self.assertGreaterEqual(len(text), 4000)

    def test_set_does_not_affect_other_tasks(self) -> None:
        with patch.dict(os.environ, {"MOCK_WRITER_CHARS": "4000"}, clear=False):
            client = LLMClient("review")
            text = client._mock_text([{"role": "user", "content": "请审查本章"}])
        payload = json.loads(text)
        self.assertEqual(payload["verdict"], "Approve")


class DriverE2ETests(_WorkspaceMixin, unittest.TestCase):
    """mock 真管道断点续跑 E2E（慢测试，~2 分钟）。

    覆盖：preflight → debate → ensure-plan → readiness → 分段 write-book，
    pause → WRITER_FORCE_FAIL 注入 resume（ch1 零重写跳过 + ch2 失败）→
    清除注入 resume（succeeded）。这是 30 章实跑前的全链 mock 预演。
    """

    def _cli(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "main.py", "--book", self.ws.name, *args],
            cwd=str(ROOT),
            env=self.env,
            capture_output=True,
            text=True,
            timeout=300,
        )

    def setUp(self) -> None:
        self._preserve_signals()
        self.ws = self._make_workspace("unit_driver_e2e_")
        self.env = {
            **os.environ,
            "OPENAI_MODEL": "mock",
            "WORKSPACE_NAME": self.ws.name,
            "MOCK_WRITER_CHARS": "4000",
        }
        self.env.pop("WRITER_FORCE_FAIL", None)
        hook = patch.dict(os.environ, {"MOCK_WRITER_CHARS": "4000"}, clear=False)
        hook.start()
        self.addCleanup(hook.stop)

        raw_dir = self.ws / "小说txt"
        raw_dir.mkdir(parents=True)
        lines = []
        for i in range(1, 6):
            lines.append(f"第{'一二三四五'[i - 1]}章 试炼之{'一二三四五'[i - 1]}")
            for j in range(30):
                lines.append(
                    f"主角林川在旧城第{j + 1}条街遇到了麻烦。他沿着石板路走过，雨水顺着屋檐滴落，远处的钟楼敲了三下。"
                )
            lines.append("")
        (raw_dir / "test_novel.txt").write_text("\n".join(lines), encoding="utf-8")

        for step in (
            ["normalize", "--lang", "zh"],
            ["split", "--lang", "zh"],
            ["extract", "--limit", "2", "--force"],
            ["compress"],
            ["bootstrap-personas"],
            ["apply-bootstrap", "--name", "personas", "--confirm"],
        ):
            proc = self._cli(*step)
            self.assertEqual(proc.returncode, 0, f"{step} failed: {proc.stdout[-800:]}\n{proc.stderr[-800:]}")

    def test_checkpoint_resume_full_chain(self) -> None:
        # 第一跑：debate + plan + ch1，段 1 后暂停
        rc = book_driver.main(
            _driver_args(
                chapters=2,
                segment_size=1,
                plan_target=2,
                skip_debate=False,
                pause_after_segment=1,
            )
        )
        self.assertEqual(rc, 0)
        state = book_driver.load_state()
        self.assertEqual(state["status"], "paused")
        self.assertEqual(
            state["segments"][0]["chapters_result"],
            [{"chapter": 1, "action": "written", "verdict": "Approve"}],
        )
        draft1 = self.ws / "outputs" / "drafts" / "chapter_01.md"
        self.assertTrue(draft1.exists())
        sha_before = read_json(self.ws / "outputs" / "drafts" / "chapter_01.meta.json", {}).get("draft_sha256")
        self.assertTrue(sha_before)

        # 第二跑：注入 WRITER_FORCE_FAIL → ch1 必须 skipped_approved 零成本，ch2 失败
        with patch.dict(os.environ, {"WRITER_FORCE_FAIL": "1"}, clear=False):
            rc = book_driver.main(_driver_args(action="resume"))
        self.assertEqual(rc, 1)
        state = book_driver.load_state()
        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["attempt"], 2)
        seg1 = state["segments"][0]
        self.assertEqual(
            seg1["chapters_result"],
            [{"chapter": 1, "action": "skipped_approved", "verdict": "Approve"}],
        )
        self.assertEqual(seg1["cost_cny"], 0.0)  # 零重复花费（llm_calls 无新增）
        sha_after = read_json(self.ws / "outputs" / "drafts" / "chapter_01.meta.json", {}).get("draft_sha256")
        self.assertEqual(sha_before, sha_after)  # 零重写：draft 指纹不变

        # 第三跑：清除注入 → ch2 补齐 → succeeded
        os.environ.pop("WRITER_FORCE_FAIL", None)
        rc = book_driver.main(_driver_args(action="resume"))
        self.assertEqual(rc, 0)
        state = book_driver.load_state()
        self.assertEqual(state["status"], "succeeded")
        self.assertEqual(state["attempt"], 3)
        self.assertEqual(
            state["segments"][1]["chapters_result"],
            [{"chapter": 2, "action": "written", "verdict": "Approve"}],
        )
        # 终局审计面：state/events 可解析，report 正常退出
        self.assertTrue(book_driver.events_path().exists())
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(book_driver.cmd_report(_driver_args(action="report", json=True)), 0)
        report = json.loads(buf.getvalue().strip().splitlines()[-1])
        self.assertEqual(report["status"], "succeeded")
        self.assertEqual(len(report["segments"]), 2)


if __name__ == "__main__":
    unittest.main()
