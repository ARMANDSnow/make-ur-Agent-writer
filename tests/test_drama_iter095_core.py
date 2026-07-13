"""Iteration 095 multi-episode domain behavior (mock-only)."""

from __future__ import annotations

import json
import unittest

from src import character_designer, drama_planner, drama_reviewer, drama_store, hook_designer, storyboard_builder
from src.drama_schemas import CharacterSheet, DramaCharacter, character_paths, episode_paths
from src.utils import write_json
from tests._drama_base import DramaTestBase


class DramaIter095CoreTests(DramaTestBase):
    def test_ep3_inherits_only_series_fields(self) -> None:
        self._make_drama_workspace("ep3_setup", "重生")
        first = drama_planner.run("ep3_setup", mock=True)
        first.update(
            {
                "title": "第一集标题",
                "logline": "第一集梗概",
                "episode_mainline": "第一集主线",
                "introduces_new_characters": True,
                "hook": {"type": "悬念钩", "content": "第一集钩子"},
            }
        )
        write_json(episode_paths("ep3_setup", episode_no=1).setup_path, first)
        second = drama_planner.run("ep3_setup", mock=True, episode_no=2)
        second.update(
            {
                "title": "第二集标题",
                "logline": "第二集梗概",
                "episode_mainline": "第二集主线",
                "introduces_new_characters": True,
                "hook": {"type": "反差钩", "content": "第二集钩子"},
            }
        )
        write_json(episode_paths("ep3_setup", episode_no=2).setup_path, second)

        third = drama_planner.run("ep3_setup", mock=True, episode_no=3)

        self.assertEqual(third["episode_no"], 3)
        self.assertEqual(third["core_setup"], first["core_setup"])
        self.assertEqual(third["track"], first["track"])
        self.assertEqual(third["target_duration_seconds"], first["target_duration_seconds"])
        self.assertEqual(third["title"], "")
        self.assertEqual(third["logline"], "")
        self.assertEqual(third["episode_mainline"], "")
        self.assertFalse(third["introduces_new_characters"])
        self.assertNotIn("hook", third)

        # Empty episode-local fields are a valid initialized state and must not
        # break the downstream mock chain once a fresh hook is selected.
        write_json(episode_paths("ep3_setup", episode_no=3).setup_path, third)
        third["hook"] = hook_designer.run("ep3_setup", mock=True, episode_no=3)["hooks"][0]
        write_json(episode_paths("ep3_setup", episode_no=3).setup_path, third)
        board = storyboard_builder.run("ep3_setup", mock=True, episode_no=3)
        write_json(episode_paths("ep3_setup", episode_no=3).storyboard_path, board)
        write_json(
            character_paths("ep3_setup").sheet_path,
            character_designer.run("ep3_setup", mock=True, episode_no=3),
        )
        write_json(
            episode_paths("ep3_setup", episode_no=3).review_path,
            drama_reviewer.run("ep3_setup", mock=True, episode_no=3),
        )
        assembled = drama_store.assemble_episode("ep3_setup", episode_no=3)
        self.assertEqual(assembled["episode"]["episode_no"], 3)
        self.assertEqual(assembled["episode"]["logline"], "")

    def test_mock_hooks_are_stable_unique_and_prompt_history_is_bounded(self) -> None:
        name = "many_hooks"
        self._make_drama_workspace(name, "霸总")
        selected = []
        for episode_no in range(1, 23):
            setup = drama_planner.run(name, mock=True, episode_no=episode_no)
            write_json(episode_paths(name, episode_no=episode_no).setup_path, setup)
            candidates = hook_designer.run(name, mock=True, episode_no=episode_no)["hooks"]
            if episode_no == 22:
                repeated = hook_designer.run(name, mock=True, episode_no=episode_no)["hooks"]
                self.assertEqual(candidates, repeated)
                self.assertTrue(
                    all(
                        (row["type"], row["content"])
                        not in {(old["type"], old["content"]) for old in selected}
                        for row in candidates
                    )
                )
                break
            setup["hook"] = candidates[0]
            write_json(episode_paths(name, episode_no=episode_no).setup_path, setup)
            selected.append(candidates[0])

        used = hook_designer.collect_used_hooks(name, before_episode_no=22)
        self.assertEqual(len(used), 21)
        prompt = hook_designer.build_system_prompt(name, used_hooks=used)
        self.assertNotIn(used[0]["content"], prompt)
        self.assertIn(used[1]["content"], prompt)

    def test_appearances_are_strict_sorted_and_merged_for_all_lock_states(self) -> None:
        base = {
            "id": "c001",
            "name": "角色",
            "lora_token": "role",
        }
        row = DramaCharacter(**{**base, "appearances": [3, 1, 3, 2]})
        self.assertEqual(row.appearances, [1, 2, 3])
        for invalid in (True, "2", 2.0, 0, 101):
            with self.subTest(invalid=invalid):
                with self.assertRaises(ValueError):
                    DramaCharacter(**{**base, "appearances": [invalid]})

        existing = CharacterSheet(
            episode_no=1,
            characters=[{**base, "appearances": [1]}],
        )
        for locked in (False, True):
            with self.subTest(locked=locked):
                old = existing.model_copy(deep=True)
                old.characters[0].manual_override = locked
                incoming = CharacterSheet(
                    episode_no=3,
                    characters=[{**base, "appearances": [3], "visual_signature": "agent"}],
                )
                merged = character_designer.merge_character_sheet(old, incoming)
                self.assertEqual(merged["characters"][0]["appearances"], [1, 3])

    def _assembled_workspace(self, name: str) -> None:
        self._make_drama_workspace(name, "霸总")
        self._write_setup(name, hook=True)
        ep = episode_paths(name)
        write_json(ep.storyboard_path, storyboard_builder.run(name, mock=True))
        write_json(character_paths(name).sheet_path, character_designer.run(name, mock=True))
        write_json(ep.review_path, drama_reviewer.run(name, mock=True))
        drama_store.assemble_episode(name)

    def _make_legacy_v1_meta(self, name: str) -> None:
        ep = episode_paths(name)
        meta = json.loads(ep.meta_path.read_text(encoding="utf-8"))
        meta.pop("input_fingerprint_version", None)
        meta["input_fingerprint"] = drama_store.input_fingerprint(
            setup=json.loads(ep.setup_path.read_text(encoding="utf-8")),
            storyboard=json.loads(ep.storyboard_path.read_text(encoding="utf-8")),
            characters=json.loads(character_paths(name).sheet_path.read_text(encoding="utf-8")),
            review=json.loads(ep.review_path.read_text(encoding="utf-8")),
            version=1,
        )
        write_json(ep.meta_path, meta)

    def test_fingerprint_v2_migrates_only_fresh_legacy_and_scopes_characters(self) -> None:
        name = "fingerprint_v2"
        self._assembled_workspace(name)
        self._make_legacy_v1_meta(name)
        self.assertFalse(drama_store.is_episode_stale(name))

        self.assertEqual(drama_store.migrate_fresh_episode_fingerprints_v2(name), [1])
        meta = json.loads(episode_paths(name).meta_path.read_text(encoding="utf-8"))
        self.assertEqual(meta["input_fingerprint_version"], 2)
        self.assertTrue(meta["character_fingerprint_ids"])

        sheet_path = character_paths(name).sheet_path
        sheet = json.loads(sheet_path.read_text(encoding="utf-8"))
        sheet["episode_no"] = 2
        for row in sheet["characters"]:
            row["appearances"].append(2)
        future = dict(sheet["characters"][0])
        future.update({"id": "c099", "name": "未来角色", "lora_token": "future_role", "appearances": [2]})
        sheet["characters"].append(future)
        write_json(sheet_path, sheet)
        self.assertFalse(drama_store.is_episode_stale(name))

        sheet["characters"][0]["visual_signature"] = "旧集活跃角色的新视觉"
        write_json(sheet_path, sheet)
        self.assertTrue(drama_store.is_episode_stale(name))

    def test_stale_legacy_meta_is_not_migrated(self) -> None:
        name = "stale_legacy"
        self._assembled_workspace(name)
        self._make_legacy_v1_meta(name)
        ep = episode_paths(name)
        board = json.loads(ep.storyboard_path.read_text(encoding="utf-8"))
        board["title"] = "已改动"
        write_json(ep.storyboard_path, board)

        self.assertEqual(drama_store.migrate_fresh_episode_fingerprints_v2(name), [])
        meta = json.loads(ep.meta_path.read_text(encoding="utf-8"))
        self.assertNotIn("input_fingerprint_version", meta)

    def test_invalid_legacy_character_sheet_migrates_nothing(self) -> None:
        name = "invalid_legacy_sheet"
        self._assembled_workspace(name)
        character_paths(name).sheet_path.write_text("{}", encoding="utf-8")
        self.assertEqual(
            drama_store.migrate_fresh_episode_fingerprints_v2(name),
            [],
        )

    def test_v2_legacy_skip_fallback_keeps_shared_cast_visuals_in_scope(self) -> None:
        characters = {
            "schema_version": 1,
            "season_no": 1,
            "episode_no": 1,
            "track": "霸总",
            "characters": [
                {
                    "id": "c001",
                    "name": "共享角色",
                    "lora_token": "shared_role",
                    "visual_signature": "旧视觉",
                    "appearances": [1],
                }
            ],
        }
        common = {
            "setup": {"episode_no": 2},
            "storyboard": {"episode_no": 2},
            "review": {"episode_no": 2},
            "episode_no": 2,
            "version": 2,
        }
        frozen_ids = drama_store.episode_character_fingerprint_ids(
            characters, episode_no=2
        )
        legacy = drama_store.input_fingerprint(
            characters=characters,
            character_ids=frozen_ids,
            **common,
        )

        persisted = json.loads(json.dumps(characters))
        persisted["episode_no"] = 2
        persisted["characters"][0]["appearances"].append(2)
        self.assertEqual(
            drama_store.input_fingerprint(
                characters=persisted,
                character_ids=frozen_ids,
                **common,
            ),
            legacy,
        )

        persisted["characters"][0]["visual_signature"] = "新视觉"
        self.assertNotEqual(
            drama_store.input_fingerprint(
                characters=persisted,
                character_ids=frozen_ids,
                **common,
            ),
            legacy,
        )

    def test_empty_episode_one_appearances_freeze_current_cast(self) -> None:
        characters = {
            "schema_version": 1,
            "season_no": 1,
            "episode_no": 1,
            "track": "霸总",
            "characters": [
                {
                    "id": "c001",
                    "name": "默认角色",
                    "lora_token": "default_role",
                    "visual_signature": "旧视觉",
                    "appearances": [],
                }
            ],
        }
        frozen_ids = drama_store.episode_character_fingerprint_ids(
            characters, episode_no=1
        )
        common = {
            "setup": {"episode_no": 1},
            "storyboard": {"episode_no": 1},
            "review": {"episode_no": 1},
            "episode_no": 1,
            "version": 2,
            "character_ids": frozen_ids,
        }
        old = drama_store.input_fingerprint(characters=characters, **common)
        characters["characters"][0]["visual_signature"] = "新视觉"
        self.assertNotEqual(
            drama_store.input_fingerprint(characters=characters, **common),
            old,
        )


if __name__ == "__main__":
    unittest.main()
