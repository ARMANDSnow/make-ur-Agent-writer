import unittest

from src.text_normalizer import clean_line, detect_encoding, volume_id_for
from pathlib import Path


class NormalizerTests(unittest.TestCase):
    def test_detects_utf16_and_gb18030(self) -> None:
        self.assertEqual(detect_encoding("第一章".encode("utf-16")), "utf-16")
        self.assertEqual(detect_encoding("第一章".encode("gb18030")), "gb18030")

    def test_cleans_html_and_boilerplate(self) -> None:
        self.assertEqual(clean_line("<small>正文</small>", 200), "正文")
        self.assertEqual(clean_line("本书下载于 http://example.com", 10), "")

    def test_volume_ids_for_current_filenames(self) -> None:
        self.assertEqual(volume_id_for(Path("龙族Ⅰ火之晨曦.txt")), "longzu_1")
        self.assertEqual(volume_id_for(Path("龙族III黑月之潮（2）.txt")), "longzu_3_2")
        self.assertEqual(volume_id_for(Path("龙族4·奥丁之渊.txt")), "longzu_4")


if __name__ == "__main__":
    unittest.main()
