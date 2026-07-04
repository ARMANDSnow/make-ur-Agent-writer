"""iter078 P1-7: workspace 级写锁 —— Web/CLI 双写者互斥。

背景（六方审查 P1）：Web job 的防重只有进程内的 ``_WORKSPACE_JOBS`` 内存
dict，CLI driver 的防重只有 ``driver.pid``，两套机制互不可见；同一
workspace 可以同时被 Web 线程（in-process 调 ``run_write_book``）和 CLI
子进程写 ``drafts/``，静默交叉覆盖章节产物。

为什么用 ``fcntl.flock`` 而不是 ``O_EXCL`` 守卫文件：flock 由内核按打开
文件描述计，**持有进程死亡（含 SIGKILL）时自动释放**——不存在 stale lock
需要清理/判活的问题；O_EXCL 文件在进程崩溃后会永久残留，需要另建一套
「锁文件里的 pid 还活着吗」判别式（driver.pid 那套的教训）。代价是 flock
只在同一台机器上有效——本项目 workspace 就是本机目录，够用。

锁语义：
- 粒度 = workspace（锁文件在 workspace root 下；legacy 无 workspace 态
  退到 ``ROOT/outputs/write.lock``），整个 write run 持有。
- 非阻塞独占：拿不到立即 raise :class:`WorkspaceLocked`（活着的 holder
  就是真双写者，等待没有意义，fail-closed）。
- 同进程两线程各自 ``open()`` 同一路径也互斥（flock 按 open file
  description 计），所以 Web-vs-Web 双保险、Web-vs-CLI 靠它拦。
- ``write.lock.holder.json`` 只是给「被拒的那一方」看的诊断信息
  （pid/来源/时间/argv），锁语义完全在 flock 上，holder 文件写失败或
  删失败都不影响互斥。
"""

from __future__ import annotations

import fcntl
import json
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, Optional

from . import paths

LOCK_FILENAME = "write.lock"


class WorkspaceLocked(RuntimeError):
    """另一个写者正持有本 workspace 的写锁。

    ``run_write_book`` 会把它包成 ``BookRunBlocked``（exit 4 家族、driver
    blocked 终态、Web job 失败路径全部沿用既有契约，零新退出码）。
    """


def lock_path() -> Path:
    """当前 workspace 的写锁文件路径。

    workspace 态放 workspace root 下；legacy 态 ``workspace_root()`` 返回
    repo ROOT，锁退到 ``ROOT/outputs/write.lock``（outputs/ 已 gitignore，
    与 legacy drafts 同一棵产物树）。
    """
    root = paths.workspace_root()
    if paths.workspace_name():
        return root / LOCK_FILENAME
    return root / "outputs" / LOCK_FILENAME


def _holder_path(lock: Path) -> Path:
    return lock.with_name(lock.name + ".holder.json")


def _read_holder(lock: Path) -> Optional[Dict[str, Any]]:
    try:
        data = json.loads(_holder_path(lock).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def _write_holder(lock: Path, source: str) -> None:
    # 原子 tmp+replace（同 utils.write_json 模式）；失败不抛——锁语义在
    # flock，holder 只是诊断信息。
    holder = {
        "pid": os.getpid(),
        "source": source,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "argv": " ".join(sys.argv[:8])[:400],
        "workspace": paths.workspace_name() or "legacy",
    }
    target = _holder_path(lock)
    tmp = target.with_name(target.name + f".tmp.{os.getpid()}")
    try:
        tmp.write_text(json.dumps(holder, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, target)
    except OSError:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass


def _locked_message(lock: Path) -> str:
    holder = _read_holder(lock) or {}
    who = (
        f"pid={holder.get('pid', '?')} source={holder.get('source', '?')} "
        f"since={holder.get('started_at', '?')} argv={holder.get('argv', '?')}"
        if holder
        else "holder 信息不可读（对方可能刚启动或 holder 文件被清理）"
    )
    return (
        f"workspace_locked: 另一个写者正持有写锁 {lock}（{who}）。"
        "flock 随持有进程退出自动释放——若确认对方是该停的，请先停掉对方"
        "（Web job 取消 / drive-book stop / kill 该 pid），不要删除锁文件。"
    )


@contextmanager
def acquire_write_lock(*, source: str) -> Iterator[None]:
    """非阻塞获取本 workspace 的独占写锁；持有期 = with 块。

    :param source: 写入 holder json 的来源标签（``cli-write-book`` /
        ``web-job`` / ``cli-write`` …），只用于被拒方的报错诊断。
    :raises WorkspaceLocked: 锁已被其他写者持有。
    """
    lock = lock_path()
    lock.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock), os.O_RDWR | os.O_CREAT, 0o644)
    acquired = False
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except BlockingIOError as exc:
            raise WorkspaceLocked(_locked_message(lock)) from exc
        # 其它 OSError（文件系统不支持 flock 等环境错误）原样上抛——响亮失败
        # 好过静默放行第二写者。
        _write_holder(lock, source)
        yield
    finally:
        if acquired:
            try:
                _holder_path(lock).unlink(missing_ok=True)
            except OSError:
                pass
        try:
            os.close(fd)  # close 即释放 flock
        except OSError:
            pass
