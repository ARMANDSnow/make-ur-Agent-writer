"""Aggregate cost / cache / sub-score data for the Insights page.

Pure aggregation over llm_calls.jsonl + chapter_NN.meta.json /
chapter_NN.review.json. No LLM calls, no writes.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, Dict, List

from .. import paths
from ..utils import read_json_optional


def collect_insights() -> Dict[str, Any]:
    """Caller is responsible for entering the workspace context."""
    cost_by_chapter = _cost_by_chapter()
    cache_by_model = _cache_by_model()
    subscores = _subscores_per_chapter()
    return {
        "cost_by_chapter": cost_by_chapter,
        "cache_by_model": cache_by_model,
        "subscores": subscores,
    }


def _cost_by_chapter() -> List[Dict[str, Any]]:
    path = paths.llm_calls_log_path()
    out: Dict[int, Dict[str, float]] = defaultdict(lambda: {"calls": 0, "cost_cny": 0.0})
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            ch = rec.get("chapter")
            if not isinstance(ch, int):
                continue
            out[ch]["calls"] += 1
            try:
                out[ch]["cost_cny"] += float(rec.get("cost_cny") or 0.0)
            except (TypeError, ValueError):
                pass
    return [
        {"chapter": ch, "calls": int(v["calls"]), "cost_cny": round(v["cost_cny"], 4)}
        for ch, v in sorted(out.items())
    ]


def _cache_by_model() -> List[Dict[str, Any]]:
    path = paths.llm_calls_log_path()
    out: Dict[str, Dict[str, int]] = defaultdict(lambda: {"calls": 0, "read": 0, "write": 0})
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            model = rec.get("model") or "(unknown)"
            out[model]["calls"] += 1
            out[model]["read"] += int(rec.get("cache_read_tokens") or 0)
            out[model]["write"] += int(rec.get("cache_write_tokens") or 0)
    rows = []
    for model, v in sorted(out.items()):
        total = v["read"] + v["write"]
        ratio = (v["read"] / total) if total else 0.0
        rows.append({
            "model": model,
            "calls": v["calls"],
            "cache_read_tokens": v["read"],
            "cache_write_tokens": v["write"],
            "hit_ratio": round(ratio, 3),
        })
    return rows


def _subscores_per_chapter() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    drafts = paths.drafts_dir()
    reviews = paths.reviews_dir()
    if not drafts.exists():
        return rows
    for md in sorted(drafts.glob("chapter_*.md")):
        meta_path = md.with_suffix(".meta.json")
        review_path = reviews / md.name.replace(".md", ".review.json")
        meta = read_json_optional(meta_path, {})
        review = read_json_optional(review_path, {})
        agent_reviews = []
        if isinstance(review, dict):
            agent_reviews = review.get("agent_reviews") or []
        if not agent_reviews and isinstance(meta, dict):
            agent_reviews = meta.get("agent_reviews") or []
        plot = prose = fidelity = total = 0.0
        n = 0
        for a in agent_reviews:
            sub = (a or {}).get("sub_scores") or {}
            try:
                plot += float(sub.get("plot") or 0)
                prose += float(sub.get("prose") or 0)
                fidelity += float(sub.get("fidelity") or 0)
            except (TypeError, ValueError):
                continue
            try:
                total += float(a.get("score") or 0)
            except (TypeError, ValueError):
                pass
            n += 1
        try:
            ch_no = int(md.stem.split("_")[1])
        except (IndexError, ValueError):
            continue
        rows.append({
            "chapter": ch_no,
            "agents": n,
            "plot": round(plot / n, 2) if n else None,
            "prose": round(prose / n, 2) if n else None,
            "fidelity": round(fidelity / n, 2) if n else None,
            "total": round(total / n, 2) if n else None,
        })
    return rows
