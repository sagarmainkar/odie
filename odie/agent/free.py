"""Tools let through without the user's tap for one background turn: the watch may add a calendar event, which in
chat (and in every other background check) asks first. The chat's own tool objects are never touched: an MCP
toolset builds its tools afresh on each get_tools, and a plain tool is copied, so only this turn's agent sees them
unlocked."""
from __future__ import annotations

import copy

from google.adk.tools.base_toolset import BaseToolset


def unlocked(tool):
    """A copy of the tool that runs without asking: the copy's require_confirmation is off, the original's as it was.
    (calendar_create_event, asks) -> a copy that doesn't ask"""
    freed = copy.copy(tool)
    freed._require_confirmation = False
    return freed


class FreedToolset(BaseToolset):
    """A toolset standing in for another, with the named tools unlocked."""

    def __init__(self, inner: BaseToolset, free: frozenset[str]):
        super().__init__()
        self.inner = inner
        self.free = free

    async def get_tools(self, readonly_context=None):
        tools = await self.inner.get_tools(readonly_context)
        return [unlocked(t) if t.name in self.free else t for t in tools]

    async def close(self) -> None:
        pass  # the inner toolset is the chat's; it closes with the app


class KeptToolset(BaseToolset):
    """A toolset standing in for another with only the tools `keep(name)` keeps: a background turn that may call a
    few tools (the watch's allow-list) is told about those alone, so an app's other tools (sending mail) are never
    declared to it. (calendar app's toolset, keep = the watch's list) -> its calendar writes only."""

    def __init__(self, inner: BaseToolset, keep):
        super().__init__()
        self.inner = inner
        self.keep = keep

    async def get_tools(self, readonly_context=None):
        tools = await self.inner.get_tools(readonly_context)
        return [t for t in tools if self.keep(t.name)]

    async def close(self) -> None:
        pass  # the inner toolset is the chat's; it closes with the app


def kept_tools(tools: list, keep) -> list:
    """Only the tools `keep(name)` keeps: a plain tool by its name, a toolset wrapped so it lists only those (a
    toolset has no name of its own, so it is never dropped whole). keep None -> the same list."""
    if keep is None:
        return list(tools)
    out = []
    for t in tools:
        if isinstance(t, BaseToolset):
            out.append(KeptToolset(t, keep))
        elif keep(getattr(t, "name", "")):
            out.append(t)
    return out


def free_tools(tools: list, free: frozenset[str]) -> list:
    """The agent's tool list for a background turn with `free` let through: a toolset is wrapped, a named plain tool
    is copied unlocked, everything else is passed as it is. ([search, calendar toolset], {"calendar_create_event"})
    -> [search, FreedToolset(calendar toolset)]; (anything, frozenset()) -> the same list"""
    if not free:
        return list(tools)
    out = []
    for t in tools:
        if isinstance(t, BaseToolset):
            out.append(FreedToolset(t, free))
        elif getattr(t, "name", None) in free:
            out.append(unlocked(t))
        else:
            out.append(t)
    return out
