"""Calling one connected app's tool from code: the watch's plumbing. Over streamable HTTP or stdio, with the app's
saved spec from mcp.json; the result is its text. Events over 1 MB arrive (odie.plugins.mcp raised the limit)."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx2
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

import odie.plugins.mcp  # noqa: F401  (imported for its 32 MB event limit)
from odie.plugins.mcp import server_env


@dataclass
class Result:
    text: str
    is_error: bool


class CallError(Exception):
    """The app didn't answer, timed out or refused, in plain words."""


def _leaf(e: BaseException) -> str:
    subs = getattr(e, "exceptions", None)
    if subs:
        return _leaf(subs[0])
    return f"{type(e).__name__}: {e}"[:300] if str(e) else type(e).__name__


async def _with_session(spec: dict, fn: Callable[[ClientSession], Awaitable[Any]]) -> Any:
    if spec.get("url"):
        client = httpx2.AsyncClient(headers=dict(spec.get("headers") or {}), timeout=httpx2.Timeout(30, read=300))
        async with client, streamable_http_client(spec["url"], http_client=client) as streams:
            async with ClientSession(streams[0], streams[1]) as s:
                await s.initialize()
                return await fn(s)
    params = StdioServerParameters(command=spec["command"], args=list(spec.get("args") or []),
                                   env={**server_env(), **(spec.get("env") or {})})
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as s:
            await s.initialize()
            return await fn(s)


async def _bounded(spec: dict, fn, timeout: float, what: str):
    try:
        return await asyncio.wait_for(_with_session(spec, fn), timeout)
    except TimeoutError:
        raise CallError(f"{what} took longer than {timeout:g} seconds") from None
    except (KeyboardInterrupt, asyncio.CancelledError):
        raise
    except BaseException as e:  # noqa: BLE001 (anything else is a plain reason)
        raise CallError(_leaf(e)) from None


async def call_tool(spec: dict, tool: str, args: dict, timeout: float = 120) -> Result:
    async def fn(s: ClientSession) -> Result:
        out = await s.call_tool(tool, args)
        text = "".join(getattr(c, "text", "") or "" for c in (out.content or []))
        return Result(text, bool(getattr(out, "is_error", False) or getattr(out, "isError", False)))
    return await _bounded(spec, fn, timeout, tool)


async def list_tools(spec: dict, timeout: float = 60) -> list[dict]:
    async def fn(s: ClientSession) -> list[dict]:
        tools = (await s.list_tools()).tools
        return [{"name": t.name, "description": t.description or "",
                 "input_schema": getattr(t, "input_schema", None) or getattr(t, "inputSchema", None) or {}} for t in tools]
    return await _bounded(spec, fn, timeout, "listing the tools")
