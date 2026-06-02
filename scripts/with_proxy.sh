#!/usr/bin/env bash
# Iter 027 — proxy adapter for the aetherheartpool tunnel.
#
# Why this exists
#   The aetherheartpool.top tunnel is reachable two ways from this repo:
#     (a) the Claude Code sandbox forces all egress through localhost:63501
#         (no DNS / no direct egress otherwise);
#     (b) the user's own terminal can reach it directly without any proxy
#         (verified 2026-05-29: curl --noproxy returns 401 in ~2s).
#   Long-running entrypoints (write_book.sh, watchdog.sh, *_smoke.sh) must
#   work in both environments without manual env tweaks per run.
#
# Strategy
#   Probe localhost:63501 with bash /dev/tcp. If something is listening,
#   assume sandbox and export HTTP(S)_PROXY=http://localhost:63501.
#   Otherwise assume local terminal and unset every PROXY var we know,
#   because the tunnel is directly reachable and a stale Clash proxy
#   (HTTP_PROXY=http://127.0.0.1:7897) silently breaks calls when Clash
#   isn't running.
#
# Usage
#   # As a source — exports env into current shell:
#   source "$(dirname "${BASH_SOURCE[0]}")/with_proxy.sh"
#
#   # As a wrapper — runs CMD with adjusted env, then exits:
#   scripts/with_proxy.sh python3 scripts/iter027_model_smoke.py

_with_proxy_sandbox_alive() {
  # /dev/tcp is a bash builtin; 1s timeout via the SECONDS-loop pattern
  # would over-engineer this. The connect either succeeds or fails fast.
  (exec 3<>/dev/tcp/localhost/63501) 2>/dev/null && exec 3>&- 3<&-
}

if _with_proxy_sandbox_alive; then
  export HTTP_PROXY="http://localhost:63501"
  export HTTPS_PROXY="http://localhost:63501"
  export http_proxy="http://localhost:63501"
  export https_proxy="http://localhost:63501"
  # ALL_PROXY outranks HTTP(S)_PROXY in some HTTP clients (requests, curl
  # with certain libcurl builds). Clear it so the 63501 tunnel actually
  # wins instead of being shadowed by a leftover socks5://… value.
  unset ALL_PROXY all_proxy
  _WITH_PROXY_MODE="sandbox-63501"
else
  unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy ALL_PROXY all_proxy
  _WITH_PROXY_MODE="direct"
fi

echo "[with_proxy] mode=${_WITH_PROXY_MODE}" >&2

unset -f _with_proxy_sandbox_alive

# Only act as a wrapper (exec the rest of argv) when invoked DIRECTLY as
# an executable — never when sourced into a parent script. When sourced,
# $@ is the parent's argv, and exec'ing it would treat the parent's
# first arg (e.g. "--book") as a command. The classic shell check:
# BASH_SOURCE[0] == $0 only when this file is the entry point.
if [ "${BASH_SOURCE[0]:-$0}" = "$0" ] && [ "$#" -gt 0 ]; then
  exec "$@"
fi
