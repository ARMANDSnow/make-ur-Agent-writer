"""iter 026: POST/PUT route coverage + method-mismatch handling."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from src import paths
from src.cli_workspace import init_workspace
from src.web import jobs, routes
from src.web import workspace_meta


def _stub_workspace(root: Path, name: str) -> None:
    ws = root / name
    for sub in ("小说txt", "data", "outputs", "logs"):
        (ws / sub).mkdir(parents=True)
    (ws / "marker.txt").write_text("hi", encoding="utf-8")


class RoutesPostTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["OPENAI_MODEL"] = "mock"
        self._tmp = tempfile.TemporaryDirectory()
        self._saved_ws_dir = paths.WORKSPACE_DIR
        self._saved_env = os.environ.get("WORKSPACE_NAME")
        os.environ.pop("WORKSPACE_NAME", None)
        paths.WORKSPACE_DIR = Path(self._tmp.name)
        _stub_workspace(paths.WORKSPACE_DIR, "alpha")
        jobs.reset_for_tests()

    def tearDown(self) -> None:
        paths.WORKSPACE_DIR = self._saved_ws_dir
        if self._saved_env is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._saved_env
        jobs.reset_for_tests()
        self._tmp.cleanup()

    def _init_drama(
        self,
        name: str = "drama",
        *,
        track: str = "霸总",
        snapshot: bool = True,
        setup: bool = False,
    ) -> None:
        init_workspace(name, type="drama")
        (paths.WORKSPACE_DIR / name / "data" / "wizard_input.json").write_text(
            json.dumps(
                {
                    "workspace": name,
                    "topic": "test topic",
                    "track": track,
                    "episode_count": 12,
                    "episode_duration_seconds": 60,
                    "schema_version": 1,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        if snapshot:
            (paths.WORKSPACE_DIR / name / "data" / "creation_standard.snapshot.md").write_text(
                "# snapshot\n\n3 秒法则\n\n60 秒的内部节奏\n",
                encoding="utf-8",
            )
        if setup:
            setup_path = paths.WORKSPACE_DIR / name / "outputs" / "episodes" / "episode_01.setup.json"
            setup_path.parent.mkdir(parents=True, exist_ok=True)
            setup_path.write_text(
                json.dumps(
                    {
                        "episode_no": 1,
                        "season_no": 1,
                        "title": "t",
                        "logline": "old",
                        "track": track,
                        "target_duration_seconds": 60,
                        "core_setup": {
                            "protagonist": "p",
                            "antagonist": "a",
                            "emotional_hook": "e",
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

    def test_post_run_happy_returns_202_and_job_id(self) -> None:
        status, _ct, body = routes.dispatch(
            "POST",
            "/api/workspace/alpha/run",
            json.dumps({"step": "normalize"}).encode(),
        )
        self.assertEqual(status, 202)
        data = json.loads(body)
        self.assertIn("job_id", data)
        self.assertEqual(len(data["job_id"]), 32)

    def test_post_run_invalid_workspace_400(self) -> None:
        status, _ct, body = routes.dispatch(
            "POST",
            "/api/workspace/-illegal-/run",
            json.dumps({"step": "normalize"}).encode(),
        )
        self.assertEqual(status, 400)

    def test_post_run_unknown_workspace_404(self) -> None:
        status, _ct, body = routes.dispatch(
            "POST",
            "/api/workspace/no_such_ws/run",
            json.dumps({"step": "normalize"}).encode(),
        )
        self.assertEqual(status, 404)

    def test_post_run_drama_workspace_returns_400_with_hint(self) -> None:
        workspace_meta.write("alpha", type="drama", created_at="2026-06-03T00:00:00+00:00")
        status, _ct, body = routes.dispatch(
            "POST",
            "/api/workspace/alpha/run",
            json.dumps({"step": "normalize"}).encode(),
        )
        self.assertEqual(status, 400)
        data = json.loads(body)
        self.assertIn("drama workspace", data["error"])
        self.assertIn("drama 模块已可用", data["hint"])

    def test_api_drama_progress_returns_four_station_shape(self) -> None:
        self._init_drama("drama")
        status, _ct, body = routes.dispatch("GET", "/api/workspace/drama/drama/progress")
        self.assertEqual(status, 200, body.decode())
        data = json.loads(body)
        self.assertEqual([s["id"] for s in data["stations"]], ["setup", "hook", "storyboard", "characters"])
        self.assertEqual(data["stations"][0]["status"], "todo")

    def test_api_drama_progress_rejects_novel_workspace(self) -> None:
        status, _ct, body = routes.dispatch("GET", "/api/workspace/alpha/drama/progress")
        self.assertEqual(status, 400)
        self.assertIn("drama-only", json.loads(body)["error"])

    def test_api_drama_plan_creates_setup_file(self) -> None:
        self._init_drama("drama", track="霸总")
        status, _ct, body = routes.dispatch("POST", "/api/workspace/drama/drama/plan", b"{}")
        self.assertEqual(status, 200, body.decode())
        data = json.loads(body)
        self.assertEqual(data["track"], "霸总")
        setup_path = paths.WORKSPACE_DIR / "drama" / "outputs" / "episodes" / "episode_01.setup.json"
        self.assertTrue(setup_path.is_file())

    def test_api_drama_plan_missing_snapshot_returns_500(self) -> None:
        self._init_drama("drama", snapshot=False)
        status, _ct, body = routes.dispatch("POST", "/api/workspace/drama/drama/plan", b"{}")
        self.assertEqual(status, 500)
        self.assertIn("creation_standard.snapshot", json.loads(body)["error"])

    def test_api_drama_hooks_requires_setup_first(self) -> None:
        self._init_drama("drama")
        status, _ct, body = routes.dispatch("POST", "/api/workspace/drama/drama/hooks", b"{}")
        self.assertEqual(status, 500)
        self.assertIn("station 1", json.loads(body)["error"])

    def test_api_drama_hooks_returns_three_candidates_after_setup(self) -> None:
        self._init_drama("drama", setup=True)
        status, _ct, body = routes.dispatch("POST", "/api/workspace/drama/drama/hooks", b"{}")
        self.assertEqual(status, 200, body.decode())
        self.assertEqual(len(json.loads(body)["hooks"]), 3)

    def test_api_drama_setup_save_merges_core_fields(self) -> None:
        self._init_drama("drama", setup=True)
        payload = {
            "logline": "new",
            "protagonist": "new p",
            "antagonist": "new a",
            "emotional_hook": "new e",
        }
        status, _ct, body = routes.dispatch(
            "PUT",
            "/api/workspace/drama/drama/setup",
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        )
        self.assertEqual(status, 200, body.decode())
        setup = json.loads(
            (paths.WORKSPACE_DIR / "drama" / "outputs" / "episodes" / "episode_01.setup.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(setup["logline"], "new")
        self.assertEqual(setup["core_setup"]["protagonist"], "new p")

    def test_api_drama_setup_save_hook_marks_progress_done(self) -> None:
        self._init_drama("drama", setup=True)
        status, _ct, body = routes.dispatch(
            "PUT",
            "/api/workspace/drama/drama/setup",
            json.dumps({"hook": {"type": "情绪钩", "content": "x"}}, ensure_ascii=False).encode("utf-8"),
        )
        self.assertEqual(status, 200, body.decode())
        status, _ct, body = routes.dispatch("GET", "/api/workspace/drama/drama/progress")
        self.assertEqual(json.loads(body)["stations"][1]["status"], "done")

    def test_api_drama_setup_save_rejects_invalid_hook(self) -> None:
        self._init_drama("drama", setup=True)
        status, _ct, body = routes.dispatch(
            "PUT",
            "/api/workspace/drama/drama/setup",
            json.dumps({"hook": "bad"}).encode("utf-8"),
        )
        self.assertEqual(status, 400)
        self.assertIn("hook", json.loads(body)["error"])

    def test_api_drama_setup_save_requires_station_one(self) -> None:
        self._init_drama("drama")
        status, _ct, body = routes.dispatch(
            "PUT",
            "/api/workspace/drama/drama/setup",
            json.dumps({"protagonist": "x"}).encode("utf-8"),
        )
        self.assertEqual(status, 400)
        self.assertIn("station 1", json.loads(body)["error"])

    def test_put_on_get_route_returns_405(self) -> None:
        status, _ct, body = routes.dispatch("PUT", "/api/workspaces")
        self.assertEqual(status, 405)
        self.assertIn("method PUT not allowed", json.loads(body)["error"])

    def test_post_on_get_only_route_returns_405(self) -> None:
        status, _ct, body = routes.dispatch("POST", "/api/workspace/alpha/status")
        self.assertEqual(status, 405)

    def test_delete_workspace_happy_path_moves_to_trash(self) -> None:
        src = paths.WORKSPACE_DIR / "alpha"
        self.assertTrue(src.is_dir())
        status, _ct, body = routes.dispatch(
            "POST",
            "/api/workspace/alpha/delete",
            json.dumps({"confirm": "alpha"}).encode(),
        )
        self.assertEqual(status, 200, body.decode())
        data = json.loads(body)
        self.assertIn("trashed_to", data)
        self.assertFalse(src.is_dir())
        trash_entries = list((paths.WORKSPACE_DIR / "_trash").iterdir())
        self.assertEqual(len(trash_entries), 1)
        self.assertTrue(trash_entries[0].name.startswith("alpha__"))

    def test_delete_workspace_requires_confirm_match(self) -> None:
        status, _ct, body = routes.dispatch(
            "POST",
            "/api/workspace/alpha/delete",
            json.dumps({"confirm": "wrong"}).encode(),
        )
        self.assertEqual(status, 400)
        self.assertIn("confirm", json.loads(body)["error"])
        self.assertTrue((paths.WORKSPACE_DIR / "alpha").is_dir())

    def test_delete_workspace_unknown_404(self) -> None:
        status, _ct, _body = routes.dispatch(
            "POST",
            "/api/workspace/never-existed/delete",
            json.dumps({"confirm": "never-existed"}).encode(),
        )
        self.assertEqual(status, 404)

    def test_delete_workspace_rejects_invalid_name(self) -> None:
        status, _ct, _body = routes.dispatch(
            "POST",
            "/api/workspace/-bad-/delete",
            json.dumps({"confirm": "-bad-"}).encode(),
        )
        self.assertEqual(status, 400)

    def test_delete_workspace_rejects_running_job(self) -> None:
        with jobs.workspace_reserved("alpha"):
            status, _ct, body = routes.dispatch(
                "POST",
                "/api/workspace/alpha/delete",
                json.dumps({"confirm": "alpha"}).encode(),
            )
        self.assertEqual(status, 409)
        data = json.loads(body)
        self.assertEqual(data["running_job_id"], "__reserved_delete__")
        self.assertTrue((paths.WORKSPACE_DIR / "alpha").is_dir())

    def test_trash_list_returns_entries(self) -> None:
        routes.dispatch(
            "POST",
            "/api/workspace/alpha/delete",
            json.dumps({"confirm": "alpha"}).encode(),
        )
        status, _ct, body = routes.dispatch("GET", "/api/trash")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(len(data["entries"]), 1)
        self.assertEqual(data["entries"][0]["original_name"], "alpha")

    def test_trash_restore_returns_workspace(self) -> None:
        routes.dispatch(
            "POST",
            "/api/workspace/alpha/delete",
            json.dumps({"confirm": "alpha"}).encode(),
        )
        entries = json.loads(routes.dispatch("GET", "/api/trash")[2])["entries"]
        entry = entries[0]["entry"]
        status, _ct, body = routes.dispatch("POST", f"/api/trash/{entry}/restore")
        self.assertEqual(status, 200, body.decode())
        self.assertTrue((paths.WORKSPACE_DIR / "alpha" / "marker.txt").exists())

    def test_trash_restore_preserves_drama_workspace_meta(self) -> None:
        workspace_meta.write("alpha", type="drama", created_at="2026-06-03T00:00:00+00:00")
        routes.dispatch(
            "POST",
            "/api/workspace/alpha/delete",
            json.dumps({"confirm": "alpha"}).encode(),
        )
        entries = json.loads(routes.dispatch("GET", "/api/trash")[2])["entries"]
        entry = entries[0]["entry"]
        status, _ct, body = routes.dispatch("POST", f"/api/trash/{entry}/restore")
        self.assertEqual(status, 200, body.decode())
        self.assertEqual(workspace_meta.read("alpha")["type"], "drama")

    def test_trash_restore_rejects_newline_entry(self) -> None:
        status, _ct, body = routes.dispatch(
            "POST",
            "/api/trash/alpha__20260101_120000%0A/restore",
        )
        self.assertEqual(status, 400)
        self.assertIn("invalid trash entry", json.loads(body)["error"])

    def test_trash_purge_requires_confirm(self) -> None:
        routes.dispatch(
            "POST",
            "/api/workspace/alpha/delete",
            json.dumps({"confirm": "alpha"}).encode(),
        )
        entries = json.loads(routes.dispatch("GET", "/api/trash")[2])["entries"]
        entry = entries[0]["entry"]
        status, _ct, body = routes.dispatch(
            "POST",
            f"/api/trash/{entry}/purge",
            json.dumps({"confirm": "wrong"}).encode(),
        )
        self.assertEqual(status, 400)
        self.assertIn("confirm", json.loads(body)["error"])
        self.assertTrue((paths.WORKSPACE_DIR / "_trash" / entry).exists())

    def test_trash_purge_removes_entry(self) -> None:
        routes.dispatch(
            "POST",
            "/api/workspace/alpha/delete",
            json.dumps({"confirm": "alpha"}).encode(),
        )
        entries = json.loads(routes.dispatch("GET", "/api/trash")[2])["entries"]
        entry = entries[0]["entry"]
        status, _ct, body = routes.dispatch(
            "POST",
            f"/api/trash/{entry}/purge",
            json.dumps({"confirm": entry}).encode(),
        )
        self.assertEqual(status, 200, body.decode())
        self.assertFalse((paths.WORKSPACE_DIR / "_trash" / entry).exists())

    def test_delete_vs_start_job_race_resolved(self) -> None:
        done = threading.Event()

        def blocking_handler(params, progress_cb):
            done.wait(timeout=5)
            return {"status": "succeeded"}

        barrier = threading.Barrier(2)
        results = {"delete_status": None, "start_error": None}

        def delete_worker() -> None:
            barrier.wait()
            status, _ct, _body = routes.dispatch(
                "POST",
                "/api/workspace/alpha/delete",
                json.dumps({"confirm": "alpha"}).encode(),
            )
            results["delete_status"] = status

        def start_worker() -> None:
            barrier.wait()
            try:
                jobs.start_job("alpha", "normalize", {})
            except RuntimeError as exc:
                results["start_error"] = str(exc)

        with patch.dict(jobs.STEP_HANDLERS, {"normalize": blocking_handler}):
            t1 = threading.Thread(target=delete_worker)
            t2 = threading.Thread(target=start_worker)
            t1.start()
            t2.start()
            t1.join(timeout=5)
            t2.join(timeout=5)
            done.set()
            for _ in range(20):
                if not jobs.workspace_running_job("alpha"):
                    break
                time.sleep(0.01)

        if results["delete_status"] == 200:
            self.assertTrue(
                "workspace_busy" in (results["start_error"] or "")
                or "workspace_not_found" in (results["start_error"] or ""),
                results,
            )
        else:
            self.assertEqual(results["delete_status"], 409)
            self.assertIsNone(results["start_error"])

    def test_run_after_delete_race_does_not_recreate_workspace(self) -> None:
        status, _ct, _body = routes.dispatch(
            "POST",
            "/api/workspace/alpha/delete",
            json.dumps({"confirm": "alpha"}).encode(),
        )
        self.assertEqual(status, 200)
        self.assertFalse((paths.WORKSPACE_DIR / "alpha").exists())

        with patch("src.web.routes._workspace_exists", return_value=True):
            status, _ct, body = routes.dispatch(
                "POST",
                "/api/workspace/alpha/run",
                json.dumps({"step": "normalize"}).encode(),
            )
        self.assertEqual(status, 404, body.decode())
        self.assertFalse((paths.WORKSPACE_DIR / "alpha").exists())


if __name__ == "__main__":
    unittest.main()
