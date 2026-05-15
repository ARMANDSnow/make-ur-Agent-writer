import tempfile
import unittest
from pathlib import Path

from src.style import load_style_examples


class StyleExampleTests(unittest.TestCase):
    def test_load_style_examples_returns_empty_when_dir_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(load_style_examples(Path(tmp)), "")

    def test_load_style_examples_concatenates_sorted_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            examples = root / "data" / "style_examples"
            examples.mkdir(parents=True)
            (examples / "b_scene.md").write_text("第二段", encoding="utf-8")
            (examples / "a_opening.md").write_text("第一段", encoding="utf-8")

            text = load_style_examples(root)

        self.assertLess(text.index("### a_opening"), text.index("### b_scene"))
        self.assertIn("第一段", text)
        self.assertIn("---", text)


if __name__ == "__main__":
    unittest.main()
