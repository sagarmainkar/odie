"""The recall tool: one search over past chats and everything remembered, in place of search_memories."""
from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING

from google.adk.tools import FunctionTool, ToolContext

from odie.memory.search import search
from odie.memory.store import MemoryFile

if TYPE_CHECKING:  # only for the annotation: odie.recall.index reaches the runner, which imports the agent
    from odie.recall.index import RecallHit

log = logging.getLogger("odie.recall.tools")

HITS = 8  # lines a call returns at most
EXCERPT = 500  # characters of a passage in one line
NOTHING = "Nothing in past chats or memories matches that."
NOT_INDEXED = "(past chats aren't indexed yet)"


def excerpt(text: str) -> str:
    """A passage on one line, cut at 500 characters with an ellipsis. Newlines become " · ".
    Examples: "you: hi\\nOdie: hello" -> "you: hi · Odie: hello"; a 900-character passage -> its first 500 and "…"."""
    one_line = text.strip().replace("\n", " · ")
    if len(one_line) <= EXCERPT:
        return one_line
    return one_line[:EXCERPT] + "…"


def short_day(day: str) -> str:
    """An ISO day as the model should say it: "2026-11-03" -> "3 Nov"; anything else as it is."""
    try:
        return date.fromisoformat(day[:10]).strftime("%-d %b")
    except ValueError:
        return day


def memory_line(title: str, day: str, body: str) -> str:
    """A memory as one line: ("Rent day", "2026-10-01", "Paid on the first.") -> "[memory] Rent day (2026-10-01): Paid on
    the first."; with no date -> "[memory] Rent day: Paid on the first."."""
    when = f" ({day})" if day else ""
    return f"[memory] {title}{when}: {excerpt(body)}"


def hit_line(hit: RecallHit) -> str:
    """One hit as one line: a chat -> "[chat 3 Nov] you: … · Odie: …", a memory -> "[memory] <title> (<date>): <body>"."""
    if hit.kind == "chat":
        return f"[chat {short_day(hit.day)}] {excerpt(hit.text)}"
    return memory_line(hit.title, hit.day, hit.text)


def own_memory_lines(own: MemoryFile, query: str) -> list[str]:
    """A personality's own memories that match the question by words, as [memory] lines (its memory is never put in
    the recall index, so nobody else's search can reach it): "lighthouse plan" with that entry -> its line; no file
    yet, or nothing matching -> []."""
    if not own.exists():
        return []
    found = search(own.load().entries(), query, limit=5)
    return [memory_line(h.entry.title, h.entry.date, h.entry.body) for h in found]


def make_recall_tool(store, memory: MemoryFile, memory_for=None) -> FunctionTool:
    """`memory` is the shared memory; `memory_for` gives a chat's own (odie.memory.tools.memory_of_chat). Who may read
    what goes one way (odie.personalities.hidden_from): an everyday chat, and a turn in no chat at all, never finds a
    personality's chats or memories; a personality finds its own, and the everyday ones."""
    async def recall(query: str, since: str | None = None, until: str | None = None,
                     tool_context: ToolContext | None = None) -> str:
        """Search what you and the user said in past chats, and everything remembered about them, by meaning. Use it
        when they refer to something from before ("what did we decide about…", "like last time"), or when nothing
        listed in What you remember fits. since, until: ISO dates. Lines are tagged [chat <day>] or [memory]. Say when
        something was said."""
        from odie import personalities
        from odie.agent.context import session_id_of
        from odie.memory.tools import is_shared, memory_of_chat
        from odie.recall.fill import recall_index
        from odie.vault.settings import embedder_for
        asker = personalities.of_session(store, session_id_of(tool_context))
        hidden = personalities.hidden_from(store, asker)
        own = memory_of_chat(memory, memory_for, tool_context)
        own_lines: list[str] = []
        if not is_shared(own, memory):
            own_lines = own_memory_lines(own, query)
        try:
            index = recall_index()
            hits = await index.search(query, k=HITS, embedder=embedder_for(store), since=since, until=until,
                                      hidden_sessions=hidden)
        except Exception:  # the index won't open, or its search breaks: the memory files' words answer
            log.warning("recall: past chats couldn't be searched; answering from the memory file's words", exc_info=True)
            return memory_words(memory, query, own_lines)
        lines = [*own_lines, *(hit_line(h) for h in hits)]
        if not lines:
            return NOTHING
        return "\n".join(lines)

    return FunctionTool(recall)


def memory_words(memory: MemoryFile, query: str, own_lines: list[str] | None = None) -> str:
    """The fallback when the recall index can't be opened or searched: the memory file searched by words, and a line saying past
    chats aren't there. "rent" with a Rent day memory -> its memory line, then the note; nothing matching -> NOTHING,
    then the note. `own_lines`: a personality's own matching memories (own_memory_lines), which come first."""
    entries = memory.load().entries() if memory.exists() else []
    found = search(entries, query, limit=5)
    shared_lines = [memory_line(h.entry.title, h.entry.date, h.entry.body) for h in found]
    lines = [*(own_lines or []), *shared_lines] or [NOTHING]
    return "\n".join([*lines, NOT_INDEXED])
