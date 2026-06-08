"""iter 047a: tests for the layered token-budget assembler.

Uses ``token_counter=len`` (1 char == 1 token) so budgets and shrink results
are exactly assertable. Also pins that the extracted ``count_tokens`` free
function matches ``LLMClient._count_tokens`` byte-for-byte (zero regression).
"""

import math
import unittest
from unittest.mock import patch

from src.context_budget import (
    Layer,
    assemble,
    budget_for_task,
    count_tokens,
    token_counter_for,
)
from src.llm_client import LLMClient


class AssembleTests(unittest.TestCase):
    def test_loose_budget_equals_naive_concat(self) -> None:
        layers = [
            Layer(name="a", text="AAAA", priority=1),
            Layer(name="b", text="BBBB", priority=2),
        ]
        out = assemble(layers, budget_tokens=1000, token_counter=len)
        self.assertEqual(out, "AAAABBBB")  # verbatim, input order preserved

    def test_over_budget_evicts_lowest_priority_first(self) -> None:
        layers = [
            Layer(name="hi", text="H" * 10, priority=5),
            Layer(name="lo", text="L" * 10, priority=1),
        ]
        out = assemble(layers, budget_tokens=12, token_counter=len)
        self.assertLessEqual(len(out), 12)
        self.assertEqual(out, "H" * 10 + "L" * 2)  # high-priority layer intact

    def test_hard_layer_never_shrunk(self) -> None:
        layers = [
            Layer(name="hard", text="H" * 20, priority=1, hard=True),
            Layer(name="soft", text="S" * 20, priority=9),
        ]
        out = assemble(layers, budget_tokens=25, token_counter=len)
        self.assertEqual(out.count("H"), 20)  # hard intact despite low priority
        self.assertEqual(out.count("S"), 5)   # soft shrunk despite high priority
        self.assertLessEqual(len(out), 25)

    def test_max_chars_cap_applied_before_budget(self) -> None:
        layers = [Layer(name="k", text="Z" * 100, priority=1, max_chars=10)]
        out = assemble(layers, budget_tokens=1000, token_counter=len)
        self.assertEqual(out, "Z" * 10)

    def test_min_chars_floor_respected(self) -> None:
        layers = [
            Layer(name="hard", text="H" * 30, priority=1, hard=True),
            Layer(name="soft", text="S" * 20, priority=9, min_chars=8),
        ]
        # budget impossible to meet without violating the floor; soft floors at 8.
        out = assemble(layers, budget_tokens=5, token_counter=len)
        self.assertEqual(out.count("H"), 30)
        self.assertEqual(out.count("S"), 8)

    def test_deterministic(self) -> None:
        def build():
            return [Layer(name=f"l{i}", text="X" * 10, priority=i) for i in range(5)]

        a = assemble(build(), budget_tokens=20, token_counter=len)
        b = assemble(build(), budget_tokens=20, token_counter=len)
        self.assertEqual(a, b)

    def test_huge_input_stays_within_budget(self) -> None:
        layers = [Layer(name="k", text="Z" * 100_000, priority=1)]
        out = assemble(layers, budget_tokens=500, token_counter=len)
        self.assertLessEqual(len(out), 500)

    def test_real_tiktoken_counter_converges_within_budget(self) -> None:
        # token != char under a real tokenizer; the convergence heuristic must
        # still terminate and land under budget.
        tc = token_counter_for("gpt-4")
        layers = [Layer(name="kb", text="中文剧透内容。" * 5000, priority=1)]
        out = assemble(layers, budget_tokens=500, token_counter=tc)
        self.assertLessEqual(tc(out), 500)

    def test_empty_layers_returns_empty(self) -> None:
        self.assertEqual(assemble([], budget_tokens=10, token_counter=len), "")

    def test_negative_budget_returns_empty(self) -> None:
        layers = [Layer(name="a", text="AAAA", priority=1)]
        self.assertEqual(assemble(layers, budget_tokens=-5, token_counter=len), "")

    def test_all_hard_over_budget_returns_full_best_effort(self) -> None:
        layers = [
            Layer(name="h1", text="H" * 10, priority=1, hard=True),
            Layer(name="h2", text="G" * 10, priority=2, hard=True),
        ]
        out = assemble(layers, budget_tokens=5, token_counter=len)
        self.assertEqual(out, "H" * 10 + "G" * 10)  # hard layers never shrunk


class CountTokensParityTests(unittest.TestCase):
    def test_count_tokens_delegation_wiring(self) -> None:
        # After 047a the client delegates to count_tokens, so this pins the
        # WIRING (self.model threaded through), not the semantics.
        client = LLMClient("default")
        for sample in ["", "hello world", "你好，世界。", "x" * 1234]:
            self.assertEqual(
                count_tokens(sample, client.model),
                client._count_tokens(sample),
                f"wiring mismatch for {sample[:20]!r}",
            )

    def test_count_tokens_matches_frozen_oracle(self) -> None:
        # Freeze the historical _count_tokens contract so a future drift in
        # count_tokens (e.g. changed estimate ratio / fallback encoding) fails.
        def oracle(text: str, model: str):
            if not text:
                return 0, "tiktoken"
            try:
                import tiktoken

                try:
                    enc = tiktoken.encoding_for_model(str(model))
                except Exception:
                    enc = tiktoken.get_encoding("cl100k_base")
                return len(enc.encode(text)), "tiktoken"
            except Exception:
                return math.ceil(len(text) / 1.6), "estimate"

        for sample in ["", "hello world", "你好，世界。续写。", "x" * 777]:
            for model in ("", "gpt-4", "openai/gpt-5.5-high"):
                self.assertEqual(count_tokens(sample, model), oracle(sample, model))

    def test_empty_text_is_zero_tiktoken(self) -> None:
        self.assertEqual(count_tokens("", "any-model"), (0, "tiktoken"))

    def test_estimate_branch_when_tiktoken_unavailable(self) -> None:
        # Force the except branch (all tiktoken lookups fail) -> char estimate.
        import tiktoken

        with patch.object(tiktoken, "encoding_for_model", side_effect=Exception), patch.object(
            tiktoken, "get_encoding", side_effect=Exception
        ):
            self.assertEqual(count_tokens("hello", "m"), (math.ceil(5 / 1.6), "estimate"))


class HelperTests(unittest.TestCase):
    def test_token_counter_for_returns_int_callable(self) -> None:
        tc = token_counter_for("")
        self.assertIsInstance(tc("abc"), int)
        self.assertGreaterEqual(tc("abc"), 1)

    def test_budget_for_task_positive_and_under_redline(self) -> None:
        from src.config import get_model_config

        cfg = get_model_config("write")
        budget = budget_for_task("write")
        self.assertGreater(budget, 0)
        self.assertLessEqual(
            budget,
            int(cfg.get("context_limit", 128000) * 0.9) - int(cfg.get("max_tokens", 2000)),
        )


if __name__ == "__main__":
    unittest.main()
