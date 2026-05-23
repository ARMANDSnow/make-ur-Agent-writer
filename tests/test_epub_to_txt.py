"""Iter 018: EPUB → text extractor regression tests.

Constructs a minimal in-memory EPUB (container.xml + content.opf + two
xhtml parts), runs ``extract_epub``, and checks spine ordering, html-tag
stripping, and ``book_filter`` selectivity.
"""

import tempfile
import unittest
import zipfile
from pathlib import Path

from src.epub_to_txt import extract_epub


CONTAINER_XML = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""

OPF_XML = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="2.0" unique-identifier="bookid">
  <metadata/>
  <manifest>
    <item id="part01" href="part01.xhtml" media-type="application/xhtml+xml"/>
    <item id="part02" href="part02.xhtml" media-type="application/xhtml+xml"/>
    <item id="extra" href="extra.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine toc="ncx">
    <itemref idref="part02"/>
    <itemref idref="part01"/>
    <itemref idref="extra"/>
  </spine>
</package>
"""

PART01_XHTML = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>p1</title></head>
<body>
  <h1>First Chapter</h1>
  <p>Hello <em>world</em> from part one.</p>
  <script>var bad = "should not appear";</script>
</body></html>
"""

PART02_XHTML = """<?xml version="1.0" encoding="UTF-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>p2</title></head>
<body>
  <h1>Second Chapter</h1>
  <p>Greetings from part two.</p>
</body></html>
"""

EXTRA_XHTML = """<?xml version="1.0" encoding="UTF-8"?>
<html><body><p>Extra appendix content.</p></body></html>
"""


def _build_epub(path: Path) -> None:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("META-INF/container.xml", CONTAINER_XML)
        z.writestr("OEBPS/content.opf", OPF_XML)
        z.writestr("OEBPS/part01.xhtml", PART01_XHTML)
        z.writestr("OEBPS/part02.xhtml", PART02_XHTML)
        z.writestr("OEBPS/extra.xhtml", EXTRA_XHTML)


class ExtractEpubTests(unittest.TestCase):
    def test_preserves_spine_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "demo.epub"
            out = Path(tmp) / "demo.txt"
            _build_epub(src)
            result = extract_epub(src, out)
            text = out.read_text(encoding="utf-8")
        # Spine declares part02 → part01 → extra; output must respect that.
        idx_first = text.find("First Chapter")
        idx_second = text.find("Second Chapter")
        idx_extra = text.find("Extra appendix")
        self.assertGreaterEqual(idx_first, 0)
        self.assertGreaterEqual(idx_second, 0)
        self.assertGreaterEqual(idx_extra, 0)
        self.assertLess(idx_second, idx_first, "spine order ignored")
        self.assertLess(idx_first, idx_extra, "spine order ignored")
        self.assertEqual(result["parts_total"], 3)
        self.assertEqual(result["parts_extracted"], 3)

    def test_html_tags_stripped_and_scripts_dropped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "demo.epub"
            out = Path(tmp) / "demo.txt"
            _build_epub(src)
            extract_epub(src, out)
            text = out.read_text(encoding="utf-8")
        # No raw tags survive.
        self.assertNotIn("<p>", text)
        self.assertNotIn("<em>", text)
        # Script body must be dropped entirely.
        self.assertNotIn("should not appear", text)
        # Inline emphasis text still present.
        self.assertIn("world", text)

    def test_book_filter_selects_subset(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "demo.epub"
            out = Path(tmp) / "demo.txt"
            _build_epub(src)
            result = extract_epub(src, out, book_filter=r"part0[12]")
            text = out.read_text(encoding="utf-8")
        # extra.xhtml filtered out.
        self.assertNotIn("Extra appendix", text)
        self.assertIn("First Chapter", text)
        self.assertIn("Second Chapter", text)
        self.assertEqual(result["parts_total"], 3)
        self.assertEqual(result["parts_extracted"], 2)
        self.assertEqual(result["skipped"], 1)


if __name__ == "__main__":
    unittest.main()
