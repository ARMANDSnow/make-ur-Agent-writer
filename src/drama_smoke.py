"""Bounded end-to-end smoke for the five-station drama pipeline."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterable
from urllib.parse import urlsplit

# Direct ``python -m`` defaults to mock.  Pin before any project imports so a
# real parent environment/.env cannot initialize LiteLLM first.  Programmatic
# callers are handled by run_smoke() plus lazy Web imports below.
if __name__ == "__main__" and "--real-text" not in sys.argv[1:]:
    os.environ["OPENAI_MODEL"] = "mock"
    os.environ["DRAMA_MODEL"] = "mock"
    os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "true"

from . import drama_store, paths
from .config import get_model_config
from .drama_schemas import episode_paths
from .utils import read_json_optional, write_json
from .web.drama_insights import collect_drama_insights


class DramaSmokeTimeout(TimeoutError):
    def __init__(self, stage: str) -> None:
        super().__init__(f"drama smoke {stage} stage timed out")
        self.stage = stage


DRAMA_TEXT_TASKS = (
    "drama_plan", "drama_hooks", "drama_storyboard", "drama_character", "drama_review"
)


def real_text_readiness_errors() -> tuple[str, ...]:
    """Return stable, secret-free reasons the five paid text tasks are not ready."""
    errors: list[str] = []
    for task in DRAMA_TEXT_TASKS:
        cfg = get_model_config(task)
        model = str(cfg.get("model") or "").strip()
        if model.lower().startswith("mock"):
            errors.append(f"{task}:model_mock")
        elif "/" not in model or any(char in model for char in "\r\n\x00"):
            errors.append(f"{task}:model_provider_prefix_invalid")
        if not str(cfg.get("api_key") or "").strip():
            errors.append(f"{task}:api_key_missing")
        base_url = str(cfg.get("base_url") or "").strip()
        parsed = urlsplit(base_url)
        try:
            parsed_port_valid = parsed.port is not None or parsed.scheme in {"http", "https"}
        except ValueError:
            parsed_port_valid = False
        host = str(parsed.hostname or "").rstrip(".").lower()
        local_http = parsed.scheme == "http" and host in {"localhost", "127.0.0.1", "::1"}
        if (
            not base_url
            or (parsed.scheme != "https" and not local_http)
            or not parsed.netloc
            or not parsed_port_valid
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            errors.append(f"{task}:base_url_invalid")
        api_key = str(cfg.get("api_key") or "")
        if any(char in api_key for char in "\r\n\x00"):
            errors.append(f"{task}:api_key_invalid")
        context_limit = cfg.get("context_limit")
        max_tokens = cfg.get("max_tokens")
        if (
            type(context_limit) is not int
            or context_limit <= 0
            or type(max_tokens) is not int
            or max_tokens <= 0
            or max_tokens >= context_limit * 0.9
        ):
            errors.append(f"{task}:context_or_max_tokens_invalid")
    return tuple(errors)


def real_text_tasks_ready() -> bool:
    return not real_text_readiness_errors()


def validate_real_text_tasks_ready() -> None:
    errors = real_text_readiness_errors()
    if errors:
        raise RuntimeError("real_text_readiness_failed:" + ",".join(errors))


def _jobs_module():
    # Importing jobs pulls in the LLM stack; defer until run_smoke() has pinned
    # mock or explicitly validated a real-text invocation.
    from .web import jobs

    return jobs


def _wizard_module():
    from .web import wizard

    return wizard


def _wait_job(job_id: str, timeout_seconds: float) -> Dict[str, Any]:
    jobs = _jobs_module()
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        record = jobs.get_job(job_id)
        if record and record.get("status") in jobs.TERMINAL_STATUSES:
            return record
        time.sleep(0.05)
    jobs.request_cancel(job_id, "drama smoke timeout")
    raise TimeoutError("drama smoke job timed out")


def _run_step(
    workspace: str,
    step: str,
    episode_no: int,
    timeout_seconds: float,
    *,
    real_text: bool = False,
    budget_cny: float = 0.0,
    confirm_text_retry: bool = False,
    confirm_upstream_status_and_billing_checked: bool = False,
) -> Dict[str, Any]:
    jobs = _jobs_module()
    params: Dict[str, Any] = {"episode_no": episode_no}
    if real_text:
        params.update({
            "confirm_real_text": True,
            "budget_cny": budget_cny,
            "timeout_minutes": timeout_seconds / 60.0,
        })
        if confirm_text_retry:
            params["confirm_text_retry"] = True
        if confirm_upstream_status_and_billing_checked:
            params["confirm_upstream_status_and_billing_checked"] = True
    started_at = time.monotonic()
    started = jobs.start_job(workspace, step, params)
    try:
        terminal = _wait_job(started["job_id"], timeout_seconds)
    except TimeoutError as exc:
        raise DramaSmokeTimeout("text") from exc
    if terminal.get("status") != "succeeded":
        summary = terminal.get("result_summary") or {}
        raise RuntimeError(f"{step} did not succeed: {summary.get('error_code') or terminal.get('status')}")
    return {
        "step": step,
        "status": "succeeded",
        "job_id": started["job_id"],
        "summary": terminal.get("result_summary") or {},
        "elapsed_seconds": round(max(0.0, time.monotonic() - started_at), 3),
    }


def _create_workspace(workspace: str, track: str) -> None:
    wizard = _wizard_module()
    payload = {
        "workspace": workspace,
        "topic": "原创都市悬疑：失忆调香师发现每瓶香水都封存一段未来记忆",
        "track": track,
        "episode_count": 2,
        "episode_duration_seconds": 60,
        "budget_cny": 0,
        "timeout_minutes": 10,
    }
    status, _ct, body = wizard.start_drama_workspace(
        json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        "application/json",
    )
    if status != 200:
        raise RuntimeError(f"failed to create isolated smoke workspace (status={status})")


def run_smoke(
    workspace: str,
    *,
    track: str = "推理",
    real_text: bool = False,
    real_image: bool = False,
    timeout_seconds: float = 900.0,
    budget_cny: float = 0.0,
    reset_jobs: bool = True,
    completed_steps: Iterable[str] = (),
    on_step_start: Callable[[str], None] | None = None,
    on_step_complete: Callable[[str, Dict[str, Any]], None] | None = None,
    create_workspace: bool = True,
    confirm_text_retry: bool = False,
    confirm_upstream_status_and_billing_checked: bool = False,
) -> Dict[str, Any]:
    if not math.isfinite(budget_cny) or budget_cny < 0:
        raise SystemExit("budget-cny must be finite and non-negative")
    if not real_text:
        # Explicit process-local pin: a real-model .env can never leak into the
        # default or image-only smoke's five text stations.
        os.environ["OPENAI_MODEL"] = "mock"
        os.environ["DRAMA_MODEL"] = "mock"
    elif os.getenv("CONFIRM_REAL_MODEL_SMOKE") != "可以跑了":
        raise SystemExit("refusing real drama text smoke without explicit confirmation")
    elif not math.isfinite(budget_cny) or budget_cny <= 0:
        raise SystemExit("real drama text smoke requires a positive budget-cny")
    elif not real_text_tasks_ready():
        errors = real_text_readiness_errors()
        if any(error.endswith(":model_mock") for error in errors):
            raise RuntimeError("real_text_tasks_still_mock")
        validate_real_text_tasks_ready()

    if real_image:
        raise SystemExit(
            "legacy drama_smoke real-image mode is disabled; use drama_multimodal_smoke "
            "for budgeted all-character image testing"
        )

    if create_workspace:
        _create_workspace(workspace, track)
    if reset_jobs:
        jobs = _jobs_module()
        jobs.reset_for_tests()
    steps = []
    completed = set(completed_steps)
    started_at = time.time()
    deadline = time.monotonic() + timeout_seconds
    baseline_cost = float(collect_drama_insights(workspace)["llm_cost"]["cost_cny"] or 0)
    for step in ("drama-plan", "drama-hooks"):
        if step in completed:
            steps.append({"step": step, "status": "resumed-skip"})
            continue
        remaining_seconds = deadline - time.monotonic()
        spent = max(0.0, float(collect_drama_insights(workspace)["llm_cost"]["cost_cny"] or 0) - baseline_cost)
        remaining_budget = max(0.0, budget_cny - spent) if real_text else 0.0
        if real_text and (remaining_seconds <= 0 or remaining_budget <= 0):
            raise DramaSmokeTimeout("text") if remaining_seconds <= 0 else RuntimeError("drama text smoke budget exhausted")
        if on_step_start is not None:
            on_step_start(step)
        steps.append(_run_step(
            workspace, step, 1, remaining_seconds, real_text=real_text, budget_cny=remaining_budget,
            confirm_text_retry=confirm_text_retry,
            confirm_upstream_status_and_billing_checked=confirm_upstream_status_and_billing_checked,
        ))
        actual = max(0.0, float(collect_drama_insights(workspace)["llm_cost"]["cost_cny"] or 0) - baseline_cost)
        steps[-1]["actual_cost_cny"] = round(actual, 6)
        steps[-1]["remaining_budget_cny"] = round(max(0.0, budget_cny - actual), 6)
        steps[-1]["remaining_seconds"] = round(max(0.0, deadline - time.monotonic()), 3)
        if on_step_complete is not None and step != "drama-hooks":
            on_step_complete(step, steps[-1])
        if real_text and actual > budget_cny:
            raise RuntimeError("drama text smoke budget exceeded")

    ep = episode_paths(workspace)
    candidates = read_json_optional(ep.hook_candidates_path, {})
    hooks = candidates.get("hooks") if isinstance(candidates, dict) else None
    setup = read_json_optional(ep.setup_path, {})
    if not isinstance(setup, dict):
        raise RuntimeError("drama plan did not persist setup")
    if isinstance(hooks, list) and len(hooks) == 3:
        setup["hook"] = hooks[0]
        write_json(ep.setup_path, setup)
        ep.hook_candidates_path.unlink(missing_ok=True)
    elif not isinstance(setup.get("hook"), dict):
        raise RuntimeError("drama hook job did not persist three candidates")
    if "drama-hooks" not in completed and on_step_complete is not None:
        hook_result = next(row for row in reversed(steps) if row.get("step") == "drama-hooks")
        on_step_complete("drama-hooks", hook_result)

    for step in ("drama-storyboard", "drama-characters", "drama-review-assemble"):
        if step in completed:
            steps.append({"step": step, "status": "resumed-skip"})
            continue
        remaining_seconds = deadline - time.monotonic()
        spent = max(0.0, float(collect_drama_insights(workspace)["llm_cost"]["cost_cny"] or 0) - baseline_cost)
        remaining_budget = max(0.0, budget_cny - spent) if real_text else 0.0
        if real_text and (remaining_seconds <= 0 or remaining_budget <= 0):
            raise DramaSmokeTimeout("text") if remaining_seconds <= 0 else RuntimeError("drama text smoke budget exhausted")
        if on_step_start is not None:
            on_step_start(step)
        steps.append(_run_step(
            workspace, step, 1, remaining_seconds, real_text=real_text, budget_cny=remaining_budget,
            confirm_text_retry=confirm_text_retry,
            confirm_upstream_status_and_billing_checked=confirm_upstream_status_and_billing_checked,
        ))
        actual = max(0.0, float(collect_drama_insights(workspace)["llm_cost"]["cost_cny"] or 0) - baseline_cost)
        steps[-1]["actual_cost_cny"] = round(actual, 6)
        steps[-1]["remaining_budget_cny"] = round(max(0.0, budget_cny - actual), 6)
        steps[-1]["remaining_seconds"] = round(max(0.0, deadline - time.monotonic()), 3)
        if on_step_complete is not None:
            on_step_complete(step, steps[-1])
        if real_text and actual > budget_cny:
            raise RuntimeError("drama text smoke budget exceeded")

    exports = {}
    for fmt in ("json", "md", "csv", "comfy"):
        artifact = drama_store.export_episode(workspace, episode_no=1, format=fmt)
        exports[fmt] = {"filename": artifact.filename, "bytes": len(artifact.body)}
    insights = collect_drama_insights(workspace)
    result = {
        "ok": True,
        "workspace": workspace,
        "real_text": real_text,
        "real_image": real_image,
        "video_requests": 0,
        "elapsed_seconds": round(time.time() - started_at, 3),
        "steps": steps,
        "exports": exports,
        "llm_calls": insights.get("llm_cost", {}).get("calls", 0),
        "cost_cny": round(max(0.0, float(insights.get("llm_cost", {}).get("cost_cny", 0.0) or 0) - baseline_cost), 6),
        "remaining_budget_cny": round(max(0.0, budget_cny - max(0.0, float(insights.get("llm_cost", {}).get("cost_cny", 0.0) or 0) - baseline_cost)), 6),
        "remaining_seconds": round(max(0.0, deadline - time.monotonic()), 3),
        "image": None,
    }
    log_path = paths.WORKSPACE_DIR / workspace / "logs" / f"drama_smoke_{int(time.time())}.json"
    write_json(log_path, result)
    result["log_path"] = str(log_path.relative_to(paths.WORKSPACE_DIR / workspace))
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--book", required=True)
    parser.add_argument("--track", default="推理", choices=("霸总", "重生", "推理", "系统", "觉醒"))
    parser.add_argument("--real-text", action="store_true")
    parser.add_argument("--real-image", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=900.0)
    parser.add_argument("--budget-cny", type=float, default=0.0)
    args = parser.parse_args()
    if not (0 < args.timeout_seconds <= 86400):
        raise SystemExit("timeout-seconds must be in (0, 86400]")
    if not math.isfinite(args.budget_cny) or args.budget_cny < 0:
        raise SystemExit("budget-cny must be finite and non-negative")
    if args.real_text and args.budget_cny <= 0:
        raise SystemExit("real drama text smoke requires a positive budget-cny")
    if args.real_image:
        print(json.dumps({
            "ok": False,
            "workspace": args.book,
            "real_text": args.real_text,
            "real_image": True,
            "video_requests": 0,
            "error_code": "legacy_real_image_requires_multimodal",
        }, ensure_ascii=False))
        return 64
    if (
        args.real_text
        and os.getenv("CONFIRM_REAL_MODEL_SMOKE") == "可以跑了"
        and not real_text_tasks_ready()
    ):
        print(json.dumps({
            "ok": False,
            "workspace": args.book,
            "real_text": True,
            "real_image": args.real_image,
            "video_requests": 0,
            "error_code": "real_text_tasks_still_mock",
        }, ensure_ascii=False))
        return 64
    try:
        result = run_smoke(
            args.book,
            track=args.track,
            real_text=args.real_text,
            real_image=args.real_image,
            timeout_seconds=args.timeout_seconds,
            budget_cny=args.budget_cny,
        )
    except Exception as exc:
        if isinstance(exc, DramaSmokeTimeout):
            code = "real_image_timeout" if exc.stage == "image" else "drama_text_timeout"
        else:
            code = "drama_smoke_failed"
        safe = {
            "ok": False,
            "workspace": args.book,
            "real_text": args.real_text,
            "real_image": args.real_image,
            "video_requests": 0,
            "error_code": code,
        }
        root = paths.WORKSPACE_DIR / args.book
        if root.is_dir():
            write_json(root / "logs" / f"drama_smoke_failed_{int(time.time())}.json", safe)
        print(json.dumps(safe, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
