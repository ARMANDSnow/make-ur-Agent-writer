from __future__ import annotations

import math
import json
from pathlib import Path
from typing import Any, Dict

from . import paths
from .config import ROOT
from .utils import read_json


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
