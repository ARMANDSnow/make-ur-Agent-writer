from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from . import paths
from .config import ROOT
from .schemas import ChapterManifestEntry, model_to_dict
from .state import log_event
from .utils import ensure_dir, read_json, write_json


# Legacy constants — kept for iter 014-016 test backward compat.
NORMALIZED_DIR = ROOT / "data" / "normalized_texts"
MANIFEST_PATH = ROOT / "data" / "chapter_manifest.json"


def _normalized_dir() -> Path:
    return paths.normalized_dir() if paths.workspace_name() else NORMALIZED_DIR


def _manifest_path() -> Path:
    return paths.chapter_manifest_path() if paths.workspace_name() else MANIFEST_PATH


def _normalized_manifest_path() -> Path:
    if paths.workspace_name():
        return paths.data_dir() / "normalized_manifest.json"
    return ROOT / "data" / "normalized_manifest.json"

CN_NUM = "一二三四五六七八九十百零〇两0-9"
HEADING_RE = re.compile(rf"^\s*((?:第[{CN_NUM}]+[章节幕]\s*[^\n]{{0,70}})|(?:楔子[^\n]{{0,70}})|(?:序章[^\n]{{0,70}})|(?:序幕[^\n]{{0,70}})|(?:尾声[^\n]{{0,70}}))\s*$")

# Iter 018: English chapter heading regex.
# Covers four common formats:
#   - PROLOGUE / EPILOGUE / INTRODUCTION single-word section markers
#   - CHAPTER I / CHAPTER 1 / Chapter 1: Title  (roman numerals or arabic)
#   - All-caps POV style (e.g. ALICE / BOB / ALICE SMITH) — up to 3 words,
#     each 3-15 ASCII uppercase letters. Catches POV-per-chapter epic-fantasy
#     formats where each chapter is titled with the viewpoint character.
HEADING_RE_EN = re.compile(
    r"^\s*("
    r"PROLOGUE|EPILOGUE|INTRODUCTION|FOREWORD|AFTERWORD"
    r"|CHAPTER\s+[IVXLCDM\d]+(\s*[:：]\s*[^\n]{1,80})?"
    r"|Chapter\s+\d+(\s*[:：]\s*[^\n]{1,80})?"
    r"|[A-Z]{3,15}(\s+[A-Z]{3,15}){0,2}"
    r")\s*$"
)

LANG_HEADING_PATTERNS = {
    "zh": HEADING_RE,
    "en": HEADING_RE_EN,
}


def is_heading(line: str, lang: str = "zh") -> bool:
    stripped = line.strip()
    if len(stripped) > 90:
        return False
    if lang == "zh" and re.search(r"[章节幕]\s*完$", stripped):
        return False
    pattern = LANG_HEADING_PATTERNS.get(lang, HEADING_RE)
    return bool(pattern.match(stripped))


def heading_allowed(volume_id: str, heading: str, lang: str = "zh") -> bool:
    if lang == "en":
        # Iter 018: English headings are accepted as-is by is_heading(); no
        # additional volume-specific filtering. Empty heading is rejected.
        return bool(heading.strip())
    if heading.startswith(("楔子", "序章", "序幕", "尾声")):
        return True
    if volume_id in {"longzu_1", "longzu_2"}:
        return "幕" in heading
    return "章" in heading or "幕" in heading


def normalize_heading_key(heading: str) -> str:
    return re.sub(r"\s+", "", heading).replace("＆", "&")


def candidate_headings(lines: List[str], volume_id: str, lang: str = "zh") -> List[Tuple[int, str]]:
    candidates = [(i, line.strip()) for i, line in enumerate(lines, 1) if is_heading(line, lang) and heading_allowed(volume_id, line.strip(), lang)]
    # Repeated chapter names belong to different volumes/POVs. Never dedupe
    # globally. A table of contents is a local, explicitly labelled region.
    def chapter_key(heading: str) -> str:
        match = re.match(rf"第[{CN_NUM}]+[章节幕]|楔子|序章|序幕|尾声|CHAPTER\s+[IVXLCDM0-9]+|Chapter\s+[0-9]+", heading)
        return normalize_heading_key(match.group(0) if match else heading)

    excluded: set[int] = set()
    markers = [i for i, line in enumerate(lines, 1)
               if re.fullmatch(r"目\s*录|contents|table of contents", line.strip(), re.I)]
    for marker in markers:
        next_marker = next((n for n in markers if n > marker), len(lines) + 1)
        local = [(n, title) for n, title in candidates if marker < n < next_marker]
        if not local:
            continue
        first_n, first_title = local[0]
        # Stop at prose rather than guessing an offset from a line count.
        block = []
        last_n = marker
        for position, (n, title) in enumerate(local):
            between = lines[last_n:n - 1]
            if any(len(line.strip()) > 100 for line in between):
                break
            if block and chapter_key(title) == chapter_key(first_title):
                break
            if n - last_n > 40:
                break
            following_n = local[position + 1][0] if position + 1 < len(local) else next_marker
            gap = lines[n:following_n - 1]
            padding_only = all(not line.strip() or line.strip().isdecimal() for line in gap)
            repeated_later = any(chapter_key(other) == chapter_key(title) for _, other in local[position + 1:])
            if not padding_only and not repeated_later:
                break
            block.append(n)
            last_n = n
        if len(block) >= 3:
            excluded.update(block)
    return [(n, title) for n, title in candidates if n not in excluded]


def _heading_confidence(title: str, char_count: int, in_dedup_risk_zone: bool) -> float:
    if title.startswith(("序章", "序幕", "楔子", "尾声")):
        pattern_score = 0.9
    else:
        pattern_score = 1.0
    if char_count >= 1500:
        length_score = 1.0
    elif char_count >= 500:
        length_score = 0.7
    else:
        length_score = 0.4
    position_score = 0.7 if in_dedup_risk_zone else 1.0
    return round(min(pattern_score, length_score, position_score), 2)


def split_file(path: Path, lang: str | None = None) -> List[ChapterManifestEntry]:
    volume_id = path.stem
    text = path.read_text(encoding="utf-8")
    if lang is None:
        from .lang_detect import detect_language
        lang = detect_language(text)
    lines = text.splitlines()
    raw_candidates = [
        (i, line.strip())
        for i, line in enumerate(lines, 1)
        if is_heading(line, lang) and heading_allowed(volume_id, line.strip(), lang)
    ]
    early_dense = sum(1 for line_no, _ in raw_candidates if line_no <= 100) >= 5
    headings = candidate_headings(lines, volume_id, lang)
    kept_lines = {n for n, _ in headings}
    toc_starts = []
    for n, line in enumerate(lines, 1):
        if re.fullmatch(r"目\s*录|contents|table of contents", line.strip(), re.I):
            following = [pos for pos, _ in raw_candidates if pos > n][:3]
            if len(following) == 3 and all(pos not in kept_lines for pos in following):
                toc_starts.append(n)
    entries: List[ChapterManifestEntry] = []
    for chapter_index, (start_line, title) in enumerate(headings, 1):
        end_line = (headings[chapter_index][0] - 1) if chapter_index < len(headings) else len(lines)
        # A following volume's TOC/preamble is not part of this chapter.
        boundaries = [n - 1 for n in toc_starts if start_line < n <= end_line]
        if boundaries:
            end_line = min(boundaries)
        chapter_text = "\n".join(lines[start_line - 1 : end_line])
        char_count = len(chapter_text)
        in_risk_zone = early_dense and start_line <= 100
        confidence = _heading_confidence(title, char_count, in_risk_zone)
        entries.append(
            ChapterManifestEntry(
                chapter_id=f"{volume_id}_ch{chapter_index:03d}",
                volume_id=volume_id,
                source_file=str(path),
                normalized_file=str(path),
                title=title,
                start_line=start_line,
                end_line=end_line,
                char_count=char_count,
                confidence=confidence,
            )
        )
    return entries


def split_all(normalized_dir: Path | None = None, lang: str | None = None) -> List[Dict[str, object]]:
    if normalized_dir is None:
        normalized_dir = _normalized_dir()
    manifest_path = _manifest_path()
    ensure_dir(manifest_path.parent)
    entries: List[Dict[str, object]] = []
    normalized_manifest = read_json(_normalized_manifest_path(), [])
    source_by_volume = {item["volume_id"]: item["source_file"] for item in normalized_manifest}
    for path in sorted(normalized_dir.glob("*.txt")):
        for entry in split_file(path, lang=lang):
            data = model_to_dict(entry)
            data["source_file"] = source_by_volume.get(entry.volume_id, entry.source_file)
            entries.append(data)
    write_json(manifest_path, entries)
    log_event("split", "done", chapters=len(entries), output=str(manifest_path))
    return entries


def load_manifest() -> List[Dict[str, object]]:
    manifest = read_json(_manifest_path(), [])
    if not manifest:
        raise FileNotFoundError("chapter manifest not found; run `python main.py normalize` then `python main.py split`")
    return manifest


def chapter_text(entry: Dict[str, object]) -> str:
    path = Path(str(entry["normalized_file"]))
    lines = path.read_text(encoding="utf-8").splitlines()
    start = int(entry["start_line"]) - 1
    end = int(entry["end_line"])
    return "\n".join(lines[start:end])
