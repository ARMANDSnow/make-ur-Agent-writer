from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Tuple

from . import paths
from .config import ROOT
from .state import log_event, write_text_atomic
from .utils import ensure_dir, iter_text_files, write_json


# Legacy constants — kept for iter 014-016 test backward compat.
RAW_DIR = ROOT / "小说txt"
NORMALIZED_DIR = ROOT / "data" / "normalized_texts"
SOURCE_MAP_DIR = ROOT / "data" / "source_map"


def _raw_dir() -> Path:
    return paths.raw_txt_dir() if paths.workspace_name() else RAW_DIR


def _normalized_dir() -> Path:
    return paths.normalized_dir() if paths.workspace_name() else NORMALIZED_DIR


def _source_map_dir() -> Path:
    return (paths.data_dir() / "source_map") if paths.workspace_name() else SOURCE_MAP_DIR


def _normalized_manifest_path() -> Path:
    return (paths.data_dir() / "normalized_manifest.json") if paths.workspace_name() else (ROOT / "data" / "normalized_manifest.json")

BOILERPLATE_PATTERNS = [
    re.compile(r"本书下载"),
    re.compile(r"www\.|http://|https://", re.I),
    re.compile(r"版权归|版权所|请在下载后|支持作者|仅供.*收藏"),
    re.compile(r"={10,}"),
]

# Iter 018: English boilerplate covers Project Gutenberg headers/footers,
# generic copyright lines, ISBN strings, ornament rules, and the
# series-banner line that EPUB exports tend to prefix to every chapter
# (e.g. a "N-Book Bundle: <Series Name> Series" header).
#
# The series-banner regex is intentionally generic: a title-case run of
# 3-10 words ending in "Series" matches the banner shape regardless of
# the actual series title, so we never bake a copyrighted name into the
# tracked source.
BOILERPLATE_PATTERNS_EN = [
    re.compile(r"Project Gutenberg", re.I),
    re.compile(r"ISBN[\s\-:]*\d", re.I),
    re.compile(r"(©|Copyright\s*\(c\)|All rights reserved)", re.I),
    re.compile(r"www\.|http://|https://", re.I),
    re.compile(r"={10,}|\*{10,}|-{20,}"),
    re.compile(r"\d+-Book\s+Bundle", re.I),
    re.compile(r"^(?:[A-Za-z]+\s+){3,9}Series\s*$"),
]

LANG_BOILERPLATE_PATTERNS = {
    "zh": BOILERPLATE_PATTERNS,
    "en": BOILERPLATE_PATTERNS_EN,
}


def _has_cjk(text: str) -> bool:
    return any("一" <= ch <= "鿿" for ch in text)


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
    # Iter 018: only run the validation-corpus-specific naming rules when
    # the filename actually contains CJK characters. Pure-ASCII filenames
    # (English novels) fall through to the generic slug branch, which now
    # carries an ``en_`` prefix so downstream code can spot English volumes.
    if _has_cjk(name):
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
    slug = re.sub(r"\W+", "_", path.stem).strip("_").lower() or "book"
    return f"en_{slug}"


def clean_line(line: str, original_line_no: int, lang: str = "zh") -> str:
    line = line.replace("\x00", "")
    line = re.sub(r"<[^>]+>", "", line)
    line = re.sub(r"[\u0001-\u0008\u000b\u000c\u000e-\u001f]", "", line)
    line = line.replace("\ufffd", "")
    patterns = LANG_BOILERPLATE_PATTERNS.get(lang, BOILERPLATE_PATTERNS)
    # Iter 018: English EPUB exports repeat the series banner before every
    # chapter, not only in the first 120 lines. For ``en`` mode the
    # boilerplate strip runs on every line; for ``zh`` it stays scoped to
    # the head of the file as it has since iter 001.
    if lang == "en" or original_line_no <= 120:
        stripped = line.strip()
        if any(p.search(stripped) for p in patterns):
            return ""
    return line.rstrip()


def normalize_file(path: Path, lang: str | None = None) -> Tuple[Path, Path, Dict[str, object]]:
    raw = path.read_bytes()
    encoding = detect_encoding(raw)
    text = raw.decode(encoding, errors="replace")
    if lang is None:
        from .lang_detect import detect_language
        lang = detect_language(text)
    volume_id = volume_id_for(path)
    out_path = _normalized_dir() / f"{volume_id}.txt"
    map_path = _source_map_dir() / f"{volume_id}.json"

    normalized_lines: List[str] = []
    source_map: List[Dict[str, int]] = []
    for original_line, line in enumerate(text.splitlines(), 1):
        cleaned = clean_line(line, original_line, lang)
        # English mode: drop boilerplate lines anywhere (banner before every
        # chapter). Chinese mode: only drop blanks from the head as before.
        if cleaned == "" and (lang == "en" or original_line <= 120):
            continue
        normalized_lines.append(cleaned)
        source_map.append({"normalized_line": len(normalized_lines), "original_line": original_line})

    write_text_atomic(out_path, "\n".join(normalized_lines).strip() + "\n")
    meta: Dict[str, object] = {
        "volume_id": volume_id,
        "source_file": str(path),
        "normalized_file": str(out_path),
        "encoding": encoding,
        "lang": lang,
        "source_lines": len(text.splitlines()),
        "normalized_lines": len(normalized_lines),
        "line_map": source_map,
    }
    write_json(map_path, meta)
    log_event("normalize", "done", volume_id=volume_id, encoding=encoding, lang=lang, output=str(out_path))
    return out_path, map_path, meta


def normalize_all(raw_dir: Path | None = None, lang: str | None = None) -> List[Dict[str, object]]:
    if raw_dir is None:
        raw_dir = _raw_dir()
    ensure_dir(_normalized_dir())
    ensure_dir(_source_map_dir())
    results = []
    for path in iter_text_files(raw_dir):
        results.append(normalize_file(path, lang=lang)[2])
    write_json(_normalized_manifest_path(), results)
    return results

