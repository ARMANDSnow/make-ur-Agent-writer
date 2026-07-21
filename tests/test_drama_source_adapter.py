"""iter145: production source snapshot adapter contract tests."""

from __future__ import annotations

import json
import socket
from unittest.mock import patch

from src.entity_advance import chapter_anchor
from src.drama_source_adapter import (
    DramaSourceAdapterError,
    build_source_event_graph,
    load_production_source_event_graph,
)
from src.schemas import model_to_dict
from tests._drama_base import DramaTestBase


def _bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


class DramaSourceAdapterTests(DramaTestBase):
    def _snapshots(self) -> tuple[bytes, bytes]:
        rolling = {
            "chapters": [
                {
                    "chapter_id": "v1_ch001",
                    "chapter_no": 1,
                    "summary": "不应进入事件图的私有摘要甲",
                    "key_events": ["不应进入事件图的私有事件甲"],
                    "ending_state": "不应持久化的结尾",
                    "text_snippet": "不应持久化的原文片段",
                },
                {
                    "chapter_id": "v1_ch002",
                    "chapter_no": 2,
                    "summary": "不应进入事件图的私有摘要乙",
                    "key_events": [],
                    "ending_state": "",
                    "text_snippet": "",
                },
            ],
            "compressed_older": [],
        }
        entity = {
            "entities": [
                {"id": "c001", "name": "私有角色名甲"},
                {"id": "c002", "name": "私有角色名乙"},
            ],
            "relationships": [
                {
                    "src_id": "c001",
                    "dst_id": "c002",
                    "relation_type": "私有关系类型",
                    "timeline": [
                        {
                            "chapter_id": "v1_ch001",
                            "active": True,
                            "state": "不应进入事件图的私有关系状态",
                        }
                    ],
                }
            ],
        }
        return _bytes(rolling), _bytes(entity)

    def test_build_is_deterministic_hash_bound_and_text_free(self) -> None:
        self._make_drama_workspace("source-adapter", "霸总")
        rolling, entity = self._snapshots()
        first = build_source_event_graph(
            workspace="source-adapter",
            graph_family_id="season_1",
            rolling_summary_bytes=rolling,
            entity_graph_bytes=entity,
            max_spoiler_boundary=2,
        )
        second = build_source_event_graph(
            workspace="source-adapter",
            graph_family_id="season_1",
            rolling_summary_bytes=rolling,
            entity_graph_bytes=entity,
            max_spoiler_boundary=2,
        )
        self.assertEqual(first, second)
        self.assertEqual(first.status, "ready")
        self.assertIsNotNone(first.graph)
        self.assertEqual(first.source_chapter_ids, ("v1_ch001", "v1_ch002"))
        assert first.graph is not None
        self.assertEqual(first.graph.events[0].participant_ids, ("c001", "c002"))
        self.assertFalse(first.graph.events[0].causality_complete)
        self.assertEqual(first.graph.events[0].causal_parent_ids, ())
        public = json.dumps(model_to_dict(first.graph), ensure_ascii=False)
        for secret in (
            "私有摘要",
            "私有事件",
            "私有角色名",
            "私有关系类型",
            "私有关系状态",
            "原文片段",
        ):
            self.assertNotIn(secret, public)

    def test_exact_source_byte_drift_changes_snapshot_and_graph_not_family(self) -> None:
        self._make_drama_workspace("source-drift", "霸总")
        rolling, entity = self._snapshots()
        first = build_source_event_graph(
            workspace="source-drift",
            graph_family_id="season_1",
            rolling_summary_bytes=rolling,
            entity_graph_bytes=entity,
        )
        formatted = json.dumps(
            json.loads(rolling),
            ensure_ascii=False,
            indent=2,
        ).encode("utf-8")
        whitespace_only = build_source_event_graph(
            workspace="source-drift",
            graph_family_id="season_1",
            rolling_summary_bytes=formatted,
            entity_graph_bytes=entity,
        )
        changed = json.loads(rolling)
        changed["chapters"][0]["summary"] += "变更"
        second = build_source_event_graph(
            workspace="source-drift",
            graph_family_id="season_1",
            rolling_summary_bytes=_bytes(changed),
            entity_graph_bytes=entity,
        )
        assert first.graph is not None and second.graph is not None
        self.assertNotEqual(
            first.source_snapshot_fingerprint,
            second.source_snapshot_fingerprint,
        )
        self.assertNotEqual(first.graph.graph_id, second.graph.graph_id)
        assert whitespace_only.graph is not None
        self.assertNotEqual(
            first.source_snapshot_fingerprint,
            whitespace_only.source_snapshot_fingerprint,
        )
        self.assertNotEqual(first.graph.graph_id, whitespace_only.graph.graph_id)
        self.assertEqual(first.graph.scope_fingerprint, second.graph.scope_fingerprint)
        self.assertNotEqual(
            first.graph.events[0].source_chapters[0].source_hash,
            second.graph.events[0].source_chapters[0].source_hash,
        )

    def test_missing_source_degrades_and_boundary_does_not_rewrite_source_identity(self) -> None:
        self._make_drama_workspace("source-missing", "霸总")
        with patch.object(socket, "socket", side_effect=AssertionError("network")):
            missing = build_source_event_graph(
                workspace="source-missing",
                graph_family_id="season_1",
                rolling_summary_bytes=None,
            )
            outside = build_source_event_graph(
                workspace="source-missing",
                graph_family_id="season_1",
                rolling_summary_bytes=_bytes(
                    {
                        "chapters": [
                            {"chapter_no": 3, "summary": "仅用于内存哈希"}
                        ],
                        "compressed_older": [],
                    }
                ),
                max_spoiler_boundary=2,
            )
        self.assertEqual(missing.status, "insufficient_source")
        self.assertIsNone(missing.graph)
        self.assertEqual(outside.status, "ready")
        self.assertEqual(outside.source_chapter_ids, ("chapter_000003",))

    def test_summary_only_is_ready_but_marks_entity_graph_degraded(self) -> None:
        self._make_drama_workspace("source-summary-only", "霸总")
        rolling, _entity = self._snapshots()
        result = build_source_event_graph(
            workspace="source-summary-only",
            graph_family_id="season_1",
            rolling_summary_bytes=rolling,
        )
        self.assertEqual(result.status, "ready")
        self.assertEqual(result.degraded_reasons, ("entity_graph_missing",))
        assert result.graph is not None
        self.assertEqual(result.graph.events[0].participant_ids, ())

    def test_nonempty_malformed_or_cross_workspace_inputs_fail_closed(self) -> None:
        self._make_drama_workspace("source-bad-a", "霸总")
        self._make_drama_workspace("source-bad-b", "霸总")
        rolling, entity = self._snapshots()
        with self.assertRaises(DramaSourceAdapterError):
            build_source_event_graph(
                workspace="source-bad-a",
                graph_family_id="season_1",
                rolling_summary_bytes=b'{"chapters":[],"chapters":[]}',
            )
        with self.assertRaises(DramaSourceAdapterError):
            build_source_event_graph(
                workspace="source-bad-a",
                graph_family_id="season_1",
                rolling_summary_bytes=rolling,
                entity_graph_bytes=_bytes(
                    {"entities": [{"id": "bad id"}], "relationships": []}
                ),
            )
        first = build_source_event_graph(
            workspace="source-bad-a",
            graph_family_id="season_1",
            rolling_summary_bytes=rolling,
            entity_graph_bytes=entity,
        )
        second = build_source_event_graph(
            workspace="source-bad-b",
            graph_family_id="season_1",
            rolling_summary_bytes=rolling,
            entity_graph_bytes=entity,
        )
        assert first.graph is not None and second.graph is not None
        self.assertNotEqual(
            first.graph.workspace_scope_fingerprint,
            second.graph.workspace_scope_fingerprint,
        )
        self.assertNotEqual(first.graph.graph_id, second.graph.graph_id)

    def test_named_workspace_loader_reads_only_strict_current_state(self) -> None:
        name = "source-loader"
        self._make_drama_workspace(name, "霸总")
        rolling, entity = self._snapshots()
        root = self._tmp.name
        from pathlib import Path

        workspace_root = Path(root) / name
        rolling_path = workspace_root / "outputs" / "drafts" / "rolling_chapter_summary.json"
        entity_path = workspace_root / "data" / "entity_graph.json"
        rolling_path.parent.mkdir(parents=True, exist_ok=True)
        entity_path.parent.mkdir(parents=True, exist_ok=True)
        rolling_path.write_bytes(rolling)
        entity_path.write_bytes(entity)
        loaded = load_production_source_event_graph(
            workspace=name,
            graph_family_id="season_1",
            max_spoiler_boundary=2,
        )
        pure = build_source_event_graph(
            workspace=name,
            graph_family_id="season_1",
            rolling_summary_bytes=rolling,
            entity_graph_bytes=entity,
            max_spoiler_boundary=2,
        )
        self.assertEqual(loaded, pure)

        rolling_path.unlink()
        rolling_path.symlink_to(entity_path)
        with self.assertRaises(DramaSourceAdapterError):
            load_production_source_event_graph(
                workspace=name,
                graph_family_id="season_1",
            )
        rolling_path.unlink()
        rolling_path.write_bytes(b"")
        with self.assertRaises(DramaSourceAdapterError):
            load_production_source_event_graph(
                workspace=name,
                graph_family_id="season_1",
            )

    def test_entity_advance_anchor_maps_once_and_unknown_anchor_is_not_guessed(self) -> None:
        self._make_drama_workspace("source-anchor", "霸总")
        rolling = _bytes(
            {
                "chapters": [
                    {"chapter_id": "v1_ch007", "chapter_no": 7, "summary": "摘要"}
                ],
                "compressed_older": [],
            }
        )
        entity = _bytes(
            {
                "entities": [{"id": "c001"}, {"id": "c002"}],
                "relationships": [
                    {
                        "src_id": "c001",
                        "dst_id": "c002",
                        "relation_type": "ally",
                        "timeline": [
                            {
                                "anchor_chapter": chapter_anchor(7),
                                "state": "private state",
                                "trigger_event": "private trigger",
                                "confidence": 0.8,
                                "active": True,
                            },
                            {
                                "anchor_chapter": "mock_chapter",
                                "state": "must not be guessed",
                                "active": False,
                            },
                        ],
                    }
                ],
            }
        )
        result = build_source_event_graph(
            workspace="source-anchor",
            graph_family_id="season_1",
            rolling_summary_bytes=rolling,
            entity_graph_bytes=entity,
        )
        assert result.graph is not None
        self.assertEqual(result.graph.events[0].participant_ids, ("c001", "c002"))
        self.assertEqual(len(result.graph.events[0].effects), 1)
        self.assertIn("unresolved_chapter_anchor", result.degraded_reasons)
        rendered = json.dumps(model_to_dict(result.graph), ensure_ascii=False)
        self.assertNotIn("private state", rendered)
        self.assertNotIn("private trigger", rendered)
        self.assertNotIn("must not be guessed", rendered)

    def test_nonfinite_compact_and_conflicting_timeline_inputs_are_rejected(self) -> None:
        self._make_drama_workspace("source-strict", "霸总")
        rolling = _bytes(
            {
                "chapters": [
                    {"chapter_id": "v1_ch001", "chapter_no": 1, "summary": "甲"},
                    {"chapter_id": "v1_ch002", "chapter_no": 2, "summary": "乙"},
                ],
                "compressed_older": [],
            }
        )
        with self.assertRaises(DramaSourceAdapterError):
            build_source_event_graph(
                workspace="source-strict",
                graph_family_id="season_1",
                rolling_summary_bytes=b'{"chapters":[],"compressed_older":[{"chapter_no":1,"text":{}}]}',
            )
        with self.assertRaises(DramaSourceAdapterError):
            build_source_event_graph(
                workspace="source-strict",
                graph_family_id="season_1",
                rolling_summary_bytes=rolling,
                entity_graph_bytes=(
                    b'{"entities":[{"id":"c001"},{"id":"c002"}],'
                    b'"relationships":[{"src_id":"c001","dst_id":"c002",'
                    b'"timeline":[{"anchor_chapter":"mock_chapter",'
                    b'"confidence":1e999}]}]}'
                ),
            )
        conflict = {
            "entities": [{"id": "c001"}, {"id": "c002"}],
            "relationships": [
                {
                    "src_id": "c001",
                    "dst_id": "c002",
                    "timeline": [
                        {
                            "chapter_id": "v1_ch001",
                            "chapter_no": 2,
                            "state": "conflict",
                            "active": True,
                        }
                    ],
                }
            ],
        }
        with self.assertRaises(DramaSourceAdapterError):
            build_source_event_graph(
                workspace="source-strict",
                graph_family_id="season_1",
                rolling_summary_bytes=rolling,
                entity_graph_bytes=_bytes(conflict),
            )
        anchor_conflict = json.loads(json.dumps(conflict))
        anchor_conflict["relationships"][0]["timeline"] = [
            {
                "chapter_no": 1,
                "anchor_chapter": chapter_anchor(2),
                "state": "conflict",
                "active": True,
            }
        ]
        with self.assertRaises(DramaSourceAdapterError):
            build_source_event_graph(
                workspace="source-strict",
                graph_family_id="season_1",
                rolling_summary_bytes=rolling,
                entity_graph_bytes=_bytes(anchor_conflict),
            )
        foreign_anchor = json.loads(json.dumps(conflict))
        foreign_anchor["relationships"][0]["timeline"] = [
            {
                "chapter_id": "foreign_chapter",
                "anchor_chapter": chapter_anchor(1),
                "state": "conflict",
                "active": True,
            }
        ]
        with self.assertRaises(DramaSourceAdapterError):
            build_source_event_graph(
                workspace="source-strict",
                graph_family_id="season_1",
                rolling_summary_bytes=rolling,
                entity_graph_bytes=_bytes(foreign_anchor),
            )
        bad_unmatched = json.loads(json.dumps(conflict))
        bad_unmatched["relationships"][0]["timeline"] = [
            {"anchor_chapter": "unmatched", "active": 1}
        ]
        with self.assertRaises(DramaSourceAdapterError):
            build_source_event_graph(
                workspace="source-strict",
                graph_family_id="season_1",
                rolling_summary_bytes=rolling,
                entity_graph_bytes=_bytes(bad_unmatched),
            )


if __name__ == "__main__":
    import unittest

    unittest.main()
