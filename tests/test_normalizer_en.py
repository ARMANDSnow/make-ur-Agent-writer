"""Iter 018: English normalizer regression tests.

Covers the English boilerplate dictionary, the every-line strip behaviour
in ``en`` mode, and the ASCII-filename branch of ``volume_id_for``.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import text_normalizer
from src.text_normalizer import clean_line, normalize_file, volume_id_for


class CleanLineEnglishTests(unittest.TestCase):
    def test_strips_project_gutenberg_anywhere(self) -> None:
        # Line 500 (well past zh's 120-line head) — en still strips it.
        self.assertEqual(clean_line("Project Gutenberg eBook of foo", 500, lang="en"), "")

    def test_strips_copyright_isbn_url(self) -> None:
        self.assertEqual(clean_line("Copyright (c) 2011 by Someone", 50, lang="en"), "")
        self.assertEqual(clean_line("ISBN: 978-0-553-10354-0", 50, lang="en"), "")
        self.assertEqual(clean_line("Visit https://example.com for more", 50, lang="en"), "")

    def test_strips_series_banner(self) -> None:
        # Every-chapter series banner that EPUB exports prefix.
        # We test the generic shape (Title Case words ending in "Series")
        # rather than any specific copyrighted series name.
        self.assertEqual(
            clean_line("Chronicles Of A Fictional World Series", 800, lang="en"), ""
        )
        self.assertEqual(
            clean_line("5-Book Bundle: foo bar", 800, lang="en"), ""
        )

    def test_keeps_normal_prose(self) -> None:
        sentence = "The morning had dawned clear and cold."
        self.assertEqual(clean_line(sentence, 500, lang="en"), sentence)

    def test_zh_default_preserves_legacy(self) -> None:
        # In zh mode, "Project Gutenberg" past line 120 must NOT be stripped
        # (the line-no guard kept iter 001-017 behaviour scoped to the head).
        self.assertEqual(
            clean_line("Project Gutenberg something", 500, lang="zh"),
            "Project Gutenberg something",
        )


class VolumeIdEnglishTests(unittest.TestCase):
    def test_ascii_filename_gets_en_prefix(self) -> None:
        self.assertEqual(volume_id_for(Path("english_book_one.txt")), "en_english_book_one")
        self.assertEqual(volume_id_for(Path("fantasy-saga-v1.txt")), "en_fantasy_saga_v1")

    def test_cjk_filename_unchanged(self) -> None:
        # Backward compat — Chinese-named files keep their slug path.
        self.assertFalse(volume_id_for(Path("龙族Ⅰ火之晨曦.txt")).startswith("en_"))


class NormalizeFileEnglishTests(unittest.TestCase):
    def test_utf8_english_file_roundtrip(self) -> None:
        body = "\n".join(
            [
                "Project Gutenberg banner",  # boilerplate — should drop
                "Chronicles Of A Fictional World Series",  # banner — should drop
                "PROLOGUE",
                "The cold wind whispered through the trees.",
                "",
                "It was a long night that followed.",
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            src = tmp_path / "demo_book.txt"
            src.write_text(body, encoding="utf-8")
            with patch.object(text_normalizer, "_normalized_dir", return_value=tmp_path), \
                 patch.object(text_normalizer, "_source_map_dir", return_value=tmp_path):
                out, _, meta = normalize_file(src, lang="en")
            content = out.read_text(encoding="utf-8")
        self.assertNotIn("Project Gutenberg", content)
        self.assertNotIn("Fictional World Series", content)
        self.assertIn("PROLOGUE", content)
        self.assertIn("cold wind", content)
        self.assertEqual(meta["lang"], "en")
        self.assertEqual(meta["encoding"], "utf-8")


if __name__ == "__main__":
    unittest.main()
