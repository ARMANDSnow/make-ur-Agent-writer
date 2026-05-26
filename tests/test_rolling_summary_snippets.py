"""Iter 022 B5: tests for rolling_summary layered snippets.

Validates:
* `append_chapter_summary(text_snippet=...)` persists snippet to JSON
* `render_rolling_context(snippet_chapters=K)` inlines snippets for last K chapters
* Older chapters get summaries only (no snippet)
* Backward compat: chapters without `text_snippet` field render exactly as before
"""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path


class RollingSummarySnippetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp(prefix="iter022_rolling_"))
        self.path = self.tmp / "rolling.json"

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_append_persists_text_snippet(self):
        from src.chapter_summary import append_chapter_summary, load_rolling_summary

        append_chapter_summary(
            chapter_no=1,
            summary="ch1 summary",
            key_events=["event A"],
            ending_state="cliffhanger",
            text_snippet="opening prose\n\n[…]\n\nending prose",
            path=self.path,
        )
        data = load_rolling_summary(self.path)
        self.assertEqual(len(data["chapters"]), 1)
        entry = data["chapters"][0]
        self.assertEqual(entry["text_snippet"], "opening prose\n\n[…]\n\nending prose")

    def test_render_includes_snippet_for_recent_chapters_only(self):
        from src.chapter_summary import append_chapter_summary, render_rolling_context

        for i in range(1, 6):
            append_chapter_summary(
                chapter_no=i,
                summary=f"ch{i} summary text",
                key_events=[f"event{i}"],
                text_snippet=f"SNIPPET-{i}",
                path=self.path,
            )
        # max_chapters=5, snippet_chapters=2 → only ch4 + ch5 snippets shown
        rendered = render_rolling_context(
            max_chapters=5, path=self.path, snippet_chapters=2
        )
        # Older chapters' snippets do NOT appear
        self.assertNotIn("SNIPPET-1", rendered)
        self.assertNotIn("SNIPPET-2", rendered)
        self.assertNotIn("SNIPPET-3", rendered)
        # Last 2 chapters' snippets DO appear
        self.assertIn("SNIPPET-4", rendered)
        self.assertIn("SNIPPET-5", rendered)
        # Summary anchor "原文片段" appears at least once
        self.assertIn("原文片段", rendered)

    def test_render_backward_compat_no_snippet_field(self):
        # Manually write old-style data lacking text_snippet field
        old = {
            "chapters": [
                {
                    "chapter_no": 1,
                    "summary": "old ch1",
                    "key_events": ["e1"],
                    "ending_state": "end1",
                },
            ],
            "compressed_older": [],
        }
        self.path.write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
        from src.chapter_summary import render_rolling_context

        rendered = render_rolling_context(
            max_chapters=5, path=self.path, snippet_chapters=2
        )
        self.assertIn("old ch1", rendered)
        # No "原文片段" header because no snippet was provided
        self.assertNotIn("原文片段", rendered)


if __name__ == "__main__":
    unittest.main()
