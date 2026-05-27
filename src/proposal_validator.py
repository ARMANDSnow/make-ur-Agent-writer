"""Iter 024 P4: validate entity_advance proposals against next chapter plan.

iter 019 added auto-apply for entity_advance proposals (confidence >=
0.7). iter 024 adds a safety check: if applying a proposal would change
a relationship state into a hard-conflict marker (敌对 / 已死 / 已背叛
/ ...) AND the *next* chapter's plan describes those same characters
interacting actively, applying the proposal would create an internal
contradiction the writer can't resolve.

This module returns a list of conflicting proposal indexes so
``scripts/write_book.sh`` can skip them (and let the operator review
manually) without blocking the entire chapter pipeline.

Heuristic v1 (intentionally conservative):

1. For each proposal, derive (src_name, dst_name, new_state).
2. If new_state contains NO hard-conflict marker → SAFE (most cases).
3. Find the next chapter (target_chapter_no + 1) in chapter_plan.chapters.
4. Scan its ``relationships_in_play`` strings for both names.
5. If both names co-occur in any relationship string → CONFLICT (the
   plan expects them to interact, but the proposal would mark them as
   敌对/已死/etc).

Returns ``[]`` when chapter_plan is missing, when no proposals carry
hard-conflict markers, or when next-chapter relationships don't mention
the affected pair. Default conservative: when in doubt, allow apply
(matches iter 023 behavior).

API:

    validate_proposals_against_plan(proposals, target_chapter_no,
                                    chapter_plan, entity_graph)
    -> list[dict]  # conflicting proposal info (empty = all safe)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .relationship_auditor import _HARD_CONFLICT_KEYWORDS


def _names_index(entity_graph: Dict[str, Any]) -> Dict[str, str]:
    """Build {entity_id: name} lookup. Missing fields default empty."""
    if not isinstance(entity_graph, dict):
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


def _next_chapter_plan(
    chapter_plan: Dict[str, Any], target_chapter_no: int
) -> Optional[Dict[str, Any]]:
    """Return chapter_plan.chapters[i] where i == target_chapter_no + 1.

    Returns None if chapter_plan is malformed, empty, or the next
    chapter index is past the plan's tail.
    """
    if not isinstance(chapter_plan, dict):
        return None
    chapters = chapter_plan.get("chapters", []) or []
    if not isinstance(chapters, list):
        return None
    target_next = target_chapter_no + 1
    for ch in chapters:
        if isinstance(ch, dict) and int(ch.get("chapter_no", 0) or 0) == target_next:
            return ch
    return None


def _hard_conflict_markers(state_text: str) -> List[str]:
    """Return any hard-conflict marker substrings present in state_text."""
    if not state_text:
        return []
    return [kw for kw in _HARD_CONFLICT_KEYWORDS if kw in state_text]


def _proposal_names(proposal: Dict[str, Any], names_index: Dict[str, str]) -> tuple[str, str]:
    """Resolve proposal's (src_name, dst_name) from id index or fallback."""
    src_id = str(proposal.get("src_id", "") or "")
    dst_id = str(proposal.get("dst_id", "") or "")
    src = names_index.get(src_id, "") or str(proposal.get("src_name", "") or "")
    dst = names_index.get(dst_id, "") or str(proposal.get("dst_name", "") or "")
    return src, dst


def validate_proposals_against_plan(
    proposals: List[Dict[str, Any]],
    target_chapter_no: int,
    chapter_plan: Dict[str, Any],
    entity_graph: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Return list of conflict reports for proposals that would create
    an internal contradiction with the next chapter's plan.

    Each conflict entry contains::

        {
            "proposal_index": int,  # position in input proposals list
            "src_name": str,
            "dst_name": str,
            "markers": list[str],   # hard-conflict markers found in new_state
            "next_chapter_no": int,
            "plan_excerpt": str,    # relationship_in_play string that mentioned both
            "reason": str,
        }

    Empty list = all proposals safe (or no plan / no hard-conflict).
    Caller (write_book.sh) can use the index list to skip those specific
    proposals while still auto-applying the rest.
    """
    if not proposals or not isinstance(proposals, list):
        return []
    next_plan = _next_chapter_plan(chapter_plan, target_chapter_no)
    if next_plan is None:
        # No next-chapter plan → can't compare → default safe (iter 023 behavior)
        return []
    relationships_in_play = next_plan.get("relationships_in_play", []) or []
    if not isinstance(relationships_in_play, list) or not relationships_in_play:
        return []
    names_index = _names_index(entity_graph)

    conflicts: List[Dict[str, Any]] = []
    for idx, proposal in enumerate(proposals):
        if not isinstance(proposal, dict):
            continue
        new_state = str(proposal.get("new_state", "") or "")
        markers = _hard_conflict_markers(new_state)
        if not markers:
            continue  # not a hard-conflict proposal — safe by default
        src_name, dst_name = _proposal_names(proposal, names_index)
        if not src_name or not dst_name:
            continue  # missing names — can't match against plan strings
        # Check if the next chapter plan expects these two to interact
        for rel_str in relationships_in_play:
            if not isinstance(rel_str, str):
                continue
            if src_name in rel_str and dst_name in rel_str:
                conflicts.append({
                    "proposal_index": idx,
                    "src_name": src_name,
                    "dst_name": dst_name,
                    "markers": markers,
                    "next_chapter_no": int(next_plan.get("chapter_no", 0) or 0),
                    "plan_excerpt": rel_str[:200],
                    "reason": (
                        f"proposal[{idx}] would set {src_name}↔{dst_name} to "
                        f"『{', '.join(markers)}』 but next chapter (ch"
                        f"{next_plan.get('chapter_no')}) plan expects active "
                        f"interaction: {rel_str[:120]}"
                    )[:300],
                })
                break  # one match is enough per proposal

    return conflicts
