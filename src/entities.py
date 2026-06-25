from __future__ import annotations

"""Entity graph loader + tag index + active-state renderer."""

from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

from . import paths
from .config import ROOT
from .utils import read_json_optional


# Long-horizon safety cap for entity-state injected into writer / reviewer /
# debater / plot_planner prompts. ~16K chars ≈ ~18K tokens at the structured-
# text ratio (~1.13 tok/char), comfortably under each task's 128K context after
# the other prompt blocks, and ~2.7× a typical book's active cast (real龙族
# start ≈ 5.9K chars) so realistic graphs render byte-identically. See
# ``render_active_state``'s ``max_chars`` docstring for the failure mode this
# guards against.
PROMPT_ENTITY_STATE_LIMIT = 16000


def _truncate_state_text(text: str, max_chars: int) -> str:
    """Cap ``text`` to ``max_chars`` at a line boundary, appending a marker.

    Used only when ``render_active_state(max_chars=...)`` overflows — a rare
    pathological-growth guard, so we favor a clean, deterministic cut (drop the
    trailing relationship lines, which grow fastest, and keep the entities/tag
    index that lead the render) over anything cleverer.
    """
    marker = "\n[实体关系状态过长，已按预算截断以避免 context 溢出；完整状态见 entity_graph.json]\n"
    max_chars = int(max_chars)
    if max_chars <= 0:
        return ""
    if len(marker) >= max_chars:
        return marker[:max_chars]
    budget = max_chars - len(marker)
    cut = text[:budget]
    boundary = cut.rfind("\n")
    if boundary > 0:
        cut = cut[:boundary]
    return cut + marker


def load_entity_graph(root: Path | None = None) -> Dict[str, Any]:
    """Load optional entity graph data; missing files degrade to an empty graph.

    Iter 017: when ``root`` is None we resolve the active workspace via
    ``paths.entity_graph_path()`` (or the legacy repo-root path when no
    workspace is active). Callers that explicitly pass ``root=Path(tmp)``
    keep the iter 015/016 test override behavior.
    """
    if root is None:
        path = paths.entity_graph_path() if paths.workspace_name() else (ROOT / "data" / "entity_graph.json")
    else:
        path = root / "data" / "entity_graph.json"
    data = read_json_optional(path, {})
    return data if isinstance(data, dict) else {}


def _build_tag_index(entities: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    """Build a tag -> entity names reverse index for implicit associations."""
    index: Dict[str, List[str]] = defaultdict(list)
    for ent in entities:
        name = str(ent.get("name") or ent.get("id") or "?")
        for tag in ent.get("tags", []) or []:
            if tag:
                index[str(tag)].append(name)
    return dict(sorted(index.items()))


def _relationship_is_spoiler(rel: Dict[str, Any], is_after_start, *, viewpoint: str | None = None) -> bool:
    """Iter 021 / 047d: spoiler filter for entity_graph relationships.

    Drop the relationship's **active** timeline entry as a spoiler when:
    * its ``chapter_id`` is strictly after the start point (iter 021), OR
    * (iter 047d, optional) it carries ``reader_known`` and the reader learns it
      only after the start, OR
    * a POV ``viewpoint`` is given and the entry's ``character_known`` map shows
      that character doesn't know it yet at the start.

    Entries lacking these optional fields are kept (no spoiler signal), so when
    the new fields are absent behavior is byte-identical to iter 021 (fail-open).
    """
    timeline = rel.get("timeline", [])
    if not isinstance(timeline, list):
        return False
    for item in timeline:
        if not isinstance(item, dict) or not item.get("active"):
            continue
        ch_id = item.get("chapter_id") or item.get("source_chapter")
        if ch_id and is_after_start(ch_id):
            return True
        reader_known = item.get("reader_known")
        if reader_known and is_after_start(reader_known):
            return True
        if viewpoint:
            known = item.get("character_known")
            if isinstance(known, dict):
                known_at = known.get(viewpoint)
                # fail-open: hide only when we KNOW this POV learns it post-start;
                # a missing char entry leaves the state visible (no info → keep).
                if known_at and is_after_start(known_at):
                    return True  # this POV character doesn't know it yet
        return False  # active entry: no spoiler signal → keep
    return False


def render_active_state(
    graph: Dict[str, Any],
    respect_start_point: bool = True,
    *,
    viewpoint: str | None = None,
    max_chars: int | None = None,
) -> str:
    """Render entity list, shared-tag index, and active relationship states.

    Iter 021: when ``respect_start_point=True`` and a start point is
    configured, relationships whose active timeline entry has a
    ``chapter_id`` strictly after the start are filtered as spoilers.
    Timeline entries without a ``chapter_id`` are kept (no info to filter
    on — schema upgrade for richer filtering is iter 022 work).

    ``max_chars``: optional safety cap (defaults to None = no cap, byte-
    identical to the legacy behavior). When set and exceeded, the rendered
    text is truncated at a line boundary with a marker. This is the
    long-horizon insurance for the four prompt-injecting callers (writer /
    reviewer / debater / plot_planner): every one of them used to inject the
    full entity-state string with no truncation, so a graph that grows over
    many chapters (or a large initial extraction, or ``allow_creation=True``)
    could push the write/review prompt past ``LLMContextOverflowError``'s
    ``context_limit*0.9`` redline — a deterministic, non-retried hard failure
    that would halt a long run. The cap is generous (~2.7× a typical book's
    active cast) so realistic graphs stay byte-identical; it only engages on
    pathological growth, where a marker-truncated state beats a crash.
    """
    if not graph:
        return ""

    entities = [ent for ent in graph.get("entities", []) or [] if isinstance(ent, dict)]
    relationships = [rel for rel in graph.get("relationships", []) or [] if isinstance(rel, dict)]
    if respect_start_point:
        from . import start_point
        if start_point.get_start_chapter_id() is not None:
            relationships = [
                rel for rel in relationships
                if not _relationship_is_spoiler(rel, start_point.is_after_start, viewpoint=viewpoint)
            ]
    entities_by_id = {str(ent.get("id", "")): ent for ent in entities if ent.get("id")}
    lines: List[str] = ["## 当前续写起点的实体关系状态", "", "### 关键实体"]

    for ent in entities:
        name = str(ent.get("name") or ent.get("id") or "<未命名实体>")
        ent_type = str(ent.get("type") or "entity")
        aliases = [str(alias) for alias in ent.get("aliases", []) if alias]
        alias_str = f"(也叫{'/'.join(aliases)})" if aliases else ""
        tags_str = " ".join(str(tag) for tag in ent.get("tags", []) or [] if tag)
        facts_str = "; ".join(str(fact) for fact in ent.get("key_facts", []) or [] if fact)
        description = str(ent.get("description") or "").strip()
        lines.append(f"- **{name}**{alias_str} [{ent_type}]")
        if tags_str:
            lines.append(f"  - tags: {tags_str}")
        if facts_str:
            lines.append(f"  - 核心: {facts_str}")
        if description:
            lines.append(f"  - 描写: {description}")

    shared_tags = {tag: names for tag, names in _build_tag_index(entities).items() if len(names) >= 2}
    if shared_tags:
        lines.extend(["", "### tag 反向索引(共享 tag 的实体之间有隐式联想)"])
        for tag, names in shared_tags.items():
            lines.append(f"- {tag} -> {' / '.join(names)}")

    lines.extend(["", "### 当前活跃关系(写作时必须遵守)"])
    for rel in relationships:
        timeline = rel.get("timeline", [])
        if not isinstance(timeline, list):
            continue
        active_state = next((item for item in timeline if isinstance(item, dict) and item.get("active")), None)
        if not active_state:
            continue
        src_id = str(rel.get("src_id", ""))
        dst_id = str(rel.get("dst_id", ""))
        src = str(entities_by_id.get(src_id, {}).get("name") or src_id or "<未知实体>")
        dst = str(entities_by_id.get(dst_id, {}).get("name") or dst_id or "<未知实体>")
        relation_type = str(rel.get("relation_type") or "关系")
        state = str(active_state.get("state") or "").strip()
        if state:
            lines.append(f"- **{src} <-> {dst}** ({relation_type}): {state}")

    text = "\n".join(lines) + "\n"
    if max_chars is not None and len(text) > int(max_chars):
        text = _truncate_state_text(text, int(max_chars))
    return text
