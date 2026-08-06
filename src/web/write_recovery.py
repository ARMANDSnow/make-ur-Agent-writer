"""Fail-closed state inspection for single-chapter write recovery.

The recovery token is deliberately a digest, not a serialized snapshot.  It
binds the operator's confirmation to the exact current draft generation while
keeping novel text, review prose, paths, and provider details out of HTTP and
job-history projections.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from typing import Any, Dict, Optional

from .. import paths, workspace_files
from . import workspace_meta


_START_REL = "data/manual_overrides/start_chapter.json"
_MANIFEST_REL = "data/chapter_manifest.json"
_EXPANSION_REL = "data/premise_expansion.json"
_KB_REL = "data/knowledge_base/global_knowledge.md"
_OUTLINE_REL = "outputs/debate/outline.md"
_PLAN_REL = "outputs/debate/chapter_plan.json"
_START_MAX = 256 * 1024
_MANIFEST_MAX = 4 * 1024 * 1024
_EXPANSION_MAX = 2 * 1024 * 1024
_KB_MAX = 2 * 1024 * 1024
_OUTLINE_MAX = 4 * 1024 * 1024
_PLAN_MAX = 4 * 1024 * 1024
_DRAFT_MAX = 4 * 1024 * 1024
_JSON_MAX = 2 * 1024 * 1024
_MISSING = b"\x00iter166-missing\x00"


def _chapter_rel(chapter: int, suffix: str, *, review: bool = False) -> str:
    directory = "outputs/reviews" if review else "outputs/drafts"
    return f"{directory}/chapter_{chapter:02d}{suffix}"


def _read_optional(workspace: str, relative: str, *, max_bytes: int) -> Optional[bytes]:
    try:
        return workspace_files.read_bytes(workspace, relative, max_bytes=max_bytes)
    except FileNotFoundError:
        return None


def _read_optional_artifact(
    workspace: str,
    relative: str,
    *,
    max_bytes: int,
) -> tuple[Optional[bytes], Optional[int]]:
    """Read one no-follow artifact and capture its freshness timestamp.

    ``workspace_files.read_bytes`` provides the descriptor-relative bounded
    read.  The following no-follow stat binds the same public freshness signal
    used by the workbench.  If an atomic replacement lands between the two
    operations, the mixed snapshot cannot reproduce on the POST/worker check
    and therefore fails closed.
    """

    raw = _read_optional(workspace, relative, max_bytes=max_bytes)
    if raw is None:
        return None, None
    try:
        info = os.stat(
            paths.workspace_root(workspace) / relative,
            follow_symlinks=False,
        )
    except (OSError, TypeError, ValueError) as exc:
        raise workspace_files.WorkspaceFileError("cannot inspect recovery artifact") from exc
    if not stat.S_ISREG(info.st_mode) or info.st_size != len(raw):
        raise workspace_files.WorkspaceFileError("recovery artifact changed during inspection")
    return raw, int(info.st_mtime_ns)


def _json_object(raw: Optional[bytes]) -> Optional[Dict[str, Any]]:
    if raw is None:
        return None
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _hash_part(digest: "hashlib._Hash", label: str, payload: Optional[bytes]) -> None:
    label_bytes = label.encode("utf-8")
    value = _MISSING if payload is None else payload
    digest.update(len(label_bytes).to_bytes(4, "big"))
    digest.update(label_bytes)
    digest.update(len(value).to_bytes(8, "big"))
    digest.update(value)


def _fingerprint(
    *,
    workspace: str,
    chapter: int,
    creation_mode: str,
    start_raw: Optional[bytes],
    start_mtime_ns: Optional[int],
    manifest_raw: Optional[bytes],
    resolved_start: Optional[str],
    expansion_raw: Optional[bytes],
    expansion_mtime_ns: Optional[int],
    kb_raw: Optional[bytes],
    kb_mtime_ns: Optional[int],
    outline_raw: Optional[bytes],
    outline_mtime_ns: Optional[int],
    plan_raw: Optional[bytes],
    plan_mtime_ns: Optional[int],
    draft_raw: Optional[bytes],
    meta_raw: Optional[bytes],
    review_raw: Optional[bytes],
) -> str:
    digest = hashlib.sha256()
    digest.update(b"novel-write-recovery-v1\x00")
    for label, value in (
        ("workspace", workspace.encode("utf-8")),
        ("chapter", str(chapter).encode("ascii")),
        ("creation_mode", creation_mode.encode("ascii")),
        ("start_point", start_raw),
        ("start_point_mtime_ns", _ascii_int(start_mtime_ns)),
        ("chapter_manifest", manifest_raw),
        ("resolved_start", resolved_start.encode("utf-8") if resolved_start else None),
        ("premise_expansion", expansion_raw),
        ("premise_expansion_mtime_ns", _ascii_int(expansion_mtime_ns)),
        ("knowledge_base", kb_raw),
        ("knowledge_base_mtime_ns", _ascii_int(kb_mtime_ns)),
        ("outline", outline_raw),
        ("outline_mtime_ns", _ascii_int(outline_mtime_ns)),
        ("chapter_plan", plan_raw),
        ("chapter_plan_mtime_ns", _ascii_int(plan_mtime_ns)),
        ("draft", draft_raw),
        ("meta", meta_raw),
        ("review", review_raw),
    ):
        _hash_part(digest, label, value)
    return digest.hexdigest()


def _ascii_int(value: Optional[int]) -> Optional[bytes]:
    return str(value).encode("ascii") if value is not None else None


def _review_state(review: Optional[Dict[str, Any]]) -> str:
    if review is None:
        return "missing"
    verdict = str(review.get("verdict") or "").strip().lower()
    if verdict == "approve" and review.get("needs_human_review") is not True:
        return "approved"
    if verdict == "reject":
        return "rejected"
    if verdict == "abstain" or review.get("needs_human_review") is True:
        return "needs_review"
    return "unknown"


def _plan_has_chapter(plan: Dict[str, Any], chapter: int) -> bool:
    chapters = plan.get("chapters")
    if not isinstance(chapters, list):
        return False
    for item in chapters:
        if not isinstance(item, dict):
            continue
        value = item.get("chapter_no")
        if isinstance(value, bool):
            continue
        try:
            if int(value) == chapter:
                return True
        except (TypeError, ValueError, OverflowError):
            continue
    return False


def _manifest_entries(raw: Optional[bytes]) -> Optional[list[Dict[str, Any]]]:
    value: Any
    if raw is None:
        return None
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    if isinstance(value, dict):
        value = value.get("chapters", value.get("entries"))
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        return None
    return value


def _resolve_start_target(
    start: Optional[Dict[str, Any]],
    manifest_raw: Optional[bytes],
) -> Optional[str]:
    entries = _manifest_entries(manifest_raw)
    if start is None or entries is None:
        return None
    chapter_id = start.get("start_chapter_id")
    volume_id = start.get("start_volume_id")
    chapter_id = chapter_id.strip() if isinstance(chapter_id, str) else ""
    volume_id = volume_id.strip() if isinstance(volume_id, str) else ""
    # Canonical selections contain exactly one discriminator.  Ambiguous or
    # hand-edited state is not safe authority for a destructive force rewrite.
    if bool(chapter_id) == bool(volume_id):
        return None
    if chapter_id:
        return chapter_id if any(item.get("chapter_id") == chapter_id for item in entries) else None
    resolved = [
        item.get("chapter_id")
        for item in entries
        if item.get("volume_id") == volume_id
        and isinstance(item.get("chapter_id"), str)
        and item.get("chapter_id").strip()
    ]
    return str(resolved[-1]) if resolved else None


def inspect_recovery_state(workspace: str, chapter: int) -> Dict[str, Any]:
    """Return a content-free recovery snapshot for one chapter.

    Unsafe descendants, malformed required JSON, stale plans, hard rejects,
    and failure-only artifacts all fail closed.  Callers may overlay live job
    state (busy/lost/general failure) without ever receiving raw novel data.
    """

    if isinstance(chapter, bool) or not isinstance(chapter, int) or not 1 <= chapter <= 9999:
        raise ValueError("chapter must be an integer between 1 and 9999")

    metadata = workspace_meta.read(workspace)
    creation_mode = str(metadata.get("creation_mode") or "continuation")
    if (
        metadata.get("type") != "novel"
        or metadata.get("_metadata_status") == "invalid"
        or creation_mode not in {"greenfield", "continuation"}
    ):
        return {
            "state": "blocked",
            "chapter": chapter,
            "draft_available": False,
            "review_state": "unknown",
            "state_fingerprint": None,
        }

    try:
        start_raw, start_mtime_ns = _read_optional_artifact(
            workspace, _START_REL, max_bytes=_START_MAX
        )
        manifest_raw = (
            _read_optional(workspace, _MANIFEST_REL, max_bytes=_MANIFEST_MAX)
            if creation_mode == "continuation"
            else None
        )
        expansion_raw, expansion_mtime_ns = _read_optional_artifact(
            workspace, _EXPANSION_REL, max_bytes=_EXPANSION_MAX
        )
        kb_raw, kb_mtime_ns = _read_optional_artifact(
            workspace, _KB_REL, max_bytes=_KB_MAX
        )
        outline_raw, outline_mtime_ns = _read_optional_artifact(
            workspace, _OUTLINE_REL, max_bytes=_OUTLINE_MAX
        )
        plan_raw, plan_mtime_ns = _read_optional_artifact(
            workspace, _PLAN_REL, max_bytes=_PLAN_MAX
        )
        draft_raw = _read_optional(
            workspace, _chapter_rel(chapter, ".md"), max_bytes=_DRAFT_MAX
        )
        meta_raw = _read_optional(
            workspace, _chapter_rel(chapter, ".meta.json"), max_bytes=_JSON_MAX
        )
        review_raw = _read_optional(
            workspace,
            _chapter_rel(chapter, ".review.json", review=True),
            max_bytes=_JSON_MAX,
        )
        failure_raw = _read_optional(
            workspace, _chapter_rel(chapter, ".failure.json"), max_bytes=_JSON_MAX
        )
    except workspace_files.WorkspaceFileError:
        return {
            "state": "blocked",
            "chapter": chapter,
            "draft_available": False,
            "review_state": "unknown",
            "state_fingerprint": None,
        }

    plan = _json_object(plan_raw)
    meta = _json_object(meta_raw)
    review = _json_object(review_raw)
    review_state = _review_state(review)
    draft_available = bool(draft_raw)
    public = {
        "state": "blocked",
        "chapter": chapter,
        "draft_available": draft_available,
        "review_state": review_state,
        "state_fingerprint": None,
    }

    # A present-but-malformed review is an unknown generation, not a missing
    # optional review.  Never archive through that ambiguity.
    if review_raw is not None and review is None:
        return public
    if not draft_available:
        public["state"] = "not_needed"
        return public
    if (
        not kb_raw
        or not outline_raw
        or plan is None
        or not _plan_has_chapter(plan, chapter)
        or not isinstance(kb_mtime_ns, int)
        or not isinstance(outline_mtime_ns, int)
        or not isinstance(plan_mtime_ns, int)
        or kb_mtime_ns <= 0
        or outline_mtime_ns < kb_mtime_ns
        or plan_mtime_ns < outline_mtime_ns
    ):
        return public
    resolved_start: Optional[str] = None
    if creation_mode == "continuation":
        start = _json_object(start_raw)
        resolved_start = _resolve_start_target(start, manifest_raw)
        if (
            resolved_start is None
            or not isinstance(start_mtime_ns, int)
            or start_mtime_ns <= 0
            or kb_mtime_ns < start_mtime_ns
        ):
            return public
    elif (
        expansion_raw is not None
        and isinstance(expansion_mtime_ns, int)
        and kb_mtime_ns < expansion_mtime_ns
    ):
        return public

    if meta is None:
        public["state"] = "needs_review"
        return public
    halted = meta.get("panel_halted")
    reason = halted.get("reason") if isinstance(halted, dict) else None
    if reason != "retry_exhausted":
        # A failure sidecar without the exact durable halt decision is the
        # legacy/failure-only case: diagnose it, never promote it to force.
        if failure_raw is not None:
            public["state"] = "blocked"
        elif reason in {"hard_reject", "external_review_reject"}:
            public["state"] = "needs_review"
        elif review_state == "approved":
            public["state"] = "not_needed"
        else:
            public["state"] = "needs_review"
        return public
    # An approved external review contradicts retry_exhausted.  Treat it as
    # state corruption/drift, never as authorization to overwrite.
    if review_state == "approved":
        return public

    public["state"] = "eligible"
    public["state_fingerprint"] = _fingerprint(
        workspace=workspace,
        chapter=chapter,
        creation_mode=creation_mode,
        start_raw=start_raw,
        start_mtime_ns=start_mtime_ns,
        manifest_raw=manifest_raw,
        resolved_start=resolved_start,
        expansion_raw=expansion_raw,
        expansion_mtime_ns=expansion_mtime_ns,
        kb_raw=kb_raw,
        kb_mtime_ns=kb_mtime_ns,
        outline_raw=outline_raw,
        outline_mtime_ns=outline_mtime_ns,
        plan_raw=plan_raw,
        plan_mtime_ns=plan_mtime_ns,
        draft_raw=draft_raw,
        meta_raw=meta_raw,
        review_raw=review_raw,
    )
    public["creation_mode"] = creation_mode
    public["requires_start_point"] = creation_mode == "continuation"
    return public


def current_fingerprint(workspace: str, chapter: int) -> Optional[str]:
    """Recompute the only fingerprint that remains eligible right now."""

    snapshot = inspect_recovery_state(workspace, chapter)
    if snapshot.get("state") != "eligible":
        return None
    value = snapshot.get("state_fingerprint")
    return str(value) if isinstance(value, str) else None
