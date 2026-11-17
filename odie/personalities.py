"""Personalities: other ways for the assistant to be, each with its own name, picture, instructions (its own SOUL),
threads and memory. Tools, skills and the model are the same for all of them; only who the assistant is changes.

Everyday Odie is not one of them: it has no row here and its id is the empty string (ODIE). Its name and picture stay
in odie.persona, its SOUL in SOUL.md and its memory in memories.md, so an install with no personalities is unchanged.

A personality is a row in `personalities` plus a folder of two plain files, <config_dir>/personalities/<id>/SOUL.md
and memories.md. Every chat thread belongs to exactly one of them (or to Odie), written in `threads.personality`
before the thread's session exists, and never changed."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from pathlib import Path

from odie import config, persona
from odie.memory.store import MemoryFile
from odie.store.db import Store, now_iso

ODIE = ""  # the everyday one's id

NAME_EMPTY = "Give it a name."
NAME_IS_ODIES = "That is the everyday one's name."
NAME_TAKEN = "You already have one called {name}."


@dataclass(frozen=True)
class Personality:
    id: str  # 12 hex characters
    name: str
    avatar: str | None  # a picture id (odie.persona.avatar_path); None = the orb
    created_at: str


def _from_row(row) -> Personality:
    return Personality(id=row["id"], name=row["name"], avatar=row["avatar"], created_at=row["created_at"])


def list_all(store: Store) -> list[Personality]:
    """Every personality, oldest first."""
    rows = store.query("select * from personalities order by created_at, rowid")
    return [_from_row(r) for r in rows]


def get(store: Store, pid: str | None) -> Personality | None:
    """The personality with this id; None for Odie's empty id and for an id nobody has."""
    if not pid:
        return None
    row = store.one("select * from personalities where id=?", (pid,))
    if row is None:
        return None
    return _from_row(row)


def clean_name(name: str) -> str:
    """A name as it is kept: single spaces, no more than persona.MAX_NAME characters. "  Mira   B " -> "Mira B"."""
    single_spaced = " ".join((name or "").split())
    return single_spaced[:persona.MAX_NAME].strip()


def name_problem(store: Store, name: str, but: str = "") -> str | None:
    """What is wrong with this name for a personality, in words for the user, or None when it is fine. `but` is the id
    of the personality being renamed, which may keep its own name.
      ""  or "   "                         -> "Give it a name."
      "odie", "ODIE ", or Odie's chosen name -> "That is the everyday one's name."
      "mira" when a Mira exists            -> "You already have one called Mira."
      "mira" while renaming Mira herself   -> None
      "Coach"                              -> None"""
    wanted = clean_name(name)
    if not wanted:
        return NAME_EMPTY
    odies_names = {persona.DEFAULT_NAME.lower(), persona.get(store)["name"].lower()}
    if wanted.lower() in odies_names:
        return NAME_IS_ODIES
    for other in list_all(store):
        if other.id != but and other.name.lower() == wanted.lower():
            return NAME_TAKEN.format(name=other.name)
    return None


def create(store: Store, name: str) -> Personality:
    """A new personality with the orb and the default instructions. A name that won't do raises ValueError with
    name_problem's words."""
    problem = name_problem(store, name)
    if problem:
        raise ValueError(problem)
    pid = uuid.uuid4().hex[:12]
    store.execute("insert into personalities(id, name, avatar, created_at) values (?,?,?,?)",
                  (pid, clean_name(name), None, now_iso()))
    made = get(store, pid)
    assert made is not None
    return made


def rename(store: Store, pid: str, name: str) -> Personality:
    problem = name_problem(store, name, but=pid)
    if problem:
        raise ValueError(problem)
    store.execute("update personalities set name=? where id=?", (clean_name(name), pid))
    return _must_get(store, pid)


def set_avatar(store: Store, pid: str, avatar: str | None) -> Personality:
    """Give it a picture (an id from persona.store_picture), or None for the orb."""
    store.execute("update personalities set avatar=? where id=?", (avatar, pid))
    return _must_get(store, pid)


def _must_get(store: Store, pid: str) -> Personality:
    found = get(store, pid)
    if found is None:
        raise ValueError("no such personality")
    return found


# ── its two files ──

def folder(pid: str) -> Path:
    return config.settings.config_dir / "personalities" / pid


def _soul_path(pid: str) -> Path:
    return folder(pid) / "SOUL.md"


def load_soul(pid: str) -> str | None:
    """Its instructions, or None when it has none of its own (it then talks with the default personality under its
    own name)."""
    try:
        text = _soul_path(pid).read_text().strip()
    except OSError:
        return None
    return text or None


def save_soul(pid: str, text: str) -> bool:
    """Save its instructions. Blank text removes the file, so it goes back to the default. True when it now has
    instructions of its own."""
    path = _soul_path(pid)
    if not text.strip():
        path.unlink(missing_ok=True)
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return True


def memory_file(p: Personality) -> MemoryFile:
    """Its own memory: memories.md in its folder. Everyday Odie's is odie.agent.agent.memory_file()."""
    lock = config.settings.data_dir / f"memory-{p.id}.lock"
    return MemoryFile(folder(p.id) / "memories.md", lock, p.name)


OWN_LABEL = "Yours alone (what you save goes here):"
# No name in this label: the prompt's "Odie" is swapped for the personality's own name (persona.apply_name).
SHARED_LABEL = "Shared, the everyday memory (read it, don't change it):"


def joined_index(own: str, shared: str) -> str:
    """The memory titles a personality's prompt lists: its own first, then the shared ones, each under a line that says
    whose they are, so the model knows a new memory is saved among its own. With nothing of its own yet, its part
    reads "nothing yet"."""
    own_part = own.strip() or "nothing yet"
    return f"{OWN_LABEL}\n{own_part}\n\n{SHARED_LABEL}\n{shared.strip()}"


# ── who a thread belongs to ──

def of_session(store: Store, session_id: str | None) -> str:
    """The personality a chat thread belongs to; ODIE for an everyday thread, for a thread nobody claimed, and when
    there is no thread at all (a background turn).
      a thread Mira started -> Mira's id;  "chat-2026-11-17" -> "";  None -> "" """
    if not session_id:
        return ODIE
    row = store.one("select personality from threads where session_id=?", (session_id,))
    if row is None:
        return ODIE
    return row["personality"] or ODIE


def claim(store: Store, session_id: str, pid: str) -> None:
    """Write that this new thread belongs to this personality. It is called before the thread's session is made, and
    the answer never changes afterwards: a thread that already belongs to someone else, or that Odie already has a
    row for (a pinned or renamed everyday thread), raises ValueError."""
    if get(store, pid) is None:
        raise ValueError("no such personality")
    row = store.one("select personality from threads where session_id=?", (session_id,))
    if row is not None:
        owner = row["personality"] or ODIE
        if owner != pid:
            raise ValueError(f"{session_id} already belongs to someone else")
        return
    store.execute("insert into threads(session_id, personality) values (?,?)", (session_id, pid))


def sessions_of(store: Store, pid: str) -> list[str]:
    """The threads of one personality, in the order they were made."""
    rows = store.query("select session_id from threads where personality=? order by rowid", (pid,))
    return [r["session_id"] for r in rows]


def owned_sessions(store: Store) -> frozenset[str]:
    """Every thread that belongs to some personality: what everyday Odie may never read."""
    rows = store.query("select session_id from threads where personality is not null and personality != ''")
    return frozenset(r["session_id"] for r in rows)


def hidden_from(store: Store, pid: str) -> frozenset[str]:
    """The threads this one may not read. Reading goes one way: a personality sees its own threads and the everyday
    ones; Odie sees only the everyday ones.
      Odie ("")  -> every personality's threads
      Mira       -> Coach's threads (not her own, not the everyday ones)"""
    rows = store.query("select session_id, personality from threads where personality is not null and personality != ''")
    return frozenset(r["session_id"] for r in rows if r["personality"] != pid)


# ── what stays everyday Odie's ──

# Tools that start or stop background work, which runs as everyday Odie and reports in the everyday chat. In a
# personality's thread they are refused (odie.agent.callbacks) and the model is told to send the user to Odie.
ODIE_ONLY_TOOLS = frozenset({"track", "stop_tracker"})
ODIE_ONLY = "That's Odie's job: it runs in the background as Odie. Tell the user to ask Odie in the everyday chat."

_QUIET = {
    "replied": ("{name} replied", "Open Odie to read it."),
    "needs you": ("{name} needs you", "Open Odie to answer."),
    "lapsed": ("{name}: a request lapsed", "Open Odie to see it."),
    "reminder": ("{name}", "A reminder is waiting."),
}


def quiet_push(name: str, what: str) -> tuple[str, str]:
    """A push's title and body for something in a personality's thread: who, and that something happened, never the
    words (they would sit on the lock screen). `what` is "replied", "needs you", "lapsed" or "reminder".
      ("Mira", "replied")  -> ("Mira replied", "Open Odie to read it.")
      ("Mira", "reminder") -> ("Mira", "A reminder is waiting.")"""
    title, body = _QUIET[what]
    return title.format(name=name), body
