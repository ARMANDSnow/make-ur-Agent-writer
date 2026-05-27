"""Iter 023 P5: deterministic relationship-consistency auditor.

Replaces the LLM-driven "关系一致性" review agent (iter 020-022) for the
*structural* check of "does the draft contradict entity_graph's active
relationship state?". The LLM agent was redundant with 情感关系 and
连续性审阅 (per iter 022 smoke), and structural conflicts can be
detected with deterministic Python — saving ~¥0.3/chapter and giving
stable, reproducible output.

Algorithm (v1, intentionally conservative):

1. Build a set of (src_name, dst_name, active_state) tuples from
   ``entity_graph.relationships`` where any timeline entry has active=True.
2. Scan the draft sentence-by-sentence (Chinese punctuation split).
3. For each pair (A, B) where BOTH names co-occur in the same sentence,
   emit a RelationshipIssue if the active_state explicitly carries one of
   the "hard conflict" markers (敌对 / 已死 / 已背叛 / 永别 / 失踪) —
   because a co-occurrence implies live interaction.

Anything more nuanced (sentiment analysis, action verb matching) is
iter 024+. The goal in iter 023 is to **catch the obvious bugs** —
characters interacting with characters the graph says have been killed
or have a hostile/severed relationship — without false-positiving on
the 80% of normal scenes.

API:

    audit_relationships(draft, entity_graph) -> list[RelationshipIssue]
"""

from __future__ import annotations

import re
from typing import Any, Dict, List


_SENTENCE_SPLITTER = re.compile(r"[。！？!?\n]+")

# Iter 023 v1 hard-conflict markers. Conservative: only flag when active
# state contains these unambiguous markers. Adding to this list widens
# detection but also raises false-positive risk — start narrow.
_HARD_CONFLICT_KEYWORDS = (
    "敌对",
    "已死",
    "死亡",
    "已背叛",
    "背叛",
    "永别",
    "失踪",
    "已脱离",
    "决裂",
)


def _entity_names(entity_graph: Dict[str, Any]) -> Dict[str, str]:
    """Build a {entity_id: name} index. Handles missing/empty graph."""
    if not entity_graph or not isinstance(entity_graph, dict):
        return {}
    out: Dict[str, str] = {}
    for ent in entity_graph.get("entities", []) or []:
        if not isinstance(ent, dict):
            continue
        ent_id = str(ent.get("id", "")) or str(ent.get("name", ""))
        name = str(ent.get("name") or ent.get("id") or "")
        if ent_id and name:
            out[ent_id] = name
    return out


def _active_state(rel: Dict[str, Any]) -> str:
    """Return the active timeline entry's state text, or '' if none."""
    timeline = rel.get("timeline", []) if isinstance(rel, dict) else []
    if not isinstance(timeline, list):
        return ""
    for item in timeline:
        if isinstance(item, dict) and item.get("active"):
            return str(item.get("state") or "")
    return ""


def _hard_conflict_markers(state_text: str) -> List[str]:
    """Return the conflict markers present in state_text (may be empty)."""
    return [kw for kw in _HARD_CONFLICT_KEYWORDS if kw in state_text]


def audit_relationships(
    draft: str, entity_graph: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Return RelationshipIssue dicts for every (A, B) co-occurrence in
    the draft whose active entity-graph state has a hard-conflict marker.

    Returns ``[]`` when:
    * draft is empty/whitespace
    * entity_graph has no relationships or no active timeline entries
    * no relationship pair carries a hard-conflict marker

    Each issue dict matches ``schemas.RelationshipIssue``:
        {src_name, dst_name, draft_excerpt, graph_active_state, conflict_reason}
    """
    if not draft or not draft.strip():
        return []
    if not entity_graph or not isinstance(entity_graph, dict):
        return []
    relationships = entity_graph.get("relationships", []) or []
    if not relationships:
        return []
    names = _entity_names(entity_graph)

    # Build the (name_a, name_b) → (active_state, markers) lookup.
    conflict_pairs: List[Dict[str, Any]] = []
    for rel in relationships:
        if not isinstance(rel, dict):
            continue
        active_state = _active_state(rel)
        if not active_state:
            continue
        markers = _hard_conflict_markers(active_state)
        if not markers:
            continue
        src_name = names.get(str(rel.get("src_id", "")), "") or str(rel.get("src_name", ""))
        dst_name = names.get(str(rel.get("dst_id", "")), "") or str(rel.get("dst_name", ""))
        if not src_name or not dst_name:
            continue
        conflict_pairs.append({
            "src_name": src_name,
            "dst_name": dst_name,
            "active_state": active_state,
            "markers": markers,
        })

    if not conflict_pairs:
        return []

    # Scan sentences for co-occurrence
    issues: List[Dict[str, Any]] = []
    sentences = _SENTENCE_SPLITTER.split(draft)
    seen_pairs: set = set()  # Dedup per (src, dst); one issue per pair
    for sent in sentences:
        sent = sent.strip()
        if len(sent) < 4:
            continue
        for pair in conflict_pairs:
            key = (pair["src_name"], pair["dst_name"])
            if key in seen_pairs:
                continue
            if pair["src_name"] in sent and pair["dst_name"] in sent:
                markers_str = ", ".join(pair["markers"])
                issues.append({
                    "src_name": pair["src_name"],
                    "dst_name": pair["dst_name"],
                    "draft_excerpt": sent[:200],
                    "graph_active_state": pair["active_state"][:200],
                    "conflict_reason": (
                        f"实体图标记 {pair['src_name']}↔{pair['dst_name']} 关系为"
                        f"『{markers_str}』，但草稿中两人在同一句中互动。"
                    )[:200],
                })
                seen_pairs.add(key)

    return issues
