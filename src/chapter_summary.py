from __future__ import annotations

"""Rolling per-chapter summary for multi-chapter writer prompt context."""

from pathlib import Path
from typing import Any, Dict, List

from . import paths
from .config import ROOT
from .utils import ensure_dir, read_json, write_json


# Legacy constant — kept for iter 014-016 test backward compat.
ROLLING_PATH = ROOT / "outputs" / "drafts" / "rolling_chapter_summary.json"


def _rolling_path() -> Path:
    return paths.rolling_summary_path() if paths.workspace_name() else ROLLING_PATH


def _empty_state() -> Dict[str, Any]:
    return {"chapters": [], "compressed_older": []}


def load_rolling_summary(path: Path | None = None) -> Dict[str, Any]:
    """Read rolling chapter summaries; missing or malformed files degrade to empty state."""
    if path is None:
        path = _rolling_path()
    data = read_json(path, _empty_state())
    if not isinstance(data, dict):
        return _empty_state()
    chapters = data.get("chapters")
    compressed = data.get("compressed_older")
    if not isinstance(chapters, list):
        chapters = []
    if not isinstance(compressed, list):
        compressed = []
    return {"chapters": chapters, "compressed_older": compressed}


def save_rolling_summary(data: Dict[str, Any], path: Path | None = None) -> None:
    if path is None:
        path = _rolling_path()
    ensure_dir(path.parent)
    write_json(path, data)


def append_chapter_summary(
    chapter_no: int,
    summary: str,
    key_events: List[str],
    ending_state: str = "",
    text_snippet: str = "",
    path: Path | None = None,
) -> None:
    """Append or replace one chapter summary in rolling state.

    Iter 022 B5: optional ``text_snippet`` (typically opening 250 chars
    + ending 250 chars of the actual draft) is stored alongside the
    LLM-compressed summary. ``render_rolling_context`` then injects the
    snippet for the most recent K chapters, giving writer prompts a
    layered context (raw prose for nearby chapters, summaries only for
    older ones). This addresses the iter 020 report finding that info
    retention from source → KB → rolling_summary dropped <1%.
    """
    if path is None:
        path = _rolling_path()
    data = load_rolling_summary(path)
    chapters = [item for item in data["chapters"] if int(item.get("chapter_no", -1)) != int(chapter_no)]
    entry = {
        "chapter_no": int(chapter_no),
        "summary": str(summary or "").strip(),
        "key_events": [str(event).strip() for event in key_events if str(event).strip()],
        "ending_state": str(ending_state or "").strip(),
    }
    if text_snippet:
        entry["text_snippet"] = str(text_snippet).strip()
    chapters.append(entry)
    data["chapters"] = sorted(chapters, key=lambda item: int(item.get("chapter_no", 0)))
    save_rolling_summary(data, path)


def prune_from_chapter(chapter_no: int, path: Path | None = None) -> None:
    """Drop rolling summaries for ``chapter_no`` and anything after it.

    ``write_book.sh`` retries rejected chapters by moving their draft/meta
    files aside before re-running the writer. The rolling summary must be
    rewound at the same boundary; otherwise a rejected draft can poison the
    retry prompt and every later chapter.
    """
    if path is None:
        path = _rolling_path()
    data = load_rolling_summary(path)
    cutoff = int(chapter_no)
    data["chapters"] = [
        item
        for item in data.get("chapters", [])
        if int(item.get("chapter_no", 0)) < cutoff
    ]
    save_rolling_summary(data, path)


def latest_ending_state(path: Path | None = None) -> str:
    if path is None:
        path = _rolling_path()
    chapters = load_rolling_summary(path).get("chapters", [])
    if not chapters:
        return ""
    latest = sorted(chapters, key=lambda item: int(item.get("chapter_no", 0)))[-1]
    return str(latest.get("ending_state") or "").strip()


def render_rolling_context(
    max_chapters: int = 5,
    path: Path | None = None,
    snippet_chapters: int = 3,
) -> str:
    """Render recent chapter summaries for writer prompt injection.

    Iter 022 B5: in addition to summaries for the most-recent
    ``max_chapters`` chapters, the LAST ``snippet_chapters`` chapters
    get their ``text_snippet`` (raw prose ~500 chars) inlined. This
    layered context preserves prose detail for what's close to the
    write head while keeping older chapters at summary level (cost-
    efficient).
    """
    if path is None:
        path = _rolling_path()
    data = load_rolling_summary(path)
    chapters = sorted(data.get("chapters", []), key=lambda item: int(item.get("chapter_no", 0)))
    if not chapters:
        return ""

    max_chapters = max(1, int(max_chapters))
    snippet_chapters = max(0, int(snippet_chapters))
    recent = chapters[-max_chapters:]
    older = chapters[:-max_chapters]
    lines: List[str] = ["## 已写章节回顾"]

    compressed_events = [str(item).strip() for item in data.get("compressed_older", []) if str(item).strip()]
    for chapter in older:
        for event in chapter.get("key_events", []) or []:
            text = str(event).strip()
            if text:
                compressed_events.append(text[:12])
    if compressed_events:
        lines.extend(["", "更早章节关键事件: " + " / ".join(compressed_events[-10:])])

    # Identify which of the recent chapters get a snippet (the last K of them)
    snippet_chapter_nos = {
        int(ch.get("chapter_no", 0)) for ch in recent[-snippet_chapters:]
    } if snippet_chapters else set()

    for chapter in recent:
        chapter_no = int(chapter.get("chapter_no", 0))
        summary = str(chapter.get("summary") or "").strip()
        key_events = [str(event).strip() for event in chapter.get("key_events", []) or [] if str(event).strip()]
        ending = str(chapter.get("ending_state") or "").strip()
        snippet = str(chapter.get("text_snippet") or "").strip()
        lines.extend(["", f"### 第 {chapter_no} 章"])
        if summary:
            lines.append(summary)
        if key_events:
            lines.append("关键事件: " + " / ".join(key_events[:6]))
        if ending:
            lines.append("结尾状态: " + ending)
        if snippet and chapter_no in snippet_chapter_nos:
            lines.extend([
                "",
                "原文片段（开场 + 结尾节选）:",
                snippet,
            ])

    return "\n".join(lines).strip() + "\n"
