"""iter058 #6b: NaN / ±Infinity must not slip through float param validation.

Before this fix, ``_float_param`` (routes) and ``_optional_float`` (wizard)
only compared ``out < minimum`` / ``out > maximum``. IEEE-754 makes every
comparison with NaN False, so ``budget_cny=NaN``/``Infinity`` and
``min_confidence=NaN`` / ``timeout_minutes=NaN`` all passed validation and
returned 202 — then disabled the downstream cost gate (``nan > 0`` is False)
and the timeout deadline (``monotonic() > nan`` is always False → never times
out). The fix adds a ``math.isfinite`` guard at both boundaries (and a
defense-in-depth fallback in jobs.py's internal ``_float_param``).

Mock-only; no network, no real workspace data.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from typing import Optional

from src import paths
from src.web import jobs, routes, wizard


def _build_multipart(
    workspace: str,
    filename: str,
    content: bytes,
    mime: str,
    extra_fields: Optional[dict] = None,
) -> tuple:
    boundary = "----FINITEGUARDBOUND"
    chunks = [
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"workspace\"\r\n\r\n{workspace}\r\n".encode("utf-8")
    ]
    for key, value in (extra_fields or {}).items():
        chunks.append(
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n".encode("utf-8")
        )
    chunks.append(
        (
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"upload\"; filename=\"{filename}\"\r\n"
            f"Content-Type: {mime}\r\n\r\n"
        ).encode("utf-8") + content + f"\r\n--{boundary}--\r\n".encode("utf-8")
    )
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _stub_workspace(root: Path, name: str) -> None:
    ws = root / name
    for sub in ("小说txt", "data", "outputs", "logs"):
        (ws / sub).mkdir(parents=True)
    (ws / "marker.txt").write_text("hi", encoding="utf-8")


class FloatParamUnitTests(unittest.TestCase):
    """Direct coverage of the two validators + the jobs.py fallback."""

    def test_routes_float_param_rejects_non_finite(self) -> None:
        for bad in ("nan", "inf", "-inf", "Infinity"):
            err, _val = routes._float_param({"budget_cny": bad}, "budget_cny", 0.0, minimum=0.0)
            self.assertIsNotNone(err, bad)
            self.assertIn("budget_cny", err)
            self.assertIn("finite", err)

    def test_routes_float_param_native_float_nan_rejected(self) -> None:
        # JSON bodies can carry a bare NaN literal that json.loads turns into
        # float('nan') — cover that wire shape too, not just the string form.
        err, _val = routes._float_param({"budget_cny": float("nan")}, "budget_cny", 0.0)
        self.assertIsNotNone(err)
        err, _val = routes._float_param({"budget_cny": float("inf")}, "budget_cny", 0.0)
        self.assertIsNotNone(err)

    def test_routes_float_param_finite_still_passes(self) -> None:
        err, val = routes._float_param({"budget_cny": "3.5"}, "budget_cny", 0.0, minimum=0.0)
        self.assertIsNone(err)
        self.assertEqual(val, 3.5)
        # Missing key falls back to the (finite) default, unchanged behavior.
        err, val = routes._float_param({}, "budget_cny", 0.0)
        self.assertIsNone(err)
        self.assertEqual(val, 0.0)

    def test_optional_float_rejects_non_finite(self) -> None:
        for bad in (float("nan"), float("inf"), "nan", "inf"):
            err, _val = wizard._optional_float(bad, "timeout_minutes", default=0.0, minimum=0.0)
            self.assertIsNotNone(err, bad)
            self.assertIn("timeout_minutes", err)
            self.assertIn("finite", err)

    def test_optional_float_finite_and_blank_pass(self) -> None:
        err, val = wizard._optional_float("12", "timeout_minutes", default=0.0, minimum=0.0)
        self.assertIsNone(err)
        self.assertEqual(val, 12.0)
        for blank in (None, ""):
            err, val = wizard._optional_float(blank, "timeout_minutes", default=0.0, minimum=0.0)
            self.assertIsNone(err)
            self.assertEqual(val, 0.0)

    def test_validate_write_book_params_rejects_non_finite(self) -> None:
        err, _out = routes._validate_write_book_params({"budget_cny": "nan"})
        self.assertIsNotNone(err)
        self.assertIn("budget_cny", err)
        err, _out = routes._validate_write_book_params({"min_confidence": "nan"})
        self.assertIsNotNone(err)
        self.assertIn("min_confidence", err)

    def test_validate_write_book_params_finite_passes(self) -> None:
        err, out = routes._validate_write_book_params({"budget_cny": "3.5", "min_confidence": "0.8"})
        self.assertIsNone(err)
        self.assertEqual(out["budget_cny"], 3.5)
        self.assertEqual(out["min_confidence"], 0.8)

    def test_jobs_float_param_defense_in_depth_falls_back(self) -> None:
        # Non-finite that somehow reaches the job layer falls back to the
        # finite default rather than disabling the budget math.
        self.assertEqual(jobs._float_param({"budget_cny": float("nan")}, "budget_cny", 10.0), 10.0)
        self.assertEqual(jobs._float_param({"budget_cny": "inf"}, "budget_cny", 10.0), 10.0)
        # Finite path unchanged.
        self.assertEqual(jobs._float_param({"budget_cny": "3.5"}, "budget_cny", 10.0), 3.5)

    def test_jobs_timeout_deadline_rejects_non_finite(self) -> None:
        # iter060 (Codex B): a NaN/inf timeout used to survive `<= 0` (IEEE-754)
        # and yield a non-None deadline that _check_cancelled could never trip.
        # Now it degrades to "no timeout".
        self.assertEqual(jobs._timeout_deadline({"timeout_minutes": float("nan")}), (None, None))
        self.assertEqual(jobs._timeout_deadline({"timeout_minutes": float("inf")}), (None, None))
        # Absent / zero still mean "no timeout" (unchanged).
        self.assertEqual(jobs._timeout_deadline({}), (None, None))
        self.assertEqual(jobs._timeout_deadline({"timeout_minutes": 0}), (None, None))
        # A finite positive value still produces a live deadline.
        deadline, minutes = jobs._timeout_deadline({"timeout_minutes": 5})
        self.assertIsNotNone(deadline)
        self.assertEqual(minutes, 5.0)

    def test_validated_run_params_rejects_non_finite_timeout_on_any_step(self) -> None:
        # The gap Codex found: only write-book/plan-chapters validated params, so
        # a NaN/inf/negative timeout on a plain step (e.g. normalize) passed
        # through to a 202 with a useless deadline. Now rejected at the boundary.
        for bad in (float("nan"), float("inf"), "nan", "inf", -3):
            err, _out = routes._validated_run_params("normalize", {"timeout_minutes": bad})
            self.assertIsNotNone(err, bad)
            self.assertIn("timeout_minutes", err)
        # A finite timeout passes straight through (preserved for the job).
        err, out = routes._validated_run_params("normalize", {"timeout_minutes": 30})
        self.assertIsNone(err)
        self.assertEqual(out.get("timeout_minutes"), 30)
        # No timeout key → unchanged passthrough.
        err, _out = routes._validated_run_params("normalize", {})
        self.assertIsNone(err)

    def test_validate_write_book_params_carries_timeout(self) -> None:
        # iter063 A5 (= 后端审查②): the rebuilt write-book params used to DROP a
        # validated timeout_minutes, so jobs._timeout_deadline never armed.
        err, out = routes._validate_write_book_params({"timeout_minutes": "30"})
        self.assertIsNone(err)
        self.assertEqual(out.get("timeout_minutes"), 30.0)
        # 0 / absent means "no cap" — key omitted (matches _timeout_deadline).
        err, out = routes._validate_write_book_params({"timeout_minutes": "0"})
        self.assertIsNone(err)
        self.assertNotIn("timeout_minutes", out)
        err, out = routes._validate_write_book_params({})
        self.assertIsNone(err)
        self.assertNotIn("timeout_minutes", out)

    def test_validate_plan_chapters_params_carries_timeout(self) -> None:
        # iter063 A5: plan-chapters is the other long step whose rebuilt params
        # dropped the timeout.
        err, out = routes._validate_plan_chapters_params({"target_chapters": 5, "timeout_minutes": "12"})
        self.assertIsNone(err)
        self.assertEqual(out.get("timeout_minutes"), 12.0)
        err, out = routes._validate_plan_chapters_params({"target_chapters": 5})
        self.assertIsNone(err)
        self.assertNotIn("timeout_minutes", out)

    def test_timeout_minutes_over_maximum_rejected(self) -> None:
        # iter063 ③: an unbounded finite timeout (e.g. 1e9 minutes) is a fake
        # deadline that never fires. Cap at 1440min (24h) like the wizard, on
        # the boundary and in both long-step validators.
        for step in ("normalize", "write-book", "plan-chapters"):
            err, _out = routes._validated_run_params(step, {"timeout_minutes": 1e9})
            self.assertIsNotNone(err, step)
            self.assertIn("timeout_minutes", err)
        # Exactly the cap is allowed.
        err, out = routes._validate_write_book_params({"timeout_minutes": "1440"})
        self.assertIsNone(err)
        self.assertEqual(out.get("timeout_minutes"), 1440.0)


class _IsolatedWorkspaceCase(unittest.TestCase):
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


class RunEndpointFiniteGuardTests(_IsolatedWorkspaceCase):
    """End-to-end via routes.dispatch — the exact path the audit found at 202."""

    def setUp(self) -> None:
        super().setUp()
        _stub_workspace(paths.WORKSPACE_DIR, "alpha")

    def _run(self, step: str, params: dict) -> tuple:
        # api_run_step reads params from the nested "params" object.
        body = json.dumps({"step": step, "params": params}).encode()
        return routes.dispatch("POST", "/api/workspace/alpha/run", body)

    def test_budget_cny_nan_rejected_with_400(self) -> None:
        status, _ct, body = self._run("write-book", {"budget_cny": "nan"})
        self.assertEqual(status, 400, body.decode("utf-8"))
        self.assertIn("budget_cny", json.loads(body)["error"])

    def test_budget_cny_infinity_rejected_with_400(self) -> None:
        status, _ct, body = self._run("write-book", {"budget_cny": "inf"})
        self.assertEqual(status, 400, body.decode("utf-8"))
        self.assertIn("budget_cny", json.loads(body)["error"])

    def test_min_confidence_nan_rejected_with_400(self) -> None:
        status, _ct, body = self._run("write-book", {"min_confidence": "nan"})
        self.assertEqual(status, 400, body.decode("utf-8"))
        self.assertIn("min_confidence", json.loads(body)["error"])

    def test_timeout_minutes_nan_on_plain_step_returns_400(self) -> None:
        # iter060 (Codex B): the exact slip — a NaN timeout on a non
        # write-book/plan-chapters step used to reach 202 running; now 400.
        status, _ct, body = self._run("normalize", {"timeout_minutes": "nan"})
        self.assertEqual(status, 400, body.decode("utf-8"))
        self.assertIn("timeout_minutes", json.loads(body)["error"])


class WizardFiniteGuardTests(_IsolatedWorkspaceCase):
    """End-to-end via /api/wizard/start — timeout_minutes / budget_cny fields."""

    def _start(self, extra_fields: dict) -> tuple:
        body, ct = _build_multipart(
            "ws6b",
            "novel.txt",
            ("第一章\n测试。\n" * 30).encode("utf-8"),
            "text/plain",
            extra_fields=extra_fields,
        )
        return routes.dispatch("POST", "/api/wizard/start", body, {"content-type": ct})

    def test_timeout_minutes_nan_rejected(self) -> None:
        status, _ct, resp = self._start({"timeout_minutes": "nan"})
        self.assertEqual(status, 400, resp.decode("utf-8"))
        self.assertIn("timeout_minutes", json.loads(resp)["error"])

    def test_timeout_minutes_infinity_rejected(self) -> None:
        status, _ct, resp = self._start({"timeout_minutes": "inf"})
        self.assertEqual(status, 400, resp.decode("utf-8"))
        self.assertIn("timeout_minutes", json.loads(resp)["error"])

    def test_budget_cny_nan_rejected(self) -> None:
        status, _ct, resp = self._start({"budget_cny": "nan"})
        self.assertEqual(status, 400, resp.decode("utf-8"))
        self.assertIn("budget_cny", json.loads(resp)["error"])


if __name__ == "__main__":
    unittest.main()
