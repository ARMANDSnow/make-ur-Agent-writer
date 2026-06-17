"""iter 056 轨 C: 风格卡注入——仅 premise + 独立第 3 缓存段 + light 不注入 +
polish 同注入 + 续写书/无卡逐字节兼容（铁律④最高优先级回退契约）。Mock-only。
"""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import paths, writer, writer_style
from src.llm_client import LLMClient
from src.writer import _write_prompt


class _WorkspaceHarness(unittest.TestCase):
    WS = "injws"

    def setUp(self) -> None:
        os.environ["OPENAI_MODEL"] = "mock"
        self._tmp = tempfile.TemporaryDirectory()
        self._saved_ws_dir = paths.WORKSPACE_DIR
        self._saved_env = os.environ.get("WORKSPACE_NAME")
        paths.WORKSPACE_DIR = Path(self._tmp.name)
        os.environ["WORKSPACE_NAME"] = self.WS
        (paths.WORKSPACE_DIR / self.WS).mkdir(parents=True)

    def tearDown(self) -> None:
        paths.WORKSPACE_DIR = self._saved_ws_dir
        if self._saved_env is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._saved_env
        self._tmp.cleanup()

    def _prompt(self, **overrides):
        common = dict(
            chapter_no=1,
            knowledge="KB全局知识内容",
            facts="facts",
            style_examples="",
            continuation_anchor="",
            index={},
            outline="outline",
            feedback="",
        )
        common.update(overrides)
        return _write_prompt(**common)


class InjectMainPathTests(_WorkspaceHarness):
    def test_continuation_book_no_injection_byte_compat(self) -> None:
        """续写书（有起点）：block 返回 "" → 输出与"强制无卡"基线逐字节相同。"""
        writer_style.activate_preset("cold_scifi")  # 即便有卡
        with patch("src.writer_style.start_point.get_start_chapter_id", return_value="ch_0005"):
            m_real, c_real = self._prompt()
            # 基线：同一续写书状态下强制 block 返回 ""（等价"无风格卡功能"）。
            # start_point 是 writer 与 writer_style 共享的同一模块对象，故
            # canon_anchor 在两次都触发，唯一变量是 style_card。
            with patch("src.writer.writer_style.writer_style_prompt_block", return_value=""):
                m_base, c_base = self._prompt()
        self.assertEqual(m_real, m_base, "续写书 messages 必须逐字节回退")
        self.assertEqual(c_real, c_base, "续写书 cache_segments 必须逐字节回退")
        self.assertEqual(len(c_real), 3)  # 无独立 style_card 段
        self.assertNotIn("作家风格卡", "\n".join(m["content"] for m in m_real))

    def test_premise_with_card_independent_cache_segment(self) -> None:
        writer_style.activate_preset("cold_scifi")
        with patch("src.writer_style.start_point.get_start_chapter_id", return_value=None):
            messages, cache_segments = self._prompt()
        prompt = "\n".join(m["content"] for m in messages)
        self.assertIn("作家风格卡", prompt)
        self.assertIn("冷峻科幻", prompt)
        self.assertIn("以系统戒律为准", prompt)
        # 独立第 3 缓存段
        self.assertEqual(len(cache_segments), 4)
        cached = "\n".join(s["content"] for s in cache_segments if s.get("cache"))
        self.assertIn("作家风格卡", cached)
        # KB 段（stable）不含风格卡 → 改卡只失效风格段、不动 KB 缓存（HIGH-1）
        stable_seg = cache_segments[1]["content"]
        self.assertNotIn("作家风格卡", stable_seg)
        self.assertIn("KB全局知识内容", stable_seg)

    def test_premise_no_card_byte_compat(self) -> None:
        with patch("src.writer_style.start_point.get_start_chapter_id", return_value=None):
            messages, cache_segments = self._prompt()  # premise 无卡
        self.assertNotIn("作家风格卡", "\n".join(m["content"] for m in messages))
        self.assertEqual(len(cache_segments), 3)

    def test_light_profile_no_injection(self) -> None:
        writer_style.activate_preset("cold_scifi")
        with patch("src.writer_style.start_point.get_start_chapter_id", return_value=None):
            with patch.dict(os.environ, {"WRITE_PROMPT_PROFILE": "light"}, clear=False):
                messages, cache_segments = self._prompt()
        self.assertNotIn("作家风格卡", "\n".join(m["content"] for m in messages))
        self.assertEqual(len(cache_segments), 3)

    def test_premise_style_examples_and_card_coexist(self) -> None:
        """BLOCKER-1: premise 书也可能有 style_examples，两者共存、顺序正确。"""
        writer_style.activate_preset("cold_scifi")
        with patch("src.writer_style.start_point.get_start_chapter_id", return_value=None):
            messages, _cs = self._prompt(style_examples="### opening_rhythm\n\n风格样例")
        prompt = "\n".join(m["content"] for m in messages)
        self.assertIn("opening_rhythm", prompt)  # style_examples 在
        self.assertIn("作家风格卡", prompt)  # 风格卡也在
        self.assertLess(
            prompt.index("作者风格参考"), prompt.index("作家风格卡"), "style_examples 在风格卡之前"
        )


class InjectPolishTests(_WorkspaceHarness):
    def _capture_polish(self, draft="一段草稿正文。" * 30):
        captured = {}

        def fake(client, messages, cache_segments):
            captured["messages"] = messages
            captured["cache_segments"] = cache_segments
            return "polished"

        with patch("src.writer._complete_write_text", side_effect=fake):
            writer._polish_draft(
                client=LLMClient("write"),
                draft=draft,
                lint_issues=[],
                review_report={},
                style_examples="",
                continuation_anchor="",
            )
        return captured

    def test_polish_injects_for_premise(self) -> None:
        writer_style.activate_preset("cold_scifi")
        with patch("src.writer_style.start_point.get_start_chapter_id", return_value=None):
            cap = self._capture_polish()
        prompt = "\n".join(m["content"] for m in cap["messages"])
        self.assertIn("作家风格卡", prompt)
        self.assertEqual(len(cap["cache_segments"]), 4)  # 独立段

    def test_polish_continuation_byte_compat(self) -> None:
        writer_style.activate_preset("cold_scifi")
        with patch("src.writer_style.start_point.get_start_chapter_id", return_value="ch_0005"):
            cap = self._capture_polish()
        prompt = "\n".join(m["content"] for m in cap["messages"])
        self.assertNotIn("作家风格卡", prompt)
        self.assertEqual(len(cap["cache_segments"]), 3)  # 无注入、无空段


if __name__ == "__main__":
    unittest.main()
