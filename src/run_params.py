"""iter064 #1: single source of truth for run-parameter validation, shared by
the WebUI (``src/web/routes.py`` / ``wizard.py``) and the CLI/driver
(``main.py`` / ``src/book_driver.py``).

Before iter064 the numeric caps + finite guards lived ONLY in
``src/web/routes.py`` (``_int_value`` / ``_float_param`` /
``_validate_write_book_params``; iter058 #6b, iter059 #6a, iter063 ③). The CLI
used raw argparse ``type=int`` / ``type=float`` with no validation, so:

  * ``main.py write-book --chapters 999999999`` reached
    ``book_runner.run_write_book`` -> ``list(range(...))`` and tried to
    materialize ~1e9 ints (OOM); and
  * ``--budget-cny nan`` (argparse ``type=float`` accepts ``"nan"``/``"inf"``)
    silently disabled the cost gate, because ``current_cost > nan`` is always
    False (IEEE-754).

This module hoists the caps + validators to the core level (imports only
``math`` / ``typing`` — no web dependency, mirroring ``src/readiness_catalog.py``)
so the WebUI and the CLI/driver enforce identical rules and can never drift
again. The Web helpers (``routes._int_value`` etc.) are kept as thin wrappers
over the functions here so their existing call sites and the finite-guard
regression tests (``tests/test_int_finite_guard.py`` /
``tests/test_float_finite_guard.py``) stay byte-for-byte green.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Mapping, Optional, Sequence, Tuple

# ---------------------------------------------------------------------------
# Canonical cap tables. ``(default, minimum, maximum)``; ``maximum=None`` means
# unbounded above. Caps are well above any real run — they exist only to make
# resource-exhaustion / non-finite inputs unreachable at the boundary.
# ---------------------------------------------------------------------------
INT_CAPS: Dict[str, Tuple[int, int, Optional[int]]] = {
    "chapters": (1, 1, 2000),
    "resume_from": (1, 1, 10000),
    "max_retries": (2, 0, 20),
    "replan_every": (0, 0, 2000),
    "target_chapters": (5, 1, 200),
    "append_count": (0, 0, 2000),
    "from_chapter": (0, 0, 10000),
    "segment_size": (5, 1, 2000),
    "plan_target": (0, 0, 2000),
}

FLOAT_CAPS: Dict[str, Tuple[float, float, Optional[float]]] = {
    "budget_cny": (0.0, 0.0, None),
    "min_confidence": (0.7, 0.0, 1.0),
    "timeout_minutes": (0.0, 0.0, 1440.0),
}

# The integer fields the WebUI write-book validator caps. Kept here so
# ``routes._validate_write_book_params`` and the CLI read the SAME numbers.
WRITE_BOOK_INT_FIELDS: Tuple[str, ...] = (
    "chapters",
    "resume_from",
    "max_retries",
    "replan_every",
)


def validate_int(
    value: Any,
    key: str,
    *,
    minimum: int = 0,
    maximum: Optional[int] = None,
) -> Tuple[Optional[str], int]:
    """Exact port of the former ``routes._int_value``.

    Rejects a non-finite native float (``Infinity``/``NaN`` arriving as a JSON
    literal) before ``int()`` — ``int(float('inf'))`` raises ``OverflowError``,
    ``int(float('nan'))`` raises ``ValueError``. Returns ``(error, 0)`` on any
    failure; callers gate on ``error`` and never consume the 0.
    """
    if isinstance(value, float) and not math.isfinite(value):
        return f"{key} must be a finite integer", 0
    try:
        out = int(value)
    except (TypeError, ValueError, OverflowError):
        return f"{key} must be an integer", 0
    if out < minimum:
        return f"{key} must be >= {minimum}", 0
    if maximum is not None and out > maximum:
        return f"{key} must be <= {maximum}", 0
    return None, out


def validate_float(
    value: Any,
    key: str,
    default: float = 0.0,
    *,
    minimum: float = 0.0,
    maximum: Optional[float] = None,
    allow_blank: bool = False,
) -> Tuple[Optional[str], float]:
    """Unify the former ``routes._float_param`` and ``wizard._optional_float``.

    ``allow_blank=True`` (wizard semantics) treats ``None``/``""`` as "use the
    default" rather than an error. The ``math.isfinite`` guard rejects
    NaN/±Infinity, which otherwise pass every ``<``/``>`` comparison (IEEE-754)
    and would silently disable the downstream cost / timeout gates (iter058
    #6b). Returns ``float(default)`` as the throwaway value on error.
    """
    if allow_blank and (value is None or value == ""):
        return None, float(default)
    try:
        out = float(value)
    except (TypeError, ValueError):
        return f"{key} must be a number", float(default)
    if not math.isfinite(out):
        return f"{key} must be a finite number", float(default)
    if out < minimum:
        return f"{key} must be >= {minimum}", float(default)
    if maximum is not None and out > maximum:
        return f"{key} must be <= {maximum}", float(default)
    return None, out


def validate_run_params(
    raw: Mapping[str, Any],
    *,
    fields: Sequence[str],
) -> Tuple[Optional[str], Dict[str, Any]]:
    """Validate a subset of run params against the canonical cap tables.

    ``fields`` names the keys to check (each must be in ``INT_CAPS`` or
    ``FLOAT_CAPS``). Missing keys fall back to the table default. Returns the
    first error (with a cleaned-but-discarded partial dict) or ``(None, out)``
    where ``out`` carries the validated values for the requested fields.

    Used by ``main.py`` (CLI dispatch arms) and ``src/book_driver.py`` so the
    CLI/driver enforce the exact caps the WebUI does. ``timeout_minutes`` blanks
    are allowed (mirrors the wizard) — a 0/absent timeout means "no cap".
    """
    out: Dict[str, Any] = {}
    for key in fields:
        if key in INT_CAPS:
            default, minimum, maximum = INT_CAPS[key]
            error, value = validate_int(
                raw.get(key, default), key, minimum=minimum, maximum=maximum
            )
        elif key in FLOAT_CAPS:
            default, minimum, maximum = FLOAT_CAPS[key]
            error, value = validate_float(
                raw.get(key, default),
                key,
                default,
                minimum=minimum,
                maximum=maximum,
                allow_blank=True,
            )
        else:  # pragma: no cover - guards against a typo'd field name
            raise KeyError(f"unknown run param: {key}")
        if error:
            return error, out
        out[key] = value
    return None, out
