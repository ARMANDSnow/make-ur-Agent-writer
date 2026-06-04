from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from src import paths
from src.web import static
from src.web.insights import collect_insights
from src.web.workspace_ctx import use_workspace


class StaticSubscoreCompatTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._saved_ws_dir = paths.WORKSPACE_DIR
        self._saved_env = os.environ.get("WORKSPACE_NAME")
        os.environ.pop("WORKSPACE_NAME", None)
        paths.WORKSPACE_DIR = Path(self._tmp.name)
        ws = paths.WORKSPACE_DIR / "alpha"
        (ws / "outputs" / "drafts").mkdir(parents=True)
        (ws / "outputs" / "reviews").mkdir(parents=True)
        (ws / "logs").mkdir(parents=True)
        (ws / "data").mkdir(parents=True)
        (ws / "小说txt").mkdir(parents=True)
        (ws / "outputs" / "drafts" / "chapter_01.md").write_text("draft", encoding="utf-8")
        (ws / "outputs" / "reviews" / "chapter_01.review.json").write_text(
            json.dumps(
                {
                    "verdict": "Approve",
                    "agent_reviews": [
                        {
                            "agent_name": "A",
                            "verdict": "Approve",
                            "score": 8,
                            "scores": {"plot": 9, "prose": 7, "fidelity": 8},
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        paths.WORKSPACE_DIR = self._saved_ws_dir
        if self._saved_env is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._saved_env
        self._tmp.cleanup()

    def test_chapter_detail_js_accepts_scores_and_legacy_sub_scores(self) -> None:
        self.assertIn("a.scores && Object.keys(a.scores).length", static.JS_DASHBOARD)
        self.assertIn(": a.sub_scores) || {}", static.JS_DASHBOARD)
        self.assertIn(".subscore-cell-approve", static.CSS_BODY)
        self.assertNotIn('td style="text-align:center;background:', static.JS_DASHBOARD)

    def test_insights_aggregates_scores_field(self) -> None:
        with use_workspace("alpha"):
            data = collect_insights()
        self.assertEqual(len(data["subscores"]), 1)
        row = data["subscores"][0]
        self.assertEqual(row["chapter"], 1)
        self.assertAlmostEqual(row["plot"], 9.0)
        self.assertAlmostEqual(row["prose"], 7.0)
        self.assertAlmostEqual(row["fidelity"], 8.0)
        self.assertEqual(row["agents"], 1)


if __name__ == "__main__":
    unittest.main()
