"""Isolated-workspace A-F local acceptance demonstration regressions."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from unittest.mock import patch

from src import (
    character_designer,
    drama_compose_web,
    drama_local_demo,
    drama_reviewer,
    drama_store,
    drama_smoke,
    storyboard_builder,
)
from src.drama_schemas import character_paths, episode_paths
from src.drama_compositor import DramaComposeError
from src.drama_media_qa import DramaMediaQaError
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

    def test_media_toolchain_preflight_is_bounded_and_checks_both_tools(self) -> None:
        completed = subprocess.CompletedProcess([], 0, b"version", b"")
        with patch(
            "src.drama_local_demo._run_bounded_process",
            return_value=completed,
        ) as run_process:
            drama_local_demo.require_local_media_toolchain()

        self.assertEqual(
            [call.args[0] for call in run_process.call_args_list],
            [["ffmpeg", "-version"], ["ffprobe", "-version"]],
        )
        for call in run_process.call_args_list:
            self.assertEqual(call.kwargs["timeout_seconds"], 5)
            self.assertEqual(call.kwargs["stdout_limit"], 4096)
            self.assertEqual(call.kwargs["stderr_limit"], 4096)

    def test_media_toolchain_preflight_maps_all_probe_failures_to_safe_error(self) -> None:
        failures = (
            DramaMediaQaError("secret executable path"),
            subprocess.CompletedProcess([], 7, b"", b"secret stderr"),
        )
        for failure in failures:
            with self.subTest(failure=type(failure).__name__):
                effect = failure if isinstance(failure, Exception) else None
                with patch(
                    "src.drama_local_demo._run_bounded_process",
                    side_effect=effect,
                    return_value=None if effect else failure,
                ):
                    with self.assertRaises(drama_local_demo.DramaLocalDemoError) as raised:
                        drama_local_demo.require_local_media_toolchain()
                self.assertEqual(raised.exception.code, "media_toolchain_unavailable")
                self.assertNotIn("secret", str(raised.exception))

    def test_production_projection_blocks_when_media_toolchain_is_unavailable(self) -> None:
        name = "local-demo-no-media-tools"
        self._approved_workspace(name)
        unavailable = drama_local_demo.DramaLocalDemoError(
            "media_toolchain_unavailable", "固定安全提示"
        )
        with patch.dict("os.environ", {"OPENAI_MODEL": "mock"}, clear=False), patch(
            "src.drama_local_demo.require_local_media_toolchain",
            side_effect=unavailable,
        ):
            status, _ct, body = routes.dispatch(
                "GET", f"/api/workspace/{name}/drama/production?episode_no=1"
            )

        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertEqual(payload["local_demo"]["state"], "blocked")
        self.assertFalse(payload["local_demo"]["can_start"])
        self.assertEqual(payload["local_demo"]["reason"], "固定安全提示")

    def test_local_demo_post_does_not_allocate_job_when_tools_are_unavailable(self) -> None:
        name = "local-demo-post-no-tools"
        self._approved_workspace(name)
        headers = {
            "content-type": "application/json",
            "x-drama-mutation-intent": "mutate-v1",
        }
        with patch.dict("os.environ", {"OPENAI_MODEL": "mock"}, clear=False), patch(
            "src.drama_local_demo.require_local_media_toolchain",
            side_effect=drama_local_demo.DramaLocalDemoError(
                "media_toolchain_unavailable", "固定安全提示"
            ),
        ), patch("src.web.routes.jobs.start_job") as start_job:
            status, _ct, body = routes.dispatch(
                "POST",
                f"/api/workspace/{name}/drama/production/local-demo",
                b'{"episode_no":1,"confirm_synthetic_local":true}',
                headers,
            )

        self.assertEqual(status, 409)
        self.assertEqual(json.loads(body)["error"], "固定安全提示")
        start_job.assert_not_called()

    def test_isolated_worker_rechecks_tools_before_creating_workspace(self) -> None:
        source = "local-demo-preflight-source"
        target = "localdemo_deadbeef_1_00000000"
        self._approved_workspace(source)
        with patch.dict("os.environ", {"OPENAI_MODEL": "mock"}, clear=False), patch(
            "src.drama_local_demo.require_local_media_toolchain",
            side_effect=drama_local_demo.DramaLocalDemoError(
                "media_toolchain_unavailable", "固定安全提示"
            ),
        ), patch("src.drama_smoke.run_smoke") as run_smoke:
            with self.assertRaises(drama_local_demo.DramaLocalDemoError) as raised:
                drama_local_demo.run_isolated_synthetic_local_demo(
                    source, demo_workspace=target
                )

        self.assertEqual(raised.exception.code, "media_toolchain_unavailable")
        run_smoke.assert_not_called()
        self.assertFalse(drama_local_demo.paths.workspace_root(target).exists())

    def test_runtime_media_error_is_safe_but_job_cancellation_propagates(self) -> None:
        with patch(
            "src.drama_local_demo.require_local_media_toolchain"
        ), patch(
            "src.drama_local_demo._run_synthetic_local_demo_impl",
            side_effect=DramaMediaQaError("secret stderr"),
        ):
            with self.assertRaises(drama_local_demo.DramaLocalDemoError) as raised:
                drama_local_demo.run_synthetic_local_demo("localdemo_f00d_1_deadbeef")
        self.assertEqual(raised.exception.code, "local_demo_media_failed")
        self.assertNotIn("secret", str(raised.exception))

        cancellation = jobs.JobCancelled("cancelled by test")
        with patch(
            "src.drama_local_demo.require_local_media_toolchain"
        ), patch(
            "src.drama_local_demo._run_synthetic_local_demo_impl",
            side_effect=cancellation,
        ):
            with self.assertRaises(jobs.JobCancelled) as raised_cancel:
                drama_local_demo.run_synthetic_local_demo("localdemo_f00d_1_deadbeef")
        self.assertIs(raised_cancel.exception, cancellation)

    def test_wrapped_compose_media_error_becomes_safe_blocked_job(self) -> None:
        name = "local-demo-compose-error"
        self._approved_workspace(name)
        target = drama_local_demo.allocate_synthetic_demo_workspace(name, episode_no=1)
        with patch(
            "src.drama_local_demo._run_synthetic_local_demo_impl",
            side_effect=DramaComposeError("secret stderr /private/tool"),
        ):
            record = jobs.start_job(name, "drama-local-demo", {
                "episode_no": 1,
                "demo_workspace": target,
            })
            terminal = self._wait_for_job(record["job_id"])
        self.assertEqual(terminal["status"], "blocked")
        blocked = terminal["result_summary"]["first_blocked"]
        self.assertEqual(blocked["reason"], "local_demo_media_failed")
        self.assertNotIn("secret", json.dumps(jobs.public_job_detail_view(terminal)))

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

    def test_embedded_smoke_does_not_mutate_process_model_environment(self) -> None:
        name = "local-demo-env"
        self._approved_workspace(name)
        completed = {
            "drama-plan",
            "drama-hooks",
            "drama-storyboard",
            "drama-characters",
            "drama-review-assemble",
        }
        with patch.dict(
            "os.environ",
            {"OPENAI_MODEL": "sentinel/model", "DRAMA_MODEL": "mock"},
            clear=False,
        ):
            drama_smoke.run_smoke(
                name,
                real_text=False,
                create_workspace=False,
                completed_steps=completed,
                pin_mock_environment=False,
            )
            import os

            self.assertEqual(os.environ["OPENAI_MODEL"], "sentinel/model")
            self.assertEqual(os.environ["DRAMA_MODEL"], "mock")

    def test_fixture_video_forwards_cancellation_checkpoint(self) -> None:
        root = Path(self._tmp.name)
        sentinel = RuntimeError("cancelled by test")
        target = root / "outputs/drama/local_demo/fixture_099.mp4"

        def create_partial_then_check(*_args, **kwargs):
            target.write_bytes(b"partial")
            kwargs["checkpoint"]()

        with patch(
            "src.drama_local_demo._run_bounded_process",
            side_effect=create_partial_then_check,
        ) as run_process:
            with self.assertRaisesRegex(RuntimeError, "cancelled by test"):
                drama_local_demo._fixture_mp4(
                    root,
                    duration_seconds=0.2,
                    ordinal=99,
                    checkpoint=lambda: (_ for _ in ()).throw(sentinel),
                )

        self.assertEqual(run_process.call_count, 1)
        self.assertFalse(target.exists())

    def tearDown(self) -> None:
        jobs.reset_for_tests()
        super().tearDown()


if __name__ == "__main__":
    import unittest

    unittest.main()
