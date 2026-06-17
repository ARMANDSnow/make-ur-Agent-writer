"""iter055 轨D: 抽取韧性观测 + --no-chunk CLI.

每章抽取记 elapsed_ms 进 log_event 载荷(成功 done / 失败 failure 双路)与失败 JSON:
真实跑中一章耗时 ≈ per-call 超时值(如 120000ms)是 Cloudflare Tunnel 挂起撞超时的特征,
没有计时就只能盲猜。--no-chunk 经 extract / rebuild-for-start CLI 透传到 extract_all
(诊断分块边界漏抽/合并失真,或短章实跑)。
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Tuple
from unittest.mock import MagicMock, patch

import main as main_module
from src.extractor import extract_all

_MANIFEST = [{
    "chapter_id": "longzu_1_ch001", "volume_id": "longzu_1",
    "source_file": "t.txt", "normalized_file": "norm.txt",
    "title": "第一章", "start_line": 1, "end_line": 3, "char_count": 30,
}]


def _ok_data() -> Dict[str, Any]:
    return {"summary": "s", "rolling_summary": "r", "evidence_spans": [{"quote": "x"}]}


class ElapsedMsLoggingTests(unittest.TestCase):
    """extract_all 每章计时 → log_event + 失败 JSON 都带 elapsed_ms。"""

    def _run(self, chapter_side_effect):
        events: List[Tuple[str, Dict[str, Any]]] = []

        def capture_log(component, event, **payload):
            events.append((event, payload))

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "extracted").mkdir()
            with patch("src.extractor.load_manifest", return_value=_MANIFEST), patch(
                "src.extractor.EXTRACTED_DIR", tmp / "extracted"
            ), patch("src.extractor.ROLLING_DIR", tmp / "rolling"), patch(
                "src.extractor.FAILURES_DIR", tmp / "failures"
            ), patch("src.extractor.chapter_text", return_value="正文"), patch(
                "src.extractor.LLMClient", MagicMock()
            ), patch("src.extractor.log_event", side_effect=capture_log), patch(
                "src.extractor._extract_chapter_data", **chapter_side_effect
            ):
                extract_all(volume="all", force=True)
            failure_path = tmp / "failures" / "longzu_1_ch001.json"
            failure_rec = json.loads(failure_path.read_text(encoding="utf-8")) if failure_path.exists() else None
        return events, failure_rec

    def test_done_event_includes_elapsed_ms(self) -> None:
        events, _ = self._run({"return_value": _ok_data()})
        done = [p for (e, p) in events if e == "done"]
        self.assertEqual(len(done), 1)
        self.assertIn("elapsed_ms", done[0])
        self.assertIsInstance(done[0]["elapsed_ms"], int)
        self.assertGreaterEqual(done[0]["elapsed_ms"], 0)

    def test_failure_event_and_record_include_elapsed_ms(self) -> None:
        events, failure_rec = self._run({"side_effect": RuntimeError("Cloudflare Tunnel 530")})
        failures = [p for (e, p) in events if e == "failure"]
        self.assertEqual(len(failures), 1)
        self.assertIn("elapsed_ms", failures[0])
        self.assertIsInstance(failures[0]["elapsed_ms"], int)
        # 失败 JSON 落盘也带计时,供事后判定是否撞超时。
        self.assertIsNotNone(failure_rec)
        self.assertIn("elapsed_ms", failure_rec)
        self.assertIsInstance(failure_rec["elapsed_ms"], int)


class NoChunkCliTests(unittest.TestCase):
    """--no-chunk 在 extract / rebuild-for-start 子命令上解析并透传。"""

    def test_extract_parser_has_no_chunk(self) -> None:
        parser = main_module.build_parser()
        self.assertTrue(parser.parse_args(["extract", "--no-chunk"]).no_chunk)
        self.assertFalse(parser.parse_args(["extract"]).no_chunk)  # 缺省 off,兼容旧调用

    def test_rebuild_parser_has_no_chunk(self) -> None:
        parser = main_module.build_parser()
        self.assertTrue(parser.parse_args(["rebuild-for-start", "--no-chunk"]).no_chunk)
        self.assertFalse(parser.parse_args(["rebuild-for-start"]).no_chunk)

    def test_extract_handler_forwards_no_chunk(self) -> None:
        with patch("main.extract_all") as mock_extract:
            with patch("sys.argv", ["main.py", "extract", "--no-chunk"]):
                main_module.main()
        mock_extract.assert_called_once()
        self.assertTrue(mock_extract.call_args.kwargs.get("no_chunk"))

    def test_extract_handler_default_no_chunk_false(self) -> None:
        with patch("main.extract_all") as mock_extract:
            with patch("sys.argv", ["main.py", "extract"]):
                main_module.main()
        mock_extract.assert_called_once()
        self.assertFalse(mock_extract.call_args.kwargs.get("no_chunk"))

    def test_extract_parser_has_per_chapter_attempts(self) -> None:
        parser = main_module.build_parser()
        self.assertEqual(
            parser.parse_args(["extract", "--per-chapter-attempts", "3"]).per_chapter_attempts, 3
        )
        self.assertIsNone(parser.parse_args(["extract"]).per_chapter_attempts)  # 缺省 None=不整章重试

    def test_extract_handler_forwards_per_chapter_attempts(self) -> None:
        with patch("main.extract_all") as mock_extract:
            with patch("sys.argv", ["main.py", "extract", "--per-chapter-attempts", "2"]):
                main_module.main()
        mock_extract.assert_called_once()
        self.assertEqual(mock_extract.call_args.kwargs.get("per_chapter_attempts"), 2)


class PerChapterRetryTests(unittest.TestCase):
    """extract_all(per_chapter_attempts=N): 整章级重试救分块合并失败(call 级救不了)。"""

    def _run(self, chapter_side_effect, **extract_kwargs):
        events: List[Tuple[str, Dict[str, Any]]] = []

        def capture_log(component, event, **payload):
            events.append((event, payload))

        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "extracted").mkdir()
            with patch("src.extractor.load_manifest", return_value=_MANIFEST), patch(
                "src.extractor.EXTRACTED_DIR", tmp / "extracted"
            ), patch("src.extractor.ROLLING_DIR", tmp / "rolling"), patch(
                "src.extractor.FAILURES_DIR", tmp / "failures"
            ), patch("src.extractor.chapter_text", return_value="正文"), patch(
                "src.extractor.LLMClient", MagicMock()
            ), patch("src.extractor.log_event", side_effect=capture_log), patch(
                "src.extractor._extract_chapter_data", **chapter_side_effect
            ):
                results = extract_all(volume="all", force=True, **extract_kwargs)
            failure_exists = (tmp / "failures" / "longzu_1_ch001.json").exists()
        return results, events, failure_exists

    def test_whole_chapter_retry_recovers(self) -> None:
        # 第一次抛(分块合并失败)、第二次成功 → per_chapter_attempts=2 救回,无失败记录。
        results, events, failure_exists = self._run(
            {"side_effect": [RuntimeError("merge boom"), _ok_data()]}, per_chapter_attempts=2
        )
        self.assertEqual(len(results), 1)
        self.assertFalse(failure_exists)
        retries = [p for (e, p) in events if e == "chapter_retry"]
        self.assertEqual(len(retries), 1)
        self.assertEqual(retries[0]["attempt"], 1)

    def test_default_none_means_no_whole_chapter_retry(self) -> None:
        # 缺省(None)→ attempts=1,第一次抛即失败,不整章重试(逐字节兼容旧行为)。
        results, events, failure_exists = self._run(
            {"side_effect": [RuntimeError("merge boom"), _ok_data()]}
        )
        self.assertEqual(len(results), 0)
        self.assertTrue(failure_exists)
        self.assertEqual([p for (e, p) in events if e == "chapter_retry"], [])

    def test_exhausted_attempts_records_failure(self) -> None:
        # 全失败耗尽 → 记失败,chapter_retry 发 attempts-1 次。
        results, events, failure_exists = self._run(
            {"side_effect": RuntimeError("persistent boom")}, per_chapter_attempts=3
        )
        self.assertEqual(len(results), 0)
        self.assertTrue(failure_exists)
        self.assertEqual(len([1 for (e, p) in events if e == "chapter_retry"]), 2)

    def test_transient_failure_not_whole_chapter_retried(self) -> None:
        # iter055 审查修正: transient(如 Cloudflare Tunnel 530)call 级(轨B)已重试耗尽,整章
        # 不再重试 —— 避免与 call 级相乘放大卡死窗口(tunnel 持续挂时数小时)。立即失败,无 chapter_retry。
        results, events, failure_exists = self._run(
            {"side_effect": RuntimeError("Cloudflare Tunnel error 530")}, per_chapter_attempts=3
        )
        self.assertEqual(len(results), 0)
        self.assertTrue(failure_exists)
        self.assertEqual([p for (e, p) in events if e == "chapter_retry"], [])  # transient 不整章重试


if __name__ == "__main__":
    unittest.main()
