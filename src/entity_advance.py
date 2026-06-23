from __future__ import annotations

"""Entity relationship advance proposals and user-approved application."""

import difflib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

from . import paths
from .config import ROOT
# Canonical home of the hard-conflict markers (owns _HARD_CONFLICT_KEYWORDS);
# proposal_validator only re-wraps it, so import the source to avoid divergence.
from .relationship_auditor import _hard_conflict_markers
from .state import log_event
from .utils import ensure_dir, read_json, write_json


# Legacy constants — kept for iter 014-016 test backward compat.
DRAFTS_DIR = ROOT / "outputs" / "drafts"
ENTITY_GRAPH_PATH = ROOT / "data" / "entity_graph.json"


def _drafts_dir() -> Path:
    return paths.drafts_dir() if paths.workspace_name() else DRAFTS_DIR


def _entity_graph_path() -> Path:
    return paths.entity_graph_path() if paths.workspace_name() else ENTITY_GRAPH_PATH


def proposal_path(chapter_no: int, drafts_dir: Path | None = None) -> Path:
    if drafts_dir is None:
        drafts_dir = _drafts_dir()
    return drafts_dir / f"chapter_{chapter_no:02d}.entity_advance_proposals.json"


def save_entity_advance_proposals(
    chapter_no: int,
    proposed_advances: List[Dict[str, Any]],
    drafts_dir: Path | None = None,
) -> Path:
    if drafts_dir is None:
        drafts_dir = _drafts_dir()
    path = proposal_path(chapter_no, drafts_dir)
    ensure_dir(path.parent)
    write_json(path, {"chapter_no": int(chapter_no), "proposed_advances": proposed_advances})
    return path


def active_relationships(graph: Dict[str, Any]) -> List[Dict[str, Any]]:
    relationships: List[Dict[str, Any]] = []
    for rel in graph.get("relationships", []) or []:
        if not isinstance(rel, dict):
            continue
        timeline = rel.get("timeline", [])
        if not isinstance(timeline, list):
            continue
        active = next((item for item in timeline if isinstance(item, dict) and item.get("active")), None)
        if active:
            item = dict(rel)
            item["old_active_state"] = str(active.get("state") or "")
            relationships.append(item)
    return relationships


def _parse_indexes(raw_indexes: str | Iterable[int]) -> List[int]:
    if isinstance(raw_indexes, str):
        if not raw_indexes.strip():
            return []
        return [int(part.strip()) for part in raw_indexes.split(",") if part.strip()]
    return [int(item) for item in raw_indexes]


def select_auto_indexes(
    proposals: List[Dict[str, Any]], min_confidence: float = 0.7
) -> List[int]:
    """Iter 019: pick proposal indexes whose confidence >= min_confidence.

    Pure function (no I/O, no path lookup) so write_book.sh's automated
    selection step is trivially unit-testable. Non-dict entries and entries
    with missing / unparseable confidence are skipped (rather than raising)
    because the upstream LLM extractor occasionally returns malformed rows
    and we'd rather drop them than crash an unattended write run.
    """

    chosen: List[int] = []
    for idx, proposal in enumerate(proposals):
        if not isinstance(proposal, dict):
            continue
        try:
            conf = float(proposal.get("confidence", 0.0))
        except (TypeError, ValueError):
            continue
        if conf >= float(min_confidence):
            chosen.append(idx)
    return chosen


def _is_applyable_proposal(proposal: Dict[str, Any]) -> bool:
    return bool(
        str(proposal.get("src_id") or "").strip()
        and str(proposal.get("dst_id") or "").strip()
        and str(proposal.get("new_state") or "").strip()
    )


def apply_advance_proposals(
    *,
    chapter_no: int,
    proposal_indexes: str | Iterable[int] = "",
    confirm: bool = False,
    graph_path: Path | None = None,
    drafts_dir: Path | None = None,
    auto_apply: bool = False,
    min_confidence: float = 0.7,
    allow_empty: bool = False,
    allow_creation: bool = False,
    creation_confidence: float = 0.85,
) -> Dict[str, Any]:
    """Dry-run or apply selected proposal indexes to data/entity_graph.json.

    Iter 019: with ``auto_apply=True`` the function ignores
    ``proposal_indexes`` and instead selects proposals whose
    ``confidence >= min_confidence`` via :func:`select_auto_indexes`.
    With ``allow_empty=True`` an empty selection short-circuits to a
    no-op result dict (no graph read, no diff) so the unattended write
    loop can call ``apply-advance`` after every chapter without erroring
    when the LLM produced zero proposals.
    """
    if graph_path is None:
        graph_path = _entity_graph_path()
    if drafts_dir is None:
        drafts_dir = _drafts_dir()
    proposals_data = read_json(proposal_path(chapter_no, drafts_dir), {})
    proposals = proposals_data.get("proposed_advances", [])
    if not isinstance(proposals, list):
        proposals = []

    if auto_apply:
        indexes = select_auto_indexes(proposals, min_confidence=min_confidence)
    else:
        indexes = _parse_indexes(proposal_indexes)

    if not indexes:
        if allow_empty:
            return {
                "chapter_no": chapter_no,
                "selected": [],
                "confirm": confirm,
                "diff": "",
                "applied_count": 0,
                "auto_apply": auto_apply,
                "min_confidence": min_confidence if auto_apply else None,
                "no_op_reason": "empty_selection",
            }
        # Fall through to existing strict behavior so legacy callers still
        # see an explicit FileNotFoundError when the graph is missing.

    selected: List[Dict[str, Any]] = []
    selected_indexes: List[int] = []
    for idx in indexes:
        if idx < 0 or idx >= len(proposals):
            raise IndexError(f"proposal index out of range: {idx}")
        proposal = proposals[idx]
        if isinstance(proposal, dict):
            if auto_apply and not _is_applyable_proposal(proposal):
                continue
            selected.append(proposal)
            selected_indexes.append(idx)

    if auto_apply and not selected:
        if allow_empty:
            return {
                "chapter_no": chapter_no,
                "selected": [],
                "confirm": confirm,
                "diff": "",
                "applied_count": 0,
                "auto_apply": auto_apply,
                "min_confidence": min_confidence,
                "no_op_reason": "no_applyable_proposals",
            }
        raise ValueError("no applyable entity advance proposals selected")

    graph = read_json(graph_path, {})
    if not graph:
        raise FileNotFoundError(f"entity graph not found or empty: {graph_path}")
    before = json.dumps(graph, ensure_ascii=False, indent=2, sort_keys=True)
    created: List[Dict[str, Any]] = []
    updated, skipped = _apply_selected(
        graph,
        selected,
        chapter_no,
        allow_creation=allow_creation,
        creation_confidence=creation_confidence,
        created=created,
    )
    after = json.dumps(updated, ensure_ascii=False, indent=2, sort_keys=True)
    diff = "\n".join(
        difflib.unified_diff(
            before.splitlines(),
            after.splitlines(),
            fromfile=str(graph_path),
            tofile=str(graph_path),
            lineterm="",
        )
    )
    if confirm:
        write_json(graph_path, updated)
    result: Dict[str, Any] = {
        "chapter_no": chapter_no,
        "selected": selected_indexes if auto_apply else indexes,
        "confirm": confirm,
        "diff": diff,
        # Skipped (stale-relationship) proposals don't count as applied; iter065
        # #6c: newly-created relationships are reported under created_count, not
        # applied_count (which stays = advances on pre-existing edges).
        "applied_count": len(selected) - len(skipped) - len(created),
        "auto_apply": auto_apply,
        "min_confidence": min_confidence if auto_apply else None,
    }
    if skipped:
        result["skipped"] = skipped
    if created:
        result["created_count"] = len(created)
        result["created"] = created
    return result


def _apply_selected(
    graph: Dict[str, Any],
    selected: List[Dict[str, Any]],
    chapter_no: int,
    *,
    allow_creation: bool = False,
    creation_confidence: float = 0.85,
    created: List[Dict[str, Any]] | None = None,
) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """Apply selected proposals to the graph timeline, tolerating stale refs.

    Returns ``(updated_graph, skipped)``. A proposal whose relationship is
    absent from the graph (or whose timeline is malformed) is collected into
    ``skipped`` and skipped — not raised — so a single stale row no longer
    discards the rest of the batch. Real-model write runs routinely emit a
    proposal for a pair the extractor never wrote to ``entity_graph.json``
    (e.g. ``ent_wuliang_east <-> ent_wuliang_west`` while continuing ch4):
    pre-fix the first such row raised ``ValueError``, which ``book_runner``
    caught as ``apply_advance_failed`` and the entity graph never advanced.
    A proposal missing ``src_id``/``dst_id`` is a structural defect (the
    auto_apply path already pre-filters these via ``_is_applyable_proposal``)
    and still raises.

    iter065 #6c: with ``allow_creation=True`` an absent relationship pair is no
    longer always skipped — a high-confidence proposal (``confidence >=
    creation_confidence``) whose ``new_state`` carries no hard-conflict marker
    creates a brand-new relationship edge instead. Created edges are appended to
    the optional ``created`` list (when provided) so the caller can report them
    separately from advances. ``allow_creation`` defaults False, so the legacy
    ``relationship_not_found`` skip path is byte-identical for existing callers.
    """
    updated = json.loads(json.dumps(graph, ensure_ascii=False))
    relationships = updated.setdefault("relationships", [])
    skipped: List[Dict[str, Any]] = []
    for proposal in selected:
        src_id = str(proposal.get("src_id") or "")
        dst_id = str(proposal.get("dst_id") or "")
        if not src_id or not dst_id:
            raise ValueError("proposal missing src_id or dst_id")
        rel = _find_relationship(relationships, src_id, dst_id)
        if rel is None:
            confidence = float(proposal.get("confidence") or 0.0)
            new_state = str(proposal.get("new_state") or "").strip()
            # iter065 #6c: confidence-gated creation of a NEW relationship,
            # behind allow_creation (default off). Refused (skipped with a
            # specific reason) when: new_state is empty (no applyable content —
            # mirrors _is_applyable_proposal's non-empty-state contract, which
            # the explicit-index creation path would otherwise bypass), the
            # state carries a hard-conflict marker (敌对/已死/已背叛 ...; reuses the
            # same fail-closed guard existing-edge advances pass), or confidence
            # is below the (stricter) creation gate.
            if allow_creation:
                conflict = _hard_conflict_markers(new_state)
                if not new_state:
                    reason = "creation_empty_state"
                elif conflict:
                    reason = "creation_hard_conflict"
                elif confidence < creation_confidence:
                    reason = "creation_below_confidence"
                else:
                    reason = None
                if reason is None:
                    relationships.append(
                        {
                            "src_id": src_id,
                            "dst_id": dst_id,
                            "relation_type": str(proposal.get("relation_type") or "续写新建"),
                            "timeline": [
                                {
                                    "anchor_chapter": f"续写第{chapter_no:02d}章",
                                    "state": new_state,
                                    "trigger_event": str(proposal.get("trigger_event") or "").strip(),
                                    "confidence": confidence,
                                    "active": True,
                                }
                            ],
                        }
                    )
                    if created is not None:
                        created.append({"src_id": src_id, "dst_id": dst_id})
                    log_event(
                        "entity_advance",
                        "relationship_created",
                        src_id=src_id,
                        dst_id=dst_id,
                        chapter_no=chapter_no,
                        confidence=confidence,
                    )
                    continue
                log_event(
                    "entity_advance",
                    "proposal_skipped",
                    reason=reason,
                    src_id=src_id,
                    dst_id=dst_id,
                    chapter_no=chapter_no,
                    confidence=confidence,
                )
                skipped.append({"src_id": src_id, "dst_id": dst_id, "reason": reason})
                continue
            # iter 051b (F5, carry-over from iter 027 review): the skip is the
            # right call (see docstring), but it used to be invisible — a
            # high-confidence proposal silently vanished with no log trail.
            # Leave an audit record so real-model runs can be diagnosed.
            log_event(
                "entity_advance",
                "proposal_skipped",
                reason="relationship_not_found",
                src_id=src_id,
                dst_id=dst_id,
                chapter_no=chapter_no,
                confidence=confidence,
            )
            skipped.append({"src_id": src_id, "dst_id": dst_id, "reason": "relationship_not_found"})
            continue
        timeline = rel.setdefault("timeline", [])
        if not isinstance(timeline, list):
            # iter 051b (F5): same audit trail for the malformed-timeline skip.
            log_event(
                "entity_advance",
                "proposal_skipped",
                reason="timeline_not_a_list",
                src_id=src_id,
                dst_id=dst_id,
                chapter_no=chapter_no,
                confidence=float(proposal.get("confidence") or 0.0),
            )
            skipped.append({"src_id": src_id, "dst_id": dst_id, "reason": "timeline_not_a_list"})
            continue
        for item in timeline:
            if isinstance(item, dict) and item.get("active"):
                item["active"] = False
        timeline.append(
            {
                "anchor_chapter": f"续写第{chapter_no:02d}章",
                "state": str(proposal.get("new_state") or "").strip(),
                "trigger_event": str(proposal.get("trigger_event") or "").strip(),
                "confidence": float(proposal.get("confidence") or 0.0),
                "active": True,
            }
        )
    return updated, skipped


def _find_relationship(relationships: List[Any], src_id: str, dst_id: str) -> Dict[str, Any] | None:
    for rel in relationships:
        if not isinstance(rel, dict):
            continue
        left = str(rel.get("src_id") or "")
        right = str(rel.get("dst_id") or "")
        if {left, right} == {src_id, dst_id}:
            return rel
    return None
