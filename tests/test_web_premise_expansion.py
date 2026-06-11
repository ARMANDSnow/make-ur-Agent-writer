"""iter 051a: web surface of the premise expansion —

* POST /api/wizard/premise-start ``expand`` opt-in (API default false keeps
  the 048a create-only contract; the wizard UI opts in via its checkbox);
* GET/PUT /api/workspace/<name>/premise-expansion (050 edit-loop contract:
  validation 400s, C3c control chars, busy 409 path shape);
* expand-premise job (blocked without seed, idempotent, force);
* workbench mtime chain: editing the expansion stales the KB and everything
  below it; missing expansion leaves the 050 chain byte-identical.

Mock-only.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from src import paths
from src.web import jobs, routes


class _WebHarness(unittest.TestCase):
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

    # ---- helpers -----------------------------------------------------------

    def _premise(self, ws: str, *, expand: object = None) -> dict:
        payload: dict = {"workspace": ws, "premise": "旧书店店主收到亡友预言谋杀的信。"}
        if expand is not None:
            payload["expand"] = expand
        status, _ct, resp = routes.dispatch(
            "POST",
            "/api/wizard/premise-start",
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            {"content-type": "application/json"},
        )
        body = json.loads(resp)
        self.assertEqual(status, 202, body)
        return body

    def _wait_for_done(self, ws: str, job_id: str, timeout: float = 30.0) -> dict:
        deadline = time.time() + timeout
        while time.time() < deadline:
            _, _, body = routes.dispatch("GET", f"/api/workspace/{ws}/job/{job_id}")
            rec = json.loads(body)
            if rec.get("status") in ("succeeded", "blocked", "failed", "aborted", "lost"):
                return rec
            time.sleep(0.05)
        self.fail("job did not finish")

    def _run_step(self, ws: str, step: str, params: dict | None = None) -> dict:
        status, _ct, resp = routes.dispatch(
            "POST",
            f"/api/workspace/{ws}/run",
            json.dumps({"step": step, "params": params or {}}).encode("utf-8"),
            {"content-type": "application/json"},
        )
        self.assertEqual(status, 202, resp.decode("utf-8"))
        return self._wait_for_done(ws, json.loads(resp)["job_id"])

    def _get_expansion(self, ws: str) -> tuple[int, dict]:
        status, _ct, body = routes.dispatch(
            "GET", f"/api/workspace/{ws}/premise-expansion"
        )
        return status, json.loads(body)

    def _put_expansion(self, ws: str, fields: object) -> tuple[int, dict]:
        status, _ct, body = routes.dispatch(
            "PUT",
            f"/api/workspace/{ws}/premise-expansion",
            json.dumps({"fields": fields}, ensure_ascii=False).encode("utf-8"),
            {"content-type": "application/json"},
        )
        return status, json.loads(body)

    def _workbench(self, ws: str) -> dict:
        _status, _ct, body = routes.dispatch("GET", f"/api/workspace/{ws}/workbench")
        return json.loads(body)

    def _artifact_path(self, ws: str) -> Path:
        return paths.WORKSPACE_DIR / ws / "data" / "premise_expansion.json"


class PremiseStartExpandTests(_WebHarness):
    def test_default_keeps_create_only_contract(self) -> None:
        body = self._premise("bare")
        self.assertIsNone(body["expansion_job_id"])
        self.assertFalse(self._artifact_path("bare").exists())

    def test_expand_false_starts_no_job(self) -> None:
        body = self._premise("noexp", expand=False)
        self.assertIsNone(body["expansion_job_id"])
        self.assertFalse(self._artifact_path("noexp").exists())

    def test_expand_true_runs_job_and_writes_artifact(self) -> None:
        body = self._premise("withexp", expand=True)
        self.assertTrue(body["expansion_job_id"])
        rec = self._wait_for_done("withexp", body["expansion_job_id"])
        self.assertEqual(rec["status"], "succeeded", rec.get("error"))
        self.assertTrue(self._artifact_path("withexp").exists())
        status, data = self._get_expansion("withexp")
        self.assertEqual(status, 200)
        self.assertEqual(data["generated_by"], "premise_expand_v1_mock")
        self.assertIn("mock 题材基调", data["fields"]["genre_tone"])
        # the original premise survives in the artifact (seed wrapper stripped)
        self.assertEqual(data["premise"], "旧书店店主收到亡友预言谋杀的信。")

    def test_expand_must_be_boolean(self) -> None:
        status, _ct, resp = routes.dispatch(
            "POST",
            "/api/wizard/premise-start",
            json.dumps({"workspace": "badexp", "premise": "x", "expand": "yes"}).encode("utf-8"),
            {"content-type": "application/json"},
        )
        self.assertEqual(status, 400, resp.decode("utf-8"))


class ExpandPremiseJobTests(_WebHarness):
    def test_blocked_without_seed(self) -> None:
        self._premise("noseed", expand=False)
        (paths.WORKSPACE_DIR / "noseed" / "小说txt" / "seed.txt").unlink()
        rec = self._run_step("noseed", "expand-premise")
        self.assertEqual(rec["status"], "blocked")
        self.assertIn("seed_missing", json.dumps(rec.get("result_summary") or rec))

    def test_rerun_without_force_preserves_user_edit(self) -> None:
        self._premise("keepedit", expand=False)
        self._run_step("keepedit", "expand-premise")
        status, _data = self._put_expansion("keepedit", {"genre_tone": "手工基调"})
        self.assertEqual(status, 200)
        self._run_step("keepedit", "expand-premise")
        _status, data = self._get_expansion("keepedit")
        self.assertEqual(data["fields"]["genre_tone"], "手工基调")

    def test_force_overwrites_user_edit(self) -> None:
        self._premise("forcewin", expand=False)
        self._run_step("forcewin", "expand-premise")
        self._put_expansion("forcewin", {"genre_tone": "手工基调"})
        self._run_step("forcewin", "expand-premise", {"force": True})
        _status, data = self._get_expansion("forcewin")
        self.assertIn("mock 题材基调", data["fields"]["genre_tone"])
        self.assertFalse(data["edited"])
        # iter 051c (review gap): force re-reads the premise from seed.txt —
        # the artifact's premise must reflect the seed, not a stale edit.
        self.assertEqual(data["premise"], "旧书店店主收到亡友预言谋杀的信。")


class ExpansionEndpointContractTests(_WebHarness):
    def test_get_404_before_artifact(self) -> None:
        self._premise("empty", expand=False)
        status, data = self._get_expansion("empty")
        self.assertEqual(status, 404, data)

    def test_put_creates_from_scratch_and_get_roundtrips(self) -> None:
        self._premise("scratch", expand=False)
        status, data = self._put_expansion(
            "scratch", {"genre_tone": "都市悬疑", "world_notes": ["要点一"]}
        )
        self.assertEqual(status, 200, data)
        self.assertTrue(data["saved"])
        status, data = self._get_expansion("scratch")
        self.assertEqual(status, 200)
        self.assertEqual(data["fields"]["world_notes"], ["要点一"])
        self.assertEqual(data["generated_by"], "manual")
        self.assertTrue(data["edited"])

    def test_put_validation_matrix(self) -> None:
        self._premise("valid", expand=False)
        cases = [
            ("not a dict", "fields-not-dict"),
            ({}, "fields-empty"),
            ({"nope": "x"}, "unknown-field"),
            ({"genre_tone": "带控制字符\x07"}, "control-chars"),
            ({"genre_tone": "x" * 301}, "schema-too-long"),
            ({"world_notes": ["x" * 501]}, "list-item-too-long"),
            ({"world_notes": "应是列表"}, "wrong-type"),
        ]
        for fields, label in cases:
            status, data = self._put_expansion("valid", fields)
            self.assertEqual(status, 400, f"{label}: {data}")
        # oversize raw payload (M-4 outer gate)
        status, _ct, body = routes.dispatch(
            "PUT",
            "/api/workspace/valid/premise-expansion",
            json.dumps({"fields": {"protagonist": "y" * 1999, "junk_pad": "x" * 120_000}}).encode("utf-8"),
            {"content-type": "application/json"},
        )
        self.assertEqual(status, 400, body.decode("utf-8")[:200])

    def test_workspace_not_found(self) -> None:
        status, _data = self._get_expansion("ghost")
        self.assertEqual(status, 404)


class WorkbenchStalenessTests(_WebHarness):
    def test_missing_expansion_leaves_chain_unchanged(self) -> None:
        self._premise("plainws", expand=False)
        self._run_step("plainws", "prepare-greenfield", {"force": True})
        st = self._workbench("plainws")
        self.assertTrue(st["has_kb"])
        self.assertFalse(st["has_expansion"])
        self.assertFalse(st["expansion_stale"])
        self.assertEqual(st["stage"], "outline")

    def test_expansion_edit_stales_kb_and_rerun_clears(self) -> None:
        self._premise("stalews", expand=True)
        # wait out the auto expansion job before driving prepare
        jid = json.loads(
            routes.dispatch("GET", "/api/workspace/stalews/jobs/recent?n=1")[2]
        )["jobs"][0]["job_id"]
        self._wait_for_done("stalews", jid)
        self._run_step("stalews", "prepare-greenfield", {"force": True})
        st = self._workbench("stalews")
        self.assertTrue(st["has_kb"])
        self.assertTrue(st["has_expansion"])
        self.assertFalse(st["expansion_stale"])
        # KB consumed the expansion (mock section pinned in module tests)
        kb_text = (
            paths.WORKSPACE_DIR / "stalews" / "data" / "knowledge_base" / "global_knowledge.md"
        ).read_text(encoding="utf-8")
        self.assertIn("premise 扩写稿", kb_text)

        # edit the expansion → KB (and the whole chain below) goes stale
        time.sleep(0.01)  # mtime granularity guard
        status, _data = self._put_expansion("stalews", {"genre_tone": "改过的基调"})
        self.assertEqual(status, 200)
        st = self._workbench("stalews")
        self.assertFalse(st["has_kb"])
        self.assertTrue(st["expansion_stale"])
        self.assertEqual(st["stage"], "prepare")

        # re-running stage ① clears the staleness
        self._run_step("stalews", "prepare-greenfield", {"force": True})
        st = self._workbench("stalews")
        self.assertTrue(st["has_kb"])
        self.assertFalse(st["expansion_stale"])


if __name__ == "__main__":
    unittest.main()
