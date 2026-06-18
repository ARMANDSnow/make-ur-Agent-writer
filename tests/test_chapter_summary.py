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

    def test_compressed_older_accumulates(self) -> None:
        # iter057 HIGH-2: append 超过近场窗口(5)后,滑出的章被确定性 compact 进
        # compressed_older(此前零写盘,older 记忆只能靠 render 砍 12 字残片)。
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rolling.json"
            for idx in range(1, 9):  # 8 章
                append_chapter_summary(
                    idx, f"第{idx}章发生了重要的事情。后续展开",
                    [f"事件{idx}"], f"结尾{idx}", path=path)
            data = load_rolling_summary(path)
        # 8 章 - 近场 5 = ch1,2,3 滑出窗口 → 累积进 compressed_older
        self.assertEqual([item["chapter_no"] for item in data["compressed_older"]], [1, 2, 3])
        # compact 行取 summary 首句(非 12 字残片)
        self.assertIn("第1章发生了重要的事情", data["compressed_older"][0]["text"])

    def test_render_uses_compressed_older(self) -> None:
        # 早期章(ch1)经 compressed_older 在 render 中仍可见,不再被 [-10:] 挤丢。
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rolling.json"
            for idx in range(1, 11):  # 10 章
                append_chapter_summary(
                    idx, f"第{idx}章梗概首句。细节", [f"事件{idx}"], f"结尾{idx}", path=path)
            rendered = render_rolling_context(max_chapters=3, path=path)
        self.assertIn("更早章节梗概", rendered)
        self.assertIn("第1章", rendered)  # 早期章可见(此前会被砍丢)
        self.assertIn("第5章", rendered)

    def test_prune_rewinds_compressed_older(self) -> None:
        # iter057 HIGH-2: prune 同步回退 compressed_older,避免被重写章的旧紧凑行残留毒化。
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "rolling.json"
            for idx in range(1, 9):
                append_chapter_summary(idx, f"第{idx}章。x", [f"事件{idx}"], f"结尾{idx}", path=path)
            prune_from_chapter(3, path=path)  # 删 ch3 及之后
            data = load_rolling_summary(path)
        # ch3+ 的紧凑行被回退,只剩 ch1,2
        self.assertEqual([item["chapter_no"] for item in data["compressed_older"]], [1, 2])
        self.assertEqual([item["chapter_no"] for item in data["chapters"]], [1, 2])


if __name__ == "__main__":
    unittest.main()
