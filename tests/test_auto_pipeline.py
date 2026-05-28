"""iter 026: src/auto_pipeline.run_auto_pipeline orchestration tests.

Runs the full 9-step pipeline against a per-test temporary workspace
(patched ``paths.WORKSPACE_DIR``), in mock LLM mode. This mirrors the
WebUI wizard path: the wizard creates ``workspaces/<name>/`` and then
``use_workspace`` + worker thread invoke ``run_auto_pipeline``.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from src import paths
from src.auto_pipeline import STEPS, run_auto_pipeline


SAMPLE_TXT = """第一章 起点

清晨六点，雨敲在玻璃上。
路明非把手机翻过来，再翻回去。
他知道自己得做出选择。
""" * 30


class AutoPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._saved_ws_dir = paths.WORKSPACE_DIR
        self._saved_env = os.environ.get("WORKSPACE_NAME")
        os.environ["OPENAI_MODEL"] = "mock"
        paths.WORKSPACE_DIR = Path(self._tmp.name)
        os.environ["WORKSPACE_NAME"] = "autopipe_test"
        ws = paths.WORKSPACE_DIR / "autopipe_test"
        for sub in ("小说txt", "data", "outputs", "logs"):
            (ws / sub).mkdir(parents=True)
        (ws / "小说txt" / "sample.txt").write_text(SAMPLE_TXT, encoding="utf-8")

    def tearDown(self) -> None:
        paths.WORKSPACE_DIR = self._saved_ws_dir
        if self._saved_env is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._saved_env
        self._tmp.cleanup()

    def _ws_path(self, rel: str) -> Path:
        return paths.WORKSPACE_DIR / "autopipe_test" / rel

    def test_writes_chapter_01_end_to_end(self) -> None:
        results = run_auto_pipeline(target_chapters=1, extract_limit=2, force=True)
        self.assertTrue(self._ws_path("outputs/drafts/chapter_01.md").exists())
        self.assertTrue(self._ws_path("outputs/drafts/chapter_01.meta.json").exists())
        self.assertEqual(len(results["write"]), 1)

    def test_progress_callback_fires_in_step_order(self) -> None:
        seen: list[tuple[str, float]] = []
        run_auto_pipeline(
            target_chapters=1,
            extract_limit=2,
            force=True,
            progress_cb=lambda step, frac: seen.append((step, frac)),
        )
        self.assertEqual(seen[0], ("normalize", 0.0))
        self.assertEqual(seen[-1], ("done", 1.0))
        step_labels = [name for name, _ in seen if name != "done"]
        self.assertEqual(step_labels, list(STEPS))

    def test_propagates_underlying_exception(self) -> None:
        """Removing the raw txt forces an early failure that must
        propagate to the caller (not get swallowed)."""
        shutil.rmtree(self._ws_path("小说txt"))
        # normalize_all returns [] silently if no txt; split_all then
        # raises because no normalized files exist. Either way the
        # caller sees an exception, not a happy results dict.
        with self.assertRaises(Exception):
            run_auto_pipeline(target_chapters=1, extract_limit=2, force=True)

    def test_apply_bootstrap_failure_per_proposal_is_non_fatal(self) -> None:
        """In mock mode the style_examples proposal references a
        non-existent file path. The orchestrator must record the
        failure and keep going so debate / plan / write still run."""
        results = run_auto_pipeline(target_chapters=1, extract_limit=2, force=True)
        applied = results["apply-bootstrap"]
        self.assertEqual(applied["style_examples"]["status"], "apply_failed")
        for name in ("global_facts", "entity_graph", "continuation_anchor", "personas"):
            self.assertEqual(applied[name]["status"], "applied")
        self.assertTrue(self._ws_path("outputs/drafts/chapter_01.md").exists())

    def test_apply_bootstrap_permission_error_propagates(self) -> None:
        """Iter 026 code-review #4 fix: per-proposal apply only catches
        recoverable mock-mode failures (FileNotFoundError / ValueError).
        System errors like PermissionError must propagate so the user
        sees the real root cause via trace_id."""
        from src import auto_pipeline as ap

        original = ap.apply_bootstrap

        def faulty(name, confirm=False):
            if name == "global_facts":
                raise PermissionError("read-only filesystem")
            return original(name, confirm=confirm)

        ap.apply_bootstrap = faulty
        try:
            with self.assertRaises(PermissionError):
                run_auto_pipeline(target_chapters=1, extract_limit=2, force=True)
        finally:
            ap.apply_bootstrap = original

    def test_skip_extract_short_circuits_marker(self) -> None:
        """skip_extract=True records the short-circuit and leaves
        downstream steps to whatever they can do with the (possibly
        empty) extracted dir. We run the full pipeline once to seed
        the artifacts compress / bootstrap / write need, then re-run
        with skip_extract to confirm the marker propagates."""
        run_auto_pipeline(target_chapters=1, extract_limit=2, force=True)
        results = run_auto_pipeline(
            target_chapters=1, skip_extract=True, force=True
        )
        self.assertEqual(results["extract"], {"skipped": True})


if __name__ == "__main__":
    unittest.main()
