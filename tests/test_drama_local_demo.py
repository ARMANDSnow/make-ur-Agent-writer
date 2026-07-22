"""Single-workspace A-F local production demonstration regressions."""

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

    def test_one_workspace_runs_a_through_f_and_commits_exact_deliverables(self) -> None:
        name = "local-demo-full"
        self._approved_workspace(name)

        with patch.dict("os.environ", {"OPENAI_MODEL": "mock"}, clear=False):
            result = drama_local_demo.run_synthetic_local_demo(name)

        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(result["acceptance_level"], "local-e2e")
        self.assertFalse(result["provider_validated"])
        self.assertGreaterEqual(result["shot_count"], 6)
        overview = drama_compose_web.build_compose_web_overview(name)
        self.assertEqual(overview["state"], "complete")
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
        with patch.dict("os.environ", {"OPENAI_MODEL": "mock"}, clear=False):
            job = jobs.start_job(name, "drama-local-demo", {"episode_no": 1})
            terminal = self._wait_for_job(job["job_id"])
        self.assertEqual(terminal["status"], "succeeded", terminal)
        self.assertEqual(
            terminal["result_summary"]["acceptance_level"], "local-e2e"
        )

    def tearDown(self) -> None:
        jobs.reset_for_tests()
        super().tearDown()


if __name__ == "__main__":
    import unittest

    unittest.main()
