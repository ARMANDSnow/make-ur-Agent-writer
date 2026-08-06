"""Host-agnostic operations for the continuer (iter 049).

Each ``op_*`` coroutine returns a Markdown reply string and (for long jobs)
narrates progress through the optional ``emit`` callback. They map the
chat-friendly mental model — 开书 → 出细纲 → 写正文 — onto the WebUI's
prepare → debate → plan-chapters → write-book pipeline.
"""

from __future__ import annotations

import inspect
import re
from typing import Any, Awaitable, Callable, Dict, Optional, Tuple, Union

from ..novel_client import NovelApiError, NovelClient
from . import formatting as fmt
from .config import NovelOpsConfig

Emit = Callable[[str], Union[None, Awaitable[None]]]

_VALID_NAME = re.compile(r"[^0-9A-Za-z_一-鿿]")


async def _maybe_await(result: Union[None, Awaitable[None]]) -> None:
    if inspect.isawaitable(result):
        await result


def _safe_ws_name(raw: str) -> str:
    """Derive a server-valid workspace name (src/web/wizard._validate_name:
    only [A-Za-z0-9_ + CJK]). Falls back to ``novel`` when nothing survives."""
    kept = _VALID_NAME.sub("", raw or "")
    return kept[:32] or "novel"


def _emitter(emit: Optional[Emit], label: str):
    """Adapt an ``emit(text)`` into a NovelClient ``on_progress(step, frac)``."""
    if emit is None:
        return None

    async def _cb(step: str, frac: float) -> None:
        pct = int(max(0.0, min(1.0, frac)) * 100)
        await _maybe_await(emit(f"{label} … {pct}%"))

    return _cb


def _creation_policy(status: Dict[str, Any]) -> Tuple[str, bool]:
    """Read the server-authoritative creation policy, failing closed.

    Older servers may omit the new fields.  In that case an explicit
    ``has_start_point`` still proves continuation; every other ambiguous
    response conservatively requires a start point instead of silently
    selecting the greenfield path.
    """

    mode = status.get("creation_mode")
    requires = status.get("requires_start_point")
    if mode in {"greenfield", "continuation"} and type(requires) is bool:
        if requires == (mode == "continuation"):
            return str(mode), requires
        return "continuation", True
    if mode == "continuation" or status.get("has_start_point") is True:
        return "continuation", True
    return "continuation", True


def _prepare_step(status: Dict[str, Any]) -> Optional[Tuple[str, Dict[str, Any]]]:
    _mode, requires_start = _creation_policy(status)
    if not requires_start:
        return "prepare-greenfield", {}
    if status.get("has_start_point") is True:
        return "rebuild-for-start", {"window": 10}
    return None


async def _resolve_book(
    client: NovelClient, book: Optional[str], cfg: NovelOpsConfig
) -> Tuple[Optional[str], Optional[str]]:
    """Return ``(name, error_md)``. Resolution order: explicit > config
    default > the sole workspace > ask the user."""
    if book and book.strip():
        return book.strip(), None
    if cfg.default_book:
        return cfg.default_book, None
    names = await client.list_workspaces()
    if len(names) == 1:
        return names[0], None
    return None, fmt.fmt_need_book(names)


# ---- operations ------------------------------------------------------------


async def op_list(client: NovelClient, *, cfg: NovelOpsConfig = NovelOpsConfig()) -> str:
    try:
        names = await client.list_workspaces()
    except NovelApiError as exc:
        return fmt.fmt_api_error(None, exc)
    return fmt.fmt_list(names)


async def op_open(
    client: NovelClient, book: Optional[str] = None, *, cfg: NovelOpsConfig = NovelOpsConfig()
) -> str:
    name, err = await _resolve_book(client, book, cfg)
    if err:
        return err
    return f"🔗 《{name}》工作台：{fmt.open_link(client.workbench_url(name))}"


async def op_status(
    client: NovelClient, book: Optional[str] = None, *, cfg: NovelOpsConfig = NovelOpsConfig()
) -> str:
    name, err = await _resolve_book(client, book, cfg)
    if err:
        return err
    try:
        wb = await client.workbench(name)
    except NovelApiError as exc:
        return fmt.fmt_api_error(name, exc)
    return fmt.fmt_status(name, wb, client.workbench_url(name))


async def op_new(
    client: NovelClient,
    premise: str,
    name: Optional[str] = None,
    *,
    emit: Optional[Emit] = None,
    cfg: NovelOpsConfig = NovelOpsConfig(),
) -> str:
    if not premise or not premise.strip():
        return "请给一句话设定，例如 `/novel new 一个赛博朋克侦探在雨夜追查记忆窃贼`。"
    ws = _safe_ws_name(name or premise)
    try:
        created = await client.create_premise(ws, premise.strip())
    except NovelApiError as exc:
        if exc.status_code == 409:
            return f"⚠️ 工作区《{ws}》已存在。换个名字：`/novel new {premise.strip()[:20]}… as 新名字`。"
        return fmt.fmt_api_error(ws, exc)
    book = created.get("name") or ws
    url = client.workbench_url(book)
    # Ask the server which preparation path belongs to this workspace.  The
    # premise endpoint currently creates greenfield books, but the integration
    # must not duplicate that policy or bypass a future server-side change.
    try:
        wb = await client.workbench(book)
        preparation = _prepare_step(wb)
        if preparation is None:
            return (
                f"✅ 已创建《{book}》，请先在工作台选择续写起点。\n\n"
                f"{fmt.open_link(url)}"
            )
        step, params = preparation
        await _maybe_await(emit(f"《{book}》开书成功，正在准备设定…") if emit else None)
        job = await client.run_and_wait(
            book, step, params, on_progress=_emitter(emit, "设定准备")
        )
    except NovelApiError as exc:
        return (
            f"✅ 已创建《{book}》，但设定准备没启动：{fmt.fmt_api_error(book, exc)}\n\n"
            f"可稍后 `/novel outline` 重试。{fmt.open_link(url)}"
        )
    if job.get("status") != "succeeded":
        return fmt.fmt_job_failure(book, step, job, url)
    return fmt.fmt_created(book, url)


async def op_prepare(
    client: NovelClient,
    book: Optional[str] = None,
    *,
    emit: Optional[Emit] = None,
    cfg: NovelOpsConfig = NovelOpsConfig(),
) -> str:
    name, err = await _resolve_book(client, book, cfg)
    if err:
        return err
    url = client.workbench_url(name)
    try:
        wb = await client.workbench(name)
        preparation = _prepare_step(wb)
        if preparation is None:
            return f"⚠️ 《{name}》请先在工作台选择续写起点。\n\n{fmt.open_link(url)}"
        step, params = preparation
        job = await client.run_and_wait(
            name, step, params, on_progress=_emitter(emit, "设定准备")
        )
    except NovelApiError as exc:
        return fmt.fmt_api_error(name, exc)
    if job.get("status") != "succeeded":
        return fmt.fmt_job_failure(name, step, job, url)
    return f"✅ 《{name}》设定准备完成。下一步 `/novel outline` 生成细纲。\n\n{fmt.open_link(url)}"


async def op_outline(
    client: NovelClient,
    book: Optional[str] = None,
    chapters: Optional[int] = None,
    *,
    emit: Optional[Emit] = None,
    cfg: NovelOpsConfig = NovelOpsConfig(),
) -> str:
    """Take a prepared book to a chapter plan, running debate (story outline)
    first when needed, then plan-chapters."""
    name, err = await _resolve_book(client, book, cfg)
    if err:
        return err
    url = client.workbench_url(name)
    n = int(chapters) if chapters else cfg.outline_chapters
    try:
        wb = await client.workbench(name)
    except NovelApiError as exc:
        return fmt.fmt_api_error(name, exc)
    stage = str(wb.get("stage") or "")
    _mode, requires_start = _creation_policy(wb)
    if stage == "start":
        return f"⚠️ 《{name}》请先在工作台选择续写起点。\n\n{fmt.open_link(url)}"
    if stage == "prepare":
        return f"⚠️ 《{name}》还没做设定准备。先 `/novel prepare`（或 `/novel new` 重新开书）。\n\n{fmt.open_link(url)}"
    try:
        # ② story outline via debate (only when missing)
        if not wb.get("has_outline"):
            job = await client.run_and_wait(
                name, "debate", {}, on_progress=_emitter(emit, "故事大纲")
            )
            if job.get("status") != "succeeded":
                return fmt.fmt_job_failure(name, "debate", job, url)
        # ③ chapter plan via plan-chapters
        job = await client.run_and_wait(
            name,
            "plan-chapters",
            {"target_chapters": n, "require_start_point": requires_start},
            on_progress=_emitter(emit, "章节细纲"),
        )
    except NovelApiError as exc:
        return fmt.fmt_api_error(name, exc)
    if job.get("status") != "succeeded":
        return fmt.fmt_job_failure(name, "plan-chapters", job, url)
    try:
        plan = await client.plan(name)
    except NovelApiError:
        plan = {}
    return fmt.fmt_outline_result(name, plan, url)


async def op_write(
    client: NovelClient,
    book: Optional[str] = None,
    chapters: Optional[int] = None,
    *,
    tier: Optional[str] = None,
    budget_cny: Optional[float] = None,
    emit: Optional[Emit] = None,
    cfg: NovelOpsConfig = NovelOpsConfig(),
) -> str:
    name, err = await _resolve_book(client, book, cfg)
    if err:
        return err
    url = client.workbench_url(name)
    n = int(chapters) if chapters else cfg.write_chapters
    try:
        readiness = await client.readiness(name, chapters=n)
    except NovelApiError as exc:
        return fmt.fmt_api_error(name, exc)
    if str(readiness.get("status")) not in {"ready", "warn"}:
        return fmt.fmt_readiness_block(name, readiness, url)
    _mode, requires_start = _creation_policy(readiness)
    params = {
        "chapters": n,
        "tier": tier or cfg.write_tier,
        "budget_cny": cfg.write_budget_cny if budget_cny is None else float(budget_cny),
        "require_start_point": requires_start,
    }
    try:
        job = await client.run_and_wait(
            name, "write-book", params, on_progress=_emitter(emit, "正文写作")
        )
    except NovelApiError as exc:
        return fmt.fmt_api_error(name, exc)
    if job.get("status") != "succeeded":
        return fmt.fmt_job_failure(name, "write-book", job, url)
    return fmt.fmt_write_result(name, job, url)


# stage -> (step, params-builder) for the one-shot auto pipeline
def _auto_step_for_stage(status: Dict[str, Any], n: int, cfg: NovelOpsConfig):
    stage = str(status.get("stage") or "")
    _mode, requires_start = _creation_policy(status)
    if stage == "prepare":
        preparation = _prepare_step(status)
        return preparation if preparation is not None else (None, None)
    if stage == "outline":
        return "debate", {}
    if stage == "plan":
        return "plan-chapters", {"target_chapters": cfg.outline_chapters, "require_start_point": requires_start}
    if stage == "write":
        return "write-book", {
            "chapters": n,
            "tier": cfg.write_tier,
            "budget_cny": cfg.write_budget_cny,
            "require_start_point": requires_start,
        }
    return None, None


async def op_auto(
    client: NovelClient,
    book: Optional[str] = None,
    chapters: Optional[int] = None,
    *,
    emit: Optional[Emit] = None,
    cfg: NovelOpsConfig = NovelOpsConfig(),
) -> str:
    """Drive the full pipeline from the book's current workbench stage to
    finished drafts, one step at a time."""
    name, err = await _resolve_book(client, book, cfg)
    if err:
        return err
    url = client.workbench_url(name)
    n = int(chapters) if chapters else cfg.write_chapters
    last_write: Optional[Dict[str, Any]] = None
    for _ in range(8):  # prepare→outline→plan→write is 4; cap guards loops
        try:
            wb = await client.workbench(name)
        except NovelApiError as exc:
            return fmt.fmt_api_error(name, exc)
        stage = str(wb.get("stage") or "")
        if stage not in {"start", "prepare", "outline", "plan", "write", "done"}:
            return (
                f"⚠️ 《{name}》的创作阶段暂时无法确认，未启动任何新任务。"
                f"请刷新工作台后重试。\n\n{fmt.open_link(url)}"
            )
        if stage == "start":
            return f"⚠️ 《{name}》请先在工作台选择续写起点。\n\n{fmt.open_link(url)}"
        if stage == "done":
            break
        step, params = _auto_step_for_stage(wb, n, cfg)
        if step is None:
            return (
                f"⚠️ 《{name}》的创作条件尚未确认，未启动任何新任务。"
                f"请在工作台完成当前必填项后重试。\n\n{fmt.open_link(url)}"
            )
        await _maybe_await(emit(f"《{name}》进行中：{fmt.step_label(step)}") if emit else None)
        try:
            job = await client.run_and_wait(
                name, step, params, on_progress=_emitter(emit, fmt.step_label(step))
            )
        except NovelApiError as exc:
            return fmt.fmt_api_error(name, exc)
        if job.get("status") != "succeeded":
            return fmt.fmt_job_failure(name, step, job, url)
        if step == "write-book":
            last_write = job
            break
    if last_write is not None:
        return fmt.fmt_write_result(name, last_write, url)
    return f"✅ 《{name}》流水线已推进到正文阶段。\n\n{fmt.open_link(url)}"
