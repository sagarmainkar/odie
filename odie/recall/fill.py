"""Recall's filler: the index worker calls fill_words on every pass, so past days' chats and the memory file are in
the recall index by words, with or without a vault or photos. Their meaning is embedded later, on the embedding
schedule (odie.vault.worker).

Today's chats are left for tomorrow: a chat still going on is read once its day is over, so an exchange is never
indexed half-finished. No chats are left out, including ones that read a signed-in page (Sagar's decision)."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from odie import config
from odie.recall.chats import chat_lines, exchanges
from odie.recall.index import RecallIndex
from odie.vault.index import adopt_old_index, index_path

_indexes: dict[str, RecallIndex] = {}  # one per data folder, like the notes' index


def recall_index() -> RecallIndex:
    """The recall index in this data folder's odie-index.db (the notes' file, its own tables)."""
    data_dir = config.settings.data_dir
    key = str(data_dir)
    if key not in _indexes:
        _indexes.clear()
        adopt_old_index(data_dir)  # before the file is made, so an old vault-index.db still becomes odie-index.db
        _indexes[key] = RecallIndex(index_path(data_dir))
    return _indexes[key]


def start_of_today(now: datetime) -> float:
    """The timestamp of today's midnight in the user's timezone: 4 Nov 15:00 -> 4 Nov 00:00."""
    today = now.astimezone(ZoneInfo(config.settings.timezone))
    midnight = today.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.timestamp()


def chats_are_read_for_today(read_until: float, today_starts: float) -> bool:
    """Whether the chats were already read up to today's midnight, so nothing new can qualify until tomorrow:
      read up to 4 Nov 00:00, now 4 Nov 15:00 -> True (skip sessions.db)
      read up to 3 Nov 00:00, now 4 Nov 08:00 -> False (read 3 Nov's chats)
      never read (0.0)                        -> False (read every past chat)"""
    return read_until >= today_starts


def fill_words(ix: RecallIndex, now: datetime) -> dict:
    """Add the past days' chat exchanges not yet in recall, then make the memory passages match the memory file.
    Returns {"chats": exchanges added, "memories": memory passages added or replaced}."""
    # the agent module is heavy; only a pass needs it
    from odie.agent.agent import memory_file

    s = config.settings
    today_starts = start_of_today(now)
    read_until = ix.chats_read_until()
    chats = 0
    if not chats_are_read_for_today(read_until, today_starts):
        lines = chat_lines(s.sessions_db_path, s.app_name, s.user_id, since=read_until, until=today_starts,
                           tz=ZoneInfo(s.timezone))
        found = exchanges(lines)
        # A chat can live for days: keep only what comes after the newest exchange already indexed for it.
        newest = {sid: ix.last_chat_ts(sid) for sid in {e.session_id for e in found}}
        new = [e for e in found if e.ts > newest[e.session_id]]
        chats = ix.add_exchanges(new)
        ix.mark_chats_read_until(today_starts)

    memories = 0
    mf = memory_file()
    if mf.exists():  # no file (yet, or a vault not synced in): the memories already in recall are kept
        memories = ix.sync_memories(mf.load().entries())
    return {"chats": chats, "memories": memories}
