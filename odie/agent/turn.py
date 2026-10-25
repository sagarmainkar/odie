"""The chat turn in progress: the user's own words (without the context Odie appends), for tools that should act only
when asked. Set by the runner for a chat turn; None in background turns (the watch, trackers, parked tasks)."""
from __future__ import annotations

import re
from contextvars import ContextVar

USER_TEXT: ContextVar[str | None] = ContextVar("odie_user_text", default=None)
# This chat's history limit in tokens (odie.models.history_limit_for), pinned per session by the runner; past it the
# older turns go as words only (odie.agent.compaction). None outside a chat turn: the default limit.
HISTORY_LIMIT: ContextVar[int | None] = ContextVar("odie_history_limit", default=None)

_ASKS = {
    "deck": re.compile(r"\b(decks?|slides?|slide ?show|presentations?|ppts?|pptx|power ?point|keynote|pdf)\b", re.I),
    "document": re.compile(r"\b(docs?|docx|documents?|word|pdf|reports?|letters?|files?|write[- ]?up)\b", re.I),
}
_AGAIN = re.compile(r"\b(again|same|redo|re-?do|remake|another|version|theme|minimal|editorial|warm|bold)\b", re.I)


def asked_for(text: str, kind: str) -> bool:
    """Did these words ask for a file of this kind ("a deck", "a Word document", "a PDF"), or for one made again?"""
    return bool(_ASKS[kind].search(text or "") or _AGAIN.search(text or ""))


def file_asked(kind: str) -> bool:
    """In a chat turn: did the user ask for this file? Outside one (background work): yes, the caller decides."""
    said = USER_TEXT.get()
    return True if said is None else asked_for(said, kind)

# The signed-in sites this chat turn has read (signed-in browsing): a private turn. None outside a chat turn.
PRIVATE: ContextVar[set | None] = ContextVar("odie_private_sites", default=None)


def mark_private(site: str) -> None:
    sites = PRIVATE.get()
    if sites is not None and site:
        sites.add(site)


def private_sites() -> set:
    return set(PRIVATE.get() or ())
