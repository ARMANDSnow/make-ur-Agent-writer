from __future__ import annotations

import math
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Set, Tuple

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

# iter078 P1-2: 按 model 前缀查表（USD per 1M tokens：prompt / cache_read /
# response）。此前三个常量对所有 model 生效——换 model 后成本仍按 deepseek
# 单价算，账本静默失真。未知前缀回落 deepseek 现值 + 进程内单次 WARN；
# mock 记 0（本地 mock 跑零成本才是真实账目）。
MODEL_PRICING: Dict[str, Tuple[float, float, float]] = {
    "deepseek": (PROMPT_USD_PER_M, CACHE_READ_USD_PER_M, RESPONSE_USD_PER_M),
    "mock": (0.0, 0.0, 0.0),
}

_UNKNOWN_MODEL_WARNED: Set[str] = set()


def _mock_pricing_override() -> Tuple[float, float, float] | None:
    raw = os.getenv("MOCK_COST_CNY_PER_1K_TOKENS", "").strip()
    if not raw:
        return None
    try:
        cny_per_1k = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(cny_per_1k) or cny_per_1k <= 0:
        return None
    usd_per_m = (cny_per_1k * 1000.0) / USD_TO_CNY
    return (usd_per_m, usd_per_m, usd_per_m)


def _pricing_for_model(model: str) -> Tuple[float, float, float]:
    name = str(model or "").strip().lower()
    if not name:
        # 旧调用方（不传 model）字节兼容：按 deepseek 现值，不告警。
        return (PROMPT_USD_PER_M, CACHE_READ_USD_PER_M, RESPONSE_USD_PER_M)
    for prefix, pricing in MODEL_PRICING.items():
        # 匹配 "deepseek" / "deepseek/deepseek-chat" / "openrouter/deepseek/..."
        if name.startswith(prefix) or f"/{prefix}" in name:
            if prefix == "mock":
                return _mock_pricing_override() or pricing
            return pricing
    if name not in _UNKNOWN_MODEL_WARNED:
        _UNKNOWN_MODEL_WARNED.add(name)
        print(
            f"[cost_estimator] WARN: 模型 {model!r} 不在 MODEL_PRICING 单价表中，"
            "按 deepseek 现值估算（成本可能失真；请在 src/cost_estimator.py 补条目）",
            file=sys.stderr,
        )
    return (PROMPT_USD_PER_M, CACHE_READ_USD_PER_M, RESPONSE_USD_PER_M)


def cost_cny(
    prompt_tokens: int,
    cache_read_tokens: int,
    response_tokens: int,
    model: str = "",
) -> float:
    """Convert raw token usage (3 fields) to estimated cost in CNY.
    Non-cache prompt tokens billed standard; cache_read cheaper; response
    tokens highest. Negative inputs clamped to 0.

    iter078 P1-2: 可选 ``model`` 按前缀查 MODEL_PRICING；缺省（旧调用方）
    沿用 deepseek 现值，字节兼容。"""
    prompt_rate, cache_rate, response_rate = _pricing_for_model(model)
    non_cache = max(prompt_tokens - cache_read_tokens, 0)
    usd = (
        non_cache * prompt_rate / 1e6
        + max(cache_read_tokens, 0) * cache_rate / 1e6
        + max(response_tokens, 0) * response_rate / 1e6
    )
    return usd * USD_TO_CNY


_DIRTY_LINES_WARNED: Set[str] = set()


def _warn_dirty_lines(path: Path, dirty: int) -> None:
    key = str(path)
    if key in _DIRTY_LINES_WARNED:
        return
    _DIRTY_LINES_WARNED.add(key)
    print(
        f"[cost_estimator] WARN: {path} 有 {dirty} 行无法解析（可能是中断残行），"
        "这些行的 token 消耗未入账，成本估算偏低",
        file=sys.stderr,
    )


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
        "dirty_lines": 0,
    }
    if not path.exists():
        return usage
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            # iter078 P1-2: 脏行不再静默归零——计数透出 + 单次 stderr WARN。
            usage["dirty_lines"] += 1
            continue
        if not isinstance(record, dict):
            # iter078 收官审查修复：合法标量 JSON 残行（null/123）过得了
            # json.loads 却会让 record.get 炸 AttributeError——同样算脏行。
            usage["dirty_lines"] += 1
            continue
        usage["calls"] += 1
        usage["prompt_tokens"] += int(record.get("prompt_tokens", 0) or 0)
        usage["response_tokens"] += int(record.get("response_tokens", 0) or 0)
        usage["cache_read_tokens"] += int(record.get("cache_read_tokens", 0) or 0)
        usage["cache_write_tokens"] += int(record.get("cache_write_tokens", 0) or 0)
    if usage["dirty_lines"]:
        _warn_dirty_lines(path, usage["dirty_lines"])
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
        "dirty_lines": 0,
    }
    if not path.exists():
        return out
    lines = path.read_text(encoding="utf-8").splitlines()
    if line_offset >= len(lines):
        return out
    # iter078 P1-2: 逐 record 按其 model 字段计价累加（此前先汇总 token 再按
    # deepseek 单价一次计价——混 model 日志必然失真）。token 汇总字段保留，
    # 消费方（budget_check_cb / driver / Web dashboard）读的形状不变。
    total_cost = 0.0
    for line in lines[line_offset:]:
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            out["dirty_lines"] += 1
            continue
        if not isinstance(record, dict):
            # 同 _token_usage_from_logs：标量 JSON 残行按脏行计。
            out["dirty_lines"] += 1
            continue
        prompt = int(record.get("prompt_tokens", 0) or 0)
        response = int(record.get("response_tokens", 0) or 0)
        cache_read = int(record.get("cache_read_tokens", 0) or 0)
        out["calls"] += 1
        out["prompt_tokens"] += prompt
        out["response_tokens"] += response
        out["cache_read_tokens"] += cache_read
        out["cache_write_tokens"] += int(record.get("cache_write_tokens", 0) or 0)
        total_cost += cost_cny(
            prompt, cache_read, response, model=str(record.get("model") or "")
        )
    out["cost_cny"] = round(total_cost, 4)
    if out["dirty_lines"]:
        _warn_dirty_lines(path, out["dirty_lines"])
    return out


def estimate_next_chapter_cost(
    cumulative_costs: list, default_cny: float, *, window: int = 3
) -> float:
    """iter076 HIGH#2：估算「下一章」的成本（CNY），供章前预算预留闸用。

    ``cumulative_costs`` 是 book_runner 的 ``costs`` 列表——每章完成后 append 的
    ``estimate_cost_since(run 起点)`` 结果，**cost_cny 是累计值不是单章值**，因此
    先相邻差分还原每章成本，再取最近 ``window`` 章的均值。无可用历史（run 内
    第一章 / 字段缺失 / 差分出负数脏值）→ 回落 ``default_cny``。任何形状异常
    不抛（fail-open 回 default，铁律④）。"""
    try:
        cumulative = []
        for item in cumulative_costs or []:
            if isinstance(item, dict) and "cost_cny" in item:
                try:
                    val = float(item.get("cost_cny") or 0.0)
                except (TypeError, ValueError):
                    continue   # 单条脏账目跳过，不拖垮整段历史
                if math.isfinite(val):
                    cumulative.append(val)
        per_chapter = []
        prev = 0.0
        for val in cumulative:
            delta = val - prev
            prev = val
            if delta > 0:
                per_chapter.append(delta)
        if not per_chapter:
            return max(0.0, float(default_cny))
        recent = per_chapter[-max(1, int(window)):]
        return sum(recent) / len(recent)
    except Exception:
        return max(0.0, float(default_cny))


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
