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


class ReadinessCardTest(unittest.TestCase):
    def test_known_kinds(self) -> None:
        self.assertEqual(errors.readiness_card("start_point_missing")["title"], "未设置续写起点")
        self.assertEqual(errors.readiness_card("chapter_plan_missing")["title"], "缺少章节计划")
        self.assertEqual(errors.readiness_card("outline_missing")["title"], "缺少全书大纲")

    def test_raw_blocker_with_suffix_classifies(self) -> None:
        self.assertEqual(errors.readiness_kind("outline_missing:foo"), "outline_missing")
        self.assertEqual(errors.readiness_kind("chapter_plan:ch3"), "chapter_plan_missing")
        self.assertEqual(errors.readiness_kind("preflight:models"), "preflight_failed")

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
