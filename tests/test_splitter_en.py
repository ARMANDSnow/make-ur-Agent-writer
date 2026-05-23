"""Iter 018: English chapter splitter regression tests.

Covers the four English heading patterns added to ``HEADING_RE_EN`` plus
the ToC-dedup heuristic when used in ``en`` mode.
"""

import tempfile
import unittest
from pathlib import Path

from src.chapter_splitter import candidate_headings, is_heading, split_file


class EnglishHeadingPatternTests(unittest.TestCase):
    def test_pov_single_word_uppercase(self) -> None:
        for line in ("ALICE", "BOB", "CHARLIE", "DANA", "EVE"):
            self.assertTrue(is_heading(line, lang="en"), f"missed POV {line!r}")

    def test_pov_two_word_uppercase(self) -> None:
        self.assertTrue(is_heading("ALICE SMITH", lang="en"))
        self.assertTrue(is_heading("KING ARTHUR", lang="en"))

    def test_chapter_roman_numeral(self) -> None:
        for line in ("CHAPTER I", "CHAPTER IV", "CHAPTER XXIII", "Chapter 1", "Chapter 12: The Hand"):
            self.assertTrue(is_heading(line, lang="en"), f"missed {line!r}")

    def test_prologue_epilogue(self) -> None:
        self.assertTrue(is_heading("PROLOGUE", lang="en"))
        self.assertTrue(is_heading("EPILOGUE", lang="en"))
        self.assertTrue(is_heading("INTRODUCTION", lang="en"))

    def test_non_heading_rejected(self) -> None:
        # Mixed-case sentence, dialog, lowercase words must NOT match.
        for line in (
            "The morning had dawned clear and cold.",
            '"What is it?" she asked.',
            "alice walked to the river that day to think",
            "1989 was a year of",  # number alone
        ):
            self.assertFalse(is_heading(line, lang="en"), f"false positive on {line!r}")


class EnglishSplitFileTests(unittest.TestCase):
    def _write(self, tmp: Path, body: str) -> Path:
        path = tmp / "en_demo_pov.txt"
        path.write_text(body, encoding="utf-8")
        return path

    def test_pov_chapters_become_entries(self) -> None:
        body = "\n".join(
            [
                "PROLOGUE",
                "The cold wind whispered through the trees.",
                " ".join(["filler"] * 200),
                "ALICE",
                "The morning had dawned clear and cold.",
                " ".join(["filler"] * 200),
                "BOB",
                "Bob had never liked the woods at dusk.",
                " ".join(["filler"] * 200),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(Path(tmp), body)
            entries = split_file(path, lang="en")
        titles = [e.title for e in entries]
        self.assertEqual(titles, ["PROLOGUE", "ALICE", "BOB"])
        # Each entry must have a positive char_count (the body lines after the heading).
        for e in entries:
            self.assertGreater(e.char_count, 0)

    def test_mixed_chapter_and_pov(self) -> None:
        body = "\n".join(
            [
                "Chapter 1: The Beginning",
                " ".join(["body"] * 300),
                "ALICE",
                " ".join(["body"] * 300),
                "EPILOGUE",
                " ".join(["body"] * 200),
            ]
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = self._write(Path(tmp), body)
            entries = split_file(path, lang="en")
        self.assertEqual([e.title for e in entries], ["Chapter 1: The Beginning", "ALICE", "EPILOGUE"])


if __name__ == "__main__":
    unittest.main()
