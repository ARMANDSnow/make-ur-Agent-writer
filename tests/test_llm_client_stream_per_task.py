"""iter055 真模型实测修正: per-task 流式开关.

V2 真模型实测发现 litellm 不把 timeout 落到流式 SSE read —— 流式下 per-call 超时失效
(timeout=5 仍跑满 294s 成功);非流式 litellm 遵守 timeout(实测 58s 触发 litellm.Timeout)。
故批处理任务(extract/compress/debate/review/premise/plot_planner)配 stream:false 走非流式
拿回超时保护。iter057 (P0-B): write 也配 stream:false —— 流式下 request_timeout 不落 SSE read,
单章卡满 driver 180min,且当前架构无流式真实消费者。per-task stream 优先于 OPENAI_STREAM env;未配则回落 env。
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.llm_client import LLMClient

_BASE = "https://relay.example/v1"


class StreamPerTaskTests(unittest.TestCase):
    def _client(self, task: str, *, stream_env: str = "1") -> LLMClient:
        # 真模型 env: OPENAI_STREAM=1 + base_url 一致(endpoint_streams=True),
        # 让 stream_default 只由 per-task stream 决定。
        env = {
            "OPENAI_STREAM": stream_env,
            "OPENAI_BASE_URL": _BASE,
            "OPENAI_MODEL": "openai/gpt-5.5-low",
            "WRITER_MODEL": "openai/gpt-5.5-low",
            "DEBATER_MODEL": "openai/gpt-5.5-low",
            "REVIEWER_MODEL": "openai/gpt-5.5-low",
        }
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("PLANNER_BASE_URL", None)  # plot_planner 回落 OPENAI_BASE_URL
            with tempfile.TemporaryDirectory() as tmp:
                with patch("src.llm_client.ROOT", Path(tmp)):
                    return LLMClient(task)

    def test_batch_tasks_non_streaming_despite_env(self) -> None:
        # OPENAI_STREAM=1 仍非流式 —— per-task stream:false 优先(拿回 litellm timeout)。
        for task in ["extract", "compress", "debate", "review", "premise_expand", "plot_planner"]:
            c = self._client(task)
            self.assertFalse(c.stream_default, f"{task} 应非流式(stream:false 覆盖 env)")

    def test_write_non_streaming_despite_env(self) -> None:
        # iter057 (P0-B): write 现配 stream:false —— 拿回 litellm read 超时(流式下
        # request_timeout 不落 SSE read,单章卡满 driver 180min)。OPENAI_STREAM=1 不再让
        # write 流式,per-task stream:false 优先于 env。当前架构无流式真实消费者(产出落盘+
        # 人工审 draft,detach stdout 进 DEVNULL),UX 损失≈零。保流式 idle-deadline 留后续。
        self.assertFalse(self._client("write", stream_env="1").stream_default)
        self.assertFalse(self._client("write", stream_env="0").stream_default)

    def test_unconfigured_task_falls_back_to_env_on(self) -> None:
        # 无 stream 配置的任务(default)回落 OPENAI_STREAM=1 —— 字节兼容旧行为。
        self.assertTrue(self._client("default", stream_env="1").stream_default)

    def test_unconfigured_task_falls_back_to_env_off(self) -> None:
        self.assertFalse(self._client("default", stream_env="0").stream_default)


if __name__ == "__main__":
    unittest.main()
