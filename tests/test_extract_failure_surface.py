"""iter058 #2: per-chapter extraction failures must stop being silently
swallowed.

``extract_all(raise_on_failure=False)`` writes failed chapters to
data/extraction_failures/ and otherwise returns a short results list — the
onboarding/prepare callers then reported success while the KB was missing
chapters. Hybrid fix (user-chosen):

* standalone ``/run extract`` (jobs._step_extract) → friendly, retryable
  ``blocked: extraction_failures`` (extracted chapters stay on disk);
* onboarding/prepare (auto_pipeline._run_prepare_steps) → loud raise so the
  pipeline never builds compress/bootstrap/debate/write on degraded data.

Mock-only; the failure is injected by patching extract_all so no real LLM /
network is involved.
"""

from __future__ import annotations

import unittest
from unittest.mock import patch

from src import auto_pipeline
from src.extractor import ExtractionBatchFailure
from src.web import jobs


def _noop(*_a, **_k) -> None:
    return None


class StepExtractBlockedTests(unittest.TestCase):
    """jobs._step_extract → blocked (not a swallow, not a hard crash)."""

    def test_failure_surfaces_as_blocked(self) -> None:
        with patch("src.web.jobs.paths.chapter_manifest_path") as mpath, \
                patch(
                    "src.web.jobs.extract_all",
                    side_effect=ExtractionBatchFailure(["ch_002"], extracted=1),
                ):
            mpath.return_value.exists.return_value = True
            result = jobs._step_extract({}, _noop)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["blocked"][0]["reason"], "extraction_failures")
        # The carried message names the failed chapter and the resume hint.
        self.assertIn("ch_002", result["blocked"][0]["error"])

    def test_step_extract_opts_into_raise_on_failure(self) -> None:
        with patch("src.web.jobs.paths.chapter_manifest_path") as mpath, \
                patch("src.web.jobs.extract_all", return_value=[{"chapter_id": "ch_001"}]) as ext:
            mpath.return_value.exists.return_value = True
            jobs._step_extract({}, _noop)
        self.assertTrue(ext.call_args.kwargs["raise_on_failure"])

    def test_success_path_unchanged(self) -> None:
        results = [{"chapter_id": "ch_001"}]
        with patch("src.web.jobs.paths.chapter_manifest_path") as mpath, \
                patch("src.web.jobs.extract_all", return_value=results):
            mpath.return_value.exists.return_value = True
            self.assertEqual(jobs._step_extract({}, _noop), results)


class OnboardingPrepareRaisesTests(unittest.TestCase):
    """auto_pipeline._run_prepare_steps → loud raise on extraction failure."""

    def test_prepare_raises_on_extraction_failure(self) -> None:
        with patch("src.auto_pipeline.normalize_all", return_value=[]), \
                patch("src.auto_pipeline.split_all", return_value=[]), \
                patch(
                    "src.auto_pipeline.extract_all",
                    side_effect=ExtractionBatchFailure(["ch_002"], extracted=1),
                ):
            with self.assertRaises(ExtractionBatchFailure):
                auto_pipeline._run_prepare_steps(total=9)

    def test_prepare_opts_into_raise_on_failure(self) -> None:
        with patch("src.auto_pipeline.normalize_all", return_value=[]), \
                patch("src.auto_pipeline.split_all", return_value=[]), \
                patch("src.auto_pipeline.extract_all", return_value=[]) as ext, \
                patch("src.auto_pipeline.compress_all", return_value=[]), \
                patch("src.auto_pipeline.bootstrap_all", return_value={}):
            auto_pipeline._run_prepare_steps(total=9)
        self.assertTrue(ext.call_args.kwargs["raise_on_failure"])

    def test_skip_extract_does_not_raise(self) -> None:
        # The skip_extract path never calls extract_all, so it can't raise.
        with patch("src.auto_pipeline.normalize_all", return_value=[]), \
                patch("src.auto_pipeline.split_all", return_value=[]), \
                patch("src.auto_pipeline.compress_all", return_value=[]), \
                patch("src.auto_pipeline.bootstrap_all", return_value={}), \
                patch("src.auto_pipeline.extract_all") as ext:
            out = auto_pipeline._run_prepare_steps(total=9, skip_extract=True)
        ext.assert_not_called()
        self.assertEqual(out["extract"], {"skipped": True})


if __name__ == "__main__":
    unittest.main()
