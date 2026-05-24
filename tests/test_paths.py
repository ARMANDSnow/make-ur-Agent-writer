"""Iter 017: src/paths.py regression tests.

Covers:
* ``workspace_name()`` returns ``None`` for empty / unset / reserved
  ``"legacy"`` env values; returns the trimmed name otherwise.
* ``workspace_root()`` resolves to repo ``ROOT`` in legacy mode and to
  ``WORKSPACE_DIR/<name>`` for a named workspace.
* Per-workspace helpers (``data_dir``, ``debate_dir``, ``drafts_dir``,
  ``reviews_dir``, ``raw_txt_dir``, ``manual_overrides_dir``) all derive
  from ``workspace_root()`` and switch correctly when the env var changes
  mid-process.
* ``WORKSPACE_NAME`` and ``BOOK`` are both honored, with ``WORKSPACE_NAME``
  winning when both are set.
* Reserved ``legacy`` sentinel and pure-whitespace values fall back to
  legacy mode (would otherwise produce ``workspaces/legacy/`` or
  ``workspaces/ /`` paths).
"""

import os
import unittest

from src import paths
from src.config import ROOT


class _EnvSandbox:
    """Mini context manager to scope WORKSPACE_NAME / BOOK env edits."""

    def __init__(self) -> None:
        self._saved: dict = {}

    def __enter__(self) -> "_EnvSandbox":
        for key in ("WORKSPACE_NAME", "BOOK"):
            self._saved[key] = os.environ.get(key)
            if key in os.environ:
                del os.environ[key]
        return self

    def __exit__(self, *exc) -> None:
        for key, val in self._saved.items():
            if val is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = val


class WorkspaceNameTests(unittest.TestCase):
    def test_unset_returns_none(self) -> None:
        with _EnvSandbox():
            self.assertIsNone(paths.workspace_name())

    def test_empty_string_returns_none(self) -> None:
        with _EnvSandbox():
            os.environ["WORKSPACE_NAME"] = ""
            self.assertIsNone(paths.workspace_name())

    def test_whitespace_returns_none(self) -> None:
        with _EnvSandbox():
            os.environ["WORKSPACE_NAME"] = "   "
            self.assertIsNone(paths.workspace_name())

    def test_reserved_legacy_returns_none(self) -> None:
        with _EnvSandbox():
            os.environ["WORKSPACE_NAME"] = "legacy"
            self.assertIsNone(paths.workspace_name())

    def test_named_returns_trimmed_name(self) -> None:
        with _EnvSandbox():
            os.environ["WORKSPACE_NAME"] = "  myBook  "
            self.assertEqual(paths.workspace_name(), "myBook")

    def test_book_env_var_fallback(self) -> None:
        with _EnvSandbox():
            os.environ["BOOK"] = "fromBook"
            self.assertEqual(paths.workspace_name(), "fromBook")

    def test_workspace_name_wins_over_book(self) -> None:
        with _EnvSandbox():
            os.environ["WORKSPACE_NAME"] = "winner"
            os.environ["BOOK"] = "loser"
            self.assertEqual(paths.workspace_name(), "winner")

    def test_path_traversal_with_double_dot_raises(self) -> None:
        """Iter 019 audit fix: WORKSPACE_NAME='../escaped' used to silently
        resolve to a path outside workspaces/. Now it raises ValueError.
        """
        with _EnvSandbox():
            os.environ["WORKSPACE_NAME"] = "../escaped"
            with self.assertRaises(ValueError):
                paths.workspace_name()

    def test_path_separator_in_name_raises(self) -> None:
        """Iter 019 audit fix: forward / backward slash in workspace name."""
        with _EnvSandbox():
            os.environ["WORKSPACE_NAME"] = "a/b"
            with self.assertRaises(ValueError):
                paths.workspace_name()
        with _EnvSandbox():
            os.environ["WORKSPACE_NAME"] = "a\\b"
            with self.assertRaises(ValueError):
                paths.workspace_name()

    def test_leading_dot_raises(self) -> None:
        """Iter 019 audit fix: hidden-file style names rejected."""
        with _EnvSandbox():
            os.environ["WORKSPACE_NAME"] = ".hidden"
            with self.assertRaises(ValueError):
                paths.workspace_name()

    def test_unicode_names_still_allowed(self) -> None:
        """Iter 019 audit fix sanity: Unicode workspace names (e.g. 龙族)
        must still pass — the validation only rejects obvious traversal
        patterns, not non-ASCII identifiers.
        """
        with _EnvSandbox():
            os.environ["WORKSPACE_NAME"] = "龙族"
            self.assertEqual(paths.workspace_name(), "龙族")


class WorkspaceRootTests(unittest.TestCase):
    def test_legacy_root_is_repo_root(self) -> None:
        with _EnvSandbox():
            self.assertEqual(paths.workspace_root(), ROOT)

    def test_named_root_is_workspaces_subdir(self) -> None:
        with _EnvSandbox():
            os.environ["WORKSPACE_NAME"] = "alpha"
            self.assertEqual(paths.workspace_root(), ROOT / "workspaces" / "alpha")

    def test_explicit_name_override(self) -> None:
        """Passing a name explicitly ignores the env var."""
        with _EnvSandbox():
            os.environ["WORKSPACE_NAME"] = "alpha"
            self.assertEqual(paths.workspace_root("beta"), ROOT / "workspaces" / "beta")

    def test_explicit_legacy_sentinel(self) -> None:
        with _EnvSandbox():
            os.environ["WORKSPACE_NAME"] = "alpha"
            self.assertEqual(paths.workspace_root("legacy"), ROOT)


class PathHelperDerivationTests(unittest.TestCase):
    def test_legacy_helpers_resolve_to_repo_root(self) -> None:
        with _EnvSandbox():
            self.assertEqual(paths.data_dir(), ROOT / "data")
            self.assertEqual(paths.debate_dir(), ROOT / "outputs" / "debate")
            self.assertEqual(paths.drafts_dir(), ROOT / "outputs" / "drafts")
            self.assertEqual(paths.reviews_dir(), ROOT / "outputs" / "reviews")
            self.assertEqual(paths.raw_txt_dir(), ROOT / "小说txt")
            self.assertEqual(paths.manual_overrides_dir(), ROOT / "data" / "manual_overrides")
            self.assertEqual(paths.personas_path(), ROOT / "data" / "manual_overrides" / "personas.json")
            self.assertEqual(paths.outline_path(), ROOT / "outputs" / "debate" / "outline.md")

    def test_named_helpers_resolve_to_workspace_subdir(self) -> None:
        with _EnvSandbox():
            os.environ["WORKSPACE_NAME"] = "gamma"
            base = ROOT / "workspaces" / "gamma"
            self.assertEqual(paths.data_dir(), base / "data")
            self.assertEqual(paths.debate_dir(), base / "outputs" / "debate")
            self.assertEqual(paths.drafts_dir(), base / "outputs" / "drafts")
            self.assertEqual(paths.reviews_dir(), base / "outputs" / "reviews")
            self.assertEqual(paths.raw_txt_dir(), base / "小说txt")
            self.assertEqual(paths.manual_overrides_dir(), base / "data" / "manual_overrides")
            self.assertEqual(paths.personas_path(), base / "data" / "manual_overrides" / "personas.json")
            self.assertEqual(paths.outline_path(), base / "outputs" / "debate" / "outline.md")

    def test_mid_process_env_switch(self) -> None:
        """Critical: helpers re-read env on each call so workspace can be
        switched within a single Python process (used by tests + repl)."""
        with _EnvSandbox():
            os.environ["WORKSPACE_NAME"] = "first"
            self.assertEqual(paths.data_dir(), ROOT / "workspaces" / "first" / "data")
            os.environ["WORKSPACE_NAME"] = "second"
            self.assertEqual(paths.data_dir(), ROOT / "workspaces" / "second" / "data")
            del os.environ["WORKSPACE_NAME"]
            self.assertEqual(paths.data_dir(), ROOT / "data")


if __name__ == "__main__":
    unittest.main()
