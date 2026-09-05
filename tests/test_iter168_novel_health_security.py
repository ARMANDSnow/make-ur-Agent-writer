"""Iteration 168 regressions for novel mutation, freshness and safe I/O."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import PropertyMock, patch

from pydantic import BaseModel

from src import paths
from src.llm_client import (
    LLMBudgetLimitExceeded,
    LLMAccountingUnavailable,
    LLMClient,
    LLMProviderFailure,
    LLMResponseValidationError,
    _sanitize_error_text,
    llm_model_config_scope,
    llm_budget_limit_scope,
    llm_accounting_degraded,
    public_llm_failure_reason,
)
from src.plot_planner import chapter_plan_item_fingerprint, plan_fingerprint
from src.preflight import run_preflight
from src.safe_errors import exception_projection, safe_exception_text, safe_url
from src.safe_jsonl import tail_jsonl
from src.utils import sha256_text, write_json
from src.web import routes, templates, workspace_meta
from src.web.workspace_ctx import use_workspace


class MutationPolicyTests(unittest.TestCase):
    def test_every_registered_mutation_has_exactly_one_policy(self) -> None:
        registered = {
            (method, pattern.pattern)
            for method, pattern, _handler in routes._ROUTES
            if method in {"POST", "PUT"}
        }
        self.assertEqual(registered, set(routes._MUTATION_POLICIES))

    def test_unregistered_mutation_route_fails_closed_before_handler(self) -> None:
        called = 0

        def handler(**_kwargs):
            nonlocal called
            called += 1
            return 200, "application/json", b"{}"

        route = ("POST", routes.re.compile(r"^/api/iter168/unregistered$"), handler)
        routes._ROUTES.append(route)
        try:
            status, _ct, _body = routes.dispatch(
                "POST",
                "/api/iter168/unregistered",
                b"{}",
                {
                    "Content-Type": "application/json",
                    "Content-Length": "2",
                    "Host": "127.0.0.1:8765",
                },
            )
        finally:
            routes._ROUTES.remove(route)
        self.assertEqual(status, 500)
        self.assertEqual(called, 0)

    def _wire_headers(
        self,
        *,
        content_type: str,
        intent_header: str,
        intent_value: str,
        cross_site: bool = True,
    ) -> dict[str, str]:
        headers = {
            "Content-Type": content_type,
            "Content-Length": "2",
            "Host": "127.0.0.1:8765",
            intent_header: intent_value,
        }
        if cross_site:
            headers.update(
                {
                    "Origin": "https://evil.example",
                    "Sec-Fetch-Site": "cross-site",
                }
            )
        return headers

    def test_cross_site_mutation_families_never_reach_handlers(self) -> None:
        cases = (
            (
                "/api/workspace/alpha/delete",
                "application/json",
                "X-Workspace-Mutation-Intent",
                "mutate-v1",
                "src.web.routes.api_workspace_delete",
            ),
            (
                "/api/workspace/alpha/run",
                "application/json",
                "X-Model-Action-Intent",
                "run-v1",
                "src.web.routes.api_run_step",
            ),
            (
                "/api/workspace/alpha/writer-style/extract",
                "multipart/form-data; boundary=x",
                "X-Model-Action-Intent",
                "extract-style-v1",
                "src.web.routes.api_workspace_writer_style_extract",
            ),
            (
                "/api/wizard/start",
                "multipart/form-data; boundary=x",
                "X-Onboarding-Intent",
                "import-v1",
                "src.web.routes.api_wizard_start",
            ),
            (
                "/api/wizard/premise-start",
                "application/json",
                "X-Onboarding-Intent",
                "premise-v1",
                "src.web.routes.api_wizard_premise_start",
            ),
            (
                "/api/settings",
                "application/json",
                "X-Settings-Mutation-Intent",
                "update-v1",
                "src.web.routes.api_settings_put",
            ),
            (
                "/api/workspace/alpha/write-recovery",
                "application/json",
                "X-Write-Recovery-Intent",
                "archive-and-regenerate-v1",
                "src.web.routes.api_workspace_write_recovery_post",
            ),
        )
        for path, content_type, header, value, target in cases:
            with self.subTest(path=path), patch(target) as handler:
                status, _ct, _body = routes.dispatch(
                    "PUT" if path == "/api/settings" else "POST",
                    path,
                    b"{}",
                    self._wire_headers(
                        content_type=content_type,
                        intent_header=header,
                        intent_value=value,
                    ),
                )
                self.assertEqual(status, 403)
                handler.assert_not_called()

    def test_run_rejects_missing_or_wrong_intent_and_wrong_content_type(self) -> None:
        base = {
            "Content-Type": "application/json",
            "Content-Length": "2",
            "Host": "127.0.0.1:8765",
        }
        cases = (
            base,
            {**base, "X-Model-Action-Intent": "wrong-v1"},
            {
                **base,
                "Content-Type": "text/plain",
                "X-Model-Action-Intent": "run-v1",
            },
        )
        for headers in cases:
            with self.subTest(headers=headers), patch("src.web.routes.api_run_step") as handler:
                status, _ct, _body = routes.dispatch(
                    "POST", "/api/workspace/alpha/run", b"{}", headers
                )
                self.assertIn(status, {403, 415})
                handler.assert_not_called()

    def test_malformed_or_non_origin_grammar_fails_closed(self) -> None:
        base = self._wire_headers(
            content_type="application/json",
            intent_header="X-Model-Action-Intent",
            intent_value="run-v1",
            cross_site=False,
        )
        for origin in ("http://[", "http://127.0.0.1:8765/path", "http://127.0.0.1:8765?q=x"):
            with self.subTest(origin=origin), patch("src.web.routes.api_run_step") as handler:
                status, _ct, _body = routes.dispatch(
                    "POST",
                    "/api/workspace/alpha/run",
                    b"{}",
                    {**base, "Origin": origin},
                )
                self.assertEqual(status, 403)
                handler.assert_not_called()

    def test_diagnostics_is_protected_post_and_legacy_get_is_405(self) -> None:
        status, _ct, _body = routes.dispatch("GET", "/api/diag/models")
        self.assertEqual(status, 405)

        headers = self._wire_headers(
            content_type="application/json",
            intent_header="X-Model-Action-Intent",
            intent_value="diagnose-v1",
        )
        with patch("src.web.routes.diag.collect_model_diagnostics") as provider:
            status, _ct, _body = routes.dispatch(
                "POST", "/api/diag/models", b"{}", headers
            )
        self.assertEqual(status, 403)
        provider.assert_not_called()

        headers.pop("Origin")
        headers.pop("Sec-Fetch-Site")
        with patch(
            "src.web.routes.diag.collect_model_diagnostics",
            return_value={"models": []},
        ) as provider:
            status, _ct, body = routes.dispatch(
                "POST", "/api/diag/models", b"{}", headers
            )
        self.assertEqual(status, 200, body)
        provider.assert_called_once_with()

    def test_frontend_declares_every_distinct_intent(self) -> None:
        scripts = routes.static.JS_DASHBOARD + routes.static.JS_WIZARD + routes.static.JS_SETTINGS
        for expected in (
            "X-Workspace-Mutation-Intent",
            "mutate-v1",
            "X-Model-Action-Intent",
            "run-v1",
            "extract-style-v1",
            "X-Onboarding-Intent",
            "import-v1",
            "premise-v1",
            "X-Settings-Mutation-Intent",
            "update-v1",
            "X-Write-Recovery-Intent",
            "archive-and-regenerate-v1",
        ):
            self.assertIn(expected, scripts)


class SafeProjectionTests(unittest.TestCase):
    def setUp(self) -> None:
        # Each case represents an independent CLI execution. The production
        # accounting failure marker intentionally persists until it ends.
        from src.llm_client import _LLM_ACCOUNTING_DEGRADED
        token = _LLM_ACCOUNTING_DEGRADED.set(None)
        self.addCleanup(_LLM_ACCOUNTING_DEGRADED.reset, token)

    def test_mock_writer_task_never_routes_to_review_json(self) -> None:
        client = LLMClient("write")
        text = client._mock_text(
            [{"role": "user", "content": "请续写正文，并遵守以下审查标准"}]
        )
        self.assertIn("雨停在凌晨", text)
        self.assertNotIn('"verdict"', text)

    SECRET = "SYNTHETIC_AUTH_TOKEN"

    def test_exception_projection_drops_arbitrary_nested_provider_text(self) -> None:
        exc = RuntimeError(
            'Authorization: Bearer SYNTHETIC_AUTH_TOKEN\n'
            '{"prompt":{"body":"PRIVATE_PROMPT"},"response_body":"PRIVATE_RESPONSE",'
            '"url":"https://user:pass@example.invalid/object?X-Amz-Signature=SIGNED"}'
        )
        values = (
            _sanitize_error_text(exc),
            safe_exception_text(exc),
            json.dumps(exception_projection(exc)),
        )
        for value in values:
            self.assertNotIn(self.SECRET, value)
            self.assertNotIn("PRIVATE_PROMPT", value)
            self.assertNotIn("PRIVATE_RESPONSE", value)
            self.assertNotIn("SIGNED", value)

    def test_safe_url_removes_userinfo_query_and_fragment(self) -> None:
        self.assertEqual(
            safe_url("https://user:pass@EXAMPLE.invalid:8443/v1?q=secret#fragment"),
            "https://example.invalid:8443/v1",
        )
        self.assertIsNone(safe_url("unknown free text PRIVATE_PROMPT"))

    def test_terminal_provider_failure_has_no_raw_cause_or_log_text(self) -> None:
        marker = "SIGNED_PRIVATE_PROVIDER_TEXT"
        with tempfile.TemporaryDirectory() as tmp, patch(
            "src.llm_client.ROOT", Path(tmp)
        ):
            client = LLMClient("extract")
            client.config = dict(client.config)
            client.config.update({"retry_attempts": 1, "max_tokens": 16})
            with patch.object(
                LLMClient, "is_mock", new_callable=PropertyMock, return_value=False
            ), patch("litellm.completion", side_effect=RuntimeError(marker)):
                with self.assertRaises(LLMProviderFailure) as raised:
                    client.complete_text([{"role": "user", "content": "PRIVATE_PROMPT"}], stream=False)
            self.assertIsNone(raised.exception.__cause__)
            self.assertNotIn(marker, str(raised.exception))
            log_text = (Path(tmp) / "logs" / "llm_calls.jsonl").read_text(encoding="utf-8")
            self.assertNotIn(marker, log_text)
            self.assertNotIn("PRIVATE_PROMPT", log_text)
            rows = [json.loads(line) for line in log_text.splitlines()]
            self.assertTrue(all("error_code" in row for row in rows))
            self.assertTrue(all("trace_id" in row for row in rows))
            self.assertEqual({row["trace_id"] for row in rows}, {raised.exception.trace_id})

    def test_response_validation_failure_drops_invalid_response(self) -> None:
        class Result(BaseModel):
            value: int

        client = LLMClient("extract")
        client.config = dict(client.config)
        client.config["json_repair"] = False
        marker = "PRIVATE_RESPONSE_BODY"
        with patch.object(
            LLMClient, "is_mock", new_callable=PropertyMock, return_value=False
        ), patch.object(client, "complete_text", return_value=marker):
            with self.assertRaises(LLMResponseValidationError) as raised:
                client.complete_json([], Result)
        self.assertNotIn(marker, str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
        self.assertIsNone(raised.exception.__context__)

    def test_json_repair_preserves_terminal_admission_failure(self) -> None:
        class Result(BaseModel):
            value: int

        client = LLMClient("extract")
        client.config = dict(client.config)
        client.config["json_repair"] = True
        terminal = LLMBudgetLimitExceeded(budget_cny=1.0, cost_cny=1.0)
        with patch.object(
            LLMClient, "is_mock", new_callable=PropertyMock, return_value=False
        ), patch.object(client, "complete_text", side_effect=["not-json", terminal]) as complete:
            with self.assertRaises(LLMBudgetLimitExceeded) as raised:
                client.complete_json([], Result)
        self.assertIs(raised.exception, terminal)
        self.assertEqual(complete.call_count, 2)

    def test_hostile_exception_shape_cannot_break_safe_projection(self) -> None:
        class Hostile(RuntimeError):
            @property
            def reason(self):
                raise KeyboardInterrupt()

            @property
            def trace_id(self):
                raise SystemExit()

            def __str__(self):
                raise RuntimeError("SYNTHETIC_SECRET")

        exc = Hostile()
        self.assertEqual(public_llm_failure_reason(exc), "generation_failed")
        projected = exception_projection(exc)
        self.assertEqual(projected["failure_reason"], "operation_failed")
        self.assertNotIn("SYNTHETIC_SECRET", safe_exception_text(exc))

        class HostileMeta(type):
            @property
            def __name__(cls):
                raise RuntimeError("TYPE_NAME_SECRET")

        class HostileType(RuntimeError, metaclass=HostileMeta):
            pass

        hostile_type = HostileType()
        self.assertEqual(public_llm_failure_reason(hostile_type), "generation_failed")
        self.assertEqual(exception_projection(hostile_type)["error_type"], "Exception")

        class BoolBomb:
            def __bool__(self):
                raise RuntimeError("BOOL_SECRET")

        weird_reason = RuntimeError()
        weird_reason.reason = BoolBomb()
        self.assertEqual(
            exception_projection(weird_reason)["failure_reason"], "operation_failed"
        )

        from src.web.safe_log import log_exception

        with patch("src.web.safe_log.sys.stderr.write"):
            trace = log_exception("iter168.hostile", hostile_type)
        self.assertRegex(trace, r"^[a-f0-9]{32}$")

    def test_log_sink_failure_never_retries_or_replaces_provider_terminal(self) -> None:
        client = LLMClient("extract")
        client.config = dict(client.config)
        client.config["retry_attempts"] = 3
        marker = "PRIVATE_PROVIDER_MARKER"
        with patch.object(
            LLMClient, "is_mock", new_callable=PropertyMock, return_value=False
        ), patch("litellm.completion", side_effect=RuntimeError(marker)) as completion, patch.object(
            client, "_log_call", side_effect=OSError("log sink failed")
        ):
            with self.assertRaises(LLMProviderFailure) as raised:
                client.complete_text([{"role": "user", "content": "private"}], stream=False)
        self.assertEqual(completion.call_count, 1)
        self.assertIsNone(raised.exception.__context__)
        self.assertNotIn(marker, str(raised.exception))

    def test_log_sink_failure_blocks_next_paid_call_when_accounting_is_degraded(self) -> None:
        client = LLMClient("extract")
        client.config = dict(client.config)
        response = {"choices": [{"message": {"content": "ok"}}]}
        with patch.object(
            LLMClient, "is_mock", new_callable=PropertyMock, return_value=False
        ), patch("litellm.completion", return_value=response) as completion, patch.object(
            client, "_log_call", side_effect=OSError("log sink failed")
        ), llm_budget_limit_scope(
            2.0, lambda: 0.0, required=True, require_known_pricing=True
        ):
            self.assertEqual(client.complete_text([{"role": "user", "content": "one"}], stream=False), "ok")
            self.assertTrue(llm_accounting_degraded())
            with self.assertRaises(LLMAccountingUnavailable):
                client.complete_text([{"role": "user", "content": "two"}], stream=False)
        self.assertEqual(completion.call_count, 1)

    def test_paid_call_reserves_worst_case_tokens_before_provider(self) -> None:
        client = LLMClient("extract")
        client.model = "deepseek/deepseek-chat"
        client.config = dict(client.config)
        client.config["max_tokens"] = 10_000
        with patch.object(
            LLMClient, "is_mock", new_callable=PropertyMock, return_value=False
        ), patch("litellm.completion") as completion, llm_budget_limit_scope(
            1.0, lambda: 0.95, required=True, require_known_pricing=True
        ):
            with self.assertRaises(LLMBudgetLimitExceeded):
                client.complete_text(
                    [{"role": "user", "content": "synthetic " * 10_000}],
                    stream=False,
                )
        completion.assert_not_called()

    def test_model_configuration_is_frozen_inside_admitted_scope(self) -> None:
        base_config = {
                "model": "provider/frozen-model",
                "max_tokens": 123,
                "context_limit": 1000,
                "temperature": 0.2,
        }
        frozen = {
            task: dict(base_config)
            for task in ("extract", "compress", "debate", "write", "review", "plot_planner")
        }
        with tempfile.TemporaryDirectory() as tmp, llm_model_config_scope(frozen), patch(
                "src.llm_client.get_model_config",
                return_value={"model": "provider/changed-after-admission"},
            ) as live_config:
                client = LLMClient("write")
                from src.book_runner import _expected_write_model
                from src.context_budget import budget_for_task

                expected_model = _expected_write_model()
                prompt_budget = budget_for_task("write")
                run_preflight(Path(tmp))
        self.assertEqual(client.model, "provider/frozen-model")
        self.assertEqual(client.config["max_tokens"], 123)
        self.assertEqual(expected_model, "provider/frozen-model")
        self.assertEqual(prompt_budget, 777)
        live_config.assert_not_called()


class SafeJsonlTests(unittest.TestCase):
    def _root(self, tmp: str) -> tuple[Path, Path]:
        root = Path(tmp)
        logs = root / "logs"
        logs.mkdir()
        return root, logs / "llm_calls.jsonl"

    def test_returns_only_bounded_dict_tail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, path = self._root(tmp)
            path.write_text('{"n":1}\n{"n":2}\n{"n":3}\n', encoding="utf-8")
            self.assertEqual(tail_jsonl(root, "logs/llm_calls.jsonl", 2), [{"n": 2}, {"n": 3}])

    def test_symlink_fifo_oversize_deep_and_bad_rows_degrade_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root, path = self._root(tmp)
            target = Path(outside) / "outside.jsonl"
            target.write_text('{"outside_marker":true}\n', encoding="utf-8")
            path.symlink_to(target)
            self.assertEqual(tail_jsonl(root, "logs/llm_calls.jsonl", 10), [])
            path.unlink()

            os.mkfifo(path)
            self.assertEqual(tail_jsonl(root, "logs/llm_calls.jsonl", 10), [])
            path.unlink()

            path.write_bytes(b'{"value":"' + b"x" * (2 * 1024 * 1024) + b'"}\n')
            self.assertEqual(tail_jsonl(root, "logs/llm_calls.jsonl", 10), [])

            nested: dict[str, object] = {}
            for _ in range(65):
                nested = {"x": nested}
            path.write_text(json.dumps(nested) + "\n", encoding="utf-8")
            self.assertEqual(tail_jsonl(root, "logs/llm_calls.jsonl", 10), [])

            path.write_text('["not", "a", "dict"]\n', encoding="utf-8")
            self.assertEqual(tail_jsonl(root, "logs/llm_calls.jsonl", 10), [])

    def test_cumulative_limit_and_identity_change_degrade_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, path = self._root(tmp)
            row = json.dumps({"value": "x" * 580}) + "\n"
            path.write_text(row * 1000, encoding="utf-8")
            self.assertEqual(tail_jsonl(root, "logs/llm_calls.jsonl", 1000), [])

            path.write_text('{"ok":true}\n', encoding="utf-8")
            real_fstat = os.fstat
            calls = 0

            def changed(fd: int):
                nonlocal calls
                calls += 1
                value = real_fstat(fd)
                if calls == 3:
                    return SimpleNamespace(
                        st_dev=value.st_dev,
                        st_ino=value.st_ino,
                        st_size=value.st_size,
                        st_mtime_ns=value.st_mtime_ns + 1,
                        st_mode=value.st_mode,
                    )
                return value

            with patch("src.safe_jsonl.os.fstat", side_effect=changed):
                self.assertEqual(tail_jsonl(root, "logs/llm_calls.jsonl", 10), [])

    def test_raw_line_limit_and_path_replacement_degrade_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root, path = self._root(tmp)
            path.write_bytes(b" " * (70 * 1024) + b"{}\n")
            self.assertEqual(tail_jsonl(root, "logs/llm_calls.jsonl", 10), [])

            path.write_text('{"old_marker":true}\n', encoding="utf-8")
            backup = path.with_suffix(".old")
            real_pread = os.pread
            replaced = False

            def replacing_pread(fd: int, size: int, offset: int) -> bytes:
                nonlocal replaced
                data = real_pread(fd, size, offset)
                if not replaced:
                    replaced = True
                    path.rename(backup)
                    path.write_text('{"new_marker":true}\n', encoding="utf-8")
                return data

            with patch("src.safe_jsonl.os.pread", side_effect=replacing_pread):
                self.assertEqual(tail_jsonl(root, "logs/llm_calls.jsonl", 10), [])

    def test_preflight_uses_same_reader_for_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, tempfile.TemporaryDirectory() as outside:
            root = Path(tmp)
            (root / "logs").mkdir()
            target = Path(outside) / "outside.jsonl"
            target.write_text('{"status":"outside_marker"}\n', encoding="utf-8")
            (root / "logs" / "llm_calls.jsonl").symlink_to(target)
            with patch.dict(os.environ, {"OPENAI_MODEL": "mock"}, clear=True):
                report = run_preflight(root)
            rendered = json.dumps(report, ensure_ascii=False)
            self.assertNotIn("outside_marker", rendered)
            self.assertIn("no readable bounded", rendered)

    def test_preflight_projects_status_and_numeric_fields_safely(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "logs").mkdir()
            (root / "logs" / "llm_calls.jsonl").write_text(
                json.dumps(
                    {
                        "status": "Bearer SYNTHETIC_SECRET",
                        "prompt_tokens": "bad",
                        "completion_tokens": {"nested": "secret"},
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {"OPENAI_MODEL": "mock"}, clear=True):
                report = run_preflight(root)
            rendered = json.dumps(report, ensure_ascii=False)
            self.assertNotIn("SYNTHETIC_SECRET", rendered)
            self.assertNotIn('"bad"', rendered)


class WorkbenchTemplateConstraintTests(unittest.TestCase):
    def test_default_write_budget_is_valid_for_rendered_step(self) -> None:
        html = templates.render_workspace_workbench("book", ["book"])
        self.assertIn(
            'id="write-budget-input" name="budget_cny" type="number" '
            'min="0.1" max="6" step="any" value="6"',
            html,
        )


class WorkbenchFreshnessTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self._saved = paths.WORKSPACE_DIR
        self._saved_env = os.environ.get("WORKSPACE_NAME")
        os.environ.pop("WORKSPACE_NAME", None)
        paths.WORKSPACE_DIR = Path(self._tmp.name)

    def tearDown(self) -> None:
        paths.WORKSPACE_DIR = self._saved
        if self._saved_env is None:
            os.environ.pop("WORKSPACE_NAME", None)
        else:
            os.environ["WORKSPACE_NAME"] = self._saved_env
        self._tmp.cleanup()

    def _plan(self, chapters: int = 2) -> dict:
        plan = {
            "target_chapters": chapters,
            "overall_arc": "synthetic arc",
            "schema_version": 1,
            "chapters": [
                {
                    "chapter_no": chapter,
                    "title": f"chapter {chapter}",
                    "opening_scene": "synthetic opening",
                    "key_events": ["event one", "event two"],
                    "relationships_in_play": [],
                    "ending_hook": "synthetic hook",
                    "target_chinese_chars": 4000,
                    "plot_purpose": "synthetic purpose",
                }
                for chapter in range(1, chapters + 1)
            ],
        }
        for item in plan["chapters"]:
            item["chapter_plan_item_fingerprint"] = chapter_plan_item_fingerprint(item)
        plan["plan_fingerprint"] = plan_fingerprint(plan)
        return plan

    def _workspace(self, name: str = "freshbook", chapters: int = 2) -> tuple[Path, dict]:
        ws = paths.WORKSPACE_DIR / name
        drafts = ws / "outputs" / "drafts"
        reviews = ws / "outputs" / "reviews"
        debate = ws / "outputs" / "debate"
        kb = ws / "data" / "knowledge_base"
        for directory in (drafts, reviews, debate, kb, ws / "logs", ws / "小说txt"):
            directory.mkdir(parents=True, exist_ok=True)
        workspace_meta.write(name, type="novel", creation_mode="greenfield")
        (kb / "global_knowledge.md").write_text("synthetic kb", encoding="utf-8")
        (debate / "outline.md").write_text("synthetic outline", encoding="utf-8")
        plan = self._plan(chapters)
        write_json(debate / "chapter_plan.json", plan)
        os.utime(kb / "global_knowledge.md", ns=(1_000_000_000, 1_000_000_000))
        os.utime(debate / "outline.md", ns=(2_000_000_000, 2_000_000_000))
        os.utime(debate / "chapter_plan.json", ns=(3_000_000_000, 3_000_000_000))

        with use_workspace(name):
            from src.writer import _load_chapter_plan, _run_context

            loaded = _load_chapter_plan()
            for chapter in range(1, chapters + 1):
                draft = f"synthetic chapter {chapter}\n"
                context = _run_context(loaded[chapter], chapter_no=chapter)
                (drafts / f"chapter_{chapter:02d}.md").write_text(draft, encoding="utf-8")
                metadata = {
                    "verdict": "Approve",
                    "needs_human_review": False,
                    "run_context": context,
                    "draft_sha256": sha256_text(draft),
                }
                write_json(drafts / f"chapter_{chapter:02d}.meta.json", metadata)
                write_json(
                    reviews / f"chapter_{chapter:02d}.review.json",
                    {
                        "verdict": "Approve",
                        "needs_human_review": False,
                        "run_context": context,
                        "draft_sha256": sha256_text(draft),
                    },
                )
        return ws, plan

    def _status(self, name: str = "freshbook") -> dict:
        status, _ct, body = routes.dispatch("GET", f"/api/workspace/{name}/workbench")
        self.assertEqual(status, 200, body)
        return json.loads(body)

    def test_stale_item_or_external_review_mismatch_never_projects_done(self) -> None:
        ws, plan = self._workspace()
        self.assertEqual(self._status()["stage"], "done")
        plan["chapters"][0]["title"] = "changed current plan item"
        plan["chapters"][0]["chapter_plan_item_fingerprint"] = chapter_plan_item_fingerprint(
            plan["chapters"][0]
        )
        write_json(ws / "outputs" / "debate" / "chapter_plan.json", plan)
        status = self._status()
        self.assertEqual(status["stage"], "write")
        self.assertEqual(status["write_state"], "needs_review")

        ws, _plan = self._workspace("reviewbook", chapters=1)
        review_path = ws / "outputs" / "reviews" / "chapter_01.review.json"
        review = json.loads(review_path.read_text(encoding="utf-8"))
        review["run_context"]["chapter_plan_item_fingerprint"] = "mismatch"
        write_json(review_path, review)
        status = self._status("reviewbook")
        self.assertEqual(status["stage"], "write")
        self.assertEqual(status["write_state"], "needs_review")

    def test_missing_plan_item_fails_closed(self) -> None:
        ws, plan = self._workspace()
        plan["target_chapters"] = 1
        plan["chapters"] = plan["chapters"][:1]
        write_json(ws / "outputs" / "debate" / "chapter_plan.json", plan)
        status = self._status()
        self.assertEqual(status["stage"], "write")
        self.assertEqual(status["write_state"], "needs_review")

    def test_reordered_or_fingerprint_inconsistent_plan_returns_to_plan_stage(self) -> None:
        ws, plan = self._workspace()
        plan["chapters"] = list(reversed(plan["chapters"]))
        write_json(ws / "outputs" / "debate" / "chapter_plan.json", plan)
        status = self._status()
        self.assertEqual(status["stage"], "plan")
        self.assertFalse(status["has_plan"])

        ws, plan = self._workspace("fingerprintbook", chapters=1)
        plan["chapters"][0]["title"] = "changed without fingerprint refresh"
        write_json(ws / "outputs" / "debate" / "chapter_plan.json", plan)
        status = self._status("fingerprintbook")
        self.assertEqual(status["stage"], "plan")
        self.assertFalse(status["has_plan"])

    def test_changed_start_never_revives_old_done_even_if_downstream_is_newer(self) -> None:
        ws, plan = self._workspace("startdrift", chapters=1)
        workspace_meta.write("startdrift", type="novel", creation_mode="continuation")
        source = ws / "normalized.txt"
        source.write_text("chapter one\nchapter two\n", encoding="utf-8")
        write_json(
            ws / "data" / "chapter_manifest.json",
            [
                {
                    "chapter_id": "synthetic_ch001",
                    "volume_id": "synthetic",
                    "source_file": str(source),
                    "normalized_file": str(source),
                    "title": "one",
                    "start_line": 1,
                    "end_line": 1,
                    "char_count": 11,
                },
                {
                    "chapter_id": "synthetic_ch002",
                    "volume_id": "synthetic",
                    "source_file": str(source),
                    "normalized_file": str(source),
                    "title": "two",
                    "start_line": 2,
                    "end_line": 2,
                    "char_count": 11,
                },
            ],
        )
        with use_workspace("startdrift"):
            from src import start_point
            from src.writer import _load_chapter_plan, _run_context

            start_point.set_start_point("synthetic_ch001")
            plan["start_chapter_id"] = "synthetic_ch001"
            plan["start_point_fingerprint"] = start_point.start_point_fingerprint()
            plan["plan_fingerprint"] = plan_fingerprint(plan)
            write_json(paths.chapter_plan_path(), plan)
            loaded = _load_chapter_plan()
            context = _run_context(loaded[1], chapter_no=1)
            draft = (paths.drafts_dir() / "chapter_01.md").read_text(encoding="utf-8")
            for artifact in (
                paths.drafts_dir() / "chapter_01.meta.json",
                paths.reviews_dir() / "chapter_01.review.json",
            ):
                write_json(
                    artifact,
                    {
                        "verdict": "Approve",
                        "needs_human_review": False,
                        "run_context": context,
                        "draft_sha256": sha256_text(draft),
                    },
                )
            now = 10_000_000_000
            os.utime(paths.manual_overrides_dir() / "start_chapter.json", ns=(now, now))
            os.utime(paths.kb_path(), ns=(now + 1, now + 1))
            os.utime(paths.outline_path(), ns=(now + 2, now + 2))
            os.utime(paths.chapter_plan_path(), ns=(now + 3, now + 3))
        self.assertEqual(self._status("startdrift")["stage"], "done")

        with use_workspace("startdrift"):
            start_point.set_start_point("synthetic_ch002")
            # Simulate a restore/touch that defeats an mtime-only gate while
            # retaining the old plan's start identity.
            now = 20_000_000_000
            os.utime(paths.manual_overrides_dir() / "start_chapter.json", ns=(now, now))
            os.utime(paths.kb_path(), ns=(now + 1, now + 1))
            os.utime(paths.outline_path(), ns=(now + 2, now + 2))
            os.utime(paths.chapter_plan_path(), ns=(now + 3, now + 3))
        status = self._status("startdrift")
        self.assertEqual(status["stage"], "plan")
        self.assertFalse(status["has_plan"])

if __name__ == "__main__":
    unittest.main()
