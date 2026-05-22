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


if __name__ == "__main__":
    unittest.main()
