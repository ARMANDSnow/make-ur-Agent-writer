"""iter106: deterministic RenderPlan and spoken-segment contract tests."""

from __future__ import annotations

import copy
import json

from pydantic import ValidationError

from src import character_designer, drama_reviewer, drama_store, storyboard_builder
from src.drama_render_plan import build_render_plan, spoken_segments_to_legacy
from src.drama_schemas import RenderPlan, character_paths, episode_paths
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
            shots[1] = copy.deepcopy(shots[0])

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
            for key in ("beat", "visual", "narration", "dialogue"):
                second[key] = copy.deepcopy(first[key])
            second["duration_seconds"] = min(30, first["duration_seconds"] + 1)

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


if __name__ == "__main__":
    import unittest

    unittest.main()
