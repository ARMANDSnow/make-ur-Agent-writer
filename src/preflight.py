from __future__ import annotations

import json
import math
import os
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

from . import paths
from .chapter_splitter import load_manifest
from .config import ROOT, get_model_config, load_config, load_dotenv_if_available
from .extractor import _extract_settings, build_extraction_prompt
from .llm_client import LLMClient
from .utils import read_json, read_json_optional


TASKS = ("extract", "compress", "debate", "write", "review", "plot_planner")
CACHE_PROVIDER_HINTS = ("anthropic", "bedrock", "claude", "deepseek")


def _resolve_root(root: Path | None) -> Path:
    if root is not None:
        return root
    return paths.workspace_root() if paths.workspace_name() else ROOT


def run_preflight(root: Path | None = None) -> Dict[str, Any]:
    root = _resolve_root(root)
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
    _check_agents_config(fatal, warn, root, info)
    _check_style_rewrite_config(warn)
    _check_review_tier(fatal, info)
    _check_provider_routing(fatal, warn, is_global_mock)
    _check_context_limits(fatal, warn, info, model_cfg)
    _check_logs_writable(fatal, root)
    _check_extraction_failures(fatal, root)
    _check_rolling_state(fatal, warn, root)
    _check_tiktoken(warn, is_global_mock)
    _check_longest_chapter(warn, info, root)
    _check_cache_provider(warn)
    _check_global_facts(warn, root)
    _check_runtime_env(warn)
    _check_budget_guard(warn, is_global_mock)
    _check_start_safe_knowledge(warn, info, root)
    _check_foreshadowing_registry(warn, info, root)
    _check_panel_block_policy(warn, info)
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


def _check_agents_config(
    fatal: List[str], warn: List[str], root: Path | None = None, info: List[str] | None = None
) -> None:
    root = _resolve_root(root)
    info = info if info is not None else []
    try:
        cfg = load_config("agents.yaml")
    except Exception as exc:
        fatal.append(f"agents.yaml failed to load: {exc}")
        return
    value = cfg.get("max_review_attempts")
    if not isinstance(value, int) or value <= 0:
        fatal.append("agents.yaml missing required key 'max_review_attempts' or value is not a positive integer.")
    # iter078 P1-8: anchor 判定改走 load_continuation_anchor 单一真源。旧代码
    # 自己拼「manual 文件 else yaml」，与生产语义有两处漂移（假阳性）：
    # ①workspace 态 yaml 的 continuation_anchor 根本不生效（load 只在 repo
    # root 回落 yaml），旧检查却按 yaml 值放行；②manual 文件存在但为空时，
    # 报错文案分不清「没配」和「配了个空文件」。
    from .continuation_anchor import load_continuation_anchor

    manual_anchor = root / "data" / "manual_overrides" / "continuation_anchor.txt"
    yaml_anchor = str(cfg.get("continuation_anchor", "") or "").strip()
    anchor = load_continuation_anchor(root=root)
    if not anchor:
        if manual_anchor.exists():
            warn.append(
                "continuation_anchor 手工文件存在但内容为空（data/manual_overrides/"
                "continuation_anchor.txt）——writer 实际拿到空锚点；填入内容或删除该文件。"
            )
        elif yaml_anchor:
            warn.append(
                "agents.yaml 配了 continuation_anchor，但当前 root 非 repo root（workspace 态）"
                "只认 manual 文件——writer 实际拿到空锚点；请写入 data/manual_overrides/"
                "continuation_anchor.txt。"
            )
        else:
            warn.append("continuation_anchor is empty; writer will lack temporal anchor.")
    elif manual_anchor.exists() and yaml_anchor:
        info.append(
            "continuation_anchor：manual 文件与 agents.yaml 配置同时存在，manual 文件优先生效。"
        )


def _check_style_rewrite_config(warn: List[str]) -> None:
    """Iter087: optional paid rewrite config is fail-closed, never guessed."""

    try:
        cfg = load_config("style_fingerprint.yaml")
    except Exception as exc:
        warn.append(f"style_fingerprint.yaml failed to load; automatic style rewrite is disabled: {type(exc).__name__}")
        return
    from .style_drift import parse_rewrite_policy

    _policy, warnings = parse_rewrite_policy(cfg)
    warn.extend(f"{message}; automatic style rewrite is disabled." for message in warnings)


def _check_review_tier(fatal: List[str], info: List[str]) -> None:
    """iter078 P1-8：WRITE_REVIEW_TIER 前置校验。

    脏值此前要到 ``run_write_book`` 的 ``resolve_tier`` 才 raise——过夜跑
    supervisor 会为一个 env 手滑烧掉整个重启周期。preflight 提前 FATAL；
    合法显式值回显生效档（INFO，对口 iter077 P0-3 的回显思路）。惰性
    import 规避 preflight→review_tier 的静态依赖。"""
    raw = os.getenv("WRITE_REVIEW_TIER", "")
    if not str(raw).strip():
        return
    from . import review_tier

    try:
        resolved = review_tier.resolve_tier(None)
    except ValueError as exc:
        fatal.append(f"WRITE_REVIEW_TIER 环境变量非法：{exc}")
        return
    info.append(f"WRITE_REVIEW_TIER 生效值：{resolved}")


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


def _check_context_limits(
    fatal: List[str], warn: List[str], info: List[str], model_cfg: Dict[str, Any]
) -> None:
    from .config import _known_context_cap

    default_limit = model_cfg.get("default", {}).get("context_limit")
    rows = []
    for task in TASKS:
        task_cfg = model_cfg.get("tasks", {}).get(task, {})
        context_limit = task_cfg.get("context_limit", default_limit)
        if not isinstance(context_limit, int) or context_limit <= 0:
            fatal.append(f"config/models.yaml task '{task}' is missing positive context_limit.")
        cfg = get_model_config(task)
        # iter078 P1-3: yaml 配置与已知模型物理上限矛盾的可见性。超上限的
        # 已被 get_model_config 封顶（危险方向：操作者以为有 128K 实际 64K
        # → WARN 生效值）；低于上限属主动保守（合法 → INFO）。mock 假模型
        # 无物理上限，跳过。
        model_name = str(cfg.get("model") or "")
        cap = _known_context_cap(model_name)
        if (
            isinstance(context_limit, int)
            and cap is not None
            and not model_name.lower().startswith("mock")
        ):
            if context_limit > cap:
                warn.append(
                    f"config/models.yaml task '{task}' context_limit={context_limit} 超过模型 "
                    f"{model_name} 的已知上限 {cap}，已按 {cap} 生效（防真溢出打到 provider）"
                )
            elif context_limit < cap:
                info.append(
                    f"task '{task}' context_limit={context_limit} 低于模型 {model_name} "
                    f"上限 {cap}（主动保守，合法）"
                )
        # iter078 P1-8: max_tokens↔context_limit 前置矛盾检查——此前只有运行
        # 时 _check_context 触发才发现（第一章就炸，白烧一次 supervisor 周期）。
        eff_max_tokens = cfg.get("max_tokens")
        eff_limit = cfg.get("context_limit")
        if (
            isinstance(eff_max_tokens, int)
            and isinstance(eff_limit, int)
            and eff_limit > 0
        ):
            if eff_max_tokens >= int(eff_limit * 0.9):
                fatal.append(
                    f"config/models.yaml task '{task}' max_tokens={eff_max_tokens} ≥ "
                    f"context_limit×0.9（{int(eff_limit * 0.9)}）——_check_context 红线恒触发，"
                    "一章都写不出。"
                )
            elif eff_max_tokens > eff_limit * 0.5:
                warn.append(
                    f"task '{task}' max_tokens={eff_max_tokens} 超过 context_limit"
                    f"（{eff_limit}）的一半，prompt 可用空间被严重挤压。"
                )
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
        data = read_json_optional(path, {})
        if not isinstance(data, dict):
            warn.append(f"{path.relative_to(root)} is not valid JSON; rolling context will be skipped.")
            continue
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
    manifest = read_json_optional(root / "data" / "chapter_manifest.json", [])
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
    data = read_json_optional(path, None)
    if not data:
        warn.append("data/manual_overrides/global_facts.json is missing or empty; key manual facts may not be injected.")


def _check_runtime_env(warn: List[str]) -> None:
    value = os.getenv("WRITE_MAX_TOKENS")
    if value:
        try:
            int(value)
        except ValueError:
            warn.append("WRITE_MAX_TOKENS is not an integer; model config will use its default max_tokens.")
    # iter078 P1-8: LLM_REQUEST_TIMEOUT 非有限/负值——config._env_float 已
    # 回退默认（同轮修复），这里把「你设了但没生效」显式告诉操作者。
    raw_timeout = os.getenv("LLM_REQUEST_TIMEOUT")
    if raw_timeout and str(raw_timeout).strip():
        try:
            parsed = float(str(raw_timeout).strip())
        except (TypeError, ValueError):
            parsed = None
        if parsed is None or not math.isfinite(parsed) or parsed < 0:
            warn.append(
                f"LLM_REQUEST_TIMEOUT={raw_timeout!r} 不是有限非负数字，已回退 "
                "models.yaml 的 request_timeout 默认值（超时守门不会按该值生效）。"
            )


def _check_budget_guard(warn: List[str], is_global_mock: bool) -> None:
    """iter 050 (F): with a real model configured, an unset / non-numeric
    ``NOVEL_DEFAULT_BUDGET_CNY`` means web write jobs fall back to the
    built-in 10元 cap — fine, but worth surfacing so the operator sets an
    explicit ceiling before a long unattended run. Mock stays silent."""
    if is_global_mock:
        return
    raw = os.getenv("NOVEL_DEFAULT_BUDGET_CNY", "")
    if not raw:
        warn.append(
            "NOVEL_DEFAULT_BUDGET_CNY is not set; write jobs that omit "
            "budget_cny default to a 10.0元 cap (the workbench form prefills "
            "this value but submits it explicitly). Set the env before long "
            "unattended runs."
        )
        return
    from .config import parse_budget_cny

    # iter 050d (L-3): nan never trips the gate (all comparisons False);
    # inf/negative are equally meaningless as caps. iter 051b: the validation
    # itself moved to config.parse_budget_cny — single source of truth shared
    # with web.jobs._default_budget_cny / _review_budget_cny.
    if parse_budget_cny(raw) is None:
        warn.append(
            f"NOVEL_DEFAULT_BUDGET_CNY='{raw}' is not a usable cap "
            "(needs a finite number >= 0); the 10.0元 default applies."
        )


def _check_start_safe_knowledge(warn: List[str], info: List[str], root: Path) -> None:
    kb = root / "data" / "knowledge_base" / "global_knowledge.md"
    index = root / "data" / "knowledge_base" / "knowledge_index.json"
    start = root / "data" / "manual_overrides" / "start_chapter.json"
    if not (kb.exists() and start.exists()):
        return
    if index.exists():
        info.append(
            "global_knowledge 起点安全已生效：writer/planner/debater/external-review 经 "
            "start_safe_knowledge 仅注入起点及之前的结构化知识（iter 047b）。"
        )
    else:
        warn.append(
            "global_knowledge.md 未按起点过滤且缺 knowledge_index.json；回退注入原文"
            "（可能含起点后剧透）。运行 `compress` 生成 index。"
        )


def _check_foreshadowing_registry(warn: List[str], info: List[str], root: Path) -> None:
    p = root / "data" / "foreshadowing_registry.json"
    if not p.exists():
        return
    data = read_json_optional(p, {})
    items = data.get("items", []) if isinstance(data, dict) else []

    def _st(it) -> str:
        return str(it.get("status") or "").strip().lower()

    open_n = sum(1 for it in items if isinstance(it, dict) and _st(it) not in ("resolved", "expired"))
    expired_n = sum(1 for it in items if isinstance(it, dict) and _st(it) == "expired")
    # iter047B2 M6: the write-readiness gate (foreshadowing.overdue_must_resolve)
    # blocks must_resolve items that are EITHER expired OR still-open-past-TTL, so
    # preflight must surface BOTH — counting only 'expired' let an operator see
    # "0 overdue" while the gate still blocked. preflight has no resume_from, so it
    # flags open must_resolve items as the gate's pending triggers.
    # iter077 P0-1: source-boundary seeds (planted_chapter<=0) no longer gate —
    # count them separately so the WARN only names real gate triggers.
    from .foreshadowing import is_boundary_item

    def _must_pending(it) -> bool:
        return isinstance(it, dict) and bool(it.get("must_resolve")) and _st(it) != "resolved"

    gating = [it for it in items if _must_pending(it) and not is_boundary_item(it)]
    boundary = [it for it in items if _must_pending(it) and is_boundary_item(it)]
    must_open = sum(1 for it in gating if _st(it) != "expired")
    must_expired = sum(1 for it in gating if _st(it) == "expired")
    info.append(
        f"伏笔 registry：open={open_n}, expired={expired_n}, "
        f"must-resolve 闸门项（expired={must_expired}, open={must_open}），"
        f"源书遗留项（仅提示不拦截）={len(boundary)}。"
    )
    if must_expired or must_open:
        warn.append(
            f"{must_expired} 个 must-resolve 伏笔已超期、{must_open} 个仍 open（续写章数超其 TTL 即被闸门拦截）；"
            "write-readiness 可能拦截续写，请用 gc/resolve 回收。"
        )


def _check_panel_block_policy(warn: List[str], info: List[str]) -> None:
    """iter077 P0-3：agents.yaml ``panel_block_policy`` 的解析告警前置到 preflight。

    配置手滑（枚举拼错、yaml bool、caveat_continue 配了但 max<=0）会让整套
    「拒稿不停机」硬化静默回落 halt——过夜跑到凌晨第一章软拒才暴露。这里把
    book_runner 的解析警告直接透出，并回显生效值。惰性 import 规避
    book_runner→preflight 的环形依赖（本函数只在运行时被调用，届时两模块均已
    加载完成）。"""
    try:
        from .book_runner import _panel_block_policy

        policy = _panel_block_policy(emit_stderr=False)
    except Exception as exc:  # 防御：策略解析永远不该让 preflight 本身崩掉
        warn.append(f"panel_block_policy 解析异常：{type(exc).__name__}: {exc}")
        return
    for msg in policy.get("config_warnings") or []:
        warn.append(msg)
    info.append(
        "panel_block_policy 生效值："
        f"on_soft_reject={policy['on_soft_reject']}, "
        f"on_hard_reject={policy['on_hard_reject']}, "
        f"max_panel_rejections={policy['max_panel_rejections']}。"
    )


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
        "Run mock smoke: bash scripts/verify.sh",
        "Real smoke requires explicit user authorization: CONFIRM_REAL_MODEL_SMOKE=可以跑了 bash scripts/real_smoke.sh",
    ]
