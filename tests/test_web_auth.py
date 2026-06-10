"""Tests for the opt-in bearer-token gate (iter 049).

``src/web/auth.py`` unit behaviour + the ``routes.dispatch`` integration:
unset → open (back-compat, the existing suite never sends a token), set+correct
→ pass, set+missing/wrong → 401, and browser deep-link / landing paths stay
open even when the gate is on.
"""

import os
import unittest

from src.web import auth, routes


class _EnvGuard(unittest.TestCase):
    """Save/restore NOVEL_API_TOKEN around each test so the gate never leaks
    into the rest of the suite."""

    def setUp(self):
        self._prev = os.environ.get(auth.TOKEN_ENV)

    def tearDown(self):
        if self._prev is None:
            os.environ.pop(auth.TOKEN_ENV, None)
        else:
            os.environ[auth.TOKEN_ENV] = self._prev


class AuthUnitTest(_EnvGuard):
    def test_required_token_unset_and_trimmed(self):
        os.environ.pop(auth.TOKEN_ENV, None)
        self.assertIsNone(auth.required_token())
        os.environ[auth.TOKEN_ENV] = "  abc  "
        self.assertEqual(auth.required_token(), "abc")

    def test_non_api_paths_always_open(self):
        self.assertTrue(auth.is_authorized("/", {}, "tok"))
        self.assertTrue(auth.is_authorized("/w/x/workbench", {}, "tok"))
        self.assertTrue(auth.is_authorized("/library", {}, "tok"))

    def test_api_requires_matching_bearer(self):
        self.assertFalse(auth.is_authorized("/api/x", {}, "tok"))
        self.assertFalse(auth.is_authorized("/api/x", {"authorization": "Bearer wrong"}, "tok"))
        self.assertFalse(auth.is_authorized("/api/x", {"authorization": "tok"}, "tok"))  # no scheme
        self.assertTrue(auth.is_authorized("/api/x", {"authorization": "Bearer tok"}, "tok"))

    def test_bearer_scheme_case_insensitive(self):
        self.assertTrue(auth.is_authorized("/api/x", {"authorization": "bearer tok"}, "tok"))


class AuthGateDispatchTest(_EnvGuard):
    def _get(self, path, headers=None):
        status, _ctype, _body = routes.dispatch("GET", path, b"", headers or {})
        return status

    def test_disabled_when_token_unset(self):
        os.environ.pop(auth.TOKEN_ENV, None)
        self.assertNotEqual(self._get("/api/workspaces/"), 401)

    def test_api_blocked_without_token(self):
        os.environ[auth.TOKEN_ENV] = "secret123"
        self.assertEqual(self._get("/api/workspaces/"), 401)

    def test_api_open_with_correct_token(self):
        os.environ[auth.TOKEN_ENV] = "secret123"
        self.assertNotEqual(
            self._get("/api/workspaces/", {"authorization": "Bearer secret123"}), 401
        )

    def test_api_blocked_with_wrong_token(self):
        os.environ[auth.TOKEN_ENV] = "secret123"
        self.assertEqual(
            self._get("/api/workspaces/", {"authorization": "Bearer nope"}), 401
        )

    def test_deep_link_open_even_when_gated(self):
        os.environ[auth.TOKEN_ENV] = "secret123"
        self.assertNotEqual(self._get("/w/anybook/workbench"), 401)

    def test_landing_open_even_when_gated(self):
        os.environ[auth.TOKEN_ENV] = "secret123"
        self.assertNotEqual(self._get("/"), 401)


if __name__ == "__main__":
    unittest.main()
