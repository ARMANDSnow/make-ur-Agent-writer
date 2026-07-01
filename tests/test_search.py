"""iter 075: 跨章全文检索纯函数测试（src/search.py）。

Mock-only（tests/__init__.py 强制 OPENAI_MODEL=mock，铁律③）；不触碰真模型。
骨架照 tests/test_web_chapter_diff.py：临时 WORKSPACE_DIR + 手搭 workspace 树 +
``with use_workspace(WS):`` 进上下文。
"""

from __future__ import annotations

import json
import os
import pathlib
import tempfile
import unittest
from pathlib import Path

from src import paths, search
from src.web.workspace_ctx import use_workspace


def _marked(snippet: search.Snippet) -> list:
    """从 offsets 抽出被高亮的子串（模拟前端 <mark> 内容）。"""
    return [snippet.text[s:e] for (s, e) in snippet.offsets]


class SearchBase(unittest.TestCase):
    WS = "searchtest"

    def setUp(self) -> None:
        os.environ["OPENAI_MODEL"] = "mock"
        self._tmp = tempfile.TemporaryDirectory()
        self._saved_ws_dir = paths.WORKSPACE_DIR
        self._saved_env = os.environ.get("WORKSPACE_NAME")
        os.environ.pop("WORKSPACE_NAME", None)
        paths.WORKSPACE_DIR = Path(self._tmp.name)
        self.root = paths.WORKSPACE_DIR / self.WS
        (self.root / "data" / "normalized_texts").mkdir(parents=True, exist_ok=True)
        (self.root / "data" / "knowledge_base").mkdir(parents=True, exist_ok=True)
        (self.root / "outputs" / "drafts").mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        paths.WORKSPACE_DIR = self._saved_ws_dir
        if self._saved_env is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._saved_env
        self._tmp.cleanup()

    # ---- seed helpers -------------------------------------------------------

    def _write_manifest(self, entries: list) -> None:
        (self.root / "data" / "chapter_manifest.json").write_text(
            json.dumps(entries, ensure_ascii=False), encoding="utf-8"
        )

    def _write_normalized(self, filename: str, lines: list) -> str:
        p = self.root / "data" / "normalized_texts" / filename
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return str(p)

    def _entry(self, chapter_id: str, nf: str, start: int, end: int, title: str = "") -> dict:
        return {
            "chapter_id": chapter_id,
            "volume_id": "vol1",
            "normalized_file": nf,
            "title": title or chapter_id,
            "start_line": start,
            "end_line": end,
            "char_count": 0,
        }

    def _write_draft(self, n: int, text: str, *, partial: bool = False) -> None:
        suffix = ".partial.md" if partial else ".md"
        (self.root / "outputs" / "drafts" / f"chapter_{n:02d}{suffix}").write_text(
            text, encoding="utf-8"
        )

    def _write_kb(self, text: str) -> None:
        (self.root / "data" / "knowledge_base" / "global_knowledge.md").write_text(
            text, encoding="utf-8"
        )

    def _seed_default(self) -> None:
        nf = self._write_normalized(
            "vol1.txt",
            [
                "路明非站在门口，楚子航沉默不语。",   # L1
                "诺诺笑着跑过来。",                    # L2
                "夜谈会开始了。",                      # L3
                "EVA 系统缓缓启动。",                  # L4
                "路明非又一次出现在众人面前。",         # L5
                "一切归于平静。",                      # L6
            ],
        )
        # ch001/ch002 共享同一个 normalized_file（读缓存的用例基础）
        self._write_manifest([
            self._entry("longzu_1_ch001", nf, 1, 3, "第一章"),
            self._entry("longzu_1_ch002", nf, 4, 6, "第二章"),
        ])
        self._write_draft(1, "路明非在续写第一章里再次露面。")
        self._write_draft(2, "只有楚子航的旧稿。", partial=True)  # 应被跳过
        self._write_kb("## 角色\n- 路明非：主角，火之言灵。")


class SearchModuleTests(SearchBase):
    def test_hit_original_draft_kb_and_ordering(self) -> None:
        self._seed_default()
        with use_workspace(self.WS):
            res = search.search_workspace("路明非")
        # draft → original → kb
        self.assertEqual([h.source for h in res.hits], ["draft", "original", "original", "kb"])
        # draft 有章号可链详情；original/kb 无
        draft = res.hits[0]
        self.assertEqual(draft.chapter_no, 1)
        self.assertIsNone(res.hits[1].chapter_no)
        self.assertEqual(res.hits[1].chapter_id, "longzu_1_ch001")
        self.assertIsNone(res.hits[3].chapter_no)
        self.assertEqual(res.hit_count, 4)
        self.assertFalse(res.truncated)
        # 每个命中至少一个片段且高亮命中「路明非」
        for h in res.hits:
            self.assertTrue(h.snippets)
            self.assertIn("路明非", _marked(h.snippets[0]))

    def test_no_match(self) -> None:
        self._seed_default()
        with use_workspace(self.WS):
            res = search.search_workspace("绝不存在的关键词XYZ")
        self.assertEqual(res.hit_count, 0)
        self.assertEqual(res.total_matches, 0)
        self.assertEqual(res.hits, [])

    def test_blank_query_graceful(self) -> None:
        self._seed_default()
        with use_workspace(self.WS):
            res = search.search_workspace("   ")
        self.assertEqual(res.hit_count, 0)
        self.assertEqual(res.query, "")

    def test_empty_workspace_graceful(self) -> None:
        # 什么都不写：manifest 缺失(FileNotFoundError 被吞) + 无 draft + 无 KB。
        with use_workspace(self.WS):
            res = search.search_workspace("路明非")
        self.assertEqual(res.hit_count, 0)
        self.assertFalse(res.truncated)

    def test_regex_metachars_are_literal(self) -> None:
        self._write_manifest([])  # 只用 draft
        self._write_draft(1, "路明非(火)之言灵苏醒。")
        with use_workspace(self.WS):
            hit_paren = search.search_workspace("(火)", sources=["draft"])
            miss_dot = search.search_workspace("路.非", sources=["draft"])
        self.assertEqual(hit_paren.hit_count, 1)              # 字面 (火) 命中
        self.assertEqual(miss_dot.hit_count, 0)              # 「.」不当通配 → 不命中

    def test_redos_pattern_returns_fast_no_crash(self) -> None:
        self._seed_default()
        with use_workspace(self.WS):
            res = search.search_workspace("(a+)+$")   # 灾难正则当字面量 → 秒回空
        self.assertEqual(res.hit_count, 0)

    def test_case_insensitive_offset_points_to_original_case(self) -> None:
        self._seed_default()
        with use_workspace(self.WS):
            res = search.search_workspace("eva", sources=["original"])
        self.assertEqual(res.hit_count, 1)
        self.assertEqual(res.hits[0].chapter_id, "longzu_1_ch002")
        self.assertEqual(_marked(res.hits[0].snippets[0]), ["EVA"])   # 高亮指向原文大小写

    def test_truncate_query_len(self) -> None:
        self._seed_default()
        long_q = "路" * (search.MAX_QUERY_LEN + 1)
        with use_workspace(self.WS):
            res = search.search_workspace(long_q)
        self.assertTrue(res.truncated)
        self.assertIn("query_len", res.truncated_reasons)
        self.assertEqual(len(res.query), search.MAX_QUERY_LEN)

    def test_truncate_snippets_per_chapter(self) -> None:
        n = search.MAX_SNIPPETS_PER_CHAPTER + 1
        self._write_manifest([])
        self._write_draft(1, "关键" * n)   # 非重叠出现 n 次
        with use_workspace(self.WS):
            res = search.search_workspace("关键", sources=["draft"])
        self.assertEqual(res.hit_count, 1)
        hit = res.hits[0]
        self.assertEqual(hit.match_count, n)                       # 计数记真实总数
        self.assertEqual(len(hit.snippets), search.MAX_SNIPPETS_PER_CHAPTER)  # 片段截断
        self.assertTrue(res.truncated)
        self.assertIn("snippets:draft:1", res.truncated_reasons)

    def test_truncate_chapters(self) -> None:
        self._write_manifest([])
        for i in range(1, search.MAX_CHAPTERS + 2):   # 201 章
            self._write_draft(i, "阈值词出现")
        with use_workspace(self.WS):
            res = search.search_workspace("阈值词", sources=["draft"])
        self.assertEqual(res.hit_count, search.MAX_CHAPTERS)
        self.assertTrue(res.truncated)
        self.assertIn("chapters", res.truncated_reasons)

    def test_truncated_reasons_only_reference_surviving_hits(self) -> None:
        # 201 章、每章命中 > MAX_SNIPPETS → chapters 截断后，被丢弃的 ch201 不应留悬空
        # snippets reason（回归 iter075 code-review finder1）。
        self._write_manifest([])
        n_matches = search.MAX_SNIPPETS_PER_CHAPTER + 1
        for i in range(1, search.MAX_CHAPTERS + 2):
            self._write_draft(i, "关键" * n_matches)
        with use_workspace(self.WS):
            res = search.search_workspace("关键", sources=["draft"])
        self.assertIn("chapters", res.truncated_reasons)
        survivors = {h.chapter_no for h in res.hits}
        self.assertNotIn(search.MAX_CHAPTERS + 1, survivors)     # ch201 被丢弃
        self.assertNotIn(f"snippets:draft:{search.MAX_CHAPTERS + 1}", res.truncated_reasons)
        for r in res.truncated_reasons:
            if r.startswith("snippets:draft:"):
                self.assertIn(int(r.rsplit(":", 1)[1]), survivors)   # 每个 reason 都指向存活章

    def test_sources_none_searches_all_empty_list_searches_nothing(self) -> None:
        self._seed_default()
        with use_workspace(self.WS):
            all_res = search.search_workspace("路明非", sources=None)   # 默认全搜
            none_res = search.search_workspace("路明非", sources=[])    # 全不搜
        self.assertGreater(all_res.hit_count, 0)
        self.assertEqual(none_res.hit_count, 0)

    def test_xss_snippet_is_raw_text(self) -> None:
        self._write_manifest([])
        self._write_draft(1, "<script>alert(1)</script>标记词ABC 后文。")
        with use_workspace(self.WS):
            res = search.search_workspace("标记词ABC", sources=["draft"])
        self.assertEqual(res.hit_count, 1)
        sn = res.hits[0].snippets[0]
        self.assertIn("<script>", sn.text)            # 原样保留、未转义、未剥离
        self.assertEqual(_marked(sn), ["标记词ABC"])   # offset 指向关键词而非脚本

    def test_corrupt_manifest_tolerated(self) -> None:
        (self.root / "data" / "chapter_manifest.json").write_text("{not json", encoding="utf-8")
        self._write_draft(1, "路明非续写。")
        with use_workspace(self.WS):
            res = search.search_workspace("路明非")
        # original 语料整块降级为空，draft 仍命中
        self.assertEqual([h.source for h in res.hits], ["draft"])

    def test_corrupt_entry_skips_only_that_chapter(self) -> None:
        good_nf = self._write_normalized("vol1.txt", ["路明非在此。"])
        bad = self._entry("ch_bad", str(self.root / "data" / "normalized_texts" / "missing.txt"), 1, 1)
        good = self._entry("ch_good", good_nf, 1, 1)
        self._write_manifest([bad, good])
        with use_workspace(self.WS):
            res = search.search_workspace("路明非", sources=["original"])
        self.assertEqual([h.chapter_id for h in res.hits], ["ch_good"])

    def test_normalized_file_read_cache(self) -> None:
        self._seed_default()   # ch001/ch002 共享 vol1.txt
        vol1 = str(self.root / "data" / "normalized_texts" / "vol1.txt")
        counts: dict = {}
        orig_read_text = pathlib.Path.read_text

        def counting_read_text(self, *a, **k):
            counts[str(self)] = counts.get(str(self), 0) + 1
            return orig_read_text(self, *a, **k)

        pathlib.Path.read_text = counting_read_text
        try:
            with use_workspace(self.WS):
                search.search_workspace("路明非", sources=["original"])
        finally:
            pathlib.Path.read_text = orig_read_text
        self.assertEqual(counts.get(vol1), 1)   # 两章共享一卷文件 → 仅读一次

    def test_length_changing_lower_no_crash_no_misalign(self) -> None:
        # 'İ'.lower() 长度 1→2：走 display=hay_lower 分支，offset 仍精确。
        self._write_manifest([])
        self._write_draft(1, "İstanbul 关键词 结尾。")
        with use_workspace(self.WS):
            res = search.search_workspace("关键词", sources=["draft"])
        self.assertEqual(res.hit_count, 1)
        self.assertEqual(_marked(res.hits[0].snippets[0]), ["关键词"])

    def test_kb_fail_open_when_missing(self) -> None:
        self._write_manifest([])
        self._write_draft(1, "路明非续写。")
        # 不写 global_knowledge.md → kb 语料空，不影响 draft，不抛
        with use_workspace(self.WS):
            res = search.search_workspace("路明非")
        self.assertEqual([h.source for h in res.hits], ["draft"])

    def test_to_dict_is_json_serializable(self) -> None:
        self._seed_default()
        with use_workspace(self.WS):
            res = search.search_workspace("路明非")
        # asdict → json 全程无异常，offsets 变 JSON array
        blob = json.dumps(res.to_dict(), ensure_ascii=False)
        parsed = json.loads(blob)
        self.assertEqual(parsed["hit_count"], 4)
        self.assertEqual(parsed["hits"][1]["chapter_id"], "longzu_1_ch001")


if __name__ == "__main__":
    unittest.main()
