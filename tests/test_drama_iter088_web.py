"""Iteration 088 Web/API integration for exports, Insights, and episode 2."""

from __future__ import annotations

import json
import unittest

from src import character_designer, drama_reviewer, drama_store, storyboard_builder
from src.cli_workspace import init_workspace
from src.drama_schemas import (
    CharacterSheet,
    DramaEpisode,
    DramaEpisodeMeta,
    DramaReview,
    DramaStoryboard,
    character_paths,
    episode_paths,
)
from src.web import jobs, routes
from src.utils import write_json
from tests._drama_base import DramaTestBase


class DramaIter088WebTests(DramaTestBase):
    def setUp(self) -> None:
        super().setUp()
        jobs.reset_for_tests()

    def tearDown(self) -> None:
        jobs.reset_for_tests()
        super().tearDown()

    def _assembled_episode_one(self, name: str = "drama") -> None:
        self._make_drama_workspace(name, "霸总", episode_count=2)
        self._write_setup(name, hook=True)
        board = storyboard_builder.run(name, mock=True, episode_no=1)
        ep = episode_paths(name, episode_no=1)
        ep.storyboard_path.parent.mkdir(parents=True, exist_ok=True)
        ep.storyboard_path.write_text(json.dumps(board, ensure_ascii=False), encoding="utf-8")
        sheet = character_designer.run(name, mock=True, episode_no=1)
        cp = character_paths(name)
        cp.sheet_path.parent.mkdir(parents=True, exist_ok=True)
        cp.sheet_path.write_text(json.dumps(sheet, ensure_ascii=False), encoding="utf-8")
        review = drama_reviewer.run(name, mock=True, episode_no=1)
        ep.review_path.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")
        drama_store.assemble_episode(name, episode_no=1)

    def test_export_api_four_formats_and_strict_boundaries(self) -> None:
        self._assembled_episode_one()
        expected = {
            "json": ("episode_01.json", "application/json"),
            "md": ("episode_01.storyboard.md", "text/markdown"),
            "csv": ("episode_01.storyboard.csv", "text/csv"),
            "comfy": ("episode_01.comfy.json", "application/json"),
        }
        for export_format, (filename, mime) in expected.items():
            response = routes.dispatch(
                "GET",
                f"/api/workspace/drama/drama/episode/1/export?format={export_format}",
            )
            self.assertEqual(len(response), 4)
            status, content_type, body, headers = response
            self.assertEqual(status, 200)
            self.assertIn(mime, content_type)
            self.assertTrue(body)
            self.assertEqual(headers["Content-Disposition"], f'attachment; filename="{filename}"')
            self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertTrue(expected.keys() <= {"json", "md", "csv", "comfy"})

        for query in ("", "../../", "JSON", "json%2F.."):
            status, _ct, body = routes.dispatch(
                "GET",
                f"/api/workspace/drama/drama/episode/1/export?format={query}",
            )
            self.assertEqual(status, 400, body.decode("utf-8", errors="replace"))
        status, _ct, _body = routes.dispatch(
            "GET",
            "/api/workspace/drama/drama/episode/1.0/export?format=json",
        )
        self.assertEqual(status, 400)
        status, _ct, _body = routes.dispatch(
            "GET",
            "/api/workspace/drama/drama/episode/101/export?format=json",
        )
        self.assertEqual(status, 400)

    def test_next_episode_mock_full_chain_preserves_episode_one(self) -> None:
        self._assembled_episode_one()
        ep1 = episode_paths("drama", episode_no=1)
        ep1_setup_before = ep1.setup_path.read_bytes()
        character_before = character_paths("drama").sheet_path.read_bytes()

        status, _ct, body = routes.dispatch(
            "POST",
            "/api/workspace/drama/drama/next-episode",
            b'{"after_episode_no": 1}',
        )
        self.assertEqual(status, 200, body.decode())
        next_payload = json.loads(body)
        self.assertEqual(next_payload["episode_no"], 2)
        ep2 = episode_paths("drama", episode_no=2)
        inherited = json.loads(ep2.setup_path.read_text(encoding="utf-8"))
        self.assertEqual(inherited["core_setup"], json.loads(ep1_setup_before)["core_setup"])
        self.assertNotIn("hook", inherited)
        self.assertEqual(ep1.setup_path.read_bytes(), ep1_setup_before)

        job = self._dispatch_drama_job("drama", "hooks", {"episode_no": 2})
        self.assertEqual(job["status"], "succeeded", job)
        status, _ct, body = routes.dispatch(
            "GET", "/api/workspace/drama/drama/hook-candidates?episode_no=2"
        )
        self.assertEqual(status, 200, body.decode())
        hooks = json.loads(body)["hooks"]
        self.assertEqual(len(hooks), 3)
        self.assertTrue(all(hook.get("content") != "测试钩子" for hook in hooks))

        status, _ct, body = routes.dispatch(
            "PUT",
            "/api/workspace/drama/drama/setup",
            json.dumps({"episode_no": 2, "hook": hooks[0]}, ensure_ascii=False).encode("utf-8"),
        )
        self.assertEqual(status, 200, body.decode())
        self.assertEqual(
            self._dispatch_drama_job("drama", "storyboard", {"episode_no": 2})["status"],
            "succeeded",
        )

        status, _ct, body = routes.dispatch(
            "GET",
            "/api/workspace/drama/drama/progress?episode_no=2",
        )
        self.assertEqual(status, 200, body.decode())
        progress = json.loads(body)
        character_station = next(row for row in progress["stations"] if row["id"] == "characters")
        self.assertEqual(character_station["status"], "skipped")
        self.assertEqual(character_paths("drama").sheet_path.read_bytes(), character_before)

        self.assertEqual(
            self._dispatch_drama_job("drama", "review", {"episode_no": 2})["status"],
            "succeeded",
        )

        status, _ct, body = routes.dispatch("GET", "/api/workspace/drama/drama/episodes")
        self.assertEqual(status, 200, body.decode())
        episode_payload = json.loads(body)
        episodes = episode_payload["episodes"]
        self.assertEqual([row["episode_no"] for row in episodes], [1, 2])
        self.assertFalse(episode_payload["can_start_next"])
        status, _ct, _body = routes.dispatch(
            "POST",
            "/api/workspace/drama/drama/next-episode",
            b'{"after_episode_no": 2}',
        )
        self.assertEqual(status, 400)
        self.assertFalse(drama_store.is_episode_stale("drama", episode_no=1))

        status, _ct, html = routes.dispatch("GET", "/w/drama/write?episode=2")
        self.assertEqual(status, 200)
        page = html.decode("utf-8")
        self.assertIn('window.CHAPTER_NO = 2', page)
        self.assertIn("第 2 集 · 4 站审查向导", page)

    def test_next_episode_requires_fresh_previous_and_honors_plan_limit(self) -> None:
        self._assembled_episode_one()
        ep1 = episode_paths("drama", episode_no=1)
        board = json.loads(ep1.storyboard_path.read_text(encoding="utf-8"))
        board["title"] = "stale"
        ep1.storyboard_path.write_text(json.dumps(board, ensure_ascii=False), encoding="utf-8")
        status, _ct, _body = routes.dispatch(
            "POST",
            "/api/workspace/drama/drama/next-episode",
            b'{"after_episode_no": 1}',
        )
        self.assertEqual(status, 409)

        write_json(
            ep1.review_path,
            drama_reviewer.run("drama", mock=True, episode_no=1),
        )
        drama_store.assemble_episode("drama", episode_no=1)
        status, _ct, body = routes.dispatch(
            "POST",
            "/api/workspace/drama/drama/next-episode",
            b'{"after_episode_no": 1}',
        )
        self.assertEqual(status, 200, body.decode())
        # Episode 3 exceeds wizard episode_count=2 even if a caller guesses it.
        episode_paths("drama", episode_no=2).episode_path.write_text(
            episode_paths("drama", episode_no=1).episode_path.read_text(encoding="utf-8").replace('"episode_no": 1', '"episode_no": 2'),
            encoding="utf-8",
        )
        status, _ct, _body = routes.dispatch(
            "POST",
            "/api/workspace/drama/drama/next-episode",
            b'{"after_episode_no": 2}',
        )
        self.assertEqual(status, 400)

    def test_next_episode_rejects_partial_artifacts_and_direct_plan_bypass(self) -> None:
        self._assembled_episode_one()
        ep1 = episode_paths("drama", episode_no=1)
        ep1.meta_path.unlink()
        status, _ct, _body = routes.dispatch(
            "POST",
            "/api/workspace/drama/drama/next-episode",
            b'{"after_episode_no": 1}',
        )
        self.assertEqual(status, 400)
        self.assertFalse(episode_paths("drama", episode_no=2).setup_path.exists())

        status, _ct, _body = routes.dispatch(
            "POST",
            "/api/workspace/drama/drama/plan",
            b'{"episode_no": 2}',
        )
        self.assertEqual(status, 409)
        self.assertFalse(episode_paths("drama", episode_no=2).setup_path.exists())

    def test_episode_schema_numbers_are_strict(self) -> None:
        self._make_drama_workspace("strict", "霸总")
        self._write_setup("strict", hook=True)
        board = storyboard_builder.run("strict", mock=True)
        episode_paths("strict").storyboard_path.write_text(
            json.dumps(board, ensure_ascii=False), encoding="utf-8"
        )
        sheet = character_designer.run("strict", mock=True)
        character_paths("strict").sheet_path.parent.mkdir(parents=True, exist_ok=True)
        character_paths("strict").sheet_path.write_text(
            json.dumps(sheet, ensure_ascii=False), encoding="utf-8"
        )
        review = drama_reviewer.run("strict", mock=True)
        fixtures = [
            (DramaStoryboard, board),
            (CharacterSheet, sheet),
            (DramaReview, review),
        ]
        episode = {
            "episode_no": 1,
            "target_duration_seconds": 60,
            "estimated_duration_seconds": 60,
        }
        meta = {
            "episode_no": 1,
            "verdict": "Approve",
            "duration_estimate_vs_target": {"target": 60, "estimate": 60, "delta": 0},
        }
        fixtures.extend([(DramaEpisode, episode), (DramaEpisodeMeta, meta)])
        for model, payload in fixtures:
            for invalid in (True, 1.0, "1"):
                with self.subTest(model=model.__name__, invalid=invalid):
                    with self.assertRaises(Exception):
                        model(**{**payload, "episode_no": invalid})

    def test_detail_rejects_mismatched_artifact_number(self) -> None:
        self._assembled_episode_one()
        ep1 = episode_paths("drama", episode_no=1)
        episode = json.loads(ep1.episode_path.read_text(encoding="utf-8"))
        episode["episode_no"] = 2
        ep1.episode_path.write_text(json.dumps(episode, ensure_ascii=False), encoding="utf-8")
        status, _ct, _body = routes.dispatch(
            "GET", "/api/workspace/drama/drama/episode/1"
        )
        self.assertEqual(status, 400)

    def test_episode_two_new_character_flag_keeps_station_four_reachable(self) -> None:
        self._assembled_episode_one()
        routes.dispatch(
            "POST",
            "/api/workspace/drama/drama/next-episode",
            b'{"after_episode_no": 1}',
        )
        self.assertEqual(
            self._dispatch_drama_job("drama", "hooks", {"episode_no": 2})["status"],
            "succeeded",
        )
        _status, _ct, body = routes.dispatch(
            "GET", "/api/workspace/drama/drama/hook-candidates?episode_no=2"
        )
        hook = json.loads(body)["hooks"][0]
        routes.dispatch(
            "PUT",
            "/api/workspace/drama/drama/setup",
            json.dumps(
                {
                    "episode_no": 2,
                    "hook": hook,
                    "introduces_new_characters": True,
                },
                ensure_ascii=False,
            ).encode("utf-8"),
        )
        self.assertEqual(
            self._dispatch_drama_job("drama", "storyboard", {"episode_no": 2})["status"],
            "succeeded",
        )
        status, _ct, body = routes.dispatch(
            "GET", "/api/workspace/drama/drama/progress?episode_no=2"
        )
        self.assertEqual(status, 200, body.decode())
        station = next(
            row for row in json.loads(body)["stations"] if row["id"] == "characters"
        )
        self.assertEqual(station["status"], "todo")
        status, _ct, body = routes.dispatch(
            "GET", "/api/workspace/drama/drama/characters?episode_no=2"
        )
        self.assertEqual(status, 200, body.decode())
        self.assertFalse(json.loads(body)["exists"])
        self.assertEqual(
            self._dispatch_drama_job("drama", "review", {"episode_no": 2})["status"],
            "blocked",
        )
        status, _ct, body = routes.dispatch(
            "POST", "/api/workspace/drama/drama/assemble", b'{"episode_no": 2}'
        )
        self.assertEqual(status, 400, body.decode())

        job = self._dispatch_drama_job("drama", "characters", {"episode_no": 2})
        self.assertEqual(job["status"], "succeeded", job)
        status, _ct, body = routes.dispatch(
            "GET", "/api/workspace/drama/drama/characters?episode_no=2"
        )
        result = json.loads(body)
        self.assertFalse(result["skipped"])
        self.assertEqual(result["sheet"]["episode_no"], 2)
        self.assertIn(2, result["sheet"]["generated_episode_nos"])
        self.assertTrue(any(
            row.get("name") == "新增角色2" and 2 in row.get("appearances", [])
            for row in result["sheet"]["characters"]
        ))

    def test_drama_insights_page_api_and_static_contract(self) -> None:
        self._assembled_episode_one()
        status, _ct, body = routes.dispatch("GET", "/w/drama/insights")
        self.assertEqual(status, 200, body.decode())
        html = body.decode("utf-8")
        self.assertIn('window.PAGE_KIND = "drama_insights"', html)
        self.assertIn('id="drama-insights-cost"', html)
        self.assertIn('/w/drama/insights', html)

        status, _ct, body = routes.dispatch("GET", "/api/workspace/drama/insights")
        self.assertEqual(status, 200, body.decode())
        payload = json.loads(body)
        self.assertIn("llm_cost", payload)
        self.assertIn("episode_meta_cost", payload)
        self.assertIn("duration", payload)
        self.assertIn("hook_types", payload)

        status, _ct, body = routes.dispatch("GET", "/static/app.js")
        self.assertEqual(status, 200)
        js = body.decode("utf-8")
        self.assertIn("function dramaPayload", js)
        self.assertIn("data-start-next-episode", js)
        self.assertIn("Comfy workflow 模板", js)
        self.assertNotIn("导出即将上线", js)

    def test_drama_only_boundaries_for_new_routes(self) -> None:
        init_workspace("novel", type="novel")
        status, _ct, _body = routes.dispatch(
            "GET",
            "/api/workspace/novel/drama/episode/1/export?format=json",
        )
        self.assertEqual(status, 400)
        status, _ct, _body = routes.dispatch(
            "POST",
            "/api/workspace/novel/drama/next-episode",
            b'{"after_episode_no": 1}',
        )
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
