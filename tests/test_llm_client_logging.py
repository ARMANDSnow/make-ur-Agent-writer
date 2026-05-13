import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.llm_client import LLMClient, LLMContextOverflowError


class LLMClientLoggingTests(unittest.TestCase):
    def test_logs_request_hash_and_token_counts_stably(self) -> None:
        messages = [{"role": "user", "content": "同一个 prompt"}]
        with tempfile.TemporaryDirectory() as tmp:
            with patch("src.llm_client.ROOT", Path(tmp)):
                client = LLMClient("write")
                client.complete_text(messages)
                client.complete_text(messages)
                rows = [
                    json.loads(line)
                    for line in (Path(tmp) / "logs" / "llm_calls.jsonl").read_text(encoding="utf-8").splitlines()
                ]
        self.assertEqual(rows[0]["request_hash"], rows[1]["request_hash"])
        self.assertGreater(rows[0]["prompt_tokens"], 0)
        self.assertGreater(rows[0]["response_tokens"], 0)
        self.assertIn("prompt_chars", rows[0])

    def test_context_overflow_raises_before_call(self) -> None:
        client = LLMClient("write")
        client.config["context_limit"] = 10
        client.config["max_tokens"] = 10
        with self.assertRaises(LLMContextOverflowError) as raised:
            client.complete_text([{"role": "user", "content": "很长的 prompt" * 20}])
        self.assertIn("task=write", str(raised.exception))


if __name__ == "__main__":
    unittest.main()
