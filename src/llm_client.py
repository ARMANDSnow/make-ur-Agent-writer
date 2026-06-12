from __future__ import annotations

import json
import hashlib
import os
import re
import sys as _sys
import types
import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from .config import ROOT
from .config import _env_int, _safe_int, get_model_config
from .schemas import model_to_dict
from .utils import append_jsonl, extract_json_object

# Iter 027: adapt HTTP(S)_PROXY for the aetherheartpool tunnel.
# The Claude Code sandbox forces all egress through localhost:63501 (no
# DNS / direct egress otherwise); the user's own terminal can reach the
# tunnel directly, but ships a stale ``HTTP_PROXY=http://127.0.0.1:7897``
# pointing at a not-always-running Clash. Mirror scripts/with_proxy.sh so
# direct-python entrypoints (scripts/iter027_*.py, scripts/collect_*.py)
# self-adapt without per-run env tweaks. Runs at import time so litellm
# sees the corrected env before its first network call.
def _setup_proxy() -> None:
    import socket

    proxies = ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy")
    sandbox_proxy = "http://localhost:63501"
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(0.5)
    try:
        sock.connect(("localhost", 63501))
        in_sandbox = True
    except OSError:
        in_sandbox = False
    finally:
        sock.close()

    if in_sandbox:
        if all(os.environ.get(k) == sandbox_proxy for k in proxies) and not any(
            k in os.environ for k in ("ALL_PROXY", "all_proxy")
        ):
            return
        for k in proxies:
            os.environ[k] = sandbox_proxy
        # ALL_PROXY outranks HTTP(S)_PROXY in some HTTP clients — clear it
        # so the 63501 tunnel actually wins. Mirrors scripts/with_proxy.sh.
        for k in ("ALL_PROXY", "all_proxy"):
            os.environ.pop(k, None)
    else:
        if all(k not in os.environ for k in (*proxies, "ALL_PROXY", "all_proxy")):
            return
        for k in (*proxies, "ALL_PROXY", "all_proxy"):
            os.environ.pop(k, None)


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


def _normalize_url(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    parsed = urlparse(text)
    if not parsed.scheme or not parsed.netloc:
        return text.rstrip("/")
    path = parsed.path.rstrip("/")
    return parsed._replace(scheme=parsed.scheme.lower(), netloc=parsed.netloc.lower(), path=path).geturl()


class LLMClient:
    def __init__(self, task: str = "default") -> None:
        self.task = task
        self.config = get_model_config(task)
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
        self.stream_default = (
            _truthy_env(os.environ.get("OPENAI_STREAM"))
            and endpoint_streams
        )

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
            self._log_call("complete_text", "ok", started, request_meta=request_meta, response_text=text)
            return text
        try:
            from litellm import completion
        except Exception as exc:
            self._log_call("complete_text", "error", started, exc, request_meta=request_meta)
            raise RuntimeError("litellm is required for real model calls") from exc

        use_stream = self.stream_default if stream is None else bool(stream)

        last_exc: Exception | None = None
        attempts = max(1, int(self.config.get("retry_attempts", 1)))
        if cache_segments and any("cache_control" in msg for msg in prepared_messages):
            attempts += 1
        cache_downgraded = False
        for attempt in range(1, attempts + 1):
            try:
                kwargs: Dict[str, Any] = {
                    "model": self.model,
                    "messages": prepared_messages,
                    "temperature": temperature if temperature is not None else self.config.get("temperature", 0.2),
                    "max_tokens": max_tokens,
                }
                if self.config.get("api_key"):
                    kwargs["api_key"] = self.config["api_key"]
                if self.config.get("base_url"):
                    kwargs["api_base"] = self.config["base_url"]
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
                self._log_call(
                    "complete_text",
                    "ok",
                    started,
                    attempt=attempt,
                    request_meta=request_meta,
                    response_text=content,
                    response=response,
                )
                return content
            except Exception as exc:
                last_exc = exc
                # Mid-stream failures discard partial output (handled inside
                # _consume_stream — it raises before returning any content).
                if cache_segments and not cache_downgraded and any("cache_control" in msg for msg in prepared_messages):
                    prepared_messages = self._prepare_messages(messages, None)
                    request_meta = self._request_meta(prepared_messages)
                    cache_downgraded = True
                    continue
                if attempt < attempts:
                    time.sleep(float(self.config.get("retry_backoff_seconds", 0.5)) * attempt)
        self._log_call("complete_text", "error", started, last_exc, request_meta=request_meta)
        suffix = "stream attempts" if use_stream else "attempt(s)"
        raise RuntimeError(f"LLM text completion failed after {attempts} {suffix}: {last_exc}") from last_exc

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
                "error": f"{type(exc).__name__}: {str(exc)[:200]}",
            }
        try:
            kwargs: Dict[str, Any] = {
                "model": self.model,
                "messages": [{"role": "user", "content": "ping"}],
                "temperature": self.config.get("temperature", 0.2),
                "max_tokens": 1,
            }
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
            # Never surface the api_key: some providers echo request kwargs
            # in their error string. Layered defense:
            #   1. exact-match replace of the configured key (covers plaintext)
            #   2. Bearer <token> pattern (covers Authorization headers
            #      echoed by middleware / proxies)
            #   3. sk-<long token> pattern (covers OpenAI-style keys that
            #      appear bare in error bodies; min length 16 so we don't
            #      false-positive on names like "sk-test")
            #   4. length cap as last-resort defense in depth
            # iter 048d (C2(a)): the prior code only had step 1, which
            # missed any encoded/echoed form of the key.
            err = f"{type(exc).__name__}: {exc}"
            key = self.config.get("api_key")
            if isinstance(key, str) and len(key) >= 8:
                err = err.replace(key, "***")
            err = re.sub(r"Bearer\s+\S+", "Bearer ***", err)
            err = re.sub(r"sk-[A-Za-z0-9_\-]{16,}", "sk-***", err)
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
        for chunk in stream_iter:
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
            self._log_call("complete_json", "ok", started, request_meta=request_meta, response_text=response_text)
            return result
        content = self.complete_text(messages)
        data: Dict[str, Any]
        try:
            data = json.loads(extract_json_object(content))
        except (json.JSONDecodeError, ValueError) as exc:
            if self.config.get("json_repair", True):
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
                    raise RuntimeError(
                        f"Failed to parse {response_model.__name__} from LLM response after repair. "
                        f"Initial error: {type(exc).__name__}: {exc}. "
                        f"Repair error: {type(repair_exc).__name__}: {repair_exc}. "
                        f"First 500 chars: {content[:500]}"
                    ) from repair_exc
            raise RuntimeError(
                f"Failed to parse {response_model.__name__} from LLM response. "
                f"Error: {type(exc).__name__}: {exc}. "
                f"First 500 chars: {content[:500]}"
            ) from exc
        return self._validate_json_response(data, response_model, original_content=content)

    def _validate_json_response(
        self,
        data: Dict[str, Any],
        response_model: type[BaseModel],
        *,
        original_content: str,
    ) -> BaseModel:
        try:
            return response_model(**data)
        except Exception as exc:
            if self.config.get("json_repair", True):
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
                                    f"Validation error:\n{type(exc).__name__}: {exc}\n\n"
                                    f"Invalid JSON object:\n{json.dumps(data, ensure_ascii=False)[:4000]}"
                                ),
                            },
                        ],
                        temperature=0,
                    )
                    repaired_data = json.loads(extract_json_object(repaired))
                    return response_model(**repaired_data)
                except Exception as repair_exc:
                    raise RuntimeError(
                        f"Failed to validate {response_model.__name__} from LLM response after schema repair. "
                        f"Validation error: {type(exc).__name__}: {exc}. "
                        f"Repair error: {type(repair_exc).__name__}: {repair_exc}. "
                        f"First 500 chars: {original_content[:500]}"
                    ) from repair_exc
            raise RuntimeError(
                f"Failed to validate {response_model.__name__} from LLM response. "
                f"Validation error: {type(exc).__name__}: {exc}. "
                f"First 500 chars: {original_content[:500]}"
            ) from exc

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
        if attempt is not None:
            record["attempt"] = attempt
        if error is not None:
            record["error"] = f"{type(error).__name__}: {error}"
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
            pad = _env_int("MOCK_WRITER_CHARS", 0)
            if pad > 0:
                base = (
                    "雨停在凌晨。路明非站在窗边，看着城市的灯一盏盏熄灭。"
                    "他没有说话，只把那张写满名字的纸折起来，放进口袋。"
                )
                reps = (pad // 40) + 1
                return "\n\n".join([base] * reps)
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
                "foreshadowing": [],
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
