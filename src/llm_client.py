from __future__ import annotations

import json
import hashlib
import math
import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel

from .config import ROOT
from .config import get_model_config
from .schemas import model_to_dict
from .utils import append_jsonl, extract_json_object


class LLMContextOverflowError(RuntimeError):
    pass


class LLMClient:
    def __init__(self, task: str = "default") -> None:
        self.task = task
        self.config = get_model_config(task)
        self.model = self.config["model"]

    @property
    def is_mock(self) -> bool:
        return str(self.model).lower().startswith("mock")

    def complete_text(
        self,
        messages: List[Dict[str, str]],
        *,
        temperature: Optional[float] = None,
        cache_segments: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        started = time.monotonic()
        prepared_messages = self._prepare_messages(messages, cache_segments)
        request_meta = self._request_meta(prepared_messages)
        max_tokens = int(self.config.get("max_tokens", 2000))
        self._check_context(request_meta["prompt_tokens"], max_tokens)
        if self.is_mock:
            text = self._mock_text(prepared_messages)
            self._log_call("complete_text", "ok", started, request_meta=request_meta, response_text=text)
            return text
        try:
            from litellm import completion
        except Exception as exc:
            self._log_call("complete_text", "error", started, exc, request_meta=request_meta)
            raise RuntimeError("litellm is required for real model calls") from exc

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
                if cache_segments and not cache_downgraded and any("cache_control" in msg for msg in prepared_messages):
                    prepared_messages = self._prepare_messages(messages, None)
                    request_meta = self._request_meta(prepared_messages)
                    cache_downgraded = True
                    continue
                if attempt < attempts:
                    time.sleep(float(self.config.get("retry_backoff_seconds", 0.5)) * attempt)
        self._log_call("complete_text", "error", started, last_exc, request_meta=request_meta)
        raise RuntimeError(f"LLM text completion failed after {attempts} attempt(s): {last_exc}") from last_exc

    def complete_json(self, messages: List[Dict[str, str]], response_model: type[BaseModel]) -> BaseModel:
        started = time.monotonic()
        request_meta = self._request_meta(messages)
        if self.is_mock:
            result = self._mock_json(response_model, messages)
            response_text = json.dumps(model_to_dict(result), ensure_ascii=False)
            self._log_call("complete_json", "ok", started, request_meta=request_meta, response_text=response_text)
            return result
        content = self.complete_text(messages)
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
                    return response_model(**data)
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
        return response_model(**data)

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
        if not cache_segments:
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
        if not text:
            return 0, "tiktoken"
        try:
            import tiktoken  # type: ignore

            try:
                encoding = tiktoken.encoding_for_model(str(self.model))
            except Exception:
                encoding = tiktoken.get_encoding("cl100k_base")
            return len(encoding.encode(text)), "tiktoken"
        except Exception:
            return math.ceil(len(text) / 1.6), "estimate"

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
        if "审查" in user or "review" in user.lower():
            return json.dumps({"verdict": "Approve", "score": 8, "issues": [], "suggestions": []}, ensure_ascii=False)
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
                "score": 8,
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


def _field_from_prompt(text: str, key: str) -> Optional[str]:
    prefix = f"{key}:"
    for line in text.splitlines():
        if line.strip().startswith(prefix):
            return line.split(":", 1)[1].strip()
    return None
