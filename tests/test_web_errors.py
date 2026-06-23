"""iter062: unit tests for the WebUI friendly-error catalog (src/web/errors.py).

Pure data + pure functions; no HTTP server, no LLM. Verifies exception->code
mapping (incl. subclass ordering), readiness mapping, and that raw exception
text is NOT leaked into ``technical`` by default.
"""

from __future__ import annotations

import json
import unittest

from src.web import errors


class CodeForExceptionTest(unittest.TestCase):
    def test_known_exception_types(self) -> None:
        cases = {
            "bad_json": json.JSONDecodeError("x", "", 0),
            "file_missing": FileNotFoundError("/p/x.json"),
            "encoding_error": UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad"),
            "invalid_value": ValueError("target_chinese_chars must be > 0"),
            "io_error": OSError(13, "Permission denied"),
            "server_error": RuntimeError("boom"),
        }
        for expected_code, exc in cases.items():
            self.assertEqual(errors.code_for_exception(exc), expected_code, exc)

    def test_subclass_ordering(self) -> None:
        # JSONDecodeError/UnicodeDecodeError subclass ValueError;
        # FileNotFoundError/PermissionError subclass OSError. Specific wins.
        self.assertEqual(errors.code_for_exception(json.JSONDecodeError("x", "", 0)), "bad_json")
        self.assertEqual(errors.code_for_exception(PermissionError("denied")), "io_error")
        self.assertEqual(errors.code_for_exception(FileNotFoundError("x")), "file_missing")


class BuildCardTest(unittest.TestCase):
    def test_server_error_carries_trace_id(self) -> None:
        card = errors.build_card("server_error", trace_id="abc123")
        self.assertEqual(card["code"], "server_error")
        self.assertEqual(card["trace_id"], "abc123")
        self.assertTrue(card["title"])
        self.assertTrue(card["cause"])

    def test_unknown_code_degrades_to_server_error(self) -> None:
        card = errors.build_card("totally_unknown_code")
        self.assertEqual(card["code"], "server_error")

    def test_invalid_value_uses_detail(self) -> None:
        card = errors.build_card("invalid_value", detail="bad field 'x'")
        self.assertIn("bad field 'x'", card["cause"])

    def test_invalid_value_empty_detail_falls_back(self) -> None:
        card = errors.build_card("invalid_value", detail="")
        self.assertNotIn("{detail}", card["cause"])
        self.assertTrue(card["cause"])

    def test_actions_are_copied_not_shared(self) -> None:
        a = errors.build_card("file_missing")
        b = errors.build_card("file_missing")
        self.assertIsNot(a["actions"], b["actions"])


class CardForExceptionTest(unittest.TestCase):
    def test_technical_withheld_by_default(self) -> None:
        card = errors.card_for_exception(OSError(13, "Permission denied: /secret/path"))
        self.assertEqual(card["technical"], "")
        # the raw path must not leak into any user-facing field by default
        self.assertNotIn("/secret/path", card["title"])
        self.assertNotIn("/secret/path", card["cause"])

    def test_technical_exposed_when_requested(self) -> None:
        card = errors.card_for_exception(RuntimeError("boom"), expose_technical=True)
        self.assertIn("RuntimeError", card["technical"])
        self.assertIn("boom", card["technical"])

    def test_value_error_detail_surfaces_in_cause(self) -> None:
        card = errors.card_for_exception(ValueError("non-editable field"))
        self.assertEqual(card["code"], "invalid_value")
        self.assertIn("non-editable field", card["cause"])

    def test_absolute_path_redacted_from_cause(self) -> None:
        # iter064 #4: a ValueError carrying an absolute path (e.g. hook_designer's
        # setup_path) must not leak the directory tree into the client-visible
        # cause. The basename survives; the leading directories are hidden.
        exc = ValueError(
            "setup must be a JSON object: "
            "/Users/me/工作区/foo/outputs/episodes/episode_01.setup.json"
        )
        card = errors.card_for_exception(exc)
        self.assertEqual(card["code"], "invalid_value")
        self.assertNotIn("/Users/me", card["cause"])
        self.assertNotIn("/outputs/episodes", card["cause"])
        self.assertIn("episode_01.setup.json", card["cause"])
        self.assertIn("…/", card["cause"])

    def test_redact_paths_leaves_prose_untouched(self) -> None:
        # Requires a leading `/` + >=2 segments, so normal prose stays intact.
        for text in ("ratio is 3/4", "a/b", "TCP/IP", "no slash here", ""):
            self.assertEqual(errors._redact_paths(text), text)

    def test_redact_paths_handles_spaces_in_parent_dirs(self) -> None:
        # iter064 收官审查 P1: a space in a parent directory must NOT truncate the
        # match and leak the rest of the tree. The whole path collapses to …/leaf.
        out = errors._redact_paths("/Users/x/My Docs/foo/report.txt")
        self.assertNotIn("My Docs", out)
        self.assertNotIn("/foo", out)
        self.assertIn("…/report.txt", out)

    def test_exception_body_redacts_both_error_and_card(self) -> None:
        # iter064 #4: the {error, card} response body must redact the path in
        # BOTH fields — the raw `error` key used to leak it even when the card
        # was clean (12 drama/web handlers inlined `{"error": str(exc), ...}`).
        exc = ValueError("setup must be a JSON object: /Users/me/ws/foo/episode_01.setup.json")
        body = errors.exception_body(exc)
        self.assertNotIn("/Users/me", body["error"])
        self.assertNotIn("/Users/me", body["card"]["cause"])
        self.assertIn("episode_01.setup.json", body["error"])  # basename survives

    def test_exception_body_preserves_non_path_message(self) -> None:
        # Backward compat: a message without a path is unchanged in `error`.
        body = errors.exception_body(ValueError("topic is required"))
        self.assertEqual(body["error"], "topic is required")


class ReadinessCatalogSingleSourceTest(unittest.TestCase):
    """iter063 Part C: errors cards, book_runner._primary_blocker, and the
    injected frontend catalog must all derive from src/readiness_catalog so the
    three former copies can't drift."""

    def test_errors_cards_derive_from_catalog(self) -> None:
        from src import readiness_catalog

        for kind, spec in readiness_catalog.KINDS.items():
            card = errors.readiness_card(kind)
            self.assertEqual(card["title"], spec["label"], kind)
            self.assertEqual(card["cause"], spec["cause"], kind)
            self.assertEqual(card["actions"][0]["action"], spec["cta_action"], kind)
            self.assertEqual(card["actions"][0]["label"], spec["cta_label"], kind)

    def test_readiness_kind_delegates_to_catalog(self) -> None:
        from src import readiness_catalog

        for raw in (
            "start_point_missing",
            "chapter_plan:ch3",
            "preflight:models",
            "stale debate outline (outline_content_mismatch): x",
            "foreshadowing_must_resolve_overdue:2",
            "some_unknown_thing",
        ):
            self.assertEqual(errors.readiness_kind(raw), readiness_catalog.classify(raw), raw)

    def test_book_runner_primary_blocker_uses_catalog(self) -> None:
        from src import book_runner, readiness_catalog

        for kind, spec in readiness_catalog.KINDS.items():
            if kind == "unknown":
                continue
            pb = book_runner._primary_blocker([kind])
            self.assertEqual(pb["label"], spec["label"], kind)
            self.assertEqual(pb["cta_action"], spec["cta_action"], kind)
            self.assertEqual(pb["cta_label"], spec["cta_label"], kind)

    def test_injected_frontend_catalog_matches_python(self) -> None:
        from src import readiness_catalog
        from src.web import templates

        self.assertEqual(json.loads(templates._READINESS_CATALOG_JSON), readiness_catalog.KINDS)
        shell = templates._render_shell(
            title="t", page_kind="index", main_html="x", breadcrumb_html=""
        )
        self.assertIn("window.READINESS_CATALOG = {", shell)
        self.assertIn(templates._READINESS_CATALOG_JSON, shell)


class ReadinessCardTest(unittest.TestCase):
    def test_known_kinds(self) -> None:
        self.assertEqual(errors.readiness_card("start_point_missing")["title"], "未设置续写起点")
        self.assertEqual(errors.readiness_card("chapter_plan_missing")["title"], "缺少章节计划")
        self.assertEqual(errors.readiness_card("outline_missing")["title"], "缺少全书大纲")

    def test_raw_blocker_with_suffix_classifies(self) -> None:
        self.assertEqual(errors.readiness_kind("outline_missing:foo"), "outline_missing")
        self.assertEqual(errors.readiness_kind("chapter_plan:ch3"), "chapter_plan_missing")
        self.assertEqual(errors.readiness_kind("preflight:models"), "preflight_failed")

    def test_outline_stale_classifies_and_has_card(self) -> None:
        # iter063 A1: both the exact kind and the raw plot_planner message
        # ("stale debate outline (outline_content_mismatch): …") classify here.
        self.assertEqual(errors.readiness_kind("outline_stale"), "outline_stale")
        self.assertEqual(
            errors.readiness_kind("stale debate outline (outline_content_mismatch): 详情"),
            "outline_stale",
        )
        card = errors.readiness_card("outline_stale")
        self.assertEqual(card["title"], "大纲与当前起点不一致")
        self.assertEqual(card["actions"][0]["action"], "go_plan")

    def test_unknown_blocker_falls_back(self) -> None:
        self.assertEqual(errors.readiness_kind("some_new_thing"), "unknown")
        self.assertTrue(errors.readiness_card("some_new_thing")["title"])


class ErrorBodyTest(unittest.TestCase):
    def test_error_body_keeps_title_and_card(self) -> None:
        card = errors.card_for_exception(ValueError("z"))
        body = errors.error_body(card)
        self.assertEqual(body["error"], card["title"])
        self.assertEqual(body["card"], card)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
