"""iter089: real image protocol and guarded video API client tests."""

from __future__ import annotations

import base64
import json
import os
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src import ai_draw_client, character_designer, drama_image_smoke, drama_video_client, preflight, storyboard_builder
from src.drama_schemas import character_paths, episode_paths
from src.web import routes
from src.secure_http import BoundedResponse
from tests._drama_base import DramaTestBase


PNG_BYTES = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


class _FakeResponse:
    def __init__(self, body: bytes, content_type: str = "application/json") -> None:
        self.body = body
        self.headers = {"content-type": content_type}

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, limit: int) -> bytes:
        return self.body[:limit]


class _CaptureOpener:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self.responses = list(responses)
        self.requests = []

    def open(self, request, timeout):  # noqa: ANN001
        self.requests.append((request, timeout))
        if not self.responses:
            raise AssertionError("unexpected network request")
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


class DramaImageClientTests(DramaTestBase):
    def setUp(self) -> None:
        super().setUp()
        for key in ("AI_DRAW_ENDPOINT", "AI_DRAW_BASE_URL", "AI_DRAW_API_KEY", "AI_DRAW_MODEL"):
            os.environ.pop(key, None)
        self._make_drama_workspace("image", "霸总")
        self._write_setup("image", hook=True)
        board = storyboard_builder.run("image", mock=True)
        path = episode_paths("image").storyboard_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(board, ensure_ascii=False), encoding="utf-8")
        self.character = character_designer.run("image", mock=True)["characters"][0]

    def test_auto_mode_stays_local_without_explicit_image_model(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "OPENAI_MODEL": "mock",
                "AI_DRAW_BASE_URL": "https://93.184.216.34/v1",
                "AI_DRAW_API_KEY": "test-image-key",
            },
            clear=False,
        ):
            with patch("src.ai_draw_client.request_bytes", side_effect=AssertionError("network attempted")):
                result = ai_draw_client.redraw_character_reference("image", self.character, mock=None)
        self.assertEqual(result["generated_by"], "placeholder_png")
        placeholder = (character_paths("image").root / result["path"]).read_bytes()
        self.assertEqual(ai_draw_client._detect_image_type(placeholder), ("image/png", ".png"))
        self.assertEqual(ai_draw_client._image_dimensions(placeholder, "image/png"), (512, 512))

    def test_openai_compatible_base64_response_is_persisted(self) -> None:
        response = json.dumps(
            {
                "model": "gpt-image-2-provider-alias",
                "size": "auto",
                "data": [{"b64_json": base64.b64encode(PNG_BYTES).decode("ascii")}],
            }
        ).encode()
        with patch.dict(
            "os.environ",
            {
                "AI_DRAW_BASE_URL": "https://93.184.216.34/api/v1",
                "AI_DRAW_API_KEY": "test-image-key",
                "AI_DRAW_MODEL": "gpt-image-2",
            },
            clear=False,
        ):
            with patch("src.ai_draw_client.request_bytes", return_value=BoundedResponse(200, "application/json", response)) as request_call:
                result = ai_draw_client.redraw_character_reference("image", self.character, mock=False)

        self.assertEqual(request_call.call_args.args[0], "https://93.184.216.34/api/v1/images/generations")
        self.assertEqual(request_call.call_args.kwargs["timeout_seconds"], ai_draw_client.IMAGE_GENERATION_TIMEOUT_SECONDS)
        payload = json.loads(request_call.call_args.kwargs["body"])
        self.assertEqual(payload["model"], "gpt-image-2")
        self.assertNotIn("response_format", payload)
        self.assertEqual(request_call.call_args.kwargs["headers"]["Authorization"], "Bearer test-image-key")
        self.assertEqual(request_call.call_args.kwargs["headers"]["User-Agent"], ai_draw_client.USER_AGENT)
        self.assertEqual(result["generated_by"], "gpt-image-2-provider-alias")
        self.assertEqual(result["requested_model"], "gpt-image-2")
        self.assertEqual(result["requested_size"], "1024x1024")
        self.assertEqual(result["provider_size"], "auto")
        self.assertEqual((result["width"], result["height"]), (1, 1))
        self.assertNotIn("test-image-key", json.dumps(result))
        self.assertEqual((character_paths("image").root / result["path"]).read_bytes(), PNG_BYTES)

    def test_bad_base64_is_rejected_without_artifact(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "AI_DRAW_BASE_URL": "https://93.184.216.34/v1",
                "AI_DRAW_API_KEY": "test-image-key",
            },
            clear=False,
        ):
            with patch("src.ai_draw_client.request_bytes", return_value=BoundedResponse(200, "application/json", b'{"data":[{"b64_json":"%%%"}]}')):
                with self.assertRaisesRegex(ValueError, "base64"):
                    ai_draw_client.redraw_character_reference("image", self.character, mock=False)
        self.assertFalse((character_paths("image").refs_dir / self.character["id"]).exists())

    def test_base_url_credentials_are_rejected_before_network(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "AI_DRAW_BASE_URL": "https://user:pass@93.184.216.34/v1",
                "AI_DRAW_API_KEY": "test-image-key",
            },
            clear=False,
        ):
            with patch("src.ai_draw_client.request_bytes", side_effect=AssertionError("network attempted")):
                with self.assertRaisesRegex(ValueError, "base URL"):
                    ai_draw_client.redraw_character_reference("image", self.character, mock=False)

    def test_openai_image_credentials_require_https(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "AI_DRAW_BASE_URL": "http://93.184.216.34/v1",
                "AI_DRAW_API_KEY": "test-image-key",
            },
            clear=False,
        ):
            with patch("src.ai_draw_client.request_bytes", side_effect=AssertionError("network attempted")):
                with self.assertRaisesRegex(ValueError, "https URL"):
                    ai_draw_client.redraw_character_reference("image", self.character, mock=False)

    def test_partial_dedicated_credentials_never_cross_fall_back(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "AI_DRAW_MODEL": "gpt-image-2",
                "AI_DRAW_BASE_URL": "https://93.184.216.34/v1",
                "OPENAI_API_KEY": "must-not-cross-fallback",
            },
            clear=False,
        ):
            os.environ.pop("AI_DRAW_API_KEY", None)
            with patch("src.ai_draw_client.request_bytes", side_effect=AssertionError("network attempted")):
                with self.assertRaisesRegex(ValueError, "configured together"):
                    ai_draw_client.redraw_character_reference("image", self.character, mock=None)

    def test_explicit_image_model_enables_real_path_even_when_text_model_is_mock(self) -> None:
        response = json.dumps({"data": [{"b64_json": base64.b64encode(PNG_BYTES).decode("ascii")}]}).encode()
        with patch.dict(
            "os.environ",
            {
                "OPENAI_MODEL": "mock",
                "AI_DRAW_MODEL": "gpt-image-2",
                "AI_DRAW_BASE_URL": "https://93.184.216.34/v1",
                "AI_DRAW_API_KEY": "test-image-key",
            },
            clear=False,
        ):
            with patch("src.ai_draw_client.request_bytes", return_value=BoundedResponse(200, "application/json", response)) as request_call:
                result = ai_draw_client.redraw_character_reference("image", self.character, mock=None)
        self.assertEqual(result["requested_model"], "gpt-image-2")
        request_call.assert_called_once()

    def test_atomic_replace_failure_preserves_existing_image(self) -> None:
        path = character_paths("image").refs_dir / self.character["id"] / "portrait_neutral.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"old-image")
        with patch("src.ai_draw_client.os.replace", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                ai_draw_client._atomic_write_bytes(path, PNG_BYTES)
        self.assertEqual(path.read_bytes(), b"old-image")
        self.assertEqual(list(path.parent.glob(".portrait_neutral.png.tmp.*")), [])

    def test_private_result_url_is_rejected_before_download(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "AI_DRAW_BASE_URL": "https://93.184.216.34/v1",
                "AI_DRAW_API_KEY": "test-image-key",
                "AI_DRAW_RESULT_HOSTS": "127.0.0.1",
            },
            clear=False,
        ):
            with patch("src.ai_draw_client.request_bytes", return_value=BoundedResponse(200, "application/json", b'{"data":[{"url":"https://127.0.0.1/image.png"}]}')) as request_call:
                with self.assertRaisesRegex(ValueError, "public address"):
                    ai_draw_client.redraw_character_reference("image", self.character, mock=False)
        request_call.assert_called_once()

    def test_untrusted_public_result_host_is_rejected_before_download(self) -> None:
        with patch.dict(
            "os.environ",
            {"AI_DRAW_BASE_URL": "https://93.184.216.34/v1", "AI_DRAW_API_KEY": "test-image-key"},
            clear=False,
        ):
            with patch("src.ai_draw_client.request_bytes", return_value=BoundedResponse(200, "application/json", b'{"data":[{"url":"https://93.184.216.35/image.png"}]}')) as request_call:
                with self.assertRaisesRegex(ValueError, "trusted result-host allowlist"):
                    ai_draw_client.redraw_character_reference("image", self.character, mock=False)
        request_call.assert_called_once()

    def test_signed_result_url_http_error_does_not_leak_url_or_token(self) -> None:
        signed_url = "https://93.184.216.34/image.png?signature=secret-query-token"
        response = Mock(status=403)
        connection = Mock()
        connection.sock.getpeername.return_value = ("93.184.216.34", 443)
        connection.getresponse.return_value = response
        with patch.dict(
            "os.environ",
            {"AI_DRAW_BASE_URL": "https://93.184.216.34/v1", "AI_DRAW_API_KEY": "test-image-key"},
            clear=False,
        ):
            with patch("src.ai_draw_client.request_bytes", return_value=BoundedResponse(200, "application/json", json.dumps({"data": [{"url": signed_url}]}).encode())), \
                    patch("src.ai_draw_client.http.client.HTTPSConnection", return_value=connection):
                with self.assertRaises(ValueError) as caught:
                    ai_draw_client.redraw_character_reference("image", self.character, mock=False)
        message = str(caught.exception)
        self.assertIn("HTTP 403", message)
        self.assertNotIn("secret-query-token", message)
        self.assertNotIn(signed_url, message)

    def test_signed_result_download_rejects_private_actual_peer_before_path(self) -> None:
        connection = Mock()
        connection.sock.getpeername.return_value = ("127.0.0.1", 443)
        with patch("src.ai_draw_client.http.client.HTTPSConnection", return_value=connection):
            with self.assertRaisesRegex(ValueError, "public address"):
                ai_draw_client._download_generated_image(
                    "https://93.184.216.34/image.png?signature=secret",
                    api_hostname="93.184.216.34",
                )
        connection.connect.assert_called_once()
        connection.request.assert_not_called()

    def test_signed_result_download_requires_matching_image_mime(self) -> None:
        response = Mock(status=200)
        response.getheader.side_effect = lambda key, default=None: {
            "content-type": "", "content-length": str(len(PNG_BYTES)),
        }.get(key, default)
        response.read.return_value = PNG_BYTES
        connection = Mock()
        connection.sock.getpeername.return_value = ("93.184.216.34", 443)
        connection.getresponse.return_value = response
        with patch("src.ai_draw_client.http.client.HTTPSConnection", return_value=connection):
            with self.assertRaisesRegex(ValueError, "content-type"):
                ai_draw_client._download_generated_image(
                    "https://93.184.216.34/image.png",
                    api_hostname="93.184.216.34",
                )

    def test_web_redraw_is_pinned_to_mock_mode(self) -> None:
        sheet = character_designer.run("image", mock=True)
        path = character_paths("image").sheet_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(sheet, ensure_ascii=False), encoding="utf-8")
        fake = {
            "path": "data/character_refs/c001/portrait_neutral.png",
            "generated_by": "gpt-image-2",
            "prompt": "test",
            "seed": None,
        }
        with patch("src.ai_draw_client.redraw_character_reference", return_value=fake) as redraw:
            status, _ct, body = routes.dispatch(
                "POST",
                "/api/workspace/image/drama/characters/c001/redraw",
                b'{}',
                {"content-type": "application/json"},
            )
        self.assertEqual(status, 200, body.decode())
        self.assertIs(redraw.call_args.kwargs["mock"], True)

    def test_web_local_preview_stays_available_with_real_configuration(self) -> None:
        sheet = character_designer.run("image", mock=True)
        path = character_paths("image").sheet_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(sheet, ensure_ascii=False), encoding="utf-8")
        fake = {
            "path": "data/character_refs/c001/portrait_neutral.png",
            "generated_by": "placeholder_png",
            "prompt": "<mock>",
        }
        with patch.dict(os.environ, {"AI_DRAW_MODEL": "gpt-image-2"}, clear=False), \
                patch("src.ai_draw_client.redraw_character_reference", return_value=fake) as redraw:
            status, _ct, body = routes.dispatch(
                "POST",
                "/api/workspace/image/drama/characters/c001/redraw",
                b"{}",
                {"content-type": "application/json"},
            )
        self.assertEqual(status, 200, body.decode())
        self.assertIs(redraw.call_args.kwargs["mock"], True)
        source = Path("src/web/static.py").read_text(encoding="utf-8")
        self.assertIn("重画本地预览", source)
        self.assertIn("查看 SD Prompt", source)
        review_pos = source.index('const reviewBtn = root.querySelector("[data-review-assemble]")')
        review_save = source.index('const saved = await putJson(wsUrl("/drama/characters")', review_pos)
        review_post = source.index('wsUrl("/drama/review")', review_save)
        self.assertLess(review_save, review_post)
        self.assertIn("real_image_would_be_overwritten", source)
        self.assertIn("返回创作台重新评审并组装", source)

    def test_web_redraw_rejects_text_plain_csrf_shape_before_drawing(self) -> None:
        with patch("src.ai_draw_client.redraw_character_reference") as redraw:
            status, _ct, body = routes.dispatch(
                "POST",
                "/api/workspace/image/drama/characters/c001/redraw",
                b'{"confirm_real_image":true}',
                {"content-type": "text/plain"},
            )
        self.assertEqual(status, 415, body.decode())
        redraw.assert_not_called()


class DramaVideoClientTests(unittest.TestCase):
    def test_payload_matches_documented_reference_image_shape(self) -> None:
        payload = drama_video_client.build_video_payload(
            prompt="原创角色转身看向镜头",
            reference_asset_id="asset-20260705003737-njxmg",
            duration=5,
            resolution="480p",
            ratio="1:1",
        )
        self.assertEqual(payload["model"], drama_video_client.DEFAULT_VIDEO_MODEL)
        self.assertEqual(payload["content"][1]["image_url"]["url"], "asset://asset-20260705003737-njxmg")
        self.assertEqual(payload["content"][1]["role"], "reference_image")

    def test_payload_accepts_multiple_unique_reference_assets(self) -> None:
        payload = drama_video_client.build_video_payload(
            prompt="原创双人镜头",
            reference_asset_ids=["asset-one", "asset-two", "asset-one"],
        )
        refs = [row["image_url"]["url"] for row in payload["content"][1:]]
        self.assertEqual(refs, ["asset://asset-one", "asset://asset-two"])

    def test_real_video_gate_rejects_before_network(self) -> None:
        with patch("src.drama_video_client._validate_public_endpoint", side_effect=AssertionError("DNS attempted")):
            client = drama_video_client.DramaVideoClient(
                base_url="https://video.example.test", api_key="test-video-key"
            )
            with self.assertRaises(drama_video_client.VideoGenerationNotAuthorized):
                client.create_video_task(prompt="不要真的生成", allow_real_video=False)

    def test_task_query_uses_bearer_without_returning_key(self) -> None:
        with patch("src.drama_video_client.request_bytes", return_value=BoundedResponse(200, "application/json", b'{"task":{"id":"mvt-test","status":"processing"}}')) as request_call:
            client = drama_video_client.DramaVideoClient(
                base_url="https://93.184.216.34", api_key="test-video-key"
            )
            result = client.get_task("mvt-test")
        self.assertEqual(request_call.call_args.args[0], "https://93.184.216.34/v1/video/tasks/mvt-test")
        self.assertEqual(request_call.call_args.kwargs["headers"]["Authorization"], "Bearer test-video-key")
        self.assertNotIn("test-video-key", json.dumps(result))

    def test_video_base_url_rejects_query_before_request(self) -> None:
        with self.assertRaisesRegex(ValueError, "without credentials, query, or fragment"):
            drama_video_client.DramaVideoClient(
                base_url="https://93.184.216.34?tenant=x", api_key="test-video-key"
            )

    def test_explicit_video_authorization_posts_documented_endpoint(self) -> None:
        with patch("src.drama_video_client.request_bytes", return_value=BoundedResponse(200, "application/json", b'{"task":{"id":"mvt-test","status":"pending"}}')) as request_call:
            client = drama_video_client.DramaVideoClient(
                base_url="https://93.184.216.34", api_key="test-video-key"
            )
            result = client.create_video_task(prompt="原创镜头", allow_real_video=True)
        self.assertEqual(request_call.call_args.args[0], "https://93.184.216.34/v1/video/generate")
        self.assertEqual(json.loads(request_call.call_args.kwargs["body"])["model"], drama_video_client.DEFAULT_VIDEO_MODEL)
        self.assertEqual(result["task"]["status"], "pending")

    def test_video_client_rejects_duplicate_json_fields_without_echoing_them(self) -> None:
        duplicate_bodies = (
            b'{"success":false,"success":true}',
            b'{"data":{"Id":"safe","Id":"must-not-appear"}}',
            b'{"data":{"base_resp":{"status_code":1,"status_code":0}}}',
        )
        for body in duplicate_bodies:
            with self.subTest(body=body):
                with patch(
                    "src.drama_video_client.request_bytes",
                    return_value=BoundedResponse(200, "application/json", body),
                ):
                    client = drama_video_client.DramaVideoClient(
                        base_url="https://93.184.216.34",
                        api_key="test-video-key",
                    )
                    with self.assertRaisesRegex(ValueError, "invalid JSON") as caught:
                        client.list_tasks()
                self.assertNotIn("must-not-appear", str(caught.exception))
                self.assertNotIn("status_code", str(caught.exception))

    def test_resource_ids_and_asset_urls_are_fail_closed(self) -> None:
        client = drama_video_client.DramaVideoClient(
            base_url="https://93.184.216.34", api_key="test-video-key"
        )
        with self.assertRaisesRegex(ValueError, "resource id"):
            client.get_task("../escape")
        with self.assertRaisesRegex(ValueError, "public address"):
            client.upload_asset(url="https://127.0.0.1/private.png", name="ref", asset_type="Image")


class DramaMediaConfigAndSmokeTests(unittest.TestCase):
    def test_web_redraw_saves_current_form_before_confirmed_generation(self) -> None:
        source = Path("src/web/static.py").read_text(encoding="utf-8")
        save_pos = source.index('const saved = await putJson(wsUrl("/drama/characters")')
        redraw_pos = source.index('wsUrl("/drama/characters/"', save_pos)
        self.assertLess(save_pos, redraw_pos)
        self.assertIn(".character-ref-img { object-fit: contain; }", source)

    def test_preflight_rejects_partial_image_pair_and_bad_url_shape(self) -> None:
        warn: list[str] = []
        info: list[str] = []
        with patch.dict(
            "os.environ",
            {
                "AI_DRAW_MODEL": "gpt-image-2",
                "AI_DRAW_BASE_URL": "ftp://example.com/v1",
                "OPENAI_API_KEY": "must-not-cross",
            },
            clear=True,
        ):
            preflight._check_drama_media_config(warn, info)
        self.assertTrue(any("configured together" in item for item in warn))
        self.assertTrue(any("valid https" in item for item in warn))
        self.assertFalse(any("OpenAI-compatible model configured" in item for item in info))

    def test_preflight_accepts_complete_media_config_without_echoing_keys(self) -> None:
        warn: list[str] = []
        info: list[str] = []
        with patch.dict(
            "os.environ",
            {
                "AI_DRAW_MODEL": "gpt-image-2",
                "AI_DRAW_BASE_URL": "https://93.184.216.34/v1",
                "AI_DRAW_API_KEY": "image-secret",
                "SD_API_BASE_URL": "https://93.184.216.34",
                "SD_API_KEY": "video-secret",
            },
            clear=True,
        ):
            preflight._check_drama_media_config(warn, info)
        rendered = json.dumps({"warn": warn, "info": info})
        self.assertEqual(warn, [])
        self.assertIn("OpenAI-compatible model configured", rendered)
        self.assertIn("explicit per-call authorization gate", rendered)
        self.assertNotIn("image-secret", rendered)
        self.assertNotIn("video-secret", rendered)

    def test_python_legacy_image_smoke_is_always_disabled(self) -> None:
        with patch.dict("os.environ", {"CONFIRM_REAL_IMAGE_SMOKE": "可以跑生图"}, clear=True):
            with self.assertRaisesRegex(SystemExit, "drama_multimodal_smoke"):
                drama_image_smoke.main()


if __name__ == "__main__":
    unittest.main()
