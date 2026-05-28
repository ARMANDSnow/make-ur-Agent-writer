"""iter 026: settings panel — .env read / write + key masking."""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from pathlib import Path

from src.web import routes, settings as settings_mod


class SettingsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.NamedTemporaryFile(suffix=".env", delete=False)
        self._tmp.write(
            b"OPENAI_API_KEY=sk-1234567890abcdefghij\n"
            b"OPENAI_MODEL=deepseek/deepseek-chat\n"
            b"OPENAI_BASE_URL=https://api.deepseek.com\n"
            b"UNRELATED_VAR=keep-me\n"
        )
        self._tmp.close()
        self._saved_path = settings_mod._ENV_PATH
        settings_mod._ENV_PATH = Path(self._tmp.name)

    def tearDown(self) -> None:
        settings_mod._ENV_PATH = self._saved_path
        Path(self._tmp.name).unlink(missing_ok=True)
        # Clean any .tmp leftover from atomic write
        Path(self._tmp.name + ".tmp").unlink(missing_ok=True)

    def test_get_masks_api_key(self) -> None:
        status, _ct, body = routes.dispatch("GET", "/api/settings")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["settings"]["OPENAI_API_KEY"], "sk-***ghij")
        # No full key anywhere in the response body
        self.assertIsNone(re.search(rb"sk-[A-Za-z0-9]{16,}", body))

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

    def test_put_updates_only_listed_fields(self) -> None:
        status, _ct, body = routes.dispatch(
            "PUT", "/api/settings", json.dumps({"OPENAI_MODEL": "mock"}).encode()
        )
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertTrue(data["saved"])
        self.assertTrue(data["restart_required"])
        # Untouched keys preserved on disk
        on_disk = Path(self._tmp.name).read_text(encoding="utf-8")
        self.assertIn("OPENAI_MODEL=mock", on_disk)
        self.assertIn("UNRELATED_VAR=keep-me", on_disk)
        self.assertIn("OPENAI_API_KEY=sk-1234567890abcdefghij", on_disk)

    def test_put_atomic_replace_no_tmp_left(self) -> None:
        routes.dispatch("PUT", "/api/settings", json.dumps({"OPENAI_MODEL": "mock"}).encode())
        self.assertFalse(Path(self._tmp.name + ".tmp").exists())


if __name__ == "__main__":
    unittest.main()
