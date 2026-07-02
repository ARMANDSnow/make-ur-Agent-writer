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


def _safe_stat_size(md_path: Path, containment_root: Path) -> Optional[int]:
    """文件字节数；缺失/越界（含 symlink 逃逸）返回 None。

    iter076（codex 审查 iter074 #6 + 低风险 symlink 项）：版本列举原来为算字数把
    **每个版本全文读进内存**，且 ``read_text``/``exists`` 都跟随 symlink——快照目录里
    一个指向外部的 symlink 能借 /versions 探测任意文件的存在性与长度。改为先
    resolve + 收容校验（与 ``resolve_version_text`` 同款闸），再 ``stat`` 取字节数，
    全程零正文 IO。"""
    try:
        resolved = md_path.resolve()
        resolved.relative_to(containment_root.resolve())
        if not resolved.is_file():
            return None
        return resolved.stat().st_size
    except (OSError, ValueError):
        return None


def _version_entry(
    md_path: Path,
    meta: Any,
    *,
    version_id: str,
    label: str,
    containment_root: Path,
    reason: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    size = _safe_stat_size(md_path, containment_root)
    if size is None:
        return None
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
        # iter076：``chars``（全文 len）→ ``size_bytes``（stat）。原字段前端/测试
        # 零消费（已核），换成零 IO 的字节数。
        "size_bytes": size,
        "exists": True,
    }


def list_chapter_versions(drafts_dir: Path, chapter_no: int) -> List[Dict[str, Any]]:
    """Enumerate versions of one chapter, current draft first then snapshots
    newest→oldest. Missing snapshot dir / bad meta degrade gracefully to []
    or empty fields (mock-friendly, iron rule ④)."""

    drafts_dir = Path(drafts_dir)
    versions: List[Dict[str, Any]] = []

    current_md = drafts_dir / _chapter_md_name(chapter_no)
    current_meta = read_json_optional(drafts_dir / _chapter_meta_name(chapter_no), {})
    current_entry = _version_entry(
        current_md,
        current_meta,
        version_id=CURRENT_VERSION_ID,
        label="当前草稿",
        containment_root=drafts_dir,
    )
    if current_entry is not None:
        versions.append(current_entry)

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
            meta = read_json_optional(entry / _chapter_meta_name(chapter_no), {})
            reason_obj = read_json_optional(entry / "archive_reason.json", {})
            reason = reason_obj.get("reason") if isinstance(reason_obj, dict) else None
            # 缺 md / symlink 逃逸收容 → None → 该版本不进列表（也就永远进不了
            # valid_ids，diff 端点在触盘前即 400）。
            snap_entry = _version_entry(
                md,
                meta,
                version_id=stamp,
                label=f"重试快照 {_format_stamp(stamp)}",
                containment_root=snap_root,
                reason=reason,
            )
            if snap_entry is not None:
                snaps.append((stamp, snap_entry))
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
        md = drafts_dir / _chapter_md_name(chapter_no)
        # iter076（审查 B L6）：current 分支补与 snapshot 分支对称的收容复检——
        # 关掉 list→resolve 之间 symlink 换链的 check-vs-use 窗口。
        try:
            md.resolve().relative_to(drafts_dir.resolve())
        except (OSError, ValueError):
            return None
        return _read_text(md)
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


# iter076（codex 审查 iter074 #6）：difflib.unified_diff 是 O(行数²) 级 DP，无上限
# 会被两份超大文本占满 CPU/内存。单章正常 4-10k 字，上限取得很宽裕；超限时不跑
# difflib，只回 meta 说明行 + truncated 标记（前端把 meta 行当普通 diff 行渲染，
# 无需改前端即可展示）。
MAX_DIFF_INPUT_CHARS = 500_000   # 每侧输入字符上限
MAX_DIFF_LINES = 5_000           # 输出 diff 行数上限（截断后追加说明行）


def compute_diff(
    old_text: Optional[str],
    new_text: Optional[str],
    *,
    old_label: str = "",
    new_label: str = "",
    context: int = 3,
) -> Dict[str, Any]:
    """Unified diff between two chapter texts as classified lines for the UI."""

    old_raw = old_text or ""
    new_raw = new_text or ""
    if len(old_raw) > MAX_DIFF_INPUT_CHARS or len(new_raw) > MAX_DIFF_INPUT_CHARS:
        note = (
            f"文本过大（{len(old_raw)} / {len(new_raw)} 字符，上限每侧 "
            f"{MAX_DIFF_INPUT_CHARS}），已跳过逐行对比。"
        )
        return {
            "identical": old_raw == new_raw,
            "diff_lines": [{"type": "meta", "text": note}],
            "truncated": True,
        }
    old_lines = old_raw.splitlines(keepends=True)
    new_lines = new_raw.splitlines(keepends=True)
    raw = list(
        difflib.unified_diff(
            old_lines, new_lines, fromfile=old_label, tofile=new_label, n=context
        )
    )
    truncated = len(raw) > MAX_DIFF_LINES
    if truncated:
        raw = raw[:MAX_DIFF_LINES]
    diff_lines = [{"type": _classify(line), "text": line.rstrip("\n")} for line in raw]
    if truncated:
        diff_lines.append(
            {"type": "meta", "text": f"… diff 过长，仅显示前 {MAX_DIFF_LINES} 行。"}
        )
    return {"identical": not raw, "diff_lines": diff_lines, "truncated": truncated}
