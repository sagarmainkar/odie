"""Context prefetch.

Vault prefetch is OFF: rank-fused search scores carry no relevance, so the top 3 were injected even when nothing
fitted, and notes about assistants matched every assistant-style question. The model
searches the vault itself with search_notes when a question is about the user's notes; gather() still takes a vault_fn
for a search that ranks by relevance.

Before each reply, the add-ons' prefetch hooks (the SMS ledger's, say) search with the current question plus the
previous two, and what comes back goes into the user message as labelled "possibly relevant" blocks. The local model
then answers from context instead of deciding whether and what to search. The searches run at the same time.

Placement and stripping: the blocks sit after the user's words and before the per-turn [context: ...] note. They stay
on every message as it was sent, and come off only when a cut sends the older part of a long conversation as words
only (odie.agent.compaction), so a normal message only adds its own block to what the model has to read.
"""
from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable


log = logging.getLogger("odie.prefetch")

NOTES_OPEN = "[from your notes: possibly relevant, use only if it answers the question; cite the note name]"
NOTES_CLOSE = "[/from your notes]"
CORE_BLOCKS = [(NOTES_OPEN, NOTES_CLOSE)]


def block_marks() -> list[tuple[str, str]]:
    """How each kind of prefetched block opens and closes: the core's and every add-on's."""
    from odie import addons
    return CORE_BLOCKS + addons.block_marks()


def block_starts() -> tuple[str, ...]:
    return tuple("\n\n" + o for o, _ in block_marks())

VAULT_CAP = 4000          # characters of notes per message (top 3 chunks, trimmed)
VAULT_K = 3
MAX_KEYWORDS = 3

_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9&'-]*")
_COMMAND_START = re.compile(r"^(remind|mark|snooze|send|add|delete|cancel|approve|decline|stop)\b", re.IGNORECASE)
# Acknowledgements skip only when the whole message is short: "Ok great, I was looking to rewind on ..." is a question.
_ACK_START = re.compile(r"^(yes|yeah|no|nope|ok|okay|thanks|thank|cool|great|nice|done)\b", re.IGNORECASE)
ACK_MAX_WORDS = 5
# Words that never help a substring search over SMS text.
_FILLER = frozenset("""
a an and are as at be but by can could did do does for from had has have how i if in into is it its me my of on or our so
than that the their them then there these they this to was we were what when where which who why will with would you your
about any all just also some please tell know remember recall show give find check look see get got want need let
pay paid spend spent much many last next week today tomorrow yesterday month year day due anything something
should answer reply update updates message messages mail email emails
""".split())


def should_search(text: str) -> bool:
    """Skip acknowledgements, very short replies and direct commands Odie handles with its own tools."""
    t = (text or "").strip()
    words = _WORD.findall(t)
    if len(words) <= 2 or _COMMAND_START.match(t):
        return False
    return not (_ACK_START.match(t) and len(words) <= ACK_MAX_WORDS)


def keywords(current: str, previous: list[str]) -> list[str]:
    """Up to MAX_KEYWORDS words for a substring search (the SMS ledger's): current message first, proper nouns and
    all-caps names (HDFC, ICICI, Amazon) before plain words, longer before shorter."""
    def ranked(text: str) -> list[str]:
        seen, out = set(), []
        for w in _WORD.findall(text or ""):
            k = w.lower().strip("'-")
            if len(k) < 3 or k in _FILLER or k in seen or k.isdigit():
                continue
            seen.add(k)
            out.append(w)
        return sorted(out, key=lambda w: (not (w.isupper() or w[0].isupper()), -len(w)))

    out: list[str] = []
    for text in [current, *previous]:
        for w in ranked(text):
            if w.lower() not in {o.lower() for o in out}:
                out.append(w)
        if len(out) >= MAX_KEYWORDS:
            break
    return out[:MAX_KEYWORDS]


def vault_query(current: str, previous: list[str]) -> str:
    """Current question first, then the previous ones (most recent first), so follow-ups carry their topic."""
    return " | ".join([current.strip(), *[p.strip() for p in previous if p.strip()]])[:400]


def _cap(text: str, limit: int) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


async def gather(current: str, previous: list[str], vault_fn: Callable[[str], Awaitable[str]] | None = None) -> str:
    """The vault search and every add-on's prefetch at once; failures and empty results simply leave their block out."""
    if not should_search(current):
        return ""
    vault_fn = vault_fn or (lambda q: _empty())
    from odie import addons
    hooks = [a for a in addons.active() if a.prefetch is not None]

    async def run(a):  # a hook that isn't async, or raises before awaiting, fails only its own block
        return await a.prefetch(current, previous)
    vault, *more = await asyncio.gather(vault_fn(vault_query(current, previous)), *(run(a) for a in hooks), return_exceptions=True)
    blocks = []
    if isinstance(vault, str) and vault.strip():
        blocks.append(f"{NOTES_OPEN}\n{_cap(vault, VAULT_CAP)}\n{NOTES_CLOSE}")
    elif isinstance(vault, BaseException):
        log.warning("vault prefetch failed: %s", vault)
    for a, got in zip(hooks, more):
        if isinstance(got, str) and got.strip():
            blocks.append(got.strip())
        elif isinstance(got, BaseException):
            log.warning("add-on %s: prefetch failed: %s", a.name, got)
    return "\n".join(blocks)


async def _empty() -> str:
    return ""


def strip_blocks(text: str) -> str:
    """Remove prefetch blocks from a user message, keeping the words and anything after the blocks."""
    starts = [i for i in (text.find(b) for b in block_starts()) if i >= 0]
    if not starts:
        return text
    start = min(starts)
    ends: list[int] = []
    for _, close in block_marks():
        i = text.rfind(close)
        if i >= 0:
            ends.append(i + len(close))
    end = max(ends, default=-1)
    return text[:start] + (text[end:] if end > start else "")
