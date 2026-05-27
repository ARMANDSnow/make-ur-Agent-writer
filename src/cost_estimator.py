from __future__ import annotations

import math
import json
from pathlib import Path
from typing import Any, Dict

from . import paths
from .config import ROOT
from .utils import read_json


# Iter 024 P3: shared deepseek-v3-pro pricing (USD per 1M tokens). Was
# duplicated in scripts/collect_iter020_data.py — now single source of
# truth. cost_cny() helper consumed by estimate_cost_since() and by the
# collector script.
PROMPT_USD_PER_M = 0.27
CACHE_READ_USD_PER_M = 0.07
RESPONSE_USD_PER_M = 1.10
USD_TO_CNY = 7.2


def cost_cny(prompt_tokens: int, cache_read_tokens: int, response_tokens: int) -> float:
    """Convert raw token usage (3 fields) to estimated cost in CNY.
    Non-cache prompt tokens billed standard; cache_read cheaper; response
    tokens highest. Negative inputs clamped to 0."""
    non_cache = max(prompt_tokens - cache_read_tokens, 0)
    usd = (
        non_cache * PROMPT_USD_PER_M / 1e6
        + max(cache_read_tokens, 0) * CACHE_READ_USD_PER_M / 1e6
        + max(response_tokens, 0) * RESPONSE_USD_PER_M / 1e6
    )
    return usd * USD_TO_CNY


def _resolve_root(root: Path | None) -> Path:
    if root is not None:
        return root
    return paths.workspace_root() if paths.workspace_name() else ROOT


def estimate_cost(root: Path | None = None) -> Dict[str, Any]:
    root = _resolve_root(root)
    manifest = read_json(root / "data" / "chapter_manifest.json", [])
    total_chars = sum(int(entry.get("char_count", 0)) for entry in manifest)
    estimated_tokens = math.ceil(total_chars / 1.6) if total_chars else 0
    chapters = len(manifest)
    token_usage = _token_usage_from_logs(root / "logs" / "llm_calls.jsonl")
    return {
        "chapters": chapters,
        "source_chars": total_chars,
        "estimated_source_tokens": estimated_tokens,
        "actual_prompt_tokens": token_usage["prompt_tokens"],
        "actual_response_tokens": token_usage["response_tokens"],
        "cache_read_tokens": token_usage["cache_read_tokens"],
        "cache_write_tokens": token_usage["cache_write_tokens"],
        "llm_logged_calls": token_usage["calls"],
        "extract_calls": chapters,
        "compress_calls": 1 if chapters else 0,
        "debate_calls": 36,
        "review_calls_per_written_chapter": 7,
        "note": (
            "Uses logged token totals when logs/llm_calls.jsonl has token fields; "
            "source token estimate remains a rough local fallback."
        ),
    }


def _token_usage_from_logs(path: Path) -> Dict[str, int]:
    usage = {
        "calls": 0,
        "prompt_tokens": 0,
        "response_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
    }
    if not path.exists():
        return usage
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        usage["calls"] += 1
        usage["prompt_tokens"] += int(record.get("prompt_tokens", 0) or 0)
        usage["response_tokens"] += int(record.get("response_tokens", 0) or 0)
        usage["cache_read_tokens"] += int(record.get("cache_read_tokens", 0) or 0)
        usage["cache_write_tokens"] += int(record.get("cache_write_tokens", 0) or 0)
    return usage


def estimate_cost_since(line_offset: int = 0, root: Path | None = None) -> Dict[str, Any]:
    """Iter 024 P3: cost delta since `line_offset` of llm_calls.jsonl.

    Used by ``scripts/write_book.sh`` to compute per-chapter cost (set
    line_offset to wc -l at chapter start, then call again after).

    Returns a dict with token totals, cost_cny, calls count. Empty/missing
    log file returns zero-filled dict so the caller never crashes."""
    root = _resolve_root(root)
    path = root / "logs" / "llm_calls.jsonl"
    out = {
        "calls": 0,
        "prompt_tokens": 0,
        "response_tokens": 0,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "cost_cny": 0.0,
        "line_offset": line_offset,
    }
    if not path.exists():
        return out
    lines = path.read_text(encoding="utf-8").splitlines()
    if line_offset >= len(lines):
        return out
    for line in lines[line_offset:]:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        out["calls"] += 1
        out["prompt_tokens"] += int(record.get("prompt_tokens", 0) or 0)
        out["response_tokens"] += int(record.get("response_tokens", 0) or 0)
        out["cache_read_tokens"] += int(record.get("cache_read_tokens", 0) or 0)
        out["cache_write_tokens"] += int(record.get("cache_write_tokens", 0) or 0)
    out["cost_cny"] = round(
        cost_cny(
            out["prompt_tokens"], out["cache_read_tokens"], out["response_tokens"]
        ),
        4,
    )
    return out


def render_cost_estimate(estimate: Dict[str, Any]) -> str:
    return "\n".join(
        [
            "# Cost Estimate",
            "",
            f"- chapters: {estimate['chapters']}",
            f"- source_chars: {estimate['source_chars']}",
            f"- estimated_source_tokens: {estimate['estimated_source_tokens']}",
            f"- llm_logged_calls: {estimate['llm_logged_calls']}",
            f"- actual_prompt_tokens: {estimate['actual_prompt_tokens']}",
            f"- actual_response_tokens: {estimate['actual_response_tokens']}",
            f"- cache_read_tokens: {estimate['cache_read_tokens']}",
            f"- cache_write_tokens: {estimate['cache_write_tokens']}",
            f"- extract_calls: {estimate['extract_calls']}",
            f"- compress_calls: {estimate['compress_calls']}",
            f"- debate_calls: {estimate['debate_calls']}",
            f"- review_calls_per_written_chapter: {estimate['review_calls_per_written_chapter']}",
            f"- note: {estimate['note']}",
        ]
    ) + "\n"
