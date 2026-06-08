import json
import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
