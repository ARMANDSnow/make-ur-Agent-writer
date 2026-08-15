"""Settings panel storage and browser-safe projection."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.web import routes, settings as settings_mod


class SettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.NamedTemporaryFile(suffix=".env", delete=False)
        self._tmp.write(
            b"OPENAI_API_KEY=test-api-key-1234567890abcdefghij\n"
            b"OPENAI_MODEL=deepseek/deepseek-chat\n"
            b"OPENAI_BASE_URL=https://api.deepseek.com\n"
            b"PLANNER_API_KEY=test-planner-key-1234567890abcdefghij\n"
            b"UNRELATED_VAR=keep-me\n"
        )
        self._tmp.close()
        self._saved_path = settings_mod._ENV_PATH
        settings_mod._ENV_PATH = Path(self._tmp.name)

    def tearDown(self) -> None:
        settings_mod._ENV_PATH = self._saved_path
        Path(self._tmp.name).unlink(missing_ok=True)
        # iter 048d (A5): atomic write now uses per-writer tmp suffix
        # (.tmp.<pid>.<tid>), so glob-clean any leftover.
        base = Path(self._tmp.name)
        for leftover in base.parent.glob(base.name + ".tmp*"):
            leftover.unlink(missing_ok=True)

    def test_get_returns_zero_secret_fragments(self) -> None:
        status, _ct, body = routes.dispatch("GET", "/api/settings")
        self.assertEqual(status, 200)
        data = json.loads(body)
        for key in settings_mod.SECRET_KEYS:
            self.assertEqual(data["settings"][key], "")
            self.assertTrue(data["configured"][key])
        self.assertNotIn(b"tes***ghij", body)
        self.assertNotIn(b"test-api-key", body)

    def test_put_unknown_key_400(self) -> None:
        status, _ct, body = routes.dispatch(
            "PUT", "/api/settings", json.dumps({"EVIL_KEY": "x"}).encode()
        )
        self.assertEqual(status, 400)
        self.assertIn("unknown key", json.loads(body)["error"])

    def test_put_rejects_control_characters(self) -> None:
        for bad in ("foo\nbar", "x\rdone", "null\x00byte"):
            status, _ct, body = routes.dispatch(
                "PUT", "/api/settings", json.dumps({"OPENAI_MODEL": bad}).encode()
            )
            self.assertEqual(status, 400, f"value {bad!r} should be rejected")





    def test_put_atomic_replace_no_tmp_left(self) -> None:
        routes.dispatch("PUT", "/api/settings", json.dumps({"OPENAI_MODEL": "mock"}).encode())
        # iter 048d (A5): tmp suffix is now .tmp.<pid>.<tid>; glob-assert
        # no leftover of any shape.
        base = Path(self._tmp.name)
        leftovers = list(base.parent.glob(base.name + ".tmp*"))
        self.assertEqual(leftovers, [], f"unexpected tmp leftover: {leftovers}")


if __name__ == "__main__":
    unittest.main()
