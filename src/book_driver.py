"""Long-run book driver (iter 052a).

smoke051 的实录教训：2 小时级真模型流程不能寄生在 agent 会话的后台任务里
——会话 context 压缩/重启会静默回收进程组（无信号无 traceback）。本模块把
当时的临时 double-fork 解法正式化为一个可断点续跑、可审计的驱动器。

设计要点（iteration_052_PLAN.md）：

* **子进程编排公开 CLI**，不 in-process import ``run_write_book``：单 step
  崩溃不毁驱动器状态；公开 CLI 即生产契约；每段子进程重新加载代码（F7
  分段对照依赖此性质）；可对子进程实施 wall-clock 超时。
* **章节进度永远从盘面推导**（write-book 自己跳 ``skipped_approved``），
  ``driver_state.json`` 只存启动参数与审计字段——不存"写到第几章"，
  防第二真源（与 iter050 指纹唯一真源同一哲学）。
* **预算双层**：驱动器级总账（启动记 ``llm_calls.jsonl`` 行偏移，每段前
  ``estimate_cost_since`` 对照）+ write-book 段内上限（传剩余额度）。
  ``budget_cny <= 0`` 与 book_runner 同语义 = 无上限。
* **与 web_jobs 绕开不复用**：jobs 是 server 进程内 daemon 线程，生命周期
  绑死 server；驱动器不写 ``web_jobs.jsonl``，两者只共享底层幂等 gate。
* **--detach** 用 double-fork + ``os.setsid()``（ppid=1 归 launchd）脱离会话，
  detach 路径起 ``caffeinate -i -w <pid>`` 防机器睡眠（setsid 治会话回收、
  治不了 sleep）。macOS 无 setsid 命令，nohup 不换 session 照死。

状态文件落在 ``workspaces/<book>/logs/driver/``（workspaces gitignore 内）：

* ``driver_state.json``  —— 原子写（utils.write_json），参数 + 审计
* ``driver_events.jsonl`` —— append-only 事件账本
* ``driver.pid``          —— 互斥（防双驱动器）
* ``step_<run>_<seq>_<name>.log`` —— 每个子进程 step 的原始输出

子进程退出码契约（main.py write-book）：0=succeeded / 3=budget_exceeded /
4=blocked / 1=failed；结果 JSON 在 stdout 末行（前面有 print 噪音，解析必须
从尾部找第一个可解析 JSON 行）。
"""

from __future__ import annotations

import json
import os
import shlex
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import paths
from .config import ROOT
from .cost_estimator import estimate_cost_since
from .utils import append_jsonl, ensure_dir, read_json, write_json

DEFAULT_STEP_TIMEOUT_MINUTES = 180
# preflight 是纯本地计算，单独给一个小超时，免得卡死也要等 3 小时。
PREFLIGHT_TIMEOUT_MINUTES = 10
_KILL_GRACE_SECONDS = 30.0
_REAL_RUN_REFUSAL_EXIT = 64  # 与 real_smoke.sh 确认闸同款退出码

TERMINAL_EXIT_CODES = {
    "succeeded": 0,
    "paused": 0,   # 主动暂停（--pause-after-segment / step 超时）是预期路径
    "stopped": 0,  # stop 命令是预期路径
    "blocked": 4,
    "budget_exceeded": 3,
    "failed": 1,
}

# 当前正在运行的子进程（信号 handler 用），以及 stop 请求标志。
_CURRENT_CHILD: Optional[subprocess.Popen] = None
_STOP_REQUESTED = False


# ---- paths -------------------------------------------------------------------


def driver_dir() -> Path:
    return paths.logs_dir() / "driver"


def state_path() -> Path:
    return driver_dir() / "driver_state.json"


def events_path() -> Path:
    return driver_dir() / "driver_events.jsonl"


def pid_path() -> Path:
    return driver_dir() / "driver.pid"


# ---- small helpers -----------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(int(pid), 0)
    except (ProcessLookupError, ValueError, TypeError):
        return False
    except PermissionError:
        return True
    return True


def load_state() -> Optional[Dict[str, Any]]:
    return read_json(state_path(), None)


def _save_state(state: Dict[str, Any]) -> None:
    state["heartbeat_at"] = _now()
    ensure_dir(driver_dir())
    write_json(state_path(), state)


def _emit(state: Optional[Dict[str, Any]], event: str, **payload: Any) -> None:
    record: Dict[str, Any] = {"ts": _now(), "event": event}
    if state is not None:
        record["run_id"] = state.get("run_id")
        record["attempt"] = state.get("attempt")
    record.update(payload)
    ensure_dir(driver_dir())
    append_jsonl(events_path(), record)
    # detach 模式下 stdout 已重定向到 driver log，这行就是人读的进度。
    compact = {k: v for k, v in payload.items() if k not in ("cmd",)}
    print(f"[drive-book] {event} {json.dumps(compact, ensure_ascii=False, default=str)}")


def parse_last_json_line(text: str) -> Optional[Dict[str, Any]]:
    """从尾部找第一个可解析的 JSON object 行。

    write-book 等 CLI 在结果 JSON 前会 print 进度噪音（暗礁实录），所以
    只认"整行是一个 JSON object"的行，从尾部往前扫。
    """

    for line in reversed(text.splitlines()):
        line = line.strip()
        if not line or not (line.startswith("{") and line.endswith("}")):
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data
    return None


def plan_segments(chapters: int, resume_from: int, segment_size: int) -> List[Tuple[int, int]]:
    """把 [resume_from, resume_from+chapters-1] 切成 [(first, last)] 段表。"""

    size = max(1, int(segment_size))
    first = max(1, int(resume_from))
    last_total = first + max(0, int(chapters)) - 1
    out: List[Tuple[int, int]] = []
    cur = first
    while cur <= last_total:
        out.append((cur, min(cur + size - 1, last_total)))
        cur += size
    return out


def _llm_log_line_count() -> int:
    path = paths.llm_calls_log_path()
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8", errors="replace") as fh:
        return sum(1 for _ in fh)


def _spent_cny(state: Dict[str, Any]) -> float:
    offset = int(state.get("llm_log_offset_at_start") or 0)
    try:
        return float(estimate_cost_since(offset).get("cost_cny", 0.0))
    except Exception:  # llm log 不可读时宁可报 0 也不要让驱动器崩
        return 0.0


def _any_draft_exists() -> bool:
    drafts = paths.drafts_dir()
    if not drafts.exists():
        return False
    return any(drafts.glob("chapter_*.md"))


# ---- subprocess step runner ---------------------------------------------------


class StepResult:
    def __init__(self, exit_code: int, payload: Optional[Dict[str, Any]], timed_out: bool, log_path: Path):
        self.exit_code = exit_code
        self.payload = payload
        self.timed_out = timed_out
        self.log_path = log_path


def _build_cmd(params: Dict[str, Any], step_args: List[str]) -> List[str]:
    prefix = params.get("cmd_prefix")
    if prefix:
        cmd = list(prefix)
    else:
        cmd = [sys.executable, str(ROOT / "main.py")]
        book = params.get("book")
        if book:
            cmd += ["--book", str(book)]
    return cmd + list(step_args)


def _terminate_child(child: subprocess.Popen) -> None:
    """SIGTERM 子进程组，宽限后 SIGKILL。子进程以 start_new_session 启动，
    自成进程组，killpg 不会误伤驱动器本体。"""

    try:
        os.killpg(child.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    deadline = time.monotonic() + _KILL_GRACE_SECONDS
    while time.monotonic() < deadline:
        if child.poll() is not None:
            return
        time.sleep(0.2)
    try:
        os.killpg(child.pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _run_step(
    state: Dict[str, Any],
    step_name: str,
    step_args: List[str],
    *,
    timeout_minutes: int,
) -> StepResult:
    global _CURRENT_CHILD
    cmd = _build_cmd(state["params"], step_args)
    seq = int(state.get("step_seq") or 1)
    state["step_seq"] = seq + 1
    log_path = driver_dir() / f"step_{state['run_id']}_{seq:03d}_{step_name}.log"
    state["phase"] = step_name
    _save_state(state)
    _emit(state, "step_start", step=step_name, args=step_args, log=str(log_path))

    ensure_dir(driver_dir())
    timed_out = False
    with log_path.open("w", encoding="utf-8") as fh:
        child = subprocess.Popen(
            cmd,
            stdout=fh,
            stderr=subprocess.STDOUT,
            cwd=str(ROOT),
            start_new_session=True,
        )
        _CURRENT_CHILD = child
        state["child_pid"] = child.pid
        _save_state(state)
        try:
            # float minutes so tests can use sub-minute timeouts.
            child.wait(timeout=max(1, int(float(timeout_minutes) * 60)))
        except subprocess.TimeoutExpired:
            timed_out = True
            _emit(state, "step_timeout", step=step_name, timeout_minutes=timeout_minutes)
            _terminate_child(child)
            child.wait()
        finally:
            _CURRENT_CHILD = None
    state["child_pid"] = None

    try:
        text = log_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    payload = parse_last_json_line(text)
    _emit(
        state,
        "step_end",
        step=step_name,
        exit_code=child.returncode,
        timed_out=timed_out,
        payload_status=(payload or {}).get("status"),
    )
    return StepResult(child.returncode, payload, timed_out, log_path)


# ---- the step graph -----------------------------------------------------------


def _segment_chapter_rows(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for item in payload.get("chapters") or []:
        status = item.get("status") or {}
        rows.append(
            {
                "chapter": item.get("chapter"),
                "action": item.get("action"),
                "verdict": status.get("verdict") if isinstance(status, dict) else None,
            }
        )
    return rows


def _run_steps(state: Dict[str, Any]) -> str:
    params = state["params"]
    timeout = int(params.get("step_timeout_minutes") or DEFAULT_STEP_TIMEOUT_MINUTES)
    chapters = int(params["chapters"])
    resume_from = int(params.get("resume_from") or 1)
    last_chapter = resume_from + chapters - 1
    budget = float(params.get("budget_cny") or 0.0)

    # 1) preflight —— 纯本地，FATAL 即 blocked。
    res = _run_step(state, "preflight", ["preflight"], timeout_minutes=PREFLIGHT_TIMEOUT_MINUTES)
    if _STOP_REQUESTED:
        return "stopped"
    if res.timed_out:
        return "paused"
    if res.exit_code != 0:
        state["last_error"] = "preflight failed (FATAL)"
        return "blocked"

    # 2) debate（可选）—— outline 已存在或 --skip-debate 即跳过；
    #    debate_log 的 done_keys 续跑由 debater 自身保证（iter015）。
    if params.get("skip_debate"):
        _emit(state, "step_skipped", step="debate", reason="skip_debate")
    elif paths.outline_path().exists():
        _emit(state, "step_skipped", step="debate", reason="outline_exists")
    else:
        res = _run_step(state, "debate", ["debate"], timeout_minutes=timeout)
        if _STOP_REQUESTED:
            return "stopped"
        if res.timed_out:
            return "paused"
        if res.exit_code != 0:
            state["last_error"] = "debate failed"
            return "failed"

    # 3) ensure-plan —— guard：plan 缺失/为空才跑，防 resume 重花 planner 钱。
    #    plan 偏短（< plan_target）时仅当盘面还没有任何草稿才允许 --force 重做：
    #    已有章节写出后重生成 plan 会破坏指纹链，这种情况交给 write-book 的
    #    --replan-every 滚动 append（iter024）或人工决断。
    plan_target = min(int(params.get("plan_target") or last_chapter), last_chapter)
    plan_data = read_json(paths.chapter_plan_path(), None) or {}
    plan_len = len(plan_data.get("chapters") or [])
    if plan_len >= plan_target:
        _emit(state, "step_skipped", step="ensure_plan", reason="plan_sufficient", plan_len=plan_len)
    elif plan_len > 0 and _any_draft_exists():
        _emit(
            state,
            "step_skipped",
            step="ensure_plan",
            reason="drafts_exist_no_force_replan",
            plan_len=plan_len,
        )
    else:
        plan_args = ["plan-chapters", "--chapters", str(plan_target), "--force"]
        if params.get("require_start_point"):
            plan_args.append("--require-start-point")
        res = _run_step(state, "ensure_plan", plan_args, timeout_minutes=timeout)
        if _STOP_REQUESTED:
            return "stopped"
        if res.timed_out:
            return "paused"
        if res.exit_code != 0:
            state["last_error"] = "plan-chapters failed"
            return "blocked"

    # 4) readiness gate —— 只在首次 attempt 跑：resume 场景下盘面可能留有
    #    失败章残迹（write-book 的 retry 路径自己能消化），readiness 的
    #    existing_output 检查会误报。write-book 内部仍有同一套 readiness。
    if int(state.get("attempt") or 1) == 1:
        ready_args = [
            "write-readiness",
            "--chapters",
            str(chapters),
            "--resume-from",
            str(resume_from),
            "--replan-every",
            str(int(params.get("replan_every") or 0)),
        ]
        for flag in ("allow_missing_start_point", "allow_missing_plan", "skip_external_review"):
            if params.get(flag):
                ready_args.append("--" + flag.replace("_", "-"))
        res = _run_step(state, "readiness", ready_args, timeout_minutes=PREFLIGHT_TIMEOUT_MINUTES)
        if _STOP_REQUESTED:
            return "stopped"
        if res.timed_out:
            return "paused"
        if res.exit_code == 4:
            state["last_error"] = "; ".join((res.payload or {}).get("blockers") or ["write-readiness blocked"])
            return "blocked"
        if res.exit_code != 0:
            state["last_error"] = "write-readiness failed"
            return "failed"

    # 5) write segments —— 每段都重新走（write-book 对已批章 skipped_approved
    #    天然幂等，零 LLM 成本），进度从盘面推导而非状态文件。
    segments = plan_segments(chapters, resume_from, int(params.get("segment_size") or chapters))
    state["segments_total"] = len(segments)
    state["segments"] = []
    pause_after = int(params.get("pause_after_segment") or 0)

    for idx, (first, last) in enumerate(segments, start=1):
        if _STOP_REQUESTED:
            return "stopped"

        spent = _spent_cny(state)
        state["cost_cny"] = spent
        if budget > 0 and spent >= budget:
            state["last_error"] = f"driver budget exhausted before segment {idx} (spent {spent:.2f} >= {budget:.2f})"
            return "budget_exceeded"
        remaining = max(0.0, budget - spent) if budget > 0 else 0.0

        seg: Dict[str, Any] = {
            "index": idx,
            "chapters": [first, last],
            "status": "running",
            "started_at": _now(),
            "cost_cny_before": round(spent, 4),
        }
        state["segments"].append(seg)

        forced = False
        while True:
            seg_args = [
                "write-book",
                "--chapters",
                str(last - first + 1),
                "--resume-from",
                str(first),
                "--max-retries",
                str(int(params.get("max_retries") or 2)),
                "--replan-every",
                str(int(params.get("replan_every") or 0)),
            ]
            if budget > 0:
                seg_args += ["--budget-cny", f"{remaining:.4f}"]
            if params.get("tier"):
                seg_args += ["--tier", str(params["tier"])]
            for flag in ("allow_missing_start_point", "allow_missing_plan", "skip_external_review"):
                if params.get(flag):
                    seg_args.append("--" + flag.replace("_", "-"))
            if forced:
                seg_args.append("--force")

            res = _run_step(state, f"write_seg{idx}", seg_args, timeout_minutes=timeout)
            payload = res.payload or {}
            seg["exit_code"] = res.exit_code
            seg["chapters_result"] = _segment_chapter_rows(payload)
            seg["cost_cny"] = round(max(0.0, _spent_cny(state) - spent), 4)
            seg["finished_at"] = _now()

            if _STOP_REQUESTED:
                seg["status"] = "stopped"
                _save_state(state)
                return "stopped"
            if res.timed_out:
                seg["status"] = "timeout"
                _save_state(state)
                return "paused"
            if res.exit_code == 0:
                seg["status"] = "succeeded"
                break
            if res.exit_code == 3:
                seg["status"] = "budget_exceeded"
                state["last_error"] = f"write-book budget_exceeded in segment {idx}"
                _save_state(state)
                return "budget_exceeded"
            if res.exit_code == 4:
                # 默认停人审：自动 --force 会掩盖质量回退（反目标）。
                # --on-blocked force-once 是显式逃生门，且只重试一次。
                if params.get("on_blocked") == "force-once" and not forced:
                    forced = True
                    _emit(state, "blocked_force_once", segment=idx)
                    continue
                seg["status"] = "blocked"
                state["last_error"] = str(payload.get("error") or "write-book blocked")
                _save_state(state)
                return "blocked"
            seg["status"] = "failed"
            state["last_error"] = f"write-book exit {res.exit_code} in segment {idx}"
            _save_state(state)
            return "failed"

        _emit(
            state,
            "segment_done",
            segment=idx,
            chapters=[first, last],
            cost_cny=seg["cost_cny"],
            results=seg["chapters_result"],
        )
        _save_state(state)

        if pause_after and idx >= pause_after:
            _emit(state, "paused_after_segment", segment=idx)
            return "paused"

    return "succeeded"


# ---- driver lifecycle ----------------------------------------------------------


def _handle_term(signum: int, frame: Any) -> None:  # pragma: no cover - signal path
    global _STOP_REQUESTED
    _STOP_REQUESTED = True
    child = _CURRENT_CHILD
    if child is not None and child.poll() is None:
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


def run_driver(state: Dict[str, Any]) -> str:
    """前台主循环：写 pid 文件 → 跑 step 图 → 落终态。"""

    signal.signal(signal.SIGTERM, _handle_term)
    signal.signal(signal.SIGINT, _handle_term)
    ensure_dir(driver_dir())
    write_json(
        pid_path(),
        {"pid": os.getpid(), "pgid": os.getpgid(0), "run_id": state["run_id"], "started_at": _now()},
    )
    state["pid"] = os.getpid()
    state["pgid"] = os.getpgid(0)
    state["status"] = "running"
    _save_state(state)
    _emit(state, "driver_start", pid=os.getpid(), params=state["params"])

    try:
        status = _run_steps(state)
    except Exception as exc:  # 编排层自身的 bug 也要落终态，不能留 running 假象
        state["last_error"] = f"driver crashed: {exc!r}"
        status = "failed"

    state["status"] = status
    state["phase"] = "done"
    state["finished_at"] = _now()
    state["cost_cny"] = _spent_cny(state)
    _save_state(state)
    _emit(state, "driver_end", status=status, cost_cny=state["cost_cny"], last_error=state.get("last_error"))
    try:
        pid_path().unlink()
    except OSError:
        pass
    return status


def _detach() -> Optional[int]:
    """double-fork + setsid 脱离会话（smoke051 实测唯一可靠方式）。

    返回值：父进程侧返回中间子进程 pid（调用方打印提示后退出）；
    孙进程侧返回 None（继续执行驱动器主循环，stdio 已重定向）。
    """

    pid = os.fork()
    if pid > 0:
        return pid
    os.setsid()
    pid2 = os.fork()
    if pid2 > 0:
        os._exit(0)
    # 孙进程：stdio 重定向到 driver log；防睡眠。
    ensure_dir(driver_dir())
    log_path = driver_dir() / f"driver_{time.strftime('%Y%m%d_%H%M%S')}.log"
    fd = os.open(str(log_path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    devnull = os.open(os.devnull, os.O_RDONLY)
    os.dup2(devnull, 0)
    os.dup2(fd, 1)
    os.dup2(fd, 2)
    os.close(fd)
    os.close(devnull)
    try:
        # caffeinate -w：驱动器进程退出后自动释放，无需清理。
        subprocess.Popen(
            ["caffeinate", "-i", "-w", str(os.getpid())],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except (FileNotFoundError, OSError):
        pass  # 非 macOS / 无 caffeinate：照常跑，睡眠风险写进 SOP
    return None


# ---- CLI actions ---------------------------------------------------------------


def _build_params(args: Any) -> Dict[str, Any]:
    cmd_prefix = getattr(args, "cmd_prefix", None)
    return {
        "book": paths.workspace_name(),
        "chapters": int(args.chapters),
        "resume_from": int(getattr(args, "resume_from", 1) or 1),
        "segment_size": int(getattr(args, "segment_size", 5) or 5),
        "replan_every": int(getattr(args, "replan_every", 0) or 0),
        "plan_target": int(getattr(args, "plan_target", 0) or 0) or None,
        "budget_cny": float(getattr(args, "budget_cny", None) or 0.0),
        "tier": getattr(args, "tier", None),
        "max_retries": int(getattr(args, "max_retries", 2) or 2),
        "skip_debate": bool(getattr(args, "skip_debate", False)),
        "require_start_point": bool(getattr(args, "require_start_point", False)),
        "allow_missing_start_point": bool(getattr(args, "allow_missing_start_point", False)),
        "allow_missing_plan": bool(getattr(args, "allow_missing_plan", False)),
        "skip_external_review": bool(getattr(args, "skip_external_review", False)),
        "pause_after_segment": int(getattr(args, "pause_after_segment", None) or 0),
        "step_timeout_minutes": int(getattr(args, "step_timeout_minutes", None) or DEFAULT_STEP_TIMEOUT_MINUTES),
        "on_blocked": getattr(args, "on_blocked", "stop") or "stop",
        "cmd_prefix": shlex.split(cmd_prefix) if cmd_prefix else None,
    }


def _refuse_real_run(args: Any) -> bool:
    model = os.environ.get("OPENAI_MODEL", "")
    if model != "mock" and not getattr(args, "confirm_real_run", False):
        print(
            "Refusing to drive a non-mock model without --confirm-real-run "
            f"(OPENAI_MODEL={model!r}). 铁律⑥：真模型实跑必须显式确认。",
            file=sys.stderr,
        )
        return True
    return False


def _another_driver_running() -> Optional[Dict[str, Any]]:
    info = read_json(pid_path(), None)
    if info and _pid_alive(info.get("pid", -1)):
        return info
    return None


def _launch(state: Dict[str, Any], detach: bool) -> int:
    if detach:
        parent_pid = _detach()
        if parent_pid is not None:
            print(
                f"driver detached (run_id={state['run_id']}); "
                f"logs: {driver_dir()} ; 用 drive-book status 查看进度"
            )
            return 0
    status = run_driver(state)
    print(
        json.dumps(
            {
                "status": status,
                "run_id": state["run_id"],
                "attempt": state.get("attempt"),
                "cost_cny": state.get("cost_cny"),
                "last_error": state.get("last_error"),
            },
            ensure_ascii=False,
        )
    )
    return TERMINAL_EXIT_CODES.get(status, 1)


def cmd_start(args: Any) -> int:
    running = _another_driver_running()
    if running:
        print(f"another driver is running (pid={running.get('pid')}); use drive-book stop first", file=sys.stderr)
        return 2
    if _refuse_real_run(args):
        return _REAL_RUN_REFUSAL_EXIT

    params = _build_params(args)
    if not params["plan_target"]:
        params["plan_target"] = min(10, int(params["chapters"]) + int(params["resume_from"]) - 1)
    state: Dict[str, Any] = {
        "run_id": time.strftime("%Y%m%d_%H%M%S"),
        "book": params["book"],
        "params": params,
        "status": "created",
        "phase": "init",
        "attempt": 1,
        "step_seq": 1,
        "segments": [],
        "segments_total": None,
        "llm_log_offset_at_start": _llm_log_line_count(),
        "created_at": _now(),
        "child_pid": None,
        "last_error": None,
    }
    return _launch(state, bool(getattr(args, "detach", False)))


def cmd_resume(args: Any) -> int:
    running = _another_driver_running()
    if running:
        print(f"driver already running (pid={running.get('pid')})", file=sys.stderr)
        return 2
    state = load_state()
    if not state:
        print("no driver state to resume; use drive-book start", file=sys.stderr)
        return 2
    if state.get("book") != paths.workspace_name():
        print(
            f"workspace mismatch: state is for {state.get('book')!r}, current is {paths.workspace_name()!r}",
            file=sys.stderr,
        )
        return 2
    if _refuse_real_run(args):
        return _REAL_RUN_REFUSAL_EXIT

    params = state["params"]
    # resume 可覆盖的参数：明确传了才覆盖；pause_after_segment 默认清零，
    # 否则每次 resume 都会在同一段再暂停一次。
    pause = getattr(args, "pause_after_segment", None)
    params["pause_after_segment"] = int(pause) if pause is not None else 0
    for key, attr in (
        ("step_timeout_minutes", "step_timeout_minutes"),
        ("budget_cny", "budget_cny"),
        ("on_blocked", "on_blocked"),
    ):
        value = getattr(args, attr, None)
        if value is not None:
            params[key] = value
    cmd_prefix = getattr(args, "cmd_prefix", None)
    if cmd_prefix:
        params["cmd_prefix"] = shlex.split(cmd_prefix)

    state["attempt"] = int(state.get("attempt") or 1) + 1
    state["step_seq"] = int(state.get("step_seq") or 1)
    state["last_error"] = None
    state["finished_at"] = None
    _emit(state, "driver_resume", previous_status=state.get("status"))
    return _launch(state, bool(getattr(args, "detach", False)))


def cmd_status(args: Any) -> int:
    state = load_state()
    if not state:
        print("no driver state")
        return 2
    info = read_json(pid_path(), None) or {}
    alive = bool(info) and _pid_alive(info.get("pid", -1))
    display_status = state.get("status")
    if display_status == "running" and not alive:
        # 进程没了但终态没落盘 = 被外力收割（机器重启/SIGKILL）。
        display_status = "lost"
    llm_path = paths.llm_calls_log_path()
    llm_age = round(time.time() - llm_path.stat().st_mtime, 1) if llm_path.exists() else None
    segments = state.get("segments") or []
    done = sum(1 for s in segments if s.get("status") == "succeeded")
    budget = float((state.get("params") or {}).get("budget_cny") or 0.0)
    payload = {
        "run_id": state.get("run_id"),
        "status": display_status,
        "phase": state.get("phase"),
        "attempt": state.get("attempt"),
        "pid": info.get("pid"),
        "pid_alive": alive,
        "heartbeat_at": state.get("heartbeat_at"),
        "llm_log_age_seconds": llm_age,
        "segments_done": done,
        "segments_total": state.get("segments_total"),
        "cost_cny": round(_spent_cny(state), 4),
        "budget_cny": budget,
        "last_error": state.get("last_error"),
    }
    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False))
    else:
        for key, value in payload.items():
            print(f"{key}: {value}")
    return 0


def _send_signal(pid: int, sig: int) -> None:
    """信号发送薄封装：单测可注入（直接 patch 这层，不动全局 os.kill）。"""

    os.kill(int(pid), sig)


def _send_signal_pg(pgid: int, sig: int) -> None:
    os.killpg(int(pgid), sig)


def cmd_stop(args: Any) -> int:
    info = read_json(pid_path(), None)
    state = load_state()
    stopped_something = False
    if info and _pid_alive(info.get("pid", -1)):
        _send_signal(int(info["pid"]), signal.SIGTERM)
        deadline = time.monotonic() + _KILL_GRACE_SECONDS
        while time.monotonic() < deadline and _pid_alive(info["pid"]):
            time.sleep(0.2)
        if _pid_alive(info["pid"]):
            print(f"driver pid {info['pid']} did not exit in {_KILL_GRACE_SECONDS}s; SIGKILL", file=sys.stderr)
            try:
                _send_signal(int(info["pid"]), signal.SIGKILL)
            except ProcessLookupError:
                pass
        stopped_something = True
    # 驱动器若已死，可能留下孤儿子进程组（write-book 自成 session）。
    child_pid = (state or {}).get("child_pid")
    if child_pid and _pid_alive(child_pid):
        try:
            _send_signal_pg(int(child_pid), signal.SIGTERM)
            stopped_something = True
        except ProcessLookupError:
            pass
    state = load_state()  # 驱动器退出时可能已自行落了终态，重读再判断
    if state and state.get("status") == "running":
        state["status"] = "stopped"
        state["last_error"] = state.get("last_error") or "stopped externally"
        _save_state(state)
        append_jsonl(events_path(), {"ts": _now(), "event": "stopped_externally", "run_id": state.get("run_id")})
    print("stopped" if stopped_something else "nothing to stop")
    return 0


def cmd_report(args: Any) -> int:
    state = load_state()
    if not state:
        print("no driver state")
        return 2
    segments = state.get("segments") or []
    rows: List[Dict[str, Any]] = []
    for seg in segments:
        for item in seg.get("chapters_result") or []:
            rows.append({**item, "segment": seg.get("index"), "segment_status": seg.get("status")})
    payload = {
        "run_id": state.get("run_id"),
        "status": state.get("status"),
        "attempt": state.get("attempt"),
        "cost_cny": round(_spent_cny(state), 4),
        "budget_cny": float((state.get("params") or {}).get("budget_cny") or 0.0),
        "segments": segments,
        "chapters": rows,
    }
    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False))
        return 0
    print(f"run_id: {payload['run_id']}  status: {payload['status']}  attempt: {payload['attempt']}")
    print(f"cost_cny: {payload['cost_cny']}  budget_cny: {payload['budget_cny']}")
    for seg in segments:
        chapters = seg.get("chapters") or ["?", "?"]
        print(
            f"segment {seg.get('index')}: ch{chapters[0]}-{chapters[1]} "
            f"{seg.get('status')} cost={seg.get('cost_cny')}"
        )
        for item in seg.get("chapters_result") or []:
            print(f"  ch{item.get('chapter')}: {item.get('action')} verdict={item.get('verdict')}")
    return 0


def main(args: Any) -> int:
    action = getattr(args, "action", None)
    if action == "start":
        return cmd_start(args)
    if action == "resume":
        return cmd_resume(args)
    if action == "status":
        return cmd_status(args)
    if action == "stop":
        return cmd_stop(args)
    if action == "report":
        return cmd_report(args)
    print(f"unknown drive-book action: {action!r}", file=sys.stderr)
    return 2
