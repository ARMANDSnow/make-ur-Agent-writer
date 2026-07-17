"""iter126: visual-only override and stale dependency contract tests."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import socket
from unittest.mock import patch

from pydantic import ValidationError

from src import (
    character_designer,
    drama_render_store,
    drama_reviewer,
    drama_store,
    drama_visual_overrides,
    storyboard_builder,
)
from src.drama_schemas import (
    StaleDependencyImpact,
    VisualOverrideCatalog,
    VisualOverrideSelectionImpact,
    VisualOverrideSelectionResult,
    VisualOverrideState,
    VisualOverrideSpec,
    character_paths,
    episode_paths,
)
from src.utils import read_json, write_json
from src.workspace_lock import WorkspaceLocked
from tests._drama_base import DramaTestBase


class DramaVisualOverrideTests(DramaTestBase):
    def _ready(self, name: str = "visual-override"):
        self._make_drama_workspace(name, "霸总", episode_count=2)
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
        return drama_render_store.create_render_plan(name)

    def _reassemble_and_replace_plan(self, name: str) -> None:
        write_json(
            episode_paths(name).review_path,
            drama_reviewer.run(name, mock=True),
        )
        drama_store.assemble_episode(name)
        drama_render_store.create_render_plan(name, replace_stale=True)

    def test_spec_is_visual_only_strict_and_content_addressed(self) -> None:
        plan = self._ready("visual-spec")
        shot = plan.shots[0]
        spec = {
            "camera_movement": "推",
            "lighting": "low-key amber rim light",
            "negative_prompt": "watermark, extra fingers",
            "transition": "hard cut on motion",
        }
        first = drama_visual_overrides.build_visual_override_version(
            plan,
            shot_id=shot.shot_id,
            spec=spec,
            source_kind="manual",
        )
        second = drama_visual_overrides.build_visual_override_version(
            plan,
            shot_id=shot.shot_id,
            spec=copy.deepcopy(spec),
            source_kind="manual",
        )
        self.assertEqual(first, second)
        self.assertTrue(first.version_id.startswith("vo_"))
        with self.assertRaises(ValidationError):
            VisualOverrideSpec(dialogue="越权对白")  # type: ignore[call-arg]
        with self.assertRaises(ValidationError):
            VisualOverrideSpec()
        with self.assertRaises(ValidationError):
            VisualOverrideSpec(lighting=" night ")
        with self.assertRaises(ValidationError):
            VisualOverrideSpec(negative_prompt="bad\nprompt")
        with self.assertRaisesRegex(ValueError, "does not exist"):
            drama_visual_overrides.build_visual_override_version(
                plan,
                shot_id="shot_" + "0" * 24,
                spec={"lighting": "night"},
                source_kind="manual",
            )

    def test_unselected_candidate_does_not_change_effective_manifest(self) -> None:
        plan = self._ready("visual-unselected")
        catalog = drama_visual_overrides.build_visual_override_catalog(plan)
        before = drama_visual_overrides.build_effective_visual_override_manifest(
            plan,
            catalog,
        )
        updated, version = drama_visual_overrides.append_visual_override_candidate(
            plan,
            catalog,
            shot_id=plan.shots[0].shot_id,
            spec={"lighting": "moonlight"},
            source_kind="manual",
        )
        after = drama_visual_overrides.build_effective_visual_override_manifest(
            plan,
            updated,
        )
        self.assertEqual(before, after)
        self.assertNotEqual(catalog.catalog_fingerprint, updated.catalog_fingerprint)
        self.assertEqual(updated.selection_revision, 0)
        self.assertIn(version, updated.versions)

    def test_selection_double_cas_blocks_stale_and_aba(self) -> None:
        plan = self._ready("visual-cas")
        catalog = drama_visual_overrides.build_visual_override_catalog(plan)
        catalog, one = drama_visual_overrides.append_visual_override_candidate(
            plan,
            catalog,
            shot_id=plan.shots[0].shot_id,
            spec={"lighting": "warm"},
            source_kind="manual",
        )
        catalog, two = drama_visual_overrides.append_visual_override_candidate(
            plan,
            catalog,
            shot_id=plan.shots[0].shot_id,
            spec={"lighting": "cold"},
            source_kind="manual",
            derived_from=one.version_id,
        )
        selected = drama_visual_overrides.select_visual_override_candidate(
            plan,
            catalog,
            shot_id=plan.shots[0].shot_id,
            version_id=one.version_id,
            expected_selection_revision=0,
            expected_current_version_id=None,
        )
        with self.assertRaisesRegex(
            drama_visual_overrides.DramaVisualOverrideError,
            "revision changed",
        ):
            drama_visual_overrides.select_visual_override_candidate(
                plan,
                selected,
                shot_id=plan.shots[0].shot_id,
                version_id=two.version_id,
                expected_selection_revision=0,
                expected_current_version_id=one.version_id,
            )
        switched = drama_visual_overrides.select_visual_override_candidate(
            plan,
            selected,
            shot_id=plan.shots[0].shot_id,
            version_id=two.version_id,
            expected_selection_revision=1,
            expected_current_version_id=one.version_id,
        )
        cleared = drama_visual_overrides.select_visual_override_candidate(
            plan,
            switched,
            shot_id=plan.shots[0].shot_id,
            version_id=None,
            expected_selection_revision=2,
            expected_current_version_id=two.version_id,
        )
        with self.assertRaisesRegex(
            drama_visual_overrides.DramaVisualOverrideError,
            "revision changed",
        ):
            drama_visual_overrides.select_visual_override_candidate(
                plan,
                cleared,
                shot_id=plan.shots[0].shot_id,
                version_id=one.version_id,
                expected_selection_revision=1,
                expected_current_version_id=None,
            )

    def test_dependency_matrix_is_precise_and_hash_bound(self) -> None:
        shot_id = "shot_" + "a" * 24
        creative = drama_visual_overrides.classify_stale_dependency(
            "creative_revision"
        )
        bgm = drama_visual_overrides.classify_stale_dependency("bgm_selection")
        lighting = drama_visual_overrides.classify_stale_dependency(
            "override_lighting",
            shot_id=shot_id,
        )
        transition = drama_visual_overrides.classify_stale_dependency(
            "override_transition",
            shot_id=shot_id,
        )
        first_frame = drama_visual_overrides.classify_stale_dependency(
            "selected_first_frame",
            shot_id=shot_id,
        )
        self.assertEqual(creative.scope, "episode")
        self.assertEqual(len(creative.affected_nodes), 10)
        self.assertEqual(
            bgm.affected_nodes,
            ["timeline", "composite", "edit_export", "media_qa"],
        )
        self.assertIn("shot_image_request", lighting.affected_nodes)
        self.assertNotIn("audio_plan", lighting.affected_nodes)
        self.assertNotIn("shot_image_request", transition.affected_nodes)
        self.assertNotIn("shot_video_plan", transition.affected_nodes)
        self.assertEqual(transition.affected_nodes, bgm.affected_nodes)
        self.assertIn("shot_video_plan", first_frame.affected_nodes)
        payload = lighting.model_dump()
        payload["affected_nodes"] = ["media_qa"]
        payload["unaffected_nodes"] = [
            item
            for item in (
                "render_plan",
                "shot_image_request",
                "shot_image_candidate",
                "shot_video_plan",
                "shot_video_candidate",
                "audio_plan",
                "timeline",
                "composite",
                "edit_export",
            )
        ]
        payload["impact_fingerprint"] = self._canonical_hash(
            {key: value for key, value in payload.items() if key != "impact_fingerprint"}
        )
        with self.assertRaises(ValidationError):
            StaleDependencyImpact(**payload)
        with self.assertRaisesRegex(ValueError, "does not accept"):
            drama_visual_overrides.classify_stale_dependency(
                "bgm_selection",
                shot_id=shot_id,
            )

    def test_store_create_append_select_and_idempotent_load(self) -> None:
        plan = self._ready("visual-store")
        with patch.object(socket, "socket", side_effect=AssertionError("network")):
            state = drama_visual_overrides.ensure_visual_override_state(
                "visual-store"
            )
            before = drama_visual_overrides.visual_override_state_path(
                "visual-store"
            ).read_bytes()
            self.assertEqual(
                drama_visual_overrides.ensure_visual_override_state("visual-store"),
                state,
            )
            self.assertEqual(
                drama_visual_overrides.visual_override_state_path(
                    "visual-store"
                ).read_bytes(),
                before,
            )
            version = drama_visual_overrides.add_visual_override_candidate(
                "visual-store",
                shot_id=plan.shots[0].shot_id,
                spec={"lighting": "practical neon"},
                source_kind="manual",
            )
            candidate_only = drama_visual_overrides.load_fresh_visual_override_manifest(
                "visual-store"
            )
            self.assertEqual(candidate_only.selected_overrides, [])
            selected_result = drama_visual_overrides.select_visual_override(
                "visual-store",
                shot_id=plan.shots[0].shot_id,
                version_id=version.version_id,
                expected_selection_revision=0,
                expected_current_version_id=None,
            )
        selected = selected_result.manifest
        self.assertEqual(selected.selected_overrides[0].version_id, version.version_id)
        self.assertEqual(selected_result.impact.changed_fields, ["lighting"])
        self.assertIn(
            "shot_image_request",
            selected_result.impact.affected_nodes,
        )
        self.assertEqual(
            drama_visual_overrides.inspect_visual_override_state(
                "visual-store"
            ).state,
            "fresh",
        )

    def test_stale_reconcile_preserves_only_exact_shot_sources(self) -> None:
        plan = self._ready("visual-reconcile")
        one = drama_visual_overrides.add_visual_override_candidate(
            "visual-reconcile",
            shot_id=plan.shots[0].shot_id,
            spec={"lighting": "warm"},
            source_kind="manual",
        )
        two = drama_visual_overrides.add_visual_override_candidate(
            "visual-reconcile",
            shot_id=plan.shots[1].shot_id,
            spec={"transition": "match cut"},
            source_kind="manual",
        )
        result = drama_visual_overrides.select_visual_override(
            "visual-reconcile",
            shot_id=plan.shots[0].shot_id,
            version_id=one.version_id,
            expected_selection_revision=0,
            expected_current_version_id=None,
        )
        manifest = result.manifest
        result = drama_visual_overrides.select_visual_override(
            "visual-reconcile",
            shot_id=plan.shots[1].shot_id,
            version_id=two.version_id,
            expected_selection_revision=manifest.selection_revision,
            expected_current_version_id=None,
        )
        manifest = result.manifest

        storyboard_path = episode_paths("visual-reconcile").storyboard_path
        storyboard = read_json(storyboard_path)
        storyboard["shots"][0]["camera_movement"] = (
            "推" if storyboard["shots"][0]["camera_movement"] != "推" else "拉"
        )
        write_json(storyboard_path, storyboard)
        self._reassemble_and_replace_plan("visual-reconcile")
        self.assertEqual(
            drama_visual_overrides.inspect_visual_override_state(
                "visual-reconcile"
            ).state,
            "stale",
        )
        reconciled = drama_visual_overrides.reconcile_visual_override_state(
            "visual-reconcile"
        )
        self.assertEqual(
            [item.version_id for item in reconciled.catalog.versions],
            [two.version_id],
        )
        self.assertEqual(
            [item.version_id for item in reconciled.manifest.selected_overrides],
            [two.version_id],
        )
        self.assertEqual(
            reconciled.catalog.selection_revision,
            manifest.selection_revision + 1,
        )

    def test_invalid_state_symlink_directory_and_tampering_fail_closed(self) -> None:
        self._ready("visual-invalid")
        drama_visual_overrides.ensure_visual_override_state("visual-invalid")
        path = drama_visual_overrides.visual_override_state_path("visual-invalid")
        original = json.loads(path.read_text(encoding="utf-8"))
        original["state"]["manifest"]["selection_revision"] = 99
        path.write_text(json.dumps(original), encoding="utf-8")
        self.assertEqual(
            drama_visual_overrides.inspect_visual_override_state(
                "visual-invalid"
            ).state,
            "invalid",
        )
        with self.assertRaisesRegex(
            drama_visual_overrides.DramaVisualOverrideError,
            "not creatable",
        ):
            drama_visual_overrides.ensure_visual_override_state("visual-invalid")

        for kind in ("symlink", "directory"):
            name = f"visual-{kind}"
            self._ready(name)
            target = drama_visual_overrides.visual_override_state_path(name)
            if kind == "symlink":
                external = target.parent / "external.json"
                external.write_text("{}", encoding="utf-8")
                target.symlink_to(external)
            else:
                target.mkdir()
            self.assertEqual(
                drama_visual_overrides.inspect_visual_override_state(name).state,
                "invalid",
            )

    def test_target_cas_failure_does_not_publish_candidate(self) -> None:
        plan = self._ready("visual-target-cas")
        drama_visual_overrides.ensure_visual_override_state("visual-target-cas")
        path = drama_visual_overrides.visual_override_state_path(
            "visual-target-cas"
        )
        before = path.read_bytes()
        real_target_token_at = drama_visual_overrides._target_token_at
        calls = 0

        def changed_after_temp(directory_fd: int, name: str):
            nonlocal calls
            calls += 1
            if calls == 2:
                return ("invalid",)
            return real_target_token_at(directory_fd, name)

        with patch.object(
            drama_visual_overrides,
            "_target_token_at",
            side_effect=changed_after_temp,
        ):
            with self.assertRaisesRegex(
                drama_visual_overrides.DramaVisualOverrideError,
                "changed concurrently|invalid visual override",
            ):
                drama_visual_overrides.add_visual_override_candidate(
                    "visual-target-cas",
                    shot_id=plan.shots[0].shot_id,
                    spec={"lighting": "rim light"},
                    source_kind="manual",
                )
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(
            drama_visual_overrides.inspect_visual_override_state(
                "visual-target-cas"
            ).state,
            "fresh",
        )
        self.assertFalse(any(item.name.startswith(f".{path.name}.tmp") for item in path.parent.iterdir()))

    def test_inspected_byte_token_cannot_overwrite_newer_or_invalid_state(self) -> None:
        plan = self._ready("visual-inspect-token")
        drama_visual_overrides.ensure_visual_override_state("visual-inspect-token")
        path = drama_visual_overrides.visual_override_state_path(
            "visual-inspect-token"
        )
        real_write = drama_visual_overrides._write_state

        def replace_with_newer_bytes(*args, **kwargs):
            path.write_bytes(path.read_bytes() + b"\n")
            return real_write(*args, **kwargs)

        with patch.object(
            drama_visual_overrides,
            "_write_state",
            side_effect=replace_with_newer_bytes,
        ):
            with self.assertRaisesRegex(
                drama_visual_overrides.DramaVisualOverrideError,
                "changed concurrently",
            ):
                drama_visual_overrides.add_visual_override_candidate(
                    "visual-inspect-token",
                    shot_id=plan.shots[0].shot_id,
                    spec={"lighting": "rim light"},
                    source_kind="manual",
                )
        newer = path.read_bytes()
        self.assertTrue(newer.endswith(b"\n\n"))

        def replace_with_invalid_bytes(*args, **kwargs):
            path.write_bytes(b"{broken")
            return real_write(*args, **kwargs)

        with patch.object(
            drama_visual_overrides,
            "_write_state",
            side_effect=replace_with_invalid_bytes,
        ):
            with self.assertRaisesRegex(
                drama_visual_overrides.DramaVisualOverrideError,
                "invalid visual override state cannot be overwritten|changed concurrently",
            ):
                drama_visual_overrides.add_visual_override_candidate(
                    "visual-inspect-token",
                    shot_id=plan.shots[0].shot_id,
                    spec={"lighting": "night"},
                    source_kind="manual",
                )
        self.assertEqual(path.read_bytes(), b"{broken")

    def test_render_plan_token_is_checked_after_state_replace(self) -> None:
        self._ready("visual-source-token")
        real_token = drama_visual_overrides._render_plan_target_token(
            "visual-source-token",
            episode_no=1,
        )
        changed_token = ("file", 1, "f" * 64)
        with patch.object(
            drama_visual_overrides,
            "_render_plan_target_token",
            side_effect=[real_token, real_token, changed_token],
        ):
            with self.assertRaisesRegex(
                drama_visual_overrides.DramaVisualOverrideError,
                "render plan changed concurrently",
            ):
                drama_visual_overrides.ensure_visual_override_state(
                    "visual-source-token"
                )

    def test_workspace_lock_diagnostic_is_sanitized(self) -> None:
        self._ready("visual-lock")
        secret = "/abs/private sk-secret https://signed.example/?token=secret"
        with patch.object(
            drama_visual_overrides,
            "acquire_write_lock",
            side_effect=WorkspaceLocked(secret),
        ):
            with self.assertRaisesRegex(
                drama_visual_overrides.DramaVisualOverrideError,
                "^visual override workspace is busy$",
            ) as caught:
                drama_visual_overrides.ensure_visual_override_state("visual-lock")
        self.assertNotIn("sk-secret", str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)

    def test_duplicate_json_and_unsupported_schema_are_invalid(self) -> None:
        self._ready("visual-json")
        drama_visual_overrides.ensure_visual_override_state("visual-json")
        path = drama_visual_overrides.visual_override_state_path("visual-json")
        path.write_text(
            '{"schema_version":1,"schema_version":1,'
            '"artifact_type":"drama_visual_overrides",'
            '"state_fingerprint":"' + "0" * 64 + '","state":{}}',
            encoding="utf-8",
        )
        self.assertEqual(
            drama_visual_overrides.inspect_visual_override_state(
                "visual-json"
            ).state,
            "invalid",
        )

        self._ready("visual-schema")
        drama_visual_overrides.ensure_visual_override_state("visual-schema")
        path = drama_visual_overrides.visual_override_state_path("visual-schema")
        value = json.loads(path.read_text(encoding="utf-8"))
        value["schema_version"] = 2
        path.write_text(json.dumps(value), encoding="utf-8")
        inspection = drama_visual_overrides.inspect_visual_override_state(
            "visual-schema"
        )
        self.assertEqual(inspection.state, "invalid")
        self.assertEqual(inspection.reasons, ("schema_unsupported",))

    @staticmethod
    def _canonical_hash(value: object) -> str:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def test_selection_change_uses_old_and_new_spec_union(self) -> None:
        plan = self._ready("visual-impact-union")
        old = drama_visual_overrides.build_visual_override_version(
            plan,
            shot_id=plan.shots[0].shot_id,
            spec={"lighting": "warm"},
            source_kind="manual",
        )
        new = drama_visual_overrides.build_visual_override_version(
            plan,
            shot_id=plan.shots[0].shot_id,
            spec={"transition": "hard cut"},
            source_kind="manual",
        )
        impact = drama_visual_overrides.classify_visual_selection_change(
            shot_id=plan.shots[0].shot_id,
            old_version=old,
            new_version=new,
        )
        self.assertEqual(impact.changed_fields, ["lighting", "transition"])
        self.assertIn("shot_image_request", impact.affected_nodes)
        self.assertIn("shot_video_plan", impact.affected_nodes)
        self.assertIn("timeline", impact.affected_nodes)

        transition_only = drama_visual_overrides.classify_visual_selection_change(
            shot_id=plan.shots[0].shot_id,
            old_version=None,
            new_version=new,
        )
        self.assertEqual(transition_only.changed_fields, ["transition"])
        self.assertNotIn("shot_image_request", transition_only.affected_nodes)
        self.assertNotIn("shot_video_plan", transition_only.affected_nodes)

        forged = impact.model_dump()
        forged["new_version"]["version_id"] = old.version_id
        forged["impact_fingerprint"] = self._canonical_hash(
            {
                key: value
                for key, value in forged.items()
                if key != "impact_fingerprint"
            }
        )
        with self.assertRaises(ValidationError):
            VisualOverrideSelectionImpact(**forged)

    def test_selection_transition_is_durable_and_old_retry_recovers(self) -> None:
        plan = self._ready("visual-lost-response")
        version = drama_visual_overrides.add_visual_override_candidate(
            "visual-lost-response",
            shot_id=plan.shots[0].shot_id,
            spec={"lighting": "warm"},
            source_kind="manual",
        )
        first = drama_visual_overrides.select_visual_override(
            "visual-lost-response",
            shot_id=plan.shots[0].shot_id,
            version_id=version.version_id,
            expected_selection_revision=0,
            expected_current_version_id=None,
        )
        path = drama_visual_overrides.visual_override_state_path(
            "visual-lost-response"
        )
        committed = path.read_bytes()
        self.assertEqual(len(first.state.selection_transitions), 1)
        first_transition = first.state.selection_transitions[-1]
        self.assertEqual(
            first_transition.transition_id,
            json.loads(committed)["state"]["selection_transitions"][-1][
                "transition_id"
            ],
        )

        recovered = drama_visual_overrides.select_visual_override(
            "visual-lost-response",
            shot_id=plan.shots[0].shot_id,
            version_id=version.version_id,
            expected_selection_revision=0,
            expected_current_version_id=None,
        )
        self.assertEqual(recovered, first)
        self.assertEqual(path.read_bytes(), committed)
        self.assertEqual(
            drama_visual_overrides.load_last_visual_selection_result(
                "visual-lost-response"
            ),
            first,
        )
        no_op_before = path.read_bytes()
        no_op = drama_visual_overrides.select_visual_override(
            "visual-lost-response",
            shot_id=plan.shots[0].shot_id,
            version_id=version.version_id,
            expected_selection_revision=1,
            expected_current_version_id=version.version_id,
        )
        self.assertEqual(no_op.status, "no_op")
        self.assertEqual(path.read_bytes(), no_op_before)
        with self.assertRaisesRegex(ValueError, "no stale impact"):
            _ = no_op.impact

    def test_selection_result_rejects_cross_state_transition_splice(self) -> None:
        plan = self._ready("visual-result-binding")
        one = drama_visual_overrides.add_visual_override_candidate(
            "visual-result-binding",
            shot_id=plan.shots[0].shot_id,
            spec={"lighting": "warm"},
            source_kind="manual",
        )
        two = drama_visual_overrides.add_visual_override_candidate(
            "visual-result-binding",
            shot_id=plan.shots[1].shot_id,
            spec={"transition": "hard cut"},
            source_kind="manual",
        )
        first = drama_visual_overrides.select_visual_override(
            "visual-result-binding",
            shot_id=plan.shots[0].shot_id,
            version_id=one.version_id,
            expected_selection_revision=0,
            expected_current_version_id=None,
        )
        second = drama_visual_overrides.select_visual_override(
            "visual-result-binding",
            shot_id=plan.shots[1].shot_id,
            version_id=two.version_id,
            expected_selection_revision=1,
            expected_current_version_id=None,
        )
        forged_state = first.state.model_dump()
        forged_state["selection_transitions"][-1] = second.state.model_dump()[
            "selection_transitions"
        ][-1]
        forged_state["state_fingerprint"] = self._canonical_hash(
            {
                key: value
                for key, value in forged_state.items()
                if key != "state_fingerprint"
            }
        )
        with self.assertRaises(ValidationError):
            VisualOverrideState(**forged_state)

        forged_result = first.model_dump()
        forged_result["state"] = second.state.model_dump()
        forged_result["result_fingerprint"] = first.result_fingerprint
        with self.assertRaises(ValidationError):
            VisualOverrideSelectionResult(**forged_result)

        outsider = drama_visual_overrides.build_visual_override_version(
            plan,
            shot_id=plan.shots[0].shot_id,
            spec={"lighting": "never appended"},
            source_kind="manual",
        )
        impossible_impact = (
            drama_visual_overrides.classify_visual_selection_change(
                shot_id=plan.shots[0].shot_id,
                old_version=outsider,
                new_version=one,
            )
        )
        impossible_state = first.state.model_dump()
        transition = impossible_state["selection_transitions"][-1]
        transition["impact"] = impossible_impact.model_dump()
        transition_payload = {
            key: value
            for key, value in transition.items()
            if key not in {"transition_id", "transition_fingerprint"}
        }
        transition_fingerprint = self._canonical_hash(transition_payload)
        transition["transition_fingerprint"] = transition_fingerprint
        transition["transition_id"] = f"vot_{transition_fingerprint[:24]}"
        impossible_state["state_fingerprint"] = self._canonical_hash(
            {
                key: value
                for key, value in impossible_state.items()
                if key != "state_fingerprint"
            }
        )
        with self.assertRaisesRegex(
            ValidationError,
            "not in the catalog|old target is inconsistent",
        ):
            VisualOverrideState(**impossible_state)

    def test_receipt_ledger_recovers_older_request_after_later_selection(self) -> None:
        plan = self._ready("visual-receipt-ledger")
        one = drama_visual_overrides.add_visual_override_candidate(
            "visual-receipt-ledger",
            shot_id=plan.shots[0].shot_id,
            spec={"lighting": "warm"},
            source_kind="manual",
        )
        two = drama_visual_overrides.add_visual_override_candidate(
            "visual-receipt-ledger",
            shot_id=plan.shots[1].shot_id,
            spec={"transition": "hard cut"},
            source_kind="manual",
        )
        first = drama_visual_overrides.select_visual_override(
            "visual-receipt-ledger",
            shot_id=plan.shots[0].shot_id,
            version_id=one.version_id,
            expected_selection_revision=0,
            expected_current_version_id=None,
        )
        second = drama_visual_overrides.select_visual_override(
            "visual-receipt-ledger",
            shot_id=plan.shots[1].shot_id,
            version_id=two.version_id,
            expected_selection_revision=1,
            expected_current_version_id=None,
        )
        path = drama_visual_overrides.visual_override_state_path(
            "visual-receipt-ledger"
        )
        before_retry = path.read_bytes()
        recovered = drama_visual_overrides.select_visual_override(
            "visual-receipt-ledger",
            shot_id=plan.shots[0].shot_id,
            version_id=one.version_id,
            expected_selection_revision=0,
            expected_current_version_id=None,
        )
        self.assertEqual(path.read_bytes(), before_retry)
        self.assertEqual(recovered.impact, first.impact)
        self.assertEqual(
            recovered.transition_id,
            first.transition_id,
        )
        self.assertEqual(len(recovered.state.selection_transitions), 2)
        self.assertEqual(
            recovered.state.state_fingerprint,
            second.state.state_fingerprint,
        )
        self.assertEqual(recovered.status, "target_current")

        acknowledged = (
            drama_visual_overrides.acknowledge_visual_selection_transition(
                "visual-receipt-ledger",
                transition_id=first.transition_id,
            )
        )
        self.assertEqual(len(acknowledged.selection_transitions), 1)
        self.assertEqual(
            acknowledged.selection_transitions[0].transition_id,
            second.transition_id,
        )
        idempotent = (
            drama_visual_overrides.acknowledge_visual_selection_transition(
                "visual-receipt-ledger",
                transition_id=first.transition_id,
            )
        )
        self.assertEqual(idempotent, acknowledged)

    def test_same_shot_old_receipt_is_explicitly_superseded(self) -> None:
        plan = self._ready("visual-same-shot-receipt")
        first_version = drama_visual_overrides.add_visual_override_candidate(
            "visual-same-shot-receipt",
            shot_id=plan.shots[0].shot_id,
            spec={"lighting": "warm"},
            source_kind="manual",
        )
        second_version = drama_visual_overrides.add_visual_override_candidate(
            "visual-same-shot-receipt",
            shot_id=plan.shots[0].shot_id,
            spec={"lighting": "cold"},
            source_kind="manual",
            derived_from=first_version.version_id,
        )
        first = drama_visual_overrides.select_visual_override(
            "visual-same-shot-receipt",
            shot_id=plan.shots[0].shot_id,
            version_id=first_version.version_id,
            expected_selection_revision=0,
            expected_current_version_id=None,
        )
        second = drama_visual_overrides.select_visual_override(
            "visual-same-shot-receipt",
            shot_id=plan.shots[0].shot_id,
            version_id=second_version.version_id,
            expected_selection_revision=1,
            expected_current_version_id=first_version.version_id,
        )
        path = drama_visual_overrides.visual_override_state_path(
            "visual-same-shot-receipt"
        )
        before_retry = path.read_bytes()
        recovered = drama_visual_overrides.select_visual_override(
            "visual-same-shot-receipt",
            shot_id=plan.shots[0].shot_id,
            version_id=first_version.version_id,
            expected_selection_revision=0,
            expected_current_version_id=None,
        )
        self.assertEqual(path.read_bytes(), before_retry)
        self.assertEqual(recovered.status, "superseded")
        self.assertEqual(
            recovered.manifest.selected_overrides[0].version_id,
            first_version.version_id,
        )
        self.assertEqual(
            recovered.state.manifest.selected_overrides[0].version_id,
            second_version.version_id,
        )
        self.assertEqual(recovered.impact, first.impact)

        drama_visual_overrides.acknowledge_visual_selection_transition(
            "visual-same-shot-receipt",
            transition_id=second.transition_id,
        )
        latest_remaining = (
            drama_visual_overrides.load_last_visual_selection_result(
                "visual-same-shot-receipt"
            )
        )
        self.assertEqual(latest_remaining.transition_id, first.transition_id)
        self.assertEqual(latest_remaining.status, "superseded")
        self.assertEqual(latest_remaining.manifest, first.manifest)

    def test_historical_receipt_rejects_rehashed_unrelated_shot_change(self) -> None:
        plan = self._ready("visual-historical-forge")
        first_version = drama_visual_overrides.add_visual_override_candidate(
            "visual-historical-forge",
            shot_id=plan.shots[0].shot_id,
            spec={"lighting": "warm"},
            source_kind="manual",
        )
        second_version = drama_visual_overrides.add_visual_override_candidate(
            "visual-historical-forge",
            shot_id=plan.shots[1].shot_id,
            spec={"transition": "hard cut"},
            source_kind="manual",
        )
        first = drama_visual_overrides.select_visual_override(
            "visual-historical-forge",
            shot_id=plan.shots[0].shot_id,
            version_id=first_version.version_id,
            expected_selection_revision=0,
            expected_current_version_id=None,
        )
        second = drama_visual_overrides.select_visual_override(
            "visual-historical-forge",
            shot_id=plan.shots[1].shot_id,
            version_id=second_version.version_id,
            expected_selection_revision=1,
            expected_current_version_id=None,
        )
        forged = second.state.model_dump()
        historical = forged["selection_transitions"][0]
        impossible_manifest = second.state.manifest.model_dump()
        impossible_manifest["selection_revision"] = 1
        impossible_manifest["manifest_fingerprint"] = self._canonical_hash(
            {
                key: value
                for key, value in impossible_manifest.items()
                if key != "manifest_fingerprint"
            }
        )
        historical["after_manifest"] = impossible_manifest
        transition_payload = {
            key: value
            for key, value in historical.items()
            if key not in {"transition_id", "transition_fingerprint"}
        }
        historical_fingerprint = self._canonical_hash(transition_payload)
        historical["transition_id"] = f"vot_{historical_fingerprint[:24]}"
        historical["transition_fingerprint"] = historical_fingerprint
        forged["state_fingerprint"] = self._canonical_hash(
            {
                key: value
                for key, value in forged.items()
                if key != "state_fingerprint"
            }
        )
        with self.assertRaisesRegex(
            ValidationError,
            "unrelated shot",
        ):
            VisualOverrideState(**forged)
        self.assertEqual(first.manifest.selection_revision, 1)

    def test_adjacent_receipts_reject_rehashed_broken_manifest_chain(self) -> None:
        plan = self._ready("visual-receipt-chain")
        first_version = drama_visual_overrides.add_visual_override_candidate(
            "visual-receipt-chain",
            shot_id=plan.shots[0].shot_id,
            spec={"lighting": "warm"},
            source_kind="manual",
        )
        second_version = drama_visual_overrides.add_visual_override_candidate(
            "visual-receipt-chain",
            shot_id=plan.shots[1].shot_id,
            spec={"transition": "hard cut"},
            source_kind="manual",
        )
        drama_visual_overrides.select_visual_override(
            "visual-receipt-chain",
            shot_id=plan.shots[0].shot_id,
            version_id=first_version.version_id,
            expected_selection_revision=0,
            expected_current_version_id=None,
        )
        second = drama_visual_overrides.select_visual_override(
            "visual-receipt-chain",
            shot_id=plan.shots[1].shot_id,
            version_id=second_version.version_id,
            expected_selection_revision=1,
            expected_current_version_id=None,
        )
        forged = second.state.model_dump()
        transition = forged["selection_transitions"][1]
        transition["impact"] = (
            drama_visual_overrides.classify_visual_selection_change(
                shot_id=plan.shots[0].shot_id,
                old_version=None,
                new_version=first_version,
            ).model_dump()
        )
        before_manifest = second.state.manifest.model_dump()
        before_manifest["selection_revision"] = 1
        before_manifest["selected_overrides"] = [
            item
            for item in before_manifest["selected_overrides"]
            if item["shot_id"] == plan.shots[1].shot_id
        ]
        before_manifest["manifest_fingerprint"] = self._canonical_hash(
            {
                key: value
                for key, value in before_manifest.items()
                if key != "manifest_fingerprint"
            }
        )
        transition["before_manifest"] = before_manifest
        transition_payload = {
            key: value
            for key, value in transition.items()
            if key not in {"transition_id", "transition_fingerprint"}
        }
        transition_fingerprint = self._canonical_hash(transition_payload)
        transition["transition_id"] = f"vot_{transition_fingerprint[:24]}"
        transition["transition_fingerprint"] = transition_fingerprint
        forged["state_fingerprint"] = self._canonical_hash(
            {
                key: value
                for key, value in forged.items()
                if key != "state_fingerprint"
            }
        )
        with self.assertRaisesRegex(
            ValidationError,
            "manifest chain is inconsistent",
        ):
            VisualOverrideState(**forged)

    def test_aba_receipt_status_means_target_current_not_lifecycle(self) -> None:
        plan = self._ready("visual-receipt-aba")
        first_version = drama_visual_overrides.add_visual_override_candidate(
            "visual-receipt-aba",
            shot_id=plan.shots[0].shot_id,
            spec={"lighting": "warm"},
            source_kind="manual",
        )
        second_version = drama_visual_overrides.add_visual_override_candidate(
            "visual-receipt-aba",
            shot_id=plan.shots[0].shot_id,
            spec={"lighting": "cold"},
            source_kind="manual",
        )
        first = drama_visual_overrides.select_visual_override(
            "visual-receipt-aba",
            shot_id=plan.shots[0].shot_id,
            version_id=first_version.version_id,
            expected_selection_revision=0,
            expected_current_version_id=None,
        )
        drama_visual_overrides.select_visual_override(
            "visual-receipt-aba",
            shot_id=plan.shots[0].shot_id,
            version_id=second_version.version_id,
            expected_selection_revision=1,
            expected_current_version_id=first_version.version_id,
        )
        drama_visual_overrides.select_visual_override(
            "visual-receipt-aba",
            shot_id=plan.shots[0].shot_id,
            version_id=first_version.version_id,
            expected_selection_revision=2,
            expected_current_version_id=second_version.version_id,
        )
        recovered = drama_visual_overrides.select_visual_override(
            "visual-receipt-aba",
            shot_id=plan.shots[0].shot_id,
            version_id=first_version.version_id,
            expected_selection_revision=0,
            expected_current_version_id=None,
        )
        self.assertEqual(recovered.status, "target_current")
        self.assertEqual(recovered.manifest, first.manifest)
        self.assertEqual(recovered.state.catalog.selection_revision, 3)

    def test_selection_input_validation_precedes_recovery_and_no_op(self) -> None:
        plan = self._ready("visual-selection-input")
        version = drama_visual_overrides.add_visual_override_candidate(
            "visual-selection-input",
            shot_id=plan.shots[0].shot_id,
            spec={"lighting": "warm"},
            source_kind="manual",
        )
        drama_visual_overrides.select_visual_override(
            "visual-selection-input",
            shot_id=plan.shots[0].shot_id,
            version_id=version.version_id,
            expected_selection_revision=0,
            expected_current_version_id=None,
        )
        for invalid_revision in (True, 1.0):
            with self.assertRaisesRegex(ValueError, "strict integer"):
                drama_visual_overrides.select_visual_override(
                    "visual-selection-input",
                    shot_id=plan.shots[0].shot_id,
                    version_id=version.version_id,
                    expected_selection_revision=invalid_revision,  # type: ignore[arg-type]
                    expected_current_version_id=version.version_id,
                )
        for invalid_shot_id in (None, True):
            with self.assertRaisesRegex(ValueError, "shot id is invalid"):
                drama_visual_overrides.select_visual_override(
                    "visual-selection-input",
                    shot_id=invalid_shot_id,  # type: ignore[arg-type]
                    version_id=version.version_id,
                    expected_selection_revision=1,
                    expected_current_version_id=version.version_id,
                )

    def test_mutated_typed_models_are_revalidated(self) -> None:
        plan = self._ready("visual-mutated-model")
        catalog = drama_visual_overrides.build_visual_override_catalog(plan)
        catalog, version = drama_visual_overrides.append_visual_override_candidate(
            plan,
            catalog,
            shot_id=plan.shots[0].shot_id,
            spec={"lighting": "warm"},
            source_kind="manual",
        )
        catalog = drama_visual_overrides.select_visual_override_candidate(
            plan,
            catalog,
            shot_id=plan.shots[0].shot_id,
            version_id=version.version_id,
            expected_selection_revision=0,
            expected_current_version_id=None,
        )
        catalog.selection_revision = 0
        with self.assertRaises(ValidationError):
            drama_visual_overrides.select_visual_override_candidate(
                plan,
                catalog,
                shot_id=plan.shots[0].shot_id,
                version_id=None,
                expected_selection_revision=0,
                expected_current_version_id=version.version_id,
            )

        fresh_catalog = drama_visual_overrides.build_visual_override_catalog(plan)
        fresh_catalog, version = drama_visual_overrides.append_visual_override_candidate(
            plan,
            fresh_catalog,
            shot_id=plan.shots[0].shot_id,
            spec={"lighting": "warm"},
            source_kind="manual",
        )
        fresh_catalog.versions[0].spec.lighting = "tampered"
        with self.assertRaises(ValidationError):
            drama_visual_overrides.build_effective_visual_override_manifest(
                plan,
                fresh_catalog,
            )

        plan.title = "mutated without fingerprint"
        with self.assertRaises(ValidationError):
            drama_visual_overrides.build_visual_override_version(
                plan,
                shot_id=plan.shots[0].shot_id,
                spec={"lighting": "night"},
                source_kind="manual",
            )

    def test_catalog_rejects_semantic_reordering_with_rehashed_payload(self) -> None:
        plan = self._ready("visual-order")
        catalog = drama_visual_overrides.build_visual_override_catalog(plan)
        for shot in plan.shots[:2]:
            catalog, _version = drama_visual_overrides.append_visual_override_candidate(
                plan,
                catalog,
                shot_id=shot.shot_id,
                spec={"lighting": f"light-{shot.source_shot_no}"},
                source_kind="manual",
            )
        payload = catalog.model_dump()
        payload["versions"].reverse()
        payload["catalog_fingerprint"] = self._canonical_hash(
            {
                key: value
                for key, value in payload.items()
                if key != "catalog_fingerprint"
            }
        )
        with self.assertRaises(ValidationError):
            VisualOverrideCatalog(**payload)


if __name__ == "__main__":
    import unittest

    unittest.main()
