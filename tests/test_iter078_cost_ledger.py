"""iter078 P1-2：预算账本三重失真回归。

六方审查确认的三个失真点：①单价硬编码 deepseek（换 model 账本静默失真）；
②N 次重试只在循环外记 1 条 error → N-1 次真实 API 调用的 prompt 消耗漏账；
③llm_calls.jsonl 脏行 JSONDecodeError 静默归零。

修复语义钉死：MODEL_PRICING 按前缀查表（mock=0 / 未知前缀回落 deepseek
现值 + 单次 WARN）；estimate_cost_since 逐 record 按其 model 计价；
complete_text 每个失败 attempt 记 retry_error（带 prompt_tokens），终态
error 条 token 置零 + final_of_attempts 防双计；dirty_lines 计数透出。

全部 mock / 打桩 litellm.completion（铁律③，零真实网络）。
"""

from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from src import cost_estimator
from src.cost_estimator import cost_cny, estimate_cost_since

from tests.test_book_driver import _WorkspaceMixin


class ModelPricingTests(unittest.TestCase):
    def setUp(self) -> None:
        cost_estimator._UNKNOWN_MODEL_WARNED.clear()

    def test_legacy_call_without_model_byte_compatible(self) -> None:
        # 旧调用方（不带 model）必须与 iter078 前逐字节同值
        legacy = cost_cny(1_000_000, 200_000, 100_000)
        expected = (
            (800_000 * 0.27 + 200_000 * 0.07 + 100_000 * 1.10) / 1e6 * 7.2
        )
        self.assertAlmostEqual(legacy, expected)

    def test_deepseek_prefix_matches_legacy(self) -> None:
        self.assertAlmostEqual(
            cost_cny(1000, 0, 500, model="deepseek/deepseek-chat"),
            cost_cny(1000, 0, 500),
        )

    def test_mock_model_costs_zero(self) -> None:
        self.assertEqual(cost_cny(1_000_000, 0, 1_000_000, model="mock"), 0.0)

    def test_unknown_model_falls_back_with_single_warn(self) -> None:
        stderr = io.StringIO()
        with redirect_stderr(stderr):
            first = cost_cny(1000, 0, 500, model="gpt-4o")
            second = cost_cny(1000, 0, 500, model="gpt-4o")
        self.assertAlmostEqual(first, cost_cny(1000, 0, 500))
        self.assertAlmostEqual(second, first)
        self.assertEqual(stderr.getvalue().count("MODEL_PRICING"), 1, "WARN 应进程内单次")


class EstimateCostSinceTests(unittest.TestCase):
    def setUp(self) -> None:
        cost_estimator._UNKNOWN_MODEL_WARNED.clear()
        cost_estimator._DIRTY_LINES_WARNED.clear()

    def _write_log(self, root: Path, lines: list) -> None:
        log = root / "logs" / "llm_calls.jsonl"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(
            "\n".join(
                line if isinstance(line, str) else json.dumps(line, ensure_ascii=False)
                for line in lines
            )
            + "\n",
            encoding="utf-8",
        )

    def test_per_record_pricing_and_dirty_lines(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_log(
                root,
                [
                    {"model": "mock", "prompt_tokens": 500_000, "response_tokens": 500_000},
                    {"model": "deepseek/deepseek-chat", "prompt_tokens": 1_000_000, "response_tokens": 100_000},
                    '{"model": "deepseek/deepseek-chat", "prompt_tokens": 99999',  # 脏行（截断）
                ],
            )
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                out = estimate_cost_since(0, root=root)
        # mock 记 0，deepseek 按现值——总额 = 仅 deepseek 行
        expected = round(cost_cny(1_000_000, 0, 100_000), 4)
        self.assertAlmostEqual(out["cost_cny"], expected)
        # token 汇总保持全量（形状不变），脏行计数透出 + WARN
        self.assertEqual(out["prompt_tokens"], 1_500_000)
        self.assertEqual(out["calls"], 2)
        self.assertEqual(out["dirty_lines"], 1)
        self.assertIn("无法解析", stderr.getvalue())

    def test_zeroed_final_error_record_adds_nothing(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._write_log(
                root,
                [
                    {"model": "deepseek/x", "status": "retry_error", "attempt": 1, "prompt_tokens": 1000, "response_tokens": 0},
                    {"model": "deepseek/x", "status": "retry_error", "attempt": 2, "prompt_tokens": 1000, "response_tokens": 0},
                    {"model": "deepseek/x", "status": "error", "final_of_attempts": 2, "prompt_tokens": 0, "response_tokens": 0},
                ],
            )
            out = estimate_cost_since(0, root=root)
        self.assertEqual(out["prompt_tokens"], 2000)
        self.assertAlmostEqual(out["cost_cny"], round(cost_cny(2000, 0, 0), 4))


class RetryErrorLoggingTests(_WorkspaceMixin, unittest.TestCase):
    """complete_text 真路径（litellm 打桩，零网络）：逐 attempt 入账。

    注意：unittest 下 config.load_dotenv_if_available 每次强制
    OPENAI_MODEL=mock（铁律③硬门），env patch 打不过——所以不碰 env，直接
    把 client 实例的 model 换成非 mock（is_mock 是基于 self.model 的
    property），litellm.completion 全程打桩保证零网络。"""

    def setUp(self) -> None:
        self.ws = self._make_workspace("iter078ledger_")

    def _log_records(self) -> list:
        log = self.ws / "logs" / "llm_calls.jsonl"
        if not log.exists():
            return []
        return [
            json.loads(line)
            for line in log.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def test_each_failed_attempt_logged_final_error_zeroed(self) -> None:
        from src.llm_client import LLMClient

        client = LLMClient("write")
        client.model = "deepseek/deepseek-chat"  # 见类 docstring
        client.config["retry_attempts"] = 2
        client.config["retry_backoff_seconds"] = 0
        client.config["retry_backoff_cap_seconds"] = 0
        client.config["retry_backoff_jitter_seconds"] = 0
        client.config.pop("base_url", None)
        client.config.pop("api_key", None)
        self.assertFalse(client.is_mock)

        with patch("litellm.completion", side_effect=ConnectionError("boom")), patch.object(
            client, "stream_default", False, create=True
        ):
            with self.assertRaises(RuntimeError):
                client.complete_text([{"role": "user", "content": "测试" * 50}])

        records = self._log_records()
        retry_rows = [r for r in records if r.get("status") == "retry_error"]
        error_rows = [r for r in records if r.get("status") == "error"]
        self.assertEqual(len(retry_rows), 1, records)
        self.assertEqual([r.get("attempt") for r in retry_rows], [1])
        for row in retry_rows:
            self.assertGreater(row.get("prompt_tokens", 0), 0, "retry_error 必须带 prompt 消耗")
        self.assertEqual(len(error_rows), 1)
        self.assertEqual(error_rows[0].get("prompt_tokens"), 0, "终态 error 条防双计")
        self.assertEqual(error_rows[0].get("final_of_attempts"), 1)

    def test_retry_error_log_redacts_keys_and_prompt_payload(self) -> None:
        from src.llm_client import LLMClient

        client = LLMClient("write")
        client.model = "deepseek/deepseek-chat"
        client.config["retry_attempts"] = 1
        client.config["retry_backoff_seconds"] = 0
        client.config["api_key"] = "configured-secret-key-123456"
        client.config.pop("base_url", None)

        leaked = (
            "Authorization: Bearer sk-leakedabcdef1234567890XYZ "
            "bare sk-anotherbarekey9876543210abcdef "
            "api_key=configured-secret-key-123456 "
            "messages=[{'role':'user','content':'SECRET_PROMPT_SHOULD_NOT_BE_LOGGED'}]"
        )
        with patch("litellm.completion", side_effect=RuntimeError(leaked)), patch.object(
            client, "stream_default", False, create=True
        ):
            with self.assertRaises(RuntimeError):
                client.complete_text([{"role": "user", "content": "SECRET_PROMPT_SHOULD_NOT_BE_LOGGED"}])

        text = (self.ws / "logs" / "llm_calls.jsonl").read_text(encoding="utf-8")
        self.assertIn("retry_error", text)
        self.assertIn("error", text)
        self.assertIn("Bearer ***", text)
        self.assertIn("sk-***", text)
        self.assertNotIn("sk-leakedabcdef1234567890XYZ", text)
        self.assertNotIn("sk-anotherbarekey9876543210abcdef", text)
        self.assertNotIn("configured-secret-key-123456", text)
        self.assertNotIn("SECRET_PROMPT_SHOULD_NOT_BE_LOGGED", text)


if __name__ == "__main__":
    unittest.main()
