"""Tests for iter 027 LLMClient streaming support.

Streaming exists so long generations bypass Cloudflare's ~100s 524 by
receiving SSE chunks within the window. These tests cover:

  - normal stream: 3 chunks + a final usage-only chunk → joined output and
    one _log_call record with usage from the stream.
  - mid-stream exception → retry from scratch; partial output discarded.
  - missing usage on final chunk → fallback to tiktoken estimate, logged
    response_tokens > 0.
  - OPENAI_STREAM=1 env opt-in: complete_text without an explicit stream
    kwarg still goes through the stream path.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, Iterator, List
from unittest.mock import PropertyMock, patch

from src.llm_client import LLMClient


def _chunk(content: str = "", usage: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """Build a litellm-style SSE chunk dict."""
    chunk: Dict[str, Any] = {
        "choices": [{"delta": {"content": content} if content else {}}],
    }
    if usage is not None:
        chunk["usage"] = usage
    return chunk


def _make_stream(chunks: List[Dict[str, Any]]) -> Iterator[Dict[str, Any]]:
    for c in chunks:
        yield c


class LLMClientStreamingTests(unittest.TestCase):
    def _read_log(self, tmp: str) -> List[Dict[str, Any]]:
        log_path = Path(tmp) / "logs" / "llm_calls.jsonl"
        return [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]

    def test_stream_joins_chunks_and_logs_usage_once(self) -> None:
        chunks = [
            _chunk("Hello "),
            _chunk("world"),
            _chunk("!"),
            _chunk(usage={"prompt_tokens": 7, "completion_tokens": 3}),
        ]
        captured: Dict[str, Any] = {}

        def fake_completion(**kwargs: Any) -> Iterator[Dict[str, Any]]:
            captured.update(kwargs)
            return _make_stream(chunks)

        with tempfile.TemporaryDirectory() as tmp:
            with patch("src.llm_client.ROOT", Path(tmp)):
                client = LLMClient("write")
                with patch.object(LLMClient, "is_mock", new_callable=PropertyMock) as mock_prop:
                    mock_prop.return_value = False
                    with patch("litellm.completion", side_effect=fake_completion):
                        text = client.complete_text(
                            [{"role": "user", "content": "hi"}], stream=True
                        )
            rows = self._read_log(tmp)

        self.assertEqual(text, "Hello world!")
        self.assertTrue(captured.get("stream"))
        self.assertEqual(captured.get("stream_options"), {"include_usage": True})
        self.assertEqual(len(rows), 1, f"expected exactly one log row, got {rows}")
        row = rows[0]
        self.assertEqual(row["status"], "ok")
        self.assertEqual(row["prompt_tokens"], 7)
        self.assertEqual(row["response_tokens"], 3)

    def test_stream_retries_after_mid_stream_exception(self) -> None:
        def bad_stream() -> Iterator[Dict[str, Any]]:
            yield _chunk("partial-")
            raise ConnectionError("simulated mid-stream drop")

        good_chunks = [
            _chunk("good "),
            _chunk("answer"),
            _chunk(usage={"prompt_tokens": 5, "completion_tokens": 2}),
        ]

        call_count = {"n": 0}

        def fake_completion(**kwargs: Any) -> Iterator[Dict[str, Any]]:
            call_count["n"] += 1
            if call_count["n"] == 1:
                return bad_stream()
            return _make_stream(good_chunks)

        with tempfile.TemporaryDirectory() as tmp:
            with patch("src.llm_client.ROOT", Path(tmp)):
                client = LLMClient("write")
                # Need at least 2 attempts for retry to fire.
                client.config["retry_attempts"] = 2
                client.config["retry_backoff_seconds"] = 0
                with patch.object(LLMClient, "is_mock", new_callable=PropertyMock) as mock_prop:
                    mock_prop.return_value = False
                    with patch("litellm.completion", side_effect=fake_completion):
                        text = client.complete_text(
                            [{"role": "user", "content": "hi"}], stream=True
                        )
            rows = self._read_log(tmp)

        self.assertEqual(text, "good answer")
        self.assertEqual(call_count["n"], 2)
        # Only the successful attempt logs; failures only log on final give-up.
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "ok")
        self.assertEqual(rows[0]["attempt"], 2)
        # Crucially the partial "partial-" must NOT leak into the result.
        self.assertNotIn("partial", text)

    def test_stream_falls_back_to_tiktoken_when_usage_missing(self) -> None:
        chunks = [
            _chunk("一段相当长的回应文本，用来确保 tiktoken 估算出非零的 token 数。"),
            _chunk("再来一段，凑够若干 token。"),
        ]

        def fake_completion(**kwargs: Any) -> Iterator[Dict[str, Any]]:
            return _make_stream(chunks)

        with tempfile.TemporaryDirectory() as tmp:
            with patch("src.llm_client.ROOT", Path(tmp)):
                client = LLMClient("write")
                with patch.object(LLMClient, "is_mock", new_callable=PropertyMock) as mock_prop:
                    mock_prop.return_value = False
                    with patch("litellm.completion", side_effect=fake_completion):
                        text = client.complete_text(
                            [{"role": "user", "content": "hi"}], stream=True
                        )
            rows = self._read_log(tmp)

        self.assertTrue(text.startswith("一段相当长"))
        self.assertEqual(len(rows), 1)
        # Usage absent → record falls back to tiktoken-counted response_tokens.
        self.assertGreater(rows[0]["response_tokens"], 0)
        # And prompt_tokens still comes from the request_meta estimate, not 0.
        self.assertGreater(rows[0]["prompt_tokens"], 0)

    def test_openai_stream_env_enables_streaming_by_default(self) -> None:
        chunks = [
            _chunk("env-stream "),
            _chunk("path"),
            _chunk(usage={"prompt_tokens": 4, "completion_tokens": 2}),
        ]
        captured: Dict[str, Any] = {}

        def fake_completion(**kwargs: Any) -> Iterator[Dict[str, Any]]:
            captured.update(kwargs)
            return _make_stream(chunks)

        env = dict(os.environ)
        env["OPENAI_STREAM"] = "1"
        with patch.dict(os.environ, env, clear=True):
            with tempfile.TemporaryDirectory() as tmp:
                with patch("src.llm_client.ROOT", Path(tmp)):
                    client = LLMClient("write")
                    self.assertTrue(client.stream_default)
                    with patch.object(LLMClient, "is_mock", new_callable=PropertyMock) as mock_prop:
                        mock_prop.return_value = False
                        with patch("litellm.completion", side_effect=fake_completion):
                            # No explicit stream= kwarg; env should drive it.
                            text = client.complete_text(
                                [{"role": "user", "content": "hi"}]
                            )

        self.assertEqual(text, "env-stream path")
        self.assertTrue(captured.get("stream"))
        self.assertEqual(captured.get("stream_options"), {"include_usage": True})


if __name__ == "__main__":
    unittest.main()
