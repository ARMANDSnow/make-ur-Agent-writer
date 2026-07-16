"""iter 080: storyboard grid API tests."""

from __future__ import annotations

import copy
import json
import unittest
from unittest.mock import patch

from src import storyboard_builder
from src.cli_workspace import init_workspace
from src.drama_schemas import episode_paths
from src.web import jobs, routes
from src.web import static
from tests._drama_base import DramaTestBase


class DramaStoryboardGridTests(DramaTestBase):
    def setUp(self) -> None:
        super().setUp()
        jobs.reset_for_tests()

    def tearDown(self) -> None:
        jobs.reset_for_tests()
        super().tearDown()

    def _workspace(self, name: str = "drama", *, hook: bool = True) -> None:
        self._make_drama_workspace(name, "霸总")
        self._write_setup(name, hook=hook)

    def _post_storyboard(self, name: str = "drama") -> dict:
        job = self._dispatch_drama_job(name, "storyboard")
        self.assertEqual(job["status"], "succeeded", job)
        status, _ct, body = routes.dispatch("GET", f"/api/workspace/{name}/drama/storyboard")
        self.assertEqual(status, 200, body.decode())
        return json.loads(body)

    def test_get_missing_storyboard_returns_empty_state(self) -> None:
        self._workspace()
        status, _ct, body = routes.dispatch("GET", "/api/workspace/drama/drama/storyboard")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertFalse(data["exists"])
        self.assertIsNone(data["storyboard"])

    def test_web_grid_exposes_claimed_add_delete_and_forward_navigation(self) -> None:
        self.assertIn("data-storyboard-add", static.JS_DASHBOARD)
        self.assertIn("data-shot-delete", static.JS_DASHBOARD)
        self.assertIn("保存并进入站 ④", static.JS_DASHBOARD)
        self.assertIn("replaceActiveTabLocation", static.JS_DASHBOARD)
        self.assertIn('url.searchParams.set("step", tabName)', static.JS_DASHBOARD)

    def test_post_generates_and_persists_storyboard(self) -> None:
        self._workspace()
        data = self._post_storyboard()
        self.assertTrue(data["exists"])
        self.assertEqual(len(data["storyboard"]["shots"]), 6)
        self.assertTrue(episode_paths("drama").storyboard_path.is_file())

        status, _ct, body = routes.dispatch("GET", "/api/workspace/drama/drama/progress")
        self.assertEqual(json.loads(body)["stations"][2]["status"], "done")

    def test_post_uses_mock_even_when_real_model_env_is_set(self) -> None:
        self._workspace()
        expected = storyboard_builder.run("drama", mock=True)
        with patch.dict("os.environ", {"OPENAI_MODEL": "deepseek/deepseek-chat"}, clear=False):
            with patch("src.storyboard_builder.run", return_value=expected) as spy:
                data = self._post_storyboard()
        self.assertTrue(data["exists"])
        self.assertIsNone(spy.call_args.kwargs["mock"])

    def test_post_runtime_error_returns_generic_card(self) -> None:
        self._workspace()
        with patch("src.storyboard_builder.run", side_effect=RuntimeError("secret TOKEN_TEST_VALUE /Users/me/.env prompt body")):
            job = self._dispatch_drama_job("drama", "storyboard")
        self.assertEqual(job["status"], "failed")
        text = json.dumps(job, ensure_ascii=False)
        self.assertNotIn("TOKEN_TEST_VALUE", text)
        self.assertNotIn("/Users/me/.env", text)
        self.assertNotIn("prompt body", text)

    def test_put_saves_grid_and_renumbers_shots(self) -> None:
        self._workspace()
        board = self._post_storyboard()["storyboard"]
        board["shots"] = list(reversed(board["shots"]))
        board["shots"][0]["visual"] = "改过的第一镜"
        status, _ct, body = routes.dispatch(
            "PUT",
            "/api/workspace/drama/drama/storyboard",
            json.dumps({"storyboard": board}, ensure_ascii=False).encode("utf-8"),
        )
        self.assertEqual(status, 200, body.decode())
        saved = json.loads(body)["storyboard"]
        self.assertEqual([s["shot_no"] for s in saved["shots"]], [1, 2, 3, 4, 5, 6])
        self.assertEqual(saved["shots"][0]["visual"], "改过的第一镜")

        disk = json.loads(episode_paths("drama").storyboard_path.read_text(encoding="utf-8"))
        self.assertEqual(disk["shots"][0]["visual"], "改过的第一镜")

    def test_put_uses_station_two_hook_not_client_hook(self) -> None:
        self._workspace()
        board = self._post_storyboard()["storyboard"]
        board["hook"] = {
            "type": "客户端伪造",
            "content": "不应落盘",
            "huge": "x" * 1000,
        }
        status, _ct, body = routes.dispatch(
            "PUT",
            "/api/workspace/drama/drama/storyboard",
            json.dumps({"storyboard": board}, ensure_ascii=False).encode("utf-8"),
        )
        self.assertEqual(status, 200, body.decode())
        saved = json.loads(body)["storyboard"]
        self.assertEqual(saved["hook"], {"type": "反差钩", "content": "测试钩子"})

    def test_put_rejects_two_highlight_shots(self) -> None:
        self._workspace()
        board = self._post_storyboard()["storyboard"]
        board["shots"][0]["is_highlight"] = True
        board["shots"][1]["is_highlight"] = True
        status, _ct, body = routes.dispatch(
            "PUT",
            "/api/workspace/drama/drama/storyboard",
            json.dumps({"storyboard": board}, ensure_ascii=False).encode("utf-8"),
        )
        self.assertEqual(status, 400)
        self.assertIn("highlight", json.loads(body)["error"])

    def test_put_allows_zero_highlight_with_soft_warning(self) -> None:
        self._workspace()
        board = self._post_storyboard()["storyboard"]
        for shot in board["shots"]:
            shot["is_highlight"] = False
        status, _ct, body = routes.dispatch(
            "PUT",
            "/api/workspace/drama/drama/storyboard",
            json.dumps({"storyboard": board}, ensure_ascii=False).encode("utf-8"),
        )
        self.assertEqual(status, 200, body.decode())
        self.assertIn("highlight_missing", json.loads(body)["soft_warnings"])

    def test_rewrite_shot_only_replaces_target(self) -> None:
        self._workspace()
        before = self._post_storyboard()["storyboard"]
        status, _ct, body = routes.dispatch(
            "POST",
            "/api/workspace/drama/drama/storyboard/rewrite-shot",
            json.dumps({"shot_no": 3}).encode("utf-8"),
        )
        self.assertEqual(status, 200, body.decode())
        after = json.loads(body)["storyboard"]
        self.assertNotEqual(after["shots"][2]["visual"], before["shots"][2]["visual"])
        self.assertEqual(after["shots"][:2] + after["shots"][3:], before["shots"][:2] + before["shots"][3:])

    def test_rewrite_uses_mock_even_when_real_model_env_is_set(self) -> None:
        self._workspace()
        board = self._post_storyboard()["storyboard"]
        with patch.dict("os.environ", {"OPENAI_MODEL": "deepseek/deepseek-chat"}, clear=False):
            with patch("src.storyboard_builder.rewrite_shot", return_value=board) as spy:
                status, _ct, body = routes.dispatch(
                    "POST",
                    "/api/workspace/drama/drama/storyboard/rewrite-shot",
                    json.dumps({"shot_no": 3, "storyboard": board}, ensure_ascii=False).encode("utf-8"),
                )
        self.assertEqual(status, 200, body.decode())
        self.assertIs(spy.call_args.kwargs["mock"], True)

    def test_rewrite_shot_uses_current_grid_payload(self) -> None:
        self._workspace()
        before = self._post_storyboard()["storyboard"]
        current = copy.deepcopy(before)
        current["shots"] = list(reversed(current["shots"]))
        current["shots"][0]["visual"] = "未保存顺序第一镜"
        for idx, shot in enumerate(current["shots"], start=1):
            shot["shot_no"] = idx

        status, _ct, body = routes.dispatch(
            "POST",
            "/api/workspace/drama/drama/storyboard/rewrite-shot",
            json.dumps({"shot_no": 3, "storyboard": current}, ensure_ascii=False).encode("utf-8"),
        )
        self.assertEqual(status, 200, body.decode())
        after = json.loads(body)["storyboard"]
        self.assertEqual(after["shots"][0]["visual"], "未保存顺序第一镜")
        self.assertNotEqual(after["shots"][2]["visual"], current["shots"][2]["visual"])
        self.assertEqual(after["shots"][:2] + after["shots"][3:], current["shots"][:2] + current["shots"][3:])

    def test_get_requires_selected_hook(self) -> None:
        self._workspace(hook=False)
        status, _ct, body = routes.dispatch("GET", "/api/workspace/drama/drama/storyboard")
        self.assertEqual(status, 400)
        self.assertIn("station 2", json.loads(body)["error"])

    def test_generate_requires_selected_hook(self) -> None:
        self._workspace(hook=False)
        job = self._dispatch_drama_job("drama", "storyboard")
        self.assertEqual(job["status"], "blocked")

    def test_put_requires_selected_hook(self) -> None:
        self._workspace("source")
        board = self._post_storyboard("source")["storyboard"]
        self._workspace(hook=False)
        status, _ct, body = routes.dispatch(
            "PUT",
            "/api/workspace/drama/drama/storyboard",
            json.dumps({"storyboard": board}, ensure_ascii=False).encode("utf-8"),
        )
        self.assertEqual(status, 400, body.decode())
        self.assertIn("station 2", json.loads(body)["error"])
        self.assertFalse(episode_paths("drama").storyboard_path.exists())

    def test_storyboard_endpoint_rejects_novel_workspace(self) -> None:
        init_workspace("novel", type="novel")
        status, _ct, body = routes.dispatch("GET", "/api/workspace/novel/drama/storyboard")
        self.assertEqual(status, 400)
        self.assertIn("drama-only", json.loads(body)["error"])

    def test_storyboard_save_busy_returns_409_and_preserves_file(self) -> None:
        self._workspace()
        board = self._post_storyboard()["storyboard"]
        before = episode_paths("drama").storyboard_path.read_text(encoding="utf-8")
        board["title"] = "锁外修改"
        with jobs.workspace_reserved("drama"):
            status, _ct, body = routes.dispatch(
                "PUT",
                "/api/workspace/drama/drama/storyboard",
                json.dumps({"storyboard": board}, ensure_ascii=False).encode("utf-8"),
            )
        self.assertEqual(status, 409, body.decode())
        self.assertEqual(episode_paths("drama").storyboard_path.read_text(encoding="utf-8"), before)


if __name__ == "__main__":
    unittest.main()
