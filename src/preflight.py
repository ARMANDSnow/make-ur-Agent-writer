from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

from .chapter_splitter import load_manifest
from .config import ROOT, get_model_config, load_config, load_dotenv_if_available
from .extractor import _extract_settings, build_extraction_prompt
from .llm_client import LLMClient
from .utils import read_json


TASKS = ("extract", "compress", "debate", "write", "review", "plot_planner")
CACHE_PROVIDER_HINTS = ("anthropic", "bedrock", "claude", "deepseek")


def run_preflight(root: Path = ROOT) -> Dict[str, Any]:
    load_dotenv_if_available()
    fatal: List[str] = []
    warn: List[str] = []
    info: List[str] = []

    model_cfg = load_config("models.yaml")
    env_model = os.getenv("OPENAI_MODEL")
    default_model = str(model_cfg.get("default", {}).get("model", "mock"))
    model = env_model or default_model
    is_global_mock = model.lower().startswith("mock")

    _check_env(fatal, warn, is_global_mock)
    _check_agents_config(fatal, warn, root)
    _check_provider_routing(fatal, warn, is_global_mock)
    _check_context_limits(fatal, info, model_cfg)
    _check_logs_writable(fatal, root)
    _check_extraction_failures(fatal, root)
    _check_rolling_state(fatal, warn, root)
    _check_tiktoken(warn, is_global_mock)
    _check_longest_chapter(warn, info, root)
    _check_cache_provider(warn)
    _check_global_facts(warn, root)
    _summarize_llm_logs(info, root)

    status = "fail" if fatal else "warn" if warn else "ok"
    return {
        "status": status,
        "fatal": fatal,
        "warn": warn,
        "info": info,
        "next_steps": _next_steps(status),
    }


def render_preflight(report: Dict[str, Any]) -> str:
    lines = [f"PREFLIGHT: {report['status']}", ""]
    for label, key in (("FATAL", "fatal"), ("WARN", "warn"), ("INFO", "info")):
        lines.append(f"## {label}")
        items = report.get(key, [])
        if items:
            lines.extend(f"- {item}" for item in items)
        else:
            lines.append("- none")
        lines.append("")
    lines.append("## Next Steps")
    lines.extend(f"- {item}" for item in report.get("next_steps", []))
    return "\n".join(lines).rstrip() + "\n"


def _check_env(fatal: List[str], warn: List[str], is_global_mock: bool) -> None:
    if is_global_mock:
        return
    for task in TASKS:
        cfg = get_model_config(task)
        model = str(cfg.get("model", "mock"))
        if model.lower().startswith("mock"):
            continue
        api_key_env = str(cfg.get("api_key_env") or "OPENAI_API_KEY")
        if not os.getenv(api_key_env):
            fatal.append(f"{api_key_env} is empty while task '{task}' model is not mock.")
        base_url_env = str(cfg.get("base_url_env") or "")
        if base_url_env:
            base_url = os.getenv(base_url_env, "")
            parsed = urlparse(base_url)
            if not base_url or not parsed.netloc:
                fatal.append(f"{base_url_env} is empty or invalid while task '{task}' model is not mock.")


def _check_agents_config(fatal: List[str], warn: List[str], root: Path = ROOT) -> None:
    try:
        cfg = load_config("agents.yaml")
    except Exception as exc:
        fatal.append(f"agents.yaml failed to load: {exc}")
        return
    value = cfg.get("max_review_attempts")
    if not isinstance(value, int) or value <= 0:
        fatal.append("agents.yaml missing required key 'max_review_attempts' or value is not a positive integer.")
    manual_anchor = root / "data" / "manual_overrides" / "continuation_anchor.txt"
    anchor = manual_anchor.read_text(encoding="utf-8").strip() if manual_anchor.exists() else str(
        cfg.get("continuation_anchor", "") or ""
    ).strip()
    if not anchor:
        warn.append("continuation_anchor is empty; writer will lack temporal anchor.")


def _check_provider_routing(fatal: List[str], warn: List[str], is_global_mock: bool) -> None:
    if is_global_mock:
        return
    try:
        from litellm import get_llm_provider
    except Exception:
        warn.append("litellm not installed; provider routing not verified.")
        return
    for task in TASKS:
        model = str(get_model_config(task).get("model", "mock"))
        if model.lower().startswith("mock"):
            continue
        try:
            get_llm_provider(model)
        except Exception as exc:
            fatal.append(
                f"litellm cannot resolve provider for task '{task}' model='{model}': {exc}. "
                f"Use an explicit provider prefix such as 'deepseek/deepseek-chat' or 'openai/gpt-4'."
            )


def _check_context_limits(fatal: List[str], info: List[str], model_cfg: Dict[str, Any]) -> None:
    default_limit = model_cfg.get("default", {}).get("context_limit")
    rows = []
    for task in TASKS:
        task_cfg = model_cfg.get("tasks", {}).get(task, {})
        context_limit = task_cfg.get("context_limit", default_limit)
        if not isinstance(context_limit, int) or context_limit <= 0:
            fatal.append(f"config/models.yaml task '{task}' is missing positive context_limit.")
        cfg = get_model_config(task)
        rows.append(
            f"{task}: model={cfg.get('model')}, temperature={cfg.get('temperature')}, "
            f"max_tokens={cfg.get('max_tokens')}, context_limit={cfg.get('context_limit')}"
        )
    info.append("Task model table: " + " | ".join(rows))


def _check_logs_writable(fatal: List[str], root: Path) -> None:
    logs = root / "logs"
    if logs.exists():
        if not os.access(logs, os.W_OK):
            fatal.append(f"logs directory is not writable: {logs}")
    elif not os.access(root, os.W_OK):
        fatal.append(f"logs directory is missing and project root is not writable: {root}")


def _check_extraction_failures(fatal: List[str], root: Path) -> None:
    failures = list((root / "data" / "extraction_failures").glob("*.json"))
    if failures:
        fatal.append(f"data/extraction_failures has {len(failures)} residual failure file(s); run retry-failures or inspect manually.")


def _check_rolling_state(fatal: List[str], warn: List[str], root: Path) -> None:
    extracted_ids = {path.stem for path in (root / "data" / "extracted_jsons").glob("*.json")}
    for path in sorted((root / "data" / "rolling_summaries").glob("*.json")):
        data = read_json(path, {})
        chapter_ids = list(data.get("previous_chapter_ids", []))
        summaries = list(data.get("previous_summaries", []))
        if summaries and not chapter_ids:
            warn.append(f"{path.relative_to(root)} uses legacy rolling schema without previous_chapter_ids; rerun small extract to refresh.")
            continue
        if chapter_ids and chapter_ids[-1] not in extracted_ids:
            fatal.append(
                f"{path.relative_to(root)} last rolling chapter id '{chapter_ids[-1]}' is missing from data/extracted_jsons."
            )


def _check_tiktoken(warn: List[str], is_global_mock: bool) -> None:
    if is_global_mock:
        return
    try:
        import tiktoken  # type: ignore

        for task in TASKS:
            model = str(get_model_config(task).get("model", "mock"))
            if model.lower().startswith("mock"):
                continue
            try:
                tiktoken.encoding_for_model(model)
            except Exception:
                warn.append(
                    f"tiktoken has no direct encoding for task '{task}' model '{model}'; "
                    "token counts may fall back to cl100k_base or char estimate."
                )
    except Exception:
        warn.append("tiktoken is not installed; token counts may fall back to char estimate.")


def _check_longest_chapter(warn: List[str], info: List[str], root: Path) -> None:
    manifest = read_json(root / "data" / "chapter_manifest.json", [])
    if not manifest:
        warn.append("data/chapter_manifest.json is missing or empty; run normalize and split before real smoke.")
        return
    longest = max(manifest, key=lambda entry: int(entry.get("char_count", 0)))
    settings = _extract_settings()
    chunk_threshold = int(settings["chunk_threshold_chars"])
    over_threshold = [entry for entry in manifest if int(entry.get("char_count", 0)) > chunk_threshold]
    info.append(
        f"Chapter stats: total={len(manifest)}, longest={longest.get('chapter_id')} "
        f"chars={longest.get('char_count')}, chunk_threshold={chunk_threshold}, over_threshold={len(over_threshold)}"
    )
    low_conf = [entry for entry in manifest if float(entry.get("confidence", 1.0)) < 0.6]
    info.append(f"Manifest confidence: low_confidence_chapters={len(low_conf)} (threshold<0.6)")
    client = LLMClient("extract")
    dummy_text = "龙" * int(longest.get("char_count", 0))
    messages = build_extraction_prompt(longest, dummy_text, [], "")
    meta = client._request_meta(messages)
    max_tokens = int(client.config.get("max_tokens", 0))
    context_limit = int(client.config.get("context_limit", 1))
    if meta["prompt_tokens"] + max_tokens > context_limit * 0.9:
        warn.append(
            f"Longest chapter {longest.get('chapter_id')} estimated prompt_tokens={meta['prompt_tokens']} "
            f"+ max_tokens={max_tokens} exceeds 90% of context_limit={context_limit}; chunked extraction should be used."
        )
    elif int(longest.get("char_count", 0)) > chunk_threshold:
        warn.append(
            f"Longest chapter {longest.get('chapter_id')} chars={longest.get('char_count')} exceeds "
            f"chunk_threshold_chars={chunk_threshold}; chunked extraction will be used."
        )


def _check_cache_provider(warn: List[str]) -> None:
    cfg = get_model_config("write")
    if not cfg.get("cache_enabled"):
        return
    model = str(cfg.get("model", "")).lower()
    if model.startswith("mock"):
        return
    if not any(hint in model for hint in CACHE_PROVIDER_HINTS):
        warn.append(f"write.cache_enabled=true but model '{cfg.get('model')}' is not a known prompt cache provider; cache may not apply.")


def _check_global_facts(warn: List[str], root: Path) -> None:
    path = root / "data" / "manual_overrides" / "global_facts.json"
    data = read_json(path, None)
    if not data:
        warn.append("data/manual_overrides/global_facts.json is missing or empty; key manual facts may not be injected.")


def _summarize_llm_logs(info: List[str], root: Path) -> None:
    path = root / "logs" / "llm_calls.jsonl"
    if not path.exists():
        info.append("LLM logs: no logs/llm_calls.jsonl found.")
        return
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines()[-10:]:
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    status_counts = Counter(str(row.get("status", "unknown")) for row in rows)
    prompt_tokens = sum(int(row.get("prompt_tokens", 0) or 0) for row in rows)
    response_tokens = sum(int(row.get("response_tokens", 0) or 0) for row in rows)
    info.append(
        f"LLM logs last10: statuses={dict(status_counts)}, prompt_tokens={prompt_tokens}, response_tokens={response_tokens}"
    )


def _next_steps(status: str) -> List[str]:
    if status == "fail":
        return ["Fix FATAL items above, then rerun: python3 main.py preflight"]
    return [
        "Run mock smoke: bash scripts/real_smoke.sh",
        "For real sample, configure .env then run: python3 main.py extract --volume longzu_1 --limit 2 --force",
    ]
