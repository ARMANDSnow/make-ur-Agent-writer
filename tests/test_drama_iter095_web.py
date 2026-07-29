"""Iteration 095 Web/API contracts for multi-episode and season delivery."""

from __future__ import annotations

import json
import unittest

from src import character_designer, drama_reviewer, drama_store, paths, storyboard_builder
from src.cli_workspace import init_workspace
from src.drama_schemas import character_paths, episode_paths
from src.utils import sha256_data
from src.web import jobs, routes
from tests._drama_base import DramaTestBase


class DramaIter095WebTests(DramaTestBase):
    def setUp(self) -> None:
        super().setUp()
        jobs.reset_for_tests()

    def tearDown(self) -> None:
        jobs.reset_for_tests()
        super().tearDown()

    def _assembled_episode_one(self, *, episode_count: int = 3) -> None:
        self._make_drama_workspace("drama", "霸总", episode_count=episode_count)
        self._write_setup("drama", hook=True)
        ep = episode_paths("drama", episode_no=1)
        board = storyboard_builder.run("drama", mock=True, episode_no=1)
        ep.storyboard_path.write_text(
            json.dumps(board, ensure_ascii=False), encoding="utf-8"
        )
        sheet = character_designer.run("drama", mock=True, episode_no=1)
        cp = character_paths("drama")
        cp.sheet_path.parent.mkdir(parents=True, exist_ok=True)
        cp.sheet_path.write_text(
            json.dumps(sheet, ensure_ascii=False), encoding="utf-8"
        )
        review = drama_reviewer.run("drama", mock=True, episode_no=1)
        ep.review_path.write_text(
            json.dumps(review, ensure_ascii=False), encoding="utf-8"
        )
        drama_store.assemble_episode("drama", episode_no=1)

    def _assemble_episode_two(self) -> None:
        self.assertEqual(
            routes.dispatch(
                "POST",
                "/api/workspace/drama/drama/next-episode",
                b'{"after_episode_no": 1}',
            )[0],
            200,
        )
        self.assertEqual(
            self._dispatch_drama_job("drama", "hooks", {"episode_no": 2})["status"],
            "succeeded",
        )
        status, _ct, body = routes.dispatch(
            "GET", "/api/workspace/drama/drama/hook-candidates?episode_no=2"
        )
        self.assertEqual(status, 200, body.decode())
        hook = json.loads(body)["hooks"][0]
        status, _ct, body = routes.dispatch(
            "PUT",
            "/api/workspace/drama/drama/setup",
            json.dumps({"episode_no": 2, "hook": hook}, ensure_ascii=False).encode(),
        )
        self.assertEqual(status, 200, body.decode())
        self.assertEqual(
            self._dispatch_drama_job("drama", "storyboard", {"episode_no": 2})[
                "status"
            ],
            "succeeded",
        )
        self.assertEqual(
            self._dispatch_drama_job("drama", "review", {"episode_no": 2})["status"],
            "succeeded",
        )

    def test_shared_status_supports_ep3_and_idempotent_setup_resume(self) -> None:
        self._assembled_episode_one(episode_count=3)
        status, _ct, body = routes.dispatch(
            "GET", "/api/workspace/drama/drama/episodes"
        )
        self.assertEqual(status, 200, body.decode())
        state = json.loads(body)
        self.assertEqual(state["planned_episode_count"], 3)
        self.assertEqual(state["next_episode_no"], 2)
        self.assertFalse(state["next_episode_initialized"])
        self.assertTrue(state["can_start_next"])
        self.assertEqual(state["season_export"]["eligible_episode_nos"], [1])

        first = routes.dispatch(
            "POST",
            "/api/workspace/drama/drama/next-episode",
            b'{"after_episode_no": 1}',
        )
        second = routes.dispatch(
            "POST",
            "/api/workspace/drama/drama/next-episode",
            b'{"after_episode_no": 1}',
        )
        self.assertEqual(first[0], 200, first[2].decode())
        self.assertEqual(second[0], 200, second[2].decode())
        self.assertTrue(json.loads(first[2])["created"])
        self.assertFalse(json.loads(second[2])["created"])

        self._assemble_episode_two()
        status, _ct, body = routes.dispatch(
            "POST",
            "/api/workspace/drama/drama/next-episode",
            b'{"after_episode_no": 2}',
        )
        self.assertEqual(status, 200, body.decode())
        payload = json.loads(body)
        self.assertEqual(payload["episode_no"], 3)
        self.assertTrue(payload["created"])
        setup = payload["setup"]
        self.assertEqual(setup["title"], "")
        self.assertEqual(setup["episode_mainline"], "")
        self.assertFalse(setup["introduces_new_characters"])

    def test_status_and_post_reject_orphan_and_meta_sha_mismatch(self) -> None:
        self._assembled_episode_one(episode_count=3)
        ep3 = episode_paths("drama", episode_no=3)
        ep3.storyboard_path.write_text("{}", encoding="utf-8")
        status, _ct, body = routes.dispatch(
            "GET", "/api/workspace/drama/drama/episodes"
        )
        self.assertEqual(status, 200, body.decode())
        self.assertEqual(
            json.loads(body)["next_episode_blocked_reason"],
            "orphan_episode_artifact",
        )
        status, _ct, body = routes.dispatch(
            "POST",
            "/api/workspace/drama/drama/next-episode",
            b'{"after_episode_no": 1}',
        )
        self.assertEqual(status, 409, body.decode())
        self.assertEqual(json.loads(body)["code"], "orphan_episode_artifact")

        ep3.storyboard_path.unlink()
        ep1 = episode_paths("drama", episode_no=1)
        episode = json.loads(ep1.episode_path.read_text(encoding="utf-8"))
        episode["title"] = "tampered"
        ep1.episode_path.write_text(
            json.dumps(episode, ensure_ascii=False), encoding="utf-8"
        )
        status, _ct, body = routes.dispatch(
            "GET", "/api/workspace/drama/drama/episodes"
        )
        self.assertEqual(status, 200, body.decode())
        self.assertEqual(
            json.loads(body)["next_episode_blocked_reason"],
            "previous_episode_sha_mismatch",
        )
        self.assertEqual(json.loads(body)["next_episode_repair_no"], 1)

    def test_invalid_initialized_setup_is_not_resumed(self) -> None:
        self._assembled_episode_one(episode_count=3)
        self.assertEqual(
            routes.dispatch(
                "POST",
                "/api/workspace/drama/drama/next-episode",
                b'{"after_episode_no": 1}',
            )[0],
            200,
        )
        setup_path = episode_paths("drama", episode_no=2).setup_path
        setup = json.loads(setup_path.read_text(encoding="utf-8"))
        setup["track"] = []
        setup["target_duration_seconds"] = "not-an-int"
        setup_path.write_text(json.dumps(setup, ensure_ascii=False), encoding="utf-8")

        status, _ct, body = routes.dispatch(
            "GET", "/api/workspace/drama/drama/episodes"
        )
        self.assertEqual(status, 200, body.decode())
        state = json.loads(body)
        self.assertFalse(state["next_episode_initialized"])
        self.assertFalse(state["can_start_next"])
        self.assertEqual(state["next_episode_blocked_reason"], "next_episode_setup_invalid")
        self.assertEqual(state["next_episode_repair_no"], 2)
        status, _ct, body = routes.dispatch(
            "POST",
            "/api/workspace/drama/drama/next-episode",
            b'{"after_episode_no": 1}',
        )
        self.assertEqual(status, 409, body.decode())
        self.assertEqual(json.loads(body)["code"], "next_episode_setup_invalid")

    def test_episode_100_returns_shared_planned_limit_blocker(self) -> None:
        self._make_drama_workspace("drama", "霸总", episode_count=100)
        self._write_setup("drama", hook=True)
        base_setup = json.loads(episode_paths("drama").setup_path.read_text(encoding="utf-8"))
        base_board = storyboard_builder.run("drama", mock=True)
        episode_paths("drama").storyboard_path.write_text(
            json.dumps(base_board, ensure_ascii=False), encoding="utf-8"
        )
        sheet = character_designer.run("drama", mock=True)
        for row in sheet["characters"]:
            row["appearances"] = list(range(1, 101))
        character_paths("drama").sheet_path.parent.mkdir(parents=True, exist_ok=True)
        character_paths("drama").sheet_path.write_text(
            json.dumps(sheet, ensure_ascii=False), encoding="utf-8"
        )
        for episode_no in range(1, 101):
            ep = episode_paths("drama", episode_no=episode_no)
            setup = {**base_setup, "episode_no": episode_no}
            if episode_no > 1:
                previous_meta = json.loads(
                    episode_paths(
                        "drama", episode_no=episode_no - 1
                    ).meta_path.read_text(encoding="utf-8")
                )
                setup.update(
                    {
                        "parent_episode_no": episode_no - 1,
                        "parent_episode_revision": sha256_data(
                            {
                                "episode_no": episode_no - 1,
                                "input_fingerprint": previous_meta[
                                    "input_fingerprint"
                                ],
                                "episode_sha256": previous_meta[
                                    "episode_sha256"
                                ],
                            }
                        ),
                    }
                )
            board = {**base_board, "episode_no": episode_no, "title": f"第 {episode_no} 集"}
            ep.setup_path.write_text(json.dumps(setup, ensure_ascii=False), encoding="utf-8")
            ep.storyboard_path.write_text(json.dumps(board, ensure_ascii=False), encoding="utf-8")
            review = drama_reviewer.run("drama", mock=True, episode_no=episode_no)
            ep.review_path.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")
            drama_store.assemble_episode("drama", episode_no=episode_no)

        state_response = routes.dispatch("GET", "/api/workspace/drama/drama/episodes")
        self.assertEqual(state_response[0], 200, state_response[2].decode())
        state = json.loads(state_response[2])
        self.assertIsNone(state["next_episode_no"])
        self.assertEqual(state["next_episode_blocked_reason"], "planned_episode_count_reached")
        status, _ct, body = routes.dispatch(
            "POST",
            "/api/workspace/drama/drama/next-episode",
            b'{"after_episode_no": 100}',
        )
        self.assertEqual(status, 400, body.decode())
        self.assertEqual(json.loads(body)["code"], "planned_episode_count_reached")

    def test_status_rejects_strict_wizard_count_and_orphan_derived_export(self) -> None:
        self._assembled_episode_one(episode_count=3)
        wizard = paths.WORKSPACE_DIR / "drama" / "data" / "wizard_input.json"
        payload = json.loads(wizard.read_text(encoding="utf-8"))
        payload["episode_count"] = "3"
        wizard.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(
            routes.dispatch("GET", "/api/workspace/drama/drama/episodes")[0],
            400,
        )

        payload["episode_count"] = 3
        wizard.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        ep2 = episode_paths("drama", episode_no=2)
        ep2.episodes_dir.mkdir(parents=True, exist_ok=True)
        (ep2.episodes_dir / "episode_02.comfy.json").write_text("{}", encoding="utf-8")
        status, _ct, body = routes.dispatch(
            "GET", "/api/workspace/drama/drama/episodes"
        )
        self.assertEqual(status, 200, body.decode())
        self.assertEqual(
            json.loads(body)["next_episode_blocked_reason"],
            "orphan_episode_artifact",
        )

    def test_season_export_download_and_boundaries(self) -> None:
        self._assembled_episode_one(episode_count=1)
        response = routes.dispatch(
            "GET", "/api/workspace/drama/drama/season/1/export?mode=master"
        )
        self.assertEqual(len(response), 4)
        status, content_type, body, headers = response
        self.assertEqual(status, 200)
        self.assertEqual(content_type, "application/zip")
        self.assertTrue(body.startswith(b"PK"))
        self.assertEqual(
            headers["Content-Disposition"],
            'attachment; filename="season_01_master.zip"',
        )
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")

        for path in (
            "/api/workspace/drama/drama/season/2/export?mode=master",
            "/api/workspace/drama/drama/season/1/export?mode=../../",
            "/api/workspace/drama/drama/season/1/export",
        ):
            self.assertEqual(routes.dispatch("GET", path)[0], 400, path)

        self._make_drama_workspace("partial", "霸总", episode_count=2)
        status, _ct, body = routes.dispatch(
            "GET", "/api/workspace/partial/drama/season/1/export?mode=master"
        )
        self.assertEqual(status, 409, body.decode())
        self.assertEqual(json.loads(body)["code"], "master_not_ready")

        init_workspace("novel", type="novel")
        self.assertEqual(
            routes.dispatch(
                "GET", "/api/workspace/novel/drama/season/1/export?mode=master"
            )[0],
            400,
        )

    def test_episodes_page_static_contract(self) -> None:
        self._assembled_episode_one(episode_count=3)
        status, _ct, body = routes.dispatch("GET", "/static/app.js")
        self.assertEqual(status, 200)
        js = body.decode("utf-8")
        self.assertIn("function dramaNextEpisodeReason", js)
        self.assertIn("继续第 ", js)
        self.assertIn("导出整季母包", js)
        self.assertIn("导出阶段快照", js)
        self.assertIn("集可交付", js)
        self.assertIn("当前也没有可导出的阶段快照", js)
        self.assertIn("修复第 ", js)


if __name__ == "__main__":
    unittest.main()
