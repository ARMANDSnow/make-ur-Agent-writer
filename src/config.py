from __future__ import annotations

import json
import os
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
            import yaml  # type: ignore

            loaded = yaml.safe_load(text)
            return loaded or {}
        except Exception as exc:
            raise ValueError(f"Cannot parse config file {path}: {exc}") from exc


def load_config(name: str) -> Dict[str, Any]:
    path = ROOT / "config" / name
    if not path.exists():
        return {}
    return load_structured_config(path)


def get_model_config(task: str = "default") -> Dict[str, Any]:
    load_dotenv_if_available()
    cfg = load_config("models.yaml")
    default = dict(cfg.get("default", {}))
    task_cfg = dict(cfg.get("tasks", {}).get(task, {}))
    default.update(task_cfg)
    model = os.getenv("OPENAI_MODEL") or default.get("model") or "mock"
    context_limit = task_cfg.get("context_limit", default.get("context_limit"))
    if context_limit is None:
        context_limit = _default_context_limit(str(model))
    return {
        "model": model,
        "api_key": os.getenv("OPENAI_API_KEY") or default.get("api_key"),
        "base_url": os.getenv("OPENAI_BASE_URL") or default.get("base_url"),
        "temperature": default.get("temperature", 0.2),
        "max_tokens": default.get("max_tokens", 2000),
        "retry_attempts": int(default.get("retry_attempts", 1)),
        "retry_backoff_seconds": float(default.get("retry_backoff_seconds", 0.5)),
        "json_repair": bool(default.get("json_repair", True)),
        "context_limit": int(context_limit),
        "cache_enabled": bool(default.get("cache_enabled", False)),
        **{key: value for key, value in task_cfg.items() if key not in {"api_key", "base_url", "model"}},
    }


def _default_context_limit(model: str) -> int:
    lower = model.lower()
    for prefix, limit in DEFAULT_CONTEXT_LIMITS.items():
        if lower.startswith(prefix) or prefix in lower:
            return limit
    return 128000
