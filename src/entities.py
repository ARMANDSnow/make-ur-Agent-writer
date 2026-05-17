from __future__ import annotations

"""Entity graph loader and active-state renderer for prompt injection."""

from pathlib import Path
from typing import Any, Dict, List

from .config import ROOT
from .utils import read_json


def load_entity_graph(root: Path = ROOT) -> Dict[str, Any]:
    """Load optional entity graph data; missing files degrade to an empty graph."""
    path = root / "data" / "entity_graph.json"
    return read_json(path, {}) or {}


def render_active_state(graph: Dict[str, Any]) -> str:
    """Render active relationship states as Markdown for writer/reviewer prompts."""
    if not graph:
        return ""

    entities = [ent for ent in graph.get("entities", []) if isinstance(ent, dict)]
    relationships = [rel for rel in graph.get("relationships", []) if isinstance(rel, dict)]
    entities_by_id = {str(ent.get("id", "")): ent for ent in entities if ent.get("id")}
    lines: List[str] = ["## 当前续写起点的实体关系状态", "", "### 关键实体"]

    for ent in entities:
        name = str(ent.get("name") or ent.get("id") or "<未命名实体>")
        ent_type = str(ent.get("type") or "entity")
        aliases = [str(alias) for alias in ent.get("aliases", []) if alias]
        alias_str = f"（也叫{'/'.join(aliases)}）" if aliases else ""
        facts = "; ".join(str(fact) for fact in ent.get("key_facts", []) if fact)
        fact_text = facts or "<无补充事实>"
        lines.append(f"- **{name}**{alias_str} [{ent_type}]: {fact_text}")

    lines.extend(["", "### 当前活跃关系（写作时必须遵守）"])
    for rel in relationships:
        timeline = rel.get("timeline", [])
        if not isinstance(timeline, list):
            continue
        active_state = next((item for item in timeline if isinstance(item, dict) and item.get("active")), None)
        if not active_state:
            continue
        src_id = str(rel.get("src_id", ""))
        dst_id = str(rel.get("dst_id", ""))
        src = str(entities_by_id.get(src_id, {}).get("name") or src_id or "<未知实体>")
        dst = str(entities_by_id.get(dst_id, {}).get("name") or dst_id or "<未知实体>")
        relation_type = str(rel.get("relation_type") or "关系")
        state = str(active_state.get("state") or "").strip()
        if state:
            lines.append(f"- **{src} ↔ {dst}** ({relation_type}): {state}")

    return "\n".join(lines) + "\n"
