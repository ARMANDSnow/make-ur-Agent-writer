from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from .config import ROOT
from .schemas import ChapterManifestEntry, model_to_dict
from .state import log_event
from .utils import ensure_dir, read_json, write_json


NORMALIZED_DIR = ROOT / "data" / "normalized_texts"
MANIFEST_PATH = ROOT / "data" / "chapter_manifest.json"

CN_NUM = "一二三四五六七八九十百零〇两0-9"
HEADING_RE = re.compile(rf"^\s*((?:第[{CN_NUM}]+[章节幕]\s*[^\n]{{0,70}})|(?:楔子[^\n]{{0,70}})|(?:序章[^\n]{{0,70}})|(?:序幕[^\n]{{0,70}})|(?:尾声[^\n]{{0,70}}))\s*$")


def is_heading(line: str) -> bool:
    stripped = line.strip()
    if len(stripped) > 90:
        return False
    if re.search(r"[章节幕]\s*完$", stripped):
        return False
    return bool(HEADING_RE.match(stripped))


def heading_allowed(volume_id: str, heading: str) -> bool:
    if heading.startswith(("楔子", "序章", "序幕", "尾声")):
        return True
    if volume_id in {"longzu_1", "longzu_2"}:
        return "幕" in heading
    return "章" in heading or "幕" in heading


def normalize_heading_key(heading: str) -> str:
    return re.sub(r"\s+", "", heading).replace("＆", "&")


def candidate_headings(lines: List[str], volume_id: str) -> List[Tuple[int, str]]:
    candidates = [(i, line.strip()) for i, line in enumerate(lines, 1) if is_heading(line) and heading_allowed(volume_id, line.strip())]
    early = [item for item in candidates if item[0] <= 100]
    if len(early) >= 5:
        first_line, first_heading = early[0]
        first_key = normalize_heading_key(first_heading)
        repeated_first = [
            line_no
            for line_no, heading in candidates
            if line_no > first_line and line_no <= 140 and normalize_heading_key(heading) == first_key
        ]
        if repeated_first:
            toc_end = repeated_first[0] - 1
            candidates = [item for item in candidates if item[0] > toc_end]
        elif first_heading.startswith(("序幕", "序章", "楔子")):
            toc_end = max(i for i, _ in early) + 3
            candidates = [early[0]] + [item for item in candidates if item[0] > toc_end]
        else:
            toc_end = max(i for i, _ in early) + 3
            candidates = [item for item in candidates if item[0] > toc_end]

    seen: Dict[str, int] = {}
    for idx, (_, heading) in enumerate(candidates):
        seen[normalize_heading_key(heading)] = idx
    deduped = []
    for idx, item in enumerate(candidates):
        if seen[normalize_heading_key(item[1])] == idx:
            deduped.append(item)
    return deduped


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


def split_file(path: Path) -> List[ChapterManifestEntry]:
    volume_id = path.stem
    lines = path.read_text(encoding="utf-8").splitlines()
    raw_candidates = [
        (i, line.strip())
        for i, line in enumerate(lines, 1)
        if is_heading(line) and heading_allowed(volume_id, line.strip())
    ]
    early_dense = sum(1 for line_no, _ in raw_candidates if line_no <= 100) >= 5
    headings = candidate_headings(lines, volume_id)
    entries: List[ChapterManifestEntry] = []
    for chapter_index, (start_line, title) in enumerate(headings, 1):
        end_line = (headings[chapter_index][0] - 1) if chapter_index < len(headings) else len(lines)
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


def split_all(normalized_dir: Path = NORMALIZED_DIR) -> List[Dict[str, object]]:
    ensure_dir(MANIFEST_PATH.parent)
    entries: List[Dict[str, object]] = []
    normalized_manifest = read_json(ROOT / "data" / "normalized_manifest.json", [])
    source_by_volume = {item["volume_id"]: item["source_file"] for item in normalized_manifest}
    for path in sorted(normalized_dir.glob("*.txt")):
        for entry in split_file(path):
            data = model_to_dict(entry)
            data["source_file"] = source_by_volume.get(entry.volume_id, entry.source_file)
            entries.append(data)
    write_json(MANIFEST_PATH, entries)
    log_event("split", "done", chapters=len(entries), output=str(MANIFEST_PATH))
    return entries


def load_manifest() -> List[Dict[str, object]]:
    manifest = read_json(MANIFEST_PATH, [])
    if not manifest:
        raise FileNotFoundError("chapter manifest not found; run `python main.py normalize` then `python main.py split`")
    return manifest


def chapter_text(entry: Dict[str, object]) -> str:
    path = Path(str(entry["normalized_file"]))
    lines = path.read_text(encoding="utf-8").splitlines()
    start = int(entry["start_line"]) - 1
    end = int(entry["end_line"])
    return "\n".join(lines[start:end])
