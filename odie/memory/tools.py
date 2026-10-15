"""Memory tools the model can call. The index in the system prompt lists titles; these fetch and write."""
from __future__ import annotations

from google.adk.tools import FunctionTool

from odie.memory.index import render_prefetch
from odie.memory.search import search
from odie.memory.store import MemoryFile


def make_memory_tools(memory: MemoryFile, on_change=None) -> list[FunctionTool]:
    def fetch_memory(title: str) -> str:
        """Read one remembered entry by its title (as listed in 'What you remember'). Partial titles work when unique."""
        e = memory.load().find(title)
        if e is None:
            return f"Nothing remembered under '{title}'. Try search_memories."
        return f"{e.title} ({e.date}) [{e.topic}]\n{e.body}"

    def search_memories(query: str) -> str:
        """Keyword search across everything remembered about the user. Use when the index has no obvious title."""
        hits = search(memory.load().entries(), query, limit=5)
        if not hits:
            return "Nothing remembered about that."
        text, _ = render_prefetch(hits, max_entries=5, max_chars=3000)
        return text

    def update_memory(title: str, content: str, topic: str | None = None) -> str:
        """Save something worth keeping about the user, people, preferences, projects or decisions. Reuse an existing title to update it; topic groups it (Identity, People, Projects, Health, Finance, ...)."""
        if (topic or "").strip().lower() == "watch for":  # standing instructions for the background watch
            doc = memory.load() if memory.exists() else None
            t = doc.topic("Watch for") if doc is not None else None
            if t is not None and len(t.entries) >= 30 and doc.find(title) is None:
                return "You have 30 things to watch for: remove one first."
        from odie.agent import turn
        if turn.private_sites():  # nothing from a signed-in page becomes a memory (signed-in browsing)
            return "Not saved: this chat read a signed-in page, and nothing from those is kept as a memory."
        try:
            entry, previous = memory.update(title, content, topic=topic, source="chat")
        except ValueError as e:
            return f"Not saved: {e}"
        if on_change:
            on_change()
        return f"Saved '{entry.title}' under {entry.topic}" + (" (replaced the earlier version)" if previous else "")

    def forget_memory(title: str) -> str:
        """Remove one remembered entry by its title, when the user says it's wrong or no longer wanted ("stop watching
        for the passport email", "forget that"). Its text is kept in the memory's history."""
        if not memory.exists():
            return f"No memory called '{title}'."
        entry = memory.forget(title, source="chat")
        if entry is None:
            return f"No memory called '{title}'."
        if on_change:
            on_change()
        return f"Forgot '{entry.title}' (from {entry.topic})."

    return [FunctionTool(f) for f in (fetch_memory, search_memories, update_memory, forget_memory)]
