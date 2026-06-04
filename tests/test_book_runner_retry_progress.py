import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.book_runner import run_write_book


def _status(chapter_no: int, *, exists: bool, approved: bool, verdict: str | None = None) -> dict:
    return {
        "chapter_no": chapter_no,
        "exists": exists,
        "approved": approved,
        "needs_review": False,
        "failure": False,
        "verdict": verdict or ("Approve" if approved else None),
        "rewrite_count": 0,
        "strict_failures": [],
    }


class BookRunnerRetryProgressTests(unittest.TestCase):
    def test_outer_retry_progress_is_monotonic_and_prefixed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            drafts = root / "outputs" / "drafts"
            drafts.mkdir(parents=True)
            progress: list[tuple[str, float]] = []

            statuses = [
                _status(1, exists=False, approved=False),
                _status(1, exists=True, approved=False, verdict="Reject"),
                _status(1, exists=True, approved=True),
            ]

            def fake_write_chapters(**kwargs):
                progress_cb = kwargs["progress_cb"]
                progress_cb("write-attempt-1", 0.05)
                progress_cb("review-attempt-1", 0.50)
                progress_cb("review-done-attempt-1", 0.60)
                progress_cb("finalize", 0.95)
                return [{"chapter": kwargs["resume_from"], "written": True}]

            with patch("src.book_runner.paths.workspace_name", return_value="unit"), patch(
                "src.book_runner.paths.workspace_root", return_value=root
            ), patch("src.book_runner.paths.drafts_dir", return_value=drafts), patch(
                "src.book_runner.paths.llm_calls_log_path", return_value=root / "logs" / "llm_calls.jsonl"
            ), patch(
                "src.book_runner.run_preflight", return_value={"status": "ok", "fatal": [], "warn": [], "info": []}
            ), patch(
                "src.book_runner._load_raw_chapter_plan", return_value={}
            ), patch(
                "src.book_runner._load_chapter_plan", return_value=None
            ), patch(
                "src.book_runner.chapter_status", side_effect=statuses
            ), patch(
                "src.book_runner.write_chapters", side_effect=fake_write_chapters
            ), patch(
                "src.book_runner.prune_from_chapter", return_value=None
            ), patch(
                "src.book_runner._snapshot", side_effect=lambda status, payload: {"status": status, **payload}
            ):
                result = run_write_book(
                    chapters=1,
                    max_retries=1,
                    auto_advance=False,
                    require_start_point=False,
                    require_plan=False,
                    require_external_review=False,
                    progress_cb=lambda step, fraction: progress.append((step, fraction)),
                )

            self.assertEqual(result["status"], "succeeded")
            fractions = [fraction for _, fraction in progress]
            self.assertEqual(fractions, sorted(fractions))
            steps = [step for step, _ in progress]
            self.assertIn("chapter-1/retry-1/write-attempt-1", steps)


if __name__ == "__main__":
    unittest.main()
