"""Iter 019: apply-advance --auto-apply regression tests.

Covers the new ``select_auto_indexes`` pure helper, the
``apply_advance_proposals`` ``auto_apply / min_confidence / allow_empty``
kwargs, and the back-compat path so legacy callers (iter 011-018) keep
working with no changes.
"""

import json
import tempfile
import unittest
from pathlib import Path

from src.cli_apply_advance import apply_advance_cli
from src.entity_advance import (
    apply_advance_proposals,
    save_entity_advance_proposals,
    select_auto_indexes,
)


def _seed_graph(graph_path: Path) -> None:
    graph_path.write_text(
        json.dumps(
            {
                "relationships": [
                    {
                        "src_id": "a",
                        "dst_id": "b",
                        "relation_type": "ally",
                        "timeline": [{"state": "前", "active": True}],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _seed_proposals(drafts: Path, confidences):
    proposals = [
        {
            "src_id": "a",
            "dst_id": "b",
            "old_active_state": "前",
            "new_state": f"after_{i}",
            "trigger_event": "evt",
            "confidence": c,
        }
        for i, c in enumerate(confidences)
    ]
    save_entity_advance_proposals(1, proposals, drafts_dir=drafts)
    return proposals


class SelectAutoIndexesTests(unittest.TestCase):
    def test_picks_only_proposals_meeting_threshold(self) -> None:
        proposals = [
            {"confidence": 0.95},
            {"confidence": 0.5},
            {"confidence": 0.7},
            {"confidence": 0.69},
        ]
        self.assertEqual(select_auto_indexes(proposals, min_confidence=0.7), [0, 2])

    def test_returns_empty_when_none_qualify(self) -> None:
        proposals = [{"confidence": 0.1}, {"confidence": 0.3}]
        self.assertEqual(select_auto_indexes(proposals, min_confidence=0.7), [])

    def test_skips_malformed_rows(self) -> None:
        proposals = [
            {"confidence": 0.9},
            "not a dict",
            {"confidence": "not a float"},
            {"confidence": 0.8},
        ]
        # Malformed entries are dropped silently; only valid >= threshold rows count.
        self.assertEqual(select_auto_indexes(proposals, min_confidence=0.7), [0, 3])


class ApplyAdvanceAutoCliTests(unittest.TestCase):
    def test_auto_apply_confirm_writes_graph_for_high_confidence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            drafts = root / "drafts"
            graph_path = root / "entity_graph.json"
            _seed_graph(graph_path)
            _seed_proposals(drafts, [0.95])
            result = apply_advance_proposals(
                chapter_no=1,
                confirm=True,
                graph_path=graph_path,
                drafts_dir=drafts,
                auto_apply=True,
                min_confidence=0.7,
            )
            self.assertEqual(result["applied_count"], 1)
            self.assertTrue(result["auto_apply"])
            self.assertEqual(result["min_confidence"], 0.7)
            data = json.loads(graph_path.read_text(encoding="utf-8"))
            timeline = data["relationships"][0]["timeline"]
            # Original is now inactive, new entry is active.
            self.assertFalse(timeline[0]["active"])
            self.assertTrue(timeline[1]["active"])
            self.assertEqual(timeline[1]["state"], "after_0")

    def test_auto_apply_empty_with_allow_empty_returns_noop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            drafts = root / "drafts"
            graph_path = root / "entity_graph.json"
            _seed_graph(graph_path)
            _seed_proposals(drafts, [0.2, 0.4])  # all below default 0.7
            result = apply_advance_proposals(
                chapter_no=1,
                confirm=True,
                graph_path=graph_path,
                drafts_dir=drafts,
                auto_apply=True,
                min_confidence=0.7,
                allow_empty=True,
            )
            self.assertEqual(result["applied_count"], 0)
            self.assertEqual(result.get("no_op_reason"), "empty_selection")
            # Graph remains untouched.
            data = json.loads(graph_path.read_text(encoding="utf-8"))
            self.assertEqual(len(data["relationships"][0]["timeline"]), 1)

    def test_min_confidence_strict_filters_out_borderline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            drafts = root / "drafts"
            graph_path = root / "entity_graph.json"
            _seed_graph(graph_path)
            _seed_proposals(drafts, [0.9, 0.94])  # both below 0.95
            result = apply_advance_proposals(
                chapter_no=1,
                confirm=True,
                graph_path=graph_path,
                drafts_dir=drafts,
                auto_apply=True,
                min_confidence=0.95,
                allow_empty=True,
            )
            self.assertEqual(result["applied_count"], 0)

    def test_legacy_proposal_idx_path_unchanged(self) -> None:
        # iter 011/018 callers: only chapter / proposal_idx / confirm — the
        # new auto_apply / min_confidence kwargs MUST default to False / 0.7
        # and NOT affect behavior. Verify by calling the underlying function
        # the legacy way (positional/explicit indexes) and checking the
        # result dict still applies the requested index and reports
        # auto_apply=False.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            drafts = root / "drafts"
            graph_path = root / "entity_graph.json"
            _seed_graph(graph_path)
            _seed_proposals(drafts, [0.95])
            result = apply_advance_proposals(
                chapter_no=1,
                proposal_indexes="0",
                confirm=True,
                graph_path=graph_path,
                drafts_dir=drafts,
            )
            self.assertEqual(result["applied_count"], 1)
            self.assertFalse(result.get("auto_apply"))
            self.assertIsNone(result.get("min_confidence"))


if __name__ == "__main__":
    unittest.main()
