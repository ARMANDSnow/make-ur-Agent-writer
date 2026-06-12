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
from .utils import read_json, read_json_optional, sha256_data, sha256_text, write_json


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


def enforce_consistency(
    *,
    require_start_point: bool = True,
    plan_data: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """iter 051b (F6, carry-over from the iter 027 code review): the single
    entry-point gate for start-point consistency. Before this, the same
    checks were scattered across shell + planner + writer layers
    (``plot_planner.generate_chapter_plan`` raised its own ValueError,
    ``book_runner.check_write_readiness`` / ``_plan_metadata_failures``
    re-implemented the comparisons inline) — drift between the copies was
    only a matter of time.

    Returns a list of failure codes (empty = consistent). Two check families:

    * presence (``plan_data is None``): ``require_start_point`` and no start
      configured → ``["start_point_missing"]``.
    * plan agreement (``plan_data`` = raw chapter_plan.json dict): the plan's
      stored ``start_chapter_id`` / ``start_point_fingerprint`` must agree
      with the CURRENT workspace start point. Codes are byte-identical to the
      pre-051b inline block in ``book_runner._plan_metadata_failures``:
      ``start_chapter_id_missing`` / ``start_chapter_id_mismatch`` /
      ``start_point_fingerprint_missing`` / ``start_point_fingerprint_mismatch``.
      Mismatch codes only fire when the workspace side is non-empty (a
      missing current start can't contradict a stored one — fail-open, same
      as before). ``start_point_missing`` is deliberately NOT emitted in this
      mode, preserving each caller's existing output verbatim.

    Callers map codes onto their own surfaces (ValueError in plot_planner,
    blocker strings in book_runner) so behavior stays byte-identical.
    ``require_start_point=False`` short-circuits to ``[]`` (greenfield runs
    have no start point by design). Spoiler-filter consumers
    (``is_after_start`` in entities/manual_facts/kb_view) are a different
    concern and intentionally untouched.
    """
    failures: List[str] = []
    if not require_start_point:
        return failures
    current_start = get_start_chapter_id() or ""
    if plan_data is None:
        if not current_start:
            failures.append("start_point_missing")
        return failures
    current_fp = start_point_fingerprint()
    if not plan_data.get("start_chapter_id"):
        failures.append("start_chapter_id_missing")
    elif current_start and str(plan_data.get("start_chapter_id")) != current_start:
        failures.append("start_chapter_id_mismatch")
    if not plan_data.get("start_point_fingerprint"):
        failures.append("start_point_fingerprint_missing")
    elif current_fp and str(plan_data.get("start_point_fingerprint")) != current_fp:
        failures.append("start_point_fingerprint_mismatch")
    return failures


#: iter 053a — the warn-level (fail-open) code emitted when debate decisions
#: carry no provenance metadata at all: legacy pre-053 workspaces AND the
#: "decisions.json missing but outline.md present" branch (callers pass the
#: read_json_optional default ``{}``). Everything else the gate returns is a
#: hard mismatch. 审查 A2: both fail-open paths route through this ONE code so
#: deleting decisions.json can never bypass a hard block silently — it lands
#: in the same warn lane as legacy workspaces, with the same留痕.
OUTLINE_METADATA_MISSING = "outline_start_metadata_missing"


def outline_consistency_failures(
    decisions: Optional[Dict[str, Any]],
    *,
    outline_text: Optional[str] = None,
) -> List[str]:
    """iter 053a: F6's fingerprint philosophy extended to debate intermediates.

    ``decisions`` is the raw decisions.json dict (``{}`` / ``None`` when the
    file is absent). Returns failure codes (empty = consistent):

    * ``outline_start_metadata_missing`` — no provenance metadata at all
      (legacy workspace or missing decisions.json). Warn-level by contract:
      callers print/log and proceed, 先例 kb_view 047b fail-open.
    * ``outline_start_chapter_id_mismatch`` — outline was debated under a
      different start chapter (the 052 accident: 起点已真正变更). Hard.
    * ``outline_start_point_fingerprint_mismatch`` — start chapter id agrees
      (or wasn't recorded) but the fingerprint moved — typically re-split /
      normalize line drift rather than a true start change. Hard, but the
      caller's error message offers ``--allow-stale-outline`` for the
      line-drift case (审查 A7: 误报不能把用户训练成习惯性逃生).
    * ``outline_content_mismatch`` — ``outline_sha256`` recorded in decisions
      doesn't hash the on-disk outline.md: hand-edited outline or a write
      interrupted between the two files. Hard (审查 A2).

    Mismatch codes only fire when the CURRENT workspace side is non-empty —
    a missing current start can't contradict a stored one (fail-open, same
    convention as :func:`enforce_consistency`).
    """
    if not isinstance(decisions, dict):
        return [OUTLINE_METADATA_MISSING]
    has_metadata = any(
        key in decisions
        for key in ("start_chapter_id", "start_point_fingerprint", "outline_sha256")
    )
    if not has_metadata:
        return [OUTLINE_METADATA_MISSING]
    failures: List[str] = []
    current_start = get_start_chapter_id() or ""
    current_fp = start_point_fingerprint()
    stored_start = str(decisions.get("start_chapter_id") or "")
    stored_fp = str(decisions.get("start_point_fingerprint") or "")
    if current_start and stored_start != current_start:
        failures.append("outline_start_chapter_id_mismatch")
    if current_fp and stored_fp != current_fp:
        failures.append("outline_start_point_fingerprint_mismatch")
    stored_outline_sha = str(decisions.get("outline_sha256") or "")
    if (
        stored_outline_sha
        and outline_text is not None
        and sha256_text(outline_text) != stored_outline_sha
    ):
        failures.append("outline_content_mismatch")
    return failures


def extraction_coverage_failures(k: int = 10) -> List[str]:
    """iter 053g（053c 实跑根因③的机制化护栏，warn 级）：起点前最近 K 章
    （含起点章）必须有提取产物。

    extracted_jsons → KB(compress) → entity_graph(bootstrap) 整条派生链都
    以提取层为底座；提取没跟上起点时，评审的"当前活跃关系"会锚死在旧
    状态。longzu 实测：全书 110 章只提取了前 3 章、起点在第 ~100 章——
    评审按"入学初期"硬尺连拒贴起点的正确稿件（052 九稿全灭与 6/5"听力
    考试假基线"的共同根因）。

    返回缺提取的 chapter_id 列表（空 = 覆盖完好）。无起点 / manifest 缺失
    fail-open 返回空（greenfield 无源书提取概念，铁律④）。
    """
    start = get_start_chapter_id()
    if not start:
        return []
    idx = _index_of(start)
    if idx is None:
        return []
    window = _load_manifest()[max(0, idx - max(1, int(k)) + 1) : idx + 1]
    extracted = paths.extracted_dir()
    missing: List[str] = []
    for entry in window:
        chapter_id = str(entry.get("chapter_id") or "")
        if chapter_id and not (extracted / f"{chapter_id}.json").exists():
            missing.append(chapter_id)
    return missing


def plan_outline_lineage_failures(
    plan_data: Optional[Dict[str, Any]],
    *,
    outline_text: Optional[str],
) -> List[str]:
    """iter 053a (审查 A1): plan↔outline lineage — warn-level by contract.

    ``generate_chapter_plan`` records the sha256 of the outline it actually
    consumed into ``chapter_plan.json["outline_sha256"]``. After a debate
    rerun the on-disk outline changes, the old plan silently goes stale, and
    F6 alone can't see it (起点没变，plan 的起点指纹照样全绿——052 的毒
    chapter_plan.json 即盘面实证). This check closes that gap one layer up.

    Returns ``["plan_outline_lineage_mismatch"]`` or ``[]``. Plans without a
    recorded hash (pre-053 legacy) and missing outline text both fail-open —
    deliberately warn-level起步: callers surface it (readiness warn lane /
    driver decision), they do NOT hard-block on it.
    """
    if not isinstance(plan_data, dict):
        return []
    stored = str(plan_data.get("outline_sha256") or "")
    if not stored or outline_text is None:
        return []
    if sha256_text(outline_text) != stored:
        return ["plan_outline_lineage_mismatch"]
    return []


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
    k: int = 3, limit_chars: int = 24000, *, include_start: bool = False
) -> str:
    """Compact text block of K pre-start chapters for ``auto_bootstrap``
    to use as anchor sampling context.

    Each chapter rendered as ``### <chapter_id> — <title>\\n\\n<body[:6000]>``,
    separated by ``\\n\\n---\\n\\n``, total truncated to ``limit_chars``.

    Returns empty string when no start set / no chapters available — caller
    must fall back to the iter 020 ``_recent_extractions_context`` path.

    iter 053f (053c 实跑发现): ``include_start=True`` 把采样窗口改为
    **以起点章收尾的 K 章**（(start-k, start] 闭区间）——续写的交接点是
    起点章自己的结尾，不是它前一章的结尾。exclusive 旧窗口在"起点章是
    时间跳跃的尾声"时是系统性毒源：longzu 的 ch024 尾声距 ch021-023 的
    高潮隔了三个月，anchor 重新生成多少次都锚在机库倒计时。默认 False
    保持全部存量调用方（writer 风格锚 / planner 方位校验 / review_source）
    逐字节不变（铁律④）。
    """
    if include_start:
        start = get_start_chapter_id()
        if not start:
            return ""
        start_idx = _index_of(start)
        if start_idx is None:
            return ""
        window = max(0, start_idx - max(0, int(k)) + 1)
        chapters = _load_manifest()[window : start_idx + 1]
    else:
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
