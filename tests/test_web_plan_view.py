"""iter 034: Plan viewer aggregation unit tests."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src import paths
from src.web.plan_view import collect_plan
from src.web.workspace_ctx import use_workspace


class PlanViewTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._saved = paths.WORKSPACE_DIR
        paths.WORKSPACE_DIR = Path(self._tmp.name)
        ws = paths.WORKSPACE_DIR / "alpha"
        (ws / "data").mkdir(parents=True)
        (ws / "outputs" / "drafts").mkdir(parents=True)
        (ws / "outputs" / "debate").mkdir(parents=True)
        (ws / "outputs" / "debate" / "chapter_plan.json").write_text(
            json.dumps(
                {
                    "target_chapters": 3,
                    "overall_arc": "arc",
                    "start_chapter_id": "alpha_ch001",
                    "plan_fingerprint": "abc1234567890",
                    "chapters": [
                        {"chapter_no": 1, "title": "t1", "key_events": ["e1", "e2"]},
                        {"chapter_no": 2, "title": "t2"},
                        {"chapter_no": 3, "title": "t3"},
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (ws / "outputs" / "debate" / "outline.md").write_text(
            "# 标题\n\n## 二级\n\n- 项 a\n- 项 b\n\n段落正文。\n",
            encoding="utf-8",
        )
        (ws / "outputs" / "debate" / "decisions.json").write_text(
            json.dumps(
                {
                    "topic": "T",
                    "aggregation_method": "majority",
                    "transcript_items": 12,
                    "votes": [
                        {
                            "question": "Q1",
                            "result": "R1",
                            "for": ["A"],
                            "against": [],
                            "agent_votes": [{"agent_name": "X", "position": "agree", "reason": "ok"}],
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        (ws / "outputs" / "drafts" / "chapter_01.md").write_text("body", encoding="utf-8")
        (ws / "outputs" / "drafts" / "chapter_01.meta.json").write_text(
            json.dumps({"verdict": "Approve"}, ensure_ascii=False), encoding="utf-8"
        )

    def tearDown(self) -> None:
        paths.WORKSPACE_DIR = self._saved
        self._tmp.cleanup()

    def test_collect_plan_full(self) -> None:
        with use_workspace("alpha"):
            data = collect_plan()
        self.assertEqual(data["plan"]["target_chapters"], 3)
        self.assertIn("二级", data["outline_md"])
        self.assertEqual(data["decisions"]["votes"][0]["question"], "Q1")
        self.assertEqual(data["draft_chapters"], [1])
        self.assertEqual(data["draft_verdicts"], {"1": "Approve"})

    def test_collect_plan_missing_files_returns_empties(self) -> None:
        debate = paths.WORKSPACE_DIR / "alpha" / "outputs" / "debate"
        for item in debate.iterdir():
            item.unlink()
        with use_workspace("alpha"):
            data = collect_plan()
        self.assertEqual(data["plan"], {})
        self.assertEqual(data["outline_md"], "")
        self.assertEqual(data["decisions"], {})
        self.assertEqual(data["draft_chapters"], [1])


if __name__ == "__main__":
    unittest.main()
