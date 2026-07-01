"""Chapter version diff (iter 074).

Reader/editor-facing quality tooling: enumerate a chapter's on-disk versions
(the current draft plus every retry snapshot archived by
``book_runner._archive_chapter_artifacts``) and compute a unified diff between
any two of them.

Pure functions only — no HTTP, no workspace context — so the web handlers in
``routes.py`` stay thin adapters and this module is unit-testable in isolation.

Path-traversal is fail-closed by construction: a version id is either the
literal ``"current"`` or a snapshot timestamp matching ``\\d{8}_\\d{6}``. No
other value can name a directory, so ``../`` and absolute paths never reach the
filesystem. ``resolve_version_text`` additionally re-checks the resolved path
stays inside ``<drafts>/snapshots`` as defense-in-depth.
"""

from __future__ import annotations

import difflib
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..utils import read_json_optional

# Snapshot dirs are named ``stale_chapter_<NN>_<YYYYMMDD_HHMMSS>`` by
# book_runner._archive_chapter_artifacts. The stamp is the ONLY accepted
# version id besides CURRENT_VERSION_ID — this regex is the fail-closed gate.
_STAMP_RE = re.compile(r"^\d{8}_\d{6}$")
CURRENT_VERSION_ID = "current"


def _chapter_md_name(chapter_no: int) -> str:
    return f"chapter_{chapter_no:02d}.md"


def _chapter_meta_name(chapter_no: int) -> str:
    return f"chapter_{chapter_no:02d}.meta.json"


def _snapshot_prefix(chapter_no: int) -> str:
    return f"stale_chapter_{chapter_no:02d}_"


def _snapshot_dir(drafts_dir: Path, chapter_no: int, stamp: str) -> Path:
    return drafts_dir / "snapshots" / f"{_snapshot_prefix(chapter_no)}{stamp}"


def _read_text(path: Path) -> Optional[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _format_stamp(stamp: str) -> str:
    """``20260612_172600`` -> ``2026-06-12 17:26:00`` (caller guarantees shape)."""
    day, clock = stamp.split("_")
    return f"{day[0:4]}-{day[4:6]}-{day[6:8]} {clock[0:2]}:{clock[2:4]}:{clock[4:6]}"


def _version_entry(
    md_path: Path,
    meta: Any,
    *,
    version_id: str,
    label: str,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    text = _read_text(md_path)
    if not isinstance(meta, dict):
        meta = {}
    return {
        "id": version_id,
        "label": label,
        "reason": reason,
        "verdict": meta.get("verdict"),
        "rewrite_count": meta.get("rewrite_count"),
        "edited": bool(meta.get("edited")),
        "edited_at": meta.get("edited_at"),
        "chars": len(text) if text is not None else 0,
        "exists": text is not None,
    }


def list_chapter_versions(drafts_dir: Path, chapter_no: int) -> List[Dict[str, Any]]:
    """Enumerate versions of one chapter, current draft first then snapshots
    newest→oldest. Missing snapshot dir / bad meta degrade gracefully to []
    or empty fields (mock-friendly, iron rule ④)."""

    drafts_dir = Path(drafts_dir)
    versions: List[Dict[str, Any]] = []

    current_md = drafts_dir / _chapter_md_name(chapter_no)
    if current_md.exists():
        meta = read_json_optional(drafts_dir / _chapter_meta_name(chapter_no), {})
        versions.append(
            _version_entry(current_md, meta, version_id=CURRENT_VERSION_ID, label="当前草稿")
        )

    snap_root = drafts_dir / "snapshots"
    snaps: List[tuple] = []
    if snap_root.is_dir():
        prefix = _snapshot_prefix(chapter_no)
        for entry in snap_root.glob(f"{prefix}*"):
            if not entry.is_dir():
                continue
            stamp = entry.name[len(prefix):]
            if not _STAMP_RE.match(stamp):
                continue
            md = entry / _chapter_md_name(chapter_no)
            if not md.exists():
                continue
            meta = read_json_optional(entry / _chapter_meta_name(chapter_no), {})
            reason_obj = read_json_optional(entry / "archive_reason.json", {})
            reason = reason_obj.get("reason") if isinstance(reason_obj, dict) else None
            snaps.append(
                (
                    stamp,
                    _version_entry(
                        md,
                        meta,
                        version_id=stamp,
                        label=f"重试快照 {_format_stamp(stamp)}",
                        reason=reason,
                    ),
                )
            )
        snaps.sort(key=lambda item: item[0], reverse=True)  # newest first

    versions.extend(entry for _, entry in snaps)
    return versions


def resolve_version_text(
    drafts_dir: Path, chapter_no: int, version_id: str
) -> Optional[str]:
    """Return the chapter text for ``version_id`` or None (fail-closed).

    ``version_id`` must be CURRENT_VERSION_ID or a clean ``\\d{8}_\\d{6}`` stamp;
    anything else returns None without touching disk."""

    drafts_dir = Path(drafts_dir)
    if version_id == CURRENT_VERSION_ID:
        return _read_text(drafts_dir / _chapter_md_name(chapter_no))
    if not _STAMP_RE.match(version_id or ""):
        return None
    md = _snapshot_dir(drafts_dir, chapter_no, version_id) / _chapter_md_name(chapter_no)
    # Defense-in-depth: the resolved file must stay under <drafts>/snapshots.
    try:
        md.resolve().relative_to((drafts_dir / "snapshots").resolve())
    except ValueError:
        return None
    if not md.exists():
        return None
    return _read_text(md)


def _classify(line: str) -> str:
    if line.startswith("+++") or line.startswith("---"):
        return "meta"
    if line.startswith("@@"):
        return "hunk"
    if line.startswith("+"):
        return "add"
    if line.startswith("-"):
        return "del"
    return "ctx"


def compute_diff(
    old_text: Optional[str],
    new_text: Optional[str],
    *,
    old_label: str = "",
    new_label: str = "",
    context: int = 3,
) -> Dict[str, Any]:
    """Unified diff between two chapter texts as classified lines for the UI."""

    old_lines = (old_text or "").splitlines(keepends=True)
    new_lines = (new_text or "").splitlines(keepends=True)
    raw = list(
        difflib.unified_diff(
            old_lines, new_lines, fromfile=old_label, tofile=new_label, n=context
        )
    )
    diff_lines = [{"type": _classify(line), "text": line.rstrip("\n")} for line in raw]
    return {"identical": not raw, "diff_lines": diff_lines}
