from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONTEXT_LIMITS = {
    "mock": 128000,
    "gpt-4o": 128000,
    "gpt-4.1": 1047576,
    "deepseek": 64000,
    "claude": 200000,
}


def load_dotenv_if_available() -> None:
    if _running_under_unittest_discover():
        os.environ["OPENAI_MODEL"] = "mock"
        for key in RUNTIME_ENV_KEYS:
            os.environ.pop(key, None)
        return
    try:
        from dotenv import load_dotenv

        load_dotenv(ROOT / ".env")
    except Exception:
        return


def load_structured_config(path: Path) -> Dict[str, Any]:
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        try:
            return json.loads(_escape_control_chars_in_json_strings(text))
        except json.JSONDecodeError:
            pass
        try:
            import yaml  # type: ignore

            loaded = yaml.safe_load(text)
            return loaded or {}
        except Exception as exc:
            raise ValueError(f"Cannot parse config file {path}: {exc}") from exc


def _escape_control_chars_in_json_strings(text: str) -> str:
    out: list[str] = []
    in_string = False
    escaped = False
    for ch in text:
        if in_string:
            if escaped:
                out.append(ch)
                escaped = False
            elif ch == "\\":
                out.append(ch)
                escaped = True
            elif ch == '"':
                out.append(ch)
                in_string = False
            elif ch == "\n":
                out.append("\\n")
            elif ch == "\r":
                out.append("\\r")
            elif ch == "\t":
                out.append("\\t")
            else:
                out.append(ch)
        else:
            out.append(ch)
            if ch == '"':
                in_string = True
    return "".join(out)


def load_config(name: str) -> Dict[str, Any]:
    path = ROOT / "config" / name
    if not path.exists():
        return {}
    return load_structured_config(path)


def get_model_config(task: str = "default") -> Dict[str, Any]:
    load_dotenv_if_available()
    cfg = load_config("models.yaml")
    default_cfg = dict(cfg.get("default", {}))
    default = dict(default_cfg)
    task_cfg = dict(cfg.get("tasks", {}).get(task, {}))
    default.update(task_cfg)
    env_model = os.getenv("OPENAI_MODEL")
    default_model = str(default_cfg.get("model") or "mock")
    model_env = task_cfg.get("model_env")
    if (env_model and env_model.lower().startswith("mock")) or (
        not env_model and default_model.lower().startswith("mock")
    ):
        model = "mock"
    elif model_env and os.getenv(str(model_env)):
        model = os.getenv(str(model_env))
    elif task_cfg.get("model"):
        model = task_cfg.get("model")
    else:
        model = env_model or default.get("model") or "mock"
    api_key_env = str(task_cfg.get("api_key_env") or default_cfg.get("api_key_env") or "OPENAI_API_KEY")
    base_url_env = task_cfg.get("base_url_env", default_cfg.get("base_url_env", "OPENAI_BASE_URL"))
    base_url_env_name = str(base_url_env) if base_url_env else ""
    context_limit = task_cfg.get("context_limit", default.get("context_limit"))
    if context_limit is None:
        context_limit = _default_context_limit(str(model))
    max_tokens = default.get("max_tokens", 2000)
    max_tokens_env = task_cfg.get("max_tokens_env")
    if max_tokens_env and os.getenv(str(max_tokens_env)):
        # iter 051b (F3): a non-numeric config max_tokens must not crash the
        # env-override path either (the env value itself is already guarded
        # by _env_int).
        max_tokens = _env_int(str(max_tokens_env), _safe_int(max_tokens, 2000))
    return {
        "model": model,
        "api_key_env": api_key_env,
        "base_url_env": base_url_env_name,
        "api_key": os.getenv(api_key_env) or default.get("api_key"),
        "base_url": (os.getenv(base_url_env_name) if base_url_env_name else None) or default.get("base_url"),
        "temperature": default.get("temperature", 0.2),
        "max_tokens": max_tokens,
        # iter 051b (F3): models.yaml is hand-edited — a non-numeric value here
        # used to crash get_model_config (and with it every pipeline step that
        # builds an LLMClient). Degrade to the documented defaults instead.
        "retry_attempts": _safe_int(default.get("retry_attempts", 1), 1),
        "retry_backoff_seconds": _safe_float(default.get("retry_backoff_seconds", 0.5), 0.5),
        # iter055 轨A: per-call timeout. 显式映射而非靠 :140-144 透传 —— 那段只透传
        # task_cfg 的 key，default 块的 request_timeout 不会进 self.config（会让超时
        # 静默失效）。因 default.update(task_cfg)，task 块可覆盖 default（分任务超时:
        # extract/review 120 · write 240 · plot_planner 300）。0 = 关闭（字节兼容旧行为）。
        # LLM_REQUEST_TIMEOUT env 优先，便于实跑现场快速调旋钮。
        "request_timeout": _env_float(
            "LLM_REQUEST_TIMEOUT", _safe_float(default.get("request_timeout", 0), 0)
        ),
        "json_repair": _env_bool("JSON_REPAIR", bool(default.get("json_repair", True))),
        "context_limit": _safe_int(context_limit, _default_context_limit(str(model))),
        "cache_enabled": _env_bool("DISABLE_PROMPT_CACHE", False) is False
        and bool(default.get("cache_enabled", False)),
        **{
            key: value
            for key, value in task_cfg.items()
            if key not in {"api_key", "base_url", "model", "max_tokens"}
        },
    }


def _default_context_limit(model: str) -> int:
    lower = model.lower()
    for prefix, limit in DEFAULT_CONTEXT_LIMITS.items():
        if lower.startswith(prefix) or prefix in lower:
            return limit
    return 128000


RUNTIME_ENV_KEYS = (
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "PLANNER_API_KEY",
    "PLANNER_BASE_URL",
    "PLANNER_MODEL",
)


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or str(value).strip() == "":
        return default
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


def _env_choice(name: str, choices: set[str], default: str) -> str:
    value = str(os.getenv(name) or "").strip().lower()
    return value if value in choices else default


def _env_float(name: str, default: float) -> float:
    # iter 051b (F8): float twin of _env_int — unset/blank/garbage env values
    # fall back to the default instead of raising at the call site.
    value = os.getenv(name)
    if value is None or str(value).strip() == "":
        return default
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def _safe_int(value: Any, default: int) -> int:
    # iter 051b (F3): coercion guard for hand-edited config values — keep the
    # documented default instead of crashing on garbage.
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float) -> float:
    # iter 051b (F3): float twin of _safe_int.
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_budget_cny(raw: Any) -> Optional[float]:
    """iter 051b: validation core for budget-cap values — the single source
    of truth for the iter 050 L-3 rules. Returns the parsed cap, or ``None``
    when ``raw`` is unusable: non-numeric, nan (compares False with
    everything, so a nan cap would never trip the gate), inf, or negative.
    ``0.0`` is a VALID return — it means "explicitly uncapped" (CLI
    semantics), which is why callers must distinguish None from 0.0."""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return value


def budget_cny_from_env(env_name: str, fallback: float) -> float:
    """iter 051b: shared env→budget resolver for ``NOVEL_DEFAULT_BUDGET_CNY``
    (write-book, fallback 10.0) and ``NOVEL_REVIEW_BUDGET_CNY``
    (review-chapter, fallback 5.0). Unset/empty, non-numeric, or
    nan/inf/negative values all degrade to ``fallback`` — never to "no cap" —
    so a typo'd env can't silently remove the spend guard. An explicit ``0``
    in the env IS honored (0.0 = uncapped, same as an explicit param)."""
    raw = os.environ.get(env_name, "")
    if not raw:
        return fallback
    value = parse_budget_cny(raw)
    return fallback if value is None else value


def _running_under_unittest_discover() -> bool:
    # iter047B2 M9: pytest is also a test runner — treat it like unittest so .env
    # (real model + OPENAI_STREAM) is scrubbed and tests stay mock-isolated no
    # matter which runner launched them. canonical `unittest discover` is
    # unaffected (pytest is not imported there).
    if "pytest" in sys.modules:
        return True
    if "unittest" not in sys.modules:
        return False
    return any(arg == "discover" or "unittest" in arg for arg in sys.argv)
