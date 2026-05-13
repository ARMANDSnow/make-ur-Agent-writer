import unittest

from pydantic import ValidationError

from src.llm_client import LLMClient
from src.schemas import ChapterExtraction
from src.utils import extract_json_object


class SchemaAndMockLLMTests(unittest.TestCase):
    def test_schema_rejects_missing_required_fields(self) -> None:
        with self.assertRaises(ValidationError):
            ChapterExtraction(chapter_id="x", volume_id="v", summary="missing title")

    def test_extract_json_object_from_markdown_fence(self) -> None:
        self.assertEqual(extract_json_object("```json\n{\"a\": 1}\n```"), "{\"a\": 1}")

    def test_mock_llm_returns_chapter_extraction(self) -> None:
        client = LLMClient("extract")
        result = client.complete_json(
            [{"role": "user", "content": "chapter_id: c1\nvolume_id: v1\ntitle: 标题"}],
            ChapterExtraction,
        )
        self.assertEqual(result.chapter_id, "c1")
        self.assertEqual(result.volume_id, "v1")
        self.assertEqual(result.title, "标题")


if __name__ == "__main__":
    unittest.main()
