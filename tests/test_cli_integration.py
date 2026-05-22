import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import main


class CliIntegrationTests(unittest.TestCase):
    def run_cli(self, argv):
        with patch("sys.argv", ["main.py"] + argv):
            buf = io.StringIO()
            with redirect_stdout(buf):
                main.main()
            return buf.getvalue()

    def test_status_manifest_review_and_cost_commands_dispatch(self) -> None:
        with patch("main.status_report", return_value="# status\n"):
            self.assertIn("# status", self.run_cli(["status"]))
        with patch("main.generate_manifest_report", return_value="data/chapter_manifest.md"):
            self.assertIn("Manifest report written", self.run_cli(["manifest-report"]))
        with patch("main.generate_review_summary") as mock_summary:
            class FakePath:
                def read_text(self, encoding="utf-8"):
                    return "# review\n"

                def __str__(self):
                    return "outputs/reviews/review_summary.md"

            mock_summary.return_value = ({}, FakePath())
            self.assertIn("# review", self.run_cli(["review-summary"]))
        with patch("main.check_report_snapshots", return_value={"checked": ["a.md"], "updated": False, "ok": True, "mismatches": {}}):
            self.assertIn("Report snapshots OK", self.run_cli(["check-reports"]))
        with patch(
            "main.check_manifest_integrity",
            return_value={
                "chapters": 1,
                "volumes": {"v": 1},
                "errors": [],
                "warnings": [],
                "strict": False,
                "ok": True,
            },
        ):
            self.assertIn("Manifest Check", self.run_cli(["check-manifest"]))
        with patch(
            "main.estimate_cost",
            return_value={
                "chapters": 0,
                "source_chars": 0,
                "estimated_source_tokens": 0,
                "llm_logged_calls": 0,
                "actual_prompt_tokens": 0,
                "actual_response_tokens": 0,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
                "extract_calls": 0,
                "compress_calls": 0,
                "debate_calls": 36,
                "review_calls_per_written_chapter": 7,
                "note": "n",
            },
        ):
            self.assertIn("Cost Estimate", self.run_cli(["estimate-cost"]))
        with patch("main.run_preflight", return_value={"status": "ok", "fatal": [], "warn": [], "info": [], "next_steps": ["next"]}):
            self.assertIn("PREFLIGHT: ok", self.run_cli(["preflight"]))

    def test_check_reports_exits_nonzero_on_drift(self) -> None:
        with patch("main.check_report_snapshots") as check:
            check.return_value = {
                "checked": ["a.md"],
                "updated": False,
                "ok": False,
                "mismatches": {"a.md": "--- a.md\n+++ a.md\n"},
            }
            with self.assertRaises(SystemExit) as raised:
                self.run_cli(["check-reports"])
            self.assertEqual(raised.exception.code, 1)

    def test_check_manifest_exits_nonzero_on_errors(self) -> None:
        with patch("main.check_manifest_integrity") as check:
            check.return_value = {
                "chapters": 1,
                "volumes": {"v": 1},
                "errors": ["bad"],
                "warnings": [],
                "strict": False,
                "ok": False,
            }
            with self.assertRaises(SystemExit) as raised:
                self.run_cli(["check-manifest"])
            self.assertEqual(raised.exception.code, 1)

    def test_preflight_exits_nonzero_on_fatal(self) -> None:
        with patch(
            "main.run_preflight",
            return_value={"status": "fail", "fatal": ["bad"], "warn": [], "info": [], "next_steps": ["fix"]},
        ):
            with self.assertRaises(SystemExit) as raised:
                self.run_cli(["preflight"])
            self.assertEqual(raised.exception.code, 1)

    def test_run_all_small_mock_dispatches_steps(self) -> None:
        with patch("main.normalize_all") as normalize, patch("main.split_all") as split, patch(
            "main.extract_all"
        ) as extract, patch("main.compress_all") as compress, patch("main.run_debate") as debate, patch(
            "main.write_chapters"
        ) as write:
            self.run_cli(["run-all", "--extract-limit", "2", "--chapters", "1", "--force"])
        normalize.assert_called_once()
        split.assert_called_once()
        extract.assert_called_once_with(volume="all", limit=2, force=True)
        compress.assert_called_once()
        debate.assert_called_once()
        write.assert_called_once_with(chapters=1, force=True)

    def test_init_book_runs_extract_compress_and_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            os.chdir(tmp)
            try:
                (Path("小说txt")).mkdir()
                (Path("小说txt") / "book.txt").write_text("text", encoding="utf-8")
                (Path("data") / "normalized_texts").mkdir(parents=True)
                (Path("data") / "normalized_texts" / "book.txt").write_text("text", encoding="utf-8")
                (Path("data") / "chapter_manifest.json").write_text("[]", encoding="utf-8")
                order = []
                with patch("main.extract_all", side_effect=lambda **kwargs: order.append("extract")) as extract, patch(
                    "main.compress_all", side_effect=lambda: order.append("compress")
                ), patch(
                    "main.bootstrap_all",
                    side_effect=lambda force=False: order.append("bootstrap")
                    or {
                        "global_facts": {"name": "global_facts", "status": "written", "path": "p", "data": {"facts": []}},
                        "entity_graph": {"name": "entity_graph", "status": "written", "path": "p", "data": {}},
                        "continuation_anchor": {
                            "name": "continuation_anchor",
                            "status": "written",
                            "path": "p",
                            "data": {},
                        },
                        "style_examples": {"name": "style_examples", "status": "written", "path": "p", "data": {}},
                    },
                ):
                    main.init_book_pipeline(extract_limit=10)
                extract.assert_called_once_with(volume="all", limit=10, force=False)
                self.assertEqual(order, ["extract", "compress", "bootstrap"])
            finally:
                os.chdir(cwd)

    def test_init_book_skip_extract_does_not_call_extract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cwd = os.getcwd()
            os.chdir(tmp)
            try:
                (Path("小说txt")).mkdir()
                (Path("小说txt") / "book.txt").write_text("text", encoding="utf-8")
                (Path("data") / "normalized_texts").mkdir(parents=True)
                (Path("data") / "normalized_texts" / "book.txt").write_text("text", encoding="utf-8")
                (Path("data") / "chapter_manifest.json").write_text("[]", encoding="utf-8")
                with patch("main.extract_all") as extract, patch("main.compress_all"), patch(
                    "main.bootstrap_all",
                    return_value={
                        "global_facts": {"name": "global_facts", "status": "written", "path": "p", "data": {"facts": []}},
                        "entity_graph": {"name": "entity_graph", "status": "written", "path": "p", "data": {}},
                        "continuation_anchor": {
                            "name": "continuation_anchor",
                            "status": "written",
                            "path": "p",
                            "data": {},
                        },
                        "style_examples": {"name": "style_examples", "status": "written", "path": "p", "data": {}},
                    },
                ):
                    main.init_book_pipeline(skip_extract=True)
                extract.assert_not_called()
            finally:
                os.chdir(cwd)


if __name__ == "__main__":
    unittest.main()
