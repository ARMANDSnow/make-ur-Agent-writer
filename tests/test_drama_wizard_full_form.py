"""iter 037: drama wizard five-field form tests."""

from __future__ import annotations

import json
import unittest

from src import paths
from src.web import routes, static, workspace_meta
from tests._drama_base import DramaTestBase


def _payload(**overrides: object) -> dict:
    data = {
        "workspace": "drama_a",
        "topic": "test topic",
        "track": "霸总",
        "episode_count": 12,
        "episode_duration_seconds": 60,
    }
    data.update(overrides)
    return data


class DramaWizardFullFormTests(DramaTestBase):
    def _post(self, payload: dict, content_type: str = "application/json") -> tuple[int, dict]:
        status, _ct, body = routes.dispatch(
            "POST",
            "/api/wizard/drama-start",
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            {"content-type": content_type},
        )
        return status, json.loads(body)

    def test_drama_wizard_full_5_field_form_renders(self) -> None:
        status, _ct, body = routes.dispatch("GET", "/wizard")
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        for needle in (
            'name="workspace"',
            'name="topic"',
            'name="track" value="霸总"',
            'name="track" value="重生"',
            'name="track" value="推理"',
            'name="track" value="系统"',
            'name="track" value="觉醒"',
            'name="episode_count"',
            'name="episode_duration_seconds" value="30"',
            'name="episode_duration_seconds" value="120"',
        ):
            self.assertIn(needle, html)

    def test_rejects_empty_topic(self) -> None:
        status, data = self._post(_payload(topic=" "))
        self.assertEqual(status, 400)
        self.assertIn("topic", data["error"])

    def test_rejects_invalid_track(self) -> None:
        status, data = self._post(_payload(track="都市"))
        self.assertEqual(status, 400)
        self.assertIn("track", data["error"])

    def test_rejects_episode_count_zero(self) -> None:
        status, data = self._post(_payload(episode_count=0))
        self.assertEqual(status, 400)
        self.assertIn("episode_count", data["error"])

    def test_rejects_episode_count_too_large(self) -> None:
        status, data = self._post(_payload(episode_count=999))
        self.assertEqual(status, 400)
        self.assertIn("episode_count", data["error"])

    def test_rejects_invalid_duration(self) -> None:
        status, data = self._post(_payload(episode_duration_seconds=45))
        self.assertEqual(status, 400)
        self.assertIn("episode_duration_seconds", data["error"])

    def test_rejects_invalid_body_shape(self) -> None:
        status, _ct, body = routes.dispatch(
            "POST",
            "/api/wizard/drama-start",
            b"[]",
            {"content-type": "application/json"},
        )
        self.assertEqual(status, 400)
        self.assertIn("object", json.loads(body)["error"])

    def test_requires_json_content_type(self) -> None:
        status, data = self._post(_payload(), content_type="text/plain")
        self.assertEqual(status, 415)
        self.assertIn("application/json", data["error"])

    def test_success_creates_snapshot_and_wizard_input_files(self) -> None:
        status, data = self._post(_payload())
        self.assertEqual(status, 200, data)
        self.assertEqual(data, {"name": "drama_a", "type": "drama"})
        self.assertEqual(workspace_meta.read("drama_a")["type"], "drama")
        ws_root = paths.WORKSPACE_DIR / "drama_a"
        wizard_input = json.loads((ws_root / "data" / "wizard_input.json").read_text(encoding="utf-8"))
        self.assertEqual(wizard_input["topic"], "test topic")
        self.assertEqual(wizard_input["track"], "霸总")
        self.assertEqual(wizard_input["episode_count"], 12)
        self.assertEqual(wizard_input["episode_duration_seconds"], 60)
        snapshot = ws_root / "data" / "creation_standard.snapshot.md"
        self.assertTrue(snapshot.is_file())
        self.assertGreater(snapshot.stat().st_size, 0)
        self.assertNotIn("job_id", data)

    def test_duplicate_workspace_returns_409(self) -> None:
        status, data = self._post(_payload())
        self.assertEqual(status, 200, data)
        status, data = self._post(_payload())
        self.assertEqual(status, 409)
        self.assertIn("already exists", data["error"])

    def test_topic_too_long_returns_400(self) -> None:
        status, data = self._post(_payload(topic="x" * 501))
        self.assertEqual(status, 400)
        self.assertIn("too long", data["error"])

    def test_wizard_js_redirects_drama_start_to_write_setup(self) -> None:
        self.assertIn("/api/wizard/drama-start", static.JS_WIZARD)
        self.assertIn("/write?step=setup", static.JS_WIZARD)
        for key in ("topic", "track", "episode_count", "episode_duration_seconds"):
            self.assertIn(key, static.JS_WIZARD)


if __name__ == "__main__":
    unittest.main()
