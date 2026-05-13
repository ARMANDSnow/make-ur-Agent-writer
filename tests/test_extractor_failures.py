import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.extractor import extract_all, retry_failures
from src.llm_client import LLMClient


class ExtractorFailureIsolationTests(unittest.TestCase):
    def test_one_chapter_fails_others_continue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            fail_dir = tmp / "extraction_failures"
            extracted_dir = tmp / "extracted_jsons"
            rolling_dir = tmp / "rolling_summaries"
            extracted_dir.mkdir(parents=True)

            norm_dir = tmp / "normalized_texts"
            norm_dir.mkdir()
            norm_file = norm_dir / "longzu_1.txt"
            norm_file.write_text("第一章 开始\n章节正文内容\n更多内容\n第二章 继续\n第二章正文\n更多内容\n", encoding="utf-8")

            manifest = [
                {
                    "chapter_id": "longzu_1_ch001",
                    "volume_id": "longzu_1",
                    "source_file": "test.txt",
                    "normalized_file": str(norm_file),
                    "title": "第一章 开始",
                    "start_line": 1,
                    "end_line": 3,
                    "char_count": 30,
                },
                {
                    "chapter_id": "longzu_1_ch002",
                    "volume_id": "longzu_1",
                    "source_file": "test.txt",
                    "normalized_file": str(norm_file),
                    "title": "第二章 继续",
                    "start_line": 4,
                    "end_line": 6,
                    "char_count": 30,
                },
            ]

            original_complete_json = LLMClient.complete_json

            def failing_json(self, messages, response_model):
                user = "\n".join(m.get("content", "") for m in messages if m.get("role") == "user")
                if "longzu_1_ch001" in user:
                    raise RuntimeError("simulated extract failure")
                return original_complete_json(self, messages, response_model)

            with patch("src.extractor.load_manifest", return_value=manifest), patch(
                "src.extractor.EXTRACTED_DIR", extracted_dir
            ), patch("src.extractor.FAILURES_DIR", fail_dir), patch(
                "src.extractor.ROLLING_DIR", rolling_dir
            ), patch(
                "src.llm_client.LLMClient.complete_json", failing_json
            ):
                results = extract_all(volume="all", force=True)

            self.assertEqual(len(results), 1)
            self.assertEqual(results[0]["chapter_id"], "longzu_1_ch002")

            failure_file = fail_dir / "longzu_1_ch001.json"
            self.assertTrue(failure_file.exists())
            failure_data = json.loads(failure_file.read_text(encoding="utf-8"))
            self.assertEqual(failure_data["chapter_id"], "longzu_1_ch001")
            self.assertIn("simulated extract failure", failure_data["error"])
            self.assertIn("last_error", failure_data)
            self.assertEqual(failure_data["retry_count"], 1)
            self.assertTrue((rolling_dir / "longzu_1.json").exists())

    def test_retry_failures_clears_failure_after_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            fail_dir = tmp / "extraction_failures"
            extracted_dir = tmp / "extracted_jsons"
            rolling_dir = tmp / "rolling_summaries"
            fail_dir.mkdir(parents=True)
            extracted_dir.mkdir(parents=True)
            norm_file = tmp / "longzu_1.txt"
            norm_file.write_text("第一章 开始\n正文\n", encoding="utf-8")
            (fail_dir / "longzu_1_ch001.json").write_text(
                json.dumps({"chapter_id": "longzu_1_ch001", "retry_count": 1}), encoding="utf-8"
            )
            manifest = [
                {
                    "chapter_id": "longzu_1_ch001",
                    "volume_id": "longzu_1",
                    "source_file": "test.txt",
                    "normalized_file": str(norm_file),
                    "title": "第一章 开始",
                    "start_line": 1,
                    "end_line": 2,
                    "char_count": 10,
                }
            ]
            with patch("src.extractor.load_manifest", return_value=manifest), patch(
                "src.extractor.EXTRACTED_DIR", extracted_dir
            ), patch("src.extractor.FAILURES_DIR", fail_dir), patch("src.extractor.ROLLING_DIR", rolling_dir):
                results = retry_failures()
            self.assertEqual(len(results), 1)
            self.assertFalse((fail_dir / "longzu_1_ch001.json").exists())
            self.assertTrue((extracted_dir / "longzu_1_ch001.json").exists())

    def test_existing_rolling_summary_is_used_in_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            extracted_dir = tmp / "extracted_jsons"
            rolling_dir = tmp / "rolling_summaries"
            extracted_dir.mkdir(parents=True)
            rolling_dir.mkdir(parents=True)
            (rolling_dir / "longzu_1.json").write_text(
                json.dumps({"previous_summaries": ["prev summary"], "volume_summary": "volume state"}),
                encoding="utf-8",
            )
            norm_file = tmp / "longzu_1.txt"
            norm_file.write_text("第一章 开始\n正文\n", encoding="utf-8")
            manifest = [
                {
                    "chapter_id": "longzu_1_ch001",
                    "volume_id": "longzu_1",
                    "source_file": "test.txt",
                    "normalized_file": str(norm_file),
                    "title": "第一章 开始",
                    "start_line": 1,
                    "end_line": 2,
                    "char_count": 10,
                }
            ]
            captured = {}

            def capture_json(self, messages, response_model):
                captured["prompt"] = "\n".join(m.get("content", "") for m in messages)
                return LLMClient._mock_json(self, response_model, messages)

            with patch("src.extractor.load_manifest", return_value=manifest), patch(
                "src.extractor.EXTRACTED_DIR", extracted_dir
            ), patch("src.extractor.ROLLING_DIR", rolling_dir), patch(
                "src.llm_client.LLMClient.complete_json", capture_json
            ):
                extract_all(volume="all", force=True)
            self.assertIn("prev summary", captured["prompt"])
            self.assertIn("volume state", captured["prompt"])


if __name__ == "__main__":
    unittest.main()
