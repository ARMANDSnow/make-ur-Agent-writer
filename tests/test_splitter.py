import tempfile
import unittest
from pathlib import Path

from src.chapter_splitter import _heading_confidence, candidate_headings, split_file


class SplitterTests(unittest.TestCase):
    def test_skips_dense_toc_but_keeps_repeated_first_chapter(self) -> None:
        lines = [
            "目录",
            "第一章 风与潮之夜",
            "第二章 浩劫的轮回",
            "第三章 老板",
            "第四章 檀香味头发的女孩",
            "第五章 荆棘丛中的男孩",
            "第一章 风与潮之夜",
            "正文一",
            "第二章 浩劫的轮回",
            "正文二",
        ]
        headings = candidate_headings(lines, "longzu_3_2")
        self.assertEqual(headings[0], (7, "第一章 风与潮之夜"))
        self.assertEqual(len(headings), 2)

    def test_excludes_chapter_end_marker(self) -> None:
        lines = ["第一幕 开始", "正文", "第一幕完", "第二幕 后续", "正文"]
        headings = candidate_headings(lines, "longzu_1")
        self.assertEqual(headings, [(1, "第一幕 开始"), (4, "第二幕 后续")])

    def test_split_file_builds_manifest_entries(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "longzu_4.txt"
            path.write_text("楔子\n正文\n第一章 开始\n正文", encoding="utf-8")
            entries = split_file(path)
        self.assertEqual([e.title for e in entries], ["楔子", "第一章 开始"])
        self.assertEqual(entries[0].chapter_id, "longzu_4_ch001")

    def test_long_normal_chapter_has_full_confidence(self) -> None:
        self.assertEqual(_heading_confidence("第一幕 开始", 5000, False), 1.0)

    def test_short_chapter_caps_confidence(self) -> None:
        # char_count < 500 => length_score=0.4 dominates regardless of pattern.
        self.assertLessEqual(_heading_confidence("第一幕 开始", 200, False), 0.4)

    def test_dedup_risk_zone_caps_confidence(self) -> None:
        # 早期密集区幸存者：position_score=0.7 主导。
        self.assertLessEqual(_heading_confidence("第一幕 开始", 5000, True), 0.7)

    def test_split_file_writes_confidence_for_long_chapter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "longzu_5.txt"
            body = "正文" * 1000
            path.write_text(f"第一幕 起始\n{body}\n第二幕 后续\n{body}", encoding="utf-8")
            entries = split_file(path)
        self.assertEqual(entries[0].confidence, 1.0)


if __name__ == "__main__":
    unittest.main()
