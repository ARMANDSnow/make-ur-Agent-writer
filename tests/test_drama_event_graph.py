"""iter140: typed source event graph, provenance, boundary, and safe store."""

from __future__ import annotations

import json
import socket
from pathlib import Path
from unittest.mock import patch

from pydantic import ValidationError

from src.cli_workspace import init_workspace
from src.drama_event_graph import (
    DramaEventGraphError,
    build_event_fact,
    build_event_graph,
    build_source_event,
    event_graph_path,
    event_graph_scope_fingerprint,
    load_event_graph,
    merge_source_events,
    save_event_graph,
    select_event_projection,
    split_source_event,
)
from src.drama_schemas import (
    DramaEventGraph,
    DramaEventGraphRecord,
    DramaEventProjection,
    DramaSourceEvent,
    _canonical_sha256,
    _drama_event_graph_identity_payload,
)
from src.schemas import model_to_dict
from tests._drama_base import DramaTestBase


SCOPE_A = "a" * 64
SCOPE_B = "b" * 64
WORKSPACE_SCOPE = "c" * 64
HASH_1 = "1" * 64
HASH_2 = "2" * 64
HASH_3 = "3" * 64


class DramaEventGraphFixture(DramaTestBase):
    def _fact(self, kind: str, suffix: str):
        return build_event_fact(
            kind=kind,
            subject_id=f"character:{suffix}",
            predicate="state",
            value=f"state-{suffix}",
        )

    def _source_event(
        self,
        *,
        chapter_no: int,
        chapter_id: str | None = None,
        source_hash: str = HASH_1,
        chronology_order: int | None = None,
        preconditions=(),
        effects=(),
        causal_parent_ids=(),
        causality_complete: bool = True,
        scope: str = SCOPE_A,
        workspace_scope: str = WORKSPACE_SCOPE,
    ):
        return build_source_event(
            workspace_scope_fingerprint=workspace_scope,
            scope_fingerprint=scope,
            source_kind="source_derived",
            adaptation_status="selected",
            chronology_order=chronology_order or chapter_no,
            source_chapters=[
                {
                    "chapter_id": chapter_id or f"chapter:{chapter_no:03d}",
                    "chapter_no": chapter_no,
                    "source_hash": source_hash,
                }
            ],
            participant_ids=["character:lead"],
            scene_ids=["scene:main"],
            preconditions=preconditions,
            effects=effects,
            causal_parent_ids=causal_parent_ids,
            causality_complete=causality_complete,
        )


class DramaEventSchemaTests(DramaEventGraphFixture):
    def test_fact_event_and_graph_are_strict_deterministic_and_bound(self) -> None:
        effect = self._fact("effect", "awake")
        first = self._source_event(chapter_no=1, effects=[effect])
        second = self._source_event(chapter_no=1, effects=[effect])
        self.assertEqual(first, second)
        equal_event = model_to_dict(first)
        equal_event["workspace_scope_fingerprint"] = SCOPE_A
        equal_event_payload = {
            key: value
            for key, value in equal_event.items()
            if key not in {"event_id", "event_fingerprint"}
        }
        equal_event_fingerprint = _canonical_sha256(equal_event_payload)
        equal_event["event_fingerprint"] = equal_event_fingerprint
        equal_event["event_id"] = f"dse_{equal_event_fingerprint[:24]}"
        with self.assertRaisesRegex(ValidationError, "must be distinct"):
            DramaSourceEvent(**equal_event)
        graph = build_event_graph(
            workspace_scope_fingerprint=WORKSPACE_SCOPE,
            scope_fingerprint=SCOPE_A,
            events=[first],
        )
        self.assertTrue(graph.graph_id.startswith("deg_"))

        equal_scopes = model_to_dict(graph)
        equal_scopes["workspace_scope_fingerprint"] = SCOPE_A
        equal_identity = _drama_event_graph_identity_payload(
            workspace_scope_fingerprint=SCOPE_A,
            scope_fingerprint=SCOPE_A,
            records=[
                {
                    "chronology_order": item.chronology_order,
                    "event_id": item.event_id,
                    "event_fingerprint": item.event_fingerprint,
                }
                for item in graph.events
            ],
        )
        equal_fingerprint = _canonical_sha256(equal_identity)
        equal_scopes["graph_fingerprint"] = equal_fingerprint
        equal_scopes["graph_id"] = f"deg_{equal_fingerprint[:24]}"
        with self.assertRaisesRegex(ValidationError, "must be distinct"):
            DramaEventGraph(**equal_scopes)

        with self.assertRaisesRegex(
            DramaEventGraphError, "another workspace scope"
        ):
            build_event_graph(
                workspace_scope_fingerprint=SCOPE_B,
                scope_fingerprint=SCOPE_A,
                events=[first],
            )

        extra = model_to_dict(graph)
        extra["unexpected"] = True
        with self.assertRaises(ValidationError):
            DramaEventGraph(**extra)

        bool_order = model_to_dict(first)
        bool_order["chronology_order"] = True
        with self.assertRaises(ValidationError):
            DramaSourceEvent(**bool_order)

        tampered = model_to_dict(first)
        tampered["participant_ids"] = [
            *tampered["participant_ids"],
            "character:other",
        ]
        with self.assertRaisesRegex(ValidationError, "fingerprint"):
            DramaSourceEvent(**tampered)

        first_fact = self._fact("effect", "a")
        second_fact = self._fact("effect", "b")
        ordered = self._source_event(
            chapter_no=2,
            source_hash=HASH_2,
            effects=[first_fact, second_fact],
        )
        reordered = model_to_dict(ordered)
        reordered["effects"] = list(reversed(reordered["effects"]))
        event_payload = {
            key: value
            for key, value in reordered.items()
            if key not in {"event_id", "event_fingerprint"}
        }
        event_fingerprint = _canonical_sha256(event_payload)
        reordered["event_id"] = f"dse_{event_fingerprint[:24]}"
        reordered["event_fingerprint"] = event_fingerprint
        with self.assertRaisesRegex(ValidationError, "canonical order"):
            DramaSourceEvent(**reordered)

    def test_fact_atoms_and_builder_limits_fail_before_expensive_work(self) -> None:
        with patch("src.drama_event_graph._canonical_sha256") as digest:
            with self.assertRaisesRegex(DramaEventGraphError, "atoms"):
                build_event_fact(
                    kind="effect",
                    subject_id="character:lead",
                    predicate="custom",
                    value="/Users/private/小说txt/chapter prompt=secret",
                )
        digest.assert_not_called()

        with self.assertRaisesRegex(DramaEventGraphError, "source chapters exceed"):
            build_source_event(
                workspace_scope_fingerprint=WORKSPACE_SCOPE,
                scope_fingerprint=SCOPE_A,
                source_kind="source_derived",
                adaptation_status="selected",
                chronology_order=1,
                source_chapters=[object()] * 65,
                causality_complete=False,
            )
        with patch("src.drama_event_graph._revalidate_fact") as validate_fact:
            with self.assertRaisesRegex(DramaEventGraphError, "facts exceed"):
                build_source_event(
                    workspace_scope_fingerprint=WORKSPACE_SCOPE,
                    scope_fingerprint=SCOPE_A,
                    source_kind="invented",
                    adaptation_status="invented",
                    chronology_order=1,
                    effects=[object()] * 65,
                    causality_complete=False,
                )
        validate_fact.assert_not_called()

    def test_source_and_invented_provenance_cannot_be_washed(self) -> None:
        with self.assertRaisesRegex(DramaEventGraphError, "invalid"):
            build_source_event(
                workspace_scope_fingerprint=WORKSPACE_SCOPE,
                scope_fingerprint=SCOPE_A,
                source_kind="invented",
                adaptation_status="invented",
                chronology_order=1,
                source_chapters=[
                    {
                        "chapter_id": "chapter:001",
                        "chapter_no": 1,
                        "source_hash": HASH_1,
                    }
                ],
                causality_complete=False,
            )
        with self.assertRaisesRegex(DramaEventGraphError, "invalid"):
            build_source_event(
                workspace_scope_fingerprint=WORKSPACE_SCOPE,
                scope_fingerprint=SCOPE_A,
                source_kind="source_derived",
                adaptation_status="invented",
                chronology_order=1,
                source_chapters=[
                    {
                        "chapter_id": "chapter:001",
                        "chapter_no": 1,
                        "source_hash": HASH_1,
                    }
                ],
                causality_complete=False,
            )
        invented = build_source_event(
            workspace_scope_fingerprint=WORKSPACE_SCOPE,
            scope_fingerprint=SCOPE_A,
            source_kind="invented",
            adaptation_status="invented",
            chronology_order=2,
            effects=[self._fact("effect", "invented")],
            causality_complete=False,
        )
        self.assertEqual(invented.source_chapters, ())
        self.assertIsNone(invented.spoiler_boundary)
        with self.assertRaisesRegex(DramaEventGraphError, "invalid"):
            build_source_event(
                workspace_scope_fingerprint=WORKSPACE_SCOPE,
                scope_fingerprint=SCOPE_A,
                source_kind="source_derived",
                adaptation_status="merged",
                chronology_order=1,
                source_chapters=[
                    {
                        "chapter_id": "chapter:001",
                        "chapter_no": 1,
                        "source_hash": HASH_1,
                    }
                ],
                causality_complete=True,
            )

    def test_graph_rejects_scope_splice_dangling_parent_and_source_conflict(self) -> None:
        first = self._source_event(chapter_no=1)
        other_scope = self._source_event(chapter_no=2, scope=SCOPE_B)
        with self.assertRaisesRegex(DramaEventGraphError, "invalid"):
            build_event_graph(
                workspace_scope_fingerprint=WORKSPACE_SCOPE,
                scope_fingerprint=SCOPE_A,
                events=[first, other_scope],
            )

        dangling = build_source_event(
            workspace_scope_fingerprint=WORKSPACE_SCOPE,
            scope_fingerprint=SCOPE_A,
            source_kind="source_derived",
            adaptation_status="selected",
            chronology_order=2,
            source_chapters=[
                {
                    "chapter_id": "chapter:002",
                    "chapter_no": 2,
                    "source_hash": HASH_2,
                }
            ],
            causal_parent_ids=["dse_" + "f" * 24],
            causality_complete=True,
        )
        with self.assertRaisesRegex(DramaEventGraphError, "invalid"):
            build_event_graph(
                workspace_scope_fingerprint=WORKSPACE_SCOPE,
                scope_fingerprint=SCOPE_A,
                events=[first, dangling],
            )

        conflicting_source = self._source_event(
            chapter_no=1,
            chapter_id="chapter:001",
            source_hash=HASH_2,
            chronology_order=2,
        )
        with self.assertRaisesRegex(DramaEventGraphError, "invalid"):
            build_event_graph(
                workspace_scope_fingerprint=WORKSPACE_SCOPE,
                scope_fingerprint=SCOPE_A,
                events=[first, conflicting_source],
            )
        aliased_source = self._source_event(
            chapter_no=1,
            chapter_id="chapter:alias",
            source_hash=HASH_1,
            chronology_order=2,
        )
        with self.assertRaisesRegex(DramaEventGraphError, "invalid"):
            build_event_graph(
                workspace_scope_fingerprint=WORKSPACE_SCOPE,
                scope_fingerprint=SCOPE_A,
                events=[first, aliased_source],
            )

    def test_known_parent_must_not_occur_after_child(self) -> None:
        parent = self._source_event(chapter_no=2, chronology_order=3)
        child = self._source_event(
            chapter_no=3,
            chronology_order=2,
            causal_parent_ids=[parent.event_id],
        )
        with self.assertRaisesRegex(DramaEventGraphError, "invalid"):
            build_event_graph(
                workspace_scope_fingerprint=WORKSPACE_SCOPE,
                scope_fingerprint=SCOPE_A,
                events=[parent, child],
            )


class DramaEventTransformTests(DramaEventGraphFixture):
    def test_merge_preserves_sources_facts_and_unknown_causality(self) -> None:
        first = self._source_event(
            chapter_no=1,
            source_hash=HASH_1,
            effects=[self._fact("effect", "one")],
            causality_complete=True,
        )
        invented = build_source_event(
            workspace_scope_fingerprint=WORKSPACE_SCOPE,
            scope_fingerprint=SCOPE_A,
            source_kind="invented",
            adaptation_status="invented",
            chronology_order=2,
            preconditions=[self._fact("precondition", "two")],
            causality_complete=False,
        )
        graph = build_event_graph(
            workspace_scope_fingerprint=WORKSPACE_SCOPE,
            scope_fingerprint=SCOPE_A,
            events=[first, invented],
        )
        updated, merged = merge_source_events(
            graph,
            event_ids=[invented.event_id, first.event_id],
        )
        self.assertEqual(merged.source_kind, "mixed")
        self.assertEqual(merged.adaptation_status, "merged")
        self.assertEqual(
            merged.lineage_parent_event_ids,
            tuple(sorted([first.event_id, invented.event_id])),
        )
        self.assertFalse(merged.causality_complete)
        self.assertEqual([row.chapter_id for row in merged.source_chapters], ["chapter:001"])
        self.assertEqual(len(merged.preconditions), 1)
        self.assertEqual(len(merged.effects), 1)

        replayed, replay_event = merge_source_events(
            updated,
            event_ids=[first.event_id, invented.event_id],
        )
        self.assertEqual(replayed, updated)
        self.assertEqual(replay_event, merged)

    def test_split_requires_exact_fact_partition_and_replays(self) -> None:
        pre = self._fact("precondition", "pre")
        effect_a = self._fact("effect", "a")
        effect_b = self._fact("effect", "b")
        parent = self._source_event(
            chapter_no=1,
            preconditions=[pre],
            effects=[effect_a, effect_b],
        )
        graph = build_event_graph(
            workspace_scope_fingerprint=WORKSPACE_SCOPE,
            scope_fingerprint=SCOPE_A,
            events=[parent],
        )
        partitions = [
            {
                "precondition_fact_ids": [pre.fact_id],
                "effect_fact_ids": [effect_a.fact_id],
            },
            {"effect_fact_ids": [effect_b.fact_id]},
        ]
        updated, children = split_source_event(
            graph,
            event_id=parent.event_id,
            partitions=partitions,
        )
        self.assertEqual(len(children), 2)
        self.assertTrue(
            all(child.lineage_parent_event_ids == (parent.event_id,) for child in children)
        )
        self.assertEqual(
            {
                fact.fact_id
                for child in children
                for fact in (*child.preconditions, *child.effects)
            },
            {pre.fact_id, effect_a.fact_id, effect_b.fact_id},
        )
        replayed, replay_children = split_source_event(
            updated,
            event_id=parent.event_id,
            partitions=partitions,
        )
        self.assertEqual(replayed, updated)
        self.assertEqual(replay_children, children)

        with self.assertRaisesRegex(DramaEventGraphError, "exactly cover"):
            split_source_event(
                graph,
                event_id=parent.event_id,
                partitions=[
                    {"effect_fact_ids": [effect_a.fact_id]},
                    {"effect_fact_ids": [effect_b.fact_id]},
                ],
            )
        with self.assertRaisesRegex(DramaEventGraphError, "exactly cover"):
            split_source_event(
                graph,
                event_id=parent.event_id,
                partitions=[
                    {
                        "precondition_fact_ids": [pre.fact_id],
                        "effect_fact_ids": [effect_a.fact_id],
                    },
                    {
                        "precondition_fact_ids": [pre.fact_id],
                        "effect_fact_ids": [effect_b.fact_id],
                    },
                ],
            )

    def test_projection_includes_full_causal_and_lineage_closure(self) -> None:
        first = self._source_event(chapter_no=1, source_hash=HASH_1)
        second = self._source_event(
            chapter_no=2,
            source_hash=HASH_2,
            causal_parent_ids=[first.event_id],
        )
        graph = build_event_graph(
            workspace_scope_fingerprint=WORKSPACE_SCOPE,
            scope_fingerprint=SCOPE_A,
            events=[first, second],
        )
        merged_graph, merged = merge_source_events(
            graph,
            event_ids=[first.event_id, second.event_id],
        )
        projection = select_event_projection(
            merged_graph,
            selected_event_ids=[merged.event_id],
            allowed_source_chapter_ids=["chapter:001", "chapter:002"],
            max_spoiler_boundary=2,
        )
        self.assertEqual(
            set(projection.included_event_ids),
            {first.event_id, second.event_id, merged.event_id},
        )
        with self.assertRaisesRegex(DramaEventGraphError, "spoiler boundary"):
            select_event_projection(
                merged_graph,
                selected_event_ids=[merged.event_id],
                allowed_source_chapter_ids=["chapter:001", "chapter:002"],
                max_spoiler_boundary=1,
            )
        with self.assertRaisesRegex(DramaEventGraphError, "disallowed source"):
            select_event_projection(
                merged_graph,
                selected_event_ids=[merged.event_id],
                allowed_source_chapter_ids=["chapter:002"],
                max_spoiler_boundary=2,
            )

    def test_projection_rejects_rehashed_extra_and_cross_graph_membership(self) -> None:
        first = self._source_event(chapter_no=1, source_hash=HASH_1)
        unrelated = self._source_event(
            chapter_no=2,
            source_hash=HASH_2,
            chronology_order=2,
        )
        graph = build_event_graph(
            workspace_scope_fingerprint=WORKSPACE_SCOPE,
            scope_fingerprint=SCOPE_A,
            events=[first, unrelated],
        )
        projection = select_event_projection(
            graph,
            selected_event_ids=[first.event_id],
            allowed_source_chapter_ids=["chapter:001", "chapter:002"],
            max_spoiler_boundary=2,
        )
        injected = model_to_dict(projection)
        injected["included_event_ids"] = [
            item.event_id for item in graph.events
        ]
        injected["events"] = [model_to_dict(item) for item in graph.events]
        injected_payload = {
            key: value
            for key, value in injected.items()
            if key != "projection_fingerprint"
        }
        injected["projection_fingerprint"] = _canonical_sha256(injected_payload)
        with self.assertRaisesRegex(ValidationError, "exact selected closure"):
            type(projection)(**injected)

        other_graph = build_event_graph(
            workspace_scope_fingerprint=WORKSPACE_SCOPE,
            scope_fingerprint=SCOPE_A,
            events=[unrelated],
        )
        spliced = model_to_dict(projection)
        spliced["graph_id"] = other_graph.graph_id
        spliced["graph_fingerprint"] = other_graph.graph_fingerprint
        spliced["graph_event_records"] = [
            {
                "chronology_order": item.chronology_order,
                "event_id": item.event_id,
                "event_fingerprint": item.event_fingerprint,
            }
            for item in other_graph.events
        ]
        spliced_payload = {
            key: value
            for key, value in spliced.items()
            if key != "projection_fingerprint"
        }
        spliced["projection_fingerprint"] = _canonical_sha256(spliced_payload)
        with self.assertRaisesRegex(ValidationError, "non-member"):
            type(projection)(**spliced)

        impossible_record = model_to_dict(projection.graph_event_records[1])
        impossible_record["event_fingerprint"] = "f" * 64
        with self.assertRaisesRegex(ValidationError, "record identity"):
            DramaEventGraphRecord(**impossible_record)

        both = select_event_projection(
            graph,
            selected_event_ids=[first.event_id, unrelated.event_id],
            allowed_source_chapter_ids=["chapter:001", "chapter:002"],
            max_spoiler_boundary=2,
        )
        reordered = model_to_dict(both)
        reordered["included_event_ids"] = list(
            reversed(reordered["included_event_ids"])
        )
        reordered["events"] = list(reversed(reordered["events"]))
        reordered_payload = {
            key: value
            for key, value in reordered.items()
            if key != "projection_fingerprint"
        }
        reordered["projection_fingerprint"] = _canonical_sha256(
            reordered_payload
        )
        with self.assertRaisesRegex(ValidationError, "order is not canonical"):
            DramaEventProjection(**reordered)

    def test_invented_projection_needs_no_fake_source(self) -> None:
        invented = build_source_event(
            workspace_scope_fingerprint=WORKSPACE_SCOPE,
            scope_fingerprint=SCOPE_A,
            source_kind="invented",
            adaptation_status="invented",
            chronology_order=1,
            effects=[self._fact("effect", "new")],
            causality_complete=False,
        )
        graph = build_event_graph(
            workspace_scope_fingerprint=WORKSPACE_SCOPE,
            scope_fingerprint=SCOPE_A,
            events=[invented],
        )
        projection = select_event_projection(
            graph,
            selected_event_ids=[invented.event_id],
            allowed_source_chapter_ids=[],
            max_spoiler_boundary=1,
        )
        self.assertEqual(projection.included_event_ids, (invented.event_id,))

        omitted = build_source_event(
            workspace_scope_fingerprint=WORKSPACE_SCOPE,
            scope_fingerprint=SCOPE_A,
            source_kind="source_derived",
            adaptation_status="omitted",
            chronology_order=2,
            source_chapters=[
                {
                    "chapter_id": "chapter:002",
                    "chapter_no": 2,
                    "source_hash": HASH_2,
                }
            ],
            effects=[self._fact("effect", "omitted")],
            causality_complete=True,
        )
        omitted_graph = build_event_graph(
            workspace_scope_fingerprint=WORKSPACE_SCOPE,
            scope_fingerprint=SCOPE_A,
            events=[omitted],
        )
        with self.assertRaisesRegex(DramaEventGraphError, "omitted"):
            select_event_projection(
                omitted_graph,
                selected_event_ids=[omitted.event_id],
                allowed_source_chapter_ids=["chapter:002"],
                max_spoiler_boundary=2,
            )
        omitted_projection = {
            "schema_version": 1,
            "graph_id": omitted_graph.graph_id,
            "graph_fingerprint": omitted_graph.graph_fingerprint,
            "workspace_scope_fingerprint": (
                omitted_graph.workspace_scope_fingerprint
            ),
            "scope_fingerprint": omitted_graph.scope_fingerprint,
            "graph_event_records": [
                {
                    "chronology_order": omitted.chronology_order,
                    "event_id": omitted.event_id,
                    "event_fingerprint": omitted.event_fingerprint,
                }
            ],
            "selected_event_ids": [omitted.event_id],
            "included_event_ids": [omitted.event_id],
            "allowed_source_chapter_ids": ["chapter:002"],
            "max_spoiler_boundary": 2,
            "events": [model_to_dict(omitted)],
        }
        omitted_projection["projection_fingerprint"] = _canonical_sha256(
            omitted_projection
        )
        with self.assertRaisesRegex(ValidationError, "omitted event"):
            DramaEventProjection(**omitted_projection)
        selected_child = self._source_event(
            chapter_no=3,
            source_hash=HASH_3,
            chronology_order=3,
            causal_parent_ids=[omitted.event_id],
        )
        closure_graph = build_event_graph(
            workspace_scope_fingerprint=WORKSPACE_SCOPE,
            scope_fingerprint=SCOPE_A,
            events=[omitted, selected_child],
        )
        with self.assertRaisesRegex(DramaEventGraphError, "closure.*omitted"):
            select_event_projection(
                closure_graph,
                selected_event_ids=[selected_child.event_id],
                allowed_source_chapter_ids=["chapter:002", "chapter:003"],
                max_spoiler_boundary=3,
            )

    def test_rehashed_merge_and_partial_split_cannot_self_certify(self) -> None:
        source = self._source_event(
            chapter_no=1,
            effects=[self._fact("effect", "source")],
        )
        invented = build_source_event(
            workspace_scope_fingerprint=WORKSPACE_SCOPE,
            scope_fingerprint=SCOPE_A,
            source_kind="invented",
            adaptation_status="invented",
            chronology_order=2,
            effects=[self._fact("effect", "invented")],
            causality_complete=False,
        )
        base = build_event_graph(
            workspace_scope_fingerprint=WORKSPACE_SCOPE,
            scope_fingerprint=SCOPE_A,
            events=[source, invented],
        )
        merged_graph, merged = merge_source_events(
            base,
            event_ids=[source.event_id, invented.event_id],
        )
        forged = model_to_dict(merged_graph)
        merged_raw = next(
            item for item in forged["events"] if item["event_id"] == merged.event_id
        )
        merged_raw["source_kind"] = "source_derived"
        event_payload = {
            key: value
            for key, value in merged_raw.items()
            if key not in {"event_id", "event_fingerprint"}
        }
        event_fingerprint = _canonical_sha256(event_payload)
        merged_raw["event_fingerprint"] = event_fingerprint
        merged_raw["event_id"] = f"dse_{event_fingerprint[:24]}"
        forged["events"] = sorted(
            forged["events"],
            key=lambda item: (item["chronology_order"], item["event_id"])
        )
        graph_payload = _drama_event_graph_identity_payload(
            workspace_scope_fingerprint=forged["workspace_scope_fingerprint"],
            scope_fingerprint=forged["scope_fingerprint"],
            records=[
                {
                    "chronology_order": item["chronology_order"],
                    "event_id": item["event_id"],
                    "event_fingerprint": item["event_fingerprint"],
                }
                for item in forged["events"]
            ],
        )
        graph_fingerprint = _canonical_sha256(graph_payload)
        forged["graph_fingerprint"] = graph_fingerprint
        forged["graph_id"] = f"deg_{graph_fingerprint[:24]}"
        with self.assertRaisesRegex(ValidationError, "provenance"):
            DramaEventGraph(**forged)

        parent = self._source_event(
            chapter_no=3,
            effects=[self._fact("effect", "left"), self._fact("effect", "right")],
            chronology_order=3,
        )
        split_base = build_event_graph(
            workspace_scope_fingerprint=WORKSPACE_SCOPE,
            scope_fingerprint=SCOPE_A,
            events=[parent],
        )
        split_graph, children = split_source_event(
            split_base,
            event_id=parent.event_id,
            partitions=[
                {"effect_fact_ids": [parent.effects[0].fact_id]},
                {"effect_fact_ids": [parent.effects[1].fact_id]},
            ],
        )
        partial = model_to_dict(split_graph)
        partial["events"] = [
            item
            for item in partial["events"]
            if item["event_id"] != children[1].event_id
        ]
        partial_payload = _drama_event_graph_identity_payload(
            workspace_scope_fingerprint=partial["workspace_scope_fingerprint"],
            scope_fingerprint=partial["scope_fingerprint"],
            records=[
                {
                    "chronology_order": item["chronology_order"],
                    "event_id": item["event_id"],
                    "event_fingerprint": item["event_fingerprint"],
                }
                for item in partial["events"]
            ],
        )
        partial_fingerprint = _canonical_sha256(partial_payload)
        partial["graph_fingerprint"] = partial_fingerprint
        partial["graph_id"] = f"deg_{partial_fingerprint[:24]}"
        with self.assertRaisesRegex(ValidationError, "partitions"):
            DramaEventGraph(**partial)


class DramaEventGraphStoreTests(DramaEventGraphFixture):
    def setUp(self) -> None:
        super().setUp()
        init_workspace("event-store", type="drama")

    def _graph(self):
        workspace_scope = event_graph_scope_fingerprint("event-store")
        event = self._source_event(
            chapter_no=1,
            effects=[self._fact("effect", "stored")],
            scope=SCOPE_A,
            workspace_scope=workspace_scope,
        )
        return build_event_graph(
            workspace_scope_fingerprint=workspace_scope,
            scope_fingerprint=SCOPE_A,
            events=[event],
        )

    def test_create_once_roundtrip_exact_replay_and_noncanonical_rejection(self) -> None:
        graph = self._graph()
        path = save_event_graph("event-store", graph)
        before = path.read_bytes()
        self.assertEqual(load_event_graph("event-store", graph.graph_id), graph)
        self.assertEqual(save_event_graph("event-store", graph), path)
        self.assertEqual(path.read_bytes(), before)

        raw = json.loads(before)
        path.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
        with self.assertRaisesRegex(DramaEventGraphError, "noncanonical"):
            load_event_graph("event-store", graph.graph_id)

    def test_tamper_duplicate_json_and_special_files_fail_closed(self) -> None:
        graph = self._graph()
        path = save_event_graph("event-store", graph)
        text = path.read_text("utf-8")
        path.write_text(
            text.replace(
                '"artifact_type":"drama_event_graph"',
                '"artifact_type":"drama_event_graph","artifact_type":"drama_event_graph"',
                1,
            ),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(DramaEventGraphError, "invalid"):
            load_event_graph("event-store", graph.graph_id)

        path.unlink()
        path.mkdir()
        with self.assertRaises(DramaEventGraphError):
            load_event_graph("event-store", graph.graph_id)

    def test_symlink_directory_and_target_are_never_followed(self) -> None:
        graph = self._graph()
        root = Path(self._tmp.name) / "event-store"
        drama_dir = root / "outputs" / "drama"
        drama_dir.mkdir(parents=True)
        external = Path(self._tmp.name) / "external"
        external.mkdir()
        (drama_dir / "event_graphs").symlink_to(external, target_is_directory=True)
        with self.assertRaises(DramaEventGraphError):
            save_event_graph("event-store", graph)
        self.assertEqual(list(external.iterdir()), [])

        (drama_dir / "event_graphs").unlink()
        (drama_dir / "event_graphs").mkdir()
        target = event_graph_path("event-store", graph.graph_id)
        outside = external / "outside.json"
        outside.write_text("untouched", encoding="utf-8")
        target.symlink_to(outside)
        with self.assertRaises(DramaEventGraphError):
            save_event_graph("event-store", graph)
        self.assertEqual(outside.read_text("utf-8"), "untouched")

    def test_store_rejects_cross_workspace_scope(self) -> None:
        graph = self._graph()
        init_workspace("event-other", type="drama")
        with self.assertRaisesRegex(DramaEventGraphError, "another workspace"):
            save_event_graph("event-other", graph)
        self.assertFalse(event_graph_path("event-other", graph.graph_id).exists())

        source = save_event_graph("event-store", graph)
        copied = event_graph_path("event-other", graph.graph_id)
        copied.parent.mkdir(parents=True)
        copied.write_bytes(source.read_bytes())
        with self.assertRaisesRegex(DramaEventGraphError, "another workspace"):
            load_event_graph("event-other", graph.graph_id)

    def test_all_h1_paths_are_zero_network(self) -> None:
        with patch.object(socket, "socket", side_effect=AssertionError("network forbidden")):
            graph = self._graph()
            stored = save_event_graph("event-store", graph)
            loaded = load_event_graph("event-store", graph.graph_id)
            projection = select_event_projection(
                loaded,
                selected_event_ids=[loaded.events[0].event_id],
                allowed_source_chapter_ids=["chapter:001"],
                max_spoiler_boundary=1,
            )
        self.assertTrue(stored.is_file())
        self.assertEqual(len(projection.events), 1)


if __name__ == "__main__":
    import unittest

    unittest.main()
