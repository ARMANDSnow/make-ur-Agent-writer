"""iter146: disposable text-free H3 context memory contract tests."""

from __future__ import annotations

import json
import os
import socket
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from src import (
    character_designer,
    drama_context_memory,
    drama_render_store,
    drama_reviewer,
    drama_store,
    paths,
    storyboard_builder,
)
from src.drama_context_memory import (
    DramaContextMemoryError,
    build_context_memory_cache,
    context_keyword_hash,
    context_memory_policy_fingerprint,
    create_context_memory_cache,
    inspect_context_memory_binding,
    inspect_context_memory_cache,
    load_context_memory_cache,
    query_context_memory,
)
from src.drama_event_graph import select_event_projection
from src.drama_render_plan import build_render_plan
from src.drama_schemas import (
    DramaContextMemoryCache,
    DramaContextMemoryRecord,
    character_paths,
    episode_paths,
)
from src.drama_source_adapter import build_source_event_graph
from src.schemas import model_to_dict
from src.utils import write_json
from tests._drama_base import DramaTestBase


def _bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


class DramaContextMemoryTests(DramaTestBase):
    def _snapshot(self, name: str) -> drama_store.FreshEpisodeSnapshot:
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

    def _source_bytes(self) -> tuple[bytes, bytes]:
        rolling = {
            "chapters": [
                {
                    "chapter_id": "v1_ch001",
                    "chapter_no": 1,
                    "summary": "绝不能进入 H3 cache 的私有摘要甲",
                    "key_events": ["绝不能进入 H3 cache 的私有事件甲"],
                },
                {
                    "chapter_id": "v1_ch002",
                    "chapter_no": 2,
                    "summary": "绝不能进入 H3 cache 的私有摘要乙",
                    "key_events": [],
                },
                {
                    "chapter_id": "v1_ch003",
                    "chapter_no": 3,
                    "summary": "绝不能进入 H3 cache 的私有摘要丙",
                    "key_events": [],
                },
            ],
            "compressed_older": [],
        }
        entity = {
            "entities": [
                {"id": "c001", "name": "不应保存的私有角色名"},
                {"id": "c002", "name": "不应保存的另一角色名"},
            ],
            "relationships": [
                {
                    "src_id": "c001",
                    "dst_id": "c002",
                    "relation_type": "不应保存的关系文本",
                    "timeline": [
                        {
                            "chapter_id": "v1_ch001",
                            "active": True,
                            "state": "不应保存的状态文本",
                        }
                    ],
                }
            ],
        }
        return _bytes(rolling), _bytes(entity)

    def _pure_inputs(self, name: str = "context-pure"):
        snapshot = self._snapshot(name)
        rolling, entity = self._source_bytes()
        adapted = build_source_event_graph(
            workspace=name,
            graph_family_id="season_1",
            rolling_summary_bytes=rolling,
            entity_graph_bytes=entity,
            max_spoiler_boundary=3,
        )
        assert adapted.graph is not None
        selected = [item.event_id for item in adapted.graph.events]
        allowed = sorted(
            source.chapter_id
            for event in adapted.graph.events
            for source in event.source_chapters
        )
        projection = select_event_projection(
            adapted.graph,
            selected_event_ids=selected,
            allowed_source_chapter_ids=allowed,
            max_spoiler_boundary=3,
        )
        plan = build_render_plan(
            snapshot,
            source_event_projection=projection,
            source_event_graph_family_id="season_1",
            source_event_snapshot_fingerprint=adapted.source_snapshot_fingerprint,
        )
        return adapted, projection, plan

    def _production_inputs(self, name: str = "context-store"):
        snapshot = self._snapshot(name)
        rolling, entity = self._source_bytes()
        root = Path(self._tmp.name) / name
        rolling_path = root / "outputs" / "drafts" / "rolling_chapter_summary.json"
        entity_path = root / "data" / "entity_graph.json"
        rolling_path.parent.mkdir(parents=True, exist_ok=True)
        entity_path.parent.mkdir(parents=True, exist_ok=True)
        rolling_path.write_bytes(rolling)
        entity_path.write_bytes(entity)
        adapted = build_source_event_graph(
            workspace=name,
            graph_family_id="season_1",
            rolling_summary_bytes=rolling,
            entity_graph_bytes=entity,
            max_spoiler_boundary=3,
        )
        assert adapted.graph is not None
        selected = [item.event_id for item in adapted.graph.events]
        plan = drama_render_store.create_render_plan(
            name,
            source_event_graph_family_id="season_1",
            source_event_ids=selected,
            source_event_max_spoiler_boundary=3,
        )
        return snapshot, rolling_path, plan, selected

    def test_pure_cache_is_deterministic_text_free_and_zero_network(self) -> None:
        adapted, projection, plan = self._pure_inputs()
        policy = context_memory_policy_fingerprint(
            {"prompt.md": b"strategy-v1", "skill.txt": b"skill-v1"}
        )
        keyword = "  线 索  "
        with patch.object(socket, "socket", side_effect=AssertionError("network")):
            first = build_context_memory_cache(
                graph=adapted.graph,
                projection=projection,
                render_plan=plan,
                graph_family_id="season_1",
                source_snapshot_fingerprint=adapted.source_snapshot_fingerprint,
                policy_fingerprint=policy,
                recent_limit=2,
                summary_event_ids=list(projection.selected_event_ids[:2]),
                keyword_event_ids={keyword: [projection.selected_event_ids[-1]]},
            )
            second = build_context_memory_cache(
                graph=adapted.graph,
                projection=projection,
                render_plan=plan,
                graph_family_id="season_1",
                source_snapshot_fingerprint=adapted.source_snapshot_fingerprint,
                policy_fingerprint=policy,
                recent_limit=2,
                summary_event_ids=list(projection.selected_event_ids[:2]),
                keyword_event_ids={keyword: [projection.selected_event_ids[-1]]},
            )
            query = query_context_memory(first, keywords=["线 索"])
        self.assertEqual(first, second)
        self.assertEqual(query.keyword_event_ids, (projection.selected_event_ids[-1],))
        self.assertEqual(len(query.recent_event_ids), 2)
        self.assertEqual(query.combined_event_ids[0], projection.selected_event_ids[-1])
        keyword_record = next(
            item
            for item in first.records
            if item.event_id == projection.selected_event_ids[-1]
        )
        self.assertEqual(
            keyword_record.keyword_hashes,
            (context_keyword_hash("线 索"),),
        )
        public = json.dumps(model_to_dict(first), ensure_ascii=False)
        for secret in (
            "私有摘要",
            "私有事件",
            "私有角色名",
            "关系文本",
            "状态文本",
            "线 索",
            "strategy-v1",
            "skill-v1",
        ):
            self.assertNotIn(secret, public)

    def test_binding_detects_source_policy_projection_and_render_drift(self) -> None:
        adapted, projection, plan = self._pure_inputs("context-drift")
        policy = context_memory_policy_fingerprint({"policy.md": b"v1"})
        cache = build_context_memory_cache(
            graph=adapted.graph,
            projection=projection,
            render_plan=plan,
            graph_family_id="season_1",
            source_snapshot_fingerprint=adapted.source_snapshot_fingerprint,
            policy_fingerprint=policy,
        )
        self.assertEqual(
            inspect_context_memory_binding(
                cache,
                graph=adapted.graph,
                projection=projection,
                render_plan=plan,
                graph_family_id="season_1",
                source_snapshot_fingerprint=adapted.source_snapshot_fingerprint,
                policy_fingerprint=policy,
            ),
            (),
        )
        reasons = inspect_context_memory_binding(
            cache,
            graph=adapted.graph,
            projection=projection,
            render_plan=plan,
            graph_family_id="season_2",
            source_snapshot_fingerprint="f" * 64,
            policy_fingerprint=context_memory_policy_fingerprint(
                {"policy.md": b"v2"}
            ),
        )
        self.assertIn("graph_family_mismatch", reasons)
        self.assertIn("source_snapshot_mismatch", reasons)
        self.assertIn("policy_mismatch", reasons)

        subset = select_event_projection(
            adapted.graph,
            selected_event_ids=[projection.selected_event_ids[0]],
            allowed_source_chapter_ids=projection.allowed_source_chapter_ids,
            max_spoiler_boundary=3,
        )
        subset_plan = build_render_plan(
            drama_store.load_fresh_episode_for_render("context-drift"),
            source_event_projection=subset,
            source_event_graph_family_id="season_1",
            source_event_snapshot_fingerprint=adapted.source_snapshot_fingerprint,
        )
        subset_reasons = inspect_context_memory_binding(
            cache,
            graph=adapted.graph,
            projection=subset,
            render_plan=subset_plan,
            graph_family_id="season_1",
            source_snapshot_fingerprint=adapted.source_snapshot_fingerprint,
            policy_fingerprint=policy,
        )
        self.assertIn("source_projection_mismatch", subset_reasons)
        self.assertIn("render_plan_mismatch", subset_reasons)

        rehashed = model_to_dict(cache)
        rehashed["records"][0]["source_fingerprint"] = "a" * 64
        record_payload = {
            key: value
            for key, value in rehashed["records"][0].items()
            if key != "record_fingerprint"
        }
        from src.drama_schemas import _canonical_sha256

        rehashed["records"][0]["record_fingerprint"] = _canonical_sha256(
            record_payload
        )
        cache_payload = {
            key: value
            for key, value in rehashed.items()
            if key not in {"cache_id", "cache_fingerprint"}
        }
        rehashed["cache_fingerprint"] = _canonical_sha256(cache_payload)
        rehashed["cache_id"] = "dcm_" + rehashed["cache_fingerprint"][:24]
        self.assertIn(
            "record_source_mismatch",
            inspect_context_memory_binding(
                DramaContextMemoryCache(**rehashed),
                graph=adapted.graph,
                projection=projection,
                render_plan=plan,
                graph_family_id="season_1",
                source_snapshot_fingerprint=adapted.source_snapshot_fingerprint,
                policy_fingerprint=policy,
            ),
        )

    def test_schema_rejects_tamper_cross_membership_and_plaintext_keyword(self) -> None:
        adapted, projection, plan = self._pure_inputs("context-tamper")
        cache = build_context_memory_cache(
            graph=adapted.graph,
            projection=projection,
            render_plan=plan,
            graph_family_id="season_1",
            source_snapshot_fingerprint=adapted.source_snapshot_fingerprint,
            policy_fingerprint=context_memory_policy_fingerprint({"p": b"v"}),
        )
        tampered = model_to_dict(cache)
        tampered["episode_no"] = 2
        with self.assertRaises(ValidationError):
            DramaContextMemoryCache(**tampered)

        from src.drama_schemas import _canonical_sha256

        rehashed_scope = model_to_dict(cache)
        rehashed_scope["episode_no"] = 2
        scope_payload = {
            key: value
            for key, value in rehashed_scope.items()
            if key not in {"cache_id", "cache_fingerprint"}
        }
        rehashed_scope["cache_fingerprint"] = _canonical_sha256(scope_payload)
        rehashed_scope["cache_id"] = (
            "dcm_" + rehashed_scope["cache_fingerprint"][:24]
        )
        self.assertIn(
            "episode_scope_mismatch",
            inspect_context_memory_binding(
                DramaContextMemoryCache(**rehashed_scope),
                graph=adapted.graph,
                projection=projection,
                render_plan=plan,
                graph_family_id="season_1",
                source_snapshot_fingerprint=adapted.source_snapshot_fingerprint,
                policy_fingerprint=cache.policy_fingerprint,
            ),
        )

        nonmember = model_to_dict(cache)
        nonmember["records"][0]["event_id"] = "dse_ffffffffffffffffffffffff"
        with self.assertRaises(ValidationError):
            DramaContextMemoryCache(**nonmember)

        with self.assertRaises(DramaContextMemoryError):
            build_context_memory_cache(
                graph=adapted.graph,
                projection=projection,
                render_plan=plan,
                graph_family_id="season_1",
                source_snapshot_fingerprint=adapted.source_snapshot_fingerprint,
                policy_fingerprint="0" * 64,
                keyword_event_ids={"bad\nkeyword": [projection.selected_event_ids[0]]},
            )

    def test_production_store_roundtrip_delete_and_policy_drift(self) -> None:
        name = "context-store"
        snapshot, _rolling_path, plan, selected = self._production_inputs(name)
        episode_before = json.dumps(snapshot.episode, sort_keys=True, ensure_ascii=False)
        render_before = drama_render_store.render_plan_path(name).read_bytes()
        with patch.object(socket, "socket", side_effect=AssertionError("network")):
            cache = create_context_memory_cache(
                name,
                recent_limit=2,
                keyword_event_ids={"角色": [selected[0]]},
            )
            replay = create_context_memory_cache(
                name,
                recent_limit=2,
                keyword_event_ids={"角色": [selected[0]]},
            )
            inspected = inspect_context_memory_cache(name, keywords=["角色"])
        self.assertEqual(cache, replay)
        self.assertEqual(inspected.state, "fresh")
        self.assertEqual(inspected.query.keyword_event_ids, (selected[0],))
        self.assertEqual(
            load_context_memory_cache(name, season_no=1, episode_no=1),
            cache,
        )
        cache_path = drama_context_memory.context_memory_path(
            name,
            season_no=1,
            episode_no=1,
        )
        cache_path.unlink()
        self.assertEqual(inspect_context_memory_cache(name).state, "missing")
        self.assertEqual(
            json.dumps(
                drama_store.load_fresh_episode_for_render(name).episode,
                sort_keys=True,
                ensure_ascii=False,
            ),
            episode_before,
        )
        self.assertEqual(drama_render_store.render_plan_path(name).read_bytes(), render_before)
        self.assertEqual(plan.plan_fingerprint, drama_render_store.load_fresh_render_plan(name).plan_fingerprint)

        create_context_memory_cache(name, recent_limit=2)
        with patch.object(
            drama_context_memory,
            "load_default_context_policy_fingerprint",
            return_value="f" * 64,
        ):
            stale = inspect_context_memory_cache(name)
        self.assertEqual(stale.state, "stale")
        self.assertIn("policy_mismatch", stale.reasons)

    def test_source_drift_blocks_cache_and_symlink_is_invalid(self) -> None:
        name = "context-boundary"
        _snapshot, rolling_path, _plan, _selected = self._production_inputs(name)
        create_context_memory_cache(name)
        rolling = json.loads(rolling_path.read_text(encoding="utf-8"))
        rolling["chapters"][0]["summary"] += "变化"
        rolling_path.write_bytes(_bytes(rolling))
        blocked = inspect_context_memory_cache(name)
        self.assertEqual(blocked.state, "blocked_source")
        self.assertEqual(blocked.reasons, ("current_source_unavailable",))

        other = self._snapshot("context-symlink")
        del other
        target = drama_context_memory.context_memory_path(
            "context-symlink",
            season_no=1,
            episode_no=1,
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        external = Path(self._tmp.name) / "external-private.txt"
        external.write_text("do-not-read", encoding="utf-8")
        target.symlink_to(external)
        self.assertEqual(
            inspect_context_memory_cache("context-symlink").state,
            "invalid",
        )
        self.assertEqual(external.read_text(encoding="utf-8"), "do-not-read")

    def test_exact_replay_and_precommit_recheck_preserve_current_cache(self) -> None:
        name = "context-replay-race"
        self._production_inputs(name)
        baseline = create_context_memory_cache(name, recent_limit=2)
        target = drama_context_memory.context_memory_path(
            name,
            season_no=1,
            episode_no=1,
        )
        baseline_bytes = target.read_bytes()
        with patch.object(
            drama_context_memory,
            "load_default_context_policy_fingerprint",
            side_effect=[baseline.policy_fingerprint, "f" * 64],
        ):
            with self.assertRaisesRegex(
                DramaContextMemoryError,
                "changed before replay",
            ):
                create_context_memory_cache(name, recent_limit=2)
        self.assertEqual(target.read_bytes(), baseline_bytes)

        current = drama_context_memory._load_current_context(name, episode_no=1)
        changed = replace(current, policy_fingerprint="e" * 64)
        with patch.object(
            drama_context_memory,
            "_load_current_context",
            side_effect=[current, changed],
        ):
            with self.assertRaisesRegex(
                DramaContextMemoryError,
                "changed before commit",
            ):
                create_context_memory_cache(
                    name,
                    recent_limit=1,
                    replace_stale=True,
                )
        self.assertEqual(target.read_bytes(), baseline_bytes)
        replaced = create_context_memory_cache(
            name,
            recent_limit=1,
            replace_stale=True,
        )
        self.assertNotEqual(replaced.cache_id, baseline.cache_id)
        self.assertEqual(load_context_memory_cache(name, season_no=1, episode_no=1), replaced)

    def test_cross_scope_oversize_special_and_bad_json_fail_closed(self) -> None:
        name = "context-store-boundaries"
        self._production_inputs(name)
        cache = create_context_memory_cache(name)
        target = drama_context_memory.context_memory_path(
            name,
            season_no=1,
            episode_no=1,
        )
        canonical = target.read_bytes()

        self._make_drama_workspace("context-foreign")
        foreign = drama_context_memory.context_memory_path(
            "context-foreign",
            season_no=1,
            episode_no=1,
        )
        foreign.parent.mkdir(parents=True, exist_ok=True)
        foreign.write_bytes(canonical)
        with self.assertRaisesRegex(DramaContextMemoryError, "another workspace"):
            load_context_memory_cache(
                "context-foreign",
                season_no=1,
                episode_no=1,
            )

        from src.drama_schemas import _canonical_sha256

        wrong_episode = model_to_dict(cache)
        wrong_episode["episode_no"] = 2
        payload = {
            key: value
            for key, value in wrong_episode.items()
            if key not in {"cache_id", "cache_fingerprint"}
        }
        wrong_episode["cache_fingerprint"] = _canonical_sha256(payload)
        wrong_episode["cache_id"] = "dcm_" + wrong_episode["cache_fingerprint"][:24]
        target.write_bytes(
            drama_context_memory._canonical_cache_bytes(
                DramaContextMemoryCache(**wrong_episode)
            )
        )
        with self.assertRaisesRegex(DramaContextMemoryError, "scope"):
            load_context_memory_cache(name, season_no=1, episode_no=1)

        bad_payloads = (
            b'{"schema_version":1,"schema_version":1}',
            b'{"value":NaN}',
            (b'{"x":' * 1100) + b"0" + (b"}" * 1100),
            b"x" * (drama_context_memory.MAX_CONTEXT_MEMORY_BYTES + 1),
        )
        for index, bad in enumerate(bad_payloads):
            with self.subTest(bad=index):
                target.write_bytes(bad)
                self.assertEqual(inspect_context_memory_cache(name).state, "invalid")

        target.unlink()
        target.mkdir()
        self.assertEqual(inspect_context_memory_cache(name).state, "invalid")
        target.rmdir()
        os.mkfifo(target)
        self.assertEqual(inspect_context_memory_cache(name).state, "invalid")

    def test_container_subclasses_long_keywords_and_create_race_are_bounded(self) -> None:
        adapted, projection, plan = self._pure_inputs("context-containers")
        policy = context_memory_policy_fingerprint({"p": b"v"})

        class DictSubclass(dict):
            pass

        class ListSubclass(list):
            pass

        class StrSubclass(str):
            pass

        class BytesSubclass(bytes):
            pass

        with self.assertRaises(DramaContextMemoryError):
            context_memory_policy_fingerprint(DictSubclass({"p": b"v"}))
        with self.assertRaises(DramaContextMemoryError):
            context_memory_policy_fingerprint({StrSubclass("p"): b"v"})
        with self.assertRaises(DramaContextMemoryError):
            context_memory_policy_fingerprint({"p": BytesSubclass(b"v")})
        with self.assertRaises(DramaContextMemoryError):
            build_context_memory_cache(
                graph=model_to_dict(adapted.graph),
                projection=projection,
                render_plan=plan,
                graph_family_id="season_1",
                source_snapshot_fingerprint=adapted.source_snapshot_fingerprint,
                policy_fingerprint=policy,
            )
        with self.assertRaises(DramaContextMemoryError):
            build_context_memory_cache(
                graph=DictSubclass(model_to_dict(adapted.graph)),
                projection=projection,
                render_plan=plan,
                graph_family_id="season_1",
                source_snapshot_fingerprint=adapted.source_snapshot_fingerprint,
                policy_fingerprint=policy,
            )
        with self.assertRaises(DramaContextMemoryError):
            build_context_memory_cache(
                graph=adapted.graph,
                projection=projection,
                render_plan=plan,
                graph_family_id="season_1",
                source_snapshot_fingerprint=adapted.source_snapshot_fingerprint,
                policy_fingerprint=policy,
                summary_event_ids=ListSubclass(projection.selected_event_ids),
            )
        with self.assertRaises(DramaContextMemoryError):
            build_context_memory_cache(
                graph=adapted.graph,
                projection=projection,
                render_plan=plan,
                graph_family_id="season_1",
                source_snapshot_fingerprint=adapted.source_snapshot_fingerprint,
                policy_fingerprint=policy,
                keyword_event_ids=DictSubclass({"k": [projection.selected_event_ids[0]]}),
            )
        cache = build_context_memory_cache(
            graph=adapted.graph,
            projection=projection,
            render_plan=plan,
            graph_family_id="season_1",
            source_snapshot_fingerprint=adapted.source_snapshot_fingerprint,
            policy_fingerprint=policy,
        )
        with self.assertRaises(DramaContextMemoryError):
            query_context_memory(cache, keywords=ListSubclass(["k"]))
        with self.assertRaises(DramaContextMemoryError):
            context_keyword_hash("k" * 321)
        with self.assertRaises(DramaContextMemoryError):
            context_keyword_hash(StrSubclass("k"))
        record_payload = model_to_dict(cache.records[0])
        record_payload["roles"] = ListSubclass(record_payload["roles"])
        with self.assertRaises(ValidationError):
            DramaContextMemoryRecord(**record_payload)
        nested_cache = model_to_dict(cache)
        nested_cache["records"] = ListSubclass(nested_cache["records"])
        with self.assertRaises(ValidationError):
            DramaContextMemoryCache(**nested_cache)

        name = "context-create-race"
        self._production_inputs(name)
        original = drama_context_memory._target_token_at
        calls = 0

        def race(directory_fd: int, filename: str):
            nonlocal calls
            calls += 1
            if calls == 2:
                fd = os.open(
                    filename,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                    0o600,
                    dir_fd=directory_fd,
                )
                os.write(fd, b"competing-cache")
                os.close(fd)
            return original(directory_fd, filename)

        with patch.object(drama_context_memory, "_target_token_at", side_effect=race):
            with self.assertRaisesRegex(DramaContextMemoryError, "concurrently"):
                create_context_memory_cache(name)
        target = drama_context_memory.context_memory_path(
            name,
            season_no=1,
            episode_no=1,
        )
        self.assertEqual(target.read_bytes(), b"competing-cache")


if __name__ == "__main__":
    import unittest

    unittest.main()
