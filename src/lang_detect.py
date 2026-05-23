"""Iter 018: lightweight script language detection.

Used by the splitter / normalizer / EPUB importer to decide whether to apply
Chinese chapter-heading rules (``zh``) or English ones (``en``) when no
explicit language is provided.

Heuristic only — no model lookups, no external dependencies. The decision
boundary is biased toward ``zh`` because the project's first three years
of pipelines (iter 014-017) were Chinese-only and we want any text with a
meaningful Chinese signal to keep using the existing path.
"""

from __future__ import annotations

CJK_START = 0x4E00
CJK_END = 0x9FFF

DEFAULT_SAMPLE_CHARS = 4000
DEFAULT_THRESHOLD = 0.30


def detect_language(text: str, sample_chars: int = DEFAULT_SAMPLE_CHARS,
                    threshold: float = DEFAULT_THRESHOLD) -> str:
    """Return ``'zh'`` or ``'en'`` based on the first ``sample_chars``.

    Counts CJK Unified Ideographs (U+4E00–U+9FFF) versus ASCII letters and
    returns ``'zh'`` when CJK / (CJK + ASCII letters) >= ``threshold``.
    Otherwise returns ``'en'``. Empty / whitespace-only / numeric-only
    samples fall through to ``'en'`` — those are degenerate inputs and
    the English path is the safer default (English splitter accepts a
    superset of conventional heading formats; Chinese splitter rejects
    everything that doesn't match ``第N章 / 楔子`` etc.).
    """

    if not text:
        return "en"
    sample = text[:sample_chars]
    cjk = 0
    ascii_letters = 0
    for ch in sample:
        codepoint = ord(ch)
        if CJK_START <= codepoint <= CJK_END:
            cjk += 1
        elif ch.isascii() and ch.isalpha():
            ascii_letters += 1
    total = cjk + ascii_letters
    if total == 0:
        return "en"
    return "zh" if (cjk / total) >= threshold else "en"
