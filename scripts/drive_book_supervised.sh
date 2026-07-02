#!/usr/bin/env bash
set -uo pipefail

# iter 076 HIGH#5: crash-auto-restart supervisor for `drive-book`（过夜长跑）。
#
# watchdog（--driver 模式）只负责「发现卡死 → SIGTERM + 写 watchdog_abort.json」；
# 本脚本负责「非终态退出 → 指数退避 → drive-book resume」，上限次数后升级人工。
# driver 以**前台**子进程跑（不 --detach）——wait 拿 exit code 最可靠；要过夜请用
# nohup 包本脚本（见用法），driver 的 setsid/caffeinate 逻辑不适用于前台路径，
# 故本脚本自带 caffeinate。
#
# 决策表（exit code + driver_state.json）：
#   exit 0 + status=succeeded            → 完工，退出 0
#   exit 0 + status=paused
#       paused_reason=step_timeout       → 自动 resume（计一次重启）
#       paused_reason=pause_after_segment→ 人工意图，尊重退出 0
#   exit 0 + status=stopped
#       有**本轮内新鲜**的 watchdog_abort.json → watchdog 杀的 → resume（计一次）
#       没有                              → 人工 stop，尊重退出 0
#   exit 3 (budget) / 4 (blocked) / 64 (确认闸) / 2 (参数拒绝) → 终态透传，等人工
#   其它（1 / 信号 / 崩溃）               → 指数退避后 resume
#
# 重启预算：SUPERVISE_MAX_RESTARTS（默认 5）；退避 = SUPERVISE_BACKOFF_BASE
# （默认 1s）× 2^(第几次-1)，封顶 60s；单轮存活 ≥ SUPERVISE_RESET_SECONDS
# （默认 600s）后计数归零（跑出进展不该被累计惩罚）。超限退出 75 并响亮报错。
# 另有 SUPERVISE_MAX_ROUNDS（默认 48）**不随归零重置**的总轮次硬顶——防「每轮
# 都活过 10 分钟才崩」的慢崩配合计数归零变成整夜无界烧钱环（审查 B M1）。
# 真模型且未传 --budget-cny 时启动即响亮 WARN。
#
# 人工干预约定（审查 B L8/L9）：要人工停链路，先停 supervisor（Ctrl-C/kill）再
# `drive-book stop`——反过来在心跳已停滞的窄窗口里，watchdog 标记可能把人工 stop
# 误判成卡死重启。每个 book 同时只允许一个 supervisor（logs/driver/supervise.pid 互斥）。
#
# 用法：
#   bash scripts/drive_book_supervised.sh --book longzu -- --chapters 20 --tier mid ...
#   # 过夜：
#   nohup bash scripts/drive_book_supervised.sh --book longzu -- --chapters 20 \
#     >> workspaces/longzu/logs/supervise.log 2>&1 &
#   # 配套 watchdog（另一终端/进程）：
#   bash scripts/watchdog.sh --book longzu --driver
#
# --resume-first：接管既有 run（跳过 start，第一轮就 resume）。
# 真模型确认闸与 drive_book.sh 同款：CONFIRM_REAL_MODEL_SMOKE=可以跑了 或
# --confirm-real-smoke（映射为 --confirm-real-run 传给 start/resume）。
#
# 测试钩子：SUPERVISE_CMD 覆盖被监督命令（默认 "$PYTHON main.py [--book X] drive-book"），
# SUPERVISE_BACKOFF_BASE=0 让单测零等待。

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# shellcheck source=with_proxy.sh
source "$ROOT/scripts/with_proxy.sh"

BOOK="${WORKSPACE_NAME:-${BOOK:-}}"
CONFIRM_REAL_MODEL_SMOKE="${CONFIRM_REAL_MODEL_SMOKE:-}"
RESUME_FIRST=0
START_ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --confirm-real-smoke) CONFIRM_REAL_MODEL_SMOKE="可以跑了"; shift;;
    --book) BOOK="$2"; shift 2;;
    --book=*) BOOK="${1#--book=}"; shift;;
    --resume-first) RESUME_FIRST=1; shift;;
    --) shift; START_ARGS=("$@"); break;;
    *) START_ARGS+=("$1"); shift;;
  esac
done
if [ -z "$BOOK" ]; then
  echo "[supervise] --book required (or WORKSPACE_NAME)" >&2
  exit 2
fi
export WORKSPACE_NAME="$BOOK"

for arg in ${START_ARGS[@]+"${START_ARGS[@]}"}; do
  if [ "$arg" = "--detach" ]; then
    echo "[supervise] --detach is incompatible: the supervisor must wait on a foreground driver" >&2
    exit 2
  fi
done

# Real-model gate: supervisor start/resume both spend money.
MODEL="${OPENAI_MODEL:-}"
CONFIRM_ARGS=()
if [ "$MODEL" != "mock" ]; then
  if [ "$CONFIRM_REAL_MODEL_SMOKE" != "可以跑了" ]; then
    echo "Refusing to supervise a real model without CONFIRM_REAL_MODEL_SMOKE=可以跑了 or --confirm-real-smoke" >&2
    exit 64
  fi
  CONFIRM_ARGS+=("--confirm-real-run")
fi

export PYTHONPYCACHEPREFIX="$ROOT/.pycache"
PYTHON="$ROOT/.venv/bin/python3"
[ -x "$PYTHON" ] || PYTHON="python3"

DRIVER_DIR="$ROOT/workspaces/$BOOK/logs/driver"
STATE_PATH="$DRIVER_DIR/driver_state.json"
ABORT_MARKER="$DRIVER_DIR/watchdog_abort.json"
SUPERVISE_PID_FILE="$DRIVER_DIR/supervise.pid"

MAX_RESTARTS="${SUPERVISE_MAX_RESTARTS:-5}"
MAX_ROUNDS="${SUPERVISE_MAX_ROUNDS:-48}"
BACKOFF_BASE="${SUPERVISE_BACKOFF_BASE:-1}"
RESET_SECONDS="${SUPERVISE_RESET_SECONDS:-600}"

# 审查 B L9：supervisor 互斥——同 book 双 supervisor 会竞争 resume/标记消费。
mkdir -p "$DRIVER_DIR"
if [ -f "$SUPERVISE_PID_FILE" ]; then
  old_pid=$(cat "$SUPERVISE_PID_FILE" 2>/dev/null || echo "")
  if [ -n "$old_pid" ] && kill -0 "$old_pid" 2>/dev/null; then
    echo "[supervise] another supervisor is running for $BOOK (pid=$old_pid); refusing" >&2
    exit 2
  fi
fi
echo $$ > "$SUPERVISE_PID_FILE"
trap 'rm -f "$SUPERVISE_PID_FILE"' EXIT

# 审查 B M1 配套：真模型不带预算上限时响亮提醒（不拒启——capstone 允许无上限，但要知情）。
if [ "$MODEL" != "mock" ]; then
  case " ${START_ARGS[*]:-} " in
    *" --budget-cny "*) : ;;
    *) echo "[supervise] WARN: real model without --budget-cny — only SUPERVISE_MAX_ROUNDS=$MAX_ROUNDS caps total spend" >&2 ;;
  esac
fi

# 防睡眠：driver 的 caffeinate 只在 detach 路径起，前台路径由 supervisor 自己包。
if command -v caffeinate >/dev/null 2>&1; then
  caffeinate -i -w $$ >/dev/null 2>&1 &
fi

# Portable mtime（与 watchdog.sh 同款探测）。
if stat -f %m "$0" >/dev/null 2>&1; then
  STAT_FMT='stat -f %m'
else
  STAT_FMT='stat -c %Y'
fi

state_field() {  # $1=top-level key → stdout value（缺失/坏 JSON → 空）
  "$PYTHON" - "$STATE_PATH" "$1" <<'PY'
import json, sys
try:
    data = json.load(open(sys.argv[1], encoding="utf-8"))
    val = data.get(sys.argv[2])
    sys.stdout.write("" if val is None else str(val))
except Exception:
    sys.stdout.write("")
PY
}

run_driver() {  # $1=action(start|resume)，其余透传参数
  local action="$1"; shift
  if [ -n "${SUPERVISE_CMD:-}" ]; then
    # 测试钩子：整条命令替换（stub 自己照剧本写 state + exit）。
    # shellcheck disable=SC2086
    $SUPERVISE_CMD "$action" "$@"
  else
    "$PYTHON" main.py --book "$BOOK" drive-book "$action" "$@"
  fi
}

echo "[supervise] book=$BOOK max_restarts=$MAX_RESTARTS max_rounds=$MAX_ROUNDS backoff_base=${BACKOFF_BASE}s reset_after=${RESET_SECONDS}s" >&2

restarts=0
round=0
action="start"
[ "$RESUME_FIRST" = "1" ] && action="resume"

while true; do
  round=$((round + 1))
  # 审查 B M1：总轮次硬顶不随「存活够久→计数归零」重置——慢崩（每轮 >RESET_SECONDS
  # 才 crash）不再能绕过上限整夜烧钱。
  if [ "$round" -gt "$MAX_ROUNDS" ]; then
    echo "" >&2
    echo "================================================================" >&2
    echo "[supervise] GIVING UP: total rounds $round > SUPERVISE_MAX_ROUNDS=$MAX_ROUNDS" >&2
    echo "[supervise] inspect $DRIVER_DIR then run: python3 main.py --book $BOOK drive-book resume" >&2
    echo "================================================================" >&2
    exit 75
  fi
  round_start=$(date +%s)
  echo "[supervise] $(date '+%H:%M:%S') round=$round action=$action (restarts so far: $restarts)" >&2
  if [ "$action" = "start" ]; then
    run_driver start ${START_ARGS[@]+"${START_ARGS[@]}"} ${CONFIRM_ARGS[@]+"${CONFIRM_ARGS[@]}"}
  else
    run_driver resume ${CONFIRM_ARGS[@]+"${CONFIRM_ARGS[@]}"}
  fi
  rc=$?
  round_elapsed=$(( $(date +%s) - round_start ))
  status="$(state_field status)"
  echo "[supervise] round=$round exit=$rc status=${status:-unknown} elapsed=${round_elapsed}s" >&2

  # 单轮存活够久 = 有实际进展，重启计数归零（避免整夜多次独立小故障累加到上限）。
  if [ "$round_elapsed" -ge "$RESET_SECONDS" ] && [ "$restarts" -gt 0 ]; then
    echo "[supervise] round lived ${round_elapsed}s >= ${RESET_SECONDS}s — restart counter reset" >&2
    restarts=0
  fi

  restart_reason=""
  case "$rc" in
    0)
      case "$status" in
        succeeded)
          echo "[supervise] driver succeeded — all done" >&2
          exit 0
          ;;
        paused)
          paused_reason="$(state_field paused_reason)"
          if [ "$paused_reason" = "pause_after_segment" ]; then
            echo "[supervise] paused by --pause-after-segment (human intent) — respecting it" >&2
            exit 0
          fi
          restart_reason="paused:${paused_reason:-unknown}"
          ;;
        stopped)
          marker_fresh=0
          if [ -f "$ABORT_MARKER" ]; then
            marker_mtime=$($STAT_FMT "$ABORT_MARKER" 2>/dev/null || echo 0)
            [ "$marker_mtime" -ge "$round_start" ] && marker_fresh=1
          fi
          if [ "$marker_fresh" = "1" ]; then
            mv "$ABORT_MARKER" "$ABORT_MARKER.consumed" 2>/dev/null || true
            restart_reason="watchdog_abort"
          else
            echo "[supervise] driver stopped without a fresh watchdog marker (human stop) — respecting it" >&2
            exit 0
          fi
          ;;
        *)
          # exit 0 但 state 读不出/未知：按 crash 保守重启。
          restart_reason="unknown_state:${status:-unreadable}"
          ;;
      esac
      ;;
    3|4|64|2)
      # budget / blocked / 确认闸 / 参数拒绝：都需要人工决策，透传退出码。
      echo "[supervise] terminal exit $rc (status=${status:-?}) — human decision needed" >&2
      exit "$rc"
      ;;
    *)
      restart_reason="crash_exit_$rc"
      ;;
  esac

  restarts=$((restarts + 1))
  if [ "$restarts" -gt "$MAX_RESTARTS" ]; then
    echo "" >&2
    echo "================================================================" >&2
    echo "[supervise] GIVING UP: $restarts restarts > max $MAX_RESTARTS (last reason: $restart_reason)" >&2
    echo "[supervise] inspect $DRIVER_DIR then run: python3 main.py --book $BOOK drive-book resume" >&2
    echo "================================================================" >&2
    exit 75
  fi
  backoff=$(( BACKOFF_BASE * (1 << (restarts - 1)) ))
  [ "$backoff" -gt 60 ] && backoff=60
  echo "[supervise] restart #$restarts (reason: $restart_reason) — resume in ${backoff}s" >&2
  sleep "$backoff"
  action="resume"
done
