"""Iteration 090: five-station drama background jobs."""

from __future__ import annotations

import json
import threading
import time
from unittest.mock import patch

from src.drama_schemas import character_paths, episode_paths
from src.web import jobs, routes
from src.web.drama_view import collect_drama_progress
from tests._drama_base import DramaTestBase


class DramaJobTests(DramaTestBase):
    def _post(self, name: str, suffix: str, payload: dict | None = None) -> dict:
        status, _ct, body = routes.dispatch(
            "POST",
            f"/api/workspace/{name}/drama/{suffix}",
            json.dumps(payload or {}, ensure_ascii=False).encode("utf-8"),
        )
        self.assertEqual(status, 202, body.decode("utf-8", errors="replace"))
        return json.loads(body)

    def _wait(self, job_id: str, timeout: float = 5.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            job = jobs.get_job(job_id)
            if job and job.get("status") in jobs.TERMINAL_STATUSES:
                return job
            time.sleep(0.01)
        self.fail(f"job did not finish: {job_id}")

    def _run(self, name: str, suffix: str, payload: dict | None = None) -> dict:
        started = self._post(name, suffix, payload)
        result = self._wait(started["job_id"])
        self.assertEqual(result["status"], "succeeded", result)
        return result

    def test_mock_five_station_chain_and_candidate_refresh(self) -> None:
        self._make_drama_workspace("drama", "霸总", episode_count=2)

        self._run("drama", "plan")
        self.assertTrue(episode_paths("drama").setup_path.is_file())

        self._run("drama", "hooks")
        status, _ct, body = routes.dispatch(
            "GET", "/api/workspace/drama/drama/hook-candidates?episode_no=1"
        )
        self.assertEqual(status, 200)
        hooks = json.loads(body)["hooks"]
        self.assertEqual(len(hooks), 3)
        status, _ct, body = routes.dispatch(
            "PUT",
            "/api/workspace/drama/drama/setup",
            json.dumps({"episode_no": 1, "hook": hooks[0]}, ensure_ascii=False).encode("utf-8"),
        )
        self.assertEqual(status, 200, body.decode())
        self.assertFalse(episode_paths("drama").hook_candidates_path.exists())

        self._run("drama", "storyboard")
        self._run("drama", "characters")
        self.assertTrue(character_paths("drama").sheet_path.is_file())
        self._run("drama", "review")
        ep = episode_paths("drama")
        self.assertTrue(ep.review_path.is_file())
        self.assertTrue(ep.episode_path.is_file())
        self.assertTrue(ep.meta_path.is_file())

    def test_cancel_during_provider_call_prevents_commit(self) -> None:
        self._make_drama_workspace("cancel", "霸总")
        entered = threading.Event()
        release = threading.Event()

        def slow_run(*_args, **_kwargs):
            entered.set()
            release.wait(timeout=2)
            return {
                "episode_no": 1,
                "season_no": 1,
                "title": "x",
                "logline": "l",
                "track": "霸总",
                "target_duration_seconds": 60,
                "core_setup": {"protagonist": "p", "antagonist": "a", "emotional_hook": "e"},
            }

        with patch("src.drama_planner.run", side_effect=slow_run):
            started = self._post("cancel", "plan")
            self.assertTrue(entered.wait(timeout=2))
            self.assertIsNotNone(jobs.request_cancel(started["job_id"]))
            release.set()
            terminal = self._wait(started["job_id"])

        self.assertEqual(terminal["status"], "aborted")
        self.assertFalse(episode_paths("cancel").setup_path.exists())

    def test_job_params_are_minimal_and_cross_workspace_poll_is_hidden(self) -> None:
        self._make_drama_workspace("one", "霸总")
        self._make_drama_workspace("two", "推理")
        started = self._post("one", "plan")
        self.assertEqual(jobs.get_job(started["job_id"])["params"], {"episode_no": 1})
        status, _ct, _body = routes.dispatch(
            "GET", f"/api/workspace/two/job/{started['job_id']}"
        )
        self.assertEqual(status, 404)
        self._wait(started["job_id"])

    def test_real_model_route_requires_confirmation_budget_and_timeout(self) -> None:
        self._make_drama_workspace("real", "推理")
        real_cfg = {"model": "deepseek/deepseek-chat"}
        with patch("src.web.routes.get_model_config", return_value=real_cfg):
            for payload in (
                {},
                {"confirm_real_text": True, "budget_cny": 1},
                {"confirm_real_text": True, "timeout_minutes": 1},
                {"confirm_real_text": True, "budget_cny": "nan", "timeout_minutes": 1},
                {"confirm_real_text": True, "budget_cny": 1, "timeout_minutes": "inf"},
            ):
                status, _ct, _body = routes.dispatch(
                    "POST", "/api/workspace/real/drama/plan", json.dumps(payload).encode()
                )
                self.assertEqual(status, 400, payload)

    def test_budget_is_settled_before_plan_artifact_commit(self) -> None:
        self._make_drama_workspace("budget", "推理")
        result = {
            "episode_no": 1, "season_no": 1, "title": "t", "logline": "l",
            "track": "推理", "target_duration_seconds": 60,
            "core_setup": {"protagonist": "p", "antagonist": "a", "emotional_hook": "e"},
        }
        with patch("src.config.get_model_config", return_value={"model": "deepseek/deepseek-chat"}), \
                patch("src.drama_smoke.validate_real_text_tasks_ready"), \
                patch("src.drama_planner.run", return_value=result), \
                patch("src.cost_estimator.estimate_cost_since", return_value={"cost_cny": 2.0}):
            started = jobs.start_job("budget", "drama-plan", {
                "episode_no": 1, "confirm_real_text": True,
                "budget_cny": 1.0, "timeout_minutes": 1.0,
            })
            terminal = self._wait(started["job_id"])
        self.assertEqual(terminal["status"], "budget_exceeded")
        self.assertEqual(terminal["result_summary"]["cost_cny"], 2.0)
        self.assertFalse(episode_paths("budget").setup_path.exists())

    def test_internal_real_job_requires_bounded_timeout(self) -> None:
        self._make_drama_workspace("timeout_guard", "推理")
        with patch("src.config.get_model_config", return_value={"model": "deepseek/deepseek-chat"}), \
                patch("src.drama_planner.run") as planner:
            started = jobs.start_job("timeout_guard", "drama-plan", {
                "episode_no": 1, "confirm_real_text": True, "budget_cny": 1.0,
            })
            terminal = self._wait(started["job_id"])
        self.assertEqual(terminal["status"], "blocked")
        planner.assert_not_called()

    def test_episode_two_character_skip_requires_current_storyboard(self) -> None:
        self._make_drama_workspace("skip", "推理")
        setup_path = episode_paths("skip", episode_no=2).setup_path
        setup_path.parent.mkdir(parents=True, exist_ok=True)
        setup_path.write_text(json.dumps({
            "schema_version": 1, "episode_no": 2, "season_no": 1,
            "title": "ep2", "logline": "l", "track": "推理",
            "target_duration_seconds": 60,
            "core_setup": {"protagonist": "p", "antagonist": "a", "emotional_hook": "e"},
            "hook": {"type": "悬念钩", "content": "h"},
            "introduces_new_characters": False,
        }, ensure_ascii=False), encoding="utf-8")
        cp = character_paths("skip").sheet_path
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps({
            "schema_version": 1, "season_no": 1, "episode_no": 1, "track": "推理",
            "source_storyboard_title": "ep1", "characters": [{
                "id": "c001", "name": "角色甲", "lora_token": "role_a",
                "visual_signature": "左眼下小痣",
            }],
        }, ensure_ascii=False), encoding="utf-8")
        with patch("src.character_designer.run") as generate:
            started = self._post("skip", "characters", {"episode_no": 2})
            terminal = self._wait(started["job_id"])
        self.assertEqual(terminal["status"], "blocked")
        generate.assert_not_called()

    def test_episode_two_rejects_storyboard_with_wrong_episode_identity(self) -> None:
        self._make_drama_workspace("wrong_ep", "推理")
        self._run("wrong_ep", "plan")
        setup1 = json.loads(episode_paths("wrong_ep").setup_path.read_text())
        setup2 = dict(setup1)
        setup2["episode_no"] = 2
        setup2["hook"] = {"type": "悬念钩", "content": "h"}
        setup2["introduces_new_characters"] = True
        ep2 = episode_paths("wrong_ep", episode_no=2)
        ep2.setup_path.write_text(json.dumps(setup2, ensure_ascii=False), encoding="utf-8")
        self._run("wrong_ep", "storyboard", {"episode_no": 2})
        board = json.loads(ep2.storyboard_path.read_text())
        board["episode_no"] = 1
        ep2.storyboard_path.write_text(json.dumps(board, ensure_ascii=False), encoding="utf-8")
        started = self._post("wrong_ep", "characters", {"episode_no": 2})
        terminal = self._wait(started["job_id"])
        self.assertEqual(terminal["status"], "blocked")
        self.assertEqual(collect_drama_progress("wrong_ep", episode_no=2)["stations"][2]["status"], "todo")
        cp = character_paths("wrong_ep").sheet_path
        cp.parent.mkdir(parents=True, exist_ok=True)
        cp.write_text(json.dumps({
            "schema_version": 1, "season_no": 1, "episode_no": 2, "track": "推理",
            "source_storyboard_title": "ep2", "characters": [{
                "id": "c001", "name": "角色甲", "lora_token": "role_a",
                "visual_signature": "左眼下小痣",
            }],
        }, ensure_ascii=False), encoding="utf-8")
        started = self._post("wrong_ep", "review", {"episode_no": 2})
        terminal = self._wait(started["job_id"])
        self.assertEqual(terminal["status"], "blocked")
        self.assertFalse(ep2.episode_path.exists())

    def test_station_five_failure_restores_previous_artifacts(self) -> None:
        self._make_drama_workspace("rollback", "霸总")
        self._run("rollback", "plan")
        self._run("rollback", "hooks")
        hooks = json.loads(episode_paths("rollback").hook_candidates_path.read_text())["hooks"]
        routes.dispatch("PUT", "/api/workspace/rollback/drama/setup", json.dumps({
            "episode_no": 1, "hook": hooks[0],
        }, ensure_ascii=False).encode())
        self._run("rollback", "storyboard")
        self._run("rollback", "characters")
        self._run("rollback", "review")
        ep = episode_paths("rollback")
        before = {path: path.read_bytes() for path in (ep.review_path, ep.episode_path, ep.meta_path)}
        with patch("src.drama_store.assemble_episode", side_effect=RuntimeError("boom")):
            started = self._post("rollback", "review")
            terminal = self._wait(started["job_id"])
        self.assertEqual(terminal["status"], "failed")
        self.assertEqual(before, {path: path.read_bytes() for path in before})

    def test_regenerating_plan_invalidates_unselected_hook_candidates(self) -> None:
        self._make_drama_workspace("invalidate", "推理")
        self._run("invalidate", "plan")
        self._run("invalidate", "hooks")
        candidate_path = episode_paths("invalidate").hook_candidates_path
        self.assertTrue(candidate_path.is_file())
        self._run("invalidate", "plan")
        self.assertFalse(candidate_path.exists())

    def test_progress_cascades_closed_after_station_one_regeneration(self) -> None:
        self._make_drama_workspace("cascade", "霸总")
        self._run("cascade", "plan")
        hook_job = self._run("cascade", "hooks")
        self.assertEqual(hook_job["status"], "succeeded")
        hooks = json.loads(episode_paths("cascade").hook_candidates_path.read_text())["hooks"]
        status, _ct, _body = routes.dispatch(
            "PUT", "/api/workspace/cascade/drama/setup",
            json.dumps({"episode_no": 1, "hook": hooks[0]}, ensure_ascii=False).encode(),
        )
        self.assertEqual(status, 200)
        self._run("cascade", "storyboard")
        self._run("cascade", "characters")
        self._run("cascade", "review")
        self.assertEqual(collect_drama_progress("cascade")["stations"][-1]["status"], "done")
        self._run("cascade", "plan")
        self.assertEqual(
            [row["status"] for row in collect_drama_progress("cascade")["stations"]],
            ["done", "todo", "locked", "locked", "locked"],
        )

    def test_run_endpoint_isolates_novel_and_drama_steps(self) -> None:
        self._make_drama_workspace("drama_run", "推理")
        from src.cli_workspace import init_workspace
        init_workspace("novel_run")
        status, _ct, _body = routes.dispatch(
            "POST", "/api/workspace/novel_run/run",
            json.dumps({"step": "drama-plan", "params": {"episode_no": 1}}).encode(),
        )
        self.assertEqual(status, 400)
        status, _ct, body = routes.dispatch(
            "POST", "/api/workspace/drama_run/run",
            json.dumps({"step": "drama-plan", "params": {"episode_no": 1}}).encode(),
        )
        self.assertEqual(status, 202, body.decode())
        self._wait(json.loads(body)["job_id"])
        status, _ct, _body = routes.dispatch(
            "POST", "/api/workspace/drama_run/run",
            json.dumps({"step": "drama-plan", "params": {"episode_no": 1, "extra": 1}}).encode(),
        )
        self.assertEqual(status, 400)


if __name__ == "__main__":
    import unittest

    unittest.main()
