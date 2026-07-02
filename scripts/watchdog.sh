#!/usr/bin/env bash
# Iter 027 P3: watchdog for capstone real-model runs.
# iter 076 HIGH#4: --driver mode watches the drive-book heartbeat file
# (workspaces/<book>/logs/driver/driver_heartbeat.json, written every ~30s by
# src/book_driver.py) instead of llm_calls.jsonl mtime — post-processing hangs
# and pure-local steps produce no LLM calls, so mtime alone under-detects a
# wedged driver. Before SIGTERM it writes watchdog_abort.json so the
# drive_book_supervised.sh wrapper can tell "watchdog killed it" (restartable)
# from a human `drive-book stop` (respect it). Driver mode does NOT exit after
# an abort: it escalates TERM→30s→KILL, disarms until a fresh heartbeat shows
# up (the supervisor restarted the driver), then keeps watching — so the
# second half of the night is still covered (review B M2). It also refuses to
# kill a pid whose command line isn't a drive-book process (pid reuse, L7).
#
# Legacy mode (default, no --driver): watches the mtime of
# workspaces/<book>/logs/llm_calls.jsonl as a heartbeat. If the file hasn't
# been written to within --warn-after seconds we print a stderr WARN; if it
# crosses --abort-after we send SIGTERM to --pid so write_book.sh can save
# partial progress before dying.
#
# Default behavior: warn-only. Kill is opt-in via --pid so a fat-
# fingered run on a healthy long-running pipeline doesn't murder it.
# In --driver mode the pid falls back to logs/driver/driver.pid when --pid
# is not given (re-read every loop — the supervisor may restart the driver).
#
# Usage:
#   bash scripts/watchdog.sh --book longzu [--warn-after 300] [--abort-after 360] [--pid <PID>]
#   bash scripts/watchdog.sh --book longzu --driver   # heartbeat mode (warn 120 / abort 600)
#
# Example (3-terminal capstone setup):
#   # terminal A — kick off the writer
#   bash scripts/write_book.sh --book longzu 30 --replan-every 5 --budget-cny 60 &
#   WRITER=$!
#   # terminal B — watchdog
#   bash scripts/watchdog.sh --book longzu --pid $WRITER
#   # terminal C — dashboard
#   /usr/bin/python3 main.py web --port 8765

set -u

BOOK=""
WARN_AFTER=""
ABORT_AFTER=""
PID=""
INTERVAL=30
DRIVER_MODE=0

while [ $# -gt 0 ]; do
  case "$1" in
    --book) BOOK="$2"; shift 2 ;;
    --book=*) BOOK="${1#--book=}"; shift ;;
    --warn-after) WARN_AFTER="$2"; shift 2 ;;
    --warn-after=*) WARN_AFTER="${1#--warn-after=}"; shift ;;
    --abort-after) ABORT_AFTER="$2"; shift 2 ;;
    --abort-after=*) ABORT_AFTER="${1#--abort-after=}"; shift ;;
    --pid) PID="$2"; shift 2 ;;
    --pid=*) PID="${1#--pid=}"; shift ;;
    --interval) INTERVAL="$2"; shift 2 ;;
    --interval=*) INTERVAL="${1#--interval=}"; shift ;;
    --driver) DRIVER_MODE=1; shift ;;
    -h|--help)
      sed -n '2,36p' "$0"
      exit 0
      ;;
    *)
      echo "[watchdog] unknown arg: $1" >&2
      exit 1
      ;;
  esac
done

if [ -z "$BOOK" ]; then
  echo "[watchdog] --book required" >&2
  exit 1
fi

# Mode defaults (only when not explicitly passed): legacy 300/360 preserved;
# driver heartbeat ticks every ~30s so 600s of silence = a hard-wedged driver.
if [ "$DRIVER_MODE" = "1" ]; then
  WARN_AFTER="${WARN_AFTER:-120}"
  ABORT_AFTER="${ABORT_AFTER:-600}"
else
  WARN_AFTER="${WARN_AFTER:-300}"
  ABORT_AFTER="${ABORT_AFTER:-360}"
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Iter 027: watchdog itself does not call LLMs, but we source the proxy
# adapter so the stderr "[with_proxy] mode=…" line lands in the same log
# as the writer — makes post-mortem easy when something does go wrong.
# shellcheck source=with_proxy.sh
source "$ROOT/scripts/with_proxy.sh"
LOG_PATH="$ROOT/workspaces/$BOOK/logs/llm_calls.jsonl"
DRIVER_DIR="$ROOT/workspaces/$BOOK/logs/driver"
HEARTBEAT_PATH="$DRIVER_DIR/driver_heartbeat.json"
ABORT_MARKER="$DRIVER_DIR/watchdog_abort.json"
DRIVER_PID_FILE="$DRIVER_DIR/driver.pid"

# Portable mtime: stat -f %m on macOS, stat -c %Y on linux.
if stat -f %m "$LOG_PATH" >/dev/null 2>&1 || stat -f %m "$0" >/dev/null 2>&1; then
  STAT_FMT='stat -f %m'
else
  STAT_FMT='stat -c %Y'
fi

# Extract an integer JSON field without jq: `json_int_field <file> <key>`.
json_int_field() {
  grep -o "\"$2\"[[:space:]]*:[[:space:]]*[0-9][0-9]*" "$1" 2>/dev/null \
    | head -1 | grep -o '[0-9][0-9]*$'
}

# iter 076: atomic abort marker so the supervisor can distinguish a watchdog
# kill (restart with backoff) from a human stop (respect it).
write_abort_marker() {
  local age="$1" reason="$2" now
  now=$(date +%s)
  mkdir -p "$DRIVER_DIR" 2>/dev/null || true
  printf '{"ts": "%s", "epoch": %s, "age_seconds": %s, "reason": "%s", "book": "%s"}\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$now" "$age" "$reason" "$BOOK" \
    > "$ABORT_MARKER.tmp" && mv "$ABORT_MARKER.tmp" "$ABORT_MARKER"
}

# 审查 B L7：pid 复用误杀保险——driver 模式 kill 前校验目标命令行确实是本项目
# 的 drive-book/main.py 进程（driver.pid 残留 + OS pid 复用时跳过 kill）。
pid_is_driver() {
  ps -p "$1" -o command= 2>/dev/null | grep -q -e "drive-book" -e "main\.py"
}

MODE_LABEL="llm-mtime"
[ "$DRIVER_MODE" = "1" ] && MODE_LABEL="driver-heartbeat"
echo "[watchdog] book=$BOOK mode=$MODE_LABEL log=$LOG_PATH" >&2
[ "$DRIVER_MODE" = "1" ] && echo "[watchdog] heartbeat=$HEARTBEAT_PATH abort_marker=$ABORT_MARKER" >&2
echo "[watchdog] warn_after=${WARN_AFTER}s abort_after=${ABORT_AFTER}s interval=${INTERVAL}s pid=${PID:-(auto/warn-only)}" >&2

warned=0
# 审查 B M2：driver 模式 abort 后不退出——supervisor 会重启 driver，watchdog 必须
# 留场继续看护后半夜。abort_armed 防同一次停滞反复开火：开火后缴械，见到新鲜
# 心跳（age < WARN_AFTER，即 driver 已重启在跳）才重新上膛。
abort_armed=1
while true; do
  now=$(date +%s)
  age=""
  age_src=""

  if [ "$DRIVER_MODE" = "1" ] && [ -f "$HEARTBEAT_PATH" ]; then
    hb_epoch=$(json_int_field "$HEARTBEAT_PATH" epoch)
    if [ -n "$hb_epoch" ]; then
      age=$((now - hb_epoch))
      age_src="heartbeat"
    fi
  fi
  if [ -z "$age" ]; then
    # Fallback (legacy mode, or heartbeat file missing/corrupt): llm log mtime.
    if [ ! -f "$LOG_PATH" ]; then
      echo "[watchdog] $(date '+%H:%M:%S') log file missing — pipeline may not have started yet" >&2
      sleep "$INTERVAL"
      continue
    fi
    mtime=$($STAT_FMT "$LOG_PATH" 2>/dev/null || echo 0)
    age=$((now - mtime))
    age_src="llm_mtime"
  fi

  if [ "$age" -ge "$ABORT_AFTER" ]; then
    if [ "$DRIVER_MODE" = "1" ] && [ "$abort_armed" = "0" ]; then
      # 同一次停滞已开过火，等 supervisor 重启出新鲜心跳再重新上膛。
      sleep "$INTERVAL"
      continue
    fi
    kill_pid="$PID"
    if [ -z "$kill_pid" ] && [ "$DRIVER_MODE" = "1" ] && [ -f "$DRIVER_PID_FILE" ]; then
      # Re-read every loop: the supervisor may have restarted the driver.
      kill_pid=$(json_int_field "$DRIVER_PID_FILE" pid)
    fi
    if [ -n "$kill_pid" ]; then
      if kill -0 "$kill_pid" 2>/dev/null; then
        if [ "$DRIVER_MODE" = "1" ] && ! pid_is_driver "$kill_pid"; then
          echo "[watchdog] pid $kill_pid is not a drive-book process (pid reuse?) — skip kill" >&2
          write_abort_marker "$age" "${age_src}_stale_pid_mismatch"
          abort_armed=0
          sleep "$INTERVAL"; continue
        fi
        echo "" >&2
        echo "================================================================" >&2
        echo "[watchdog] ABORT: no $age_src signal for ${age}s (>= ${ABORT_AFTER}s)" >&2
        echo "[watchdog] sending SIGTERM to PID $kill_pid" >&2
        echo "================================================================" >&2
        [ "$DRIVER_MODE" = "1" ] && write_abort_marker "$age" "${age_src}_stale"
        kill -TERM "$kill_pid"
        if [ "$DRIVER_MODE" = "1" ]; then
          # 审查 B M2：TERM → 30s 宽限 → 仍活则 SIGKILL（真硬卡时 TERM handler
          # 不会被执行，与 drive-book stop 的升级姿势对齐），然后**留场继续看护**
          # ——supervisor 重启 driver 后的后半夜仍有人盯。
          grace_deadline=$(( $(date +%s) + 30 ))
          while [ "$(date +%s)" -lt "$grace_deadline" ] && kill -0 "$kill_pid" 2>/dev/null; do
            sleep 1
          done
          if kill -0 "$kill_pid" 2>/dev/null; then
            echo "[watchdog] pid $kill_pid survived SIGTERM grace; sending SIGKILL" >&2
            kill -KILL "$kill_pid" 2>/dev/null || true
          fi
          abort_armed=0
          sleep "$INTERVAL"; continue
        fi
        exit 2
      else
        echo "[watchdog] PID $kill_pid already gone" >&2
        [ "$DRIVER_MODE" = "1" ] && write_abort_marker "$age" "${age_src}_stale_pid_gone"
        if [ "$DRIVER_MODE" = "1" ]; then
          abort_armed=0
          sleep "$INTERVAL"; continue
        fi
        exit 0
      fi
    else
      echo "[watchdog] ABORT threshold hit (${age}s via $age_src) but no pid known; would have killed" >&2
      [ "$DRIVER_MODE" = "1" ] && write_abort_marker "$age" "${age_src}_stale_no_pid"
      if [ "$DRIVER_MODE" = "1" ]; then
        abort_armed=0
        sleep "$INTERVAL"; continue
      fi
      exit 2
    fi
  elif [ "$age" -ge "$WARN_AFTER" ]; then
    if [ "$warned" = "0" ]; then
      echo "" >&2
      echo "[watchdog] $(date '+%H:%M:%S') WARN: no $age_src signal for ${age}s (>= ${WARN_AFTER}s, < ${ABORT_AFTER}s abort)" >&2
      warned=1
    fi
  else
    if [ "$warned" = "1" ]; then
      echo "[watchdog] $(date '+%H:%M:%S') recovered ($age_src fresh, age=${age}s)" >&2
      warned=0
    fi
    abort_armed=1   # 新鲜信号（driver 重启在跳）→ 重新上膛
  fi

  sleep "$INTERVAL"
done
