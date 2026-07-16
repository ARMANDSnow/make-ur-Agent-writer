"""iter113: strict C2 candidate manifest, artifact, CAS, and recovery store."""

from __future__ import annotations

import json
import os
import socket
from pathlib import Path
from unittest.mock import patch

from src import (
    drama_shot_image_candidate_store,
    drama_shot_image_store,
    paths,
)
from src.web.workspace_ctx import use_workspace
from src.workspace_lock import acquire_write_lock
from tests._drama_shot_image_candidate_base import DramaShotImageCandidateFixture


class DramaShotImageCandidateStoreTests(DramaShotImageCandidateFixture):
    def test_state_matrix_create_load_and_idempotent_bytes(self) -> None:
        self._seed_candidate_sources("candidate-states")
        self.assertEqual(
            drama_shot_image_candidate_store.inspect_episode_shot_image_candidates(
                "candidate-states"
            ).state,
            "needs_shot_image_assets",
        )
        with patch.object(socket, "socket", side_effect=AssertionError("network")):
            first = self._create_manifest("candidate-states")
            path = drama_shot_image_candidate_store.shot_image_candidate_manifest_path(
                "candidate-states"
            )
            before = path.read_bytes()
            mtime = path.stat().st_mtime_ns
            second = self._create_manifest("candidate-states")
        self.assertEqual(first, second)
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(path.stat().st_mtime_ns, mtime)
        inspection = drama_shot_image_candidate_store.inspect_episode_shot_image_candidates(
            "candidate-states"
        )
        self.assertEqual(inspection.state, "fresh")
        self.assertEqual(inspection.coverage.status, "incomplete")
        self.assertEqual(
            drama_shot_image_candidate_store.load_fresh_episode_shot_image_candidates(
                "candidate-states"
            ),
            first,
        )

    def test_append_revalidates_png_and_does_not_auto_select(self) -> None:
        sources = self._seed_candidate_sources("candidate-append")
        manifest = self._create_manifest("candidate-append")
        shot_id = sources["shot_image_plan"].shot_specs[0].shot_id
        with patch.object(socket, "socket", side_effect=AssertionError("network")):
            appended, candidate = self._append_candidate(
                "candidate-append",
                manifest,
                shot_id,
            )
            artifact = paths.workspace_root("candidate-append") / candidate.artifact.path
            before = artifact.read_bytes()
            replay, replay_candidate = self._append_candidate(
                "candidate-append",
                manifest,
                shot_id,
            )
        self.assertEqual(replay_candidate, candidate)
        self.assertEqual(replay, appended)
        self.assertEqual(artifact.read_bytes(), before)
        pool = replay.shots[0]
        self.assertEqual(pool.selection_revision, 0)
        self.assertIsNone(pool.first_binding)
        self.assertEqual(pool.tail_binding.kind, "none")

    def test_store_selection_uses_manifest_revision_and_current_binding_cas(self) -> None:
        sources = self._seed_candidate_sources("candidate-select")
        manifest = self._create_manifest("candidate-select")
        shot_id = sources["shot_image_plan"].shot_specs[0].shot_id
        manifest, candidate = self._append_candidate(
            "candidate-select",
            manifest,
            shot_id,
        )
        binding = {
            "kind": "direct",
            "candidate_id": candidate.candidate_id,
            "candidate_fingerprint": candidate.candidate_fingerprint,
        }
        selected = drama_shot_image_candidate_store.select_episode_shot_image_frame(
            "candidate-select",
            shot_id=shot_id,
            frame="first",
            binding=binding,
            expected_selection_revision=0,
            expected_current_binding=None,
            expected_manifest_fingerprint=manifest.manifest_fingerprint,
        )
        self.assertEqual(selected.shots[0].selection_revision, 1)
        replayed = drama_shot_image_candidate_store.select_episode_shot_image_frame(
            "candidate-select",
            shot_id=shot_id,
            frame="first",
            binding=binding,
            expected_selection_revision=0,
            expected_current_binding=None,
            expected_manifest_fingerprint=manifest.manifest_fingerprint,
        )
        self.assertEqual(replayed, selected)
        with self.assertRaisesRegex(ValueError, "rejected"):
            drama_shot_image_candidate_store.select_episode_shot_image_frame(
                "candidate-select",
                shot_id=shot_id,
                frame="first",
                binding=binding,
                expected_selection_revision=0,
                expected_current_binding=binding,
                expected_manifest_fingerprint=manifest.manifest_fingerprint,
            )
        with self.assertRaisesRegex(ValueError, "rejected"):
            drama_shot_image_candidate_store.select_episode_shot_image_frame(
                "candidate-select",
                shot_id=shot_id,
                frame="tail",
                binding=binding,
                expected_selection_revision=0,
                expected_current_binding={"kind": "none"},
                expected_manifest_fingerprint=selected.manifest_fingerprint,
            )

    def test_bad_png_and_tampered_artifact_fail_closed(self) -> None:
        sources = self._seed_candidate_sources("candidate-png")
        manifest = self._create_manifest("candidate-png")
        shot_id = sources["shot_image_plan"].shot_specs[0].shot_id
        for payload in (
            b"not-png",
            b"\x89PNG\r\n\x1a\ntruncated",
            self._png()[:-1],
        ):
            with self.assertRaises(ValueError):
                drama_shot_image_candidate_store.append_local_shot_image_candidate(
                    "candidate-png",
                    shot_id=shot_id,
                    png_bytes=payload,
                    expected_manifest_fingerprint=manifest.manifest_fingerprint,
                )
        manifest, candidate = self._append_candidate(
            "candidate-png",
            manifest,
            shot_id,
        )
        artifact = paths.workspace_root("candidate-png") / candidate.artifact.path
        artifact.write_bytes(self._png(rgba=b"\xaa\xbb\xcc\xff"))
        self.assertEqual(
            drama_shot_image_candidate_store.inspect_episode_shot_image_candidates(
                "candidate-png"
            ).state,
            "invalid",
        )

    def test_stale_append_token_does_not_publish_orphan_artifact(self) -> None:
        sources = self._seed_candidate_sources("candidate-stale-append")
        initial = self._create_manifest("candidate-stale-append")
        plan = sources["shot_image_plan"]
        shot_id = plan.shot_specs[0].shot_id
        current, _ = self._append_candidate(
            "candidate-stale-append",
            initial,
            shot_id,
        )
        payload = self._png(rgba=b"\xaa\xbb\xcc\xff")
        identity = drama_shot_image_candidate_store._candidate_payload_identity(payload)
        from src import drama_shot_image_candidates

        rejected = drama_shot_image_candidates.build_shot_image_candidate(
            plan,
            shot_id=shot_id,
            artifact_sha256=identity[0],
            artifact_size_bytes=identity[1],
            width=identity[2],
            height=identity[3],
        )
        artifact = paths.workspace_root("candidate-stale-append") / rejected.artifact.path
        with self.assertRaisesRegex(ValueError, "append was rejected"):
            drama_shot_image_candidate_store.append_local_shot_image_candidate(
                "candidate-stale-append",
                shot_id=shot_id,
                png_bytes=payload,
                expected_manifest_fingerprint=initial.manifest_fingerprint,
            )
        self.assertFalse(artifact.exists())
        self.assertEqual(
            drama_shot_image_candidate_store.load_fresh_episode_shot_image_candidates(
                "candidate-stale-append"
            ),
            current,
        )

    def test_exact_append_replay_restores_missing_referenced_artifact(self) -> None:
        sources = self._seed_candidate_sources("candidate-missing-repair")
        initial = self._create_manifest("candidate-missing-repair")
        shot_id = sources["shot_image_plan"].shot_specs[0].shot_id
        current, candidate = self._append_candidate(
            "candidate-missing-repair",
            initial,
            shot_id,
        )
        artifact = paths.workspace_root("candidate-missing-repair") / candidate.artifact.path
        artifact.unlink()
        self.assertEqual(
            drama_shot_image_candidate_store.inspect_episode_shot_image_candidates(
                "candidate-missing-repair"
            ).state,
            "invalid",
        )
        replayed, replayed_candidate = self._append_candidate(
            "candidate-missing-repair",
            initial,
            shot_id,
        )
        self.assertEqual(replayed_candidate, candidate)
        self.assertEqual(replayed, current)
        self.assertTrue(artifact.is_file())
        self.assertEqual(
            drama_shot_image_candidate_store.inspect_episode_shot_image_candidates(
                "candidate-missing-repair"
            ).state,
            "fresh",
        )

    def test_explicit_repair_restores_multiple_missing_artifacts_independently(self) -> None:
        sources = self._seed_candidate_sources("candidate-multi-repair")
        manifest = self._create_manifest("candidate-multi-repair")
        shot_id = sources["shot_image_plan"].shot_specs[0].shot_id
        first_bytes = self._png(rgba=b"\x11\x22\x33\xff")
        second_bytes = self._png(rgba=b"\x44\x55\x66\xff")
        manifest, first = self._append_candidate(
            "candidate-multi-repair", manifest, shot_id
        )
        manifest, second = self._append_candidate(
            "candidate-multi-repair",
            manifest,
            shot_id,
            rgba=b"\x44\x55\x66\xff",
        )
        root = paths.workspace_root("candidate-multi-repair")
        (root / first.artifact.path).unlink()
        (root / second.artifact.path).unlink()
        repaired_first = (
            drama_shot_image_candidate_store.repair_referenced_shot_image_candidate_artifact(
                "candidate-multi-repair",
                candidate_id=first.candidate_id,
                png_bytes=first_bytes,
                expected_manifest_fingerprint=manifest.manifest_fingerprint,
            )
        )
        self.assertEqual(repaired_first, first)
        self.assertEqual(
            drama_shot_image_candidate_store.inspect_episode_shot_image_candidates(
                "candidate-multi-repair"
            ).state,
            "invalid",
        )
        repaired_second = (
            drama_shot_image_candidate_store.repair_referenced_shot_image_candidate_artifact(
                "candidate-multi-repair",
                candidate_id=second.candidate_id,
                png_bytes=second_bytes,
                expected_manifest_fingerprint=manifest.manifest_fingerprint,
            )
        )
        self.assertEqual(repaired_second, second)
        self.assertEqual(
            drama_shot_image_candidate_store.inspect_episode_shot_image_candidates(
                "candidate-multi-repair"
            ).state,
            "fresh",
        )

    def test_full_candidate_pool_rejects_before_publishing_artifact(self) -> None:
        sources = self._seed_candidate_sources("candidate-full")
        manifest = self._create_manifest("candidate-full")
        plan = sources["shot_image_plan"]
        shot_id = plan.shot_specs[0].shot_id
        for index in range(32):
            manifest, _ = self._append_candidate(
                "candidate-full",
                manifest,
                shot_id,
                rgba=bytes([index, 1, 2, 255]),
            )
        payload = self._png(rgba=bytes([32, 1, 2, 255]))
        identity = drama_shot_image_candidate_store._candidate_payload_identity(payload)
        from src import drama_shot_image_candidates

        rejected = drama_shot_image_candidates.build_shot_image_candidate(
            plan,
            shot_id=shot_id,
            artifact_sha256=identity[0],
            artifact_size_bytes=identity[1],
            width=identity[2],
            height=identity[3],
        )
        artifact = paths.workspace_root("candidate-full") / rejected.artifact.path
        with self.assertRaisesRegex(ValueError, "append was rejected"):
            drama_shot_image_candidate_store.append_local_shot_image_candidate(
                "candidate-full",
                shot_id=shot_id,
                png_bytes=payload,
                expected_manifest_fingerprint=manifest.manifest_fingerprint,
            )
        self.assertFalse(artifact.exists())

    def test_stale_plan_requires_double_cas_reconcile_and_preserves_history(self) -> None:
        sources = self._seed_candidate_sources("candidate-stale")
        manifest = self._create_manifest("candidate-stale")
        old_plan = sources["shot_image_plan"]
        first_id = old_plan.shot_specs[0].shot_id
        manifest, candidate = self._append_candidate(
            "candidate-stale",
            manifest,
            first_id,
        )
        changed_mapping = {
            key: list(value) for key, value in sources["character_mapping"].items()
        }
        changed_mapping[first_id] = []
        drama_shot_image_store.create_episode_shot_image_plan(
            "candidate-stale",
            shot_character_ids=changed_mapping,
            reference_policy=sources["policy"],
            replace_stale=True,
            expected_plan_fingerprint=old_plan.plan_fingerprint,
        )
        inspection = drama_shot_image_candidate_store.inspect_episode_shot_image_candidates(
            "candidate-stale"
        )
        self.assertEqual(inspection.state, "stale")
        self.assertEqual(inspection.affected_shot_ids, (first_id,))
        with self.assertRaisesRegex(ValueError, "explicit confirmation"):
            self._create_manifest("candidate-stale")
        with self.assertRaisesRegex(ValueError, "refresh before replacement"):
            drama_shot_image_candidate_store.create_episode_shot_image_candidate_manifest(
                "candidate-stale",
                replace_stale=True,
                expected_manifest_fingerprint="0" * 64,
            )
        reconciled = drama_shot_image_candidate_store.create_episode_shot_image_candidate_manifest(
            "candidate-stale",
            replace_stale=True,
            expected_manifest_fingerprint=manifest.manifest_fingerprint,
        )
        self.assertEqual(reconciled.shots[0].candidates, [candidate])
        artifact = paths.workspace_root("candidate-stale") / candidate.artifact.path
        artifact.unlink()
        repaired = (
            drama_shot_image_candidate_store.repair_referenced_shot_image_candidate_artifact(
                "candidate-stale",
                candidate_id=candidate.candidate_id,
                png_bytes=self._png(),
                expected_manifest_fingerprint=reconciled.manifest_fingerprint,
            )
        )
        self.assertEqual(repaired, candidate)
        self.assertTrue(artifact.is_file())

    def test_reordered_pool_payload_is_stale_even_with_recomputed_fingerprint(self) -> None:
        sources = self._seed_candidate_sources("candidate-order")
        manifest = self._create_manifest("candidate-order")
        plan = sources["shot_image_plan"]
        from src import drama_shot_image_candidates
        from src.drama_schemas import EpisodeShotImageCandidateManifest

        tampered = EpisodeShotImageCandidateManifest(
            **drama_shot_image_candidates._manifest_payload(
                season_no=manifest.season_no,
                episode_no=manifest.episode_no,
                source_plan_fingerprint=manifest.source_plan_fingerprint,
                shots=list(reversed(manifest.shots)),
            )
        )
        envelope = {
            "schema_version": 1,
            "artifact_type": "drama_episode_shot_image_assets",
            "manifest_fingerprint": tampered.manifest_fingerprint,
            "manifest": tampered.model_dump(),
        }
        path = drama_shot_image_candidate_store.shot_image_candidate_manifest_path(
            "candidate-order"
        )
        path.write_text(
            json.dumps(envelope, ensure_ascii=False, allow_nan=False),
            encoding="utf-8",
        )
        inspection = drama_shot_image_candidate_store.inspect_episode_shot_image_candidates(
            "candidate-order"
        )
        self.assertEqual(inspection.state, "stale")
        self.assertEqual(
            set(inspection.affected_shot_ids),
            {item.shot_id for item in plan.shot_specs},
        )

    def test_invalid_special_and_nonfinite_manifest_targets_are_preserved(self) -> None:
        self._seed_candidate_sources("candidate-invalid")
        path = drama_shot_image_candidate_store.shot_image_candidate_manifest_path(
            "candidate-invalid"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")
        before = path.read_bytes()
        self.assertEqual(
            drama_shot_image_candidate_store.inspect_episode_shot_image_candidates(
                "candidate-invalid"
            ).state,
            "invalid",
        )
        with self.assertRaisesRegex(ValueError, "repaired explicitly"):
            self._create_manifest("candidate-invalid")
        self.assertEqual(path.read_bytes(), before)

        for name, payload in (
            ("candidate-nan", '{"value":NaN}'),
            ("candidate-deep", "[" * 1100 + "]" * 1100),
        ):
            self._seed_candidate_sources(name)
            target = drama_shot_image_candidate_store.shot_image_candidate_manifest_path(name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(payload, encoding="utf-8")
            self.assertEqual(
                drama_shot_image_candidate_store.inspect_episode_shot_image_candidates(
                    name
                ).state,
                "invalid",
            )

        self._seed_candidate_sources("candidate-fifo")
        fifo = drama_shot_image_candidate_store.shot_image_candidate_manifest_path(
            "candidate-fifo"
        )
        fifo.parent.mkdir(parents=True, exist_ok=True)
        os.mkfifo(fifo)
        self.assertEqual(
            drama_shot_image_candidate_store.inspect_episode_shot_image_candidates(
                "candidate-fifo"
            ).state,
            "invalid",
        )

    def test_parent_symlink_workspace_lock_and_public_errors_fail_closed(self) -> None:
        sources = self._seed_candidate_sources("candidate-parent-link")
        root = paths.workspace_root("candidate-parent-link")
        outside = Path(self._tmp.name) / "outside"
        outside.mkdir()
        linked = root / "linked-output"
        linked.symlink_to(outside, target_is_directory=True)
        escaped = linked / "episode_01.shot_image_assets.json"
        with patch.object(
            drama_shot_image_candidate_store,
            "shot_image_candidate_manifest_path",
            return_value=escaped,
        ):
            with self.assertRaises(ValueError):
                self._create_manifest("candidate-parent-link")
        self.assertFalse((outside / escaped.name).exists())

        self._seed_candidate_sources("candidate-lock")
        with use_workspace("candidate-lock"), acquire_write_lock(source="holder"):
            with self.assertRaisesRegex(ValueError, "rejected") as caught:
                self._create_manifest("candidate-lock")
        self.assertNotIn(str(paths.workspace_root("candidate-lock")), str(caught.exception))

    def test_artifact_symlink_is_never_followed(self) -> None:
        sources = self._seed_candidate_sources("candidate-artifact-link")
        manifest = self._create_manifest("candidate-artifact-link")
        plan = sources["shot_image_plan"]
        payload = self._png()
        identity = drama_shot_image_candidate_store._candidate_payload_identity(payload)
        from src import drama_shot_image_candidates

        candidate = drama_shot_image_candidates.build_shot_image_candidate(
            plan,
            shot_id=plan.shot_specs[0].shot_id,
            artifact_sha256=identity[0],
            artifact_size_bytes=identity[1],
            width=identity[2],
            height=identity[3],
        )
        target = paths.workspace_root("candidate-artifact-link") / candidate.artifact.path
        target.parent.mkdir(parents=True, exist_ok=True)
        outside = Path(self._tmp.name) / "outside.png"
        outside.write_bytes(payload)
        target.symlink_to(outside)
        with self.assertRaises(ValueError):
            drama_shot_image_candidate_store.append_local_shot_image_candidate(
                "candidate-artifact-link",
                shot_id=candidate.shot_id,
                png_bytes=payload,
                expected_manifest_fingerprint=manifest.manifest_fingerprint,
            )
        self.assertTrue(target.is_symlink())

    def test_preexisting_and_replaced_temp_entries_are_never_deleted(self) -> None:
        self._seed_candidate_sources("candidate-temp-owner")
        target = drama_shot_image_candidate_store.shot_image_candidate_manifest_path(
            "candidate-temp-owner"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        token = "a" * 32
        preexisting = target.with_name(f".{target.name}.tmp.{token}")
        preexisting.write_text("attacker-owned", encoding="utf-8")
        with patch(
            "src.drama_shot_image_candidate_store.secrets.token_hex",
            return_value=token,
        ):
            with self.assertRaisesRegex(ValueError, "written safely"):
                self._create_manifest("candidate-temp-owner")
        self.assertEqual(preexisting.read_text(encoding="utf-8"), "attacker-owned")
        self.assertFalse(target.exists())

        self._seed_candidate_sources("candidate-temp-race")
        target = drama_shot_image_candidate_store.shot_image_candidate_manifest_path(
            "candidate-temp-race"
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        token = "b" * 32
        temp = target.with_name(f".{target.name}.tmp.{token}")
        real_precommit = drama_shot_image_candidate_store._precommit_check

        def replace_temp(*args, **kwargs):
            real_precommit(*args, **kwargs)
            temp.unlink()
            temp.write_text("replacement-owned", encoding="utf-8")

        with patch(
            "src.drama_shot_image_candidate_store.secrets.token_hex",
            return_value=token,
        ), patch(
            "src.drama_shot_image_candidate_store._precommit_check",
            side_effect=replace_temp,
        ):
            with self.assertRaisesRegex(ValueError, "temporary file changed"):
                self._create_manifest("candidate-temp-race")
        self.assertEqual(temp.read_text(encoding="utf-8"), "replacement-owned")
        self.assertFalse(target.exists())

    def test_target_source_and_artifact_precommit_races_fail_closed(self) -> None:
        self._seed_candidate_sources("candidate-target-race")
        with patch(
            "src.drama_shot_image_candidate_store._target_token_at",
            side_effect=[("missing",), ("file", 1, "changed")],
        ):
            with self.assertRaisesRegex(ValueError, "changed concurrently"):
                self._create_manifest("candidate-target-race")
        self.assertFalse(
            drama_shot_image_candidate_store.shot_image_candidate_manifest_path(
                "candidate-target-race"
            ).exists()
        )

        sources = self._seed_candidate_sources("candidate-source-race")
        manifest = self._create_manifest("candidate-source-race")
        plan = sources["shot_image_plan"]
        first_id = plan.shot_specs[0].shot_id
        payload = self._png()
        identity = drama_shot_image_candidate_store._candidate_payload_identity(payload)
        from src import drama_shot_image_candidates

        source_race_candidate = drama_shot_image_candidates.build_shot_image_candidate(
            plan,
            shot_id=first_id,
            artifact_sha256=identity[0],
            artifact_size_bytes=identity[1],
            width=identity[2],
            height=identity[3],
        )
        source_race_artifact = (
            paths.workspace_root("candidate-source-race")
            / source_race_candidate.artifact.path
        )
        changed_mapping = {
            key: list(value) for key, value in sources["character_mapping"].items()
        }
        changed_mapping[first_id] = []
        sources["character_mapping"] = changed_mapping
        changed_plan = self._build_pure(sources, binding_revision=1)
        manifest_before = drama_shot_image_candidate_store.shot_image_candidate_manifest_path(
            "candidate-source-race"
        ).read_bytes()
        with patch(
            "src.drama_shot_image_candidate_store.load_fresh_episode_shot_image_plan",
            side_effect=[plan, changed_plan],
        ):
            with self.assertRaisesRegex(ValueError, "plan changed"):
                self._append_candidate(
                    "candidate-source-race",
                    manifest,
                    first_id,
                )
        self.assertEqual(
            drama_shot_image_candidate_store.shot_image_candidate_manifest_path(
                "candidate-source-race"
            ).read_bytes(),
            manifest_before,
        )
        self.assertFalse(source_race_artifact.exists())

        sources = self._seed_candidate_sources("candidate-artifact-race")
        manifest = self._create_manifest("candidate-artifact-race")
        first_id = sources["shot_image_plan"].shot_specs[0].shot_id
        with patch(
            "src.drama_shot_image_candidate_store._validate_manifest_artifacts",
            side_effect=[
                None,
                drama_shot_image_candidate_store.DramaShotImageCandidateStoreError(
                    "candidate artifact bytes changed"
                ),
            ],
        ):
            with self.assertRaisesRegex(ValueError, "artifact bytes changed"):
                self._append_candidate(
                    "candidate-artifact-race",
                    manifest,
                    first_id,
                )
        reloaded = drama_shot_image_candidate_store._read_manifest(
            "candidate-artifact-race",
            episode_no=1,
        )
        self.assertEqual(reloaded, manifest)

    def test_public_errors_are_redacted(self) -> None:
        sources = self._seed_candidate_sources("candidate-redacted")
        manifest = self._create_manifest("candidate-redacted")
        secret = "SECRET_SHOT_IMAGE_113"
        with self.assertRaises(
            drama_shot_image_candidate_store.DramaShotImageCandidateStoreError
        ) as caught:
            drama_shot_image_candidate_store.append_local_shot_image_candidate(
                "candidate-redacted",
                shot_id=secret,
                png_bytes=self._png(),
                expected_manifest_fingerprint=manifest.manifest_fingerprint,
            )
        rendered = f"{caught.exception!s} {caught.exception!r}"
        self.assertNotIn(secret, rendered)
        self.assertNotIn(str(paths.workspace_root("candidate-redacted")), rendered)
        inspection = drama_shot_image_candidate_store.inspect_episode_shot_image_candidates(
            f"../{secret}"
        )
        self.assertEqual(inspection.state, "invalid")
        self.assertNotIn(secret, " ".join(inspection.reasons))
