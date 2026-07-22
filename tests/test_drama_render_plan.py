"""iter106: deterministic RenderPlan and spoken-segment contract tests."""

from __future__ import annotations

import copy
import hashlib
import json
from unittest.mock import patch

from pydantic import ValidationError

from src import (
    character_designer,
    drama_render_store,
    drama_reviewer,
    drama_store,
    paths,
    storyboard_builder,
)
from src.drama_event_graph import select_event_projection
from src.drama_render_plan import (
    build_render_plan,
    inspect_render_plan_source_events,
    spoken_segments_to_legacy,
)
from src.drama_source_adapter import build_source_event_graph
from src.drama_schemas import (
    RenderPlan,
    character_paths,
    drama_render_source_projection_fingerprint,
    episode_paths,
)
from src.schemas import model_to_dict
from src.utils import read_json, write_json
from tests._drama_base import DramaTestBase


class DramaRenderPlanTests(DramaTestBase):
    def _snapshot(self, name: str = "render-plan") -> drama_store.FreshEpisodeSnapshot:
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
        return drama_store.load_fresh_episode_for_render(name)

    def _mutate_and_snapshot(self, name: str, mutate) -> drama_store.FreshEpisodeSnapshot:
        storyboard_path = episode_paths(name).storyboard_path
        storyboard = read_json(storyboard_path)
        mutate(storyboard["shots"])
        for shot_no, shot in enumerate(storyboard["shots"], start=1):
            shot["shot_no"] = shot_no
        write_json(storyboard_path, storyboard)
        write_json(
            episode_paths(name).review_path,
            drama_reviewer.run(name, mock=True),
        )
        drama_store.assemble_episode(name)
        return drama_store.load_fresh_episode_for_render(name)

    def test_plan_is_strict_deterministic_and_hash_bound(self) -> None:
        snapshot = self._snapshot()
        episode_before = copy.deepcopy(snapshot.episode)
        meta_before = copy.deepcopy(snapshot.meta)
        projection_before = copy.deepcopy(snapshot.character_projection)
        first = build_render_plan(snapshot)
        second = build_render_plan(snapshot)
        self.assertEqual(model_to_dict(first), model_to_dict(second))
        self.assertEqual(snapshot.episode, episode_before)
        self.assertEqual(snapshot.meta, meta_before)
        self.assertEqual(snapshot.character_projection, projection_before)
        self.assertEqual(first.frozen_character_ids, list(snapshot.frozen_character_ids))
        self.assertEqual(first.creative_revision, snapshot.creative_revision)
        self.assertEqual(first.source_episode_sha256, snapshot.source_episode_sha256)

        extra = model_to_dict(first)
        extra["unexpected"] = True
        with self.assertRaises(ValidationError):
            RenderPlan(**extra)

        tampered = model_to_dict(first)
        tampered["title"] = "changed without rehash"
        with self.assertRaisesRegex(ValidationError, "fingerprint"):
            RenderPlan(**tampered)

        bool_episode = model_to_dict(first)
        bool_episode["episode_no"] = True
        with self.assertRaises(ValidationError):
            RenderPlan(**bool_episode)

    def test_spoken_segments_are_ordered_lossless_and_do_not_guess_speaker(self) -> None:
        self._snapshot("spoken")

        def mutate(shots: list[dict]) -> None:
            shots[0]["narration"] = "先说旁白"
            shots[0]["dialogue"] = "再说对白"
            shots[1]["narration"] = ""
            shots[1]["dialogue"] = ""

        plan = build_render_plan(self._mutate_and_snapshot("spoken", mutate))
        first_segments = [
            segment
            for segment in plan.spoken_segments
            if segment.shot_id == plan.shots[0].shot_id
        ]
        self.assertEqual([row.kind for row in first_segments], ["narration", "dialogue"])
        self.assertEqual(
            [row.sequence for row in plan.spoken_segments],
            list(range(1, len(plan.spoken_segments) + 1)),
        )
        self.assertIsNone(first_segments[1].speaker_character_id)
        self.assertEqual(plan.shots[1].audio_policy, "silent")

        legacy = spoken_segments_to_legacy(plan)
        self.assertEqual(legacy[0]["voiceover"], "先说旁白")
        self.assertEqual(legacy[0]["dialogue"], "再说对白")
        self.assertEqual(legacy[1]["voiceover"], "")
        self.assertEqual(legacy[1]["dialogue"], "")

        bad_speaker = model_to_dict(plan)
        dialogue = next(
            row for row in bad_speaker["spoken_segments"] if row["kind"] == "dialogue"
        )
        dialogue["speaker_character_id"] = "c001"
        with self.assertRaises(ValidationError):
            RenderPlan(**bad_speaker)

        future_policy = model_to_dict(plan)
        future_policy["shots"][0]["audio_policy"] = "source_only"
        with self.assertRaises(ValidationError):
            RenderPlan(**future_policy)

    def test_shot_ids_survive_reorder_and_execution_only_edits(self) -> None:
        snapshot = self._snapshot("shot-id")
        original = build_render_plan(snapshot)

        def reorder(shots: list[dict]) -> None:
            shots[0], shots[1] = shots[1], shots[0]

        reordered = build_render_plan(self._mutate_and_snapshot("shot-id", reorder))
        original_ids = {shot.source_fingerprint: shot.shot_id for shot in original.shots}
        reordered_ids = {shot.source_fingerprint: shot.shot_id for shot in reordered.shots}
        self.assertEqual(original_ids, reordered_ids)
        self.assertNotEqual(original.plan_fingerprint, reordered.plan_fingerprint)

        self._snapshot("shot-id-execution")
        execution_original = build_render_plan(
            drama_store.load_fresh_episode_for_render("shot-id-execution")
        )

        def edit_execution(shots: list[dict]) -> None:
            shots[0]["duration_seconds"] += 1
            shots[0]["camera_move"] = "推"
            shots[0]["ai_draw_prompt"] += ", updated"

        execution = build_render_plan(
            self._mutate_and_snapshot("shot-id-execution", edit_execution)
        )
        self.assertEqual(execution_original.shots[0].shot_id, execution.shots[0].shot_id)
        self.assertNotEqual(
            execution_original.shots[0].source_fingerprint,
            execution.shots[0].source_fingerprint,
        )

        self._snapshot("shot-id-semantic")
        semantic_original = build_render_plan(
            drama_store.load_fresh_episode_for_render("shot-id-semantic")
        )

        def edit_semantic(shots: list[dict]) -> None:
            shots[0]["visual"] += "，新的动作"

        semantic = build_render_plan(
            self._mutate_and_snapshot("shot-id-semantic", edit_semantic)
        )
        self.assertNotEqual(
            semantic_original.shots[0].shot_id,
            semantic.shots[0].shot_id,
        )

    def test_duplicate_semantic_shots_get_deterministic_unique_ids(self) -> None:
        self._snapshot("duplicates")

        def duplicate(shots: list[dict]) -> None:
            original_duration = shots[1]["duration_seconds"]
            shots[1] = copy.deepcopy(shots[0])
            shots[2]["duration_seconds"] += (
                original_duration - shots[1]["duration_seconds"]
            )

        changed = self._mutate_and_snapshot("duplicates", duplicate)
        one = build_render_plan(changed)
        two = build_render_plan(changed)
        ids = [shot.shot_id for shot in one.shots]
        self.assertEqual(ids, [shot.shot_id for shot in two.shots])
        self.assertEqual(len(ids), len(set(ids)))

    def test_ambiguous_duplicate_execution_variants_fail_closed(self) -> None:
        self._snapshot("ambiguous-duplicates")

        def duplicate_identity(shots: list[dict]) -> None:
            first = shots[0]
            second = shots[1]
            original_duration = second["duration_seconds"]
            for key in ("beat", "visual", "narration", "dialogue"):
                second[key] = copy.deepcopy(first[key])
            second["duration_seconds"] = min(30, first["duration_seconds"] + 1)
            shots[2]["duration_seconds"] += (
                original_duration - second["duration_seconds"]
            )

        snapshot = self._mutate_and_snapshot(
            "ambiguous-duplicates",
            duplicate_identity,
        )
        with self.assertRaisesRegex(ValueError, "persistent shot ids"):
            build_render_plan(snapshot)

    def test_builder_rejects_mutated_snapshot_and_keeps_private_inputs_out(self) -> None:
        snapshot = self._snapshot("privacy")
        plan = build_render_plan(snapshot)
        snapshot.episode["storyboard"][0]["provider_response"] = "private"
        with self.assertRaisesRegex(ValueError, "lineage|fingerprint"):
            build_render_plan(snapshot)

        plan_text = json.dumps(model_to_dict(plan), ensure_ascii=False)
        self.assertNotIn("agent_reviews", plan_text)
        self.assertNotIn(str(episode_paths("privacy").root), plan_text)
        self.assertNotIn("provider_response", plan_text)

    def test_builder_rechecks_approve_verdict_on_mutable_snapshot(self) -> None:
        for verdict in ("Reject", "Abstain"):
            with self.subTest(verdict=verdict):
                snapshot = self._snapshot(f"verdict-{verdict.lower()}")
                snapshot.meta["verdict"] = verdict
                with self.assertRaisesRegex(ValueError, "lineage|fingerprint"):
                    build_render_plan(snapshot)

    def test_source_event_projection_is_exact_optional_render_lineage(self) -> None:
        snapshot = self._snapshot("source-events")
        episode_before = copy.deepcopy(snapshot.episode)
        rolling = json.dumps(
            {
                "chapters": [
                    {"chapter_id": "v1_ch001", "chapter_no": 1, "summary": "甲"},
                    {"chapter_id": "v1_ch002", "chapter_no": 2, "summary": "乙"},
                ],
                "compressed_older": [],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        adapted = build_source_event_graph(
            workspace="source-events",
            graph_family_id="season_1",
            rolling_summary_bytes=rolling,
            max_spoiler_boundary=2,
        )
        assert adapted.graph is not None
        first_id, second_id = [event.event_id for event in adapted.graph.events]
        projection = select_event_projection(
            adapted.graph,
            selected_event_ids=[first_id],
            allowed_source_chapter_ids=["v1_ch001", "v1_ch002"],
            max_spoiler_boundary=2,
        )
        plan = build_render_plan(
            snapshot,
            source_event_projection=projection,
            source_event_graph_family_id="season_1",
            source_event_snapshot_fingerprint=(
                adapted.source_snapshot_fingerprint
            ),
        )
        self.assertEqual(plan.source_event_ids, [first_id])
        self.assertEqual(plan.source_event_graph_id, adapted.graph.graph_id)
        self.assertEqual(
            plan.source_event_projection_fingerprint,
            drama_render_source_projection_fingerprint(
                graph_fingerprint=projection.graph_fingerprint,
                selected_event_ids=list(projection.selected_event_ids),
                allowed_source_chapter_ids=list(
                    projection.allowed_source_chapter_ids
                ),
                max_spoiler_boundary=projection.max_spoiler_boundary,
            ),
        )
        self.assertEqual(
            inspect_render_plan_source_events(
                plan,
                projection,
                adapted.source_snapshot_fingerprint,
            ),
            "fresh",
        )
        self.assertEqual(
            inspect_render_plan_source_events(
                plan,
                projection,
                "0" * 64,
            ),
            "stale",
        )
        self.assertEqual(inspect_render_plan_source_events(plan, None), "stale")
        other = select_event_projection(
            adapted.graph,
            selected_event_ids=[second_id],
            allowed_source_chapter_ids=["v1_ch001", "v1_ch002"],
            max_spoiler_boundary=2,
        )
        self.assertEqual(inspect_render_plan_source_events(plan, other), "stale")
        self.assertEqual(snapshot.episode, episode_before)

        unbound = build_render_plan(snapshot)
        self.assertEqual(inspect_render_plan_source_events(unbound, None), "unbound")
        self.assertEqual(inspect_render_plan_source_events(unbound, projection), "unbound")
        legacy_payload = model_to_dict(unbound)
        legacy_fingerprint = legacy_payload.pop("plan_fingerprint")
        for key in (
            "source_event_graph_id",
            "source_event_graph_fingerprint",
            "source_event_graph_records",
            "source_event_projection_fingerprint",
            "source_event_workspace_scope_fingerprint",
            "source_event_scope_fingerprint",
            "source_event_graph_family_id",
            "source_event_snapshot_fingerprint",
            "source_event_allowed_chapter_ids",
            "source_event_spoiler_boundary",
        ):
            legacy_payload.pop(key, None)
        legacy_payload.pop("art_direction_resolution", None)
        expected_legacy = hashlib.sha256(
            json.dumps(
                legacy_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        self.assertEqual(legacy_fingerprint, expected_legacy)

        other_snapshot = self._snapshot("source-events-other")
        with self.assertRaisesRegex(ValueError, "another workspace"):
            build_render_plan(
                other_snapshot,
                source_event_projection=projection,
                source_event_graph_family_id="season_1",
                source_event_snapshot_fingerprint=adapted.source_snapshot_fingerprint,
            )
        forged = projection.model_copy(
            update={"workspace_scope_fingerprint": "0" * 64}
        )
        with self.assertRaises(ValueError):
            build_render_plan(
                snapshot,
                source_event_projection=forged,
                source_event_graph_family_id="season_1",
                source_event_snapshot_fingerprint=adapted.source_snapshot_fingerprint,
            )
        with self.assertRaises(ValueError):
            build_render_plan(
                snapshot,
                source_event_projection=projection,
                source_event_graph_family_id="season_2",
                source_event_snapshot_fingerprint=adapted.source_snapshot_fingerprint,
            )
        other_family = build_source_event_graph(
            workspace="source-events",
            graph_family_id="season_2",
            rolling_summary_bytes=rolling,
            max_spoiler_boundary=2,
        )
        assert other_family.graph is not None
        other_family_projection = select_event_projection(
            other_family.graph,
            selected_event_ids=[other_family.graph.events[0].event_id],
            allowed_source_chapter_ids=["v1_ch001", "v1_ch002"],
            max_spoiler_boundary=2,
        )
        self.assertEqual(
            inspect_render_plan_source_events(
                plan,
                other_family_projection,
                other_family.source_snapshot_fingerprint,
            ),
            "stale",
        )

        partial = model_to_dict(plan)
        partial["source_event_graph_fingerprint"] = None
        partial["plan_fingerprint"] = "0" * 64
        with self.assertRaises(ValidationError):
            RenderPlan(**partial)

        for field, replacement in (
            ("source_event_graph_family_id", "season_2"),
            ("source_event_scope_fingerprint", "0" * 64),
        ):
            spliced = model_to_dict(plan)
            spliced[field] = replacement
            fingerprint_payload = dict(spliced)
            fingerprint_payload.pop("plan_fingerprint")
            spliced["plan_fingerprint"] = hashlib.sha256(
                json.dumps(
                    fingerprint_payload,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                    allow_nan=False,
                ).encode("utf-8")
            ).hexdigest()
            with self.assertRaises(ValidationError):
                RenderPlan(**spliced)
        paired = model_to_dict(plan)
        paired["source_event_graph_family_id"] = "season_2"
        from src.drama_schemas import drama_event_graph_family_scope_fingerprint

        paired["source_event_scope_fingerprint"] = (
            drama_event_graph_family_scope_fingerprint(
                workspace_scope_fingerprint=(
                    paired["source_event_workspace_scope_fingerprint"]
                ),
                graph_family_id="season_2",
            )
        )
        paired_payload = dict(paired)
        paired_payload.pop("plan_fingerprint")
        paired["plan_fingerprint"] = hashlib.sha256(
            json.dumps(
                paired_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        with self.assertRaises(ValidationError):
            RenderPlan(**paired)
        nonmember = model_to_dict(plan)
        nonmember["source_event_ids"] = ["dse_ffffffffffffffffffffffff"]
        nonmember_payload = dict(nonmember)
        nonmember_payload.pop("plan_fingerprint")
        nonmember["plan_fingerprint"] = hashlib.sha256(
            json.dumps(
                nonmember_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        with self.assertRaises(ValidationError):
            RenderPlan(**nonmember)

        fully_rehashed = model_to_dict(plan)
        fully_rehashed["source_event_graph_family_id"] = "season_2"
        fully_rehashed["source_event_scope_fingerprint"] = (
            drama_event_graph_family_scope_fingerprint(
                workspace_scope_fingerprint=(
                    fully_rehashed["source_event_workspace_scope_fingerprint"]
                ),
                graph_family_id="season_2",
            )
        )
        graph_identity = {
            "schema_version": 1,
            "workspace_scope_fingerprint": (
                fully_rehashed["source_event_workspace_scope_fingerprint"]
            ),
            "scope_fingerprint": fully_rehashed["source_event_scope_fingerprint"],
            "event_records": fully_rehashed["source_event_graph_records"],
        }
        fully_rehashed["source_event_graph_fingerprint"] = hashlib.sha256(
            json.dumps(
                graph_identity,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        fully_rehashed["source_event_graph_id"] = (
            "deg_" + fully_rehashed["source_event_graph_fingerprint"][:24]
        )
        fully_rehashed_payload = dict(fully_rehashed)
        fully_rehashed_payload.pop("plan_fingerprint")
        fully_rehashed["plan_fingerprint"] = hashlib.sha256(
            json.dumps(
                fully_rehashed_payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        with self.assertRaises(ValidationError):
            RenderPlan(**fully_rehashed)

    def test_render_store_rebuilds_current_production_source_binding(self) -> None:
        snapshot = self._snapshot("source-store")
        rolling = {
            "chapters": [
                {"chapter_id": "v1_ch001", "chapter_no": 1, "summary": "甲"},
                {"chapter_id": "v1_ch002", "chapter_no": 2, "summary": "乙"},
            ],
            "compressed_older": [],
        }
        rolling_bytes = json.dumps(
            rolling,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        rolling_path = (
            paths.WORKSPACE_DIR
            / "source-store"
            / "outputs"
            / "drafts"
            / "rolling_chapter_summary.json"
        )
        rolling_path.parent.mkdir(parents=True, exist_ok=True)
        rolling_path.write_bytes(rolling_bytes)
        adapted = build_source_event_graph(
            workspace="source-store",
            graph_family_id="season_1",
            rolling_summary_bytes=rolling_bytes,
            max_spoiler_boundary=2,
        )
        assert adapted.graph is not None
        selected = [adapted.graph.events[0].event_id]
        created = drama_render_store.create_render_plan(
            "source-store",
            source_event_graph_family_id="season_1",
            source_event_ids=selected,
            source_event_max_spoiler_boundary=2,
        )
        self.assertEqual(created.source_event_ids, selected)
        self.assertEqual(created.source_event_graph_family_id, "season_1")
        self.assertEqual(
            drama_render_store.inspect_render_plan("source-store").state,
            "fresh",
        )
        self.assertEqual(
            drama_render_store.load_fresh_render_plan("source-store"),
            created,
        )
        self.assertEqual(snapshot.episode, drama_store.load_fresh_episode_for_render("source-store").episode)

        rolling["chapters"][0]["summary"] = "甲发生变化"
        rolling_path.write_text(
            json.dumps(rolling, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        drift = drama_render_store.inspect_render_plan("source-store")
        self.assertEqual(drift.state, "stale")
        self.assertIn("source_event_snapshot_mismatch", drift.reasons)

        rolling_path.unlink()
        blocked = drama_render_store.inspect_render_plan("source-store")
        self.assertEqual(blocked.state, "blocked_source")
        self.assertIn("source_event_source_missing", blocked.reasons)

    def test_render_store_precommit_source_drift_preserves_old_plan(self) -> None:
        name = "source-precommit"
        self._snapshot(name)
        rolling = {
            "chapters": [
                {"chapter_id": "v1_ch001", "chapter_no": 1, "summary": "甲"}
            ],
            "compressed_older": [],
        }
        rolling_path = (
            paths.WORKSPACE_DIR
            / name
            / "outputs"
            / "drafts"
            / "rolling_chapter_summary.json"
        )
        rolling_path.parent.mkdir(parents=True, exist_ok=True)
        rolling_path.write_text(
            json.dumps(rolling, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        adapted = build_source_event_graph(
            workspace=name,
            graph_family_id="season_1",
            rolling_summary_bytes=rolling_path.read_bytes(),
        )
        assert adapted.graph is not None
        event_id = adapted.graph.events[0].event_id
        old = drama_render_store.create_render_plan(name)
        target = drama_render_store.render_plan_path(name)
        old_bytes = target.read_bytes()
        original_write = drama_render_store._write_render_plan

        def race(*args, **kwargs):
            rolling["chapters"][0]["summary"] = "并发变化"
            rolling_path.write_text(
                json.dumps(rolling, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            return original_write(*args, **kwargs)

        with patch.object(drama_render_store, "_write_render_plan", side_effect=race):
            with self.assertRaisesRegex(
                drama_render_store.RenderPlanStoreError,
                "source event projection changed concurrently",
            ):
                drama_render_store.create_render_plan(
                    name,
                    source_event_graph_family_id="season_1",
                    source_event_ids=[event_id],
                    source_event_max_spoiler_boundary=1,
                    replace_stale=True,
                )
        self.assertEqual(target.read_bytes(), old_bytes)
        self.assertEqual(drama_render_store.inspect_stored_render_plan(name).plan, old)


if __name__ == "__main__":
    import unittest

    unittest.main()
