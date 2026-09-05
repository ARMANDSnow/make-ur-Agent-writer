from __future__ import annotations

import json
import hashlib
import math
import os
import random
import re
import sys as _sys
import types
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from .config import ROOT
from .config import _env_int, _safe_int, get_model_config, prepare_litellm_environment
from .schemas import model_to_dict
from .safe_errors import safe_exception_type_name, safe_url
from .utils import append_jsonl, extract_json_object


def _sanitize_error_text(error: Any, *, api_key: Optional[str] = None, max_chars: int = 500) -> str:
    """Return metadata only; provider-controlled free text is never retained."""

    if isinstance(error, BaseException):
        error_type = safe_exception_type_name(error)
        reason = public_llm_failure_reason(error)
        text = f"{reason}:{error_type}"
    else:
        text = "generation_failed:non_exception"
    if max_chars > 0 and len(text) > max_chars:
        return text[:max_chars] + "...<truncated>"
    return text


# User proxy configuration is authoritative. The historical local tunnel
# adapter is opt-in and never deletes configuration on a failed probe.
def _setup_proxy() -> None:
    if os.environ.get("DRAGON_RAJA_PROXY_MODE") != "sandbox-63501":
        return
    import socket
    try:
        with socket.create_connection(("localhost", 63501), timeout=0.5):
            pass
    except OSError:
        return
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        os.environ[key] = "http://localhost:63501"
    for key in ("ALL_PROXY", "all_proxy"):
        os.environ.pop(key, None)


# Iter 096: LiteLLM reads its cost-map source during import.  Resolve the
# effective global model first so mock processes force the bundled map and do
# not even probe the localhost proxy.  Real-model processes preserve user proxies unless adaptation is explicitly enabled.
_LITELLM_MOCK_OFFLINE = prepare_litellm_environment()
if not _LITELLM_MOCK_OFFLINE:
    _setup_proxy()


# Iter 027: GPT-5 family rejects ``temperature != 1`` (and a handful of
# other params) with ``UnsupportedParamsError``. The pipeline's tasks
# set custom temperatures per-step (write 0.65, review 0.1, etc.) which
# matter for non-GPT-5 models. Telling litellm to silently drop the
# unsupported params lets us keep the same task config for both model
# families — GPT-5 callers fall back to its single supported
# temperature, everyone else honors the task value.
try:
    import litellm as _litellm

    _litellm.drop_params = True
except Exception:
    def _missing_litellm_completion(**_kwargs: Any) -> Any:
        raise RuntimeError("litellm is required for real model calls")

    _litellm = types.ModuleType("litellm")
    _litellm.drop_params = True
    _litellm.completion = _missing_litellm_completion
    _sys.modules.setdefault("litellm", _litellm)


# Iter 027 bugfix: litellm/__init__.py:20 calls dotenv.load_dotenv() on
# import, which leaks `OPENAI_STREAM=1` from .env into os.environ EVEN
# under unittest. tests/__init__.py also pops it, but `python -m unittest
# discover` does NOT reliably import the tests package — so we also pop
# here, scoped to unittest runs (sys.argv detection mirrors
# src/config.py:_running_under_unittest_discover). Per-test patch.dict()
# of OPENAI_STREAM=1 still wins because LLMClient.__init__ re-reads env.
from urllib.parse import urlparse

if (
    "pytest" in _sys.modules  # iter047B2 M9: scrub under pytest too, not only unittest
    or "unittest" in _sys.modules
    or any("unittest" in str(a) for a in _sys.argv)
):
    os.environ.pop("OPENAI_STREAM", None)


class LLMContextOverflowError(RuntimeError):
    pass


class LLMCallDeadlineExceeded(TimeoutError):
    pass


class LLMRequestLimitExceeded(RuntimeError):
    """Raised before a real provider call would exceed the active job cap."""


class LLMBudgetLimitExceeded(RuntimeError):
    """Raised before a real provider call when known job spend reached its cap."""

    def __init__(self, *, budget_cny: float | None, cost_cny: float) -> None:
        self.budget_cny = budget_cny
        self.cost_cny = cost_cny
        label = "required" if budget_cny is None else f"{budget_cny:g}"
        super().__init__(f"model budget limit exhausted ({cost_cny:g}/{label})")


class LLMPricingUnavailable(RuntimeError):
    """Raised before a paid Web call whose model has no trusted CNY price."""


class LLMAccountingUnavailable(RuntimeError):
    """Raised when paid-call telemetry can no longer enforce the CNY cap."""


class LLMProviderFailure(RuntimeError):
    """Metadata-only terminal wrapper for any provider-controlled failure."""

    def __init__(self, *, reason: str, error_type: str, attempts: int, trace_id: str | None = None) -> None:
        self.reason = reason if re.fullmatch(r"[a-z0-9_]{1,48}", reason) else "generation_failed"
        self.error_type = (
            error_type
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", error_type)
            else "Exception"
        )
        self.attempts = max(1, int(attempts))
        self.trace_id = trace_id if trace_id and re.fullmatch(r"[a-f0-9]{32}", trace_id) else uuid.uuid4().hex
        super().__init__(
            f"{self.reason} (provider_error_type={self.error_type}, "
            f"attempts={self.attempts}, trace_id={self.trace_id})"
        )


class LLMResponseValidationError(RuntimeError):
    """Safe terminal for invalid provider output after bounded repair."""

    def __init__(self, response_model: str, *, repaired: bool) -> None:
        self.reason = "response_validation_failed"
        self.error_type = "ValidationError"
        self.attempts = 1
        self.trace_id = uuid.uuid4().hex
        phase = "after_repair" if repaired else "without_repair"
        super().__init__(
            f"response_validation_failed (model={response_model}, phase={phase}, "
            f"trace_id={self.trace_id})"
        )


def raise_if_terminal_llm_failure(exc: BaseException) -> None:
    """Prevent paid-action terminal/admission failures from being degraded.

    Local parse/schema fallbacks may continue, but submission-unknown,
    deadline and admission failures must end the entire authorized job so no
    later chapter/advisor/repair call is sent under the same intent.
    """

    if isinstance(
        exc,
        (
            LLMProviderFailure,
            LLMResponseValidationError,
            LLMCallDeadlineExceeded,
            LLMRequestLimitExceeded,
            LLMBudgetLimitExceeded,
            LLMPricingUnavailable,
            LLMAccountingUnavailable,
            LLMContextOverflowError,
        ),
    ):
        raise exc


_LLM_DEADLINE: ContextVar[float | None] = ContextVar("llm_deadline", default=None)
# Keep the value immutable.  Contexts copied into concurrent asyncio tasks then
# advance their own counter instead of sharing a mutable list/dict by reference.
# ``None`` as the limit means that a Web job required a limit but did not supply
# one; it is deliberately distinct from no active scope (the ContextVar default).
_LLM_REQUEST_LIMIT: ContextVar[tuple[int | None, int] | None] = ContextVar(
    "llm_request_limit", default=None
)
_LLM_BUDGET_CHECK: ContextVar[tuple[float | None, Any, bool] | None] = ContextVar(
    "llm_budget_check", default=None
)
_LLM_MODEL_CONFIGS: ContextVar[dict[str, Dict[str, Any]] | None] = ContextVar(
    "llm_model_configs", default=None
)
_LLM_ACCOUNTING_DEGRADED: ContextVar[bool | None] = ContextVar(
    "llm_accounting_degraded", default=None
)
MAX_MODEL_REQUESTS_PER_JOB = 160


@contextmanager
def llm_model_config_scope(configs: dict[str, Dict[str, Any]] | None):
    """Freeze resolved per-task model configuration for one admitted job."""

    snapshot = None if configs is None else {
        str(task): dict(config) for task, config in configs.items()
    }
    token = _LLM_MODEL_CONFIGS.set(snapshot)
    try:
        yield
    finally:
        _LLM_MODEL_CONFIGS.reset(token)


def resolved_model_config(task: str) -> Dict[str, Any]:
    """Return the admitted job's frozen config, or the current CLI config.

    Fingerprint and context-budget consumers must use the same snapshot as
    ``LLMClient``; otherwise a settings edit after admission can make output
    from model A look stale against live model B.
    """

    frozen = _LLM_MODEL_CONFIGS.get()
    if frozen is not None and task in frozen:
        return dict(frozen[task])
    return get_model_config(task)


def model_config_scope_active() -> bool:
    return _LLM_MODEL_CONFIGS.get() is not None


def llm_accounting_degraded() -> bool:
    return _LLM_ACCOUNTING_DEGRADED.get() is True


@contextmanager
def llm_deadline_scope(deadline: float | None):
    """Bound every provider attempt in this thread/task to an outer job deadline."""

    token = _LLM_DEADLINE.set(deadline)
    try:
        yield
    finally:
        _LLM_DEADLINE.reset(token)


def _parse_model_request_limit(value: Any, *, required: bool) -> int | None:
    """Validate one job's provider-attempt cap without accepting bool/float.

    An omitted optional scope preserves non-Web/CLI compatibility.  A required
    scope records the missing value and fails immediately before the first real
    provider attempt, while mock completions remain strictly offline and do not
    consume the counter.
    """

    if value is None or value == "":
        if required:
            return None
        return None
    if isinstance(value, bool):
        raise ValueError("max_model_requests must be an integer")
    if isinstance(value, int):
        limit = value
    elif isinstance(value, str) and re.fullmatch(r"[0-9]+", value.strip()):
        limit = int(value.strip())
    else:
        raise ValueError("max_model_requests must be an integer")
    if not 1 <= limit <= MAX_MODEL_REQUESTS_PER_JOB:
        raise ValueError(
            f"max_model_requests must be between 1 and {MAX_MODEL_REQUESTS_PER_JOB}"
        )
    return limit


@contextmanager
def llm_request_limit_scope(max_model_requests: Any, *, required: bool = False):
    """Isolate and bound real provider attempts for one job/task.

    Nested scopes start their own counter and restore the exact outer counter
    on exit.  The immutable ContextVar state also isolates independently copied
    async contexts.  This guards provider *attempts* (including a safe retry or
    JSON repair), not high-level completion calls.
    """

    limit = _parse_model_request_limit(max_model_requests, required=required)
    if limit is None and not required:
        yield
        return
    token = _LLM_REQUEST_LIMIT.set((limit, 0))
    try:
        yield
    finally:
        _LLM_REQUEST_LIMIT.reset(token)


def _claim_model_request(model: str = "", *, reserved_cost_cny: float = 0.0) -> None:
    """Atomically claim the next attempt in the current execution context."""

    if llm_accounting_degraded():
        raise LLMAccountingUnavailable(
            "paid model accounting is unavailable after telemetry failure"
        )
    budget_state = _LLM_BUDGET_CHECK.get()
    if budget_state is not None:
        budget_cny, cost_check, require_known_pricing = budget_state
        if require_known_pricing:
            from .cost_estimator import has_known_model_pricing

            if not has_known_model_pricing(model):
                raise LLMPricingUnavailable(
                    "trusted model pricing is required before a paid Web request"
                )
        if budget_cny is None:
            raise LLMBudgetLimitExceeded(budget_cny=None, cost_cny=0.0)
        known_cost = float(cost_check())
        if not math.isfinite(known_cost) or known_cost < 0:
            raise LLMBudgetLimitExceeded(budget_cny=budget_cny, cost_cny=0.0)
        if known_cost >= budget_cny:
            raise LLMBudgetLimitExceeded(
                budget_cny=budget_cny,
                cost_cny=known_cost,
            )
        reserve = float(reserved_cost_cny)
        if not math.isfinite(reserve) or reserve < 0 or known_cost + reserve > budget_cny:
            raise LLMBudgetLimitExceeded(
                budget_cny=budget_cny,
                cost_cny=known_cost,
            )
    state = _LLM_REQUEST_LIMIT.get()
    if state is None:
        # Standalone/CLI callers retain their existing behavior unless they opt
        # into a scope.  Web novel workers always install a required scope.
        return
    limit, consumed = state
    if limit is None:
        raise LLMRequestLimitExceeded(
            "max_model_requests is required before a real provider attempt"
        )
    if consumed >= limit:
        raise LLMRequestLimitExceeded(
            f"model request limit exhausted ({consumed}/{limit})"
        )
    _LLM_REQUEST_LIMIT.set((limit, consumed + 1))


@contextmanager
def llm_budget_limit_scope(
    budget_cny: Any,
    cost_check: Any,
    *,
    required: bool = False,
    require_known_pricing: bool = False,
):
    """Check known spend immediately before every real provider attempt.

    ``cost_check`` is workspace-scoped and returns cost accumulated since this
    job started.  Mock calls return before the check, preserving strict offline
    tests.  The final settlement remains the worker's responsibility because a
    last successful call can itself cross the cap.
    """

    if budget_cny is None or budget_cny == "":
        parsed = None
    else:
        if isinstance(budget_cny, bool):
            raise ValueError("budget_cny must be a positive finite number")
        try:
            parsed = float(budget_cny)
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError("budget_cny must be a positive finite number") from exc
        if not math.isfinite(parsed) or parsed <= 0:
            raise ValueError("budget_cny must be a positive finite number")
    if parsed is None and not required:
        yield
        return
    token = _LLM_BUDGET_CHECK.set((parsed, cost_check, require_known_pricing))
    accounting_token = _LLM_ACCOUNTING_DEGRADED.set(False)
    try:
        yield
    finally:
        _LLM_ACCOUNTING_DEGRADED.reset(accounting_token)
        _LLM_BUDGET_CHECK.reset(token)


# iter055 轨B: 中转站抖动(Cloudflare Tunnel 530/1033、provider 过载 50x、连接/读取
# 超时)是 transient,应重试;schema/context/JSON 等确定性错立即抛(重试纯浪费且掩盖
# bug,现状空耗 5 次 ≈ 20s)。鸭子判定(类名 + 错误串关键词)而非 isinstance(litellm.X)
# —— litellm 跨版本类名漂移且 requirements 未 pin(R8)。
_TRANSIENT_EXC_NAMES = frozenset(
    {
        "Timeout",
        "APITimeoutError",
        "APIConnectionError",
        "ServiceUnavailableError",
        "RateLimitError",
        "InternalServerError",
    }
)
_TRANSIENT_ERR_MARKERS = (
    "530",
    "1033",
    "502",
    "503",
    "504",
    "timeout",
    "tunnel",
    "cloudflare",
)


def _safe_exception_text_lower(exc: BaseException) -> str:
    try:
        return str(exc).lower()
    except BaseException:
        return ""


def _safe_exception_attr(exc: BaseException, name: str, default: Any = None) -> Any:
    try:
        return getattr(exc, name, default)
    except BaseException:
        return default


def _is_transient(exc: BaseException) -> bool:
    if isinstance(exc, (LLMContextOverflowError, LLMCallDeadlineExceeded)):
        return False
    # stdlib 连接/超时(含 ConnectionReset/Aborted/BrokenPipe 等子类、socket.timeout)
    # 稳定类型,用 isinstance 兜住 —— 流式中途断流即走这里。
    if isinstance(exc, (ConnectionError, TimeoutError)):
        return True
    if safe_exception_type_name(exc) in _TRANSIENT_EXC_NAMES:
        return True
    text = _safe_exception_text_lower(exc)
    return any(marker in text for marker in _TRANSIENT_ERR_MARKERS)


def _is_submission_unknown(exc: BaseException) -> bool:
    """Whether a transport failure may have happened after submission."""

    if _safe_exception_attr(exc, "request_not_sent", False) is True:
        return False
    name = safe_exception_type_name(exc).lower()
    text = _safe_exception_text_lower(exc)
    return (
        isinstance(exc, (TimeoutError, ConnectionError))
        or "timeout" in name
        or "connection" in name
        or "stream" in name
        or any(
            marker in text
            for marker in (
                "timed out",
                "timeout",
                "connection reset",
                "connection aborted",
                "broken pipe",
                "mid-stream",
                "stream closed",
            )
        )
    )


def _is_safe_to_retry(exc: BaseException) -> bool:
    """Retry only a transient attempt with a definitive non-submission result."""

    if not _is_transient(exc):
        return False
    return _safe_exception_attr(exc, "request_not_sent", False) is True


def public_llm_failure_reason(exc: BaseException) -> str:
    """Return a bounded, credential-free reason for user-facing job state.

    Provider exceptions routinely embed upstream URLs, request metadata, or
    echoed payload fragments, so callers must never project ``str(exc)`` into
    the Web job ledger.  This classifier deliberately returns only stable
    enums.  ``submission_unknown`` is checked before the broader transient
    bucket because it carries the important paid-action rule: never retry an
    attempt whose submission outcome is uncertain without a fresh user action.
    """

    chain: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen and len(chain) < 8:
        chain.append(current)
        seen.add(id(current))
        cause = _safe_exception_attr(current, "__cause__")
        context = _safe_exception_attr(current, "__context__")
        current = cause if isinstance(cause, BaseException) else (
            context if isinstance(context, BaseException) else None
        )

    for item in chain:
        reason = _safe_exception_attr(item, "reason")
        if isinstance(reason, str) and re.fullmatch(r"[a-z0-9_]{1,48}", reason):
            return reason
    if any(isinstance(item, LLMAccountingUnavailable) for item in chain):
        return "accounting_unavailable"
    if any(isinstance(item, LLMRequestLimitExceeded) for item in chain):
        return "request_limit_exhausted"
    if any(isinstance(item, LLMContextOverflowError) for item in chain):
        return "context_too_large"
    if any(isinstance(item, LLMCallDeadlineExceeded) for item in chain):
        return "job_timeout"
    if any(_is_submission_unknown(item) for item in chain):
        return "submission_unknown"
    if any(_is_transient(item) for item in chain):
        return "provider_unavailable"
    return "generation_failed"


def _is_cache_control_rejection(exc: BaseException) -> bool:
    text = _safe_exception_text_lower(exc)
    return (
        not _is_submission_unknown(exc)
        and "cache_control" in text
        and any(marker in text for marker in ("reject", "unsupported", "invalid"))
    )


def _normalize_url(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    parsed = urlparse(text)
    if not parsed.scheme or not parsed.netloc:
        return text.rstrip("/")
    projected = safe_url(text)
    return projected.rstrip("/") if projected else None


class LLMClient:
    def __init__(self, task: str = "default") -> None:
        self.task = task
        self.config = resolved_model_config(task)
        self.model = self.config["model"]
        # Iter 027 capstone: OPENAI_STREAM=1 makes complete_text default to
        # streaming so long generations bypass Cloudflare's 524 / 100s edge
        # timeout. Non-streaming callers stay byte-identical when unset.
        #
        # iter 027 P2b-fix (v2): allow streaming when this client's
        # resolved base_url matches the MAIN OPENAI_BASE_URL value.
        # Earlier the gate was env-name-based (base_url_env ==
        # "OPENAI_BASE_URL"), but with the user unifying PLANNER and
        # main on the same keep-alive-capable 中转站, env-name
        # comparison wrongly excludes PLANNER. Comparing values lets
        # a single proxy serve both task families safely while still
        # blocking streaming to a separately-configured proxy that may
        # not have keep-alive yet. Per-call stream=True/False overrides.
        main_url = _normalize_url(os.environ.get("OPENAI_BASE_URL"))
        this_url = _normalize_url(self.config.get("base_url"))
        endpoint_streams = this_url is None or this_url == main_url
        # iter055 真模型实测修正: per-task stream(models.yaml)优先于 OPENAI_STREAM env。
        # 批处理任务(extract/compress/debate/review/premise/plot_planner)配 stream:false
        # —— litellm 不把 timeout 落到流式 read,流式下 per-call 超时失效(V2 实测 timeout=5
        # 仍跑满 294s);非流式 litellm 遵守 timeout(实测 58s 触发 litellm.Timeout)。write
        # 保流式(交互 UX,idle-deadline 另补)。未配 stream 的任务回落 OPENAI_STREAM(字节兼容)。
        cfg_stream = self.config.get("stream")
        if cfg_stream is None:
            cfg_stream = _truthy_env(os.environ.get("OPENAI_STREAM"))
        else:
            cfg_stream = bool(cfg_stream)
        self.stream_default = bool(cfg_stream) and endpoint_streams

    @property
    def is_mock(self) -> bool:
        return str(self.model).lower().startswith("mock")

    def complete_text(
        self,
        messages: List[Dict[str, str]],
        *,
        temperature: Optional[float] = None,
        cache_segments: Optional[List[Dict[str, Any]]] = None,
        stream: Optional[bool] = None,
    ) -> str:
        started = time.monotonic()
        prepared_messages = self._prepare_messages(messages, cache_segments)
        request_meta = self._request_meta(prepared_messages)
        # iter 051b (F3): task-level max_tokens may come straight from a
        # hand-edited models.yaml — degrade to 2000 instead of crashing the
        # whole completion call on a non-numeric value.
        max_tokens = _safe_int(self.config.get("max_tokens", 2000), 2000)
        self._check_context(request_meta["prompt_tokens"], max_tokens)
        if self.is_mock:
            # OPENAI_MODEL=mock must NOT stream (existing behavior, no SSE involved).
            text = self._mock_text(prepared_messages)
            self._try_log_call("complete_text", "ok", started, request_meta=request_meta, response_text=text)
            return text
        try:
            from litellm import completion
        except Exception as exc:
            self._try_log_call("complete_text", "error", started, exc, request_meta=request_meta)
            raise RuntimeError("litellm is required for real model calls") from exc

        use_stream = self.stream_default if stream is None else bool(stream)
        # A synchronous streaming iterator can block inside ``next()`` before
        # Python regains control to check the outer job deadline.  Web jobs
        # always install an LLM deadline, so use the non-streaming transport in
        # that scope and let LiteLLM's clamped request timeout cover connect +
        # read.  CLI/direct callers without an outer deadline keep streaming.
        if _LLM_DEADLINE.get() is not None:
            use_stream = False

        last_exc: Exception | None = None
        attempts = max(1, int(self.config.get("retry_attempts", 1)))
        if cache_segments and any("cache_control" in msg for msg in prepared_messages):
            attempts += 1
        cache_downgraded = False
        failure_trace_id = uuid.uuid4().hex
        for attempt in range(1, attempts + 1):
            try:
                deadline = _LLM_DEADLINE.get()
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    raise LLMCallDeadlineExceeded("LLM job deadline expired before provider attempt")
                kwargs: Dict[str, Any] = {
                    "model": self.model,
                    "messages": prepared_messages,
                    "temperature": temperature if temperature is not None else self.config.get("temperature", 0.2),
                    "max_tokens": max_tokens,
                }
                # iter055 轨A: per-call 超时(覆盖连接+读取)。>0 才加 → 未配(=0)时不含
                # timeout key，逐字节兼容旧行为。litellm drop_params 不丢顶层 timeout(R9)。
                configured_timeout = float(self.config.get("request_timeout") or 0.0)
                if remaining is not None:
                    kwargs["timeout"] = min(configured_timeout, remaining) if configured_timeout > 0 else remaining
                elif configured_timeout > 0:
                    kwargs["timeout"] = configured_timeout
                # iter055 真模型实测修正: 自管重试(轨B transient 分类 + 指数退避),禁 litellm
                # 内部重试 —— 否则它在我们每次 attempt 内再重试,叠加放大墙钟(实测 timeout=5
                # 下单 attempt ~19s 而非 ~5s),且绕过我们的分类/退避,拖慢卡死检测。
                kwargs["num_retries"] = 0
                if self.config.get("api_key"):
                    kwargs["api_key"] = self.config["api_key"]
                if self.config.get("base_url"):
                    kwargs["api_base"] = self.config["base_url"]
                # Claim at the last possible point before calling LiteLLM so
                # every real provider attempt (safe retry/cache downgrade/JSON
                # repair included) is bounded. Mock returned above and consumes
                # no allowance.
                from .cost_estimator import cost_cny as _cost_cny

                reserved_cost = _cost_cny(
                    int(request_meta.get("prompt_bytes", 0) or 0),
                    0,
                    max_tokens,
                    self.model,
                )
                _claim_model_request(self.model, reserved_cost_cny=reserved_cost)
                if use_stream:
                    kwargs["stream"] = True
                    # include_usage asks the upstream to emit a final SSE chunk
                    # with usage tallies; supported by litellm >= 1.40-ish.
                    kwargs["stream_options"] = {"include_usage": True}
                    stream_iter = completion(**kwargs)
                    content, response = self._consume_stream(stream_iter)
                else:
                    response = completion(**kwargs)
                    content = response["choices"][0]["message"]["content"]
                self._try_log_call(
                    "complete_text",
                    "ok",
                    started,
                    attempt=attempt,
                    request_meta=request_meta,
                    response_text=content,
                    response=response,
                )
                return content
            except (
                LLMRequestLimitExceeded,
                LLMBudgetLimitExceeded,
                LLMPricingUnavailable,
                LLMAccountingUnavailable,
            ):
                # No provider call occurred, so do not write a retry_error cost
                # row or wrap this deterministic admission failure as a model
                # transport error.
                raise
            except Exception as exc:
                last_exc = exc
                # iter078 P1-2: 每个失败 attempt 记一条 retry_error——此前 N 次
                # 真实 API 调用只在循环外记 1 条 error，N-1 次的 prompt 消耗从
                # 账本消失（真模型弱网下预算持续虚低）。prompt_tokens 随
                # request_meta 入账；response 侧超时场景 provider 已计费部分
                # 结构性不可知，不估（见 iteration_078 已知残留低估声明）。
                self._try_log_call(
                    "complete_text",
                    "retry_error",
                    started,
                    exc,
                    attempt=attempt,
                    request_meta=request_meta,
                    trace_id=failure_trace_id,
                )
                # Mid-stream failures discard partial output (handled inside
                # _consume_stream — it raises before returning any content).
                if (
                    cache_segments
                    and not cache_downgraded
                    and any("cache_control" in msg for msg in prepared_messages)
                    and _is_cache_control_rejection(exc)
                ):
                    prepared_messages = self._prepare_messages(messages, None)
                    request_meta = self._request_meta(prepared_messages)
                    cache_downgraded = True
                    continue
                # iter055 轨B: 仅 transient 重试,指数退避(base*2^(n-1) 封顶 cap)+ 抖动
                # 错峰(530/1033 是 provider 过载,线性退避加剧拥堵)。非 transient(schema/
                # context)立即 break → 不空耗 attempts。cache 降级 continue 路径在上方不受影响。
                if attempt < attempts and _is_safe_to_retry(exc):
                    base = float(self.config.get("retry_backoff_seconds", 0.5))
                    cap = float(self.config.get("retry_backoff_cap_seconds", 30))
                    jitter = float(self.config.get("retry_backoff_jitter_seconds", 1))
                    delay = min(base * (2 ** (attempt - 1)), cap) + random.uniform(0, jitter)
                    deadline = _LLM_DEADLINE.get()
                    if deadline is not None and time.monotonic() + delay >= deadline:
                        last_exc = LLMCallDeadlineExceeded(
                            "LLM job deadline would expire during retry backoff"
                        )
                        break
                    time.sleep(delay)
                else:
                    break
        # iter078 P1-2: 终态 error 条保留（dashboard/grep 兼容）但 token 置零
        # ——每次尝试的消耗已由上方 retry_error 条逐笔入账，这里再带 token
        # 就是双计。final_of_attempts 标记它是 N 次尝试的收尾条。
        terminal_error = LLMProviderFailure(
            reason=public_llm_failure_reason(last_exc or RuntimeError()),
            error_type=safe_exception_type_name(last_exc) if last_exc is not None else "Exception",
            attempts=attempt,
            trace_id=failure_trace_id,
        )
        self._try_log_call(
            "complete_text",
            "error",
            started,
            terminal_error,
            request_meta=request_meta,
            zero_tokens=True,
            final_of_attempts=attempt,
        )
        # Never retain the raw provider exception as ``__cause__``: traceback
        # serialization in a downstream sink would otherwise bypass the safe
        # wrapper even when ``str(terminal_error)`` is metadata-only.
        raise terminal_error from None

    def ping(self) -> Dict[str, Any]:
        """iter 048a: lightweight model-key connectivity probe for the
        workbench "test key" matrix. Returns a JSON-safe dict; never raises
        and never echoes the api_key.

        ``OPENAI_MODEL=mock`` short-circuits with zero network I/O (so
        ``unittest discover`` and the default WebUI stay offline). A real
        probe sends a single ``max_tokens=1`` "ping" completion — cost is
        on the order of one token, comparable to ``python main.py
        preflight`` — and is only ever triggered by an explicit user click.
        """
        if self.is_mock:
            return {"task": self.task, "model": self.model, "ok": True, "mock": True}
        started = time.monotonic()
        try:
            from litellm import completion
        except Exception as exc:
            return {
                "task": self.task,
                "model": self.model,
                "ok": False,
                "mock": False,
                "error": _sanitize_error_text(exc, max_chars=200),
            }
        try:
            kwargs: Dict[str, Any] = {
                "model": self.model,
                "messages": [{"role": "user", "content": "ping"}],
                "temperature": self.config.get("temperature", 0.2),
                "max_tokens": 1,
            }
            if self.config.get("request_timeout"):  # iter055 轨A
                kwargs["timeout"] = float(self.config["request_timeout"])
            kwargs["num_retries"] = 0  # iter055: 自管重试,禁 litellm 内部重试(同 complete_text)
            if self.config.get("api_key"):
                kwargs["api_key"] = self.config["api_key"]
            if self.config.get("base_url"):
                kwargs["api_base"] = self.config["base_url"]
            completion(**kwargs)
            latency_ms = int((time.monotonic() - started) * 1000)
            return {
                "task": self.task,
                "model": self.model,
                "ok": True,
                "mock": False,
                "latency_ms": latency_ms,
            }
        except Exception as exc:
            # Never surface the api_key or echoed prompt payloads: some
            # providers/proxies include request kwargs in exception strings.
            err = _sanitize_error_text(exc, api_key=self.config.get("api_key"), max_chars=200)
            return {
                "task": self.task,
                "model": self.model,
                "ok": False,
                "mock": False,
                "error": err[:200],
            }

    def _consume_stream(self, stream_iter: Any) -> tuple[str, Dict[str, Any]]:
        """Consume an SSE iterator from litellm.completion(stream=True).

        Returns (joined_content, synthetic_response_dict). The synthetic dict
        mirrors the non-streaming response shape expected by _log_call so the
        per-call log record stays identical for dashboards / cost_estimator.
        Any exception mid-stream propagates so the outer retry loop can throw
        away partial output and start over.
        """
        chunks: List[str] = []
        usage: Optional[Dict[str, Any]] = None
        deadline = _LLM_DEADLINE.get()
        if deadline is not None and time.monotonic() >= deadline:
            raise LLMCallDeadlineExceeded("LLM job deadline expired before stream read")
        for chunk in stream_iter:
            deadline = _LLM_DEADLINE.get()
            if deadline is not None and time.monotonic() >= deadline:
                raise LLMCallDeadlineExceeded("LLM job deadline expired during stream read")
            # chunk may be dict or pydantic-like object depending on litellm
            # version; normalize via __getitem__ / getattr.
            try:
                choices = chunk["choices"] if isinstance(chunk, dict) else getattr(chunk, "choices", None)
            except (KeyError, TypeError):
                choices = None
            if choices:
                first = choices[0]
                delta = first["delta"] if isinstance(first, dict) else getattr(first, "delta", None)
                if delta is not None:
                    if isinstance(delta, dict):
                        piece = delta.get("content") or ""
                    else:
                        piece = getattr(delta, "content", None) or ""
                    if piece:
                        chunks.append(piece)
            chunk_usage = chunk.get("usage") if isinstance(chunk, dict) else getattr(chunk, "usage", None)
            if chunk_usage:
                usage = self._usage_dict({"usage": chunk_usage})
            deadline = _LLM_DEADLINE.get()
            if deadline is not None and time.monotonic() >= deadline:
                raise LLMCallDeadlineExceeded("LLM job deadline expired during stream read")
        content = "".join(chunks)
        response: Dict[str, Any] = {
            "choices": [{"message": {"content": content}}],
        }
        if usage:
            response["usage"] = usage
        return content, response

    def complete_json(self, messages: List[Dict[str, str]], response_model: type[BaseModel]) -> BaseModel:
        started = time.monotonic()
        request_meta = self._request_meta(messages)
        if self.is_mock:
            result = self._mock_json(response_model, messages)
            response_text = json.dumps(model_to_dict(result), ensure_ascii=False)
            self._try_log_call("complete_json", "ok", started, request_meta=request_meta, response_text=response_text)
            return result
        content = self.complete_text(messages)
        data: Dict[str, Any]
        parse_failed = False
        try:
            data = json.loads(extract_json_object(content))
        except (json.JSONDecodeError, ValueError):
            parse_failed = True
        if parse_failed:
            if self.config.get("json_repair", True):
                repair_failure: Exception | None = None
                try:
                    repaired = self.complete_text(
                        [
                            {
                                "role": "system",
                                "content": (
                                    "You repair invalid JSON. Output only one valid JSON object matching the requested schema."
                                ),
                            },
                            {
                                "role": "user",
                                "content": (
                                    f"Response model: {response_model.__name__}\n"
                                    f"Invalid response:\n{content[:4000]}"
                                ),
                            },
                        ],
                        temperature=0,
                    )
                    data = json.loads(extract_json_object(repaired))
                    return self._validate_json_response(data, response_model, original_content=content)
                except Exception as repair_exc:
                    repair_failure = repair_exc
                assert repair_failure is not None
                raise_if_terminal_llm_failure(repair_failure)
                raise LLMResponseValidationError(
                    response_model.__name__, repaired=True
                ) from None
            raise LLMResponseValidationError(
                response_model.__name__, repaired=False
            ) from None
        return self._validate_json_response(data, response_model, original_content=content)

    def _validate_json_response(
        self,
        data: Dict[str, Any],
        response_model: type[BaseModel],
        *,
        original_content: str,
    ) -> BaseModel:
        validation_error_text = ""
        try:
            return response_model(**data)
        except Exception as exc:
            # Used only in the provider repair prompt; never persisted.
            validation_error_text = f"{safe_exception_type_name(exc)}: {_safe_exception_text_lower(exc)[:1000]}"
        if self.config.get("json_repair", True):
            repair_failure: Exception | None = None
            try:
                repaired = self.complete_text(
                    [
                        {
                            "role": "system",
                            "content": (
                                "You repair JSON that is syntactically valid but fails schema validation. "
                                "Output only one JSON object matching the requested response model."
                            ),
                        },
                        {
                            "role": "user",
                            "content": (
                                f"Response model: {response_model.__name__}\n"
                                f"Validation error:\n{validation_error_text}\n\n"
                                f"Invalid JSON object:\n{json.dumps(data, ensure_ascii=False)[:4000]}"
                            ),
                        },
                    ],
                    temperature=0,
                )
                repaired_data = json.loads(extract_json_object(repaired))
                return response_model(**repaired_data)
            except Exception as repair_exc:
                repair_failure = repair_exc
            assert repair_failure is not None
            raise_if_terminal_llm_failure(repair_failure)
            raise LLMResponseValidationError(
                response_model.__name__, repaired=True
            ) from None
        raise LLMResponseValidationError(
            response_model.__name__, repaired=False
        ) from None

    def _try_log_call(self, *args: Any, **kwargs: Any) -> None:
        """Best-effort telemetry that can never change provider semantics.

        A provider response may already have been accepted or may be
        submission-unknown.  Retrying because a local log sink failed would
        duplicate a paid action, while propagating the sink exception could
        retain the raw provider error in ``__context__``.
        """

        try:
            self._log_call(*args, **kwargs)
        except BaseException:
            # Deliberately drop all exception text: filesystem and serializer
            # errors may themselves carry user-controlled content.
            _LLM_ACCOUNTING_DEGRADED.set(True)
            return

    def _log_call(
        self,
        operation: str,
        status: str,
        started: float,
        error: Exception | None = None,
        *,
        attempt: int | None = None,
        request_meta: Dict[str, Any] | None = None,
        response_text: str = "",
        response: Any = None,
        zero_tokens: bool = False,
        final_of_attempts: int | None = None,
        trace_id: str | None = None,
    ) -> None:
        record: Dict[str, Any] = {
            "task": self.task,
            "operation": operation,
            "model": self.model,
            "status": status,
            "duration_ms": round((time.monotonic() - started) * 1000, 2),
        }
        if request_meta:
            record.update(request_meta)
        record["response_chars"] = len(response_text)
        response_tokens, response_method = self._count_tokens(response_text)
        record["response_tokens"] = response_tokens
        if request_meta and request_meta.get("token_method") != response_method:
            record["response_token_method"] = response_method
        usage = self._usage_dict(response)
        if status == "ok" and not str(self.model).lower().startswith("mock"):
            prompt_usage = usage.get("prompt_tokens")
            completion_usage = usage.get("completion_tokens", usage.get("response_tokens"))
            reliable_usage = all(type(value) is int and value >= 0
                                 for value in (prompt_usage, completion_usage))
            record["usage_reliable"] = reliable_usage
            if not reliable_usage:
                _LLM_ACCOUNTING_DEGRADED.set(True)
        if usage:
            record["prompt_tokens"] = int(usage.get("prompt_tokens", record.get("prompt_tokens", 0)) or 0)
            record["response_tokens"] = int(
                usage.get("completion_tokens", usage.get("response_tokens", record.get("response_tokens", 0))) or 0
            )
            record["cache_read_tokens"] = int(
                usage.get("cache_read_tokens", usage.get("prompt_cache_hit_tokens", 0)) or 0
            )
            record["cache_write_tokens"] = int(
                usage.get("cache_write_tokens", usage.get("prompt_cache_miss_tokens", 0)) or 0
            )
        if zero_tokens:
            # iter078 P1-2: 终态 error 条的 token 已由逐 attempt 的 retry_error
            # 条入账，这里置零防聚合双计。
            record["prompt_tokens"] = 0
            record["response_tokens"] = 0
            record["cache_read_tokens"] = 0
            record["cache_write_tokens"] = 0
        if final_of_attempts is not None:
            record["final_of_attempts"] = final_of_attempts
        if attempt is not None:
            record["attempt"] = attempt
        if error is not None:
            error_code = public_llm_failure_reason(error)
            error_type = safe_exception_type_name(error)
            candidate_trace_id = trace_id or _safe_exception_attr(error, "trace_id")
            if not isinstance(candidate_trace_id, str) or re.fullmatch(r"[a-f0-9]{32}", candidate_trace_id) is None:
                candidate_trace_id = uuid.uuid4().hex
            record.update({
                "error": error_code,
                "error_code": error_code,
                "error_type": error_type,
                "trace_id": candidate_trace_id,
            })
        from . import paths
        log_path = paths.llm_calls_log_path() if paths.workspace_name() else (ROOT / "logs" / "llm_calls.jsonl")
        append_jsonl(log_path, record)

    def _prepare_messages(
        self, messages: List[Dict[str, str]], cache_segments: Optional[List[Dict[str, Any]]]
    ) -> List[Dict[str, Any]]:
        cache_disabled = _truthy_env(os.environ.get("DISABLE_PROMPT_CACHE"))
        if not cache_segments or cache_disabled:
            return [dict(message) for message in messages]
        prepared: List[Dict[str, Any]] = []
        cache_enabled = bool(self.config.get("cache_enabled", False))
        for segment in cache_segments:
            message = {"role": segment.get("role", "user"), "content": segment.get("content", "")}
            if cache_enabled and segment.get("cache"):
                message["cache_control"] = {"type": "ephemeral"}
            prepared.append(message)
        return prepared

    def _request_meta(self, messages: List[Dict[str, Any]]) -> Dict[str, Any]:
        clean_messages = [{"role": msg.get("role", ""), "content": msg.get("content", "")} for msg in messages]
        payload = self.model + json.dumps(clean_messages, sort_keys=True, ensure_ascii=False)
        prompt_text = "\n".join(str(msg.get("content", "")) for msg in clean_messages)
        prompt_tokens, token_method = self._count_tokens(prompt_text)
        return {
            "request_hash": hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16],
            "prompt_chars": len(prompt_text),
            # A byte count is a conservative upper bound for byte-level BPE
            # input tokens and supports a pre-call CNY reservation.
            "prompt_bytes": len(prompt_text.encode("utf-8")),
            "prompt_tokens": prompt_tokens,
            "token_method": token_method,
        }

    def _count_tokens(self, text: str) -> tuple[int, str]:
        # iter 047a: delegate to the free function in context_budget so token
        # counting has a single source of truth (also used by the budget
        # assembler). Return shape (tokens, method) is unchanged.
        from .context_budget import count_tokens

        return count_tokens(text, self.model)

    def _check_context(self, prompt_tokens: int, max_tokens: int) -> None:
        context_limit = int(self.config.get("context_limit", 128000))
        if prompt_tokens + max_tokens > context_limit * 0.9:
            raise LLMContextOverflowError(
                f"LLM context overflow: task={self.task}, model={self.model}, "
                f"prompt_tokens={prompt_tokens}, max_tokens={max_tokens}, context_limit={context_limit}"
            )

    def _usage_dict(self, response: Any) -> Dict[str, Any]:
        if response is None:
            return {}
        usage = None
        if isinstance(response, dict):
            usage = response.get("usage")
        else:
            usage = getattr(response, "usage", None)
        if usage is None:
            return {}
        if isinstance(usage, dict):
            return usage
        if hasattr(usage, "model_dump"):
            return usage.model_dump()
        if hasattr(usage, "dict"):
            return usage.dict()
        return {key: getattr(usage, key) for key in dir(usage) if not key.startswith("_")}

    def _mock_text(self, messages: List[Dict[str, str]]) -> str:
        user = "\n".join(m.get("content", "") for m in messages if m.get("role") == "user")
        # iter 052 mock-only test hook: the fixed mock draft (~60 chars) can
        # never pass the deterministic short_chapter_length gate (3500+), so
        # mock write-book always ends in Reject. MOCK_WRITER_CHARS=<n> makes
        # the "write" task return a deterministic long draft so driver E2E
        # tests can walk the approve path through the real pipeline. Unset =
        # byte-identical legacy behavior. (Same opt-in pattern as iter 019's
        # WRITER_FORCE_FAIL.)
        if self.task == "write":
            # 052 铁律⑨ B-L1：clamp 防呆——极端 env 值不应让测试进程 OOM。
            pad = min(_env_int("MOCK_WRITER_CHARS", 0), 1_000_000)
            if pad > 0:
                base = (
                    "雨停在凌晨。路明非站在窗边，看着城市的灯一盏盏熄灭。"
                    "他没有说话，只把那张写满名字的纸折起来，放进口袋。"
                )
                reps = (pad // 40) + 1
                return "\n\n".join([base] * reps)
            # Writer prompts legitimately contain review criteria and words
            # such as “审查”.  Task identity must win over keyword routing;
            # otherwise the mock writer returns a review JSON object and that
            # object is persisted as chapter prose in the real Web workflow.
            return (
                "雨停在凌晨。路明非站在窗边，看着城市的灯一盏盏熄灭。"
                "他没有说话，只把那张写满名字的纸折起来，放进口袋。"
            )
        if "审查" in user or "review" in user.lower():
            return json.dumps({"verdict": "Approve", "score": 9, "issues": [], "suggestions": []}, ensure_ascii=False)
        if "续写" in user or "写作" in user:
            return "雨停在凌晨。路明非站在窗边，看着城市的灯一盏盏熄灭。他没有说话，只把那张写满名字的纸折起来，放进口袋。"
        return "基于当前资料，方案倾向于保留角色选择的代价，并回收主要伏笔。"

    def _mock_json(self, response_model: type[BaseModel], messages: List[Dict[str, str]]) -> BaseModel:
        name = response_model.__name__
        payload: Dict[str, Any]
        if name == "ChapterExtraction":
            user = "\n".join(m.get("content", "") for m in messages if m.get("role") == "user")
            chapter_id = _field_from_prompt(user, "chapter_id") or "mock_chapter"
            volume_id = _field_from_prompt(user, "volume_id") or "mock_volume"
            title = _field_from_prompt(user, "title") or "未命名章节"
            payload = {
                "chapter_id": chapter_id,
                "volume_id": volume_id,
                "title": title,
                "summary": "mock 提取摘要：本章更新了角色状态、关系和伏笔。",
                "rolling_summary": "mock 滚动摘要。",
                "character_states": [],
                "relationships": [],
                # iter077 P0-1: non-empty so mock compress seeds a non-empty
                # foreshadowing registry — the boundary-advisory path of the
                # readiness gate is exercised in mock long runs instead of the
                # registry staying empty and giving the gate zero coverage.
                "foreshadowing": [
                    {
                        "kind": "clue",
                        "description": f"mock 伏笔：{chapter_id} 留下的线索尚未回收。",
                        "status": "unresolved",
                    }
                ],
                "worldbuilding": [],
                "style_samples": [],
                "evidence_spans": [],
            }
            return response_model(**payload)
        if name == "AgentReview":
            payload = {
                "agent_name": _field_from_prompt("\n".join(m.get("content", "") for m in messages), "agent_name") or "mock_agent",
                "verdict": "Approve",
                "score": 9,
                "issues": [],
                "suggestions": [],
            }
            return response_model(**payload)
        if name == "ChapterPlan":
            payload = {
                "target_chapters": 5,
                "overall_arc": "mock 五章大纲：角色先确认当前处境，再逐步推进线索、关系与最终选择。",
                "generated_by": "plot_planner_v1_mock",
                "chapters": [
                    {
                        "chapter_no": chapter_no,
                        "title": f"mock 第 {chapter_no} 章",
                        "opening_scene": f"第 {chapter_no} 章开场在一个具体地点承接上一章结尾。",
                        "key_events": [f"mock 第 {chapter_no} 章事件一", f"mock 第 {chapter_no} 章事件二"],
                        "relationships_in_play": ["mock 关系"],
                        "ending_hook": f"第 {chapter_no} 章结尾留下下一章钩子。",
                        "target_chinese_chars": 4000,
                        "plot_purpose": f"推进第 {chapter_no} 段情节并保持主线可控。",
                    }
                    for chapter_no in range(1, 6)
                ],
            }
            return response_model(**payload)
        if name == "GlobalFactsProposal":
            payload = {
                "_meta": {"review_instructions": "mock review"},
                "facts": [
                    {
                        "fact_id": "mock_fact_1",
                        "statement": "mock 全局事实：主角已经进入新的选择节点。",
                        "confidence": 0.8,
                        "scope": "global",
                        "evidence_spans": [],
                        "applies_to": ["mock 主角"],
                    }
                ],
            }
            return response_model(**payload)
        if name == "EntityGraphProposal":
            payload = {
                "_meta": {"review_instructions": "mock review"},
                "entities": [
                    {
                        "id": "mock_protagonist",
                        "name": "mock 主角",
                        "type": "character",
                        "aliases": [],
                        "tags": ["#主角", "#同伴"],
                        "key_facts": ["处在新的选择节点"],
                        "description": "mock 角色状态。",
                    },
                    {
                        "id": "mock_companion",
                        "name": "mock 同伴",
                        "type": "character",
                        "aliases": [],
                        "tags": ["#同伴"],
                        "key_facts": ["与主角共享线索"],
                        "description": "mock 同伴状态。",
                    },
                ],
                "relationships": [
                    {
                        "src_id": "mock_protagonist",
                        "dst_id": "mock_companion",
                        "relation_type": "同伴",
                        "timeline": [{"anchor_chapter": "mock_chapter", "state": "共同面对下一步选择", "active": True}],
                    }
                ],
            }
            return response_model(**payload)
        if name == "ContinuationAnchorProposal":
            payload = {
                "_meta": {"review_instructions": "mock review"},
                "anchor_text": "mock 续写起点：上一轮事件结束后，主角需要处理新的线索和关系压力。",
                "key_state_points": ["mock 主角状态：需要主动选择", "mock 关系状态：同伴仍在场"],
            }
            return response_model(**payload)
        if name == "StyleExamplesProposal":
            payload = {
                "_meta": {"review_instructions": "mock review"},
                "examples": [
                    {
                        "category": "opening_rhythm",
                        "source_file": "data/normalized_texts/mock.txt",
                        "start_line": 1,
                        "end_line": 2,
                        "preview": "mock preview",
                        "target_file": "data/style_examples/opening_rhythm.md",
                    }
                ],
            }
            return response_model(**payload)
        if name == "PremiseExpansion":
            # iter 051a: deterministic stub so tests can pin the artifact and
            # the downstream KB/debate injection byte-exactly.
            payload = {
                "genre_tone": "mock 题材基调：都市悬疑，冷静克制。",
                "protagonist": "mock 主角：身份与欲望来自立意，缺陷待第一章揭示。",
                "world_notes": ["mock 世界观要点一", "mock 世界观要点二"],
                "central_conflict": "mock 主冲突：主角必须在两难中做出选择。",
                "ending_anchor": "mock 结局锚点：以主角承担选择的代价收束。",
                "arc_hints": ["mock 第 1 章弧线提示", "mock 第 2 章弧线提示"],
            }
            return response_model(**payload)
        if name == "WriterStyleCard":
            # iter 056: deterministic stub so extract tests pin the card and
            # the prompt injection byte-exactly (铁律③).
            payload = {
                "name": "mock 风格卡",
                "category": "mock 流派",
                "rhythm": "mock 节奏：张弛交替，场景切换克制。",
                "sentence": "mock 句式：以短句为主，偶用长句铺陈。",
                "diction": "mock 用词：书面偏冷，少用流行语。",
                "imagery": "mock 意象：以光影与温度为主感官通道。",
                "dialogue": "mock 对话：信息密度高，潜台词多。",
                "subtext": "mock 含蓄度：克制留白，情绪不外显。",
                "narration": "mock 叙述：限知视角，与人物心理贴近。",
                "signatures": ["mock 标志性笔法一", "mock 标志性笔法二"],
                "taboo": ["mock 规避笔法一"],
            }
            return response_model(**payload)
        if name == "PersonasProposal":
            payload = {
                "_meta": {"review_instructions": "mock review"},
                "protagonist_name": "mock 主角",
                "protagonist_role": "mock 主角的身份与处境",
                "author_name": "mock 作者",
                "style_short_descriptor": "mock 风格描述",
                "world_setting_brief": "mock 世界观骨架：用于让 agent 模板知道大概背景。",
                "core_relationships": ["mock 主角 与 mock 同伴 的 同伴 关系"],
                "core_setting_rules": ["mock 设定规则一"],
            }
            return response_model(**payload)
        return response_model(**{})


def _truthy_env(value: Optional[str]) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _field_from_prompt(text: str, key: str) -> Optional[str]:
    prefix = f"{key}:"
    for line in text.splitlines():
        if line.strip().startswith(prefix):
            return line.split(":", 1)[1].strip()
    return None
