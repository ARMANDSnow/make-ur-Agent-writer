"""iter 058: src/web/background.py —— 幂等后台启动 + 就绪探测 + 优雅停止。

测试分两类：
* **纯逻辑 / 全 mock**（parse_base_url / resolve_python / 启动路径 / 降级 /
  stop_backend）—— 不碰真 socket，沙箱也能跑。
* **真 server**（probe_ready / is_our_backend / 幂等复用 / 不抢占）—— 起一个
  轻量 ThreadingHTTPServer，禁 bind 的沙箱用 SOCKET_BIND_BLOCKED 跳过
  （同 tests/test_web_server.py 的做法）。

全程 **不真起** ``main.py web`` 子进程（慢且会拉续写重依赖）：起子进程的路径
一律 mock ``subprocess.Popen``。
"""

from __future__ import annotations

import socket
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests._socket_skip import SOCKET_BIND_BLOCKED

from src.web import background
from src.web.background import BackendHandle, ensure_backend_running, parse_base_url, stop_backend
from src.web.server import WebHandler


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_listen(port: int, timeout: float = 2.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)


class ParseBaseUrlTests(unittest.TestCase):
    def test_loopback_with_port(self) -> None:
        self.assertEqual(parse_base_url("http://127.0.0.1:8765"), ("127.0.0.1", 8765, True))

    def test_default_port_when_omitted(self) -> None:
        self.assertEqual(parse_base_url("http://127.0.0.1"), ("127.0.0.1", 8765, True))

    def test_localhost_is_loopback(self) -> None:
        self.assertEqual(parse_base_url("http://localhost:9000"), ("localhost", 9000, True))

    def test_remote_host_not_loopback(self) -> None:
        host, port, is_loopback = parse_base_url("http://10.0.0.5:8765")
        self.assertEqual((host, port), ("10.0.0.5", 8765))
        self.assertFalse(is_loopback)

    def test_bare_host_port_without_scheme(self) -> None:
        self.assertEqual(parse_base_url("127.0.0.1:8765"), ("127.0.0.1", 8765, True))

    def test_blank_falls_back_to_loopback(self) -> None:
        self.assertEqual(parse_base_url(""), ("127.0.0.1", 8765, True))


class ResolvePythonTests(unittest.TestCase):
    def test_prefers_repo_venv_when_present(self) -> None:
        with patch.object(Path, "exists", return_value=True):
            py = background.resolve_python(Path("/fake/repo"))
        self.assertEqual(py, str(Path("/fake/repo/.venv/bin/python")))

    def test_falls_back_to_sys_executable(self) -> None:
        with patch.object(Path, "exists", return_value=False):
            py = background.resolve_python(Path("/fake/repo"))
        self.assertEqual(py, sys.executable)


class EnsureStartPathTests(unittest.TestCase):
    """端口空闲 → 起子进程 的各分支，全 mock，不真起进程。"""

    @patch("src.web.background.subprocess.Popen")
    @patch("src.web.background.probe_ready")
    def test_starts_subprocess_when_port_free(self, mock_probe: MagicMock, mock_popen: MagicMock) -> None:
        mock_probe.side_effect = [False, True]  # 端口空 → 起进程后就绪
        fake_proc = MagicMock()
        fake_proc.poll.return_value = None  # 进程活着
        mock_popen.return_value = fake_proc

        handle = ensure_backend_running("127.0.0.1", 8765, wait_s=5.0, poll_s=0.01)

        self.assertTrue(handle.started_by_us)
        self.assertIs(handle.proc, fake_proc)
        self.assertEqual(handle.reason, "")
        cmd = mock_popen.call_args.args[0]
        self.assertTrue(cmd[1].endswith("main.py"))
        self.assertEqual(cmd[2:], ["web", "--host", "127.0.0.1", "--port", "8765"])
        self.assertTrue(mock_popen.call_args.kwargs.get("start_new_session"))
        self.assertEqual(mock_popen.call_args.kwargs.get("cwd"), str(background._REPO_ROOT))

    @patch("src.web.background.subprocess.Popen")
    @patch("src.web.background.probe_ready")
    def test_custom_port_passed_through(self, mock_probe: MagicMock, mock_popen: MagicMock) -> None:
        mock_probe.side_effect = [False, True]
        fake_proc = MagicMock()
        fake_proc.poll.return_value = None
        mock_popen.return_value = fake_proc

        ensure_backend_running("127.0.0.1", 9999, wait_s=5.0, poll_s=0.01)

        self.assertEqual(mock_popen.call_args.args[0][2:], ["web", "--host", "127.0.0.1", "--port", "9999"])

    @patch("src.web.background.subprocess.Popen")
    @patch("src.web.background.probe_ready")
    def test_immediate_exit_degrades(self, mock_probe: MagicMock, mock_popen: MagicMock) -> None:
        mock_probe.return_value = False
        fake_proc = MagicMock()
        fake_proc.poll.return_value = 1  # 秒退
        mock_popen.return_value = fake_proc

        handle = ensure_backend_running(wait_s=5.0, poll_s=0.01)

        self.assertFalse(handle.started_by_us)
        self.assertIsNone(handle.proc)
        self.assertIn("立即退出", handle.reason)

    @patch("src.web.background._terminate")
    @patch("src.web.background.subprocess.Popen")
    @patch("src.web.background.probe_ready")
    def test_timeout_degrades_and_terminates(
        self, mock_probe: MagicMock, mock_popen: MagicMock, mock_term: MagicMock
    ) -> None:
        mock_probe.return_value = False  # 永不就绪
        fake_proc = MagicMock()
        fake_proc.poll.return_value = None  # 活着但不就绪
        mock_popen.return_value = fake_proc

        handle = ensure_backend_running(wait_s=0.05, poll_s=0.01)

        self.assertFalse(handle.started_by_us)
        self.assertIn("未就绪", handle.reason)
        mock_term.assert_called_once_with(fake_proc)

    @patch("src.web.background.subprocess.Popen", side_effect=OSError("boom"))
    @patch("src.web.background.probe_ready", return_value=False)
    def test_popen_error_degrades(self, _mock_probe: MagicMock, _mock_popen: MagicMock) -> None:
        handle = ensure_backend_running(wait_s=5.0, poll_s=0.01)
        self.assertFalse(handle.started_by_us)
        self.assertIn("启动续写后端失败", handle.reason)

    @patch("src.web.background.subprocess.Popen")
    @patch("src.web.background.probe_ready")
    def test_token_injected_into_subprocess_env(self, mock_probe: MagicMock, mock_popen: MagicMock) -> None:
        mock_probe.side_effect = [False, True]
        fake_proc = MagicMock()
        fake_proc.poll.return_value = None
        mock_popen.return_value = fake_proc

        ensure_backend_running("127.0.0.1", 8765, token="s3cret", wait_s=5.0, poll_s=0.01)

        env = mock_popen.call_args.kwargs.get("env")
        self.assertIsNotNone(env)
        self.assertEqual(env["NOVEL_API_TOKEN"], "s3cret")

    @patch("src.web.background.subprocess.Popen")
    @patch("src.web.background.probe_ready")
    def test_no_token_inherits_parent_env(self, mock_probe: MagicMock, mock_popen: MagicMock) -> None:
        mock_probe.side_effect = [False, True]
        fake_proc = MagicMock()
        fake_proc.poll.return_value = None
        mock_popen.return_value = fake_proc

        ensure_backend_running("127.0.0.1", 8765, wait_s=5.0, poll_s=0.01)

        self.assertIsNone(mock_popen.call_args.kwargs.get("env"))  # env=None → 继承父进程

    @patch("src.web.background._terminate")
    @patch("src.web.background.subprocess.Popen")
    @patch("src.web.background.probe_ready")
    def test_zero_wait_still_probes_once(
        self, mock_probe: MagicMock, mock_popen: MagicMock, mock_term: MagicMock
    ) -> None:
        # wait_s=0 也要至少探一次：开头 probe(False)=端口空，循环里探到 True → 成功，不 churn
        mock_probe.side_effect = [False, True]
        fake_proc = MagicMock()
        fake_proc.poll.return_value = None
        mock_popen.return_value = fake_proc

        handle = ensure_backend_running(wait_s=0.0, poll_s=0.01)

        self.assertTrue(handle.started_by_us)
        mock_term.assert_not_called()


class StopBackendTests(unittest.TestCase):
    @patch("src.web.background._terminate")
    def test_terminates_only_started_by_us(self, mock_term: MagicMock) -> None:
        proc = MagicMock()
        stop_backend(BackendHandle("127.0.0.1", 8765, started_by_us=True, proc=proc))
        mock_term.assert_called_once_with(proc)

    @patch("src.web.background._terminate")
    def test_noop_for_reused_backend(self, mock_term: MagicMock) -> None:
        stop_backend(BackendHandle("127.0.0.1", 8765, started_by_us=False, proc=None))
        mock_term.assert_not_called()

    @patch("src.web.background._terminate")
    def test_noop_for_none(self, mock_term: MagicMock) -> None:
        stop_backend(None)
        mock_term.assert_not_called()


@unittest.skipIf(SOCKET_BIND_BLOCKED, "sandbox: socket.bind blocked")
class EmptyPortProbeTests(unittest.TestCase):
    def test_probe_ready_false_for_empty_port(self) -> None:
        port = _free_port()  # 拿到后立即释放，无人监听
        self.assertFalse(background.probe_ready("127.0.0.1", port, timeout=0.3))


@unittest.skipIf(SOCKET_BIND_BLOCKED, "sandbox: socket.bind blocked")
class OurRunningServerTests(unittest.TestCase):
    """端口上跑着真正的续写 WebHandler —— 应被识别并复用，不另起进程。"""

    def setUp(self) -> None:
        self.port = _free_port()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", self.port), WebHandler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        _wait_listen(self.port)

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2.0)

    def test_probe_ready_true(self) -> None:
        self.assertTrue(background.probe_ready("127.0.0.1", self.port))

    def test_is_our_backend_true(self) -> None:
        self.assertTrue(background.is_our_backend("127.0.0.1", self.port))

    @patch("src.web.background.subprocess.Popen")
    def test_ensure_reuses_without_spawning(self, mock_popen: MagicMock) -> None:
        handle = ensure_backend_running("127.0.0.1", self.port)
        self.assertFalse(handle.started_by_us)
        self.assertIsNone(handle.proc)
        self.assertEqual(handle.reason, "")
        mock_popen.assert_not_called()


class _ForeignHandler(BaseHTTPRequestHandler):
    server_version = "SomeOtherServer/1.0"
    sys_version = ""

    def do_GET(self) -> None:  # noqa: N802 - stdlib naming
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"not us")

    def log_message(self, *args: object) -> None:  # noqa: A003 - silence
        pass


@unittest.skipIf(SOCKET_BIND_BLOCKED, "sandbox: socket.bind blocked")
class ForeignServerTests(unittest.TestCase):
    """端口被 *别的* 程序占用 —— 不抢，降级提示。"""

    def setUp(self) -> None:
        self.port = _free_port()
        self.httpd = ThreadingHTTPServer(("127.0.0.1", self.port), _ForeignHandler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        _wait_listen(self.port)

    def tearDown(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2.0)

    def test_is_our_backend_false(self) -> None:
        self.assertFalse(background.is_our_backend("127.0.0.1", self.port))

    @patch("src.web.background.subprocess.Popen")
    def test_ensure_does_not_hijack_foreign_port(self, mock_popen: MagicMock) -> None:
        handle = ensure_backend_running("127.0.0.1", self.port)
        self.assertFalse(handle.started_by_us)
        self.assertIn("被其他程序占用", handle.reason)
        mock_popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
