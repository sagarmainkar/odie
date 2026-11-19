"""The Now list (proactive design §5, §15-16 Q5, §17): five to seven lines of what matters to him now, one list per
owner (everyday Odie, each personality). Stage 2 reads it to set a loop's priority, stage 4 to judge what is worth his
attention.

Written only by his tap, in the app (PUT /api/now, the Accept on Odie's weekly proposal): it lives in the settings
table, never in a memory file, so no model tool (update_memory, the memory review) can ever write it. Odie drafts the
first one from what it remembers and his recent chats, and proposes changes once a week; both wait for his tap."""
from __future__ import annotations

from datetime import datetime

from odie.loops.secret import secret_in

KEY = "now.list"  # per owner (odie.watch.owner.key): {"lines": [...], "at": "2026-11-19T10:00:00+05:30", "by": "you"}
MOST_LINES = 7
LINE_MOST = 120


def _key(pid: str) -> str:
    from odie.watch.owner import key
    return key(KEY, pid)


def lines(store, pid: str) -> list[str]:
    """This owner's Now lines, in his order; [] when he has none."""
    saved = store.get_setting(_key(pid)) or {}
    return [str(line) for line in saved.get("lines") or []]


def text(store, pid: str) -> str:
    """The Now list as a model reads it, one "- " line each; "" when there is none.
    ["Ship Odie", "Asha's deck"] -> "- Ship Odie\\n- Asha's deck"."""
    return "\n".join(f"- {line}" for line in lines(store, pid))


def clean(given: list[str]) -> list[str]:
    """His lines as they are kept: each trimmed, blanks left out. More than MOST_LINES, a line over LINE_MOST
    characters, or a line holding a secret raises ValueError with words he can read.
      ["  Ship Odie ", "", "Asha's deck"] -> ["Ship Odie", "Asha's deck"];  eight lines -> ValueError;
      "Pay from account 123456789012 …" -> ValueError ("Not kept: it holds a bank account number.")"""
    kept = [" ".join(str(line).split()) for line in given]
    kept = [line for line in kept if line]
    if len(kept) > MOST_LINES:
        raise ValueError(f"Keep it to {MOST_LINES} lines.")
    for line in kept:
        if len(line) > LINE_MOST:
            raise ValueError(f"Keep each line under {LINE_MOST} characters.")
        why = secret_in(line)
        if why:
            raise ValueError(f"Not kept: it holds {why}.")
    return kept


def save(store, pid: str, given: list[str], now: datetime, by: str = "you") -> list[str]:
    """Saves this owner's Now list as he wrote it (clean decides what is kept). Only his tap calls this."""
    kept = clean(given)
    store.set_setting(_key(pid), {"lines": kept, "at": now.isoformat(timespec="seconds"), "by": by})
    return kept
