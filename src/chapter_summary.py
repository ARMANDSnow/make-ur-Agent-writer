from __future__ import annotations

"""Rolling per-chapter summary for multi-chapter writer prompt context."""

from pathlib import Path
from typing import Any, Dict, List

from . import paths
from .config import ROOT
from .utils import ensure_dir, read_json, write_json


# Legacy constant — kept for iter 014-016 test backward compat.
ROLLING_PATH = ROOT / "outputs" / "drafts" / "rolling_chapter_summary.json"

# iter057 HIGH-2: 滑出最近 _ROLLING_NEAR 章窗口的章会被确定性 compact 成一行
# (≤_COMPACT_LINE_CHARS 字)累积进 rolling 的 compressed_older,取代 render 时把 older 章
# key_events 砍成 12 字残片、只留 10 条的退化(ch25+ 早期伏笔/设定失忆)。compressed_older
# 上限 _COMPACT_OLDER_KEEP 章。纯确定性、无 LLM(周期性 LLM 二次压缩留完整版)。
_ROLLING_NEAR = 5
_COMPACT_OLDER_KEEP = 40
_COMPACT_LINE_CHARS = 60


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


def _compact_line(entry: Dict[str, Any]) -> str:
    """把一章 summary entry 确定性压成一行长程记忆(无 LLM,≤_COMPACT_LINE_CHARS 字)。

    优先取 summary 首句;无 summary 则用前两条 key_events 拼接。"""
    summary = str(entry.get("summary") or "").strip()
    head = summary.split("。")[0].strip() if summary else ""
    if not head:
        events = [str(e).strip() for e in entry.get("key_events", []) or [] if str(e).strip()]
        head = "；".join(events[:2])
    return head[:_COMPACT_LINE_CHARS]


def _compact_older(data: Dict[str, Any], near: int = _ROLLING_NEAR) -> None:
    """把滑出最近 ``near`` 章窗口、且尚未 compact 的章累积进 ``compressed_older``。

    幂等(按 chapter_no 去重);上限 ``_COMPACT_OLDER_KEEP`` 章(留最近的 older)。这是 HIGH-2
    的写盘点——此前 compressed_older 零写入,older 记忆只能靠 render 砍成 12 字残片。"""
    chapters = data.get("chapters", []) or []
    if len(chapters) <= near:
        return
    compressed = [item for item in data.get("compressed_older", []) or [] if item]
    covered = {
        int(item["chapter_no"])
        for item in compressed
        if isinstance(item, dict) and item.get("chapter_no") is not None
    }
    for chapter in chapters[:-near]:
        cno = int(chapter.get("chapter_no", 0))
        if cno in covered:
            continue
        text = _compact_line(chapter)
        if text:
            compressed.append({"chapter_no": cno, "text": text})
            covered.add(cno)
    compressed.sort(
        key=lambda item: int(item.get("chapter_no", 0)) if isinstance(item, dict) else 0
    )
    data["compressed_older"] = compressed[-_COMPACT_OLDER_KEEP:]


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
    _compact_older(data)
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
    # iter057 HIGH-2: 同步回退 compressed_older,否则被重写章(>=cutoff)的旧紧凑行残留毒化 retry。
    data["compressed_older"] = [
        item
        for item in data.get("compressed_older", []) or []
        if not (isinstance(item, dict) and int(item.get("chapter_no", 0)) >= cutoff)
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

    # iter057 HIGH-2: compressed_older 现累积 older 章的紧凑行({"chapter_no","text"})。
    # 有内容时优先输出每章一行梗概(取代 12 字残片);为空时(早期/向后兼容)回落旧逻辑。
    compact_lines: List[str] = []
    covered = set()
    for item in data.get("compressed_older", []) or []:
        if isinstance(item, dict):
            text = str(item.get("text") or "").strip()
            cno = int(item.get("chapter_no", 0) or 0)
        else:  # 向后兼容纯字符串旧格式
            text, cno = str(item).strip(), 0
        if text:
            compact_lines.append(f"第{cno}章：{text}" if cno else text)
            if cno:
                covered.add(cno)
    # older 中未被 compressed_older 覆盖的章(边界章/向后兼容)→ key_events 截断回落
    residual_events: List[str] = []
    for chapter in older:
        if int(chapter.get("chapter_no", 0)) in covered:
            continue
        for event in chapter.get("key_events", []) or []:
            text = str(event).strip()
            if text:
                residual_events.append(text[:12])
    if compact_lines:
        lines.extend(["", "更早章节梗概:", *compact_lines[-_COMPACT_OLDER_KEEP:]])
        if residual_events:
            lines.append("更早关键事件: " + " / ".join(residual_events[-10:]))
    elif residual_events:
        lines.extend(["", "更早章节关键事件: " + " / ".join(residual_events[-10:])])

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
