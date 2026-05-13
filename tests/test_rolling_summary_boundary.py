import unittest

from src.extractor import _tail_by_sentence


class RollingSummaryBoundaryTests(unittest.TestCase):
    def test_tail_keeps_sentence_boundary_for_chinese_text(self) -> None:
        text = "前情。" + ("龙王苏醒" * 700) + "。路明非收起刀。楚子航没有回头。"
        result = _tail_by_sentence(text, 4000)
        self.assertFalse(result.startswith("王苏醒"))
        self.assertTrue(result.endswith("。"))
        self.assertIn("路明非收起刀。", result)

    def test_tail_falls_back_when_no_boundary_exists(self) -> None:
        text = "abcdef"
        self.assertEqual(_tail_by_sentence(text, 3), "def")


if __name__ == "__main__":
    unittest.main()
