"""iter055 轨C: chunk_bypass_max_chars —— 单调用上限,绕过分块。

抽取默认按 chunk_threshold_chars 分块(长章切 N 块各自抽取,再 LLMClient("compress") 合并)。
分块边界会漏抽跨块的人物状态/伏笔,合并环节也可能失真。bypass 把"必须单调用"的上限抬到
max(threshold, bypass):文本 ≤ 此值则强制单次抽取。缺省 0 → max(threshold,0)=threshold,
逐字节兼容旧行为。--no-chunk 经 extract_all 把 bypass 设极大值 → 每章单调用(诊断/短章实跑)。
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict
from unittest.mock import MagicMock, patch

from src.extractor import _extract_chapter_data, _extract_settings, extract_all
from src.schemas import ChapterExtraction


def _entry() -> Dict[str, Any]:
    return {
        "chapter_id": "longzu_1_ch999",
        "volume_id": "longzu_1",
        "source_file": "source.txt",
        "normalized_file": "norm.txt",
        "title": "长章节",
        "start_line": 1,
        "end_line": 100,
        "char_count": 30000,
    }


class _CountingClient:
    """每次 complete_json 计数并回不同人物,便于区分单调用(1 次)vs 分块合并(3 次)。"""

    def __init__(self, entry: Dict[str, Any]) -> None:
        self._entry = entry
        self.names = ["路明非", "楚子航", "凯撒"]
        self.calls = 0

    def complete_json(self, messages: Any, response_model: Any) -> ChapterExtraction:
        name = self.names[self.calls % len(self.names)]
        self.calls += 1
        return ChapterExtraction(
            chapter_id=self._entry["chapter_id"],
            volume_id=self._entry["volume_id"],
            title=self._entry["title"],
            summary=f"{name} 摘要。",
            rolling_summary=f"{name} 滚动。",
            character_states=[{"character": name, "after": "状态", "status": "active"}],
            relationships=[],
            foreshadowing=[],
            worldbuilding=[],
            style_samples=[],
            evidence_spans=[],
        )


class _FakeSummarizer:
    """分块合并路径里 LLMClient("compress") 的替身。"""

    def complete_text(self, messages: Any, temperature: Any = None) -> str:
        return "合并摘要。"


class ExtractorBypassDecisionTests(unittest.TestCase):
    """_extract_chapter_data: effective_threshold=max(threshold, bypass) 的分支判定。"""

    def _run(self, settings: Dict[str, Any], text_len: int = 30000):
        entry = _entry()
        client = _CountingClient(entry)
        with patch("src.extractor.LLMClient", return_value=_FakeSummarizer()):
            data = _extract_chapter_data(entry, "龙" * text_len, [], "", client, settings)
        return client.calls, data

    def test_bypass_above_text_forces_single_call(self) -> None:
        # bypass 50000 > 文本 30000 > threshold 24000 → effective=50000 → 单调用,不合并。
        calls, data = self._run(
            {"chunk_threshold_chars": 24000, "chunk_count": 3, "chunk_overlap_chars": 200,
             "chunk_bypass_max_chars": 50000}
        )
        self.assertEqual(calls, 1)
        self.assertEqual(data["summary"], "路明非 摘要。")  # 单次抽取原样,非"合并摘要。"

    def test_bypass_zero_still_chunks(self) -> None:
        # bypass=0 → effective=max(24000,0)=24000;文本 30000 > 24000 → 分块(逐字节兼容)。
        calls, data = self._run(
            {"chunk_threshold_chars": 24000, "chunk_count": 3, "chunk_overlap_chars": 200,
             "chunk_bypass_max_chars": 0}
        )
        self.assertEqual(calls, 3)
        self.assertEqual(data["summary"], "合并摘要。")

    def test_bypass_key_absent_defaults_to_chunk(self) -> None:
        # settings 无 chunk_bypass_max_chars 键(旧调用方/旧测试形状)→ .get 缺省 0 → 分块,不 KeyError。
        calls, _data = self._run(
            {"chunk_threshold_chars": 24000, "chunk_count": 3, "chunk_overlap_chars": 200}
        )
        self.assertEqual(calls, 3)

    def test_bypass_below_threshold_is_noop(self) -> None:
        # bypass 10000 < threshold 24000 → effective=max(24000,10000)=24000 → 仍分块(取较大者)。
        calls, _data = self._run(
            {"chunk_threshold_chars": 24000, "chunk_count": 3, "chunk_overlap_chars": 200,
             "chunk_bypass_max_chars": 10000}
        )
        self.assertEqual(calls, 3)


class ExtractSettingsBypassTests(unittest.TestCase):
    """_extract_settings: 从 models.yaml extract 任务读 chunk_bypass_max_chars。"""

    def test_settings_reads_configured_default(self) -> None:
        # 真配置 models.yaml tasks.extract = 48000(覆盖 20-30K longzu 章默认单调用,治根因②
        # 长章分块拥堵 967s/章);仍 << 128K context,_check_context 兜底超长章。
        settings = _extract_settings()
        self.assertEqual(settings["chunk_bypass_max_chars"], 48000)

    def test_settings_reads_config_override(self) -> None:
        fake_cfg = {"tasks": {"extract": {"chunk_bypass_max_chars": 99999}}}
        with patch("src.extractor.load_config", return_value=fake_cfg):
            settings = _extract_settings()
        self.assertEqual(settings["chunk_bypass_max_chars"], 99999)

    def test_settings_default_zero_when_key_missing(self) -> None:
        fake_cfg = {"tasks": {"extract": {}}}
        with patch("src.extractor.load_config", return_value=fake_cfg):
            settings = _extract_settings()
        self.assertEqual(settings["chunk_bypass_max_chars"], 0)


class ExtractAllNoChunkTests(unittest.TestCase):
    """extract_all(no_chunk=True): 把 bypass 抬到极大值,透传给每章抽取。"""

    def test_no_chunk_propagates_huge_bypass(self) -> None:
        manifest = [{
            "chapter_id": "longzu_1_ch001", "volume_id": "longzu_1",
            "source_file": "t.txt", "normalized_file": "norm.txt",
            "title": "第一章", "start_line": 1, "end_line": 3, "char_count": 30,
        }]
        captured: Dict[str, Any] = {}

        def capturing(entry, text, prev, vol, client, settings):
            captured["bypass"] = settings.get("chunk_bypass_max_chars")
            return {"summary": "s", "rolling_summary": "r", "evidence_spans": [{"quote": "x"}]}

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "extracted").mkdir()
            with patch("src.extractor.load_manifest", return_value=manifest), patch(
                "src.extractor.EXTRACTED_DIR", tmp / "extracted"
            ), patch("src.extractor.ROLLING_DIR", tmp / "rolling"), patch(
                "src.extractor.FAILURES_DIR", tmp / "failures"
            ), patch("src.extractor.chapter_text", return_value="正文"), patch(
                "src.extractor.LLMClient", MagicMock()
            ), patch("src.extractor._extract_chapter_data", side_effect=capturing):
                extract_all(volume="all", force=True, no_chunk=True)
        self.assertEqual(captured["bypass"], 10 ** 9)

    def test_default_keeps_configured_bypass(self) -> None:
        # 不传 no_chunk → 透传配置原值(models.yaml 默认 48000),不被改写。
        manifest = [{
            "chapter_id": "longzu_1_ch001", "volume_id": "longzu_1",
            "source_file": "t.txt", "normalized_file": "norm.txt",
            "title": "第一章", "start_line": 1, "end_line": 3, "char_count": 30,
        }]
        captured: Dict[str, Any] = {}

        def capturing(entry, text, prev, vol, client, settings):
            captured["bypass"] = settings.get("chunk_bypass_max_chars")
            return {"summary": "s", "rolling_summary": "r", "evidence_spans": [{"quote": "x"}]}

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "extracted").mkdir()
            with patch("src.extractor.load_manifest", return_value=manifest), patch(
                "src.extractor.EXTRACTED_DIR", tmp / "extracted"
            ), patch("src.extractor.ROLLING_DIR", tmp / "rolling"), patch(
                "src.extractor.FAILURES_DIR", tmp / "failures"
            ), patch("src.extractor.chapter_text", return_value="正文"), patch(
                "src.extractor.LLMClient", MagicMock()
            ), patch("src.extractor._extract_chapter_data", side_effect=capturing):
                extract_all(volume="all", force=True)
        self.assertEqual(captured["bypass"], 48000)


if __name__ == "__main__":
    unittest.main()
