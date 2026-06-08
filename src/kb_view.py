"""iter 047b: start-safe KB view (closes the documented gap (b)).

The compressed prose KB (``global_knowledge.md``) is built from the WHOLE
source novel, so it leaks post-start canon (endings/reveals) into
writer/planner prompts. This module renders a *start-safe* knowledge block from
the structured ``knowledge_index.json`` — every entry carries ``chapter_id``
(written by ``compressor.build_knowledge_index``) — dropping anything strictly
AFTER the continuation start point.

Fail-open: with no start point, no index, or ``respect_start_point=False``,
returns the original prose KB verbatim — so swapping a writer/planner KB read
for ``start_safe_knowledge()`` is byte-identical until a start point is set.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from . import paths
from .config import ROOT
from .utils import read_json


# Legacy constants — workspace-aware resolution below.
KB_PATH = ROOT / "data" / "knowledge_base" / "global_knowledge.md"
INDEX_PATH = ROOT / "data" / "knowledge_base" / "knowledge_index.json"


def _kb_path() -> Path:
    return paths.kb_path() if paths.workspace_name() else KB_PATH


def _index_path() -> Path:
    return paths.index_path() if paths.workspace_name() else INDEX_PATH


def _raw_kb(kb_path: Path) -> str:
    return kb_path.read_text(encoding="utf-8") if kb_path.exists() else ""


def _manifest_order() -> Dict[str, int]:
    p = paths.chapter_manifest_path()
    data = read_json(p, []) if p.exists() else []
    if isinstance(data, dict):
        data = data.get("chapters", data.get("entries", []))
    if not isinstance(data, list):
        return {}
    # First occurrence wins, matching start_point._index_of. (Defensive: real
    # chapter_id is a unique primary key, so this only matters on malformed input.)
    order: Dict[str, int] = {}
    for i, c in enumerate(data):
        if isinstance(c, dict):
            cid = c.get("chapter_id")
            if cid and cid not in order:
                order[cid] = i
    return order


def start_safe_knowledge(
    *,
    kb_path: Path | None = None,
    index_path: Path | None = None,
    respect_start_point: bool = True,
) -> str:
    """Return the knowledge block to inject into writer/planner/debater prompts.

    Callers SHOULD pass their own ``kb_path``/``index_path`` (their
    ``_kb_path()`` / ``_index_path()``) so the KB source is a single injected
    seam — this keeps test patches of those module constants effective and
    avoids accidentally reading the real repo data. When omitted, falls back to
    this module's workspace-aware paths.

    * start point set + ``knowledge_index.json`` present + respect_start_point
      -> structured block filtered to entries at/before the start (spoiler-safe).
    * otherwise -> the original prose ``global_knowledge.md`` verbatim
      (fail-open; byte-identical when no start point is configured).
    """

    from . import start_point

    kb_path = kb_path or _kb_path()
    index_path = index_path or _index_path()
    if not respect_start_point:
        return _raw_kb(kb_path)
    start = start_point.get_start_chapter_id()
    if not start:
        return _raw_kb(kb_path)
    if not index_path.exists():
        return _raw_kb(kb_path)
    index = read_json(index_path, {})
    if not isinstance(index, dict) or not index:
        return _raw_kb(kb_path)
    return _render_start_safe_index(index, start)


def _render_start_safe_index(index: Dict[str, Any], start: str) -> str:
    order = _manifest_order()
    start_idx = order.get(start)

    def kept(chapter_id: Any) -> bool:
        if not chapter_id:
            return True  # fail-open: no chapter_id -> keep
        if start_idx is None:
            return True  # start not in manifest -> can't filter, keep
        ci = order.get(str(chapter_id))
        if ci is None:
            return True  # entry's chapter not in manifest -> keep
        return ci <= start_idx

    lines: List[str] = [
        "# 全局知识（起点安全：仅含续写起点及之前的信息，已过滤起点之后的剧透）",
        "",
    ]

    # 角色状态：每个角色取保留条目中的最近一条
    characters = index.get("characters", {})
    if isinstance(characters, dict):
        char_lines: List[str] = []
        for name, states in characters.items():
            if not name or not isinstance(states, list):
                continue
            kept_states = [s for s in states if isinstance(s, dict) and kept(s.get("chapter_id"))]
            if not kept_states:
                continue
            last = kept_states[-1]
            desc = str(last.get("after") or last.get("status") or last.get("before") or "").strip()
            char_lines.append(f"- {name}：{desc}" if desc else f"- {name}")
        if char_lines:
            lines.append("## 角色状态")
            lines.extend(char_lines)
            lines.append("")

    # 关系
    rels = [
        r for r in index.get("relationships", []) or []
        if isinstance(r, dict) and kept(r.get("chapter_id"))
    ]
    if rels:
        lines.append("## 关系")
        for r in rels:
            who = " / ".join(str(c) for c in (r.get("characters") or []) if c) or "?"
            after = str(r.get("after") or r.get("before") or "").strip()
            lines.append(f"- {who}：{after}" if after else f"- {who}")
        lines.append("")

    # 未闭合伏笔
    fos = [
        f for f in index.get("foreshadowing", []) or []
        if isinstance(f, dict) and kept(f.get("chapter_id"))
    ]
    if fos:
        lines.append("## 未闭合伏笔")
        for f in fos:
            tag = "/".join(t for t in (str(f.get("kind") or "").strip(), str(f.get("status") or "").strip()) if t)
            desc = str(f.get("description") or "").strip()
            prefix = f"[{tag}] " if tag else ""
            lines.append(f"- {prefix}{desc}")
        lines.append("")

    # 世界观规则
    wbs = [
        w for w in index.get("worldbuilding", []) or []
        if isinstance(w, dict) and kept(w.get("chapter_id"))
    ]
    if wbs:
        lines.append("## 世界观规则")
        for w in wbs:
            topic = str(w.get("topic") or "").strip()
            detail = str(w.get("detail") or "").strip()
            lines.append(f"- {topic}：{detail}" if detail else f"- {topic}")
        lines.append("")

    return "\n".join(lines).strip() + "\n"
