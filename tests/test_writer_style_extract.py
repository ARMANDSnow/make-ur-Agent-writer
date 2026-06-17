"""iter 056 轨 B: 上传样本提取 + 反污染护栏——mock 确定性 stub、幂等、
n-gram 反污染剥离、record 标记不泄露到 prompt 渲染面。Mock-only。
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src import paths, writer_style
from src.llm_client import LLMClient
from src.schemas import WriterStyleCard


class ScrubTests(unittest.TestCase):
    """反污染二次扫描——纯函数，无需 workspace。"""

    def test_scrub_strips_verbatim_overlap(self) -> None:
        sample = "暮色四合他独自走在长街上影子被路灯拉得很长"
        fields = {
            "rhythm": "节奏舒缓，留白克制。",  # 与样本无重合
            "imagery": "影子被路灯拉得很长",  # 9 字连续重合 → 剥离
            "signatures": ["独自走在长街上影", "用环境烘托孤独"],  # 第一条重合 → 剔除
            "taboo": [],
        }
        cleaned, scrubbed = writer_style._scrub_sample_overlap(fields, sample)
        self.assertIn("imagery", scrubbed)
        self.assertEqual(cleaned["imagery"], "")
        self.assertIn("signatures", scrubbed)
        self.assertEqual(cleaned["signatures"], ["用环境烘托孤独"])
        self.assertNotIn("rhythm", scrubbed)  # 无重合不动

    def test_scrub_noop_when_no_overlap(self) -> None:
        cleaned, scrubbed = writer_style._scrub_sample_overlap(
            {"rhythm": "完全不同的风格描述文字"}, "另一段毫不相干的样本内容片段"
        )
        self.assertEqual(scrubbed, [])

    def test_mock_json_dispatch_hits_branch(self) -> None:
        os.environ["OPENAI_MODEL"] = "mock"
        client = LLMClient("style_extract")
        card = client._mock_json(WriterStyleCard, [])
        self.assertEqual(card.name, "mock 风格卡")
        self.assertTrue(card.rhythm)


class _WorkspaceHarness(unittest.TestCase):
    WS = "extractws"

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


class ExtractStyleTests(_WorkspaceHarness):
    def test_mock_extract_deterministic(self) -> None:
        rec = writer_style.extract_style_card("这是一段写作样本的开头，用于提炼文体。" * 50)
        self.assertEqual(rec["source"], "extract")
        self.assertTrue(rec["generated_by"].endswith("_mock"))
        self.assertEqual(rec["fields"]["name"], "mock 风格卡")
        self.assertFalse(rec["edited"])
        # 落盘 + 可回读 + 过 schema
        reloaded = writer_style.load_card()
        self.assertEqual(reloaded["fields"]["name"], "mock 风格卡")
        WriterStyleCard(**reloaded["fields"])

    def test_empty_sample_raises(self) -> None:
        with self.assertRaises(ValueError):
            writer_style.extract_style_card("   ")

    def test_idempotent_unless_force(self) -> None:
        writer_style.extract_style_card("样本甲" * 100)
        writer_style.save_card_fields({"name": "我改的卡"})  # 用户编辑
        # 不 force：已有卡 → 跳过、保留用户编辑
        rec = writer_style.extract_style_card("样本乙" * 100)
        self.assertEqual(rec["fields"]["name"], "我改的卡")
        # force：覆盖
        rec2 = writer_style.extract_style_card("样本乙" * 100, force=True)
        self.assertEqual(rec2["fields"]["name"], "mock 风格卡")

    def test_record_markers_not_in_prompt(self) -> None:
        path = paths.writer_style_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "source": "extract",
                    "fields": {"rhythm": "快节奏推进", "name": "测试卡"},
                    "_incomplete_fields": ["imagery"],
                    "_scrubbed_fields": ["dialogue"],
                }
            ),
            encoding="utf-8",
        )
        with patch("src.writer_style.start_point.get_start_chapter_id", return_value=None):
            block = writer_style.writer_style_prompt_block()
        self.assertIn("快节奏推进", block)
        # record 层标记绝不进注入面
        self.assertNotIn("_incomplete", block)
        self.assertNotIn("_scrubbed", block)


if __name__ == "__main__":
    unittest.main()
