"""iter055 轨B: 重试加固——transient 分类 + 指数退避 + cap/jitter + retry_attempts 5→3.

中转站抖动(Cloudflare Tunnel 530/1033、provider 过载 50x、连接/读取超时)是 transient,
应重试;schema/context/JSON 等确定性错立即抛(空耗重试纯浪费且掩盖 bug)。退避从线性
(iter055 前: base*attempt)改指数 base*2^(n-1) 封顶 cap + jitter 错峰(530/1033 是过载,
线性加剧拥堵)。鸭子判定(类名 + 错误串关键词)而非 isinstance(litellm.X)——litellm 跨版本
类名漂移且 requirements 未 pin;stdlib ConnectionError/TimeoutError 用 isinstance 兜(流式断流)。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import PropertyMock, patch

from src.llm_client import LLMClient, LLMContextOverflowError, _is_transient


def _ok(content: str = "ok") -> Dict[str, Any]:
    return {"choices": [{"message": {"content": content}}]}


class _NamedExc(Exception):
    """基类——子类名进 _TRANSIENT_EXC_NAMES 用于鸭子判定测试(不依赖真 litellm 类型)。"""


class RateLimitError(_NamedExc):
    pass


class APITimeoutError(_NamedExc):
    pass


class IsTransientClassificationTests(unittest.TestCase):
    """_is_transient 纯函数——分类边界,不触网。"""

    def test_stdlib_connection_and_timeout_are_transient(self) -> None:
        self.assertTrue(_is_transient(ConnectionError("simulated mid-stream drop")))
        self.assertTrue(_is_transient(TimeoutError("read timed out")))
        # 子类(连接重置/中断/断管)也兜住——流式中途断流走这里。
        self.assertTrue(_is_transient(ConnectionResetError("reset by peer")))

    def test_litellm_classnames_are_transient(self) -> None:
        # 跨版本类名漂移 → 按类名(非 isinstance)判 provider 过载/限流/超时。
        self.assertTrue(_is_transient(RateLimitError("429 Too Many Requests")))
        self.assertTrue(_is_transient(APITimeoutError("upstream timeout")))

    def test_error_string_markers_are_transient(self) -> None:
        # 中转站/网关错误码与关键词,大小写不敏感。
        self.assertTrue(_is_transient(Exception("HTTP 503 Service Unavailable")))
        self.assertTrue(_is_transient(Exception("Error 1033: Cloudflare Tunnel error")))
        self.assertTrue(_is_transient(Exception("Web server is down (Error 530)")))
        self.assertTrue(_is_transient(Exception("Connection TIMEOUT")))

    def test_context_overflow_never_transient(self) -> None:
        # context 溢出确定性,绝不重试(显式 isinstance 守卫优先于一切标记匹配)。
        self.assertFalse(_is_transient(LLMContextOverflowError("context window exceeded")))

    def test_deterministic_errors_not_transient(self) -> None:
        # schema/解析/业务错 → 立即抛,不空耗 attempts。
        self.assertFalse(_is_transient(ValueError("schema validation failed")))
        self.assertFalse(_is_transient(RuntimeError("retry boom")))  # premise_guard 现存用例
        self.assertFalse(_is_transient(KeyError("missing field")))


class RetryLoopBehaviorTests(unittest.TestCase):
    """complete_text 内部重试循环——仅 transient 重试,指数退避 + cap + jitter。"""

    def _run(self, side_effect, *, uniform_return: float = 0.0, **config_overrides):
        """非 mock client 跑 complete_text;返回 (content, err, completion 调用次数, sleep 延时序列)。"""
        sleeps: List[float] = []
        with tempfile.TemporaryDirectory() as tmp:
            with patch("src.llm_client.ROOT", Path(tmp)):
                client = LLMClient("extract")
                client.config = dict(client.config)
                client.config.update(config_overrides)
                with patch.object(LLMClient, "is_mock", new_callable=PropertyMock) as mp:
                    mp.return_value = False
                    with patch("src.llm_client.random.uniform", return_value=uniform_return), patch(
                        "src.llm_client.time.sleep", side_effect=lambda d: sleeps.append(d)
                    ), patch("litellm.completion", side_effect=side_effect) as comp:
                        try:
                            content = client.complete_text(
                                [{"role": "user", "content": "hi"}], stream=False
                            )
                            err: Exception | None = None
                        except Exception as exc:  # noqa: BLE001 —— 捕获供断言
                            content = None
                            err = exc
        return content, err, comp.call_count, sleeps

    def test_transient_retries_then_succeeds(self) -> None:
        # 两次 transient(530 + 断流)后成功 → 第三次返回内容,completion 调 3 次,sleep 2 次。
        content, err, calls, sleeps = self._run(
            side_effect=[Exception("Error 530"), ConnectionError("drop"), _ok("done")],
            retry_attempts=3,
        )
        self.assertIsNone(err)
        self.assertEqual(content, "done")
        self.assertEqual(calls, 3)
        self.assertEqual(len(sleeps), 2)

    def test_non_transient_breaks_immediately(self) -> None:
        # schema 错(非 transient)→ 立即 break,只调 1 次,绝不 sleep(治"空耗 5 次"病根)。
        _content, err, calls, sleeps = self._run(
            side_effect=ValueError("schema validation failed"),
            retry_attempts=3,
        )
        self.assertIsInstance(err, RuntimeError)
        self.assertEqual(calls, 1)
        self.assertEqual(sleeps, [])

    def test_transient_exhausts_attempts_then_raises(self) -> None:
        # 全 transient 且耗尽 → 调满 attempts 次,sleep attempts-1 次,最终抛 RuntimeError。
        _content, err, calls, sleeps = self._run(
            side_effect=ConnectionError("persistent drop"),
            retry_attempts=3,
        )
        self.assertIsInstance(err, RuntimeError)
        self.assertEqual(calls, 3)
        self.assertEqual(len(sleeps), 2)

    def test_exponential_backoff_growth(self) -> None:
        # base=1, jitter=0 → 退避 1,2,4(指数 2^(n-1),非线性 1,2,3)。
        _content, _err, _calls, sleeps = self._run(
            side_effect=ConnectionError("drop"),
            retry_attempts=4,
            retry_backoff_seconds=1,
            retry_backoff_cap_seconds=100,
            retry_backoff_jitter_seconds=0,
        )
        self.assertEqual(sleeps, [1.0, 2.0, 4.0])

    def test_backoff_capped(self) -> None:
        # base=10, cap=15 → 10,15,15(封顶,不无限翻倍烧延时)。
        _content, _err, _calls, sleeps = self._run(
            side_effect=ConnectionError("drop"),
            retry_attempts=4,
            retry_backoff_seconds=10,
            retry_backoff_cap_seconds=15,
            retry_backoff_jitter_seconds=0,
        )
        self.assertEqual(sleeps, [10.0, 15.0, 15.0])

    def test_jitter_added_to_delay(self) -> None:
        # 退避 = min(指数,cap) + uniform(0,jitter);抖动错峰避免多实例重试同步拥堵。
        _content, _err, _calls, sleeps = self._run(
            side_effect=ConnectionError("drop"),
            uniform_return=0.5,
            retry_attempts=2,
            retry_backoff_seconds=1,
            retry_backoff_cap_seconds=100,
            retry_backoff_jitter_seconds=1,
        )
        self.assertEqual(sleeps, [1.5])  # min(1*1,100)=1 + 0.5 jitter


if __name__ == "__main__":
    unittest.main()
