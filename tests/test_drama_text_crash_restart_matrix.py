"""Production-backed five-station text crash/restart behavior matrix."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src import paths
from src.paid_recovery_states import (
    TEXT_ATTEMPT_STATUSES,
    TEXT_CANONICAL_RECOVERY_STATUSES,
    TEXT_RECONCILIATION_REQUIRED_STATUSES,
)
from src.web import jobs
from src.web.workspace_ctx import use_workspace
from tests.support.drama_text_crash_driver import (
    CRASH_EXIT,
    MODEL_CONFIG,
    TEXT_STATIONS,
    bind_and_write_canonical,
    mutate_station_input,
    prepare_workspace,
    station_result,
)


ROOT = Path(__file__).resolve().parents[1]
DRIVER = ROOT / "tests" / "support" / "drama_text_crash_driver.py"


class DramaTextProductionStateMatrixTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.saved_workspace_dir = paths.WORKSPACE_DIR
        self.addCleanup(setattr, paths, "WORKSPACE_DIR", self.saved_workspace_dir)
        self.workspace_root = Path(self.temporary.name) / "workspaces"
        self.workspace_root.mkdir()
        paths.WORKSPACE_DIR = self.workspace_root

    def _workspace(self, suffix: str) -> str:
        return "text-matrix-" + suffix.replace("drama-", "").replace("_", "-")

    def _create_attempt_at_status(
        self,
        workspace: str,
        step: str,
        status: str,
    ) -> dict:
        prepare_workspace(self.workspace_root, workspace)
        result = station_result(step)
        with use_workspace(workspace), patch(
            "src.config.get_model_config", return_value=MODEL_CONFIG
        ):
            if status == "submitting":
                token = jobs._begin_drama_text_attempt(step, {}, 1)
                self.assertIsNotNone(token)
            elif status == "failed_after_submission":
                attempted_provider = Mock(side_effect=RuntimeError("synthetic failure"))
                with self.assertRaisesRegex(RuntimeError, "synthetic failure"):
                    jobs._call_drama_text_model(step, {}, 1, attempted_provider)
                attempted_provider.assert_called_once_with()
            else:
                attempted_provider = Mock(return_value=result)
                returned, token = jobs._call_drama_text_model(
                    step, {}, 1, attempted_provider
                )
                self.assertIsNotNone(token)
                attempted_provider.assert_called_once_with()
                if status in TEXT_CANONICAL_RECOVERY_STATUSES:
                    bind_and_write_canonical(workspace, step, token, returned)
                if status != "response_received":
                    jobs._mark_drama_text_attempt(token, status)
            persisted = jobs._load_drama_text_attempts(workspace)
            self.assertEqual(
                persisted["attempts"][f"{step}:1"]["status"], status
            )
        return result

    def test_all_five_stations_execute_every_durable_status_without_automatic_provider(self) -> None:
        observed: set[str] = set()
        for station in TEXT_STATIONS:
            for status in TEXT_ATTEMPT_STATUSES:
                with self.subTest(station=station, status=status):
                    workspace = self._workspace(f"{station}-{status}")
                    expected = self._create_attempt_at_status(
                        workspace, station, status
                    )
                    second_provider = Mock(side_effect=AssertionError("provider called on recovery"))
                    with use_workspace(workspace), patch(
                        "src.config.get_model_config", return_value=MODEL_CONFIG
                    ):
                        persisted = jobs._load_drama_text_attempts(workspace)
                        self.assertEqual(
                            persisted["attempts"][f"{station}:1"]["status"], status
                        )
                        if status in TEXT_CANONICAL_RECOVERY_STATUSES:
                            recovered, _ = jobs._call_drama_text_model(
                                station, {}, 1, second_provider
                            )
                            self.assertEqual(recovered, expected)
                        else:
                            self.assertIn(status, TEXT_RECONCILIATION_REQUIRED_STATUSES)
                            with self.assertRaisesRegex(ValueError, "reconciliation"):
                                jobs._call_drama_text_model(
                                    station, {}, 1, second_provider
                                )
                    second_provider.assert_not_called()
                    observed.add(status)
        self.assertEqual(observed, set(TEXT_ATTEMPT_STATUSES))

    def test_unknown_status_is_rejected_by_production_loader_before_provider(self) -> None:
        for station in TEXT_STATIONS:
            with self.subTest(station=station):
                workspace = self._workspace(f"{station}-unknown")
                prepare_workspace(self.workspace_root, workspace)
                provider = Mock(side_effect=AssertionError("provider called with invalid ledger"))
                with use_workspace(workspace), patch(
                    "src.config.get_model_config", return_value=MODEL_CONFIG
                ):
                    token = jobs._begin_drama_text_attempt(station, {}, 1)
                    self.assertIsNotNone(token)
                    jobs._mark_drama_text_attempt(token, "unknown")
                    with self.assertRaisesRegex(ValueError, "ledger row is invalid"):
                        jobs._call_drama_text_model(station, {}, 1, provider)
                provider.assert_not_called()

    def test_provider_and_input_drift_fail_closed_before_provider_for_every_station(self) -> None:
        for station in TEXT_STATIONS:
            for drift in ("model", "endpoint", "account", "input"):
                with self.subTest(station=station, drift=drift):
                    workspace = self._workspace(f"{station}-{drift}-drift")
                    prepare_workspace(self.workspace_root, workspace)
                    provider = Mock(side_effect=AssertionError("provider called after drift"))
                    with use_workspace(workspace), patch(
                        "src.config.get_model_config", return_value=MODEL_CONFIG
                    ):
                        token = jobs._begin_drama_text_attempt(station, {}, 1)
                        self.assertIsNotNone(token)
                    if drift == "input":
                        mutate_station_input(workspace, station)
                        current_config = MODEL_CONFIG
                    elif drift == "model":
                        current_config = {**MODEL_CONFIG, "model": "test-provider/other-model"}
                    elif drift == "endpoint":
                        current_config = {**MODEL_CONFIG, "base_url": "https://other-provider.invalid/v1"}
                    else:
                        current_config = {**MODEL_CONFIG, "api_key": "different-test-token"}
                    with use_workspace(workspace), patch(
                        "src.config.get_model_config", return_value=current_config
                    ):
                        with self.assertRaisesRegex(
                            ValueError, "provider or input identity changed"
                        ):
                            jobs._call_drama_text_model(station, {}, 1, provider)
                    provider.assert_not_called()

    def test_workspace_escape_is_rejected_before_any_write(self) -> None:
        outside = self.workspace_root.parent / "escape"
        with self.assertRaisesRegex(ValueError, "workspace name"):
            prepare_workspace(self.workspace_root, "../escape")
        self.assertFalse(outside.exists())


class DramaTextCrossProcessCrashRestartTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.workspace_root = Path(self.temporary.name) / "workspaces"
        self.workspace_root.mkdir()
        (self.workspace_root / ".dragon-raja-text-crash-matrix").write_text(
            "iter104\n", encoding="utf-8"
        )
        self.tmpdir = Path(self.temporary.name) / "tmp"
        self.tmpdir.mkdir()

    def _environment(self) -> dict[str, str]:
        return {
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": self.temporary.name,
            "LANG": "C.UTF-8",
            "TMPDIR": str(self.tmpdir),
            "DRAGON_RAJA_SKIP_DOTENV": "1",
            "PYTHON_DOTENV_DISABLED": "1",
            "OPENAI_MODEL": "mock",
            "DRAMA_MODEL": "mock",
            "LITELLM_LOCAL_MODEL_COST_MAP": "true",
            "PYTHONPYCACHEPREFIX": str(self.tmpdir / "pycache"),
        }

    def _run(
        self,
        mode: str,
        workspace: str,
        station: str,
        marker: Path,
        nonce: Path,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(DRIVER),
                mode,
                "--workspace-root", str(self.workspace_root),
                "--workspace", workspace,
                "--step", station,
                "--marker", str(marker),
                "--provider-nonce", str(nonce),
            ],
            cwd=ROOT,
            env=self._environment(),
            text=True,
            capture_output=True,
            timeout=30,
            check=False,
        )

    def test_durable_submitting_crash_restarts_fresh_and_never_calls_provider(self) -> None:
        for station in TEXT_STATIONS:
            with self.subTest(station=station):
                slug = station.replace("drama-", "")
                workspace = f"text-process-{slug}"
                crash_marker = Path(self.temporary.name) / f"{slug}-crash.json"
                resume_marker = Path(self.temporary.name) / f"{slug}-resume.json"
                provider_nonce = Path(self.temporary.name) / f"{slug}-provider.nonce"
                crashed = self._run(
                    "crash", workspace, station, crash_marker, provider_nonce
                )
                self.assertEqual(crashed.returncode, CRASH_EXIT, crashed.stderr)
                crash_facts = json.loads(crash_marker.read_text(encoding="utf-8"))
                self.assertEqual(crash_facts["durable_status"], "submitting")
                self.assertFalse(provider_nonce.exists())

                resumed = self._run(
                    "resume", workspace, station, resume_marker, provider_nonce
                )
                self.assertEqual(resumed.returncode, 0, resumed.stderr)
                resume_facts = json.loads(resume_marker.read_text(encoding="utf-8"))
                self.assertNotEqual(crash_facts["pid"], resume_facts["pid"])
                self.assertNotEqual(
                    crash_facts["import_nonce"], resume_facts["import_nonce"]
                )
                self.assertEqual(resume_facts["durable_status"], "submitting")
                self.assertTrue(resume_facts["reconciliation_required"])
                self.assertFalse(resume_facts["provider_called"])
                self.assertFalse(provider_nonce.exists())


if __name__ == "__main__":
    unittest.main()
