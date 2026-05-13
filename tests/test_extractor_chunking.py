import unittest
from unittest.mock import patch

from src.extractor import _extract_chapter_data
from src.schemas import ChapterExtraction


class ExtractorChunkingTests(unittest.TestCase):
    def test_long_chapter_chunks_and_merges_character_states(self) -> None:
        entry = {
            "chapter_id": "longzu_1_ch999",
            "volume_id": "longzu_1",
            "source_file": "source.txt",
            "normalized_file": "norm.txt",
            "title": "长章节",
            "start_line": 1,
            "end_line": 100,
            "char_count": 30000,
        }
        names = ["路明非", "楚子航", "凯撒"]
        calls = {"count": 0}

        class FakeClient:
            def complete_json(self, messages, response_model):
                name = names[calls["count"]]
                calls["count"] += 1
                return ChapterExtraction(
                    chapter_id=entry["chapter_id"],
                    volume_id=entry["volume_id"],
                    title=entry["title"],
                    summary=f"{name} 分段摘要。",
                    rolling_summary=f"{name} 滚动摘要。",
                    character_states=[{"character": name, "after": "状态更新", "status": "active"}],
                    relationships=[],
                    foreshadowing=[],
                    worldbuilding=[],
                    style_samples=[],
                    evidence_spans=[],
                )

        class FakeSummarizer:
            def complete_text(self, messages, temperature=None):
                return "合并摘要。"

        settings = {
            "chunk_threshold_chars": 24000,
            "chunk_count": 3,
            "chunk_overlap_chars": 200,
        }
        with patch("src.extractor.LLMClient", return_value=FakeSummarizer()):
            data = _extract_chapter_data(entry, "龙" * 30000, [], "", FakeClient(), settings)

        self.assertEqual(calls["count"], 3)
        self.assertEqual({item["character"] for item in data["character_states"]}, set(names))
        self.assertEqual(data["summary"], "合并摘要。")


if __name__ == "__main__":
    unittest.main()
