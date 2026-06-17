"""iter055 轨A: per-call timeout plumbing.

``request_timeout`` 经 ``get_model_config`` **显式映射**(非靠 models.yaml default 块
"自动透传" —— 那段 ``**{...}`` 只透传 ``task_cfg`` 的 key、不含 default 块,不显式映射
则恒 None、超时静默失效)进 ``self.config``,再注入 ``litellm.completion`` 的 ``timeout=``
kwarg。分任务超时(iter055 真模型实测调高: 中转站 + gpt-5.5-low reasoning 单章 extract
实测 294s): extract 400 / write 480 / plot_planner 600 / default 240。未配(=0)时不含
timeout key(字节兼容 iter055 之前)。``LLM_REQUEST_TIMEOUT`` env 优先(实跑现场调旋钮)。
批处理任务 stream:false 让非流式 litellm 真执行 timeout(流式下 litellm 不落 read 超时)。
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict
from unittest.mock import PropertyMock, patch

from src.llm_client import LLMClient


def _non_stream_response(content: str = "ok") -> Dict[str, Any]:
    return {"choices": [{"message": {"content": content}}]}


class LLMClientTimeoutTests(unittest.TestCase):
    def _capture_completion_kwargs(self, task: str, *, request_timeout_override: Any = None):
        captured: Dict[str, Any] = {}

        def fake_completion(**kwargs: Any) -> Dict[str, Any]:
            captured.update(kwargs)
            return _non_stream_response()

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LLM_REQUEST_TIMEOUT", None)
            os.environ.pop("OPENAI_STREAM", None)
            with tempfile.TemporaryDirectory() as tmp:
                with patch("src.llm_client.ROOT", Path(tmp)):
                    client = LLMClient(task)
                    if request_timeout_override is not None:
                        client.config["request_timeout"] = request_timeout_override
                    with patch.object(LLMClient, "is_mock", new_callable=PropertyMock) as mp:
                        mp.return_value = False
                        with patch("litellm.completion", side_effect=fake_completion):
                            client.complete_text([{"role": "user", "content": "hi"}], stream=False)
        return client, captured

    def test_extract_task_timeout_400(self) -> None:
        client, captured = self._capture_completion_kwargs("extract")
        # iter055 真模型实测修正: extract 自有 request_timeout 400(实测单章 294s + 余量);
        # 显式映射 + 非流式(stream:false)让 litellm 真执行此 timeout。
        self.assertEqual(client.config["request_timeout"], 400)
        self.assertEqual(captured.get("timeout"), 400.0)

    def test_write_task_timeout_480(self) -> None:
        client, captured = self._capture_completion_kwargs("write")
        # write 8000 tokens 给足 480(write 保流式,此值在 idle-deadline 落地前为名义上限)。
        self.assertEqual(client.config["request_timeout"], 480)
        self.assertEqual(captured.get("timeout"), 480.0)

    def test_num_retries_zero_passed(self) -> None:
        # iter055 真模型实测修正: 自管重试(轨B),禁 litellm 内部重试(免叠加放大墙钟/绕过分类)。
        _client, captured = self._capture_completion_kwargs("extract")
        self.assertEqual(captured.get("num_retries"), 0)

    def test_zero_timeout_omits_kwarg_byte_compatible(self) -> None:
        # request_timeout=0 → 不注入 timeout key（与 iter055 之前逐字节一致）。
        _client, captured = self._capture_completion_kwargs("extract", request_timeout_override=0)
        self.assertNotIn("timeout", captured)

    def test_env_var_overrides_config_value(self) -> None:
        # LLM_REQUEST_TIMEOUT 优先于 config（V2: 临时设 5 故意触发超时验证非无限挂）。
        with patch.dict(os.environ, {"LLM_REQUEST_TIMEOUT": "5"}, clear=False):
            client = LLMClient("extract")
        self.assertEqual(client.config["request_timeout"], 5.0)

    def test_ping_includes_timeout(self) -> None:
        captured: Dict[str, Any] = {}

        def fake_completion(**kwargs: Any) -> Dict[str, Any]:
            captured.update(kwargs)
            return _non_stream_response()

        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LLM_REQUEST_TIMEOUT", None)
            client = LLMClient("extract")
            with patch.object(LLMClient, "is_mock", new_callable=PropertyMock) as mp:
                mp.return_value = False
                with patch("litellm.completion", side_effect=fake_completion):
                    result = client.ping()
        self.assertTrue(result["ok"])
        self.assertEqual(captured.get("timeout"), 400.0)  # ping 用 extract 任务 → 400


if __name__ == "__main__":
    unittest.main()
