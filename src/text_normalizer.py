from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Tuple

from .config import ROOT
from .state import log_event, write_text_atomic
from .utils import ensure_dir, iter_text_files, write_json


RAW_DIR = ROOT / "小说txt"
NORMALIZED_DIR = ROOT / "data" / "normalized_texts"
SOURCE_MAP_DIR = ROOT / "data" / "source_map"

BOILERPLATE_PATTERNS = [
    re.compile(r"本书下载"),
    re.compile(r"www\.|http://|https://", re.I),
    re.compile(r"版权归|版权所|请在下载后|支持作者|仅供.*收藏"),
    re.compile(r"={10,}"),
]


def detect_encoding(raw: bytes) -> str:
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return "utf-16"
    sample = raw[:4000]
    if sample.count(b"\x00") > max(8, len(sample) // 20):
        return "utf-16"
    for enc in ("utf-8", "gb18030", "gbk"):
        try:
            raw.decode(enc)
            return enc
        except UnicodeDecodeError:
            continue
    return "gb18030"


def volume_id_for(path: Path) -> str:
    name = path.name
    if "Ⅰ" in name or "I火" in name:
        return "longzu_1"
    if "Ⅱ" in name or "II悼" in name:
        return "longzu_2"
    if "（1）" in name or "(1)" in name:
        return "longzu_3_1"
    if "（2）" in name or "(2)" in name:
        return "longzu_3_2"
    if "（3）" in name or "(3)" in name:
        return "longzu_3_3"
    if "4" in name or "Ⅳ" in name:
        return "longzu_4"
    return re.sub(r"\W+", "_", path.stem).strip("_").lower()


def clean_line(line: str, original_line_no: int) -> str:
    line = line.replace("\x00", "")
    line = re.sub(r"<[^>]+>", "", line)
    line = re.sub(r"[\u0001-\u0008\u000b\u000c\u000e-\u001f]", "", line)
    line = line.replace("\ufffd", "")
    if original_line_no <= 120:
        stripped = line.strip()
        if any(p.search(stripped) for p in BOILERPLATE_PATTERNS):
            return ""
    return line.rstrip()


def normalize_file(path: Path) -> Tuple[Path, Path, Dict[str, object]]:
    raw = path.read_bytes()
    encoding = detect_encoding(raw)
    text = raw.decode(encoding, errors="replace")
    volume_id = volume_id_for(path)
    out_path = NORMALIZED_DIR / f"{volume_id}.txt"
    map_path = SOURCE_MAP_DIR / f"{volume_id}.json"

    normalized_lines: List[str] = []
    source_map: List[Dict[str, int]] = []
    for original_line, line in enumerate(text.splitlines(), 1):
        cleaned = clean_line(line, original_line)
        if cleaned == "" and original_line <= 120:
            continue
        normalized_lines.append(cleaned)
        source_map.append({"normalized_line": len(normalized_lines), "original_line": original_line})

    write_text_atomic(out_path, "\n".join(normalized_lines).strip() + "\n")
    meta: Dict[str, object] = {
        "volume_id": volume_id,
        "source_file": str(path),
        "normalized_file": str(out_path),
        "encoding": encoding,
        "source_lines": len(text.splitlines()),
        "normalized_lines": len(normalized_lines),
        "line_map": source_map,
    }
    write_json(map_path, meta)
    log_event("normalize", "done", volume_id=volume_id, encoding=encoding, output=str(out_path))
    return out_path, map_path, meta


def normalize_all(raw_dir: Path = RAW_DIR) -> List[Dict[str, object]]:
    ensure_dir(NORMALIZED_DIR)
    ensure_dir(SOURCE_MAP_DIR)
    results = []
    for path in iter_text_files(raw_dir):
        results.append(normalize_file(path)[2])
    write_json(ROOT / "data" / "normalized_manifest.json", results)
    return results

