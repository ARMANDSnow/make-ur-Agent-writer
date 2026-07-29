"""iter 075: 全文搜索 route 端到端测试（routes.dispatch，无 HTTP 服务器）。

Mock-only。骨架照 tests/test_web_chapter_diff.py 的 ChapterDiffRouteTests。
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from src import paths
from src.web import routes
from src.web import workspace_meta


class SearchRouteTests(unittest.TestCase):
    WS = "searchws"

    def setUp(self) -> None:
        os.environ["OPENAI_MODEL"] = "mock"
        self._tmp = tempfile.TemporaryDirectory()
        self._saved_ws_dir = paths.WORKSPACE_DIR
        self._saved_env = os.environ.get("WORKSPACE_NAME")
        os.environ.pop("WORKSPACE_NAME", None)
        paths.WORKSPACE_DIR = Path(self._tmp.name)
        self.root = paths.WORKSPACE_DIR / self.WS
        (self.root / "data" / "normalized_texts").mkdir(parents=True, exist_ok=True)
        (self.root / "outputs" / "drafts").mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        paths.WORKSPACE_DIR = self._saved_ws_dir
        if self._saved_env is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._saved_env
        self._tmp.cleanup()

    def _seed(self) -> None:
        nf = self.root / "data" / "normalized_texts" / "vol1.txt"
        nf.write_text("路明非登场。\n楚子航沉默。\n", encoding="utf-8")
        (self.root / "data" / "chapter_manifest.json").write_text(
            json.dumps([
                {
                    "chapter_id": "ws_ch001",
                    "volume_id": "v1",
                    "normalized_file": str(nf),
                    "title": "第一章",
                    "start_line": 1,
                    "end_line": 2,
                    "char_count": 0,
                }
            ], ensure_ascii=False),
            encoding="utf-8",
        )
        (self.root / "outputs" / "drafts" / "chapter_01.md").write_text(
            "路明非在续写里再次出现。", encoding="utf-8"
        )

    def _get(self, path: str) -> tuple:
        status, ct, body = routes.dispatch("GET", path)
        return status, ct, body

    def _get_json(self, path: str) -> tuple:
        status, _ct, body = routes.dispatch("GET", path)
        return status, json.loads(body)

    # ---- API ---------------------------------------------------------------

    def test_search_hit(self) -> None:
        self._seed()
        status, data = self._get_json(f"/api/workspace/{self.WS}/search?q=路明非")
        self.assertEqual(status, 200, data)
        self.assertTrue(data["hits"])
        self.assertEqual(data["query"], "路明非")
        # draft 命中带 chapter_no；original 命中 chapter_no 为 None
        by_source = {h["source"]: h for h in data["hits"]}
        self.assertEqual(by_source["draft"]["chapter_no"], 1)
        self.assertIsNone(by_source["original"]["chapter_no"])
        self.assertEqual(by_source["original"]["chapter_id"], "ws_ch001")

    def test_empty_query_returns_200_empty(self) -> None:
        self._seed()
        status, data = self._get_json(f"/api/workspace/{self.WS}/search?q=")
        self.assertEqual(status, 200)
        self.assertEqual(data["hits"], [])
        self.assertEqual(data["hit_count"], 0)

    def test_whitespace_query_returns_200_empty(self) -> None:
        self._seed()
        status, data = self._get_json(f"/api/workspace/{self.WS}/search?q=%20%20")
        self.assertEqual(status, 200)
        self.assertEqual(data["hits"], [])

    def test_missing_q_param_returns_200_empty(self) -> None:
        self._seed()
        status, data = self._get_json(f"/api/workspace/{self.WS}/search")
        self.assertEqual(status, 200)
        self.assertEqual(data["hit_count"], 0)

    def test_invalid_workspace_name_400(self) -> None:
        # 无斜杠但含 ``..`` → 命中路由后被 _validate_workspace_name 拒（400，非 404）。
        status, data = self._get_json("/api/workspace/a..b/search?q=x")
        self.assertEqual(status, 400, data)

    def test_unknown_workspace_404(self) -> None:
        status, data = self._get_json("/api/workspace/nope/search?q=x")
        self.assertEqual(status, 404, data)

    def test_sources_param_scopes_search(self) -> None:
        self._seed()  # 原文含「路明非」、续写含「路明非」
        # 只搜续写 → 只返回 draft 命中
        status, data = self._get_json(f"/api/workspace/{self.WS}/search?q=路明非&sources=draft")
        self.assertEqual(status, 200, data)
        self.assertTrue(data["hits"])
        self.assertEqual({h["source"] for h in data["hits"]}, {"draft"})
        # 缺 sources 参数 → 默认全搜（original + draft 都在）
        _s, alld = self._get_json(f"/api/workspace/{self.WS}/search?q=路明非")
        self.assertIn("original", {h["source"] for h in alld["hits"]})

    def test_blank_sources_param_searches_nothing(self) -> None:
        # iter076（codex 审查 iter075 #2）：``?sources=``（显式空值）≠ 未传——
        # keep_blank_values 后到达 handler → 空列表 → 0 结果，而非误判全搜。
        self._seed()
        status, data = self._get_json(f"/api/workspace/{self.WS}/search?q=路明非&sources=")
        self.assertEqual(status, 200, data)
        self.assertEqual(data["hits"], [])
        self.assertEqual(data["hit_count"], 0)
        self.assertEqual(data["total_matches"], 0)

    def test_blank_int_query_params_fall_back_to_default(self) -> None:
        # keep_blank_values 波及面回归：``?n=`` 空值经 _parse_n int("") → ValueError
        # → 落 default，不得变 400/500。
        self._seed()
        status, _ct, body = routes.dispatch("GET", f"/api/workspace/{self.WS}/logs/tail?n=")
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertIn("lines", payload)

    def test_url_encoded_chinese_query(self) -> None:
        self._seed()
        # 「路明非」url 编码
        status, data = self._get_json(
            f"/api/workspace/{self.WS}/search?q=%E8%B7%AF%E6%98%8E%E9%9D%9E"
        )
        self.assertEqual(status, 200, data)
        self.assertTrue(data["hits"])

    def test_xss_body_is_valid_json_plain_text(self) -> None:
        nf = self.root / "data" / "normalized_texts" / "vol1.txt"
        nf.write_text("<img onerror=alert(1)>关键词ZZZ 后文。\n", encoding="utf-8")
        (self.root / "data" / "chapter_manifest.json").write_text(
            json.dumps([{
                "chapter_id": "x1", "volume_id": "v1", "normalized_file": str(nf),
                "title": "t", "start_line": 1, "end_line": 1, "char_count": 0,
            }], ensure_ascii=False),
            encoding="utf-8",
        )
        status, _ct, body = self._get(f"/api/workspace/{self.WS}/search?q=关键词ZZZ")
        self.assertEqual(status, 200)
        data = json.loads(body)   # 合法 JSON
        snippet = data["hits"][0]["snippets"][0]["text"]
        self.assertIn("<img onerror", snippet)   # 纯文本字段（前端负责渲染安全）

    # ---- page --------------------------------------------------------------

    def test_search_page_renders(self) -> None:
        self._seed()
        status, _ct, body = self._get(f"/w/{self.WS}/search")
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        self.assertIn('id="search-input"', html)
        self.assertIn('window.PAGE_KIND = "search"', html)
        self.assertIn('内容搜索', html)

    def test_search_page_drama_novel_only_guard(self) -> None:
        self._seed()
        workspace_meta.write(self.WS, type="drama")
        status, _ct, body = self._get(f"/w/{self.WS}/search")
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        self.assertNotIn('id="search-input"', html)   # drama → novel-only 引导页


if __name__ == "__main__":
    unittest.main()
