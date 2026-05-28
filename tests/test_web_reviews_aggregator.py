"""iter 025: reviews_aggregator filters demos, preserves full fields."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.web.reviews_aggregator import aggregate_reviews


def _write_meta(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _ch_meta(verdict: str = "Approve", rewrite_count: int = 0, extra: dict | None = None) -> dict:
    base = {
        "target": "outputs/drafts/chapter_NN.md",
        "verdict": verdict,
        "rewrite_count": rewrite_count,
        "rewrite_round": rewrite_count,
        "chinese_char_count": 4000,
        "needs_human_review": False,
        "polish_applied": False,
        "lint_issues": [],
        "agent_reviews": [
            {
                "agent_name": "PlotMaster",
                "verdict": "Approve",
                "score": 7,
                "issues": ["pace OK"],
                "suggestions": ["tighten intro"],
                "comparison_checklist": [],
            }
        ],
    }
    if extra:
        base.update(extra)
    return base


class AggregateReviewsTests(unittest.TestCase):
    def test_returns_empty_for_missing_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            drafts = Path(tmp) / "drafts"  # not created
            result = aggregate_reviews(drafts)
        self.assertEqual(result["chapters"], [])
        self.assertEqual(result["stats"]["total"], 0)
        self.assertEqual(result["stats"]["advisor_suggestions_total"], 0)

    def test_filters_demo_and_backup_variants(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            drafts = Path(tmp)
            _write_meta(drafts / "chapter_01.meta.json", _ch_meta())
            _write_meta(drafts / "chapter_02.meta.json", _ch_meta(verdict="Reject", rewrite_count=2))
            _write_meta(drafts / "chapter_01_iter024_advisor_demo.meta.json", _ch_meta())
            _write_meta(drafts / "chapter_03.meta_backup.json", _ch_meta())
            result = aggregate_reviews(drafts)
        self.assertEqual([c["chapter"] for c in result["chapters"]], [1, 2])
        self.assertEqual(result["stats"]["total"], 2)
        self.assertEqual(result["stats"]["accepted"], 1)
        self.assertEqual(result["stats"]["rewrite_max"], 2)

    def test_preserves_full_agent_review_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            drafts = Path(tmp)
            _write_meta(drafts / "chapter_01.meta.json", _ch_meta())
            result = aggregate_reviews(drafts)
        ch1 = result["chapters"][0]
        review = ch1["agent_reviews"][0]
        self.assertEqual(review["agent_name"], "PlotMaster")
        self.assertEqual(review["score"], 7)
        self.assertEqual(review["issues"], ["pace OK"])
        self.assertEqual(review["suggestions"], ["tighten intro"])

    def test_aggregates_advisor_rewrite_suggestions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            drafts = Path(tmp)
            _write_meta(
                drafts / "chapter_01.meta.json",
                _ch_meta(
                    extra={
                        "rewrite_suggestions": [
                            {"section": "开场", "type": "rewrite", "guidance": "...", "_advisor": "改写顾问"},
                            {"section": "结尾", "type": "add", "guidance": "...", "_advisor": "改写顾问"},
                        ]
                    }
                ),
            )
            _write_meta(drafts / "chapter_02.meta.json", _ch_meta())
            result = aggregate_reviews(drafts)
        self.assertEqual(len(result["chapters"][0]["rewrite_suggestions"]), 2)
        self.assertEqual(result["stats"]["advisor_suggestions_total"], 2)

    def test_preserves_lint_issues(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            drafts = Path(tmp)
            _write_meta(
                drafts / "chapter_01.meta.json",
                _ch_meta(extra={"lint_issues": [{"rule": "not_x_but_y", "count": 3}]}),
            )
            result = aggregate_reviews(drafts)
        self.assertEqual(result["chapters"][0]["lint_issues"], [{"rule": "not_x_but_y", "count": 3}])

    def test_null_list_fields_do_not_crash(self) -> None:
        """Iter 025 code-review #4: meta.json may contain JSON null for
        list fields (reviewer / advisor pipeline can short-circuit a
        section). aggregate_reviews must treat null as empty, not raise
        TypeError from list(None)."""
        with tempfile.TemporaryDirectory() as tmp:
            drafts = Path(tmp)
            payload = _ch_meta()
            payload["lint_issues"] = None
            payload["agent_reviews"] = None
            payload["rewrite_suggestions"] = None
            _write_meta(drafts / "chapter_01.meta.json", payload)
            result = aggregate_reviews(drafts)
        ch1 = result["chapters"][0]
        self.assertEqual(ch1["lint_issues"], [])
        self.assertEqual(ch1["agent_reviews"], [])
        self.assertEqual(ch1["rewrite_suggestions"], [])
        self.assertEqual(result["stats"]["total"], 1)

    def test_three_digit_chapters_visible(self) -> None:
        """Iter 025 code-review #1: regex now matches \\d{2,} so capstone
        runs past ch99 stay visible on the dashboard."""
        with tempfile.TemporaryDirectory() as tmp:
            drafts = Path(tmp)
            _write_meta(drafts / "chapter_99.meta.json", _ch_meta())
            _write_meta(drafts / "chapter_100.meta.json", _ch_meta())
            _write_meta(drafts / "chapter_137.meta.json", _ch_meta())
            # 1-digit should still be skipped (filename shape contract)
            _write_meta(drafts / "chapter_7.meta.json", _ch_meta())
            result = aggregate_reviews(drafts)
        self.assertEqual([c["chapter"] for c in result["chapters"]], [99, 100, 137])

    def test_needs_human_review_counted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            drafts = Path(tmp)
            _write_meta(drafts / "chapter_01.meta.json", _ch_meta(extra={"needs_human_review": True}))
            _write_meta(drafts / "chapter_02.meta.json", _ch_meta())
            result = aggregate_reviews(drafts)
        self.assertEqual(result["stats"]["needs_human_review"], 1)


if __name__ == "__main__":
    unittest.main()
