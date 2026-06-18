"""iter057 P1-C: outline 语义漂移探针(确定性 MVP)测试。

锚点 = outline 提及的实体名;命中 = 锚点在最近 K 章 rolling 出现。命中率低 → warn。
只 warn 不 block;锚点不足/无剧情不判定(避免误报)。
"""

import unittest

from src.outline_drift import outline_drift_codes


def _graph(*names: str) -> dict:
    return {"entities": [{"name": n} for n in names]}


def _rolling(*summaries: str) -> dict:
    return {
        "chapters": [
            {"chapter_no": i + 1, "summary": s, "key_events": []}
            for i, s in enumerate(summaries)
        ]
    }


class OutlineDriftTests(unittest.TestCase):
    def test_drift_detected_when_anchors_missing(self) -> None:
        # outline 提 4 个实体,最近 rolling 只提 1 个 → 命中率 25% < 40% → drift warn。
        outline = "本卷围绕 路明非 与 陈墨瞳 在 卡塞尔 对抗 诺顿 展开"
        graph = _graph("路明非", "陈墨瞳", "卡塞尔", "诺顿")
        rolling = _rolling("路明非 独自在房间发呆", "路明非 继续发呆")
        codes = outline_drift_codes(outline, rolling, graph)
        self.assertTrue(codes)
        self.assertIn("semantic_drift", codes[0])
        self.assertIn("陈墨瞳", codes[0])  # 未命中锚点入清单

    def test_no_drift_when_anchors_present(self) -> None:
        outline = "本卷围绕 路明非 与 陈墨瞳 在 卡塞尔 对抗 诺顿 展开"
        graph = _graph("路明非", "陈墨瞳", "卡塞尔", "诺顿")
        rolling = _rolling("路明非 陈墨瞳 在 卡塞尔", "对抗 诺顿 的战斗")
        self.assertEqual(outline_drift_codes(outline, rolling, graph), [])

    def test_too_few_anchors_no_judgment(self) -> None:
        # outline 只提及 1 个实体 → 锚点 < 3 → 不判定(避免小样本噪声)。
        outline = "本卷围绕 路明非 一人展开"
        graph = _graph("路明非", "陈墨瞳", "卡塞尔")
        rolling = _rolling("完全无关的内容")
        self.assertEqual(outline_drift_codes(outline, rolling, graph), [])

    def test_empty_outline_or_no_chapters(self) -> None:
        graph = _graph("路明非", "陈墨瞳", "卡塞尔", "诺顿")
        self.assertEqual(outline_drift_codes("", _rolling("x"), graph), [])
        outline = "路明非 陈墨瞳 卡塞尔 诺顿 全在"
        self.assertEqual(outline_drift_codes(outline, {"chapters": []}, graph), [])

    def test_aliases_count_as_hits(self) -> None:
        # rolling 用别名提及 → 算命中(锚点含别名)。
        outline = "路明非 陈墨瞳 卡塞尔 诺顿 齐聚"
        graph = {
            "entities": [
                {"name": "路明非", "aliases": ["路鸣非"]},
                {"name": "陈墨瞳", "aliases": []},
                {"name": "卡塞尔", "aliases": []},
                {"name": "诺顿", "aliases": []},
            ]
        }
        rolling = _rolling("路明非 与 陈墨瞳", "卡塞尔 学院 诺顿")
        self.assertEqual(outline_drift_codes(outline, rolling, graph), [])


if __name__ == "__main__":
    unittest.main()
