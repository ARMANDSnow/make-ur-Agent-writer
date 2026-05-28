"""iter 025: WebUI route dispatcher (pure functions, no HTTP server)."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from src import paths
from src.web import routes


def _stub_workspace(root: Path, name: str) -> Path:
    """Create a minimal workspace tree under ``root`` so route handlers
    return realistic JSON instead of 404."""

    ws = root / name
    (ws / "data").mkdir(parents=True)
    (ws / "outputs" / "debate").mkdir(parents=True)
    (ws / "outputs" / "drafts").mkdir(parents=True)
    (ws / "logs").mkdir(parents=True)
    (ws / "小说txt").mkdir(parents=True)
    # chapter_manifest is enough to make collect_status report "split done"
    (ws / "data" / "chapter_manifest.json").write_text(
        json.dumps([{"chapter_id": f"{name}_ch001", "title": "t", "char_count": 100}], ensure_ascii=False),
        encoding="utf-8",
    )
    meta = {
        "target": "outputs/drafts/chapter_01.md",
        "verdict": "Approve",
        "rewrite_count": 0,
        "rewrite_round": 0,
        "chinese_char_count": 4000,
        "needs_human_review": False,
        "polish_applied": False,
        "lint_issues": [],
        "agent_reviews": [
            {"agent_name": "PlotMaster", "verdict": "Approve", "score": 7, "issues": [], "suggestions": [], "comparison_checklist": []}
        ],
        "rewrite_suggestions": [{"section": "intro", "type": "rewrite", "guidance": "..."}],
    }
    (ws / "outputs" / "drafts" / "chapter_01.meta.json").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8"
    )
    (ws / "logs" / "llm_calls.jsonl").write_text(
        '{"task":"review","model":"mock","prompt_tokens":10,"response_tokens":5}\n',
        encoding="utf-8",
    )
    return ws


class RoutesGetTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._saved_ws_dir = paths.WORKSPACE_DIR
        self._saved_env = os.environ.get("WORKSPACE_NAME")
        os.environ.pop("WORKSPACE_NAME", None)
        root = Path(self._tmp.name)
        paths.WORKSPACE_DIR = root
        _stub_workspace(root, "alpha")
        _stub_workspace(root, "beta")

    def tearDown(self) -> None:
        paths.WORKSPACE_DIR = self._saved_ws_dir
        if self._saved_env is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._saved_env
        self._tmp.cleanup()

    def _get_json(self, path: str) -> tuple[int, dict]:
        status, ct, body = routes.dispatch("GET", path)
        self.assertIn("json", ct)
        return status, json.loads(body.decode("utf-8"))

    def test_index_lists_workspaces(self) -> None:
        status, _ct, body = routes.dispatch("GET", "/")
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        self.assertIn("alpha", html)
        self.assertIn("beta", html)

    def test_workspace_page_renders(self) -> None:
        status, _ct, body = routes.dispatch("GET", "/workspace/alpha/")
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        self.assertIn("alpha", html)
        self.assertIn('data-source="reviews"', html)

    def test_workspace_page_404(self) -> None:
        status, _ct, _body = routes.dispatch("GET", "/workspace/__missing__/")
        self.assertEqual(status, 404)

    def test_api_workspaces(self) -> None:
        status, data = self._get_json("/api/workspaces")
        self.assertEqual(status, 200)
        self.assertEqual(sorted(data["workspaces"]), ["alpha", "beta"])

    def test_api_status_404_for_unknown(self) -> None:
        status, data = self._get_json("/api/workspace/nope/status")
        self.assertEqual(status, 404)
        self.assertIn("not found", data["error"])

    def test_api_manifest_returns_chapters(self) -> None:
        status, data = self._get_json("/api/workspace/alpha/manifest")
        self.assertEqual(status, 200)
        self.assertEqual(data["chapters"][0]["chapter_id"], "alpha_ch001")

    def test_api_reviews_full_shape(self) -> None:
        status, data = self._get_json("/api/workspace/alpha/reviews")
        self.assertEqual(status, 200)
        self.assertEqual(data["stats"]["total"], 1)
        self.assertEqual(data["stats"]["accepted"], 1)
        self.assertEqual(data["stats"]["advisor_suggestions_total"], 1)
        # full agent_reviews preserved
        self.assertEqual(data["chapters"][0]["agent_reviews"][0]["agent_name"], "PlotMaster")

    def test_api_logs_tail(self) -> None:
        status, data = self._get_json("/api/workspace/alpha/logs/tail?n=10")
        self.assertEqual(status, 200)
        self.assertEqual(len(data["lines"]), 1)
        self.assertEqual(data["lines"][0]["task"], "review")

    def test_api_cost_runs(self) -> None:
        status, data = self._get_json("/api/workspace/alpha/cost")
        self.assertEqual(status, 200)
        self.assertIn("chapters", data)

    def test_invalid_workspace_name_400(self) -> None:
        status, data = self._get_json("/api/workspace/..%2Fescape/status")
        # urlsplit hands ``..%2Fescape`` straight through; our regex rejects /
        # because of [^/]+; the % escape stays literal and fails the name re.
        self.assertIn(status, (400, 404))
        self.assertIn("error", data)

    def test_unknown_api_path_404_json(self) -> None:
        status, ct, body = routes.dispatch("GET", "/api/nothing")
        self.assertEqual(status, 404)
        self.assertIn("json", ct)
        self.assertIn("error", json.loads(body))

    def test_unknown_html_path_404(self) -> None:
        status, ct, _body = routes.dispatch("GET", "/no-such-thing")
        self.assertEqual(status, 404)
        self.assertIn("html", ct)

    def test_static_css_served(self) -> None:
        status, ct, body = routes.dispatch("GET", "/static/app.css")
        self.assertEqual(status, 200)
        self.assertIn("text/css", ct)
        self.assertIn(b"body", body)

    def test_static_js_served(self) -> None:
        status, ct, body = routes.dispatch("GET", "/static/app.js")
        self.assertEqual(status, 200)
        self.assertIn("javascript", ct)
        self.assertIn(b"fetch", body)

    def test_cjk_workspace_url_decoded(self) -> None:
        """Iter 025 code-review #8: percent-encoded CJK in path must
        match the on-disk workspace name after URL-decoding."""
        _stub_workspace(Path(self._tmp.name), "龙族")
        # urllib's quote of '龙族' = %E9%BE%99%E6%97%8F
        status, ct, body = routes.dispatch(
            "GET", "/api/workspace/%E9%BE%99%E6%97%8F/manifest"
        )
        self.assertEqual(status, 200, body.decode("utf-8"))
        self.assertIn("json", ct)

    def test_legacy_workspace_rejected(self) -> None:
        """Iter 025 code-review #5: 'legacy' is a paths sentinel that
        silently falls back to repo root; reject it at the API edge."""
        status, data = self._get_json("/api/workspace/legacy/status")
        self.assertEqual(status, 400)
        self.assertIn("error", data)

    def test_leading_or_trailing_hyphen_rejected(self) -> None:
        """Iter 025 code-review #9: '-foo' / 'foo-' collide with argparse
        and shell-flag parsing in iter 026 wizard / settings paths."""
        for bad in ("-foo", "foo-", "-", "--"):
            status, _data = self._get_json(f"/api/workspace/{bad}/status")
            self.assertEqual(status, 400, f"name {bad!r} should be rejected")


if __name__ == "__main__":
    unittest.main()
