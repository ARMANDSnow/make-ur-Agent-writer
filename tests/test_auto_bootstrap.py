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

    def test_load_extractions_before_start_only(self) -> None:
        # iter 054b: start-aware base seal for the entity_graph / global_facts /
        # anchor-fallback paths. is_after_start resolves the workspace via paths
        # (WORKSPACE_NAME), so it must match the root passed to _load_extractions.
        import os
        import shutil
        from src import auto_bootstrap, start_point

        repo_root = Path(__file__).resolve().parent.parent
        ws = repo_root / "workspaces" / "iter054b_load_extractions"
        old_ws = os.environ.get("WORKSPACE_NAME")
        os.environ["WORKSPACE_NAME"] = "iter054b_load_extractions"
        try:
            ex = ws / "data" / "extracted_jsons"
            ex.mkdir(parents=True, exist_ok=True)
            (ws / "data" / "manual_overrides").mkdir(parents=True, exist_ok=True)
            chapter_ids = ["bk_ch001", "bk_ch002", "bk_ch003", "bk_ch004"]
            for cid in chapter_ids:
                (ex / f"{cid}.json").write_text(
                    json.dumps({"chapter_id": cid, "summary": cid}, ensure_ascii=False),
                    encoding="utf-8",
                )
            manifest = [{"chapter_id": cid, "volume_id": "bk"} for cid in chapter_ids]
            (ws / "data" / "chapter_manifest.json").write_text(
                json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
            )
            # no start point → before_start_only keeps all (greenfield fail-open)
            self.assertEqual(
                [d["chapter_id"] for d in auto_bootstrap._load_extractions(ws, before_start_only=True)],
                chapter_ids,
            )
            # start at ch002 → only ch001 + ch002 (start chapter itself) kept
            start_point.set_start_point("bk_ch002")
            self.assertEqual(
                [d["chapter_id"] for d in auto_bootstrap._load_extractions(ws, before_start_only=True)],
                ["bk_ch001", "bk_ch002"],
            )
            # default path (before_start_only=False) still returns all 4 verbatim
            self.assertEqual(
                [d["chapter_id"] for d in auto_bootstrap._load_extractions(ws)],
                chapter_ids,
            )
        finally:
            if ws.exists():
                shutil.rmtree(ws)
            if old_ws is None:
                os.environ.pop("WORKSPACE_NAME", None)
            else:
                os.environ["WORKSPACE_NAME"] = old_ws

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
