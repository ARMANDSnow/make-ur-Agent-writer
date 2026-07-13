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
LITELLM_LOCAL_MODEL_COST_MAP_ENV = "LITELLM_LOCAL_MODEL_COST_MAP"


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


def prepare_litellm_environment() -> bool:
    """Prepare LiteLLM before its first import and return global mock mode.

    LiteLLM fetches its public model-cost map at import time unless
    ``LITELLM_LOCAL_MODEL_COST_MAP=true`` is already present.  The project
    loads ``.env`` lazily, so this guard must resolve the effective global
    model *before* importing LiteLLM: explicit ``OPENAI_MODEL`` wins, then
    the configured default.  Mock is fail-closed and overwrites a conflicting
    inherited/dotenv value; real-model processes retain the caller's existing
    LiteLLM choice and proxy behavior.
    """

    load_dotenv_if_available()
    model_cfg = load_config("models.yaml")
    default_model = str(model_cfg.get("default", {}).get("model") or "mock")
    env_model = os.getenv("OPENAI_MODEL")
    effective_model = env_model or default_model
    is_mock = str(effective_model).lower().startswith("mock")
    if is_mock:
        os.environ[LITELLM_LOCAL_MODEL_COST_MAP_ENV] = "true"
    return is_mock


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
    else:
        # iter078 P1-3: 已知模型物理上限封顶。models.yaml 的 context_limit 是
        # task 级静态值（默认 128000），而运行时 model 由 env 决定——deepseek
        # 实际 64K，配 128K 会让 _check_context 的 0.9 红线永不触发、真溢出
        # 直接打到 provider（RTE + 重试空耗）。只对 DEFAULT_CONTEXT_LIMITS
        # 里有把握的前缀做 min 封顶；未知模型（如 gpt-5.5 走 200K 配置）与
        # mock（假模型无物理上限，封顶只会改变 mock 回归行为）不动。
        known_cap = _known_context_cap(str(model))
        if (
            known_cap is not None
            and not str(model).lower().startswith("mock")
            and _safe_int(context_limit, known_cap) > known_cap
        ):
            context_limit = known_cap
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
        # iter055 轨B: 指数退避上限 + 抖动(缺省与 llm_client 代码 fallback 一致,字节兼容)。
        "retry_backoff_cap_seconds": _safe_float(default.get("retry_backoff_cap_seconds", 30), 30),
        "retry_backoff_jitter_seconds": _safe_float(default.get("retry_backoff_jitter_seconds", 1), 1),
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
        # iter055 真模型实测修正: 透传 task 块的"额外"键(rolling_*/chunk_*/stream/model_env
        # 等),但排除所有上面已"显式映射"的标量键 —— 否则原值会覆盖掉显式映射里的 env 优先
        # 逻辑(实测: extract 加 request_timeout 后,这段 spread 用原值压掉 LLM_REQUEST_TIMEOUT
        # 覆盖;同理 cache_enabled 会压掉 DISABLE_PROMPT_CACHE、json_repair 压掉 JSON_REPAIR)。
        **{
            key: value
            for key, value in task_cfg.items()
            if key not in {
                "api_key", "base_url", "model", "max_tokens",
                "request_timeout", "retry_attempts", "retry_backoff_seconds",
                "retry_backoff_cap_seconds", "retry_backoff_jitter_seconds",
                "json_repair", "temperature", "context_limit", "cache_enabled",
            }
        },
    }


def is_mock_mode(task: str = "default") -> bool:
    """iter073: canonical mock detection for client-less callers.

    Resolves the effective model exactly as ``get_model_config`` does (so an
    unset ``OPENAI_MODEL`` with a ``mock`` models.yaml default still reads as
    mock) and checks the ``mock`` prefix — matching ``LLMClient.is_mock``. Use
    this instead of a raw ``os.getenv("OPENAI_MODEL")`` check, which disagrees
    in the env-empty + default-mock case.
    """
    return str(get_model_config(task).get("model") or "").lower().startswith("mock")


def _default_context_limit(model: str) -> int:
    lower = model.lower()
    for prefix, limit in DEFAULT_CONTEXT_LIMITS.items():
        if lower.startswith(prefix) or prefix in lower:
            return limit
    return 128000


def _known_context_cap(model: str) -> int | None:
    """iter078 P1-3: DEFAULT_CONTEXT_LIMITS 中有把握的前缀 → 物理上限；
    未知模型 → None（yaml 配置原样生效，配置者负责）。与
    ``_default_context_limit`` 的区别：后者对未知模型回 128000 兜底，
    不能用来判断「我们是否真的知道这个模型的上限」。"""
    lower = model.lower()
    for prefix, limit in DEFAULT_CONTEXT_LIMITS.items():
        if lower.startswith(prefix) or prefix in lower:
            return limit
    return None


RUNTIME_ENV_KEYS = (
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "PLANNER_API_KEY",
    "PLANNER_BASE_URL",
    "PLANNER_MODEL",
    "AI_DRAW_ENDPOINT",
    "AI_DRAW_BASE_URL",
    "AI_DRAW_MODEL",
    "AI_DRAW_API_KEY",
    "AI_DRAW_RESULT_HOSTS",
    "SD_API_BASE_URL",
    "SD_API_KEY",
    "SD_VIDEO_MODE",
    "SD_VIDEO_MODEL",
    "SD_ASSET_PUBLIC_BASE_URL",
    "SD_VIDEO_RESULT_HOSTS",
    "SD_VIDEO_ESTIMATED_COST_CNY",
    "CONFIRM_REAL_VIDEO_SMOKE",
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
        parsed = float(str(value).strip())
    except (TypeError, ValueError):
        return default
    # iter078 P1-8: float("inf")/float("nan") 解析成功但都是垃圾——inf 让
    # LLM_REQUEST_TIMEOUT 超时静默失效、NaN 会毒化任何数值比较。与
    # unparseable 同款回退（铁律④契约），preflight 另有 WARN 提示。
    # iter078 收官审查修复：负数一并回退。唯一调用点是 LLM_REQUEST_TIMEOUT，
    # 负超时无合法语义，且 preflight 的 WARN 文案承诺「已回退默认值」——此前
    # 负值实际原样透传给 litellm，与文案相反。
    if not math.isfinite(parsed) or parsed < 0:
        return default
    return parsed


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
