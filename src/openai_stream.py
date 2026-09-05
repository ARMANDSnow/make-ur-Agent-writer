"""Opt-in OpenAI streaming with cooperative cancellation and a total deadline."""
from __future__ import annotations

import asyncio
import json
import math
import multiprocessing
import os
import re
import select
import struct
import time
from contextlib import suppress
from typing import Any, Callable


MAX_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_REQUEST_BYTES = 8 * 1024 * 1024
MAX_RESULT_BYTES = 6 * MAX_RESPONSE_BYTES + 8192


class BoundedStreamFailure(RuntimeError):
    """An incomplete submitted stream must never trigger an automatic retry."""


async def _wait(awaitable: Any, deadline: float, check: Callable[[], None]) -> Any:
    task = asyncio.ensure_future(awaitable)
    try:
        while True:
            check()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BoundedStreamFailure("stream deadline exceeded")
            done, _ = await asyncio.wait({task}, timeout=min(0.1, remaining))
            if task in done:
                # Observe a cancellation/deadline that raced with the response.
                check()
                if time.monotonic() >= deadline:
                    raise BoundedStreamFailure("stream deadline exceeded")
                return task.result()
    finally:
        if not task.done():
            task.cancel()
        with suppress(BaseException):
            await task


async def _receive(kwargs: dict[str, Any], check: Callable[[], None]) -> tuple[str, dict]:
    # Native SDK preserves provider usage instead of filling missing usage
    # with LiteLLM's local token estimate. Import stays outside mock execution.
    from openai import AsyncOpenAI

    timeout = float(kwargs.get("timeout", 60))
    if not math.isfinite(timeout) or timeout <= 0:
        raise BoundedStreamFailure("invalid stream timeout")
    deadline = time.monotonic() + timeout
    if kwargs.get("_deadline") is not None:
        deadline = min(deadline, float(kwargs["_deadline"]))
    client = AsyncOpenAI(api_key=kwargs.get("api_key"), base_url=kwargs.get("api_base"),
                         timeout=timeout, max_retries=0)
    stream = None
    try:
        model = kwargs["model"].removeprefix("openai/")
        options = {"model": model, "messages": kwargs["messages"], "stream": True,
                   "stream_options": {"include_usage": True}}
        if re.match(r"^(gpt-5(?:[.-]|$)|o[134](?:[.-]|$))", model):
            options["max_completion_tokens"] = kwargs["max_tokens"]
        else:
            options.update(temperature=kwargs["temperature"], max_tokens=kwargs["max_tokens"])
        stream = await _wait(client.chat.completions.create(**options), deadline, check)
        parts: list[str] = []
        size = 0
        usage = None
        finish = None
        iterator = stream.__aiter__()
        while True:
            try:
                chunk = await _wait(iterator.__anext__(), deadline, check)
            except StopAsyncIteration:
                break
            if chunk.usage is not None:
                raw_usage = chunk.usage.model_dump()
                usage = {key: raw_usage[key] for key in ("prompt_tokens", "completion_tokens") if key in raw_usage}
            if chunk.choices:
                choice = chunk.choices[0]
                if choice.finish_reason is not None:
                    finish = choice.finish_reason
                piece = choice.delta.content or ""
                size += len(piece.encode("utf-8"))
                if size > MAX_RESPONSE_BYTES:
                    raise BoundedStreamFailure("stream response too large")
                parts.append(piece)
        content = "".join(parts)
        if finish != "stop" or not content.strip():
            raise BoundedStreamFailure("stream response incomplete")
        response = {"choices": [{"message": {"content": content}}]}
        if usage is not None:
            response["usage"] = usage
        return content, response
    finally:
        # SDK/httpx cancellation closes the pending read. Bound normal cleanup
        # too; it must neither replace the original error nor retry a request.
        if stream is not None:
            with suppress(Exception):
                await asyncio.wait_for(stream.close(), timeout=1)
        with suppress(Exception):
            await asyncio.wait_for(client.close(), timeout=1)


def _worker(connection: Any) -> None:
    """Only transport work runs here; no business writes, counters or logs."""
    try:
        kwargs = json.loads(connection.recv_bytes(MAX_REQUEST_BYTES))
        content, response = asyncio.run(_receive(kwargs, lambda: None))
        payload = [True, content, response.get("usage")]
    except BaseException:
        payload = [False, "", None]
    try:
        with suppress(OSError, EOFError):
            connection.send_bytes(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    finally:
        connection.close()


def receive(kwargs: dict[str, Any], check: Callable[[], None]) -> tuple[str, dict]:
    """Bound even SDK cleanup/DNS waits; credentials travel only through IPC."""
    timeout = float(kwargs.get("timeout", 60))
    if not math.isfinite(timeout) or timeout <= 0:
        raise BoundedStreamFailure("invalid stream timeout")
    deadline = time.monotonic() + timeout
    if kwargs.get("_deadline") is not None:
        deadline = min(deadline, float(kwargs["_deadline"]))
    payload = json.dumps({**kwargs, "_deadline": deadline}, ensure_ascii=False).encode("utf-8")
    if len(payload) > MAX_REQUEST_BYTES:
        raise BoundedStreamFailure("stream request too large")
    pending = memoryview(struct.pack("!i", len(payload)) + payload)
    sent = 0
    context = multiprocessing.get_context("spawn")
    reader, sender = context.Pipe(duplex=True)
    # Keep spawn bootstrap small: a large prompt must never block start().
    # Both request and result bytes cross the nonblocking parent loop below.
    process = context.Process(target=_worker, args=(sender,), daemon=True)
    try:
        check()
        if time.monotonic() >= deadline:
            raise BoundedStreamFailure("stream deadline exceeded")
        process.start()
        sender.close()
        fd = reader.fileno()
        os.set_blocking(fd, False)
        buffer = bytearray()
        expected = None
        while True:
            check()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise BoundedStreamFailure("stream deadline exceeded")
            readable, writable, _ = select.select([fd], [fd] if sent < len(pending) else [], [], min(.1, remaining))
            if writable:
                try:
                    sent += os.write(fd, pending[sent:sent+65536])
                except BlockingIOError:
                    pass
            if readable:
                try:
                    data = os.read(fd, 65536)
                except BlockingIOError:
                    continue
                if not data:
                    raise BoundedStreamFailure("stream worker stopped")
                buffer.extend(data)
                if expected is None and len(buffer) >= 4:
                    expected = struct.unpack("!i", buffer[:4])[0]
                    if expected < 0 or expected > MAX_RESULT_BYTES:
                        raise BoundedStreamFailure("invalid stream result size")
                if expected is None or len(buffer) < expected + 4:
                    continue
                succeeded, content, usage = json.loads(buffer[4:expected+4])
                check()
                if time.monotonic() >= deadline or not succeeded:
                    raise BoundedStreamFailure("stream did not complete")
                if not isinstance(content, str) or len(content.encode("utf-8")) > MAX_RESPONSE_BYTES:
                    raise BoundedStreamFailure("invalid stream content size")
                response = {"choices": [{"message": {"content": content}}]}
                if usage is not None:
                    response["usage"] = usage
                return content, response
    finally:
        reader.close()
        sender.close()
        if process.pid is not None:
            process.join(timeout=.1)
            if process.is_alive():
                process.terminate()
                process.join(timeout=.2)
            if process.is_alive():
                process.kill()
                process.join(timeout=.2)
            process.close()
