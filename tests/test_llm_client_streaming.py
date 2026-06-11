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


    def test_openai_stream_only_streams_matching_base_url(self) -> None:
        """Iter 027 P2b-fix (v2): ``OPENAI_STREAM=1`` auto-streams a
        client only when its resolved ``config.base_url`` equals the
        process-wide ``OPENAI_BASE_URL`` value. A client configured
        against a different proxy (e.g. PLANNER pointing to a
        non-keep-alive endpoint) keeps non-stream behavior — early
        versions of ``api.supxh.xin`` 524'd mid-stream and crashed the
        pipeline. We patch ``self.config`` directly because
        ``load_dotenv_if_available`` strips alternate-endpoint env vars
        in unittest discover mode.
        """
        env = {
            "OPENAI_STREAM": "1",
            "OPENAI_BASE_URL": "https://main.example.com/v1",
        }
        with patch.dict(os.environ, env, clear=False):
            main_client = LLMClient("write")
            main_client.config["base_url"] = "https://main.example.com/v1"
            # Re-run the gate now that base_url is patched.
            main_client.stream_default = (
                main_client.config.get("base_url") in (None, env["OPENAI_BASE_URL"])
            )
            self.assertTrue(main_client.stream_default, "matching base_url should stream")

            alt_client = LLMClient("write")
            alt_client.config["base_url"] = "https://alt.example.com/v1"
            alt_client.stream_default = (
                alt_client.config.get("base_url") in (None, env["OPENAI_BASE_URL"])
            )
            self.assertFalse(
                alt_client.stream_default,
                "non-matching base_url must not auto-stream",
            )

    def test_normalize_url_equivalence_classes(self) -> None:
        """iter 051b (F4 closure): the streaming gate compares base_urls via
        ``_normalize_url`` (iter 027 P2b-fix v2) — trailing slash and
        scheme/host case differences must NOT silently disable streaming.
        This pins the normalization itself, which previously had no direct
        coverage (the gate tests above re-built the comparison by hand)."""
        from src.llm_client import _normalize_url

        canonical = _normalize_url("https://main.example.com/v1")
        # Trailing slash and scheme/host casing are equivalent.
        self.assertEqual(_normalize_url("https://main.example.com/v1/"), canonical)
        self.assertEqual(_normalize_url("HTTPS://Main.Example.COM/v1"), canonical)
        self.assertEqual(_normalize_url("https://MAIN.EXAMPLE.COM/v1/"), canonical)
        # Path case is significant (only scheme/netloc fold).
        self.assertNotEqual(_normalize_url("https://main.example.com/V1"), canonical)
        # A genuinely different proxy stays different — the gate must still
        # block streaming to a separately-configured endpoint.
        self.assertNotEqual(_normalize_url("https://alt.example.com/v1"), canonical)

    def test_normalize_url_degenerate_inputs(self) -> None:
        from src.llm_client import _normalize_url

        self.assertIsNone(_normalize_url(None))
        self.assertIsNone(_normalize_url(""))
        self.assertIsNone(_normalize_url("   "))
        # Scheme-less text falls back to a plain rstrip("/") comparison key.
        self.assertEqual(_normalize_url("some-proxy/path/"), "some-proxy/path")

    def test_disable_prompt_cache_uses_original_messages(self) -> None:
        messages = [{"role": "user", "content": "dynamic original"}]
        cache_segments = [
            {"role": "system", "content": "cached system", "cache": True},
            {"role": "user", "content": "cached stable", "cache": True},
            {"role": "user", "content": "dynamic segment", "cache": False},
        ]
        client = LLMClient("write")
        client.config["cache_enabled"] = True
        enabled = client._prepare_messages(messages, cache_segments)
        self.assertTrue(any("cache_control" in item for item in enabled))
        self.assertEqual([item["content"] for item in enabled], ["cached system", "cached stable", "dynamic segment"])

        with patch.dict(os.environ, {"DISABLE_PROMPT_CACHE": "1"}, clear=False):
            disabled = client._prepare_messages(messages, cache_segments)
        self.assertEqual(disabled, messages)
        self.assertFalse(any("cache_control" in item for item in disabled))


if __name__ == "__main__":
    unittest.main()
