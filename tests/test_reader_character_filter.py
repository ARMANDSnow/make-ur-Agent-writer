"""iter 047d: reader_known / character_known spoiler axes (lightweight, fail-open).

On top of the iter-021 start-point (chapter_id) filter, an active relationship
timeline entry / a global fact may optionally carry:
* ``reader_known`` / ``reader_known_after`` — the reader learns it only after
  the start, so it's hidden pre-start even if its chapter_id is pre-start.
* ``character_known`` {char_id: chapter_id} — when a POV ``viewpoint`` is given,
  hide states that POV character doesn't know yet.
Absent these fields, behavior is byte-identical to iter 021 (fail-open).
"""

import json
import os
import shutil
import unittest
from pathlib import Path

START = "s_ch002"


class ReaderCharacterFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old = os.environ.get("WORKSPACE_NAME")
        os.environ["WORKSPACE_NAME"] = "iter047d"
        root = Path(__file__).resolve().parent.parent
        self.ws = root / "workspaces" / "iter047d"
        (self.ws / "data" / "manual_overrides").mkdir(parents=True, exist_ok=True)
        manifest = [{"chapter_id": f"s_ch00{i}", "volume_id": "s", "title": str(i)} for i in (1, 2, 3)]
        (self.ws / "data" / "chapter_manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )
        from src import start_point

        start_point.set_start_point(START)

    def tearDown(self) -> None:
        if self.ws.exists():
            shutil.rmtree(self.ws)
        if self._old is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._old

    def _graph(self, item_extra: dict) -> dict:
        item = {"active": True, "state": "SECRET_STATE", "chapter_id": "s_ch001"}
        item.update(item_extra)
        return {
            "entities": [{"id": "a", "name": "alpha"}, {"id": "b", "name": "beta"}],
            "relationships": [{"src_id": "a", "dst_id": "b", "relation_type": "r", "timeline": [item]}],
        }

    def test_missing_new_fields_unchanged(self) -> None:
        # only chapter_id s_ch001 (pre-start) -> kept, exactly like iter 021.
        from src.entities import render_active_state

        self.assertIn("SECRET_STATE", render_active_state(self._graph({})))

    def test_reader_known_after_start_hidden(self) -> None:
        from src.entities import render_active_state

        out = render_active_state(self._graph({"reader_known": "s_ch003"}))
        self.assertNotIn("SECRET_STATE", out)  # reader learns it post-start

    def test_character_known_viewpoint(self) -> None:
        from src.entities import render_active_state

        g = self._graph({"character_known": {"a": "s_ch001", "b": "s_ch003"}})
        # reader view (no viewpoint) ignores character_known -> kept
        self.assertIn("SECRET_STATE", render_active_state(g))
        # POV alpha knows at s_ch001 (pre-start) -> kept
        self.assertIn("SECRET_STATE", render_active_state(g, viewpoint="a"))
        # POV beta knows at s_ch003 (post-start) -> hidden
        self.assertNotIn("SECRET_STATE", render_active_state(g, viewpoint="b"))
        # POV not in the character_known map -> fail-open keep (missing info ≠ hide)
        self.assertIn("SECRET_STATE", render_active_state(g, viewpoint="c"))

    def test_no_start_point_disables_reader_known(self) -> None:
        # reader_known only matters relative to a start point; with none set the
        # whole spoiler filter is off, so the state stays visible.
        from src import start_point
        from src.entities import render_active_state

        start_point.clear_start_point()
        self.assertIn("SECRET_STATE", render_active_state(self._graph({"reader_known": "s_ch003"})))

    def test_fact_reader_known_after_hidden(self) -> None:
        from src.manual_facts import global_facts_summary

        facts = {
            "facts": [
                {
                    "fact_id": "reader_late",
                    "statement": "LATE_FACT",
                    "scope": "global",
                    "evidence_spans": [{"source_file": "x", "chapter_id": "s_ch001", "start_line": 1, "end_line": 2}],
                    "reader_known_after": "s_ch003",
                },
                {
                    "fact_id": "early_ok",
                    "statement": "EARLY_FACT",
                    "scope": "global",
                    "evidence_spans": [{"source_file": "x", "chapter_id": "s_ch001", "start_line": 1, "end_line": 2}],
                },
            ]
        }
        (self.ws / "data" / "manual_overrides" / "global_facts.json").write_text(
            json.dumps(facts, ensure_ascii=False), encoding="utf-8"
        )
        out = global_facts_summary(respect_start_point=True)
        self.assertIn("EARLY_FACT", out)
        self.assertNotIn("LATE_FACT", out)  # reader_known_after is post-start


if __name__ == "__main__":
    unittest.main()
