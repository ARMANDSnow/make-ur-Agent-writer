import json
import tempfile
import unittest
from pathlib import Path

from src.auto_bootstrap import (
    bootstrap_continuation_anchor,
    bootstrap_entity_graph,
    bootstrap_global_facts,
    bootstrap_personas,
    bootstrap_style_examples,
)


def _seed_bootstrap_root(root: Path) -> None:
    extracted = root / "data" / "extracted_jsons"
    normalized = root / "data" / "normalized_texts"
    extracted.mkdir(parents=True)
    normalized.mkdir(parents=True)
    (extracted / "ch001.json").write_text(
        json.dumps(
            {
                "chapter_id": "book_ch001",
                "title": "第一章",
                "summary": "mock chapter summary",
                "character_states": [{"character": "甲", "after": "做出选择"}],
                "relationships": [],
                "foreshadowing": [],
                "worldbuilding": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (normalized / "mock.txt").write_text("第一行\n第二行\n第三行\n", encoding="utf-8")


class AutoBootstrapTests(unittest.TestCase):
    def test_bootstrap_global_facts_writes_mock_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _seed_bootstrap_root(root)
            result = bootstrap_global_facts(root=root)
            data = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "written")
        self.assertIn("_meta", data)
        self.assertEqual(len(data["facts"]), 1)

    def test_bootstrap_entity_graph_writes_mock_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _seed_bootstrap_root(root)
            result = bootstrap_entity_graph(root=root)
            data = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "written")
        self.assertTrue(data["entities"])
        self.assertTrue(data["relationships"])

    def test_bootstrap_continuation_anchor_writes_mock_proposal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _seed_bootstrap_root(root)
            result = bootstrap_continuation_anchor(root=root)
            data = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "written")
        self.assertIn("anchor_text", data)
        self.assertTrue(data["key_state_points"])

    def test_bootstrap_style_examples_writes_ranges_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _seed_bootstrap_root(root)
            result = bootstrap_style_examples(root=root)
            data = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "written")
        self.assertEqual(len(data["examples"]), 1)
        self.assertLessEqual(len(data["examples"][0]["preview"]), 100)
        self.assertFalse((root / "data" / "style_examples" / "opening_rhythm.md").exists())

    def test_bootstrap_personas_writes_mock_proposal(self) -> None:
        """Iter 016: bootstrap_personas must produce a PersonasProposal-shaped
        file with the seven persona binding fields and a non-empty
        protagonist_name; it must NOT touch the applied manual file.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _seed_bootstrap_root(root)
            result = bootstrap_personas(root=root)
            data = json.loads(Path(result["path"]).read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "written")
        self.assertIn("_meta", data)
        self.assertEqual(data["protagonist_name"], "mock 主角")
        self.assertEqual(data["author_name"], "mock 作者")
        self.assertEqual(data["style_short_descriptor"], "mock 风格描述")
        self.assertTrue(data["world_setting_brief"])
        self.assertEqual(len(data["core_relationships"]), 1)
        self.assertEqual(len(data["core_setting_rules"]), 1)
        # bootstrap must not write the applied manual; only proposal path.
        applied = root / "data" / "manual_overrides" / "personas.json"
        self.assertFalse(applied.exists())


if __name__ == "__main__":
    unittest.main()
