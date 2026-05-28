"""iter 027 P2 (code-review #7): shared workspace-name validation
must be the single source of truth for routes.py and wizard.py.
"""

from __future__ import annotations

import unittest

from src.web import _naming, routes, wizard


class NamingSharedModuleTests(unittest.TestCase):
    def test_legacy_rejected(self) -> None:
        self.assertFalse(_naming.validate_workspace_name("legacy"))

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


if __name__ == "__main__":
    unittest.main()
