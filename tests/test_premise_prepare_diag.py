"""iter 048a: workbench backend skeleton — premise开书 entry,
prepare-greenfield composite step (progress-contract fix), and the全 task
test-Key diagnostics matrix. Mock-only: no network, no real model.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from src import auto_pipeline, paths
from src.llm_client import LLMClient
from src.web import diag, jobs, routes
from src.web.workspace_ctx import use_workspace


class PremisePrepareDiagTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ["OPENAI_MODEL"] = "mock"
        self._tmp = tempfile.TemporaryDirectory()
        self._saved_ws_dir = paths.WORKSPACE_DIR
        self._saved_env = os.environ.get("WORKSPACE_NAME")
        os.environ.pop("WORKSPACE_NAME", None)
        paths.WORKSPACE_DIR = Path(self._tmp.name)
        jobs.reset_for_tests()

    def tearDown(self) -> None:
        paths.WORKSPACE_DIR = self._saved_ws_dir
        if self._saved_env is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._saved_env
        jobs.reset_for_tests()
        self._tmp.cleanup()

    # ---- helpers ----------------------------------------------------------

    def _premise_start(self, ws: str, premise: str = "一个关于测试的前提故事，主角在异世界觉醒。") -> tuple[int, dict]:
        status, _ct, resp = routes.dispatch(
            "POST",
            "/api/wizard/premise-start",
            json.dumps({"workspace": ws, "premise": premise}, ensure_ascii=False).encode("utf-8"),
            {"content-type": "application/json"},
        )
        return status, json.loads(resp)

    def _wait_for_done(self, ws: str, job_id: str, timeout: float = 30.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            _, _, body = routes.dispatch("GET", f"/api/workspace/{ws}/job/{job_id}")
            rec = json.loads(body)
            if rec.get("status") in ("succeeded", "blocked", "failed", "aborted", "lost"):
                return rec
            time.sleep(0.05)
        self.fail("job did not finish")

    # ---- premise开书 entry -----------------------------------------------

    def test_premise_start_creates_workspace_and_seed(self) -> None:
        status, data = self._premise_start("seedbook", "少年觉醒系统，踏上修行路。")
        self.assertEqual(status, 202, data)
        # iter 051a: response carries expansion_job_id (None unless the
        # caller opts in with expand=true — API default keeps create-only).
        self.assertEqual(data, {"name": "seedbook", "expansion_job_id": None})
        self.assertNotIn("job_id", data)  # premise starts NO pipeline job
        seed = paths.WORKSPACE_DIR / "seedbook" / "小说txt" / "seed.txt"
        self.assertTrue(seed.exists(), f"missing {seed}")
        # seed.txt wraps the premise as a single-chapter doc so split can
        # produce ≥1 chapter; the premise text itself must be present.
        seed_text = seed.read_text(encoding="utf-8")
        self.assertIn("少年觉醒系统，踏上修行路。", seed_text)
        self.assertIn("第一章", seed_text)

    def test_premise_missing_or_empty_400(self) -> None:
        for premise in ("", "   "):
            status, data = self._premise_start("emptybook", premise)
            self.assertEqual(status, 400, data)
            self.assertIn("premise", data["error"])

    def test_premise_too_long_400(self) -> None:
        status, data = self._premise_start("longbook", "字" * 2001)
        self.assertEqual(status, 400, data)
        self.assertIn("too long", data["error"])

    def test_premise_invalid_name_400(self) -> None:
        status, data = self._premise_start("-bad-")
        self.assertEqual(status, 400, data)
        self.assertIn("invalid workspace name", data["error"])

    def test_premise_existing_409(self) -> None:
        first, _ = self._premise_start("dupbook")
        self.assertEqual(first, 202)
        again, data = self._premise_start("dupbook")
        self.assertEqual(again, 409, data)

    def test_premise_requires_json_content_type(self) -> None:
        status, _ct, resp = routes.dispatch(
            "POST",
            "/api/wizard/premise-start",
            json.dumps({"workspace": "ctbook", "premise": "x"}).encode("utf-8"),
            {"content-type": "text/plain"},
        )
        self.assertEqual(status, 415, resp.decode("utf-8"))

    # ---- prepare-greenfield composite step + progress contract -----------

    def test_prepare_greenfield_job_succeeds_with_done_progress(self) -> None:
        """End-to-end via POST /run: the composite step runs the 6 prep
        steps and fills the progress bar to 1.0 — NOT stalling at 5/6 or
        5/9 (the red-team progress-denominator bug)."""
        status, data = self._premise_start("prepbook")
        self.assertEqual(status, 202, data)
        run_status, _ct, run_resp = routes.dispatch(
            "POST",
            "/api/workspace/prepbook/run",
            json.dumps({"step": "prepare-greenfield", "params": {"force": True}}).encode("utf-8"),
            {"content-type": "application/json"},
        )
        self.assertEqual(run_status, 202, run_resp.decode("utf-8"))
        job_id = json.loads(run_resp)["job_id"]
        rec = self._wait_for_done("prepbook", job_id)
        self.assertEqual(rec["status"], "succeeded", f"job error: {rec.get('error')}")
        # progress filled to 1.0 via emit_done — NOT stalled at 5/6, which
        # is the red-team progress-denominator bug this step guards against.
        # (current_step is overwritten by the terminal status on completion,
        # so progress is the durable signal to assert here.)
        self.assertEqual(rec.get("progress"), 1.0)
        # prep produced data artifacts (normalize/extract/compress/bootstrap)
        data_dir = paths.WORKSPACE_DIR / "prepbook" / "data"
        self.assertTrue(
            any(p.is_file() for p in data_dir.rglob("*")),
            "prepare-greenfield produced no data artifacts",
        )

    def test_prepare_steps_standalone_remaps_to_done(self) -> None:
        """_run_prepare_steps(total=6, emit_done=True): 6 steps map onto a
        self-contained 0→1.0 bar (apply-bootstrap at 5/6, then done 1.0)."""
        self.assertEqual(self._premise_start("standbook")[0], 202)
        seen: list[tuple[str, float]] = []
        with use_workspace("standbook"):
            results = auto_pipeline._run_prepare_steps(
                progress_cb=lambda s, f: seen.append((s, f)),
                total=6,
                emit_done=True,
                force=True,
            )
        labels = [s for s, _ in seen if s != "done"]
        self.assertEqual(
            labels,
            ["normalize", "split", "extract", "compress", "bootstrap", "apply-bootstrap"],
        )
        self.assertEqual(seen[0], ("normalize", 0.0))
        self.assertEqual(seen[5][0], "apply-bootstrap")
        self.assertAlmostEqual(seen[5][1], 5 / 6)
        self.assertEqual(seen[-1], ("done", 1.0))
        self.assertEqual(
            set(results),
            {"normalize", "split", "extract", "compress", "bootstrap", "apply-bootstrap"},
        )

    def test_prepare_steps_embedded_keeps_ninths_and_no_done(self) -> None:
        """_run_prepare_steps(total=9, emit_done=False): the same 6 steps
        render as index/9 and emit NO done sentinel — preserving
        run_auto_pipeline's 9-step contract (debate/plan/write follow)."""
        self.assertEqual(self._premise_start("embedbook")[0], 202)
        seen: list[tuple[str, float]] = []
        with use_workspace("embedbook"):
            auto_pipeline._run_prepare_steps(
                progress_cb=lambda s, f: seen.append((s, f)),
                total=9,
                emit_done=False,
                force=True,
            )
        self.assertEqual(seen[0], ("normalize", 0.0))
        self.assertEqual(seen[5][0], "apply-bootstrap")
        self.assertAlmostEqual(seen[5][1], 5 / 9)
        self.assertNotIn("done", [s for s, _ in seen])

    def test_run_auto_pipeline_9_step_contract_intact(self) -> None:
        """Regression guard mirroring test_auto_pipeline: after extracting
        _run_prepare_steps, the full pipeline must still emit all 9 step
        labels in order plus the ("done", 1.0) sentinel."""
        self.assertEqual(self._premise_start("fullbook")[0], 202)
        seen: list[tuple[str, float]] = []
        with use_workspace("fullbook"):
            auto_pipeline.run_auto_pipeline(
                target_chapters=1,
                extract_limit=2,
                force=True,
                progress_cb=lambda s, f: seen.append((s, f)),
            )
        self.assertEqual(seen[0], ("normalize", 0.0))
        self.assertEqual(seen[-1], ("done", 1.0))
        labels = [s for s, _ in seen if s != "done"]
        self.assertEqual(labels, list(auto_pipeline.STEPS))

    # ---- 全 task test-Key diagnostics matrix -----------------------------

    def test_diag_models_mock_short_circuits_offline(self) -> None:
        with patch("litellm.completion") as comp:
            status, _ct, resp = routes.dispatch("GET", "/api/diag/models")
        self.assertEqual(status, 200, resp.decode("utf-8"))
        data = json.loads(resp)
        self.assertTrue(data["is_mock"])
        self.assertTrue(data["all_ok"])
        # All 6 task families resolve to the single mock model → de-duped
        # to exactly one probe.
        self.assertEqual(len(data["models"]), 1)
        self.assertTrue(data["models"][0]["mock"])
        self.assertEqual(set(data["tasks"]), {"write", "review", "debate", "extract", "compress", "plot_planner"})
        comp.assert_not_called()

    def test_ping_mock_returns_ok_without_network(self) -> None:
        with patch("litellm.completion") as comp:
            res = LLMClient("write").ping()
        self.assertTrue(res["ok"])
        self.assertTrue(res["mock"])
        self.assertEqual(res["model"], "mock")
        comp.assert_not_called()

    def test_diag_collect_is_pure_callable(self) -> None:
        """diag.collect_model_diagnostics is importable + callable directly
        (no HTTP needed) and stays offline in mock mode."""
        with patch("litellm.completion") as comp:
            out = diag.collect_model_diagnostics()
        self.assertEqual(set(out), {"is_mock", "tasks", "models", "all_ok"})
        self.assertTrue(out["is_mock"])
        comp.assert_not_called()

    # ---- iter 048d C2(a): redact widened to Bearer / sk- patterns --------

    def test_ping_redacts_bearer_and_sk_key_from_litellm_error(self) -> None:
        """Prior to 048d, ping() only redacted exact-match plaintext of the
        configured ``api_key``. If the upstream litellm/openai error string
        echoed the credential in encoded form (``Authorization: Bearer
        <token>``) OR a bare ``sk-...`` from a different source, the raw
        credential would surface to the workbench client. 048d adds regex
        redaction for both shapes as defense in depth."""
        # Force a non-mock client by stubbing the resolved model. Inject
        # a fake api_key that is INTENTIONALLY different from the token
        # in the simulated error message — so the exact-match replace path
        # is NOT what redacts the leak; only the regex layers can do it.
        leaking_msg = (
            "AuthenticationError: Incorrect API key provided: "
            "Authorization: Bearer sk-leakedabcdef1234567890XYZ. "
            "Also stray sk-anotherbarekey9876543210abcdef in body."
        )

        client = LLMClient("write")
        # Replace the mock model so ping() takes the real network branch.
        client.model = "gpt-4o-mini"
        client.config = dict(client.config)
        client.config["model"] = "gpt-4o-mini"
        client.config["api_key"] = "totally-different-configured-key"

        with patch("litellm.completion", side_effect=Exception(leaking_msg)):
            res = client.ping()

        self.assertFalse(res["ok"])
        self.assertFalse(res["mock"])
        # The actual bearer token must NOT appear in the returned error.
        self.assertNotIn("sk-leakedabcdef1234567890XYZ", res["error"])
        self.assertNotIn("sk-anotherbarekey9876543210abcdef", res["error"])
        # And the redacted markers should be present so the user still
        # sees the redaction happened (rather than silent truncation).
        self.assertIn("Bearer ***", res["error"])
        self.assertIn("sk-***", res["error"])
        # Exception type stays visible so the user can tell 401 / 429 / etc.
        self.assertIn("AuthenticationError", res["error"])


if __name__ == "__main__":
    unittest.main()
