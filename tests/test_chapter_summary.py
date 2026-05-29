import json
import tempfile
import unittest
from pathlib import Path

from src.chapter_summary import (
    append_chapter_summary,
    load_rolling_summary,
    prune_from_chapter,
    render_rolling_context,
    save_rolling_summary,
)


class ChapterSummaryTests(unittest.TestCase):
    def test_load_save_append_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rolling.json"
            save_rolling_summary({"chapters": [], "compressed_older": []}, path=path)
            append_chapter_summary(1, "第一章摘要", ["事件一"], "停在门口", path=path)
            data = load_rolling_summary(path)
        self.assertEqual(data["chapters"][0]["chapter_no"], 1)
        self.assertEqual(data["chapters"][0]["ending_state"], "停在门口")

    def test_render_recent_and_compresses_older_events(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rolling.json"
            for idx in range(1, 5):
                append_chapter_summary(idx, f"第{idx}章摘要", [f"第{idx}章关键事件很长"], f"第{idx}章结尾", path=path)
            rendered = render_rolling_context(max_chapters=2, path=path)
        self.assertIn("更早章节关键事件", rendered)
        self.assertIn("第 3 章", rendered)
        self.assertIn("第 4 章", rendered)
        self.assertNotIn("### 第 1 章", rendered)
        self.assertIn("结尾状态: 第4章结尾", rendered)

    def test_missing_file_degrades_to_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing.json"
            self.assertEqual(load_rolling_summary(path), {"chapters": [], "compressed_older": []})
            self.assertEqual(render_rolling_context(path=path), "")

    def test_prune_from_chapter_drops_failed_retry_tail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rolling.json"
            for idx in range(1, 5):
                append_chapter_summary(idx, f"第{idx}章摘要", [f"事件{idx}"], f"结尾{idx}", path=path)

            prune_from_chapter(3, path=path)
            data = load_rolling_summary(path)

        self.assertEqual([item["chapter_no"] for item in data["chapters"]], [1, 2])


if __name__ == "__main__":
    unittest.main()
