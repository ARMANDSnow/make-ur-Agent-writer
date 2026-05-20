import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.plot_planner import generate_chapter_plan


class PlotPlannerTests(unittest.TestCase):
    def test_mock_plan_writes_chapter_plan_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            outline_path = tmp_path / "outline.md"
            plan_path = tmp_path / "chapter_plan.json"
            outline_path.write_text("# mock outline", encoding="utf-8")
            with patch("src.plot_planner.OUTLINE_PATH", outline_path), patch(
                "src.plot_planner.CHAPTER_PLAN_PATH", plan_path
            ):
                data = generate_chapter_plan(target_chapters=5, force=False)

            written = json.loads(plan_path.read_text(encoding="utf-8"))
        self.assertEqual(data["target_chapters"], 5)
        self.assertEqual(len(data["chapters"]), 5)
        self.assertEqual(written["generated_by"], "plot_planner_v1_mock")
        self.assertTrue(written["overall_arc"])
        self.assertIn("opening_scene", written["chapters"][0])
        self.assertGreaterEqual(len(written["chapters"][0]["key_events"]), 2)

    def test_force_false_refuses_to_overwrite_existing_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            outline_path = tmp_path / "outline.md"
            plan_path = tmp_path / "chapter_plan.json"
            outline_path.write_text("# mock outline", encoding="utf-8")
            plan_path.write_text("{}", encoding="utf-8")
            with patch("src.plot_planner.OUTLINE_PATH", outline_path), patch(
                "src.plot_planner.CHAPTER_PLAN_PATH", plan_path
            ):
                with self.assertRaises(FileExistsError):
                    generate_chapter_plan(target_chapters=5, force=False)


if __name__ == "__main__":
    unittest.main()
