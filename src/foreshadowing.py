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

iter077 P0-1: source-boundary seeds (clues that already existed in the source
book at the continuation start) are EXCLUDED from the fail-closed gate by
default and surfaced as an advisory instead (``boundary_overdue_must_resolve``).
Rationale: ``build_registry`` seeds every source clue at planted_chapter=0 with
ttl=12 and the pipeline has no automatic resolve path, so any 14+-chapter
continuation run deterministically tripped the gate at the ch14+ segment
boundary (supervisor terminal exit). The gate stays fail-closed for clues
planted DURING the continuation and for items whose provenance is unknowable.
Escape hatch: hand-edit a boundary item's ``planted_chapter`` to a positive
chapter number (or set ``origin: "continuation"``) to re-arm the gate for it.

iter078 技债-2: 显式 ``origin`` 字段（两轴语义）——
``"continuation"``（预留给未来的续写期回灌路径）→ **无条件进闸门**（即使
planted_chapter=0 形态）；``"source_book"``（build_registry 播种时写入）与
缺失/非法 origin → 走 ``planted_chapter <= 0`` 启发式（存量 registry 零迁移，
且保留 iter077 逃生门：planted_chapter 改正数 = 重新武装闸门）。动机
（iter077 审查提名）：纯 planted_chapter 猜测下，若未来加「续写回灌
compress」，新种伏笔会以 planted_chapter=0 形态生而 advisory、闸门静默失效
——origin 把「出身」钉死在播种侧，planted_chapter 保留「武装状态」语义。
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


def _normalize_desc(desc: Any) -> str:
    # iter047B2 M1: normalize so a trivial LLM rewording on re-extract (collapsed
    # whitespace / trailing punctuation) doesn't change the id and resurrect a
    # human-resolved item. Only the id is normalized; the stored description
    # keeps its original text.
    s = " ".join(str(desc or "").split())
    return s.rstrip(" 　。．.!！?？;；,，、…").strip()


def _item_id(fo: Dict[str, Any]) -> str:
    # json-encode the tuple so a '|' inside any field can't cause id collisions.
    key = json.dumps(
        [fo.get("chapter_id", ""), fo.get("kind", ""), _normalize_desc(fo.get("description", ""))],
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
    # 'unresolved' / 'irresolvable' contain the substring 'resolv' — exclude them
    # explicitly (iter047B2 M2: 'irresolvable' means STILL-OPEN, not closed).
    # 'partially_*' is still open (a partial payoff hasn't fully discharged it).
    if "unresolv" in s or "irresolv" in s or "partial" in s:
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
                # iter078 技债-2: 显式出身——knowledge_index 播种的伏笔全部
                # 来自源书正文（续写起点前已存在）。未来若加续写期回灌路径，
                # 新种项必须写 "continuation"，否则会被 boundary 豁免静默
                # 绕过闸门（见模块 docstring）。
                "origin": "source_book",
            }
        )
        seen_ids.add(iid)
    data = {"version": 1, "items": items}
    write_json(_registry_path(), data)
    return data


def _overdue_by_ttl(item: Dict[str, Any], current_chapter: int) -> bool:
    # iter047B2 H3: a malformed ttl/planted must NOT raise — the readiness gate
    # swallows exceptions, so a raise would silently fail-OPEN a fail-closed
    # gate. Treat unparseable values as immediately overdue (fail-closed).
    try:
        ttl = int(item.get("ttl", DEFAULT_TTL_CHAPTERS))
        planted = int(item.get("planted_chapter", 0))
        cur = int(current_chapter)
    except (TypeError, ValueError):
        return True
    return (cur - planted) > ttl


def is_boundary_item(item: Dict[str, Any]) -> bool:
    """True for source-boundary seeds（豁免 must_resolve 闸门、走 advisory）。

    iter078 技债-2 判定（两轴）：
    1. ``origin == "continuation"``（续写期新种项）→ 无条件非 boundary
       ——必须进闸门，即使 planted_chapter=0 形态（未来回灌路径的防毒钉）。
    2. ``origin == "source_book"`` 与缺失/非法 origin → 走
       ``planted_chapter <= 0`` 启发式：存量 registry 零迁移，且保留
       iter077 逃生门（planted_chapter 改正数 = 重新武装闸门）。
    3. An unparseable planted_chapter is NOT boundary — the item stays in
       the fail-closed gate rather than being silently exempted
       (iter047B2 H3 spirit).
    """

    origin = str(item.get("origin") or "").strip().lower()
    if origin == "continuation":
        return False
    if "planted_chapter" not in item:
        # iter078 收官审查修复：键缺失 = 出身不可知（手填条目漏字段），与
        # unparseable 同款留在 fail-closed 闸门内，不得默认 0 静默豁免。
        # build_registry 播种必写该键，存量 registry 零影响。
        return False
    try:
        return int(item.get("planted_chapter", 0)) <= 0
    except (TypeError, ValueError):
        return False


def _overdue_must_resolve_items(current_chapter: int) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for it in load_registry().get("items", []):
        if not isinstance(it, dict) or not it.get("must_resolve"):
            continue
        status = str(it.get("status") or "").strip().lower()
        if status == "resolved":
            resolution = it.get("resolution")
            if not isinstance(resolution, dict):
                continue  # Retain legacy explicit human decisions.
            current = resolution_is_current(resolution)
            if current:
                continue
            status = "open"
        # iter047B2 M3: 'expired' always blocks; anything NOT explicitly
        # resolved/expired (open, blank, or an unknown word like 'deferred', or
        # wrong-case 'Open') is treated as still-open and blocks once past TTL —
        # fail-closed, so a non-standard status can't slip a must-resolve clue past.
        if status == "expired" or _overdue_by_ttl(it, current_chapter):
            out.append(it)
    return out


def overdue_must_resolve(
    current_chapter: int, *, include_boundary: bool = False
) -> List[Dict[str, Any]]:
    """Pure read: GATING must_resolve items overdue at ``current_chapter``.

    Includes both still-``open`` items past their TTL and already-``expired``
    items (a gc'd item keeps blocking until ``resolve``d). ``[]`` when no/empty
    registry.

    iter077 P0-1: source-boundary seeds (``planted_chapter <= 0``) are excluded
    unless ``include_boundary=True`` — see module docstring. Use
    ``boundary_overdue_must_resolve`` for the advisory (non-gating) list.
    """

    return [
        it
        for it in _overdue_must_resolve_items(current_chapter)
        if include_boundary or not is_boundary_item(it)
    ]


def boundary_overdue_must_resolve(current_chapter: int) -> List[Dict[str, Any]]:
    """Advisory read: overdue must_resolve items that are source-boundary seeds.

    These do NOT gate write-readiness (iter077 P0-1); callers surface them as
    warnings so a human can resolve/gc them or re-arm the gate per item by
    setting a positive ``planted_chapter``.
    """

    return [it for it in _overdue_must_resolve_items(current_chapter) if is_boundary_item(it)]


def gc(current_chapter: int) -> Dict[str, Any]:
    """Mark overdue 'open' items 'expired'; persist only if anything changed."""

    data = load_registry()
    expired: List[str] = []
    for it in data.get("items", []):
        if (
            isinstance(it, dict)
            and str(it.get("status") or "").strip().lower() in ("open", "")
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


def confirm_resolution(item_id: str, chapter: int, evidence: str, *, confirm: bool = False) -> Dict[str, Any]:
    """Human-confirmed payoff supported by an exact, strictly reviewed draft."""
    from .chapter_status import chapter_status
    from .writer import _load_chapter_plan, _chapter_plan_item, _run_context
    from .story_memory import _read, _write
    from .utils import sha256_text
    from . import workspace_files
    if not confirm or type(chapter) is not int or chapter < 1 or not evidence.strip() or len(evidence) > 2000:
        raise ValueError('foreshadowing_confirmation_required')
    drafts = paths.drafts_dir()
    plan = _load_chapter_plan()
    if not plan:
        raise ValueError('chapter_plan_missing')
    expected = _run_context(_chapter_plan_item(plan, chapter), chapter_no=chapter)
    status = chapter_status(chapter, drafts, validate_context=True, require_external_review=True, expected_context=expected)
    if not status.get('approved'):
        raise ValueError('foreshadowing_requires_current_approved_chapter')
    if not paths.workspace_name():
        raise ValueError('foreshadowing_requires_named_workspace')
    draft = workspace_files.read_text(paths.workspace_name(), f'outputs/drafts/chapter_{chapter:02d}.md', max_bytes=4*1024*1024)
    if evidence not in draft:
        raise ValueError('foreshadowing_evidence_not_in_draft')
    data = _read(_registry_path(), None)
    if not isinstance(data, dict) or not isinstance(data.get('items'), list):
        raise ValueError('foreshadowing_registry_invalid')
    item = next((it for it in data['items'] if isinstance(it,dict) and it.get('id') == item_id), None)
    if item is None:
        raise ValueError('foreshadowing_item_missing')
    meta = _read(drafts/f'chapter_{chapter:02d}.meta.json', {})
    review = _read(drafts.parent/'reviews'/f'chapter_{chapter:02d}.review.json', {})
    digest = sha256_text(draft)
    if meta.get('draft_sha256') != digest or review.get('draft_sha256') != digest or meta.get('story_memory_invalidated'):
        raise ValueError('foreshadowing_draft_changed')
    item['status'] = 'resolved'
    item['resolution'] = {'source':'human_confirmed', 'chapter':chapter, 'draft_sha256':digest,
                          'evidence':evidence, 'review_sha256':sha256_text(json.dumps(review,sort_keys=True,ensure_ascii=False))}
    _write(_registry_path(), data)
    return {'id':item_id, 'status':'resolved', 'chapter':chapter, 'draft_sha256':digest}


def configure_ttl(item_id: str, ttl: int, *, confirm: bool = False) -> Dict[str, Any]:
    from .story_memory import _read, _write
    if not confirm or type(ttl) is not int or not 1 <= ttl <= 10000 or not paths.workspace_name():
        raise ValueError('foreshadowing_ttl_confirmation_required')
    data = _read(_registry_path(), None)
    if not isinstance(data, dict) or not isinstance(data.get('items'), list):
        raise ValueError('foreshadowing_registry_invalid')
    item = next((it for it in data['items'] if isinstance(it,dict) and it.get('id') == item_id), None)
    if item is None:
        raise ValueError('foreshadowing_item_missing')
    item['ttl'] = ttl
    if item.get('status') == 'expired':
        item['status'] = 'open'
    _write(_registry_path(),data)
    return {'id':item_id, 'ttl':ttl, 'status':item.get('status')}


def resolution_is_current(resolution: Dict[str, Any]) -> bool:
    from .chapter_status import chapter_status
    from .writer import _load_chapter_plan, _chapter_plan_item, _run_context
    from .story_memory import _read
    from . import workspace_files
    from .utils import sha256_text
    try:
        chapter = resolution.get('chapter')
        if type(chapter) is not int or chapter < 1 or not paths.workspace_name():
            return False
        drafts = paths.drafts_dir()
        meta = _read(drafts/f'chapter_{chapter:02d}.meta.json', {})
        review = _read(drafts.parent/'reviews'/f'chapter_{chapter:02d}.review.json', {})
        plan = _load_chapter_plan()
        if not plan:
            return False
        expected = _run_context(_chapter_plan_item(plan,chapter),chapter_no=chapter)
        current = chapter_status(chapter,drafts,validate_context=True,require_external_review=True,expected_context=expected)
        draft = workspace_files.read_text(paths.workspace_name(),f'outputs/drafts/chapter_{chapter:02d}.md',max_bytes=4*1024*1024)
        return (bool(current.get('approved')) and not meta.get('story_memory_invalidated')
            and sha256_text(draft) == resolution.get('draft_sha256')
            and sha256_text(json.dumps(review,sort_keys=True,ensure_ascii=False)) == resolution.get('review_sha256'))
    except (OSError,ValueError,TypeError,KeyError):
        return False
