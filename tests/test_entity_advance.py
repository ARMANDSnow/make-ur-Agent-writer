import json
import tempfile
import unittest
from pathlib import Path

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


if __name__ == "__main__":
    unittest.main()
