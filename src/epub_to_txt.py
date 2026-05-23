"""Iter 018: stdlib-only EPUB → plain text extractor.

EPUB files are ZIP archives. ``META-INF/container.xml`` points at the OPF
manifest, the OPF manifest declares item IDs and hrefs, and ``<spine>``
declares the reading order. We follow that chain to read xhtml files in
the correct sequence, strip HTML markup with ``html.parser``, collapse
runs of blank lines, and write a single UTF-8 ``.txt``.

No third-party dependency — uses only ``zipfile``, ``html.parser``,
``xml.etree.ElementTree``, and ``re``. Tolerant of malformed XHTML
(``html.parser`` swallows bad tags rather than raising).

Use case: the user has a multi-book EPUB bundle on their desktop and
wants only Book 1 — pass ``book_filter`` as a regex that matches the
xhtml part file names (e.g. ``r"part00(09|1[0-9])"``).
"""

from __future__ import annotations

import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Dict, List, Optional
from xml.etree import ElementTree as ET


class _TextExtractor(HTMLParser):
    """Strip tags, emit text. Adds newlines around block-level elements
    so the output is line-broken in a way the splitter can scan."""

    BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "div", "li", "br", "tr"}
    SKIP_TAGS = {"script", "style", "head"}

    def __init__(self) -> None:
        super().__init__()
        self._parts: List[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
        if tag in self.BLOCK_TAGS:
            self._parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in self.SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag in self.BLOCK_TAGS:
            self._parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._parts.append(data)

    def get_text(self) -> str:
        text = "".join(self._parts)
        # Collapse 3+ consecutive newlines to 2 (paragraph break).
        text = re.sub(r"\n{3,}", "\n\n", text)
        # Trim trailing whitespace on each line.
        lines = [line.rstrip() for line in text.split("\n")]
        return "\n".join(lines).strip() + "\n"


def _parse_spine_order(epub: zipfile.ZipFile) -> List[str]:
    """Return ordered list of href strings (relative to the OPF directory)."""

    # container.xml → OPF path
    try:
        container_xml = epub.read("META-INF/container.xml").decode("utf-8")
    except KeyError:
        # Fall back: scan top-level for any .opf
        opf_paths = [n for n in epub.namelist() if n.endswith(".opf")]
        return _parse_opf_spine(epub, opf_paths[0]) if opf_paths else []

    ns = {"c": "urn:oasis:names:tc:opendocument:xmlns:container"}
    container_root = ET.fromstring(container_xml)
    rootfile = container_root.find(".//c:rootfile", ns)
    if rootfile is None:
        return []
    opf_path = rootfile.attrib.get("full-path", "")
    if not opf_path:
        return []
    return _parse_opf_spine(epub, opf_path)


def _parse_opf_spine(epub: zipfile.ZipFile, opf_path: str) -> List[str]:
    """Return absolute zip-internal paths for spine itemrefs, in order."""

    opf_xml = epub.read(opf_path).decode("utf-8")
    # Strip default namespace to avoid ET prefix noise — works because we
    # only need the spine / manifest element tree.
    opf_xml = re.sub(r'\sxmlns="[^"]+"', "", opf_xml, count=1)
    root = ET.fromstring(opf_xml)

    manifest = {}
    for item in root.iter("item"):
        item_id = item.attrib.get("id")
        href = item.attrib.get("href")
        if item_id and href:
            manifest[item_id] = href

    base_dir = str(Path(opf_path).parent) if "/" in opf_path else ""
    ordered: List[str] = []
    for itemref in root.iter("itemref"):
        idref = itemref.attrib.get("idref")
        if idref and idref in manifest:
            href = manifest[idref]
            full = f"{base_dir}/{href}" if base_dir else href
            ordered.append(full)
    return ordered


def extract_epub(src: Path, out: Path, book_filter: Optional[str] = None) -> Dict[str, Any]:
    """Extract EPUB ``src`` to plain-text ``out``.

    Parameters
    ----------
    src : Path
        Path to the .epub file.
    out : Path
        Destination .txt path. Parent directory is created if missing.
    book_filter : optional regex string
        When set, only spine entries whose path matches this regex are
        extracted. Useful for picking a single book out of a multi-book
        bundle (e.g. ``r"part00(09|1[0-9])"``).

    Returns a stats dict::

        {
          "src": str,
          "out": str,
          "parts_total": int,        # spine entries in EPUB
          "parts_extracted": int,    # parts after book_filter
          "total_chars": int,
          "skipped": int,
        }
    """

    src = Path(src)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)

    filter_re = re.compile(book_filter) if book_filter else None
    extracted = 0
    skipped = 0
    parts_total = 0
    buf: List[str] = []

    with zipfile.ZipFile(src) as epub:
        spine = _parse_spine_order(epub)
        parts_total = len(spine)
        for href in spine:
            if filter_re is not None and not filter_re.search(href):
                skipped += 1
                continue
            try:
                raw = epub.read(href)
            except KeyError:
                skipped += 1
                continue
            try:
                html = raw.decode("utf-8")
            except UnicodeDecodeError:
                html = raw.decode("utf-8", errors="replace")
            extractor = _TextExtractor()
            extractor.feed(html)
            chunk = extractor.get_text()
            if chunk.strip():
                buf.append(chunk)
                extracted += 1
            else:
                skipped += 1

    text = "\n".join(buf)
    out.write_text(text, encoding="utf-8")
    return {
        "src": str(src),
        "out": str(out),
        "parts_total": parts_total,
        "parts_extracted": extracted,
        "total_chars": len(text),
        "skipped": skipped,
    }


def render_extract_result(result: Dict[str, Any]) -> str:
    lines = [
        f"epub-import: {result['src']}",
        f"  -> {result['out']}",
        f"  spine entries: {result['parts_total']}",
        f"  extracted:     {result['parts_extracted']}",
        f"  skipped:       {result['skipped']}",
        f"  total chars:   {result['total_chars']}",
    ]
    return "\n".join(lines) + "\n"
