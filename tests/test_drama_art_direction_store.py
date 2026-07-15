"""iter108: safe ArtDirection catalog persistence and mutation."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from src import drama_art_direction_store, paths
from src.drama_assets import build_art_direction_version
from src.drama_schemas import _canonical_sha256
from src.schemas import model_to_dict
from src.workspace_lock import WorkspaceLocked
from tests._drama_base import DramaTestBase


def _spec(preset: str = "cinematic") -> dict:
    return {
        "preset": preset,
        "positive_tokens": ["ink wash", "soft rim light"],
        "negative_tokens": ["watermark"],
        "palette": ["#112233", "#aabbcc"],
        "aspect_ratio": "9:16",
    }


class DramaArtDirectionStoreTests(DramaTestBase):
    def _workspace(self, name: str) -> None:
        self._make_drama_workspace(name)

    def _create(self, name: str = "art-direction"):
        return drama_art_direction_store.create_art_direction_catalog(
            name,
            art_direction_id="season_default",
            spec=_spec(),
            source_kind="preset",
        )

    def test_missing_create_load_and_idempotent_bytes_are_offline(self) -> None:
        self._workspace("art-direction")
        self.assertEqual(
            drama_art_direction_store.inspect_art_direction_catalog(
                "art-direction"
            ).state,
            "needs_art_direction_catalog",
        )
        with patch.object(socket, "socket", side_effect=AssertionError("network")):
            first = self._create()
            path = drama_art_direction_store.art_direction_catalog_path(
                "art-direction"
            )
            before = path.read_bytes()
            mtime = path.stat().st_mtime_ns
            second = self._create()
            loaded = drama_art_direction_store.load_fresh_art_direction_catalog(
                "art-direction"
            )
            ref = drama_art_direction_store.load_selected_art_direction_ref(
                "art-direction"
            )
        self.assertEqual(first, second)
        self.assertEqual(second, loaded)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(path.stat().st_mtime_ns, mtime)
        self.assertEqual(ref.version_id, first.selected_version_id)
        self.assertEqual(ref.fingerprint, first.versions[0].version_fingerprint)

    @patch.object(socket, "socket", side_effect=AssertionError("network"))
    def test_append_and_select_preserve_idempotence_and_double_cas(
        self,
        _socket,
    ) -> None:
        self._workspace("mutate")
        original = self._create("mutate")
        path = drama_art_direction_store.art_direction_catalog_path("mutate")
        appended = drama_art_direction_store.append_art_direction_candidate(
            "mutate",
            spec=_spec("graphic-novel"),
            source_kind="manual",
            derived_from=original.selected_version_id,
            expected_catalog_fingerprint=original.catalog_fingerprint,
        )
        self.assertEqual(appended.selected_version_id, original.selected_version_id)
        self.assertEqual(appended.selection_revision, 0)
        append_bytes = path.read_bytes()
        append_mtime = path.stat().st_mtime_ns
        repeated = drama_art_direction_store.append_art_direction_candidate(
            "mutate",
            spec=_spec("graphic-novel"),
            source_kind="manual",
            derived_from=original.selected_version_id,
            expected_catalog_fingerprint=appended.catalog_fingerprint,
        )
        self.assertEqual(repeated, appended)
        self.assertEqual(path.read_bytes(), append_bytes)
        self.assertEqual(path.stat().st_mtime_ns, append_mtime)

        candidate = appended.versions[-1]
        selected = drama_art_direction_store.select_art_direction_version(
            "mutate",
            version_id=candidate.version_id,
            expected_selection_revision=0,
            expected_selected_version_id=original.selected_version_id,
        )
        self.assertEqual(selected.selection_revision, 1)
        selected_bytes = path.read_bytes()
        selected_mtime = path.stat().st_mtime_ns
        repeated = drama_art_direction_store.select_art_direction_version(
            "mutate",
            version_id=candidate.version_id,
            expected_selection_revision=1,
            expected_selected_version_id=candidate.version_id,
        )
        self.assertEqual(repeated, selected)
        self.assertEqual(path.read_bytes(), selected_bytes)
        self.assertEqual(path.stat().st_mtime_ns, selected_mtime)
        restored = drama_art_direction_store.select_art_direction_version(
            "mutate",
            version_id=original.selected_version_id,
            expected_selection_revision=1,
            expected_selected_version_id=candidate.version_id,
        )
        self.assertEqual(restored.selection_revision, 2)
        self.assertEqual(restored.selected_version_id, original.selected_version_id)
        with self.assertRaisesRegex(ValueError, "selection was rejected"):
            drama_art_direction_store.select_art_direction_version(
                "mutate",
                version_id=candidate.version_id,
                expected_selection_revision=0,
                expected_selected_version_id=original.selected_version_id,
            )

    def test_invalid_duplicate_nonfinite_deep_oversize_and_symlink_fail_closed(self) -> None:
        self._workspace("invalid")
        self._create("invalid")
        path = drama_art_direction_store.art_direction_catalog_path("invalid")
        valid = path.read_bytes()
        for payload in (
            b'{"schema_version":1,"schema_version":1}',
            b'{"x":NaN}',
            ('{"x":' * 1100 + "0" + "}" * 1100).encode("utf-8"),
            b"{" + b" " * (drama_art_direction_store.MAX_ART_DIRECTION_CATALOG_BYTES + 1),
        ):
            path.write_bytes(payload)
            self.assertEqual(
                drama_art_direction_store.inspect_art_direction_catalog("invalid").state,
                "invalid",
            )
        path.write_bytes(valid)
        target = path.with_name("outside.json")
        target.write_bytes(valid)
        path.unlink()
        path.symlink_to(target)
        self.assertEqual(
            drama_art_direction_store.inspect_art_direction_catalog("invalid").state,
            "invalid",
        )

    def test_directory_and_parent_symlink_are_rejected(self) -> None:
        self._workspace("directory")
        self._create("directory")
        path = drama_art_direction_store.art_direction_catalog_path("directory")
        valid = path.read_bytes()
        path.unlink()
        path.mkdir()
        self.assertEqual(
            drama_art_direction_store.inspect_art_direction_catalog("directory").state,
            "invalid",
        )
        path.rmdir()
        path.write_bytes(valid)

        assets_dir = path.parent
        real_assets = assets_dir.with_name("assets-real")
        assets_dir.rename(real_assets)
        assets_dir.symlink_to(real_assets, target_is_directory=True)
        self.assertEqual(
            drama_art_direction_store.inspect_art_direction_catalog("directory").state,
            "invalid",
        )
        with self.assertRaises((ValueError, drama_art_direction_store.DramaArtDirectionStoreError)):
            drama_art_direction_store.select_art_direction_version(
                "directory",
                version_id=self._create_version_id_from_bytes(valid),
                expected_selection_revision=0,
                expected_selected_version_id=self._create_version_id_from_bytes(valid),
            )

    @staticmethod
    def _create_version_id_from_bytes(payload: bytes) -> str:
        return json.loads(payload.decode("utf-8"))["catalog"]["selected_version_id"]

    def test_target_cas_failure_preserves_original_bytes(self) -> None:
        self._workspace("race")
        original = self._create("race")
        path = drama_art_direction_store.art_direction_catalog_path("race")
        before = path.read_bytes()
        with patch(
            "src.drama_art_direction_store._target_token_at",
            return_value=("file", 1, "changed"),
        ):
            with self.assertRaisesRegex(
                drama_art_direction_store.DramaArtDirectionStoreError,
                "changed concurrently",
            ):
                drama_art_direction_store.append_art_direction_candidate(
                    "race",
                    spec=_spec("candidate"),
                    source_kind="manual",
                    derived_from=original.selected_version_id,
                    expected_catalog_fingerprint=original.catalog_fingerprint,
                )
        self.assertEqual(path.read_bytes(), before)

        real_token = drama_art_direction_store._target_token(
            paths.workspace_root("race"),
            path,
        )
        with patch(
            "src.drama_art_direction_store._target_token_at",
            side_effect=[real_token, ("file", 1, "changed-before-replace")],
        ):
            with self.assertRaisesRegex(
                drama_art_direction_store.DramaArtDirectionStoreError,
                "changed concurrently",
            ):
                drama_art_direction_store.append_art_direction_candidate(
                    "race",
                    spec=_spec("late-candidate"),
                    source_kind="manual",
                    derived_from=original.selected_version_id,
                    expected_catalog_fingerprint=original.catalog_fingerprint,
                )
        self.assertEqual(path.read_bytes(), before)

    def test_unknown_selection_and_orphan_append_do_not_write(self) -> None:
        self._workspace("unknown")
        catalog = self._create("unknown")
        path = drama_art_direction_store.art_direction_catalog_path("unknown")
        before = path.read_bytes()
        with self.assertRaisesRegex(
            drama_art_direction_store.DramaArtDirectionStoreError,
            "selection was rejected",
        ):
            drama_art_direction_store.select_art_direction_version(
                "unknown",
                version_id="ad_" + "f" * 24,
                expected_selection_revision=0,
                expected_selected_version_id=catalog.selected_version_id,
            )
        self.assertEqual(path.read_bytes(), before)
        with self.assertRaisesRegex(
            drama_art_direction_store.DramaArtDirectionStoreError,
            "candidate append was rejected",
        ):
            drama_art_direction_store.append_art_direction_candidate(
                "unknown",
                spec=_spec("orphan"),
                source_kind="manual",
                derived_from="ad_" + "e" * 24,
                expected_catalog_fingerprint=catalog.catalog_fingerprint,
            )
        self.assertEqual(path.read_bytes(), before)

    def test_indirect_orphan_chain_is_invalid_in_persisted_catalog(self) -> None:
        self._workspace("orphan-chain")
        tail = build_art_direction_version(
            art_direction_id="season_default",
            spec=_spec("orphan-tail"),
            source_kind="manual",
            derived_from="ad_" + "f" * 24,
        )
        head = build_art_direction_version(
            art_direction_id="season_default",
            spec=_spec("orphan-head"),
            source_kind="manual",
            derived_from=tail.version_id,
        )
        catalog = {
            "schema_version": 1,
            "season_no": 1,
            "art_direction_id": "season_default",
            "versions": [model_to_dict(head), model_to_dict(tail)],
            "selected_version_id": head.version_id,
            "selection_revision": 0,
        }
        catalog["catalog_fingerprint"] = _canonical_sha256(catalog)
        envelope = {
            "schema_version": 1,
            "artifact_type": "drama_art_direction_catalog",
            "catalog_fingerprint": catalog["catalog_fingerprint"],
            "catalog": catalog,
        }
        path = drama_art_direction_store.art_direction_catalog_path("orphan-chain")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(envelope), encoding="utf-8")
        self.assertEqual(
            drama_art_direction_store.inspect_art_direction_catalog(
                "orphan-chain"
            ).state,
            "invalid",
        )

    def test_public_mutation_errors_redact_specs_paths_and_lock_holder(self) -> None:
        self._workspace("redaction")
        secret = "SECRET_ART_DIRECTION_TOKEN"
        bad = _spec()
        bad["positive_tokens"] = [secret, secret]
        with self.assertRaises(
            drama_art_direction_store.DramaArtDirectionStoreError
        ) as captured:
            drama_art_direction_store.create_art_direction_catalog(
                "redaction",
                art_direction_id="season_default",
                spec=bad,
                source_kind="manual",
            )
        self.assertNotIn(secret, str(captured.exception))
        self.assertNotIn(str(paths.workspace_root("redaction")), str(captured.exception))

        catalog = self._create("redaction")

        @contextmanager
        def locked_context():
            raise WorkspaceLocked(
                f"secret-holder argv=--token {secret} {paths.workspace_root('redaction')}"
            )
            yield

        with patch(
            "src.drama_art_direction_store.acquire_write_lock",
            return_value=locked_context(),
        ):
            with self.assertRaises(
                drama_art_direction_store.DramaArtDirectionStoreError
            ) as captured:
                drama_art_direction_store.append_art_direction_candidate(
                    "redaction",
                    spec=_spec("candidate"),
                    source_kind="manual",
                    derived_from=catalog.selected_version_id,
                    expected_catalog_fingerprint=catalog.catalog_fingerprint,
                )
        self.assertNotIn(secret, str(captured.exception))
        self.assertNotIn(str(paths.workspace_root("redaction")), str(captured.exception))

    def test_fifo_target_is_invalid_without_blocking(self) -> None:
        base = paths.WORKSPACE_DIR
        root = base / "fifo"
        target = root / "data/assets/season_01.art_direction.json"
        target.parent.mkdir(parents=True)
        os.mkfifo(target)
        code = """
import os, sys
from pathlib import Path
from src import drama_art_direction_store, paths
paths.WORKSPACE_DIR = Path(sys.argv[1])
state = drama_art_direction_store.inspect_art_direction_catalog('fifo').state
parent = drama_art_direction_store.art_direction_catalog_path('fifo').parent
fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
try:
    token = drama_art_direction_store._target_token_at(fd, 'season_01.art_direction.json')
finally:
    os.close(fd)
raise SystemExit(0 if state == 'invalid' and token == ('invalid',) else 3)
"""
        completed = subprocess.run(
            [sys.executable, "-c", code, str(base)],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)


if __name__ == "__main__":
    import unittest

    unittest.main()
