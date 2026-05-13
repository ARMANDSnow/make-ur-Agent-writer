import json
import types
import tempfile
import unittest
from pathlib import Path
from unittest.mock import PropertyMock, patch

from src.llm_client import LLMClient


class LLMClientCacheTests(unittest.TestCase):
    def test_cache_segments_add_cache_control_when_enabled(self) -> None:
        client = LLMClient("write")
        client.config["cache_enabled"] = True
        prepared = client._prepare_messages(
            [],
            [
                {"role": "system", "content": "stable", "cache": True},
                {"role": "user", "content": "dynamic", "cache": False},
            ],
        )
        self.assertEqual(prepared[0]["cache_control"], {"type": "ephemeral"})
        self.assertNotIn("cache_control", prepared[1])

    def test_logs_provider_cache_usage(self) -> None:
        class FakeResponse(dict):
            pass

        fake_response = FakeResponse(
            {
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 2, "cache_read_tokens": 7, "cache_write_tokens": 3},
            }
        )

        with tempfile.TemporaryDirectory() as tmp:
            fake_litellm = types.SimpleNamespace(completion=lambda **_: fake_response)
            with patch("src.llm_client.ROOT", Path(tmp)), patch.dict(
                "sys.modules", {"litellm": fake_litellm}
            ), patch.object(LLMClient, "is_mock", new_callable=PropertyMock) as is_mock:
                is_mock.return_value = False
                client = LLMClient("write")
                client.complete_text([{"role": "user", "content": "hi"}])
                row = json.loads((Path(tmp) / "logs" / "llm_calls.jsonl").read_text(encoding="utf-8").splitlines()[0])
        self.assertEqual(row["cache_read_tokens"], 7)
        self.assertEqual(row["cache_write_tokens"], 3)

    def test_cache_control_downgrades_when_provider_rejects_it(self) -> None:
        calls = []

        def fake_completion(**kwargs):
            calls.append(kwargs["messages"])
            if any("cache_control" in message for message in kwargs["messages"]):
                raise RuntimeError("provider rejected cache_control")
            return {"choices": [{"message": {"content": "ok"}}], "usage": {"prompt_tokens": 5, "completion_tokens": 1}}

        with tempfile.TemporaryDirectory() as tmp:
            fake_litellm = types.SimpleNamespace(completion=fake_completion)
            with patch("src.llm_client.ROOT", Path(tmp)), patch.dict(
                "sys.modules", {"litellm": fake_litellm}
            ), patch.object(LLMClient, "is_mock", new_callable=PropertyMock) as is_mock:
                is_mock.return_value = False
                client = LLMClient("write")
                client.config["cache_enabled"] = True
                text = client.complete_text(
                    [{"role": "user", "content": "fallback"}],
                    cache_segments=[{"role": "user", "content": "stable", "cache": True}],
                )
        self.assertEqual(text, "ok")
        self.assertIn("cache_control", calls[0][0])
        self.assertNotIn("cache_control", calls[1][0])


if __name__ == "__main__":
    unittest.main()
