"""iter 082: drama episodes Web/API tests."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from src import character_designer, drama_reviewer, storyboard_builder
from src.cli_workspace import init_workspace
from src.drama_schemas import episode_paths, character_paths
from src.web import jobs, routes
from tests._drama_base import DramaTestBase


class DramaEpisodesApiTests(DramaTestBase):
    def setUp(self) -> None:
        super().setUp()
        jobs.reset_for_tests()

    def tearDown(self) -> None:
        jobs.reset_for_tests()
        super().tearDown()

    def _workspace(self, name: str = "drama", *, with_characters: bool = True) -> None:
        self._make_drama_workspace(name, "霸总")
        self._write_setup(name, hook=True)
        board = storyboard_builder.run(name, mock=True)
        ep = episode_paths(name)
        ep.storyboard_path.parent.mkdir(parents=True, exist_ok=True)
        ep.storyboard_path.write_text(json.dumps(board, ensure_ascii=False), encoding="utf-8")
        if with_characters:
            sheet = character_designer.run(name, mock=True)
            cp = character_paths(name)
            cp.sheet_path.parent.mkdir(parents=True, exist_ok=True)
            cp.sheet_path.write_text(json.dumps(sheet, ensure_ascii=False), encoding="utf-8")

    def test_review_and_assemble_api_round_trip(self) -> None:
        self._workspace()
        status, _ct, body = routes.dispatch("POST", "/api/workspace/drama/drama/review", b"{}")
        self.assertEqual(status, 200, body.decode())
        review = json.loads(body)["review"]
        self.assertEqual(review["verdict"], "Approve")
        self.assertTrue(episode_paths("drama").review_path.is_file())

        status, _ct, body = routes.dispatch("POST", "/api/workspace/drama/drama/assemble", b"{}")
        self.assertEqual(status, 200, body.decode())
        assembled = json.loads(body)
        self.assertEqual(assembled["episode"]["episode_no"], 1)

        status, _ct, body = routes.dispatch("GET", "/api/workspace/drama/drama/episodes")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["episodes"][0]["episode_no"], 1)

        status, _ct, body = routes.dispatch("GET", "/api/workspace/drama/drama/episode/1")
        self.assertEqual(status, 200)
        self.assertFalse(json.loads(body)["stale"])

    def test_review_requires_characters_and_rejects_novel_workspace(self) -> None:
        self._workspace(with_characters=False)
        status, _ct, body = routes.dispatch("POST", "/api/workspace/drama/drama/review", b"{}")
        self.assertEqual(status, 400)
        self.assertIn("station 4", json.loads(body)["error"])

        init_workspace("novel", type="novel")
        status, _ct, body = routes.dispatch("GET", "/api/workspace/novel/drama/episodes")
        self.assertEqual(status, 400)
        self.assertIn("drama-only", json.loads(body)["error"])

    def test_bad_episode_no_rejected(self) -> None:
        self._workspace()
        status, _ct, body = routes.dispatch("POST", "/api/workspace/drama/drama/review", b'{"episode_no": false}')
        self.assertEqual(status, 400)
        self.assertIn("episode_no", json.loads(body)["error"])

        status, _ct, body = routes.dispatch("POST", "/api/workspace/drama/drama/review", b'{"episode_no": 1.9}')
        self.assertEqual(status, 400)
        self.assertIn("episode_no", json.loads(body)["error"])

    def test_review_route_uses_mock_even_with_real_model_env(self) -> None:
        self._workspace()
        expected = drama_reviewer.run("drama", mock=True)
        with patch.dict("os.environ", {"OPENAI_MODEL": "deepseek/deepseek-chat"}, clear=False):
            with patch("src.drama_reviewer.run", return_value=expected) as spy:
                status, _ct, body = routes.dispatch("POST", "/api/workspace/drama/drama/review", b"{}")
        self.assertEqual(status, 200, body.decode())
        self.assertIs(spy.call_args.kwargs["mock"], True)

    def test_assemble_busy_returns_409(self) -> None:
        self._workspace()
        review = drama_reviewer.run("drama", mock=True)
        episode_paths("drama").review_path.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")
        with jobs.workspace_reserved("drama"):
            status, _ct, body = routes.dispatch("POST", "/api/workspace/drama/drama/assemble", b"{}")
        self.assertEqual(status, 409, body.decode())
        self.assertIn("workspace busy", json.loads(body)["error"])

    def test_apply_suggestion_updates_hook_and_marks_stale(self) -> None:
        self._workspace()
        routes.dispatch("POST", "/api/workspace/drama/drama/review", b"{}")
        routes.dispatch("POST", "/api/workspace/drama/drama/assemble", b"{}")
        suggestion = {
            "station": "hook",
            "field": "content",
            "new_value": "新的结尾钩子",
            "reason": "测试 stale",
        }
        status, _ct, body = routes.dispatch(
            "POST",
            "/api/workspace/drama/drama/apply-suggestion",
            json.dumps({"suggestion": suggestion}, ensure_ascii=False).encode("utf-8"),
        )
        self.assertEqual(status, 200, body.decode())
        status, _ct, body = routes.dispatch("GET", "/api/workspace/drama/drama/episode/1")
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)["stale"])

    def test_episodes_pages_render(self) -> None:
        self._workspace()
        status, ct, body = routes.dispatch("GET", "/w/drama/episodes")
        self.assertEqual(status, 200)
        self.assertIn("text/html", ct)
        self.assertIn('window.PAGE_KIND = "drama_episodes"', body.decode("utf-8"))
        self.assertIn('id="episodes-panel"', body.decode("utf-8"))

        status, ct, body = routes.dispatch("GET", "/w/drama/episode/1")
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        self.assertIn('window.PAGE_KIND = "drama_episode_detail"', html)
        self.assertIn('data-tab="script"', html)


if __name__ == "__main__":
    unittest.main()
