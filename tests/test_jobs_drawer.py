import unittest

from src.web import static


class JobsDrawerTests(unittest.TestCase):
    def test_job_actionable_summary_status_reason_matrix(self) -> None:
        statuses = {
            "succeeded": "✓ succeeded",
            "blocked": "! blocked",
            "failed": "! failed",
            "lost": "? lost",
        }
        reasons = ("start_point_missing", "retry_exhausted")
        for status, prefix in statuses.items():
            for reason in reasons:
                with self.subTest(status=status, reason=reason):
                    job = {
                        "status": status,
                        "result_summary": {
                            "first_blocked": {
                                "chapter": 2,
                                "reason": reason,
                                "error": "sample error",
                            },
                            "snapshot_path": "outputs/drafts/snapshots/sample.json",
                        },
                    }
                    summary = static.job_actionable_summary(job)
                    self.assertTrue(summary.startswith(prefix), summary)
                    if status != "succeeded":
                        self.assertIn(reason, summary)

    def test_static_js_has_jobs_drawer_recovery_hooks(self) -> None:
        js = static.JS_DASHBOARD
        self.assertIn("function jobActionableSummary", js)
        self.assertIn("function renderJobDrawer", js)
        self.assertIn("data-job-retry", js)
        self.assertIn("data-job-partial", js)
        self.assertIn("variant=partial", js)


if __name__ == "__main__":
    unittest.main()
