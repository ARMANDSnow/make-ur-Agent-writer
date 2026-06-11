"""Async HTTP client for the continuer WebUI job API (iter 049).

Zero third-party dependencies: blocking ``urllib`` calls are offloaded to a
worker thread via ``asyncio.to_thread`` so the public coroutine methods never
stall the caller's event loop (Aeloon / MCP hosts are asyncio-based). The
contract mirrors ``src/web/routes.py`` — see ``docs/iterations/iteration_049_PLAN.md``.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import time
import urllib.error
import urllib.request
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple, Union
from urllib.parse import quote

from .errors import NovelApiError

# Job statuses that mean "stop polling" (jobs.py worker outcomes).
TERMINAL_STATUSES = frozenset(
    {"succeeded", "blocked", "failed", "aborted", "lost", "budget_exceeded"}
)

ProgressCallback = Callable[[str, float], Union[None, Awaitable[None]]]


async def _maybe_await(result: Union[None, Awaitable[None]]) -> None:
    if inspect.isawaitable(result):
        await result


class NovelClient:
    """Thin async wrapper over the WebUI's REST + job API."""

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8765",
        *,
        api_token: Optional[str] = None,
        request_timeout_s: float = 30.0,
        poll_interval_s: float = 2.0,
        job_timeout_s: float = 3600.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token or None
        self.request_timeout_s = float(request_timeout_s)
        self.poll_interval_s = float(poll_interval_s)
        self.job_timeout_s = float(job_timeout_s)

    # ---- deep link ---------------------------------------------------------

    def workbench_url(self, workspace: str) -> str:
        """Stable browser deep-link to the four-stage workbench (routes.py:1301)."""
        return f"{self.base_url}/w/{quote(workspace, safe='')}/workbench"

    # ---- low-level transport ----------------------------------------------

    def _request_sync(
        self, method: str, path: str, payload: Optional[Dict[str, Any]] = None
    ) -> Tuple[int, Any]:
        url = self.base_url + path
        headers = {"Accept": "application/json"}
        data: Optional[bytes] = None
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.request_timeout_s) as resp:
                status = int(resp.status)
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            status = int(exc.code)
            raw = exc.read()
        except urllib.error.URLError as exc:
            raise NovelApiError(
                0, None, f"cannot reach continuer at {self.base_url}: {exc.reason}"
            ) from exc
        body: Any = {}
        if raw:
            try:
                body = json.loads(raw.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                body = {"_raw": raw.decode("utf-8", "replace")}
        if status >= 400:
            msg = body.get("error") if isinstance(body, dict) else None
            raise NovelApiError(status, body, msg)
        return status, body

    async def _request(
        self, method: str, path: str, payload: Optional[Dict[str, Any]] = None
    ) -> Any:
        _status, body = await asyncio.to_thread(self._request_sync, method, path, payload)
        return body

    @staticmethod
    def _ws(workspace: str) -> str:
        return quote(workspace, safe="")

    # ---- endpoints ---------------------------------------------------------

    async def create_premise(self, workspace: str, premise: str) -> Dict[str, Any]:
        """POST /api/wizard/premise-start → {"name": ...}. Creates the
        workspace + seed; does NOT start a job."""
        return await self._request(
            "POST",
            "/api/wizard/premise-start",
            {"workspace": workspace, "premise": premise},
        )

    async def list_workspaces(self) -> List[str]:
        body = await self._request("GET", "/api/workspaces/")
        names = body.get("workspaces") if isinstance(body, dict) else None
        return [str(n) for n in names] if isinstance(names, list) else []

    async def status(self, workspace: str) -> Dict[str, Any]:
        return await self._request("GET", f"/api/workspace/{self._ws(workspace)}/status")

    async def workbench(self, workspace: str) -> Dict[str, Any]:
        return await self._request("GET", f"/api/workspace/{self._ws(workspace)}/workbench")

    async def plan(self, workspace: str) -> Dict[str, Any]:
        return await self._request("GET", f"/api/workspace/{self._ws(workspace)}/plan")

    async def save_outline(self, workspace: str, outline: str) -> Dict[str, Any]:
        return await self._request(
            "PUT", f"/api/workspace/{self._ws(workspace)}/outline", {"outline": outline}
        )

    async def readiness(
        self,
        workspace: str,
        *,
        chapters: int = 1,
        resume_from: int = 1,
        replan_every: int = 0,
    ) -> Dict[str, Any]:
        path = (
            f"/api/workspace/{self._ws(workspace)}/readiness"
            f"?chapters={int(chapters)}&resume_from={int(resume_from)}"
            f"&replan_every={int(replan_every)}"
        )
        return await self._request("GET", path)

    async def run_step(
        self, workspace: str, step: str, params: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """POST /api/workspace/<ws>/run → {"job_id", "status", "step"}."""
        return await self._request(
            "POST",
            f"/api/workspace/{self._ws(workspace)}/run",
            {"step": step, "params": params or {}},
        )

    async def get_job(self, workspace: str, job_id: str) -> Dict[str, Any]:
        return await self._request(
            "GET", f"/api/workspace/{self._ws(workspace)}/job/{self._ws(job_id)}"
        )

    async def cancel_job(self, workspace: str, job_id: str) -> Dict[str, Any]:
        return await self._request(
            "POST", f"/api/workspace/{self._ws(workspace)}/job/{self._ws(job_id)}/cancel"
        )

    # ---- orchestration -----------------------------------------------------

    async def run_and_wait(
        self,
        workspace: str,
        step: str,
        params: Optional[Dict[str, Any]] = None,
        *,
        on_progress: Optional[ProgressCallback] = None,
        poll_interval_s: Optional[float] = None,
        job_timeout_s: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Start a step job and poll until it reaches a terminal status.

        ``on_progress(current_step, progress)`` fires on each *change* of
        progress (sync or async callback). Returns the final job record (its
        ``status`` is one of :data:`TERMINAL_STATUSES`). Raises
        :class:`NovelApiError` on transport/API failure; on a client-side
        timeout it requests cancellation and raises ``NovelApiError(0, ...)``.
        """
        started = await self.run_step(workspace, step, params)
        job_id = started.get("job_id")
        if not isinstance(job_id, str):
            raise NovelApiError(0, started, "run did not return a job_id")

        interval = poll_interval_s if poll_interval_s is not None else self.poll_interval_s
        timeout = job_timeout_s if job_timeout_s is not None else self.job_timeout_s
        deadline = time.monotonic() + timeout
        last_progress = -1.0

        while True:
            job = await self.get_job(workspace, job_id)
            status = str(job.get("status") or "")
            current = str(job.get("current_step") or step)
            try:
                progress = float(job.get("progress") or 0.0)
            except (TypeError, ValueError):
                progress = 0.0
            if on_progress is not None and progress != last_progress:
                await _maybe_await(on_progress(current, progress))
                last_progress = progress
            if status in TERMINAL_STATUSES:
                return job
            if time.monotonic() >= deadline:
                try:
                    await self.cancel_job(workspace, job_id)
                except NovelApiError:
                    pass
                raise NovelApiError(
                    0, job, f"job {job_id} did not finish within {timeout:.0f}s"
                )
            await asyncio.sleep(interval)
