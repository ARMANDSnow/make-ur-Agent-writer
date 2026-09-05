#!/usr/bin/env bash
# Preserve caller proxy configuration by default. The old local tunnel is
# available only with DRAGON_RAJA_PROXY_MODE=sandbox-63501. A failed probe
# leaves every proxy variable untouched; importing/running mock never probes.
if [[ "${OPENAI_MODEL:-mock}" != "mock" && "${DRAGON_RAJA_PROXY_MODE:-}" == "sandbox-63501" ]]; then
  if (exec 3<>/dev/tcp/localhost/63501) 2>/dev/null; then
    export HTTP_PROXY="http://localhost:63501" HTTPS_PROXY="http://localhost:63501"
    export http_proxy="http://localhost:63501" https_proxy="http://localhost:63501"
    unset ALL_PROXY all_proxy
  fi
fi
if [[ "${BASH_SOURCE[0]:-$0}" == "$0" && "$#" -gt 0 ]]; then
  exec "$@"
fi
