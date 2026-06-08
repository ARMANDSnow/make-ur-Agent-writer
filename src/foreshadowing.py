"""iter 047c: foreshadowing TTL registry + GC + must-resolve gate.

``knowledge_index.json["foreshadowing"]`` is a flat per-chapter list with no
lifecycle state. This module adds a workspace-scoped registry tracking each
clue's ``planted_chapter`` / ``ttl`` (in CHAPTERS — deterministic, no
wall-clock) / ``must_resolve`` / ``status`` (open|resolved|expired):

* ``build_registry()`` — (re)seed from knowledge_index; **merge-additive** so
  human lifecycle decisions (resolved/expired) survive a re-extract.
* ``gc(current_chapter)`` — mark overdue 'open' items 'expired' (persisted).
* ``resolve(item_id)`` — mark an item resolved.
* ``overdue_must_resolve(current_chapter)`` — pure read: must_resolve items
  overdue at the given continuation chapter; drives the fail-closed
  write-readiness gate.

Absent / corrupt registry -> read helpers no-op (empty), so behavior is
unchanged until a valid registry exists. ``compress_all`` seeds it from the
fresh index so the gate is live in normal operation.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

from . import paths
from .config import ROOT
from .utils import read_json_optional, write_json


REGISTRY_PATH = ROOT / "data" / "foreshadowing_registry.json"
DEFAULT_TTL_CHAPTERS = 12
# A clue counts as must-resolve (gates writing when overdue) for these kinds.
# Excludes 'payoff' (already a resolution) and 'ambiguity' (intentional).
MUST_RESOLVE_KINDS = ("clue", "unresolved")


def _registry_path() -> Path:
    return paths.foreshadowing_registry_path() if paths.workspace_name() else REGISTRY_PATH


def _index_path() -> Path:
    return (
        paths.index_path()
        if paths.workspace_name()
        else ROOT / "data" / "knowledge_base" / "knowledge_index.json"
    )


def _item_id(fo: Dict[str, Any]) -> str:
    # json-encode the tuple so a '|' inside any field can't cause id collisions.
    key = json.dumps(
        [fo.get("chapter_id", ""), fo.get("kind", ""), fo.get("description", "")],
        ensure_ascii=False,
        sort_keys=True,
    )
    return "fo_" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:12]


def _is_resolved_status(status: str) -> bool:
    """True if a source status means 'already closed' (so it isn't tracked).

    Substring match catches LLM variants like ``resolved_in_chunk`` /
    ``resolved_with_consequences`` / ``paid_off``. ``partially_*`` is treated as
    STILL OPEN (a partial payoff hasn't fully discharged the clue).
    """

    s = status.lower()
    # 'unresolved' contains the substring 'resolv' — exclude it explicitly.
    # 'partially_*' is still open (a partial payoff hasn't fully discharged it).
    if "unresolv" in s or "partial" in s:
        return False
    return any(token in s for token in ("resolv", "payoff", "paid", "closed"))


def registry_exists() -> bool:
    return _registry_path().exists()


def load_registry() -> Dict[str, Any]:
    # read_json_optional degrades to the default on missing/corrupt JSON, so a
    # broken registry fails open (empty) rather than crashing callers.
    data = read_json_optional(_registry_path(), {})
    if not isinstance(data, dict):
        return {"version": 1, "items": []}
    data.setdefault("version", 1)
    if not isinstance(data.get("items"), list):
        data["items"] = []
    return data


def build_registry(*, ttl: int = DEFAULT_TTL_CHAPTERS, force: bool = False) -> Dict[str, Any]:
    """(Re)seed the registry from knowledge_index foreshadowing.

    Merge-additive: existing items (by id) are kept verbatim so a human's
    resolve/expire decision survives a re-extract; only genuinely-new clues are
    appended as ``open``. ``planted_chapter`` is 0 (these clues already exist at
    the continuation start). ``must_resolve`` defaults True for kinds in
    ``MUST_RESOLVE_KINDS``. ``force=True`` rebuilds from scratch (drops existing).
    """

    existing = [] if force else [it for it in load_registry().get("items", []) if isinstance(it, dict)]
    seen_ids = {it.get("id") for it in existing}
    items: List[Dict[str, Any]] = list(existing)

    index = read_json_optional(_index_path(), {}) or {}
    raw = index.get("foreshadowing", []) if isinstance(index, dict) else []
    for fo in raw:
        if not isinstance(fo, dict):
            continue
        if _is_resolved_status(str(fo.get("status") or "")):
            continue  # already closed in source — don't track
        iid = _item_id(fo)
        if iid in seen_ids:
            continue  # already tracked (keep its lifecycle state)
        kind = str(fo.get("kind") or "").lower()
        items.append(
            {
                "id": iid,
                "description": str(fo.get("description") or "").strip(),
                "kind": kind,
                "planted_chapter": 0,
                "ttl": int(ttl),
                "must_resolve": kind in MUST_RESOLVE_KINDS,
                "status": "open",
            }
        )
        seen_ids.add(iid)
    data = {"version": 1, "items": items}
    write_json(_registry_path(), data)
    return data


def _overdue_by_ttl(item: Dict[str, Any], current_chapter: int) -> bool:
    ttl = int(item.get("ttl", DEFAULT_TTL_CHAPTERS))
    planted = int(item.get("planted_chapter", 0))
    return (int(current_chapter) - planted) > ttl


def overdue_must_resolve(current_chapter: int) -> List[Dict[str, Any]]:
    """Pure read: must_resolve items overdue at ``current_chapter``.

    Includes both still-``open`` items past their TTL and already-``expired``
    items (a gc'd item keeps blocking until ``resolve``d). ``[]`` when no/empty
    registry.
    """

    out: List[Dict[str, Any]] = []
    for it in load_registry().get("items", []):
        if not isinstance(it, dict) or not it.get("must_resolve"):
            continue
        status = it.get("status")
        if status == "resolved":
            continue
        if status == "expired" or (
            status in ("open", "", None) and _overdue_by_ttl(it, current_chapter)
        ):
            out.append(it)
    return out


def gc(current_chapter: int) -> Dict[str, Any]:
    """Mark overdue 'open' items 'expired'; persist only if anything changed."""

    data = load_registry()
    expired: List[str] = []
    for it in data.get("items", []):
        if (
            isinstance(it, dict)
            and it.get("status") in ("open", "", None)
            and _overdue_by_ttl(it, current_chapter)
        ):
            it["status"] = "expired"
            expired.append(it.get("id"))
    if expired:
        write_json(_registry_path(), data)
    return {"current_chapter": int(current_chapter), "expired": expired, "total": len(data.get("items", []))}


def resolve(item_id: str) -> bool:
    data = load_registry()
    changed = False
    for it in data.get("items", []):
        if isinstance(it, dict) and it.get("id") == item_id:
            it["status"] = "resolved"
            changed = True
    if changed:
        write_json(_registry_path(), data)
    return changed
