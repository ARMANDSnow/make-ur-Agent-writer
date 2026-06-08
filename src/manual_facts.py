from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from . import paths
from .config import ROOT
from .schemas import GlobalFact, model_to_dict
from .utils import read_json_optional


# Legacy constant — kept for iter 014-016 test backward compat.
GLOBAL_FACTS_PATH = ROOT / "data" / "manual_overrides" / "global_facts.json"


def _global_facts_path() -> Path:
    return paths.global_facts_path() if paths.workspace_name() else GLOBAL_FACTS_PATH


def load_global_facts(path: Path | None = None) -> List[Dict[str, Any]]:
    path = path or _global_facts_path()
    data = read_json_optional(path, [])
    if isinstance(data, dict):
        items = data.get("facts", [data])
    elif isinstance(data, list):
        items = data
    else:
        items = []
    facts: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        try:
            facts.append(model_to_dict(GlobalFact(**item)))
        except Exception:
            continue
    return facts


def _fact_has_spoiler_evidence(fact: Dict[str, Any]) -> bool:
    """Iter 021: True iff this fact's evidence_spans cite at least one
    chapter that is strictly AFTER the configured start_point.

    Facts whose ALL evidence comes from chapters at or before the start
    are considered "established before continuation" and stay visible.
    Facts with any evidence after the start are filtered as spoilers.

    Defensive: if no evidence_spans or no chapter_id fields, treat as
    NON-spoiler (keep). The intent is to drop only obvious leaks.
    """
    from . import start_point

    if start_point.get_start_chapter_id() is None:
        return False
    # iter 047d (optional, fail-open): explicit reader-known-after axis — the
    # reader learns this fact only after the start point, so hide it pre-start.
    reader_known_after = fact.get("reader_known_after")
    if reader_known_after and start_point.is_after_start(reader_known_after):
        return True
    spans = fact.get("evidence_spans") or []
    if not spans:
        return False
    for span in spans:
        ch_id = span.get("chapter_id") if isinstance(span, dict) else None
        if ch_id and start_point.is_after_start(ch_id):
            return True
    return False


def global_facts_summary(
    path: Path | None = None,
    limit: int = 6000,
    respect_start_point: bool = True,
) -> str:
    """Iter 021: when ``respect_start_point=True`` (the default), facts
    whose evidence cites chapters strictly after the configured start
    point are filtered out as spoilers.

    Default keeps backward compatibility for workspaces with no
    start_chapter.json set (filter becomes a no-op).
    """
    facts = load_global_facts(path)
    if respect_start_point:
        facts = [f for f in facts if not _fact_has_spoiler_evidence(f)]
    if not facts:
        return "无人工全局事实。"
    lines = ["人工全局事实优先于模型推断："]
    for fact in facts:
        applies_to = ", ".join(fact.get("applies_to", [])) or "all"
        lines.append(
            f"- {fact.get('fact_id')}: {fact.get('statement')} "
            f"(confidence={fact.get('confidence')}, scope={fact.get('scope')}, applies_to={applies_to})"
        )
    return "\n".join(lines)[:limit]
