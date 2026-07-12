"""Shared setup helpers for drama-related tests."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from src import drama_planner, paths
from src.drama_schemas import episode_paths
from src.cli_workspace import init_workspace
from src.web import wizard


class DramaTestBase(unittest.TestCase):
    """Isolate workspace state and provide minimal drama workspace setup."""

    def setUp(self) -> None:
        os.environ["OPENAI_MODEL"] = "mock"
        self._tmp = tempfile.TemporaryDirectory()
        self._saved_ws_dir = paths.WORKSPACE_DIR
        self._saved_env = os.environ.get("WORKSPACE_NAME")
        os.environ.pop("WORKSPACE_NAME", None)
        paths.WORKSPACE_DIR = Path(self._tmp.name)

    def tearDown(self) -> None:
        paths.WORKSPACE_DIR = self._saved_ws_dir
        if self._saved_env is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._saved_env
        self._tmp.cleanup()

    def _make_drama_workspace(
        self,
        name: str,
        track: str = "霸总",
        *,
        snapshot: bool = True,
        episode_count: int = 12,
        episode_duration_seconds: int = 60,
    ) -> None:
        """Create a drama workspace with wizard input and optional snapshot."""

        init_workspace(name, type="drama")
        data_dir = paths.WORKSPACE_DIR / name / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "wizard_input.json").write_text(
            json.dumps(
                {
                    "workspace": name,
                    "topic": "test topic",
                    "track": track,
                    "episode_count": episode_count,
                    "episode_duration_seconds": episode_duration_seconds,
                    "schema_version": 1,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        if snapshot:
            wizard._snapshot_creation_standard(name)

    def _write_setup(self, name: str, *, hook: bool = True, episode_no: int = 1) -> Path:
        """Persist a station-1 setup fixture, optionally with selected hook."""

        p = episode_paths(name, episode_no=episode_no).setup_path
        p.parent.mkdir(parents=True, exist_ok=True)
        setup = drama_planner.run(name, episode_no=episode_no)
        if hook:
            setup["hook"] = {"type": "反差钩", "content": "测试钩子"}
        p.write_text(json.dumps(setup, ensure_ascii=False), encoding="utf-8")
        return p
