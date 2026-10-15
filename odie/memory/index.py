"""Index block for the system prompt and prefetch rendering for the turn context."""
from __future__ import annotations

from odie.memory.search import Hit
from odie.memory.store import MemoryDoc


def build_index(doc: MemoryDoc, max_chars: int = 5000) -> str:
    lines: list[str] = []
    for t in doc.topics:
        if not t.entries:
            continue
        lines.append(f"## {t.name}")
        lines.extend(f"- {e.heading}" for e in t.entries)
    out = "\n".join(lines)
    return out if len(out) <= max_chars else out[: max_chars - 1].rstrip() + "…"


def render_prefetch(hits: list[Hit], max_entries: int = 4, max_chars: int = 2500) -> tuple[str, list[str]]:
    blocks, used, size = [], [], 0
    for h in hits[:max_entries]:
        block = f"### {h.entry.title}\n{h.entry.body.strip()}"
        if size + len(block) > max_chars:
            break
        blocks.append(block)
        used.append(h.entry.title)
        size += len(block)
    return "\n\n".join(blocks), used
