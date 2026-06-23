"""iter 027 P2 (code-review #7): shared workspace-name validation
must be the single source of truth for routes.py and wizard.py.
"""

from __future__ import annotations

import re
import unittest

from src.web import _naming, routes, wizard


class NamingSharedModuleTests(unittest.TestCase):
    def test_legacy_rejected(self) -> None:
        self.assertFalse(_naming.validate_workspace_name("legacy"))

    def test_trash_reserved(self) -> None:
        self.assertFalse(_naming.validate_workspace_name("_trash"))

    def test_valid_ascii(self) -> None:
        for ok in ("alpha", "alpha_beta", "alpha-beta", "a1b2c3", "_x", "x_"):
            self.assertTrue(_naming.validate_workspace_name(ok), f"rejected {ok!r}")

    def test_valid_cjk(self) -> None:
        for ok in ("龙族", "西游_2026", "三国-演义"):
            self.assertTrue(_naming.validate_workspace_name(ok), f"rejected {ok!r}")

    def test_leading_trailing_dash_rejected(self) -> None:
        for bad in ("-foo", "foo-", "-", "--"):
            self.assertFalse(_naming.validate_workspace_name(bad), f"accepted {bad!r}")

    def test_path_traversal_rejected(self) -> None:
        for bad in ("../etc", "foo/bar", ".hidden", "a\\b"):
            self.assertFalse(_naming.validate_workspace_name(bad), f"accepted {bad!r}")

    def test_length_cap_33_rejected(self) -> None:
        self.assertFalse(_naming.validate_workspace_name("a" * 33))
        self.assertTrue(_naming.validate_workspace_name("a" * 32))


class CrossModuleSyncTests(unittest.TestCase):
    """If routes.py and wizard.py drift on what's accepted, a workspace
    could get created via the wizard that the dashboard then rejects
    with 400 — invisible workspace. Pin the contract via cross-module
    object identity."""

    def test_routes_and_wizard_share_validator(self) -> None:
        # Both modules' validators should accept the same set, exactly.
        for name in (
            "alpha",
            "龙族",
            "-bad",
            "legacy",
            "_trash",
            "ok_name-1",
            "..escape",
            "a" * 32,
            "a" * 33,
        ):
            self.assertEqual(
                routes._validate_workspace_name(name),
                wizard._validate_name(name),
                f"routes / wizard disagree on {name!r}",
            )

    def test_reserved_names_in_sync(self) -> None:
        self.assertEqual(routes._RESERVED_WORKSPACE_NAMES, _naming.RESERVED_NAMES)


class HtmlPatternBackendSyncTests(unittest.TestCase):
    """iter064 #5: the wizard's client-side HTML ``pattern`` must accept/reject
    the exact same names as the backend ``WORKSPACE_NAME_RE``. Before this fix
    the frontend's optional final char (``[...]?``) wrongly accepted a trailing
    hyphen (``foo-``) that the backend rejects — a name that passes the browser
    but 400s on submit."""

    def test_html_pattern_matches_backend_re(self) -> None:
        # HTML input ``pattern`` is implicitly anchored; add ^...$ to compare.
        anchored = re.compile("^(?:" + _naming.WORKSPACE_NAME_HTML_PATTERN + ")$")
        cases = [
            ("f", True),
            ("foo-bar", True),
            ("foo_bar", True),
            ("foo-", False),   # trailing hyphen — old frontend wrongly allowed it
            ("-foo", False),
            ("a" * 32, True),
            ("a" * 33, False),
            ("龙族", True),
            ("三国-演义", True),
        ]
        for name, ok in cases:
            self.assertEqual(bool(anchored.match(name)), ok, f"html pattern: {name!r}")
            self.assertEqual(bool(_naming.WORKSPACE_NAME_RE.match(name)), ok, f"backend RE: {name!r}")

    def test_html_pattern_keeps_chromium_v_flag_escape(self) -> None:
        # iter063 A4: a bare `-` in the char class is a `v`-flag SyntaxError in
        # Chromium. The single-sourced constant must keep the hyphen escaped.
        self.assertIn(r"\-", _naming.WORKSPACE_NAME_HTML_PATTERN)


if __name__ == "__main__":
    unittest.main()
