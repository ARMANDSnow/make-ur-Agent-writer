import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.cli_apply_advance import render_apply_advance_result
from src.entity_advance import active_relationships, apply_advance_proposals, save_entity_advance_proposals
from src.schemas import EntityAdvanceProposal, EntityAdvanceProposalSet


class EntityAdvanceTests(unittest.TestCase):
    def test_schema_repairs_common_llm_aliases(self) -> None:
        proposal = EntityAdvanceProposal(
            relationship_id="a<->b",
            proposed_state="互相试探但开始合作",
            confidence="high",
        )

        self.assertEqual(proposal.src_id, "a")
        self.assertEqual(proposal.dst_id, "b")
        self.assertEqual(proposal.new_state, "互相试探但开始合作")
        self.assertEqual(proposal.confidence, 0.85)

    def test_schema_accepts_unparseable_relationship_id_as_non_applyable(self) -> None:
        data = EntityAdvanceProposalSet(
            proposed_advances=[
                {
                    "relationship_id": "rel_001",
                    "new_state": "新状态",
                    "confidence": "medium",
                }
            ]
        )

        self.assertEqual(data.proposed_advances[0].src_id, "")
        self.assertEqual(data.proposed_advances[0].dst_id, "")
        self.assertEqual(data.proposed_advances[0].confidence, 0.6)

    def test_active_relationships_include_old_active_state(self) -> None:
        graph = {
            "relationships": [
                {
                    "src_id": "a",
                    "dst_id": "b",
                    "timeline": [
                        {"state": "过去", "active": False},
                        {"state": "现在", "active": True},
                    ],
                }
            ]
        }
        active = active_relationships(graph)
        self.assertEqual(active[0]["old_active_state"], "现在")

    def test_apply_advance_dry_run_and_confirm_switches_active_timeline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            drafts = root / "drafts"
            graph_path = root / "entity_graph.json"
            graph_path.write_text(
                json.dumps(
                    {
                        "relationships": [
                            {
                                "src_id": "a",
                                "dst_id": "b",
                                "relation_type": "同盟",
                                "timeline": [{"state": "旧状态", "active": True}],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            save_entity_advance_proposals(
                1,
                [
                    {
                        "src_id": "a",
                        "dst_id": "b",
                        "old_active_state": "旧状态",
                        "new_state": "新状态",
                        "trigger_event": "共同选择",
                        "confidence": 0.8,
                    }
                ],
                drafts_dir=drafts,
            )
            dry_run = apply_advance_proposals(
                chapter_no=1,
                proposal_indexes="0",
                confirm=False,
                graph_path=graph_path,
                drafts_dir=drafts,
            )
            self.assertIn("新状态", dry_run["diff"])
            self.assertEqual(json.loads(graph_path.read_text(encoding="utf-8"))["relationships"][0]["timeline"][0]["active"], True)

            apply_advance_proposals(
                chapter_no=1,
                proposal_indexes=[0],
                confirm=True,
                graph_path=graph_path,
                drafts_dir=drafts,
            )
            timeline = json.loads(graph_path.read_text(encoding="utf-8"))["relationships"][0]["timeline"]
        self.assertEqual(timeline[0]["active"], False)
        self.assertEqual(timeline[1]["state"], "新状态")
        self.assertEqual(timeline[1]["active"], True)


class ApplyAdvanceCorruptGraphFailClosedTests(unittest.TestCase):
    """iter067 F3: a confirm write must never persist a non-finite float. A
    pre-existing NaN/Infinity sitting elsewhere in entity_graph.json used to be
    cloned through _apply_selected and written straight back (default json.dumps
    has allow_nan=True). write_json now uses allow_nan=False, so confirm raises
    ValueError instead of re-emitting invalid JSON — book_runner's auto_advance
    catches ValueError and degrades to apply_advance_failed (safe no-op)."""

    def _seed(self, root: Path):
        drafts = root / "drafts"
        graph_path = root / "entity_graph.json"
        # Write the file directly with the stdlib encoder (allow_nan=True) so the
        # on-disk graph carries a bare NaN token, the exact corruption hazard.
        graph_path.write_text(
            json.dumps(
                {
                    "relationships": [
                        {
                            "src_id": "a",
                            "dst_id": "b",
                            "relation_type": "同盟",
                            "timeline": [
                                {"state": "旧状态", "active": True, "confidence": float("nan")}
                            ],
                        }
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        save_entity_advance_proposals(
            1,
            [
                {
                    "src_id": "a",
                    "dst_id": "b",
                    "old_active_state": "旧状态",
                    "new_state": "新状态",
                    "trigger_event": "共同选择",
                    "confidence": 0.8,
                }
            ],
            drafts_dir=drafts,
        )
        return drafts, graph_path

    def test_confirm_on_corrupt_graph_raises_value_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            drafts, graph_path = self._seed(root)
            with self.assertRaises(ValueError):
                apply_advance_proposals(
                    chapter_no=1,
                    proposal_indexes="0",
                    confirm=True,
                    graph_path=graph_path,
                    drafts_dir=drafts,
                )

    def test_dry_run_on_corrupt_graph_does_not_write(self) -> None:
        # Dry run never persists, so it must not raise even with a corrupt graph
        # (the file is left exactly as seeded for the user to repair).
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            drafts, graph_path = self._seed(root)
            before = graph_path.read_text(encoding="utf-8")
            result = apply_advance_proposals(
                chapter_no=1,
                proposal_indexes="0",
                confirm=False,
                graph_path=graph_path,
                drafts_dir=drafts,
            )
            self.assertIn("新状态", result["diff"])
            self.assertEqual(graph_path.read_text(encoding="utf-8"), before)


class ApplyAdvanceSkipsMissingRelationshipTests(unittest.TestCase):
    """Regression: a proposal referencing a relationship absent from the graph
    (e.g. the real-model ``ent_wuliang_east <-> ent_wuliang_west`` emitted while
    continuing ch4) must be skipped with a warning while the remaining valid
    proposals still apply.

    Pre-fix, the first such stale row raised
    ``ValueError("relationship not found ...")`` inside ``_apply_selected``;
    ``book_runner._auto_apply_advances`` caught it and recorded
    ``applied_count=0 / no_op_reason="apply_advance_failed"`` — so the entity
    graph never advanced even though the chapter wrote successfully.
    """

    def _seed(self, root: Path):
        drafts = root / "drafts"
        graph_path = root / "entity_graph.json"
        graph_path.write_text(
            json.dumps(
                {
                    "relationships": [
                        {
                            "src_id": "ent_a",
                            "dst_id": "ent_b",
                            "relation_type": "同盟",
                            "timeline": [{"state": "旧_ab", "active": True}],
                        },
                        {
                            "src_id": "ent_c",
                            "dst_id": "ent_d",
                            "relation_type": "敌对",
                            "timeline": [{"state": "旧_cd", "active": True}],
                        },
                    ]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        # The stale pair sits BETWEEN two valid proposals so the test proves the
        # batch continues past the skip in both directions (not just trailing).
        save_entity_advance_proposals(
            4,
            [
                {
                    "src_id": "ent_a",
                    "dst_id": "ent_b",
                    "old_active_state": "旧_ab",
                    "new_state": "新_ab",
                    "trigger_event": "并肩",
                    "confidence": 0.9,
                },
                {
                    "src_id": "ent_wuliang_east",
                    "dst_id": "ent_wuliang_west",
                    "old_active_state": "",
                    "new_state": "决裂",
                    "trigger_event": "内讧",
                    "confidence": 0.95,
                },
                {
                    "src_id": "ent_c",
                    "dst_id": "ent_d",
                    "old_active_state": "旧_cd",
                    "new_state": "新_cd",
                    "trigger_event": "和解",
                    "confidence": 0.88,
                },
            ],
            drafts_dir=drafts,
        )
        return drafts, graph_path

    def _assert_valid_pair_advanced(self, graph, pair, new_state) -> None:
        rels = {(r["src_id"], r["dst_id"]): r for r in graph["relationships"]}
        timeline = rels[pair]["timeline"]
        self.assertFalse(timeline[0]["active"])
        self.assertEqual(timeline[-1]["state"], new_state)
        self.assertTrue(timeline[-1]["active"])

    def test_explicit_indexes_skip_missing_and_apply_rest(self) -> None:
        # Mirrors book_runner._auto_apply_advances' exact call: explicit
        # comma-joined indexes, confirm + allow_empty, auto_apply=False.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            drafts, graph_path = self._seed(root)
            result = apply_advance_proposals(
                chapter_no=4,
                proposal_indexes="0,1,2",
                confirm=True,
                graph_path=graph_path,
                drafts_dir=drafts,
                allow_empty=True,
            )
            graph = json.loads(graph_path.read_text(encoding="utf-8"))

        # Two valid proposals applied; the stale one skipped (not counted).
        self.assertEqual(result["applied_count"], 2)
        skipped = result.get("skipped") or []
        self.assertEqual(len(skipped), 1)
        self.assertEqual(
            {skipped[0]["src_id"], skipped[0]["dst_id"]},
            {"ent_wuliang_east", "ent_wuliang_west"},
        )
        self.assertEqual(skipped[0]["reason"], "relationship_not_found")
        # The unknown pair was NOT injected into the graph.
        self.assertEqual(len(graph["relationships"]), 2)
        # Both valid relationships advanced.
        self._assert_valid_pair_advanced(graph, ("ent_a", "ent_b"), "新_ab")
        self._assert_valid_pair_advanced(graph, ("ent_c", "ent_d"), "新_cd")

    def test_auto_apply_path_skips_missing_and_applies_rest(self) -> None:
        # The confidence-gated auto-apply variant must behave the same.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            drafts, graph_path = self._seed(root)
            result = apply_advance_proposals(
                chapter_no=4,
                confirm=True,
                graph_path=graph_path,
                drafts_dir=drafts,
                auto_apply=True,
                min_confidence=0.7,
                allow_empty=True,
            )
            graph = json.loads(graph_path.read_text(encoding="utf-8"))

        self.assertEqual(result["applied_count"], 2)
        self.assertEqual(len(result.get("skipped") or []), 1)
        self.assertIsNone(result.get("no_op_reason"))  # batch did NOT fail
        self.assertEqual(len(graph["relationships"]), 2)
        self._assert_valid_pair_advanced(graph, ("ent_a", "ent_b"), "新_ab")
        self._assert_valid_pair_advanced(graph, ("ent_c", "ent_d"), "新_cd")

    def test_dry_run_does_not_write_but_still_reports_skip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            drafts, graph_path = self._seed(root)
            before = graph_path.read_text(encoding="utf-8")
            result = apply_advance_proposals(
                chapter_no=4,
                proposal_indexes="0,1,2",
                confirm=False,
                graph_path=graph_path,
                drafts_dir=drafts,
            )
            after = graph_path.read_text(encoding="utf-8")
        # confirm=False: graph file untouched, but skip is still surfaced.
        self.assertEqual(before, after)
        self.assertEqual(result["applied_count"], 2)
        self.assertEqual(len(result.get("skipped") or []), 1)

    def test_renderer_surfaces_skip_warning(self) -> None:
        result = {
            "chapter_no": 4,
            "confirm": True,
            "selected": [0, 1, 2],
            "applied_count": 2,
            "diff": "--- a\n+++ b",
            "skipped": [
                {
                    "src_id": "ent_wuliang_east",
                    "dst_id": "ent_wuliang_west",
                    "reason": "relationship_not_found",
                }
            ],
        }
        rendered = render_apply_advance_result(result)
        self.assertIn("WARNING", rendered)
        self.assertIn("ent_wuliang_east <-> ent_wuliang_west", rendered)
        self.assertIn("applied_count=2", rendered)


class SkippedProposalLoggingTests(unittest.TestCase):
    """iter 051b (F5, carry-over from the iter 027 code review): the
    stale-proposal skip is correct behavior, but it used to be silent — no
    log trail for a high-confidence proposal that vanished. Both skip
    reasons must now emit a ``log_event`` audit record; applied proposals
    must stay silent."""

    def test_relationship_not_found_logs_event(self) -> None:
        from src.entity_advance import _apply_selected

        graph = {"relationships": []}
        proposal = {"src_id": "ent_a", "dst_id": "ent_b", "new_state": "x", "confidence": 0.9}
        with patch("src.entity_advance.log_event") as log:
            _updated, skipped = _apply_selected(graph, [proposal], 3)
        self.assertEqual(skipped[0]["reason"], "relationship_not_found")
        log.assert_called_once()
        args, kwargs = log.call_args
        self.assertEqual(args, ("entity_advance", "proposal_skipped"))
        self.assertEqual(kwargs["reason"], "relationship_not_found")
        self.assertEqual(kwargs["src_id"], "ent_a")
        self.assertEqual(kwargs["dst_id"], "ent_b")
        self.assertEqual(kwargs["chapter_no"], 3)
        self.assertEqual(kwargs["confidence"], 0.9)

    def test_timeline_not_a_list_logs_event(self) -> None:
        from src.entity_advance import _apply_selected

        graph = {
            "relationships": [
                {"src_id": "ent_a", "dst_id": "ent_b", "timeline": "corrupt"}
            ]
        }
        proposal = {"src_id": "ent_a", "dst_id": "ent_b", "new_state": "x", "confidence": 0.8}
        with patch("src.entity_advance.log_event") as log:
            _updated, skipped = _apply_selected(graph, [proposal], 5)
        self.assertEqual(skipped[0]["reason"], "timeline_not_a_list")
        log.assert_called_once()
        self.assertEqual(log.call_args.kwargs["reason"], "timeline_not_a_list")

    def test_applied_proposal_does_not_log(self) -> None:
        from src.entity_advance import _apply_selected

        graph = {
            "relationships": [
                {
                    "src_id": "ent_a",
                    "dst_id": "ent_b",
                    "timeline": [{"state": "旧", "active": True}],
                }
            ]
        }
        proposal = {"src_id": "ent_a", "dst_id": "ent_b", "new_state": "新", "confidence": 0.9}
        with patch("src.entity_advance.log_event") as log:
            _updated, skipped = _apply_selected(graph, [proposal], 1)
        self.assertEqual(skipped, [])
        log.assert_not_called()

    def test_skipped_result_structure_unchanged(self) -> None:
        # The audit log must not alter the public skipped/applied contract.
        from src.entity_advance import _apply_selected

        graph = {"relationships": []}
        proposal = {"src_id": "a", "dst_id": "b", "new_state": "x", "confidence": 0.7}
        with patch("src.entity_advance.log_event"):
            _updated, skipped = _apply_selected(graph, [proposal], 2)
        self.assertEqual(
            skipped,
            [{"src_id": "a", "dst_id": "b", "reason": "relationship_not_found"}],
        )


class ApplyAdvanceCreatesNewRelationshipTests(unittest.TestCase):
    """iter065 #6c: with ``allow_creation=True`` a high-confidence proposal for a
    pair absent from the graph CREATES a new relationship edge instead of being
    skipped as ``relationship_not_found``. Default off keeps legacy behavior
    byte-identical (covered by ApplyAdvanceSkipsMissingRelationshipTests).
    """

    def _apply(self, **kwargs):
        from src.entity_advance import _apply_selected

        graph = {
            "entities": [{"id": "ent_x", "name": "X"}, {"id": "ent_y", "name": "Y"}],
            "relationships": [],
        }
        proposal = {
            "src_id": "ent_x",
            "dst_id": "ent_y",
            "new_state": "结为同伴并肩作战",
            "trigger_event": "并肩",
            "confidence": kwargs.pop("confidence", 0.9),
            **kwargs.pop("proposal_extra", {}),
        }
        created: list = []
        with patch("src.entity_advance.log_event"):
            updated, skipped = _apply_selected(
                graph, [proposal], 7, created=created, **kwargs
            )
        return updated, skipped, created

    def test_default_off_still_skips_byte_identical(self) -> None:
        updated, skipped, created = self._apply()  # allow_creation defaults False
        self.assertEqual(created, [])
        self.assertEqual(updated["relationships"], [])
        self.assertEqual(
            skipped,
            [{"src_id": "ent_x", "dst_id": "ent_y", "reason": "relationship_not_found"}],
        )

    def test_high_confidence_creates_new_edge(self) -> None:
        updated, skipped, created = self._apply(
            allow_creation=True, creation_confidence=0.85, confidence=0.9
        )
        self.assertEqual(skipped, [])
        self.assertEqual(created, [{"src_id": "ent_x", "dst_id": "ent_y"}])
        self.assertEqual(len(updated["relationships"]), 1)
        rel = updated["relationships"][0]
        self.assertEqual((rel["src_id"], rel["dst_id"]), ("ent_x", "ent_y"))
        self.assertEqual(rel["relation_type"], "续写新建")
        entry = rel["timeline"][0]
        # anchor_chapter must match the existing advance format byte-for-byte.
        self.assertEqual(entry["anchor_chapter"], "续写第07章")
        self.assertEqual(entry["state"], "结为同伴并肩作战")
        self.assertTrue(entry["active"])
        self.assertEqual(entry["confidence"], 0.9)

    def test_proposal_relation_type_is_honored(self) -> None:
        updated, _skipped, _created = self._apply(
            allow_creation=True, proposal_extra={"relation_type": "师徒"}
        )
        self.assertEqual(updated["relationships"][0]["relation_type"], "师徒")

    def test_below_creation_confidence_is_skipped(self) -> None:
        updated, skipped, created = self._apply(
            allow_creation=True, creation_confidence=0.85, confidence=0.8
        )
        self.assertEqual(created, [])
        self.assertEqual(updated["relationships"], [])
        self.assertEqual(skipped[0]["reason"], "creation_below_confidence")

    def test_hard_conflict_state_refuses_creation(self) -> None:
        updated, skipped, created = self._apply(
            allow_creation=True,
            creation_confidence=0.85,
            confidence=0.99,
            proposal_extra={"new_state": "两人已死，彻底敌对"},
        )
        self.assertEqual(created, [])
        self.assertEqual(updated["relationships"], [])
        self.assertEqual(skipped[0]["reason"], "creation_hard_conflict")

    def test_empty_new_state_refuses_creation(self) -> None:
        # iter065 review P2: the explicit-index creation path bypasses
        # _is_applyable_proposal, so the creation branch must itself refuse an
        # empty new_state instead of persisting a stateless junk edge.
        updated, skipped, created = self._apply(
            allow_creation=True,
            creation_confidence=0.85,
            confidence=0.99,
            proposal_extra={"new_state": ""},
        )
        self.assertEqual(created, [])
        self.assertEqual(updated["relationships"], [])
        self.assertEqual(skipped[0]["reason"], "creation_empty_state")

    def test_nonfinite_confidence_refuses_creation(self) -> None:
        # iter066 #4: inf/nan confidence coerces to 0.0 on the write path, so it
        # falls below the creation gate instead of passing `nan < gate == False`.
        for bad in (float("inf"), float("nan"), float("-inf")):
            updated, skipped, created = self._apply(
                allow_creation=True, creation_confidence=0.85, confidence=bad
            )
            self.assertEqual(created, [], bad)
            self.assertEqual(updated["relationships"], [], bad)
            self.assertEqual(skipped[0]["reason"], "creation_below_confidence", bad)

    def test_ghost_entity_refuses_creation(self) -> None:
        # iter066 #2: src/dst must both exist in graph["entities"]; an id the
        # graph never knew (here ent_ghost) is refused, not persisted as a ghost.
        updated, skipped, created = self._apply(
            allow_creation=True, proposal_extra={"src_id": "ent_ghost"}
        )
        self.assertEqual(created, [])
        self.assertEqual(updated["relationships"], [])
        self.assertEqual(skipped[0]["reason"], "creation_unknown_entity")

    def test_whitespace_id_is_stripped_and_raises(self) -> None:
        # iter066 #2: a whitespace-only id strips to empty and raises (structural
        # defect) instead of slipping through the non-empty check as `"  "`.
        from src.entity_advance import _apply_selected

        graph = {"entities": [{"id": "ent_y"}], "relationships": []}
        proposal = {"src_id": "  ", "dst_id": "ent_y", "new_state": "x", "confidence": 0.9}
        with patch("src.entity_advance.log_event"):
            with self.assertRaises(ValueError):
                _apply_selected(graph, [proposal], 1, allow_creation=True)

    def test_public_apply_surfaces_created_count(self) -> None:
        # End-to-end via the public entry, mirroring book_runner's call shape.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            drafts = root / "drafts"
            graph_path = root / "entity_graph.json"
            graph_path.write_text(
                json.dumps(
                    {
                        "entities": [{"id": "ent_x", "name": "X"}, {"id": "ent_y", "name": "Y"}],
                        "relationships": [],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            save_entity_advance_proposals(
                7,
                [
                    {
                        "src_id": "ent_x",
                        "dst_id": "ent_y",
                        "new_state": "结为同伴并肩作战",
                        "trigger_event": "并肩",
                        "confidence": 0.9,
                    }
                ],
                drafts_dir=drafts,
            )
            result = apply_advance_proposals(
                chapter_no=7,
                proposal_indexes="0",
                confirm=True,
                graph_path=graph_path,
                drafts_dir=drafts,
                allow_empty=True,
                allow_creation=True,
                creation_confidence=0.85,
            )
            graph = json.loads(graph_path.read_text(encoding="utf-8"))

        self.assertEqual(result.get("created_count"), 1)
        self.assertEqual(result.get("applied_count"), 0)  # creation != advance
        self.assertNotIn("skipped", result)
        self.assertEqual(len(graph["relationships"]), 1)


class ApplySelectedLegacyConfidenceTests(unittest.TestCase):
    """iter066 #4: the legacy advance path (existing edge) must write a FINITE
    confidence to the timeline — a nan/inf collapses to 0.0, never a non-standard
    JSON literal (``NaN``/``Infinity``) that downstream JSON parsers choke on."""

    def test_legacy_advance_coerces_nonfinite_confidence(self) -> None:
        from src.entity_advance import _apply_selected

        graph = {
            "entities": [{"id": "ent_a"}, {"id": "ent_b"}],
            "relationships": [
                {"src_id": "ent_a", "dst_id": "ent_b", "timeline": [{"state": "旧", "active": True}]}
            ],
        }
        proposal = {"src_id": "ent_a", "dst_id": "ent_b", "new_state": "新", "confidence": float("inf")}
        with patch("src.entity_advance.log_event"):
            updated, skipped = _apply_selected(graph, [proposal], 3)
        self.assertEqual(skipped, [])
        entry = updated["relationships"][0]["timeline"][-1]
        self.assertEqual(entry["state"], "新")
        self.assertEqual(entry["confidence"], 0.0)  # inf coerced → standard JSON


if __name__ == "__main__":
    unittest.main()
