"""iter059 #6a/NEW-A: integer params must reject non-finite / out-of-range
values with a clean 400, never an unbounded accept or an HTTP 500.

Before this fix, ``_int_value`` (routes) only caught ``(TypeError, ValueError)``
and ``_validate_write_book_params`` set no upper bound:
  - ``chapters=Infinity`` -> json.loads gives float('inf') ->
    ``int(float('inf'))`` raises OverflowError -> uncaught -> HTTP 500.
  - ``chapters=999999999`` -> accepted (202), no ceiling.
``chapters=NaN`` already 400'd (int(nan) -> ValueError) but is now rejected
explicitly for a clearer message. The fix adds a ``math.isfinite`` pre-check
plus ``OverflowError`` to the except, and finite upper bounds on
chapters / resume_from / max_retries / replan_every. Sibling of
test_float_finite_guard.py (iter058 #6b).

Mock-only; no network, no real workspace data.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from src import paths
from src.web import jobs, routes


class IntValueUnitTests(unittest.TestCase):
    """Direct coverage of routes._int_value."""

    def test_native_float_infinity_rejected(self) -> None:
        # The OverflowError-trigger wire shape: json.loads('... Infinity') gives
        # a native float('inf'), which used to crash int() with OverflowError.
        err, _val = routes._int_value(float("inf"), "chapters")
        self.assertIsNotNone(err)
        self.assertIn("chapters", err)
        self.assertIn("finite", err)

    def test_native_float_nan_rejected(self) -> None:
        err, _val = routes._int_value(float("nan"), "chapters")
        self.assertIsNotNone(err)
        self.assertIn("chapters", err)

    def test_string_infinity_rejected(self) -> None:
        # int("Infinity") raises ValueError -> "must be an integer".
        for bad in ("inf", "Infinity", "nan"):
            err, _val = routes._int_value(bad, "chapters")
            self.assertIsNotNone(err, bad)
            self.assertIn("chapters", err)

    def test_over_maximum_rejected(self) -> None:
        err, _val = routes._int_value(999999999, "chapters", minimum=1, maximum=2000)
        self.assertIsNotNone(err)
        self.assertIn("<= 2000", err)

    def test_below_minimum_rejected(self) -> None:
        err, _val = routes._int_value(0, "chapters", minimum=1, maximum=2000)
        self.assertIsNotNone(err)
        self.assertIn(">= 1", err)

    def test_finite_in_range_passes(self) -> None:
        err, val = routes._int_value(5, "chapters", minimum=1, maximum=2000)
        self.assertIsNone(err)
        self.assertEqual(val, 5)
        # String integers still coerce, unchanged behavior.
        err, val = routes._int_value("7", "chapters", minimum=1, maximum=2000)
        self.assertIsNone(err)
        self.assertEqual(val, 7)


class ValidateWriteBookParamsBoundsTests(unittest.TestCase):
    """The four write-book integer params gained finite upper bounds."""

    def test_chapters_over_cap_rejected(self) -> None:
        err, _out = routes._validate_write_book_params({"chapters": 999999999})
        self.assertIsNotNone(err)
        self.assertIn("chapters", err)

    def test_resume_from_over_cap_rejected(self) -> None:
        err, _out = routes._validate_write_book_params({"resume_from": 10001})
        self.assertIsNotNone(err)
        self.assertIn("resume_from", err)

    def test_max_retries_over_cap_rejected(self) -> None:
        err, _out = routes._validate_write_book_params({"max_retries": 21})
        self.assertIsNotNone(err)
        self.assertIn("max_retries", err)

    def test_default_and_in_range_pass(self) -> None:
        # Defaults (no params) and a normal run both validate cleanly.
        err, out = routes._validate_write_book_params({})
        self.assertIsNone(err)
        self.assertEqual(out["chapters"], 1)
        err, out = routes._validate_write_book_params({"chapters": 30, "resume_from": 5})
        self.assertIsNone(err)
        self.assertEqual(out["chapters"], 30)
        self.assertEqual(out["resume_from"], 5)


def _stub_workspace(root: Path, name: str) -> None:
    ws = root / name
    for sub in ("小说txt", "data", "outputs", "logs"):
        (ws / sub).mkdir(parents=True)


class RunEndpointIntGuardTests(unittest.TestCase):
    """End-to-end via routes.dispatch — the 500 the audit found becomes 400.

    The validation runs in api_run_step before start_job, so a rejected param
    returns 400 synchronously without ever spawning a worker thread."""

    def setUp(self) -> None:
        os.environ["OPENAI_MODEL"] = "mock"
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._saved_ws_dir = paths.WORKSPACE_DIR
        self._saved_env = os.environ.get("WORKSPACE_NAME")
        os.environ.pop("WORKSPACE_NAME", None)
        paths.WORKSPACE_DIR = Path(self._tmp.name)
        _stub_workspace(paths.WORKSPACE_DIR, "alpha")
        jobs.reset_for_tests()
        self.addCleanup(jobs.reset_for_tests)
        self.addCleanup(self._restore_env)

    def _restore_env(self) -> None:
        paths.WORKSPACE_DIR = self._saved_ws_dir
        if self._saved_env is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._saved_env

    def _run(self, params: dict) -> tuple:
        body = json.dumps({"step": "write-book", "params": params}).encode()
        return routes.dispatch("POST", "/api/workspace/alpha/run", body)

    def test_chapters_infinity_returns_400_not_500(self) -> None:
        # json.dumps(float('inf')) emits the bare `Infinity` literal that
        # json.loads parses back to float('inf') — the exact 500 path.
        status, _ct, resp = self._run({"chapters": float("inf")})
        self.assertEqual(status, 400, resp.decode("utf-8"))
        self.assertIn("chapters", json.loads(resp)["error"])

    def test_chapters_over_cap_returns_400(self) -> None:
        status, _ct, resp = self._run({"chapters": 999999999})
        self.assertEqual(status, 400, resp.decode("utf-8"))
        self.assertIn("chapters", json.loads(resp)["error"])

    def test_chapters_finite_accepted_202(self) -> None:
        # A normal value still validates and starts a job (drain it so the
        # tmp workspace teardown is clean).
        status, _ct, resp = self._run({"chapters": 5})
        self.assertEqual(status, 202, resp.decode("utf-8"))
        job_id = json.loads(resp)["job_id"]
        import time

        deadline = time.time() + 10.0
        while time.time() < deadline:
            _s, _c, b = routes.dispatch("GET", f"/api/workspace/alpha/job/{job_id}")
            if json.loads(b).get("status") in (
                "succeeded", "blocked", "failed", "aborted", "lost", "budget_exceeded",
            ):
                break
            time.sleep(0.05)


class ReadinessClampTests(unittest.TestCase):
    """iter060 (Codex A): GET /readiness clamps chapters/resume_from/replan_every
    to the write-book caps. The GET query parser (_parse_int) is a bare int()
    with no ceiling, so chapters=999999999 used to reach check_write_readiness ->
    list(range(...)) and try to materialise ~1e9 ints. The clamp lives in the
    handler (like api_workspace_logs_tail) since this is a read-only preview that
    should mirror what write-book would actually accept."""

    def setUp(self) -> None:
        os.environ["OPENAI_MODEL"] = "mock"
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._saved_ws_dir = paths.WORKSPACE_DIR
        self._saved_env = os.environ.get("WORKSPACE_NAME")
        os.environ.pop("WORKSPACE_NAME", None)
        paths.WORKSPACE_DIR = Path(self._tmp.name)
        _stub_workspace(paths.WORKSPACE_DIR, "alpha")
        self.addCleanup(self._restore_env)

    def _restore_env(self) -> None:
        paths.WORKSPACE_DIR = self._saved_ws_dir
        if self._saved_env is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._saved_env

    def test_huge_params_clamped_not_materialised(self) -> None:
        # Pre-fix this hangs/OOMs on list(range(1, 1_000_000_000)). Post-fix the
        # clamp bounds chapters/plan_window to 2000 and resume_from to 10000, so
        # it returns 200 immediately.
        status, _ct, resp = routes.dispatch(
            "GET",
            "/api/workspace/alpha/readiness?chapters=999999999&resume_from=888888&replan_every=777777",
        )
        self.assertEqual(status, 200, resp.decode("utf-8"))
        data = json.loads(resp)
        self.assertLessEqual(data["chapters"], 2000)
        self.assertLessEqual(data["plan_window"], 2000)
        self.assertLessEqual(data["resume_from"], 10000)
        # iter063 ⑤: clamping is reported (requested vs applied), not silent.
        self.assertIn("clamped", data)
        self.assertEqual(data["clamped"]["chapters"]["requested"], 999999999)
        self.assertEqual(data["clamped"]["chapters"]["applied"], data["chapters"])
        self.assertEqual(data["clamped"]["resume_from"]["requested"], 888888)

    def test_normal_values_not_over_clamped(self) -> None:
        status, _ct, resp = routes.dispatch(
            "GET",
            "/api/workspace/alpha/readiness?chapters=30&resume_from=5&replan_every=10",
        )
        self.assertEqual(status, 200, resp.decode("utf-8"))
        data = json.loads(resp)
        self.assertEqual(data["chapters"], 30)
        self.assertEqual(data["resume_from"], 5)
        self.assertLessEqual(data["plan_window"], 30)
        # iter063 ⑤: no clamp happened → no clamped field.
        self.assertNotIn("clamped", data)


if __name__ == "__main__":
    unittest.main()
