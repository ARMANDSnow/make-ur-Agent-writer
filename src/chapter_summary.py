from __future__ import annotations

"""Rolling per-chapter summary for multi-chapter writer prompt context."""

from pathlib import Path
from typing import Any, Dict, List

from .config import ROOT
from .utils import ensure_dir, read_json, write_json


ROLLING_PATH = ROOT / "outputs" / "drafts" / "rolling_chapter_summary.json"


def _empty_state() -> Dict[str, Any]:
    return {"chapters": [], "compressed_older": []}


def load_rolling_summary(path: Path = ROLLING_PATH) -> Dict[str, Any]:
    """Read rolling chapter summaries; missing or malformed files degrade to empty state."""
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


def save_rolling_summary(data: Dict[str, Any], path: Path = ROLLING_PATH) -> None:
    ensure_dir(path.parent)
    write_json(path, data)


def append_chapter_summary(
    chapter_no: int,
    summary: str,
    key_events: List[str],
    ending_state: str = "",
    path: Path = ROLLING_PATH,
) -> None:
    """Append or replace one chapter summary in rolling state."""
    data = load_rolling_summary(path)
    chapters = [item for item in data["chapters"] if int(item.get("chapter_no", -1)) != int(chapter_no)]
    chapters.append(
        {
            "chapter_no": int(chapter_no),
            "summary": str(summary or "").strip(),
            "key_events": [str(event).strip() for event in key_events if str(event).strip()],
            "ending_state": str(ending_state or "").strip(),
        }
    )
    data["chapters"] = sorted(chapters, key=lambda item: int(item.get("chapter_no", 0)))
    save_rolling_summary(data, path)


def latest_ending_state(path: Path = ROLLING_PATH) -> str:
    chapters = load_rolling_summary(path).get("chapters", [])
    if not chapters:
        return ""
    latest = sorted(chapters, key=lambda item: int(item.get("chapter_no", 0)))[-1]
    return str(latest.get("ending_state") or "").strip()


def render_rolling_context(max_chapters: int = 5, path: Path = ROLLING_PATH) -> str:
    """Render recent chapter summaries for writer prompt injection."""
    data = load_rolling_summary(path)
    chapters = sorted(data.get("chapters", []), key=lambda item: int(item.get("chapter_no", 0)))
    if not chapters:
        return ""

    max_chapters = max(1, int(max_chapters))
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

    for chapter in recent:
        chapter_no = int(chapter.get("chapter_no", 0))
        summary = str(chapter.get("summary") or "").strip()
        key_events = [str(event).strip() for event in chapter.get("key_events", []) or [] if str(event).strip()]
        ending = str(chapter.get("ending_state") or "").strip()
        lines.extend(["", f"### 第 {chapter_no} 章"])
        if summary:
            lines.append(summary)
        if key_events:
            lines.append("关键事件: " + " / ".join(key_events[:6]))
        if ending:
            lines.append("结尾状态: " + ending)

    return "\n".join(lines).strip() + "\n"
