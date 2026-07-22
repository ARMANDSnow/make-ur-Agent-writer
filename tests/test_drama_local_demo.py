"""Isolated-workspace A-F local acceptance demonstration regressions."""

from __future__ import annotations

import json
import time
from unittest.mock import patch

from src import (
    character_designer,
    drama_compose_web,
    drama_local_demo,
    drama_reviewer,
    drama_store,
    storyboard_builder,
)
from src.drama_schemas import character_paths, episode_paths
from src.utils import write_json
from src.web import jobs, routes
from tests._drama_base import DramaTestBase


class DramaLocalDemoTests(DramaTestBase):
    @staticmethod
    def _wait_for_job(job_id: str) -> dict:
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            row = jobs.get_job(job_id)
            if row and row.get("status") in jobs.TERMINAL_STATUSES:
                return row
            time.sleep(0.02)
        raise TimeoutError(job_id)

    def _approved_workspace(self, name: str) -> None:
        self._make_drama_workspace(name, episode_duration_seconds=30)
        self._write_setup(name, hook=True)
        write_json(
            episode_paths(name).storyboard_path,
            storyboard_builder.run(name, mock=True),
        )
        write_json(
            character_paths(name).sheet_path,
            character_designer.run(name, mock=True),
        )
        write_json(
            episode_paths(name).review_path,
            drama_reviewer.run(name, mock=True),
        )
        drama_store.assemble_episode(name)

    def test_isolated_workspace_runs_a_through_f_with_exact_duration_and_deliverables(self) -> None:
        name = "localdemo_f00d_00000001"
        self._approved_workspace(name)

        with patch.dict("os.environ", {"OPENAI_MODEL": "mock"}, clear=False):
            result = drama_local_demo.run_synthetic_local_demo(name)

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["acceptance_level"], "local-e2e")
        self.assertFalse(result["provider_validated"])
        self.assertGreaterEqual(result["shot_count"], 6)
        overview = drama_compose_web.build_compose_web_overview(name)
        self.assertEqual(overview["state"], "complete")
        self.assertAlmostEqual(overview["duration_ms"] / 1000, 30.0, delta=0.25)
        self.assertAlmostEqual(overview["qa"]["duration_ms"] / 1000, 30.0, delta=0.25)
        self.assertEqual(len(overview["deliverables"]), 4)
        for row in overview["deliverables"]:
            status, _content_type, body = routes.dispatch("GET", row["url"])[:3]
            self.assertEqual(status, 200, row)
            self.assertGreater(len(body), 0)

    def test_local_demo_endpoint_requires_explicit_confirmation_and_mock(self) -> None:
        name = "local-demo-route"
        self._approved_workspace(name)
        url = f"/api/workspace/{name}/drama/production/local-demo"
        headers = {
            "content-type": "application/json",
            "x-drama-mutation-intent": "mutate-v1",
        }
        denied = routes.dispatch(
            "POST", url, b'{"episode_no":1}', headers
        )
        self.assertEqual(denied[0], 400)

        with patch(
            "src.drama_local_demo.get_model_config",
            return_value={"model": "openai/not-mock"},
        ):
            real = routes.dispatch(
                "POST",
                url,
                json.dumps({
                    "episode_no": 1,
                    "confirm_synthetic_local": True,
                }).encode(),
                headers,
            )
        self.assertEqual(real[0], 409)
        self.assertNotIn(b"openai/not-mock", real[2])

    def test_production_get_exposes_truthful_local_demo_action(self) -> None:
        name = "local-demo-projection"
        self._approved_workspace(name)
        with patch.dict("os.environ", {"OPENAI_MODEL": "mock"}, clear=False):
            status, _ct, body = routes.dispatch(
                "GET", f"/api/workspace/{name}/drama/production?episode_no=1"
            )
        self.assertEqual(status, 200, body.decode())
        payload = json.loads(body)
        self.assertEqual(payload["local_demo"]["state"], "ready")
        self.assertTrue(payload["local_demo"]["can_start"])

    def test_background_job_runs_without_nesting_workspace_lock(self) -> None:
        name = "local-demo-job"
        self._approved_workspace(name)
        before_characters = character_paths(name).sheet_path.read_bytes()
        demo_name = drama_local_demo.allocate_synthetic_demo_workspace(
            name, episode_no=1
        )
        with patch.dict("os.environ", {"OPENAI_MODEL": "mock"}, clear=False):
            job = jobs.start_job(name, "drama-local-demo", {
                "episode_no": 1,
                "demo_workspace": demo_name,
            })
            terminal = self._wait_for_job(job["job_id"])
        self.assertEqual(terminal["status"], "succeeded", terminal)
        self.assertEqual(
            terminal["result_summary"]["acceptance_level"], "local-e2e"
        )
        self.assertEqual(character_paths(name).sheet_path.read_bytes(), before_characters)
        self.assertFalse(
            drama_local_demo.drama_render_store.render_plan_path(name).exists()
        )
        overview = drama_compose_web.build_compose_web_overview(demo_name)
        self.assertEqual(overview["state"], "complete")

    def test_user_facing_route_returns_isolated_target(self) -> None:
        name = "local-demo-isolated-route"
        self._approved_workspace(name)
        before_characters = character_paths(name).sheet_path.read_bytes()
        headers = {
            "content-type": "application/json",
            "x-drama-mutation-intent": "mutate-v1",
        }
        with patch.dict("os.environ", {"OPENAI_MODEL": "mock"}, clear=False):
            status, _ct, body = routes.dispatch(
                "POST",
                f"/api/workspace/{name}/drama/production/local-demo",
                json.dumps({
                    "episode_no": 1,
                    "confirm_synthetic_local": True,
                }).encode(),
                headers,
            )
            payload = json.loads(body)
            terminal = self._wait_for_job(payload["job_id"])
        self.assertEqual(status, 202, payload)
        self.assertRegex(payload["demo_workspace"], r"^localdemo_[a-f0-9_]+$")
        self.assertEqual(terminal["status"], "succeeded", terminal)
        self.assertEqual(character_paths(name).sheet_path.read_bytes(), before_characters)

    def test_direct_demo_rejects_a_normal_user_workspace(self) -> None:
        name = "local-demo-normal-source"
        self._approved_workspace(name)
        with patch.dict("os.environ", {"OPENAI_MODEL": "mock"}, clear=False):
            with self.assertRaisesRegex(
                drama_local_demo.DramaLocalDemoError,
                "只能写入 localdemo_",
            ):
                drama_local_demo.run_synthetic_local_demo(name)

    def tearDown(self) -> None:
        jobs.reset_for_tests()
        super().tearDown()


if __name__ == "__main__":
    import unittest

    unittest.main()
