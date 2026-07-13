"""Iteration 100: real short-drama end-to-end blocker regressions."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import zlib
from pathlib import Path
from unittest.mock import Mock, patch

from src import ai_draw_client, drama_multimodal_smoke as multi
from src import drama_video, drama_video_smoke
from src.drama_schemas import DramaCharacter, character_paths, episode_paths
from src.utils import read_json, sha256_data, write_json
from src.web import jobs, routes, static
from src.web.workspace_ctx import use_workspace
from tests._drama_base import DramaTestBase
from tests.test_drama_video import _FakeVideoClient


class Iter100DramaHardeningTests(DramaTestBase):
    def _prepare_text_only(self, name: str) -> None:
        with patch(
            "src.drama_multimodal_smoke.drama_smoke.real_text_tasks_ready",
            return_value=True,
        ), patch.dict(
            os.environ,
            {"CONFIRM_REAL_MODEL_SMOKE": "可以跑了", "DRAMA_MODEL": "mock"},
            clear=False,
        ):
            state = multi.run(name, real_text=True, options={
                "confirm_real_text": True,
                "text_budget_cny": 5,
                "text_timeout_seconds": 20,
            })
        self.assertEqual(state["status"], "awaiting_image_authorization")

    def test_hook_attempt_recovers_after_its_selected_hook_mutates_setup(self) -> None:
        self._make_drama_workspace("hook-recovery", "推理")
        setup_path = self._write_setup("hook-recovery", hook=False)
        result = {"hooks": [
            {"type": "情绪钩", "content": "a"},
            {"type": "悬念钩", "content": "b"},
            {"type": "反差钩", "content": "c"},
        ]}
        config = {"model": "provider/model", "base_url": "https://provider.example/v1"}
        with use_workspace("hook-recovery"), patch(
            "src.config.get_model_config", return_value=config
        ):
            returned, token = jobs._call_drama_text_model(
                "drama-hooks", {}, 1, lambda: result
            )
            jobs._bind_drama_text_artifact(token, returned, candidates=returned["hooks"])
            write_json(episode_paths("hook-recovery").hook_candidates_path, returned)
            jobs._mark_drama_text_attempt(token, "succeeded")
            setup = read_json(setup_path)
            setup["hook"] = returned["hooks"][0]
            write_json(setup_path, setup)
            provider = Mock(side_effect=AssertionError("provider called"))
            recovered, _token = jobs._call_drama_text_model(
                "drama-hooks", {}, 1, provider
            )
            episode_paths("hook-recovery").hook_candidates_path.unlink()
            with self.assertRaisesRegex(ValueError, "artifact no longer matches"):
                jobs._call_drama_text_model("drama-hooks", {}, 1, provider)
        provider.assert_not_called()
        self.assertEqual(recovered, result)

    def test_character_attempt_recovers_after_its_sheet_is_committed(self) -> None:
        self._make_drama_workspace("character-recovery", "推理")
        self._write_setup("character-recovery", hook=True)
        write_json(episode_paths("character-recovery").storyboard_path, {"stable": True})
        result = {"schema_version": 1, "characters": [{"id": "c001"}]}
        config = {"model": "provider/model", "base_url": "https://provider.example/v1"}
        with use_workspace("character-recovery"), patch(
            "src.config.get_model_config", return_value=config
        ):
            returned, token = jobs._call_drama_text_model(
                "drama-characters", {}, 1, lambda: result
            )
            jobs._bind_drama_text_artifact(token, returned)
            write_json(character_paths("character-recovery").sheet_path, returned)
            jobs._mark_drama_text_attempt(token, "succeeded")
            provider = Mock(side_effect=AssertionError("provider called"))
            recovered, _token = jobs._call_drama_text_model(
                "drama-characters", {}, 1, provider
            )
        provider.assert_not_called()
        self.assertEqual(recovered, result)

    def test_legacy_first_character_attempt_can_upgrade_without_rebilling(self) -> None:
        self._make_drama_workspace("character-legacy", "推理")
        self._write_setup("character-legacy", hook=True)
        write_json(episode_paths("character-legacy").storyboard_path, {"stable": True})
        result = {"schema_version": 1, "characters": [{"id": "c001"}]}
        config = {"model": "provider/model", "base_url": "https://provider.example/v1"}
        with use_workspace("character-legacy"), patch(
            "src.config.get_model_config", return_value=config
        ):
            returned, token = jobs._call_drama_text_model(
                "drama-characters", {}, 1, lambda: result
            )
            jobs._bind_drama_text_artifact(token, returned)
            write_json(character_paths("character-legacy").sheet_path, returned)
            jobs._mark_drama_text_attempt(token, "succeeded")
            ledger = jobs._load_drama_text_attempts("character-legacy")
            ledger["attempts"]["drama-characters:1"].pop("recovery_fingerprint")
            jobs._save_drama_text_attempts("character-legacy", ledger)
            provider = Mock(side_effect=AssertionError("provider called"))
            recovered, _token = jobs._call_drama_text_model(
                "drama-characters", {}, 1, provider
            )
        provider.assert_not_called()
        self.assertEqual(recovered, result)

    def test_budget_exceeded_text_attempt_requires_reconciliation(self) -> None:
        self._make_drama_workspace("budget-retry", "推理")
        params = {"confirm_real_text": True, "budget_cny": 1, "timeout_minutes": 1}
        config = {"model": "provider/model", "base_url": "https://provider.example/v1"}
        with use_workspace("budget-retry"), patch(
            "src.config.get_model_config", return_value=config
        ):
            token = jobs._begin_drama_text_attempt("drama-plan", params, 1)
            jobs._mark_drama_text_attempt(token, "budget_exceeded")
            with self.assertRaisesRegex(ValueError, "reconciliation"):
                jobs._begin_drama_text_attempt("drama-plan", params, 1)

    def test_started_image_staging_is_adopted_without_second_paid_call(self) -> None:
        self._prepare_text_only("image-staging-recovery")
        options = {
            "confirm_real_image": True,
            "image_budget_cny": 10,
            "image_estimated_cost_cny": 1,
            "image_timeout_seconds": 120,
        }

        def crash_after_provider_write(_workspace, _character, **kwargs):
            multi._atomic_write_bytes(kwargs["output_path"], multi._PNG_1X1)
            raise KeyboardInterrupt("simulated process death")

        with patch(
            "src.drama_multimodal_smoke._image_provider_fingerprint",
            return_value="a" * 64,
        ), patch(
            "src.drama_multimodal_smoke.redraw_character_reference",
            side_effect=crash_after_provider_write,
        ):
            with self.assertRaises(KeyboardInterrupt):
                multi.run("image-staging-recovery", real_image=True, options=options)
        crashed = read_json(multi.state_path("image-staging-recovery"))
        self.assertEqual(crashed["image_attempts"]["c001"][-1]["status"], "started")
        original_staging = crashed["image_attempts"]["c001"][-1]["staging_path"]
        crashed["image_attempts"]["c001"][-1]["staging_path"] = (
            "data/character_refs/c002/portrait_neutral.png"
        )
        write_json(multi.state_path("image-staging-recovery"), crashed)
        with self.assertRaisesRegex(ValueError, "staging state"):
            multi.load_state("image-staging-recovery")
        crashed["image_attempts"]["c001"][-1]["staging_path"] = original_staging
        write_json(multi.state_path("image-staging-recovery"), crashed)

        def finish_other_character(workspace, _character, **kwargs):
            target = kwargs["output_path"]
            multi._atomic_write_bytes(target, multi._PNG_1X1)
            return {
                "path": str(target.relative_to(multi.paths.workspace_root(workspace))),
                "generated_by": "provider-a",
                "prompt": "x",
                "width": 1,
                "height": 1,
            }

        with patch(
            "src.drama_multimodal_smoke._image_provider_fingerprint",
            return_value="a" * 64,
        ), patch(
            "src.drama_multimodal_smoke.redraw_character_reference",
            side_effect=finish_other_character,
        ) as provider:
            state = multi.run("image-staging-recovery", real_image=True, options=options)
        self.assertEqual(provider.call_count, 1)
        self.assertEqual(provider.call_args.args[1]["id"], "c002")
        self.assertTrue(state["image_attempts"]["c001"][-1]["recovered_from_staging"])
        self.assertEqual(state["image_attempts"]["c001"][-1]["status"], "succeeded")

    def test_submitted_video_adopts_already_committed_local_pair(self) -> None:
        workspace = "video-local-recovery"
        drama_video_smoke._prepare_mock_inputs(workspace)
        inputs = drama_video.load_video_inputs(workspace)
        mock_result = drama_video._run_mock_video(inputs, lambda *_args: None)
        client = _FakeVideoClient()
        provider_fingerprint = drama_video._video_provider_fingerprint(
            client, drama_video.DEFAULT_VIDEO_MODEL
        )
        meta_path = drama_video.video_paths(workspace).meta_path
        meta = read_json(meta_path)
        meta.update({
            "task_id": "task-local",
            "provider": "video.example.test",
            "provider_model": drama_video.DEFAULT_VIDEO_MODEL,
            "duration_seconds": 5.0,
            "ratio": "9:16",
            "resolution": "720x1280px",
            "cost_cny": 1.25,
            "cost_unreported": False,
            "provider_fingerprint": provider_fingerprint,
        })
        write_json(meta_path, meta)
        hosts_fingerprint = sha256_data(["result.example.test"])
        drama_video._write_video_submission(workspace, {
            "status": "submitted",
            "input_fingerprint": inputs.fingerprint,
            "provider_fingerprint": provider_fingerprint,
            "result_hosts_fingerprint": hosts_fingerprint,
            "submission_count": 1,
            "task_id": "task-local",
            **drama_video._video_authorization(3.0, 1.0, 2.0),
            "updated_at": int(time.time()),
        })
        env = {
            "SD_VIDEO_MODE": "real",
            "SD_VIDEO_ESTIMATED_COST_CNY": "2",
            "SD_VIDEO_RESULT_HOSTS": "result.example.test",
            "SD_VIDEO_MODEL": drama_video.DEFAULT_VIDEO_MODEL,
        }
        with patch.dict(os.environ, env, clear=False), patch(
            "src.drama_video._probe_mp4",
            return_value=drama_video.VideoSpec(5.0, 720, 1280),
        ):
            recovered = drama_video.run_video_job(
                workspace,
                {"confirm_real_video": True, "budget_cny": 3, "timeout_minutes": 1},
                lambda *_args: None,
                client=client,
            )
        self.assertTrue(mock_result["committed"])
        self.assertTrue(recovered["resumed"])
        self.assertEqual(recovered["network_requests"], 0)
        self.assertEqual((client.uploads, client.submissions, client.polls), (0, 0, 0))
        self.assertEqual(drama_video.read_video_submission(workspace)["status"], "succeeded")

    def test_local_video_recovery_rejects_missing_provider_or_cost_lineage(self) -> None:
        workspace = "video-local-lineage"
        drama_video_smoke._prepare_mock_inputs(workspace)
        inputs = drama_video.load_video_inputs(workspace)
        drama_video._run_mock_video(inputs, lambda *_args: None)
        meta_path = drama_video.video_paths(workspace).meta_path
        meta = read_json(meta_path)
        meta.update({"task_id": "task-local", "cost_cny": None, "cost_unreported": False})
        write_json(meta_path, meta)
        with self.assertRaisesRegex(ValueError, "reported cost"):
            drama_video.read_video(workspace)

        client = _FakeVideoClient()
        client.get_task = Mock(side_effect=RuntimeError("poll required"))
        drama_video._write_video_submission(workspace, {
            "status": "submitted",
            "input_fingerprint": inputs.fingerprint,
            "provider_fingerprint": drama_video._video_provider_fingerprint(
                client, drama_video.DEFAULT_VIDEO_MODEL
            ),
            "result_hosts_fingerprint": sha256_data(["result.example.test"]),
            "submission_count": 1,
            "task_id": "task-local",
            **drama_video._video_authorization(3.0, 1.0, 2.0),
            "updated_at": int(time.time()),
        })
        env = {
            "SD_VIDEO_MODE": "real",
            "SD_VIDEO_ESTIMATED_COST_CNY": "2",
            "SD_VIDEO_RESULT_HOSTS": "result.example.test",
            "SD_VIDEO_MODEL": drama_video.DEFAULT_VIDEO_MODEL,
        }
        with patch.dict(os.environ, env, clear=False):
            with self.assertRaisesRegex(RuntimeError, "poll required"):
                drama_video.run_video_job(
                    workspace,
                    {"confirm_real_video": True, "budget_cny": 3, "timeout_minutes": 1},
                    lambda *_args: None,
                    client=client,
                )
        client.get_task.assert_called_once_with("task-local")

    def test_legacy_submitted_video_without_result_hosts_requires_reconciliation(self) -> None:
        workspace = "video-legacy-hosts"
        drama_video_smoke._prepare_mock_inputs(workspace)
        inputs = drama_video.load_video_inputs(workspace)
        client = _FakeVideoClient()
        drama_video._write_video_submission(workspace, {
            "status": "submitted",
            "input_fingerprint": inputs.fingerprint,
            "provider_fingerprint": drama_video._video_provider_fingerprint(
                client, drama_video.DEFAULT_VIDEO_MODEL
            ),
            "submission_count": 1,
            "task_id": "task-legacy",
            "updated_at": int(time.time()),
        })
        with self.assertRaisesRegex(ValueError, "result-host reconciliation"):
            drama_video.read_video_submission(workspace)

    def test_multimodal_preserves_video_budget_exceeded_terminal_state(self) -> None:
        state = multi.run("video-budget-terminal")
        state["phases"]["real_video"] = {"status": "pending"}
        state["phases"]["video_readiness"] = {"status": "awaiting_real_video_authorization"}
        state["status"] = "awaiting_video_authorization"
        multi._save(state)
        opts = {
            "confirm_real_video": True,
            "confirm_asset_callback_reachable": True,
            "video_budget_cny": 3,
            "video_timeout_seconds": 60,
        }
        result = {
            "status": "budget_exceeded",
            "cost_cny": 4.0,
            "cost_unreported": False,
            "budget_cny": 3.0,
            "network_requests": 1,
        }
        ledger = {"status": "succeeded"}
        with patch(
            "src.drama_multimodal_smoke._video_readiness",
            return_value={"reference_count": 2},
        ), patch(
            "src.drama_multimodal_smoke.run_video_smoke", return_value=result
        ), patch(
            "src.drama_multimodal_smoke.drama_video.read_video_submission",
            return_value=ledger,
        ):
            terminal = multi.run(
                "video-budget-terminal", real_video=True, options=opts
            )
        self.assertEqual(terminal["status"], "budget_exceeded")
        self.assertEqual(terminal["phases"]["real_video"]["status"], "budget_exceeded")

    def test_video_result_host_drift_blocks_before_network(self) -> None:
        workspace = "video-host-drift"
        drama_video_smoke._prepare_mock_inputs(workspace)
        inputs = drama_video.load_video_inputs(workspace)
        client = _FakeVideoClient()
        drama_video._write_video_submission(workspace, {
            "status": "submitted",
            "input_fingerprint": inputs.fingerprint,
            "provider_fingerprint": drama_video._video_provider_fingerprint(
                client, drama_video.DEFAULT_VIDEO_MODEL
            ),
            "result_hosts_fingerprint": sha256_data(["old.example.test"]),
            "submission_count": 1,
            "task_id": "task-one",
            **drama_video._video_authorization(3.0, 1.0, 2.0),
            "updated_at": int(time.time()),
        })
        env = {
            "SD_VIDEO_MODE": "real",
            "SD_VIDEO_ESTIMATED_COST_CNY": "2",
            "SD_VIDEO_RESULT_HOSTS": "new.example.test",
            "SD_VIDEO_MODEL": drama_video.DEFAULT_VIDEO_MODEL,
        }
        with patch.dict(os.environ, env, clear=False):
            with self.assertRaisesRegex(drama_video.DramaVideoProviderError, "allowlist changed"):
                drama_video.run_video_job(
                    workspace,
                    {"confirm_real_video": True, "budget_cny": 3, "timeout_minutes": 1},
                    lambda *_args: None,
                    client=client,
                )
        self.assertEqual((client.uploads, client.submissions, client.polls), (0, 0, 0))

    def test_public_asset_capability_is_durable_and_tamper_evident(self) -> None:
        drama_video_smoke._prepare_mock_inputs("public-capability")
        asset = drama_video.load_video_inputs("public-capability").references[0][2]
        token = drama_video.register_public_asset(asset, expires_at=time.monotonic() + 30)
        data_path, meta_path = drama_video._public_asset_paths(token)
        self.assertTrue(data_path.is_file())
        self.assertTrue(meta_path.is_file())
        self.assertEqual(routes.dispatch("GET", f"/media/drama-assets/{token}")[0], 200)
        probe = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "import hashlib,sys; from pathlib import Path; "
                    "from src import drama_video,paths; "
                    "paths.WORKSPACE_DIR=Path(sys.argv[1]); "
                    "data,kind=drama_video.read_public_asset(sys.argv[2]); "
                    "print(kind,hashlib.sha256(data).hexdigest())"
                ),
                str(multi.paths.WORKSPACE_DIR),
                token,
            ],
            cwd=str(Path(__file__).resolve().parents[1]),
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertIn("image/png", probe.stdout)
        data_path.write_bytes(data_path.read_bytes() + b"tamper")
        with self.assertRaises(FileNotFoundError):
            drama_video.read_public_asset(token)

    def test_public_asset_store_rejects_directory_symlink(self) -> None:
        drama_video_smoke._prepare_mock_inputs("public-store-link")
        asset = drama_video.load_video_inputs("public-store-link").references[0][2]
        outside = multi.paths.WORKSPACE_DIR / "outside-store"
        outside.mkdir()
        store = multi.paths.WORKSPACE_DIR / drama_video.PUBLIC_ASSET_STORE_DIRNAME
        store.symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "regular directory"):
            drama_video.register_public_asset(asset, expires_at=time.monotonic() + 30)

    def test_real_image_persist_writes_private_staging_before_public_schema(self) -> None:
        self._prepare_text_only("image-persist-staging")
        sheet = read_json(character_paths("image-persist-staging").sheet_path)
        character = DramaCharacter(**sheet["characters"][0])
        target = (
            multi.paths.workspace_root("image-persist-staging")
            / "logs/drama_multimodal_images/c001/attempt_1_abcdefghijklmnop.png"
        )
        record = ai_draw_client._persist_image(
            "image-persist-staging",
            character,
            multi._PNG_1X1,
            content_type="image/png",
            suffix=".png",
            generated_by="provider/model",
            prompt="private prompt",
            season_no=1,
            requested_model="provider/model",
            requested_size="1024x1024",
            width=1,
            height=1,
            output_path=target,
        )
        self.assertTrue(target.is_file())
        self.assertTrue(record["path"].startswith("logs/drama_multimodal_images/"))

    def test_png_rejects_missing_palette_and_unknown_critical_chunk(self) -> None:
        def chunk(kind: bytes, payload: bytes) -> bytes:
            return (
                len(payload).to_bytes(4, "big")
                + kind
                + payload
                + (zlib.crc32(kind + payload) & 0xFFFFFFFF).to_bytes(4, "big")
            )

        signature = b"\x89PNG\r\n\x1a\n"
        indexed_ihdr = (
            (1).to_bytes(4, "big") + (1).to_bytes(4, "big") + bytes([8, 3, 0, 0, 0])
        )
        indexed = (
            signature
            + chunk(b"IHDR", indexed_ihdr)
            + chunk(b"IDAT", zlib.compress(b"\x00\x00"))
            + chunk(b"IEND", b"")
        )
        with self.assertRaisesRegex(ValueError, "missing PLTE"):
            ai_draw_client._validate_png(indexed)

        rgba_ihdr = (
            (1).to_bytes(4, "big") + (1).to_bytes(4, "big") + bytes([8, 6, 0, 0, 0])
        )
        unknown_critical = (
            signature
            + chunk(b"IHDR", rgba_ihdr)
            + chunk(b"ABCD", b"")
            + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\x00"))
            + chunk(b"IEND", b"")
        )
        with self.assertRaisesRegex(ValueError, "unsupported critical"):
            ai_draw_client._validate_png(unknown_critical)

    def test_web_exposes_mode_only_and_authorizes_each_real_station_call(self) -> None:
        self._make_drama_workspace("web-real-mode", "推理")

        def config(task: str):
            return {"model": "provider/model" if task == "drama_hooks" else "mock"}

        with patch("src.web.routes.get_model_config", side_effect=config):
            status, _content_type, body = routes.dispatch(
                "GET", "/api/workspace/web-real-mode/drama/progress"
            )
        self.assertEqual(status, 200)
        payload = json.loads(body)
        self.assertTrue(payload["real_text_steps"]["drama-hooks"])
        self.assertFalse(payload["real_text_steps"]["drama-plan"])
        self.assertNotIn("provider/model", body.decode("utf-8"))
        source = static.JS_DASHBOARD
        for step in (
            "drama-plan",
            "drama-hooks",
            "drama-storyboard",
            "drama-characters",
            "drama-review-assemble",
        ):
            self.assertIn(f'dramaGenerationPayload("{step}"', source)
        self.assertIn("out.confirm_real_text = true", source)
        self.assertIn("out.confirm_upstream_status_and_billing_checked = true", source)
        with patch("src.web.routes.get_model_config", return_value={"model": "provider/model"}):
            error, validated = routes._validated_drama_params("drama-hooks", {
                "episode_no": 1,
                "confirm_real_text": True,
                "budget_cny": 10,
                "timeout_minutes": 10,
            })
        self.assertIsNone(error)
        self.assertEqual(validated["confirm_real_text"], True)
        self.assertEqual(validated["budget_cny"], 10.0)
        self.assertEqual(validated["timeout_minutes"], 10.0)
