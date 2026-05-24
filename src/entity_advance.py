from __future__ import annotations

"""Entity relationship advance proposals and user-approved application."""

import difflib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

from . import paths
from .config import ROOT
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
    for idx in indexes:
        if idx < 0 or idx >= len(proposals):
            raise IndexError(f"proposal index out of range: {idx}")
        proposal = proposals[idx]
        if isinstance(proposal, dict):
            selected.append(proposal)

    graph = read_json(graph_path, {})
    if not graph:
        raise FileNotFoundError(f"entity graph not found or empty: {graph_path}")
    before = json.dumps(graph, ensure_ascii=False, indent=2, sort_keys=True)
    updated = _apply_selected(graph, selected, chapter_no)
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
    return {
        "chapter_no": chapter_no,
        "selected": indexes,
        "confirm": confirm,
        "diff": diff,
        "applied_count": len(selected),
        "auto_apply": auto_apply,
        "min_confidence": min_confidence if auto_apply else None,
    }


def _apply_selected(graph: Dict[str, Any], selected: List[Dict[str, Any]], chapter_no: int) -> Dict[str, Any]:
    updated = json.loads(json.dumps(graph, ensure_ascii=False))
    relationships = updated.setdefault("relationships", [])
    for proposal in selected:
        src_id = str(proposal.get("src_id") or "")
        dst_id = str(proposal.get("dst_id") or "")
        if not src_id or not dst_id:
            raise ValueError("proposal missing src_id or dst_id")
        rel = _find_relationship(relationships, src_id, dst_id)
        if rel is None:
            raise ValueError(f"relationship not found: {src_id} <-> {dst_id}")
        timeline = rel.setdefault("timeline", [])
        if not isinstance(timeline, list):
            raise ValueError(f"relationship timeline is not a list: {src_id} <-> {dst_id}")
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
    return updated


def _find_relationship(relationships: List[Any], src_id: str, dst_id: str) -> Dict[str, Any] | None:
    for rel in relationships:
        if not isinstance(rel, dict):
            continue
        left = str(rel.get("src_id") or "")
        right = str(rel.get("dst_id") or "")
        if {left, right} == {src_id, dst_id}:
            return rel
    return None
