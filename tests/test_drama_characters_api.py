"""iter 081: drama character Web/API tests."""

from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from src import ai_draw_client, character_designer, storyboard_builder
from src.cli_workspace import init_workspace
from src.drama_schemas import character_paths, episode_paths
from src.web import jobs, routes
from tests._drama_base import DramaTestBase


class DramaCharactersApiTests(DramaTestBase):
    def setUp(self) -> None:
        super().setUp()
        jobs.reset_for_tests()
        self._saved_endpoint = os.environ.pop("AI_DRAW_ENDPOINT", None)

    def tearDown(self) -> None:
        if self._saved_endpoint is not None:
            os.environ["AI_DRAW_ENDPOINT"] = self._saved_endpoint
        else:
            os.environ.pop("AI_DRAW_ENDPOINT", None)
        jobs.reset_for_tests()
        super().tearDown()

    def _workspace(self, name: str = "drama", *, storyboard: bool = True) -> None:
        self._make_drama_workspace(name, "霸总")
        self._write_setup(name, hook=True)
        if storyboard:
            board = storyboard_builder.run(name, mock=True)
            p = episode_paths(name).storyboard_path
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(board, ensure_ascii=False), encoding="utf-8")

    def _post_characters(self, name: str = "drama") -> dict:
        job = self._dispatch_drama_job(name, "characters")
        self.assertEqual(job["status"], "succeeded", job)
        status, _ct, body = routes.dispatch("GET", f"/api/workspace/{name}/drama/characters")
        self.assertEqual(status, 200, body.decode())
        return json.loads(body)

    def test_get_missing_character_sheet_returns_empty_state(self) -> None:
        self._workspace()
        status, _ct, body = routes.dispatch("GET", "/api/workspace/drama/drama/characters")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertFalse(data["exists"])
        self.assertIsNone(data["sheet"])

    def test_post_generates_and_persists_character_sheet(self) -> None:
        self._workspace()
        data = self._post_characters()
        self.assertTrue(data["exists"])
        self.assertEqual(data["sheet"]["characters"][0]["id"], "c001")
        self.assertTrue(character_paths("drama").sheet_path.is_file())

        status, _ct, body = routes.dispatch("GET", "/api/workspace/drama/drama/progress")
        stations = json.loads(body)["stations"]
        self.assertEqual(stations[3]["status"], "done")

    def test_post_uses_mock_even_when_real_model_env_is_set(self) -> None:
        self._workspace()
        expected = character_designer.run("drama", mock=True)
        with patch.dict("os.environ", {"OPENAI_MODEL": "deepseek/deepseek-chat"}, clear=False):
            with patch("src.character_designer.run", return_value=expected) as spy:
                data = self._post_characters()
        self.assertTrue(data["exists"])
        self.assertIsNone(spy.call_args.kwargs["mock"])

    def test_put_saves_manual_override(self) -> None:
        self._workspace()
        sheet = self._post_characters()["sheet"]
        sheet["characters"][0]["manual_override"] = True
        sheet["characters"][0]["name"] = "用户锁定名"
        status, _ct, body = routes.dispatch(
            "PUT",
            "/api/workspace/drama/drama/characters",
            json.dumps({"sheet": sheet}, ensure_ascii=False).encode("utf-8"),
        )
        self.assertEqual(status, 200, body.decode())
        saved = json.loads(body)["sheet"]
        self.assertTrue(saved["characters"][0]["manual_override"])
        self.assertEqual(saved["characters"][0]["name"], "用户锁定名")

    def test_regenerate_preserves_manual_override(self) -> None:
        self._workspace()
        sheet = self._post_characters()["sheet"]
        sheet["characters"][0]["manual_override"] = True
        sheet["characters"][0]["name"] = "手编字段"
        routes.dispatch(
            "PUT",
            "/api/workspace/drama/drama/characters",
            json.dumps({"sheet": sheet}, ensure_ascii=False).encode("utf-8"),
        )
        data = self._post_characters()["sheet"]
        self.assertEqual(data["characters"][0]["name"], "手编字段")
        self.assertGreaterEqual(len(data["characters"][0]["agent_suggestions"]), 1)

    def test_requires_storyboard_and_rejects_novel_workspace(self) -> None:
        self._workspace(storyboard=False)
        job = self._dispatch_drama_job("drama", "characters")
        self.assertEqual(job["status"], "blocked")

        init_workspace("novel", type="novel")
        status, _ct, body = routes.dispatch("GET", "/api/workspace/novel/drama/characters")
        self.assertEqual(status, 400)
        self.assertIn("drama-only", json.loads(body)["error"])

    def test_save_busy_returns_409_and_preserves_file(self) -> None:
        self._workspace()
        sheet = self._post_characters()["sheet"]
        before = character_paths("drama").sheet_path.read_text(encoding="utf-8")
        sheet["characters"][0]["name"] = "锁外修改"
        with jobs.workspace_reserved("drama"):
            status, _ct, body = routes.dispatch(
                "PUT",
                "/api/workspace/drama/drama/characters",
                json.dumps({"sheet": sheet}, ensure_ascii=False).encode("utf-8"),
            )
        self.assertEqual(status, 409, body.decode())
        self.assertEqual(character_paths("drama").sheet_path.read_text(encoding="utf-8"), before)

    def test_redraw_writes_placeholder_svg_without_network(self) -> None:
        self._workspace()
        self._post_characters()
        with patch("src.ai_draw_client.build_opener", side_effect=AssertionError("network attempted")):
            status, _ct, body = routes.dispatch(
                "POST",
                "/api/workspace/drama/drama/characters/c001/redraw",
                b'{}',
                {"content-type": "application/json"},
            )
        self.assertEqual(status, 200, body.decode())
        data = json.loads(body)
        image = data["image"]
        self.assertEqual(image["generated_by"], "placeholder_svg")
        self.assertTrue((character_paths("drama").root / image["path"]).is_file())

        filename = image["path"].split("/")[-1]
        status, ct, body = routes.dispatch("GET", f"/api/workspace/drama/character-ref/c001/{filename}")
        self.assertEqual(status, 200)
        self.assertIn("image/svg+xml", ct)
        self.assertIn(b"<svg", body)

    def test_real_draw_rejects_private_endpoint_before_network(self) -> None:
        self._workspace()
        sheet = self._post_characters()["sheet"]
        with patch.dict("os.environ", {"AI_DRAW_ENDPOINT": "http://127.0.0.1/draw"}, clear=False):
            with patch("src.ai_draw_client.build_opener", side_effect=AssertionError("network attempted")):
                with self.assertRaisesRegex(ValueError, "public address"):
                    ai_draw_client.redraw_character_reference("drama", sheet["characters"][0], mock=False)

    def test_real_draw_rejects_unsupported_content_type(self) -> None:
        self._workspace()
        sheet = self._post_characters()["sheet"]

        class FakeResponse:
            headers = {"content-type": "text/html; charset=utf-8"}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit):
                return b"<html>not an image</html>"

        class FakeOpener:
            def open(self, _request, timeout):  # noqa: ANN001
                self.timeout = timeout
                return FakeResponse()

        with patch.dict("os.environ", {"AI_DRAW_ENDPOINT": "https://93.184.216.34/draw"}, clear=False):
            with patch("src.ai_draw_client.build_opener", return_value=FakeOpener()):
                with self.assertRaisesRegex(ValueError, "content-type"):
                    ai_draw_client.redraw_character_reference("drama", sheet["characters"][0], mock=False)
        self.assertFalse((character_paths("drama").refs_dir / "c001").exists())

    def test_character_ref_rejects_invalid_paths(self) -> None:
        self._workspace()
        self._post_characters()
        status, _ct, body = routes.dispatch("GET", "/api/workspace/drama/character-ref/bad/portrait_neutral.svg")
        self.assertEqual(status, 400)
        self.assertIn("invalid", json.loads(body)["error"])

        status, _ct, body = routes.api_character_ref("drama", "c001", "../escape.svg")
        self.assertEqual(status, 400)
        self.assertIn("invalid", json.loads(body)["error"])

    def test_character_ref_rejects_unsupported_and_oversized_files(self) -> None:
        self._workspace()
        self._post_characters()
        ref_dir = character_paths("drama").refs_dir / "c001"
        ref_dir.mkdir(parents=True, exist_ok=True)
        (ref_dir / "portrait_neutral.txt").write_text("not an image", encoding="utf-8")
        status, _ct, body = routes.dispatch("GET", "/api/workspace/drama/character-ref/c001/portrait_neutral.txt")
        self.assertEqual(status, 400)
        self.assertIn("unsupported", json.loads(body)["error"])

        (ref_dir / "huge.png").write_bytes(b"0" * (ai_draw_client.MAX_RESPONSE_BYTES + 1))
        status, _ct, body = routes.dispatch("GET", "/api/workspace/drama/character-ref/c001/huge.png")
        self.assertEqual(status, 413)
        self.assertIn("size", json.loads(body)["error"])

    def test_characters_page_route(self) -> None:
        self._workspace()
        status, ct, body = routes.dispatch("GET", "/w/drama/characters")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ct)
        self.assertIn("角色库", body.decode("utf-8"))


if __name__ == "__main__":
    unittest.main()
