"""iter 082: drama episode assembly tests."""

from __future__ import annotations

import json
import unittest

from src import character_designer, drama_reviewer, drama_store, storyboard_builder
from src.drama_schemas import DramaEpisode, DramaEpisodeMeta, episode_paths, character_paths
from tests._drama_base import DramaTestBase


class DramaStoreTests(DramaTestBase):
    def _workspace(self, name: str = "store", *, with_review: bool = True) -> None:
        self._make_drama_workspace(name, "霸总")
        self._write_setup(name, hook=True)
        board = storyboard_builder.run(name, mock=True)
        ep = episode_paths(name)
        ep.storyboard_path.parent.mkdir(parents=True, exist_ok=True)
        ep.storyboard_path.write_text(json.dumps(board, ensure_ascii=False), encoding="utf-8")
        sheet = character_designer.run(name, mock=True)
        cp = character_paths(name)
        cp.sheet_path.parent.mkdir(parents=True, exist_ok=True)
        cp.sheet_path.write_text(json.dumps(sheet, ensure_ascii=False), encoding="utf-8")
        if with_review:
            review = drama_reviewer.run(name, mock=True)
            ep.review_path.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")

    def test_assemble_writes_episode_and_meta(self) -> None:
        self._workspace()
        result = drama_store.assemble_episode("store")
        episode = DramaEpisode(**result["episode"])
        meta = DramaEpisodeMeta(**result["meta"])
        self.assertEqual(episode.episode_no, 1)
        self.assertEqual(episode.estimated_duration_seconds, 60)
        self.assertEqual(episode.self_check["highlight_shot_no"], 4)
        self.assertEqual(meta.verdict, "Approve")
        self.assertFalse(meta.needs_human_review)
        self.assertTrue(episode_paths("store").episode_path.is_file())
        self.assertTrue(episode_paths("store").meta_path.is_file())

    def test_assemble_is_idempotent(self) -> None:
        self._workspace()
        first = drama_store.assemble_episode("store")
        second = drama_store.assemble_episode("store")
        self.assertEqual(first, second)

    def test_missing_review_blocks_assembly(self) -> None:
        self._workspace("no_review", with_review=False)
        with self.assertRaisesRegex(FileNotFoundError, "review"):
            drama_store.assemble_episode("no_review")

    def test_stale_detects_changed_storyboard(self) -> None:
        self._workspace()
        drama_store.assemble_episode("store")
        self.assertFalse(drama_store.is_episode_stale("store"))
        ep = episode_paths("store")
        data = json.loads(ep.storyboard_path.read_text(encoding="utf-8"))
        data["title"] = "用户改过的标题"
        ep.storyboard_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        self.assertTrue(drama_store.is_episode_stale("store"))

    def test_list_and_detail(self) -> None:
        self._workspace()
        drama_store.assemble_episode("store")
        items = drama_store.list_episodes("store")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["episode_no"], 1)
        detail = drama_store.episode_detail("store")
        self.assertEqual(detail["episode"]["episode_no"], 1)
        self.assertFalse(detail["stale"])


if __name__ == "__main__":
    unittest.main()
