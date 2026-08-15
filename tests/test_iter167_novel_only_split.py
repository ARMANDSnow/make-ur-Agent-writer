from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import main
from src import paths
from src import cli_workspace
from src.cli_workspace import init_workspace, list_workspaces
from src.web import jobs, routes, static, templates, trash, workspace_meta
from scripts import check_novel_only_boundary as boundary


class NovelOnlySplitTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._old_workspace_dir = paths.WORKSPACE_DIR
        paths.WORKSPACE_DIR = Path(self._tmp.name) / "workspaces"
        paths.WORKSPACE_DIR.mkdir()
        routes._clear_overview_cache()

    def tearDown(self) -> None:
        jobs.reset_for_tests()
        routes._clear_overview_cache()
        paths.WORKSPACE_DIR = self._old_workspace_dir
        self._tmp.cleanup()

    def _legacy_drama_workspace(self, name: str = "legacy_show") -> Path:
        root = paths.WORKSPACE_DIR / name
        (root / "data").mkdir(parents=True)
        (root / "outputs").mkdir()
        (root / "logs").mkdir()
        (root / "小说txt").mkdir()
        (root / "data" / "workspace.json").write_text(
            json.dumps({"type": "drama", "schema_version": 2}, ensure_ascii=False),
            encoding="utf-8",
        )
        return root

    def test_short_drama_entries_are_native_disabled_controls(self) -> None:
        pages = (templates.render_landing(), templates.render_index([]))
        for html in pages:
            self.assertIn("短剧模块暂未开放", html)
            self.assertIn("disabled", html)
            self.assertIn('aria-disabled="true"', html)
            self.assertNotIn("?type=drama", html)
        self.assertNotIn("?type=drama", static.JS_DASHBOARD)
        self.assertNotIn("?type=drama", static.JS_WIZARD)
        wizard_html = templates.render_wizard()
        self.assertEqual(wizard_html.count('id="panel-progress"'), 1)
        self.assertIn('<section class="card" id="panel-progress" hidden>', wizard_html)

    def test_removed_routes_and_cli_command_are_absent(self) -> None:
        init_workspace("novel_one")
        for method, path in (
            ("GET", "/api/workspace/novel_one/drama/progress"),
            ("GET", "/api/workspace/novel_one/character-ref/c001/ref.png"),
            ("POST", "/api/wizard/drama-start"),
            ("GET", "/media/drama-assets/novel_one/file.png"),
        ):
            status, _content_type, _body = routes.dispatch(method, path)
            self.assertEqual(status, 404, (method, path))
        help_result = subprocess.run(
            [sys.executable, "main.py", "--help"],
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertNotIn("drama-project-archive", help_result.stdout)

    def test_legacy_type_is_recognized_but_hidden_and_fail_closed(self) -> None:
        root = self._legacy_drama_workspace()
        before = (root / "data" / "workspace.json").read_bytes()
        self.assertEqual(workspace_meta.read("legacy_show")["type"], "drama")
        self.assertNotIn("legacy_show", list_workspaces())
        status, _ct, body = routes.dispatch("GET", "/api/workspaces")
        self.assertEqual(status, 200)
        self.assertNotIn("legacy_show", json.loads(body)["workspaces"])
        for method, path in (
            ("GET", "/w/legacy_show/"),
            ("GET", "/api/workspace/legacy_show/status"),
            ("POST", "/api/workspace/legacy_show/delete"),
            ("POST", "/api/workspace/legacy_show/run"),
            ("GET", "/api/workspace/legacy_show/logs/tail"),
        ):
            payload = b"not-json" if path.endswith("/run") else b'{"confirm":"legacy_show"}' if method == "POST" else b""
            result = routes.dispatch(method, path, payload)
            self.assertEqual(result[0], 404, (method, path, result[2]))
        self.assertEqual((root / "data" / "workspace.json").read_bytes(), before)
        self.assertTrue(root.is_dir())

    def test_legacy_drama_trash_entry_is_hidden_and_immutable(self) -> None:
        entry = "legacy_show__20260815_120000"
        root = paths.WORKSPACE_DIR / "_trash" / entry
        (root / "data").mkdir(parents=True)
        metadata = json.dumps({"type": "drama", "schema_version": 2}).encode("utf-8")
        (root / "data" / "workspace.json").write_bytes(metadata)
        marker = root / "marker.bin"
        marker.write_bytes(b"do-not-touch")

        status, _ct, body = routes.dispatch("GET", "/api/trash")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(body)["entries"], [])
        for path, payload in (
            (f"/api/trash/{entry}/restore", b""),
            (f"/api/trash/{entry}/purge", json.dumps({"confirm": entry}).encode()),
        ):
            status, _ct, _body = routes.dispatch("POST", path, payload)
            self.assertEqual(status, 404)
            self.assertEqual(json.loads(_body)["error"], "entry_not_found")
        self.assertEqual((root / "data" / "workspace.json").read_bytes(), metadata)
        self.assertEqual(marker.read_bytes(), b"do-not-touch")

    def test_trash_swap_cannot_restore_or_purge_replacement(self) -> None:
        for operation in (trash.restore_trash_entry, trash.purge_trash_entry):
            with self.subTest(operation=operation.__name__):
                suffix = "restore" if operation is trash.restore_trash_entry else "purge"
                entry = f"novel_{suffix}__20260815_120000"
                replacement = f"hidden_{suffix}__20260815_120000"
                root = paths.WORKSPACE_DIR / "_trash"
                novel = root / entry
                hidden = root / replacement
                (novel / "data").mkdir(parents=True)
                (hidden / "data").mkdir(parents=True)
                (novel / "data" / "workspace.json").write_text(
                    json.dumps({"type": "novel", "schema_version": 2, "creation_mode": "continuation"}),
                    encoding="utf-8",
                )
                (hidden / "data" / "workspace.json").write_text(
                    json.dumps({"type": "drama", "schema_version": 2}), encoding="utf-8"
                )
                (novel / "marker").write_text("novel", encoding="utf-8")
                (hidden / "marker").write_text("hidden", encoding="utf-8")
                parked = root / f"parked_{suffix}"
                real_identity = trash._entry_supported_novel_identity

                def swap_after_check(name: str):
                    identity = real_identity(name)
                    novel.rename(parked)
                    hidden.rename(novel)
                    return identity

                with mock.patch.object(
                    trash, "_entry_supported_novel_identity", side_effect=swap_after_check
                ):
                    ok, reason = operation(entry)
                self.assertFalse(ok)
                self.assertEqual(reason, "entry_not_found")
                self.assertEqual((novel / "marker").read_text(encoding="utf-8"), "hidden")
                self.assertEqual((parked / "marker").read_text(encoding="utf-8"), "novel")

    def test_import_current_cannot_write_into_legacy_drama(self) -> None:
        target = self._legacy_drama_workspace()
        before = (target / "data" / "workspace.json").read_bytes()
        source_root = Path(self._tmp.name) / "legacy-root"
        (source_root / "data").mkdir(parents=True)
        source_marker = source_root / "data" / "source.json"
        source_marker.write_text("{}", encoding="utf-8")
        with mock.patch.object(cli_workspace, "ROOT", source_root):
            with self.assertRaisesRegex(ValueError, "not available"):
                cli_workspace.import_current("legacy_show")
        self.assertTrue(source_marker.is_file())
        self.assertEqual((target / "data" / "workspace.json").read_bytes(), before)

    def test_invalid_metadata_is_not_listed_or_cli_accessible(self) -> None:
        root = paths.WORKSPACE_DIR / "unknown"
        (root / "data").mkdir(parents=True)
        (root / "data" / "workspace.json").write_text("not-json", encoding="utf-8")
        self.assertNotIn("unknown", list_workspaces())
        with self.assertRaises(SystemExit) as raised:
            main._require_supported_workspace("unknown")
        self.assertEqual(raised.exception.code, 2)

    def test_boundary_checker_detects_generic_removed_surfaces(self) -> None:
        for token in ("character-ref", "shot-video", "storyboard", "hook_designer"):
            self.assertTrue(boundary.scan_text("src/web/static.py", token), token)
        self.assertEqual(
            boundary.scan_text("src/web/workspace_meta.py", 'KNOWN_TYPES = {"novel", "drama"}'),
            [],
        )

    def test_main_creates_only_novels(self) -> None:
        with self.assertRaises(ValueError):
            init_workspace("blocked_show", type="drama")
        self.assertFalse((paths.WORKSPACE_DIR / "blocked_show").exists())
        created = init_workspace("novel_one", creation_mode="greenfield")
        self.assertEqual(created["type"], "novel")
        self.assertEqual(list_workspaces(), ["novel_one"])

    def test_direct_cli_access_to_legacy_type_fails_closed(self) -> None:
        self._legacy_drama_workspace()
        with mock.patch.dict("os.environ", {}, clear=False):
            with self.assertRaises(SystemExit) as raised:
                main._require_supported_workspace("legacy_show")
        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
