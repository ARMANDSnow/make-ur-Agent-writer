"""iter 027 P1 — single-call connectivity + latency + token sample.

Hits the configured main model (OPENAI_MODEL via OPENAI_BASE_URL) once
with a short Chinese prompt, measures round-trip latency, and prints
the token usage so we have a baseline before committing to a 30-chapter
capstone run.

Outputs JSON to ``logs/iter027_preflight.json`` (per-workspace logs
directory in workspace mode; current-dir-relative in legacy mode).
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

# Project root: scripts/ is one dir below repo root.
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))


def main() -> int:
    from src.llm_client import LLMClient

    prompt = (
        "请用一段不超过 60 字的现代汉语，简述路明非这个人物的关键性格特征。"
        "只输出正文，不要 markdown 或前后缀。"
    )

    client = LLMClient()
    base_url = client.config.get("base_url") or "(provider default)"
    print(f"[smoke] model={client.model} base_url={base_url}")
    print(f"[smoke] is_mock={client.is_mock}")
    if client.is_mock:
        print("[smoke] WARNING: client is in mock mode — connectivity NOT actually tested")

    t0 = time.time()
    try:
        text = client.complete_text(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
        )
    except Exception as exc:
        elapsed = time.time() - t0
        record = {
            "ok": False,
            "elapsed_seconds": round(elapsed, 3),
            "error": f"{type(exc).__name__}: {exc}",
            "model": client.model,
            "base_url": base_url,
        }
        _write(record)
        print(f"[smoke] FAILED after {elapsed:.2f}s: {record['error']}")
        return 1

    elapsed = time.time() - t0
    # Usage / token info is logged separately to logs/llm_calls.jsonl by
    # ``_log_call`` inside complete_text — pull the latest entry to add
    # it to the smoke record.
    usage = _read_last_call_tokens()
    record = {
        "ok": True,
        "elapsed_seconds": round(elapsed, 3),
        "model": client.model,
        "base_url": base_url,
        "response_preview": text[:200],
        "response_chars": len(text),
        "usage": usage,
    }
    _write(record)
    print(f"[smoke] OK in {elapsed:.2f}s · response_chars={len(text)} · usage={usage}")
    print(f"[smoke] preview: {text[:120]}…")
    return 0


def _read_last_call_tokens() -> dict:
    """Pull the last entry from logs/llm_calls.jsonl and extract tokens."""
    try:
        from src import paths

        log_path = paths.llm_calls_log_path() if paths.workspace_name() else Path("logs/llm_calls.jsonl")
    except Exception:
        log_path = Path("logs/llm_calls.jsonl")
    if not log_path.exists():
        return {}
    try:
        lines = log_path.read_text(encoding="utf-8").splitlines()
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            return {
                "prompt_tokens": rec.get("prompt_tokens"),
                "response_tokens": rec.get("response_tokens"),
                "cache_read_tokens": rec.get("cache_read_tokens", 0),
            }
    except Exception:
        return {}
    return {}


def _write(record: dict) -> None:
    try:
        from src import paths

        log_dir = paths.logs_dir() if paths.workspace_name() else Path("logs")
    except Exception:
        log_dir = Path("logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    out = log_dir / "iter027_preflight.json"
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[smoke] wrote {out}")


if __name__ == "__main__":
    sys.exit(main())
