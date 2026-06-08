"""iter 047a: deterministic, stdlib-only layered token-budget assembler.

Shared keystone for 047b/c/d. Today writer/planner assemble prompt context
with scattered hardcoded truncations (e.g. ``knowledge[:9000]``); this module
replaces that with priority-aware, budgeted assembly:

* ``Layer`` describes one context block + how it may be shrunk.
* ``assemble`` keeps the input order, and when over budget shrinks the
  lowest-priority non-``hard`` layers first until under ``budget_tokens``.
* When the budget is loose, output is the verbatim concatenation of the layer
  texts — so swapping a current ad-hoc ``"".join(...)`` for ``assemble`` is
  byte-identical until a budget actually binds.

The module is pure: no LLM calls, no I/O, deterministic. Token counting lives
here as a free function (``count_tokens``) so context assembly has zero
dependency on ``LLMClient``; the client delegates here to keep one source of
truth (and identical logged token counts).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple


@dataclass
class Layer:
    """One prompt-context block competing for the token budget.

    ``priority`` higher = more important (shrunk last). ``min_chars`` is the
    floor a layer may be shrunk to (default 0 = may be cut entirely).
    ``max_chars`` is a static, budget-independent cap applied first.
    ``hard`` layers are never shrunk or dropped.
    """

    name: str
    text: str
    priority: int
    min_chars: int = 0
    max_chars: Optional[int] = None
    hard: bool = False


def count_tokens(text: str, model: str = "") -> Tuple[int, str]:
    """Return ``(tokens, method)`` — single source of truth for token counting.

    Mirrors the historical ``LLMClient._count_tokens`` exactly so the client can
    delegate here without changing any logged count: empty -> ``(0, "tiktoken")``;
    tiktoken available -> ``(len(encode), "tiktoken")``; otherwise a char
    estimate -> ``(ceil(len/1.6), "estimate")``.
    """

    if not text:
        return 0, "tiktoken"
    try:
        import tiktoken  # type: ignore

        try:
            encoding = tiktoken.encoding_for_model(str(model))
        except Exception:
            encoding = tiktoken.get_encoding("cl100k_base")
        return len(encoding.encode(text)), "tiktoken"
    except Exception:
        return math.ceil(len(text) / 1.6), "estimate"


def token_counter_for(model: str = "") -> Callable[[str], int]:
    """A ``Callable[[str], int]`` suitable for ``assemble(token_counter=...)``."""

    return lambda text: count_tokens(text, model)[0]


def budget_for_task(task: str = "write", *, margin_tokens: int = 0) -> int:
    """Prompt-token budget that stays under ``LLMClient._check_context``'s
    ``context_limit * 0.9`` redline: ``int(limit*0.9) - max_tokens - margin``.
    """

    from .config import get_model_config

    cfg = get_model_config(task)
    context_limit = int(cfg.get("context_limit", 128000))
    max_tokens = int(cfg.get("max_tokens", 2000))
    return max(0, int(context_limit * 0.9) - max_tokens - int(margin_tokens))


def assemble(
    layers: List[Layer],
    *,
    budget_tokens: int,
    token_counter: Callable[[str], int],
) -> str:
    """Assemble ``layers`` into one string within ``budget_tokens``.

    - Output order == input order (priority only decides *what* to shrink).
    - Budget loose => verbatim concatenation (== naive ``"".join`` after any
      static ``max_chars`` caps).
    - ``hard`` layers are never shrunk or dropped.
    - Lowest-priority non-hard layers shrink first (tie -> later layer first).
    - Deterministic: same input => same output.
    """

    # Static, budget-independent caps first.
    texts: List[str] = []
    for layer in layers:
        text = layer.text or ""
        if layer.max_chars is not None and len(text) > layer.max_chars:
            text = text[: layer.max_chars]
        texts.append(text)

    def joined() -> str:
        return "".join(texts)

    guard = 0
    while True:
        cur = token_counter(joined())  # one count per iteration (hot path)
        if cur <= budget_tokens:
            break
        guard += 1
        if guard > 100_000:  # pathological safety net; never expected
            break
        candidates = [
            i
            for i, layer in enumerate(layers)
            if not layer.hard and len(texts[i]) > layer.min_chars
        ]
        if not candidates:
            break  # only hard / floored layers remain — return best effort
        # lowest priority first; tie -> later index first (deterministic)
        idx = min(candidates, key=lambda k: (layers[k].priority, -k))
        over = cur - budget_tokens
        layer_tokens = max(1, token_counter(texts[idx]))
        layer_chars = len(texts[idx])
        cut_chars = max(1, math.ceil(over * layer_chars / layer_tokens))
        new_len = max(layers[idx].min_chars, layer_chars - cut_chars)
        # cut_chars >= 1 already guarantees forward progress; this clamp is a
        # defensive guard kept only in case the heuristic above changes.
        if new_len >= layer_chars:
            new_len = max(layers[idx].min_chars, layer_chars - 1)
        texts[idx] = texts[idx][:new_len]
    return joined()
