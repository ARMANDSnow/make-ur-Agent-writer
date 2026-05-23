"""Iter 017: workspace isolation across modules.

These tests confirm that switching ``WORKSPACE_NAME`` mid-process actually
routes downstream module path resolution through the new workspace. They
guard against the regression where a module caches its path constant at
import time.

The tests do not perform real LLM calls — they only verify that the
``_resolved_*`` helpers in each refactored module return the per-workspace
path when the env var is set, and the legacy path when it is not.
"""

import os
import unittest

from src import (
    auto_bootstrap,
    chapter_splitter,
    chapter_summary,
    compressor,
    continuation_anchor,
    debater,
    entity_advance,
    extractor,
    manual_facts,
    persona_loader,
    plot_planner,
    reviewer,
    writer,
)
from src import paths
from src.config import ROOT


class _EnvSandbox:
    def __init__(self) -> None:
        self._saved = None

    def __enter__(self) -> "_EnvSandbox":
        self._saved = os.environ.get("WORKSPACE_NAME")
        os.environ.pop("WORKSPACE_NAME", None)
        os.environ.pop("BOOK", None)
        return self

    def __exit__(self, *exc) -> None:
        if self._saved is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._saved


class WorkspaceIsolationTests(unittest.TestCase):
    def test_legacy_mode_all_modules_use_repo_root(self) -> None:
        """Without WORKSPACE_NAME every refactored module resolves paths to
        the original repo-root locations the project used in iter 014-016."""
        with _EnvSandbox():
            self.assertEqual(debater._debate_dir(), ROOT / "outputs" / "debate")
            self.assertEqual(debater._kb_path(), ROOT / "data" / "knowledge_base" / "global_knowledge.md")
            self.assertEqual(writer._drafts_dir(), ROOT / "outputs" / "drafts")
            self.assertEqual(writer._outline_path(), ROOT / "outputs" / "debate" / "outline.md")
            self.assertEqual(writer._chapter_plan_path(), ROOT / "outputs" / "debate" / "chapter_plan.json")
            self.assertEqual(reviewer._reviews_dir(), ROOT / "outputs" / "reviews")
            self.assertEqual(persona_loader._personas_path(), ROOT / "data" / "manual_overrides" / "personas.json")
            self.assertEqual(plot_planner._chapter_plan_path(), ROOT / "outputs" / "debate" / "chapter_plan.json")
            self.assertEqual(plot_planner._outline_path(), ROOT / "outputs" / "debate" / "outline.md")
            self.assertEqual(extractor._extracted_dir(), ROOT / "data" / "extracted_jsons")
            self.assertEqual(extractor._failures_dir(), ROOT / "data" / "extraction_failures")
            self.assertEqual(compressor._extracted_dir(), ROOT / "data" / "extracted_jsons")
            self.assertEqual(compressor._kb_dir(), ROOT / "data" / "knowledge_base")
            self.assertEqual(manual_facts._global_facts_path(), ROOT / "data" / "manual_overrides" / "global_facts.json")
            self.assertEqual(chapter_summary._rolling_path(), ROOT / "outputs" / "drafts" / "rolling_chapter_summary.json")
            self.assertEqual(chapter_splitter._normalized_dir(), ROOT / "data" / "normalized_texts")
            self.assertEqual(chapter_splitter._manifest_path(), ROOT / "data" / "chapter_manifest.json")
            self.assertEqual(entity_advance._drafts_dir(), ROOT / "outputs" / "drafts")
            self.assertEqual(entity_advance._entity_graph_path(), ROOT / "data" / "entity_graph.json")

    def test_named_workspace_all_modules_use_per_book_paths(self) -> None:
        """With WORKSPACE_NAME set, every module's path helper points into
        ``workspaces/<name>/`` instead of the repo root."""
        with _EnvSandbox():
            os.environ["WORKSPACE_NAME"] = "iso_test"
            base = ROOT / "workspaces" / "iso_test"
            self.assertEqual(debater._debate_dir(), base / "outputs" / "debate")
            self.assertEqual(writer._drafts_dir(), base / "outputs" / "drafts")
            self.assertEqual(writer._outline_path(), base / "outputs" / "debate" / "outline.md")
            self.assertEqual(reviewer._reviews_dir(), base / "outputs" / "reviews")
            self.assertEqual(persona_loader._personas_path(), base / "data" / "manual_overrides" / "personas.json")
            self.assertEqual(extractor._extracted_dir(), base / "data" / "extracted_jsons")
            self.assertEqual(compressor._kb_dir(), base / "data" / "knowledge_base")
            self.assertEqual(manual_facts._global_facts_path(), base / "data" / "manual_overrides" / "global_facts.json")
            self.assertEqual(chapter_splitter._normalized_dir(), base / "data" / "normalized_texts")
            self.assertEqual(chapter_summary._rolling_path(), base / "outputs" / "drafts" / "rolling_chapter_summary.json")
            self.assertEqual(entity_advance._entity_graph_path(), base / "data" / "entity_graph.json")

    def test_switching_between_two_workspaces_in_one_process(self) -> None:
        """The critical iter 017 property: two workspaces can coexist in the
        same Python process without leaking paths into each other."""
        with _EnvSandbox():
            os.environ["WORKSPACE_NAME"] = "alpha"
            alpha_drafts = writer._drafts_dir()
            os.environ["WORKSPACE_NAME"] = "beta"
            beta_drafts = writer._drafts_dir()
            self.assertNotEqual(alpha_drafts, beta_drafts)
            self.assertTrue(str(alpha_drafts).endswith("workspaces/alpha/outputs/drafts"))
            self.assertTrue(str(beta_drafts).endswith("workspaces/beta/outputs/drafts"))


if __name__ == "__main__":
    unittest.main()
