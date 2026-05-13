from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from .config import ROOT
from .schemas import GlobalFact, model_to_dict
from .utils import read_json


GLOBAL_FACTS_PATH = ROOT / "data" / "manual_overrides" / "global_facts.json"


def load_global_facts(path: Path | None = None) -> List[Dict[str, Any]]:
    path = path or GLOBAL_FACTS_PATH
    data = read_json(path, [])
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
        facts.append(model_to_dict(GlobalFact(**item)))
    return facts


def global_facts_summary(path: Path | None = None, limit: int = 6000) -> str:
    facts = load_global_facts(path)
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
