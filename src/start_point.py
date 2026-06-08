"""Start-point management — iter 021.

Lets users specify where in the source material continuation should
begin. Before iter 021, the bootstrap pipeline always sampled the first
few extracted chapters (via `auto_bootstrap._recent_extractions_context`),
silently locking the writer to "before book 1, ch001". After iter 021,
users can call ``set_start_point("longzu_4")`` or
``set_start_point("longzu_3_3_ch020")`` to indicate "continue from the
end of Book 3 Part 3" / "from a specific chapter".

API contract:

* ``get_start_chapter_id() -> Optional[str]``
    Resolved chapter_id (None if no start point set).
* ``set_start_point(name) -> None``
    Persist a chapter_id or volume_id selection.
* ``clear_start_point() -> None``
    Remove the start point file.
* ``is_after_start(chapter_id) -> bool``
    True iff chapter_id is strictly after the current start.
* ``chapters_before_start(k=3) -> list[dict]``
    Manifest entries for the K chapters immediately before start (exclusive
    of start itself).
* ``load_chapter_text(chapter_id) -> str``
    Read source_file [start_line:end_line] for the given chapter.
* ``format_chapters_before_start_for_anchor(k=3, limit_chars=24000) -> str``
    Compact text block for use by auto_bootstrap as anchor context.

All functions are workspace-aware via ``src.paths``. Backwards-compatible:
when ``start_chapter.json`` doesn't exist, every function degrades
gracefully (None / False / [] / "").
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from . import paths
from .utils import read_json, read_json_optional, sha256_data, write_json


_START_FILE = "start_chapter.json"


def _start_path() -> Path:
    return paths.manual_overrides_dir() / _START_FILE


def _load_manifest() -> List[Dict[str, Any]]:
    """Return chapter_manifest entries in canonical order. Defensive against
    both list-form and dict-wrapped-form manifests."""
    p = paths.chapter_manifest_path()
    if not p.exists():
        return []
    # iter047B2 H1b: a corrupt manifest must fail-open (read_json would raise
    # JSONDecodeError, crashing every start-safe KB read that resolves order).
    data = read_json_optional(p, [])
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return data.get("chapters", data.get("entries", []))
    return []


def _resolve_chapter_id_from_volume(volume_id: str) -> Optional[str]:
    """Take the last chapter_id of the given volume from manifest order."""
    chapters_in_vol = [c for c in _load_manifest() if c.get("volume_id") == volume_id]
    if not chapters_in_vol:
        return None
    return chapters_in_vol[-1].get("chapter_id")


def set_start_point(name: str) -> None:
    """Persist a start point. ``name`` may be a chapter_id or volume_id.

    Raises ``ValueError`` if the name matches neither in chapter_manifest.
    The check is intentional: typos like ``longzu_3_2_ch20`` (vs ch020)
    would otherwise silently fall through to "no start set" and confuse
    users.
    """
    name = (name or "").strip()
    if not name:
        raise ValueError("start point name must not be empty")
    manifest = _load_manifest()
    if not manifest:
        raise ValueError(
            "chapter_manifest.json missing or empty; run `normalize + split` first."
        )
    chapter_ids = {c.get("chapter_id") for c in manifest}
    volume_ids = {c.get("volume_id") for c in manifest}

    if name in chapter_ids:
        data: Dict[str, str] = {"start_chapter_id": name}
    elif name in volume_ids:
        data = {"start_volume_id": name}
    else:
        raise ValueError(
            f"{name!r} matches neither chapter_id nor volume_id in "
            f"chapter_manifest. Inspect "
            f"{paths.chapter_manifest_path()} to see valid options."
        )

    target = _start_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    write_json(target, data)


def clear_start_point() -> None:
    """Remove the start_chapter.json file. Restores iter 020 default behavior
    where bootstrap samples from the first extracted chapters."""
    p = _start_path()
    if p.exists():
        p.unlink()


def get_start_chapter_id() -> Optional[str]:
    """Return the resolved chapter_id, or ``None`` if no start point set.

    If the stored data is a ``start_volume_id``, resolves to the last
    chapter_id of that volume (so "after Book 3" becomes "the last
    chapter of Book 3").
    """
    p = _start_path()
    if not p.exists():
        return None
    # iter047B2 H1b: a corrupt start_chapter.json must fail-open (treat as no
    # start point) rather than raise into kb_view/writer/planner.
    data = read_json_optional(p, {})
    if not isinstance(data, dict):
        return None
    if "start_chapter_id" in data and data["start_chapter_id"]:
        return data["start_chapter_id"]
    if "start_volume_id" in data and data["start_volume_id"]:
        return _resolve_chapter_id_from_volume(data["start_volume_id"])
    return None


def get_start_point_metadata() -> Dict[str, Any]:
    """Return stable metadata for the current continuation start point.

    This intentionally includes only fields that identify the operator's
    selected source position. Volatile manifest fields are left out so the
    fingerprint changes on meaningful start/source changes, not on unrelated
    manifest decoration.
    """

    start = get_start_chapter_id()
    if not start:
        return {
            "schema_version": 1,
            "has_start_point": False,
            "start_chapter_id": "",
        }
    manifest_item: Dict[str, Any] = {}
    for entry in _load_manifest():
        if entry.get("chapter_id") == start:
            manifest_item = entry
            break
    source_file = str(manifest_item.get("source_file", ""))
    source_name = Path(source_file).name if source_file else ""
    return {
        "schema_version": 1,
        "has_start_point": True,
        "start_chapter_id": start,
        "manifest": {
            "chapter_id": manifest_item.get("chapter_id", start),
            "volume_id": manifest_item.get("volume_id", ""),
            "title": manifest_item.get("title", ""),
            "index": manifest_item.get("index", manifest_item.get("chapter_index", "")),
            "source_file": source_name,
            "start_line": manifest_item.get("start_line", ""),
            "end_line": manifest_item.get("end_line", ""),
        },
    }


def start_point_fingerprint() -> str:
    """Stable sha256 over :func:`get_start_point_metadata`.

    Empty string means no start point is configured, preserving legacy callers
    while letting strict production runners require the value.
    """

    metadata = get_start_point_metadata()
    if not metadata.get("has_start_point"):
        return ""
    return sha256_data(metadata)


def _index_of(chapter_id: str) -> Optional[int]:
    """Return the manifest index of chapter_id, or ``None`` if not found."""
    for i, c in enumerate(_load_manifest()):
        if c.get("chapter_id") == chapter_id:
            return i
    return None


def is_after_start(chapter_id: str) -> bool:
    """True iff chapter_id is **strictly** after the current start in
    manifest order.

    Returns False if no start set, or if either chapter_id isn't in the
    manifest, or if chapter_id is the start itself / before it. Used by
    spoiler-filter callers in ``src.manual_facts`` and ``src.entities``.
    """
    start = get_start_chapter_id()
    if not start:
        return False
    start_idx = _index_of(start)
    if start_idx is None:
        return False
    ch_idx = _index_of(chapter_id)
    if ch_idx is None:
        return False
    return ch_idx > start_idx


def chapters_before_start(k: int = 3) -> List[Dict[str, Any]]:
    """Return the K manifest entries immediately BEFORE start (exclusive of
    start). Empty list if no start set or start is at manifest position 0.

    The intent: feed K chapters of authentic source-novel text to writer
    and bootstrap_continuation_anchor as a "style + detail anchor". Three
    chapters is the iter 021 default — small enough to fit deepseek's
    128K context window after the existing ~30K prompt overhead.
    """
    if k <= 0:
        return []
    start = get_start_chapter_id()
    if not start:
        return []
    manifest = _load_manifest()
    start_idx = _index_of(start)
    if start_idx is None or start_idx == 0:
        return []
    start_window = max(0, start_idx - k)
    return manifest[start_window:start_idx]


def load_chapter_text(chapter_id: str) -> str:
    """Return raw text for chapter, slicing source_file by start_line:end_line.

    Returns empty string if chapter_id not in manifest, source_file missing,
    or read fails. ``start_line`` and ``end_line`` in the manifest are
    1-indexed inclusive (as produced by ``chapter_splitter``).
    """
    entry: Optional[Dict[str, Any]] = None
    for c in _load_manifest():
        if c.get("chapter_id") == chapter_id:
            entry = c
            break
    if entry is None:
        return ""
    src = Path(entry.get("source_file", ""))
    if not src.is_absolute():
        src = paths.workspace_root() / src
    if not src.exists():
        return ""
    try:
        with src.open(encoding="utf-8") as f:
            all_lines = f.readlines()
    except (OSError, UnicodeDecodeError):
        return ""
    # 1-based inclusive → 0-based slice
    start = max(1, int(entry.get("start_line", 1))) - 1
    end = max(start, int(entry.get("end_line", start + 1)))
    return "".join(all_lines[start:end])


def format_chapters_before_start_for_anchor(
    k: int = 3, limit_chars: int = 24000
) -> str:
    """Compact text block of K pre-start chapters for ``auto_bootstrap``
    to use as anchor sampling context.

    Each chapter rendered as ``### <chapter_id> — <title>\\n\\n<body[:6000]>``,
    separated by ``\\n\\n---\\n\\n``, total truncated to ``limit_chars``.

    Returns empty string when no start set / no chapters available — caller
    must fall back to the iter 020 ``_recent_extractions_context`` path.
    """
    chapters = chapters_before_start(k=k)
    if not chapters:
        return ""
    parts = []
    for ch in chapters:
        body = load_chapter_text(ch.get("chapter_id", ""))[:6000]
        parts.append(
            f"### {ch.get('chapter_id')} — {ch.get('title', '')}\n\n{body}"
        )
    out = "\n\n---\n\n".join(parts)
    return out[:limit_chars]
