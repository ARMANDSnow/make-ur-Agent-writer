"""Focused contracts for the iter103 loopback fake-provider harness."""

from __future__ import annotations

import base64
import http.client
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import run_local_drama_e2e as harness
from src import ai_draw_client, drama_video, drama_video_client
from tests.support.local_drama_provider import (
    LocalDramaProvider,
    PNG_1X1,
    mp4_sample_dimensions,
    strict_mp4_fixture,
)


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "provider_contracts"


class LocalDramaE2ETests(unittest.TestCase):
    def setUp(self) -> None:
        self.environment = patch.dict(os.environ, {
            "DRAGON_RAJA_SKIP_DOTENV": "1",
            "PYTHON_DOTENV_DISABLED": "1",
            "OPENAI_MODEL": "mock",
            "DRAMA_MODEL": "mock",
        }, clear=False)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        for key in ("OPENAI_API_KEY", "PLANNER_API_KEY", "AI_DRAW_API_KEY", "SD_API_KEY"):
            os.environ.pop(key, None)

    def test_strict_media_fixtures_pass_production_parsers(self) -> None:
        self.assertEqual(ai_draw_client._detect_image_type(PNG_1X1), ("image/png", ".png"))
        payload = strict_mp4_fixture()
        spec = drama_video._probe_mp4(payload)
        self.assertEqual((spec.duration_seconds, spec.width, spec.height), (5.0, 720, 1280))
        self.assertEqual(mp4_sample_dimensions(payload), (720, 1280))

    def test_fake_provider_uses_real_loopback_http_and_redacted_counts(self) -> None:
        with LocalDramaProvider() as provider:
            connection = http.client.HTTPConnection(
                "127.0.0.1", provider.server.server_port, timeout=5
            )
            body = json.dumps({
                "model": "local-openai-image-adapter",
                "prompt": "original local fixture",
                "size": "1024x1024",
                "n": 1,
            }).encode("utf-8")
            try:
                connection.request("POST", "/v1/images/generations", body=body, headers={
                    "Authorization": "Bearer local-image-test-token",
                    "Content-Type": "application/json",
                })
                response = connection.getresponse()
                payload = json.loads(response.read().decode("utf-8"))
            finally:
                connection.close()
            self.assertEqual(response.status, 200)
            decoded = base64.b64decode(payload["data"][0]["b64_json"], validate=True)
            self.assertEqual(decoded, PNG_1X1)
            self.assertEqual(provider.counters()["image_generate"], 1)
            rendered = json.dumps(provider.counters(), sort_keys=True).lower()
            for forbidden in ("token", "prompt", "signature", "url", "authorization"):
                self.assertNotIn(forbidden, rendered)

    def test_fake_provider_rejects_malformed_image_row_with_bounded_400(self) -> None:
        with LocalDramaProvider() as provider:
            connection = http.client.HTTPConnection(
                "127.0.0.1", provider.server.server_port, timeout=5
            )
            body = {
                "model": "seedance-1-0-pro-250528",
                "content": [
                    {"type": "text", "text": "local fixture"},
                    {"type": "image_url", "role": "reference_image", "image_url": "bad"},
                ],
                "duration": 5,
                "resolution": "720p",
                "ratio": "9:16",
                "generate_audio": False,
                "watermark": False,
            }
            try:
                connection.request(
                    "POST", "/v1/video/generate",
                    body=json.dumps(body).encode("utf-8"),
                    headers={
                        "Authorization": "Bearer local-video-test-token",
                        "Content-Type": "application/json",
                    },
                )
                response = connection.getresponse()
                response.read()
            finally:
                connection.close()
            self.assertEqual(response.status, 400)
            self.assertEqual(provider.counters()["video_create"], 0)

    def test_production_loopback_guards_remain_closed(self) -> None:
        with self.assertRaisesRegex(ValueError, "https"):
            ai_draw_client.validate_api_base_url(
                "http://127.0.0.1:9999/v1", label="AI draw base URL"
            )
        with self.assertRaisesRegex(ValueError, "public address"):
            ai_draw_client._validate_public_endpoint("127.0.0.1")
        with self.assertRaisesRegex(ValueError, "https"):
            drama_video_client.DramaVideoClient(
                base_url="http://127.0.0.1:9999", api_key="local-test-only"
            )

    def test_golden_contracts_distinguish_adapters_and_disclaim_authority(self) -> None:
        image = json.loads((FIXTURES / "openai_image_request.json").read_text(encoding="utf-8"))
        video = json.loads((FIXTURES / "compatible_video_request.json").read_text(encoding="utf-8"))
        self.assertEqual(image["adapter"], "openai-image")
        self.assertEqual(video["adapter"], "short-drama-compatible-video")
        self.assertNotEqual(image["adapter"], video["adapter"])
        for fixture in (image, video):
            self.assertEqual(fixture["authority"], "local-contract-fixture-only")
            self.assertEqual(fixture["reviewed_at"], "2026-07-14")

    def test_evidence_is_atomic_single_link_and_never_provider_validated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "local.json"
            value = {
                "schema_version": 1,
                "status": "passed",
                "acceptance_level": "local-e2e",
                "provider_validated": False,
            }
            harness._atomic_json(path, value)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), value)
            self.assertFalse(path.is_symlink())
            self.assertEqual(path.stat().st_nlink, 1)

    def test_workspace_root_requires_verify_owned_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaisesRegex(ValueError, "marker"):
                harness._workspace_root(str(root))
            marker = root / ".dragon-raja-local-e2e"
            marker.write_text("iter103\n", encoding="utf-8")
            self.assertEqual(harness._workspace_root(str(root)), root.resolve())


if __name__ == "__main__":
    unittest.main()
