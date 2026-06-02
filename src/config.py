from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict


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
        max_tokens = _env_int(str(max_tokens_env), int(max_tokens))
    return {
        "model": model,
        "api_key_env": api_key_env,
        "base_url_env": base_url_env_name,
        "api_key": os.getenv(api_key_env) or default.get("api_key"),
        "base_url": (os.getenv(base_url_env_name) if base_url_env_name else None) or default.get("base_url"),
        "temperature": default.get("temperature", 0.2),
        "max_tokens": max_tokens,
        "retry_attempts": int(default.get("retry_attempts", 1)),
        "retry_backoff_seconds": float(default.get("retry_backoff_seconds", 0.5)),
        "json_repair": _env_bool("JSON_REPAIR", bool(default.get("json_repair", True))),
        "context_limit": int(context_limit),
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


def _running_under_unittest_discover() -> bool:
    if "unittest" not in sys.modules:
        return False
    return any(arg == "discover" or "unittest" in arg for arg in sys.argv)
