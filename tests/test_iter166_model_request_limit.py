from __future__ import annotations

import threading
import unittest
from unittest.mock import PropertyMock, patch

from src.llm_client import (
    LLMBudgetLimitExceeded,
    LLMClient,
    LLMPricingUnavailable,
    LLMRequestLimitExceeded,
    MAX_MODEL_REQUESTS_PER_JOB,
    llm_request_limit_scope,
    llm_budget_limit_scope,
)
from src.web import jobs, routes


def _response(text: str = "ok") -> dict:
    return {
        "choices": [{"message": {"content": text}}],
        "usage": {"prompt_tokens": 1, "completion_tokens": 1},
    }


class ModelRequestLimitScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = LLMClient("write")
        self.client.config["retry_attempts"] = 1
        self.messages = [{"role": "user", "content": "bounded test"}]

    def _real_call(self) -> str:
        return self.client.complete_text(self.messages, stream=False)

    def test_real_attempt_is_rejected_before_second_provider_call(self) -> None:
        with patch.object(LLMClient, "is_mock", new_callable=PropertyMock, return_value=False), patch.object(
            self.client, "_log_call"
        ), patch("litellm.completion", return_value=_response()) as completion:
            with llm_request_limit_scope(1, required=True):
                self.assertEqual(self._real_call(), "ok")
                with self.assertRaises(LLMRequestLimitExceeded):
                    self._real_call()
        self.assertEqual(completion.call_count, 1)

    def test_each_safe_retry_attempt_consumes_allowance(self) -> None:
        transient = ConnectionError("definitive pre-submit failure")
        transient.request_not_sent = True  # type: ignore[attr-defined]
        self.client.config.update(
            retry_attempts=3,
            retry_backoff_seconds=0,
            retry_backoff_jitter_seconds=0,
        )
        with patch.object(LLMClient, "is_mock", new_callable=PropertyMock, return_value=False), patch.object(
            self.client, "_log_call"
        ), patch("litellm.completion", side_effect=transient) as completion:
            with llm_request_limit_scope(1, required=True):
                with self.assertRaises(LLMRequestLimitExceeded):
                    self._real_call()
        self.assertEqual(completion.call_count, 1)

    def test_mock_completions_do_not_consume_real_allowance(self) -> None:
        with patch.object(self.client, "_log_call"):
            with llm_request_limit_scope(1, required=True):
                # The configured test model is mock, so both calls are local.
                self.client.complete_text(self.messages)
                self.client.complete_text(self.messages)
                with patch.object(
                    LLMClient, "is_mock", new_callable=PropertyMock, return_value=False
                ), patch("litellm.completion", return_value=_response()) as completion:
                    self.assertEqual(self._real_call(), "ok")
        completion.assert_called_once()

    def test_nested_scope_restores_outer_counter(self) -> None:
        with patch.object(LLMClient, "is_mock", new_callable=PropertyMock, return_value=False), patch.object(
            self.client, "_log_call"
        ), patch("litellm.completion", return_value=_response()) as completion:
            with llm_request_limit_scope(2, required=True):
                self._real_call()
                with llm_request_limit_scope(1, required=True):
                    self._real_call()
                    with self.assertRaises(LLMRequestLimitExceeded):
                        self._real_call()
                self._real_call()
                with self.assertRaises(LLMRequestLimitExceeded):
                    self._real_call()
        self.assertEqual(completion.call_count, 3)

    def test_concurrent_threads_have_independent_counters(self) -> None:
        calls = 0
        calls_lock = threading.Lock()
        outcomes: list[tuple[bool, bool]] = []

        def fake_completion(**_kwargs: object) -> dict:
            nonlocal calls
            with calls_lock:
                calls += 1
            return _response()

        def run() -> None:
            first = second_blocked = False
            with llm_request_limit_scope(1, required=True):
                first = self._real_call() == "ok"
                try:
                    self._real_call()
                except LLMRequestLimitExceeded:
                    second_blocked = True
            outcomes.append((first, second_blocked))

        with patch.object(LLMClient, "is_mock", new_callable=PropertyMock, return_value=False), patch.object(
            self.client, "_log_call"
        ), patch("litellm.completion", side_effect=fake_completion):
            threads = [threading.Thread(target=run) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=5)
        self.assertEqual(sorted(outcomes), [(True, True), (True, True)])
        self.assertEqual(calls, 2)

    def test_missing_required_limit_fails_before_provider(self) -> None:
        with patch.object(LLMClient, "is_mock", new_callable=PropertyMock, return_value=False), patch.object(
            self.client, "_log_call"
        ), patch("litellm.completion", return_value=_response()) as completion:
            with llm_request_limit_scope(None, required=True):
                with self.assertRaises(LLMRequestLimitExceeded):
                    self._real_call()
        completion.assert_not_called()

    def test_bad_and_out_of_range_scopes_fail_closed(self) -> None:
        bad_values = (True, 1.5, "1.5", 0, -1, MAX_MODEL_REQUESTS_PER_JOB + 1)
        for value in bad_values:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    with llm_request_limit_scope(value, required=True):
                        self.fail("invalid scope entered")

    def test_known_budget_is_checked_before_provider_attempt(self) -> None:
        with patch.object(LLMClient, "is_mock", new_callable=PropertyMock, return_value=False), patch.object(
            self.client, "_log_call"
        ), patch("litellm.completion", return_value=_response()) as completion:
            with llm_budget_limit_scope(1.0, lambda: 1.0, required=True):
                with self.assertRaises(LLMBudgetLimitExceeded):
                    self._real_call()
        completion.assert_not_called()

    def test_mock_does_not_evaluate_budget_probe(self) -> None:
        probe = unittest.mock.Mock(side_effect=AssertionError("mock touched budget probe"))
        with llm_budget_limit_scope(
            1.0, probe, required=True, require_known_pricing=True
        ):
            self.client.complete_text(self.messages)
        probe.assert_not_called()

    def test_paid_web_scope_rejects_unknown_pricing_before_provider(self) -> None:
        self.client.model = "openai/synthetic-unknown-price"
        with patch.object(self.client, "_log_call"), patch(
            "litellm.completion", return_value=_response()
        ) as completion:
            with llm_budget_limit_scope(
                1.0,
                lambda: 0.0,
                required=True,
                require_known_pricing=True,
            ):
                with self.assertRaises(LLMPricingUnavailable):
                    self._real_call()
        completion.assert_not_called()

    def test_paid_web_scope_allows_explicitly_priced_model(self) -> None:
        self.client.model = "deepseek/deepseek-chat"
        with patch.object(self.client, "_log_call"), patch(
            "litellm.completion", return_value=_response()
        ) as completion:
            with llm_budget_limit_scope(
                1.0,
                lambda: 0.0,
                required=True,
                require_known_pricing=True,
            ):
                self.assertEqual(self._real_call(), "ok")
        completion.assert_called_once()

    def test_cli_compatibility_keeps_legacy_unknown_price_fallback(self) -> None:
        self.client.model = "openai/synthetic-unknown-price"
        with patch.object(self.client, "_log_call"), patch(
            "litellm.completion", return_value=_response()
        ) as completion:
            with llm_budget_limit_scope(1.0, lambda: 0.0, required=True):
                self.assertEqual(self._real_call(), "ok")
        completion.assert_called_once()


class WebModelRequestLimitValidationTests(unittest.TestCase):
    def test_stage_defaults_are_server_derived(self) -> None:
        expected = {
            "expand-premise": 2,
            "prepare-greenfield": 10,
            "rebuild-for-start": 32,
            "debate": 45,
            "plan-chapters": 3,
            "write-book": 20,
        }
        for step, limit in expected.items():
            with self.subTest(step=step):
                error, params = routes._validated_run_params(step, {})
                self.assertIsNone(error)
                self.assertEqual(params["max_model_requests"], limit)
                self.assertGreater(params["budget_cny"], 0)
                self.assertGreater(params["timeout_minutes"], 0)

    def test_explicit_limit_is_validated_and_preserved(self) -> None:
        error, params = routes._validated_run_params(
            "write-book", {"max_model_requests": 7}
        )
        self.assertIsNone(error)
        self.assertEqual(params["max_model_requests"], 7)

    def test_stage_specific_hard_maxima_are_enforced(self) -> None:
        maxima = {
            "expand-premise": (2, 1.0, 15.0),
            "prepare-greenfield": (10, 3.0, 15.0),
            "rebuild-for-start": (32, 20.0, 15.0),
            "extract": (10, 3.0, 15.0),
            "compress": (10, 3.0, 15.0),
            "bootstrap": (10, 3.0, 15.0),
            "debate": (45, 33.0, 60.0),
            "plan-chapters": (3, 10.0, 15.0),
            "write-book": (160, 32.0, 45.0),
            "review-chapter": (20, 6.0, 45.0),
            "auto-pipeline-greenfield": (160, 40.0, 120.0),
            "extract-style": (2, 2.0, 15.0),
        }
        for step, (requests, budget, timeout) in maxima.items():
            with self.subTest(step=step, field="at_max"):
                error, params = routes._validated_run_params(
                    step,
                    {
                        "max_model_requests": requests,
                        "budget_cny": budget,
                        "timeout_minutes": timeout,
                    },
                )
                self.assertIsNone(error)
                self.assertEqual(params["max_model_requests"], requests)
                self.assertEqual(params["budget_cny"], budget)
                self.assertEqual(params["timeout_minutes"], timeout)
            for field, value in (
                ("max_model_requests", requests + 1),
                ("budget_cny", budget + 0.1),
                ("timeout_minutes", timeout + 0.1),
            ):
                with self.subTest(step=step, field=field):
                    error, params = routes._validated_run_params(step, {field: value})
                    self.assertIsNotNone(error)
                    self.assertEqual(params, {})

    def test_invalid_web_limits_are_rejected(self) -> None:
        for value in (None, True, 0, -1, 2.5, "2.5", jobs.MAX_MODEL_REQUESTS_PER_JOB + 1):
            with self.subTest(value=value):
                error, params = routes._validated_run_params(
                    "debate", {"max_model_requests": value}
                )
                self.assertIsNotNone(error)
                self.assertEqual(params, {})

    def test_model_steps_reject_uncapped_budget_and_timeout(self) -> None:
        for field in ("budget_cny", "timeout_minutes"):
            with self.subTest(field=field):
                error, params = routes._validated_run_params("debate", {field: 0})
                self.assertIsNotNone(error)
                self.assertEqual(params, {})

    def test_retry_projection_keeps_limit_but_not_confirmation(self) -> None:
        projected = jobs._public_retry_params(
            {
                "chapters": 1,
                "max_model_requests": 20,
                "confirm_archive_and_regenerate": True,
            },
            step="write-book",
        )
        self.assertEqual(projected, {"chapters": 1, "max_model_requests": 20})


if __name__ == "__main__":
    unittest.main()
