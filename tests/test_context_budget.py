"""iter 047a: tests for the layered token-budget assembler.

Uses ``token_counter=len`` (1 char == 1 token) so budgets and shrink results
are exactly assertable. Also pins that the extracted ``count_tokens`` free
function matches ``LLMClient._count_tokens`` byte-for-byte (zero regression).
"""

from __future__ import annotations

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

    def test_mock_never_initializes_tiktoken(self) -> None:
        import tiktoken

        with patch.object(
            tiktoken, "encoding_for_model", side_effect=AssertionError("mock touched tiktoken")
        ), patch.object(
            tiktoken, "get_encoding", side_effect=AssertionError("mock touched tiktoken")
        ):
            self.assertEqual(
                count_tokens("offline mock prompt", "mock"),
                (math.ceil(len("offline mock prompt") / 1.6), "estimate"),
            )


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


class Iter078CjkCapTests(unittest.TestCase):
    """iter078 P1-3：deepseek 前缀的 CJK min-cap 修正。

    cl100k_base 对中文虚高 1.5-2×；修正 = min(tiktoken_raw, cjk*0.75+other*0.4)。
    结构不变式：修正只减不增（永不高于旧值 → 不引入「虚低致真溢出」）；
    mock/gpt/claude 路径逐字节不变。"""

    @staticmethod
    def _tiktoken_available() -> bool:
        try:
            import tiktoken  # noqa: F401

            return True
        except Exception:
            return False

    def test_deepseek_chinese_capped_below_raw(self) -> None:
        if not self._tiktoken_available():
            self.skipTest("tiktoken unavailable")
        text = "龙族少年在雨夜里沉默地走过长街，霓虹倒映在他的眼底。" * 40
        raw, raw_method = count_tokens(text, "")
        capped, method = count_tokens(text, "deepseek/deepseek-chat")
        self.assertEqual(raw_method, "tiktoken")
        self.assertLess(capped, raw, "中文文本必须被修正到 raw 以下")
        self.assertEqual(method, "tiktoken_cjk_capped")

    def test_min_cap_invariant_never_exceeds_raw(self) -> None:
        if not self._tiktoken_available():
            self.skipTest("tiktoken unavailable")
        samples = [
            "hello world, plain ascii only " * 30,
            "中英 mixed 混排 text 各占 half 一半 " * 30,
            "标点。！？；：、（）《》" * 50,
            "龙族" * 500,
        ]
        for text in samples:
            with self.subTest(text=text[:20]):
                raw, _ = count_tokens(text, "")
                capped, _ = count_tokens(text, "deepseek/deepseek-chat")
                self.assertLessEqual(capped, raw)

    def test_english_under_deepseek_keeps_raw(self) -> None:
        if not self._tiktoken_available():
            self.skipTest("tiktoken unavailable")
        text = "the quick brown fox jumps over the lazy dog " * 20
        raw, _ = count_tokens(text, "")
        capped, method = count_tokens(text, "deepseek/deepseek-chat")
        # 英文的估算（0.4/字符）高于 tiktoken 实际 → cap 不生效，raw 原样
        self.assertEqual(capped, raw)
        self.assertEqual(method, "tiktoken")

    def test_mock_estimates_and_other_models_never_capped(self) -> None:
        text = "龙族少年在雨夜里沉默地走过长街。" * 20
        base = count_tokens(text, "")
        # Iter096: mock deliberately bypasses tiktoken for strict offline
        # operation.  Real non-DeepSeek models keep their historical tokenizer
        # behavior; none may enter the DeepSeek-only CJK cap branch.
        self.assertEqual(count_tokens(text, "mock"), (math.ceil(len(text) / 1.6), "estimate"))
        self.assertEqual(count_tokens(text, "claude-3"), base)
        for model in ("mock", "gpt-4o", "claude-3"):
            with self.subTest(model=model, check="method"):
                self.assertNotEqual(count_tokens(text, model)[1], "tiktoken_cjk_capped")

    def test_openrouter_deepseek_prefix_also_capped(self) -> None:
        if not self._tiktoken_available():
            self.skipTest("tiktoken unavailable")
        text = "龙族少年在雨夜里沉默地走过长街。" * 40
        self.assertEqual(
            count_tokens(text, "openrouter/deepseek/deepseek-chat"),
            count_tokens(text, "deepseek/deepseek-chat"),
        )


class Iter078ContextCapTests(unittest.TestCase):
    """iter078 P1-3：已知模型 context_limit 物理上限封顶（config 层）。

    unittest 下 load_dotenv_if_available 每次强制 mock（铁律③硬门），测
    clamp 分支需把它 patch 成 no-op——本测试只走 config 解析，零 LLM 构造
    零网络。"""

    _CFG = {
        "default": {"model": "mock", "context_limit": 128000, "max_tokens": 2000},
        "tasks": {
            "write": {"context_limit": 128000, "max_tokens": 8000},
            "plot_planner": {"model": "openai/gpt-5.5", "context_limit": 200000},
        },
    }

    def _config_for(self, task: str, env_model: str, cfg_dict: dict | None = None) -> dict:
        import os

        from src import config as config_mod

        payload = cfg_dict or self._CFG
        with patch.object(config_mod, "load_dotenv_if_available", lambda: None), patch.object(
            config_mod, "load_config", lambda name: dict(payload) if name == "models.yaml" else {}
        ), patch.dict(os.environ, {"OPENAI_MODEL": env_model}, clear=False):
            return config_mod.get_model_config(task)

    def test_deepseek_clamped_to_64k(self) -> None:
        cfg = self._config_for("write", "deepseek/deepseek-chat")
        self.assertEqual(cfg["model"], "deepseek/deepseek-chat")
        self.assertEqual(cfg["context_limit"], 64000)

    def test_unknown_model_yaml_value_untouched(self) -> None:
        cfg = self._config_for("plot_planner", "deepseek/deepseek-chat")
        # task 块显式 model=gpt-5.5（未知前缀）→ 200000 原样生效
        self.assertEqual(cfg["model"], "openai/gpt-5.5")
        self.assertEqual(cfg["context_limit"], 200000)

    def test_mock_never_clamped(self) -> None:
        cfg = self._config_for("write", "mock")
        self.assertEqual(cfg["model"], "mock")
        self.assertEqual(cfg["context_limit"], 128000)

    def test_conservative_config_below_cap_kept(self) -> None:
        cfg = self._config_for(
            "write",
            "deepseek/deepseek-chat",
            cfg_dict={
                "default": {"model": "mock", "context_limit": 128000},
                "tasks": {"write": {"context_limit": 32000}},
            },
        )
        self.assertEqual(cfg["context_limit"], 32000)


if __name__ == "__main__":
    unittest.main()
