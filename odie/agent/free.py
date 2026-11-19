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

    async def process_llm_request(self, *, tool_context, llm_request) -> None:
        """Passes the inner toolset's own words on (a skill toolset's catalog, a loaded app's instructions)."""
        await self.inner.process_llm_request(tool_context=tool_context, llm_request=llm_request)

    async def close(self) -> None:
        pass  # the inner toolset is the chat's; it closes with the app


class KeptToolset(BaseToolset):
    """A toolset standing in for another with only the tools `keep(name)` keeps: a background turn that may call a
    few tools (the watch's allow-list) is told about those alone, so an app's other tools (sending mail) are never
    declared to it. (calendar app's toolset, keep = the watch's list) -> its calendar writes only."""

    def __init__(self, inner: BaseToolset, keep, taken: frozenset[str] = frozenset()):
        super().__init__()
        self.inner = inner
        self.keep = keep
        self.taken = taken  # names a plain tool of the turn already has: declared once, the turn's own winning

    async def get_tools(self, readonly_context=None):
        tools = await self.inner.get_tools(readonly_context)
        return [t for t in tools if self.keep(t.name) and t.name not in self.taken]

    async def process_llm_request(self, *, tool_context, llm_request) -> None:
        """Passes the inner toolset's own words on: the calendar app's skill text reaches the turn."""
        await self.inner.process_llm_request(tool_context=tool_context, llm_request=llm_request)

    async def close(self) -> None:
        pass  # the inner toolset is the chat's; it closes with the app


def kept_tools(tools: list, keep) -> list:
    """Only the tools `keep(name)` keeps: a plain tool by its name (one per name, the turn's own winning), a toolset
    wrapped so it lists only those and none a plain tool already has (a toolset has no name of its own, so it is
    never dropped whole). keep None -> the same list."""
    if keep is None:
        return list(tools)
    plain: list = []
    for t in tools:  # each plain name once, the last given winning (the turn's own tools come after the chat's)
        if not isinstance(t, BaseToolset) and keep(getattr(t, "name", "")):
            plain = [p for p in plain if p.name != t.name] + [t]
    taken = frozenset(t.name for t in plain)
    sets = [KeptToolset(t, keep, taken) for t in tools if isinstance(t, BaseToolset)]
    return [*plain, *sets]


async def declared_once(plain: list, toolsets: list, readonly_context) -> list:
    """The tools a model is told about, each name once: the plain tools first (the turn's own), then each toolset's
    in order, a name already declared left out. (report from the watch, an app's report and calendar_create_event)
    -> the watch's report and the app's calendar_create_event."""
    out = list(plain)
    names = {t.name for t in out}
    for toolset in toolsets:
        for t in await toolset.get_tools(readonly_context):
            if t.name not in names:
                names.add(t.name)
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
