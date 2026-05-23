"""Iter 018: lang_detect heuristic."""

import unittest

from src.lang_detect import detect_language


class DetectLanguageTests(unittest.TestCase):
    def test_pure_chinese_returns_zh(self) -> None:
        text = "武当山下，徐凤年练刀未成，却已卷入一场因绣冬刀而起的风波。" * 5
        self.assertEqual(detect_language(text), "zh")

    def test_pure_english_returns_en(self) -> None:
        text = "The morning had dawned clear and cold, with a crispness that hinted at the end of summer." * 5
        self.assertEqual(detect_language(text), "en")

    def test_mixed_majority_chinese_returns_zh(self) -> None:
        # 80% Chinese, 20% English author notes — should still be zh.
        text = ("武当山下，徐凤年练刀。" * 20) + ("the wind blew cold " * 5)
        self.assertEqual(detect_language(text), "zh")

    def test_mixed_majority_english_returns_en(self) -> None:
        # 80% English, scattered Chinese — should be en.
        text = ("The brothers rode south through " * 20) + ("中文 " * 3)
        self.assertEqual(detect_language(text), "en")

    def test_empty_returns_en_fallback(self) -> None:
        self.assertEqual(detect_language(""), "en")
        self.assertEqual(detect_language("   \n\n   "), "en")
        self.assertEqual(detect_language("12345 67890 !@#$%"), "en")


if __name__ == "__main__":
    unittest.main()
