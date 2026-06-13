import json
import tempfile
import unittest
from pathlib import Path

from src.cli_apply_bootstrap import apply_bootstrap
from src.utils import write_json


class ApplyBootstrapTests(unittest.TestCase):
    def test_dry_run_does_not_write_manual_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json(
                root / "data" / "proposals" / "continuation_anchor.proposal.json",
                {"anchor_text": "mock anchor", "key_state_points": ["state"]},
            )
            result = apply_bootstrap("continuation_anchor", root=root)
            target = root / "data" / "manual_overrides" / "continuation_anchor.txt"
        self.assertEqual(result["status"], "dry_run")
        self.assertFalse(target.exists())

    def test_confirm_writes_global_facts_and_backs_up_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_json(root / "data" / "manual_overrides" / "global_facts.json", [{"fact_id": "old", "statement": "old"}])
            write_json(
                root / "data" / "proposals" / "global_facts.proposal.json",
                {"facts": [{"fact_id": "new", "statement": "new", "confidence": 0.9}]},
            )
            result = apply_bootstrap("global_facts", confirm=True, root=root)
            written = json.loads((root / "data" / "manual_overrides" / "global_facts.json").read_text(encoding="utf-8"))
            backups = list((root / "data" / "proposals" / ".backup").glob("*"))
        self.assertEqual(result["status"], "applied")
        self.assertEqual(written["facts"][0]["fact_id"], "new")
        self.assertTrue(backups)

    def test_style_examples_confirm_copies_source_with_header(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "data" / "normalized_texts" / "book.txt"
            source.parent.mkdir(parents=True)
            source.write_text("line one\nline two\nline three\n", encoding="utf-8")
            write_json(
                root / "data" / "proposals" / "style_examples.proposal.json",
                {
                    "examples": [
                        {
                            "category": "opening_rhythm",
                            "source_file": "data/normalized_texts/book.txt",
                            "start_line": 1,
                            "end_line": 2,
                            "preview": "line one",
                            "target_file": "data/style_examples/opening_rhythm.md",
                        }
                    ]
                },
            )
            result = apply_bootstrap("style_examples", confirm=True, root=root)
            text = (root / "data" / "style_examples" / "opening_rhythm.md").read_text(encoding="utf-8")
        self.assertEqual(result["status"], "applied")
        self.assertTrue(text.startswith("<!-- source: data/normalized_texts/book.txt lines 1-2 -->"))
        self.assertIn("line one\nline two", text)

    def test_style_examples_apply_side_spoiler_guard(self) -> None:
        # iter 054a: apply RE-READS the normalized file, so a post-start (or
        # LLM-hallucinated) line range must be skipped/clamped. before_start_
        # line_limit resolves the workspace via paths, so WORKSPACE_NAME and
        # root must point at the same workspace.
        import os
        import shutil
        from src import start_point

        repo_root = Path(__file__).resolve().parent.parent
        ws = repo_root / "workspaces" / "iter054a_style_guard"
        old_ws = os.environ.get("WORKSPACE_NAME")
        os.environ["WORKSPACE_NAME"] = "iter054a_style_guard"
        try:
            nd = ws / "data" / "normalized_texts"
            nd.mkdir(parents=True, exist_ok=True)
            (ws / "data" / "manual_overrides").mkdir(parents=True, exist_ok=True)
            (nd / "v1.txt").write_text(
                "\n".join(f"L{i}" for i in range(1, 16)) + "\n", encoding="utf-8"
            )
            manifest = [
                {"chapter_id": "c1", "volume_id": "v1",
                 "normalized_file": str(nd / "v1.txt"), "start_line": 1, "end_line": 5},
                {"chapter_id": "c2", "volume_id": "v1",
                 "normalized_file": str(nd / "v1.txt"), "start_line": 6, "end_line": 10},
                {"chapter_id": "c3", "volume_id": "v1",
                 "normalized_file": str(nd / "v1.txt"), "start_line": 11, "end_line": 15},
            ]
            write_json(ws / "data" / "chapter_manifest.json", manifest)
            start_point.set_start_point("c2")  # before-start window = lines 1-10
            write_json(
                ws / "data" / "proposals" / "style_examples.proposal.json",
                {"examples": [
                    {"category": "before", "source_file": "data/normalized_texts/v1.txt",
                     "start_line": 2, "end_line": 4,
                     "target_file": "data/style_examples/before.md"},
                    {"category": "straddle", "source_file": "data/normalized_texts/v1.txt",
                     "start_line": 9, "end_line": 14,
                     "target_file": "data/style_examples/straddle.md"},
                    {"category": "after", "source_file": "data/normalized_texts/v1.txt",
                     "start_line": 12, "end_line": 15,
                     "target_file": "data/style_examples/after.md"},
                ]},
            )
            apply_bootstrap("style_examples", confirm=True, root=ws)
            sd = ws / "data" / "style_examples"
            before = (sd / "before.md").read_text(encoding="utf-8")
            self.assertIn("L2\nL3\nL4", before)            # fully before start → verbatim
            straddle = (sd / "straddle.md").read_text(encoding="utf-8")
            self.assertIn("L9\nL10", straddle)             # clamped to before-start end (10)
            self.assertNotIn("L11", straddle)              # post-start tail dropped
            self.assertNotIn("L14", straddle)
            self.assertFalse((sd / "after.md").exists())   # entirely after start → skipped
        finally:
            if ws.exists():
                shutil.rmtree(ws)
            if old_ws is None:
                os.environ.pop("WORKSPACE_NAME", None)
            else:
                os.environ["WORKSPACE_NAME"] = old_ws

    def test_personas_dry_run_then_confirm_writes_manual_file(self) -> None:
        """Iter 016: apply-bootstrap --name personas dry-run/confirm cycle.

        Dry run must not write to manual_overrides/personas.json. --confirm
        must write the seven persona binding fields and (when the target
        already exists) back up the old one.
        """

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            proposal_payload = {
                "_meta": {"review_instructions": "test"},
                "protagonist_name": "新主角",
                "protagonist_role": "新身份",
                "author_name": "新作者",
                "style_short_descriptor": "简洁含蓄",
                "world_setting_brief": "世界观骨架描述。",
                "core_relationships": ["新主角 与 新同伴 的 同伴 关系"],
                "core_setting_rules": ["规则一", "规则二"],
            }
            write_json(
                root / "data" / "proposals" / "personas.proposal.json",
                proposal_payload,
            )

            applied = root / "data" / "manual_overrides" / "personas.json"

            dry = apply_bootstrap("personas", root=root)
            self.assertEqual(dry["status"], "dry_run")
            self.assertFalse(applied.exists())

            # Seed an existing manual file to verify backup creation.
            write_json(applied, {"protagonist_name": "旧主角"})

            confirmed = apply_bootstrap("personas", confirm=True, root=root)
            written = json.loads(applied.read_text(encoding="utf-8"))
            backups = list((root / "data" / "proposals" / ".backup").glob("*"))

        self.assertEqual(confirmed["status"], "applied")
        # _meta must be stripped on apply; only seven binding fields remain.
        self.assertNotIn("_meta", written)
        self.assertEqual(written["protagonist_name"], "新主角")
        self.assertEqual(written["protagonist_role"], "新身份")
        self.assertEqual(written["author_name"], "新作者")
        self.assertEqual(written["core_relationships"], ["新主角 与 新同伴 的 同伴 关系"])
        self.assertEqual(written["core_setting_rules"], ["规则一", "规则二"])
        self.assertTrue(backups)


if __name__ == "__main__":
    unittest.main()
