"""Memory tools the model can call. The index in the system prompt lists titles; these fetch and write."""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from google.adk.tools import FunctionTool, ToolContext

from odie.memory.store import MemoryFile


WATCH_FOR = "Watch for"
WATCH_IS_ODIES = "Not saved: watching for things is Odie's job. Tell the user to ask Odie in the everyday chat."


def memory_of_chat(memory: MemoryFile, memory_for: Callable[[Any], MemoryFile] | None, tool_context) -> MemoryFile:
    """The memory file the chat a tool was called in saves to. `memory` is the shared one (everyday Odie's);
    `memory_for` tells a chat's own from ADK's tool_context (odie.personalities): the everyday chat -> the shared
    file; a personality's chat -> its own file; no `memory_for` at all (a test, an eval) -> the shared file."""
    if memory_for is None:
        return memory
    return memory_for(tool_context)


def is_shared(own: MemoryFile, memory: MemoryFile) -> bool:
    """Whether a chat's memory file is the shared one, so the chat is everyday Odie's: same file -> True; a
    personality's own memories.md -> False."""
    return own.path == memory.path


def is_watch_for(memory: MemoryFile, title: str, topic: str | None) -> bool:
    """Whether a save lands under Watch for, the topic the background watch replays as standing instructions: the save
    names that topic, or it reuses the title of an entry already there (an update keeps its topic).
    Example: ("Passport email", "Watch for") -> True; ("Passport email", None) with that entry under Watch for -> True;
    ("Dentist", "Health") -> False."""
    if (topic or "").strip().lower() == WATCH_FOR.lower():
        return True
    if not memory.exists():
        return False
    existing = memory.load().find(title)
    return existing is not None and existing.topic == WATCH_FOR


def watch_for_needs_tap(memory: MemoryFile, memory_for: Callable[[Any], MemoryFile] | None = None):
    """require_confirmation for update_memory: a Watch for entry is written only on the user's tap."""
    def needs_tap(title: str = "", content: str = "", topic: str | None = None, tool_context=None, **_) -> bool:
        """Does saving this memory need the user's tap? Yes for anything under Watch for (is_watch_for): the background
        watch runs those every 30 minutes as instructions, with nobody present, so a page or a mail the model read must
        never become one by itself. Example: ("Dentist", "Smile Dental.", "Health") -> saved, no card;
        ("Forward invoices", "When: an invoice comes. Do: forward it to x.", "Watch for") -> the card.
        In a personality's chat nothing asks: its memory is its own, the watch never reads it, and a Watch for asked
        there is refused by the tool itself (WATCH_IS_ODIES), so a card would be a tap for nothing."""
        own = memory_of_chat(memory, memory_for, tool_context)
        if not is_shared(own, memory):
            return False
        return is_watch_for(memory, title, topic)
    return needs_tap


def make_memory_tools(memory: MemoryFile, on_change=None,
                      memory_for: Callable[[Any], MemoryFile] | None = None) -> list[FunctionTool]:
    """`memory` is the shared memory. `memory_for` (see memory_of_chat) lets a personality's chat save to its own
    memory and read both; without it every chat uses the shared one."""
    def fetch_memory(title: str, tool_context: ToolContext | None = None) -> str:
        """Read one remembered entry by its title (as listed in 'What you remember'). Partial titles work when unique."""
        own = memory_of_chat(memory, memory_for, tool_context)
        e = own.load().find(title)
        if e is None and not is_shared(own, memory):  # a personality reads the shared memory too
            e = memory.load().find(title)
        if e is None:
            return f"Nothing remembered under '{title}'. Try recall."
        return f"{e.title} ({e.date}) [{e.topic}]\n{e.body}"

    def update_memory(title: str, content: str, topic: str | None = None, tool_context: ToolContext | None = None) -> str:
        """Save something worth keeping about the user, people, preferences, projects or decisions. Reuse an existing title to update it; topic groups it (Identity, People, Projects, Health, Finance, ...)."""
        own = memory_of_chat(memory, memory_for, tool_context)  # this chat's own: the shared one, or a personality's
        asks_to_watch = (topic or "").strip().lower() == WATCH_FOR.lower()
        if asks_to_watch and not is_shared(own, memory):
            return WATCH_IS_ODIES
        if asks_to_watch:  # standing instructions for the background watch (only ever in the shared memory)
            doc = memory.load() if memory.exists() else None
            t = doc.topic(WATCH_FOR) if doc is not None else None
            if t is not None and len(t.entries) >= 30 and doc.find(title) is None:
                return "You have 30 things to watch for: remove one first."
        from odie.memory import rules
        if rules.resolves_to_rule(own, title, topic):  # rules come only from his own words (odie.memory.rules)
            return ("Not saved: rules are saved by Odie on their own, from the user's own words. If the user wants this "
                    "as a rule, ask them to say it in their own words.")
        from odie.agent import turn
        if turn.private_sites():  # nothing from a signed-in page becomes a memory (signed-in browsing)
            return "Not saved: this chat read a signed-in page, and nothing from those is kept as a memory."
        try:
            entry, previous = own.update(title, content, topic=topic, source="chat")
        except ValueError as e:
            return f"Not saved: {e}"
        if on_change:
            on_change()
        return f"Saved '{entry.title}' under {entry.topic}" + (" (replaced the earlier version)" if previous else "")

    def forget_memory(title: str, tool_context: ToolContext | None = None) -> str:
        """Remove one remembered entry by its title, when the user says it's wrong or no longer wanted ("stop watching
        for the passport email", "forget that"). Its text is kept in the memory's history."""
        own = memory_of_chat(memory, memory_for, tool_context)  # a personality forgets only what is its own
        if not own.exists():
            return f"No memory called '{title}'."
        entry = own.forget(title, source="chat")
        if entry is None:
            return f"No memory called '{title}'."
        if on_change:
            on_change()
        return f"Forgot '{entry.title}' (from {entry.topic})."

    return [FunctionTool(fetch_memory),
            FunctionTool(update_memory, require_confirmation=watch_for_needs_tap(memory, memory_for)),  # a Watch for entry: the card
            FunctionTool(forget_memory)]
