"""iter 058: 幂等地在后台启动续写 web 后端，供 Aeloon 插件 ``activate`` 调用。

**stdlib-only / SDK-free / import-light**：本模块只用标准库（socket /
subprocess / urllib / pathlib），**不** import litellm 等续写重依赖——那些只在
被 ``subprocess.Popen`` 起来的子进程里、用续写自己的 ``.venv`` 解释器才加载。
于是：

* 插件运行在 Aeloon 解释器里 ``import src.web.background`` 不会触发续写重依赖，
  也不破坏 "plugin.py 是唯一 import Aeloon SDK 的模块" 的格局；
* 整个公开面（``ensure_backend_running`` / ``stop_backend`` / …）可在
  ``OPENAI_MODEL=mock``、无 Aeloon SDK 的环境下单测。

设计背景见 ``integrations/__init__.py``：续写后端被刻意做成一个 **独立运行的
进程**（``python3 main.py web``），而不是 in-process import——pipeline 同步且
分钟级，inline 跑会卡住 host 的事件循环；而 "点小说续写跳网页" 的 deep-link
本就要求该 HTTP 服务在跑。本模块负责把这个进程随 Aeloon 一起、幂等地拉起来。
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple
from urllib.parse import urlsplit

# 仓库根 = .../src/web/background.py 上溯三级（与 src/config.py:11 的 ROOT 同值）。
# 故意不 ``from ..config import ROOT``——config 的 import 链可能拉重依赖，而本
# 模块要保持 import-light。
_REPO_ROOT = Path(__file__).resolve().parents[2]

# 与 src/web/server.py:100 的 _LOOPBACK_HOSTS 对齐：仅这些 host 才自动起本地后端。
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

# src/web/server.py:20 的 server_version 前缀，用于识别 "占着端口的是不是我们"。
_SERVER_FINGERPRINT = "AgentContinuationWebUI"

_DEFAULT_PORT = 8765
# 比 book_driver 的 30s 宽限短得多：deactivate 总超时才 30s，留余量。
_KILL_GRACE_SECONDS = 5.0


@dataclass
class BackendHandle:
    """``ensure_backend_running`` 的结果。

    * ``started_by_us=True`` —— 本次 ``Popen`` 起的进程，``deactivate`` 时该终止它。
    * ``started_by_us=False`` —— 复用了已在跑的服务，或降级未启动；``deactivate``
      不应去动它（``proc`` 为 None）。
    * ``reason`` 非空 —— 降级/未启动的原因，可供 ``/novel`` 友好提示。
    """

    host: str
    port: int
    started_by_us: bool
    proc: Optional[subprocess.Popen] = None
    reason: str = ""


def parse_base_url(base_url: str) -> Tuple[str, int, bool]:
    """``"http://127.0.0.1:8765"`` → ``("127.0.0.1", 8765, True)``。

    缺省端口 8765；裸 ``host:port`` 也接受；无法解析时回退 loopback 默认值。
    第三个返回值标记 host 是否 loopback——仅 loopback 才适合自动起 *本地* 后端。
    """
    raw = (base_url or "").strip()
    try:
        parts = urlsplit(raw if "://" in raw else f"http://{raw}")
        host = parts.hostname or "127.0.0.1"
        port = parts.port or _DEFAULT_PORT
    except (ValueError, AttributeError):
        host, port = "127.0.0.1", _DEFAULT_PORT
    return host, port, host in _LOOPBACK_HOSTS


def resolve_python(repo_root: Path = _REPO_ROOT) -> str:
    """挑选启动 ``main.py web`` 的 Python 解释器。

    优先用续写仓库自带的 ``.venv``（装了 litellm 等续写重依赖），因为 Aeloon
    进程的 ``sys.executable`` 可能是另一个环境、跑 ``main.py`` 会 ImportError。
    找不到 ``.venv`` 时回退当前解释器。
    """
    for cand in (
        repo_root / ".venv" / "bin" / "python",          # POSIX
        repo_root / ".venv" / "Scripts" / "python.exe",  # Windows
    ):
        if cand.exists():
            return str(cand)
    return sys.executable


def _url(host: str, port: int, path: str) -> str:
    # IPv6 字面量（如 ::1）在 URL 里要用方括号包裹。
    host_part = f"[{host}]" if ":" in host and not host.startswith("[") else host
    return f"http://{host_part}:{port}{path}"


def _server_header(host: str, port: int, timeout: float) -> Optional[str]:
    """GET ``/`` 取 ``Server`` 响应头；连不上返回 None。

    ``/`` 是非 ``/api/`` 路由，永不被 NOVEL_API_TOKEN 鉴权门拦（auth.py:40），
    所以即便设了 token 也能拿到响应头。HTTPError（含 401/404）也算 "连上了"。
    """
    try:
        with urllib.request.urlopen(_url(host, port, "/"), timeout=timeout) as resp:
            return resp.headers.get("Server", "")
    except urllib.error.HTTPError as exc:
        return exc.headers.get("Server", "") if exc.headers else ""
    except (urllib.error.URLError, OSError):
        return None


def probe_ready(host: str, port: int, timeout: float = 1.0) -> bool:
    """服务是否可达。先探 TCP 端口（连接被拒 = 未起），端口开着再 GET ``/``。

    任何 HTTP 响应（含 401）都算就绪——不依赖 2xx，避免鉴权门导致误判 "没起"。
    """
    try:
        with socket.create_connection((host, port), timeout=timeout):
            pass
    except OSError:
        return False
    return _server_header(host, port, timeout) is not None


def is_our_backend(host: str, port: int, timeout: float = 1.0) -> bool:
    """端口被占时，确认占用者是不是我们的续写服务（看 ``Server`` 头指纹）。"""
    header = _server_header(host, port, timeout)
    return header is not None and _SERVER_FINGERPRINT in header


def ensure_backend_running(
    host: str = "127.0.0.1",
    port: int = _DEFAULT_PORT,
    *,
    token: Optional[str] = None,
    python: Optional[str] = None,
    wait_s: float = 20.0,
    poll_s: float = 0.25,
) -> BackendHandle:
    """幂等地确保续写后端在 ``host:port`` 上跑着。

    **绝不抛异常**——任何失败都填 ``reason`` 返回降级 handle，让调用方
    （插件 activate）保持 best-effort、不拖垮 Aeloon 启动。

    ``token`` 非空时注入子进程的 ``NOVEL_API_TOKEN``，使自动起的后端带上鉴权
    门，与 NovelClient 所发 bearer 对齐（否则会"client 发 token、server 不校验"）。

    流程：
      1. 已就绪 → 是我们的服务则复用；是别人占端口则降级、不强抢。
      2. 端口空闲 → 用 ``resolve_python()`` 起 ``main.py web`` 子进程。
      3. 轮询至 ``wait_s``；子进程秒退（依赖缺失/端口竞争）或超时 → 降级。
    """
    # 1) 已有服务在跑？
    if probe_ready(host, port):
        if is_our_backend(host, port):
            return BackendHandle(host, port, started_by_us=False)
        return BackendHandle(
            host, port, started_by_us=False,
            reason=f"端口 {port} 已被其他程序占用，未自动启动续写后端",
        )

    # 2) 端口空闲 → 起子进程。整段（main.py 检查 / resolve_python / Popen）都包进
    #    try：Path.exists() / resolve_python 理论上也可能抛 OSError，本函数须"绝不抛"。
    main_py = _REPO_ROOT / "main.py"
    # token 非空 → 注入子进程 NOVEL_API_TOKEN，让自动起的后端带上鉴权门（serve 的
    # load_dotenv 默认不覆盖已存在的 env var，故此值优先于 .env）。
    env = None
    if token:
        env = os.environ.copy()
        env["NOVEL_API_TOKEN"] = token
    try:
        if not main_py.exists():
            return BackendHandle(
                host, port, started_by_us=False,
                reason=f"未找到 {main_py}，无法自动启动续写后端",
            )
        cmd = [python or resolve_python(), str(main_py), "web", "--host", host, "--port", str(port)]
        proc = subprocess.Popen(
            cmd,
            cwd=str(_REPO_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,  # 自成进程组，便于 killpg 干净终止整组
            env=env,
        )
    except (OSError, ValueError) as exc:
        return BackendHandle(
            host, port, started_by_us=False,
            reason=f"启动续写后端失败：{type(exc).__name__}: {exc}",
        )

    # 3) 轮询就绪。用 while True 保证至少探测一次——即便 wait_s 被配成 0/极小值，也不
    #    会起了进程一次没探就 _terminate（否则每次 activate 都 churn 一个秒杀的子进程）。
    deadline = time.monotonic() + max(wait_s, poll_s)
    while True:
        rc = proc.poll()
        if rc is not None:
            return BackendHandle(
                host, port, started_by_us=False,
                reason=f"续写后端启动后立即退出（exit={rc}），可能缺依赖或端口竞争",
            )
        if probe_ready(host, port, timeout=0.5):
            return BackendHandle(host, port, started_by_us=True, proc=proc)
        if time.monotonic() >= deadline:
            break
        time.sleep(poll_s)

    # 4) 超时 → 杀掉半死进程降级
    _terminate(proc)
    return BackendHandle(
        host, port, started_by_us=False,
        reason=f"续写后端 {wait_s:.0f}s 内未就绪，已放弃自动启动",
    )


def stop_backend(handle: Optional[BackendHandle]) -> None:
    """只终止 *我们起的* 子进程；复用的/降级的不动。供插件 ``deactivate`` 调用。"""
    if handle is None or not handle.started_by_us or handle.proc is None:
        return
    _terminate(handle.proc)


def _terminate(proc: subprocess.Popen, grace: float = _KILL_GRACE_SECONDS) -> None:
    """SIGTERM 进程组 → 宽限 → SIGKILL（同 src/book_driver.py:216-232）。

    子进程以 ``start_new_session`` 启动、自成进程组，``killpg`` 不会误伤插件
    宿主。Windows 无 ``killpg``，回退到 ``Popen`` 自带的 terminate()/kill()。
    """
    if proc.poll() is not None:
        return
    _kill_group(proc, "term")
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            return
        time.sleep(0.2)
    _kill_group(proc, "kill")


def _kill_group(proc: subprocess.Popen, how: str) -> None:
    killpg = getattr(os, "killpg", None)
    try:
        if killpg is not None:
            killpg(proc.pid, signal.SIGKILL if how == "kill" else signal.SIGTERM)
        elif how == "kill":
            proc.kill()
        else:
            proc.terminate()
    except (ProcessLookupError, OSError):
        pass
