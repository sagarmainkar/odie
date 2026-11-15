"""The recall tool: one search over past chats and everything remembered, in place of search_memories."""
from __future__ import annotations

import logging
from datetime import date
from typing import TYPE_CHECKING

from google.adk.tools import FunctionTool

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


def make_recall_tool(store, memory: MemoryFile) -> FunctionTool:
    async def recall(query: str, since: str | None = None, until: str | None = None) -> str:
        """Search what you and the user said in past chats, and everything remembered about them, by meaning. Use it
        when they refer to something from before ("what did we decide about…", "like last time"), or when nothing
        listed in What you remember fits. since, until: ISO dates. Lines are tagged [chat <day>] or [memory]. Say when
        something was said."""
        from odie.recall.fill import recall_index
        from odie.vault.settings import embedder_for
        try:
            index = recall_index()
            hits = await index.search(query, k=HITS, embedder=embedder_for(store), since=since, until=until)
        except Exception:  # the index won't open, or its search breaks: the memory file's words answer
            log.warning("recall: past chats couldn't be searched; answering from the memory file's words", exc_info=True)
            return memory_words(memory, query)
        if not hits:
            return NOTHING
        return "\n".join(hit_line(h) for h in hits)

    return FunctionTool(recall)


def memory_words(memory: MemoryFile, query: str) -> str:
    """The fallback when the recall index can't be opened or searched: the memory file searched by words, and a line saying past
    chats aren't there. "rent" with a Rent day memory -> its memory line, then the note; nothing matching -> NOTHING,
    then the note."""
    entries = memory.load().entries() if memory.exists() else []
    found = search(entries, query, limit=5)
    lines = [memory_line(h.entry.title, h.entry.date, h.entry.body) for h in found] or [NOTHING]
    return "\n".join([*lines, NOT_INDEXED])
