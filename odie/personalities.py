"""Personalities: other ways for the assistant to be, each with its own name, picture, instructions (its own SOUL),
threads and memory, and optionally a brain of its own (odie.brains) and its own set of connected apps
(odie.plugins.access). Tools and skills are the same for all of them.

Everyday Odie is not one of them: it has no row here and its id is the empty string (ODIE). Its name and picture stay
in odie.persona, its SOUL in SOUL.md and its memory in memories.md, so an install with no personalities is unchanged.

A personality is a row in `personalities` plus a folder of two plain files, <config_dir>/personalities/<id>/SOUL.md
and memories.md. Every chat thread belongs to exactly one of them (or to Odie), written in `threads.personality`
before the thread's session exists, and never changed."""
from __future__ import annotations

import logging
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path

from odie import config, persona
from odie.memory.store import MemoryFile
from odie.store.db import Store, now_iso

log = logging.getLogger("odie.personalities")

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
    from odie.plugins import access
    access.copy_odies(store, pid)  # it starts with the connected apps everyday Odie has on now
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

# Background turns run for a personality (its own mail watch, odie.watch.owner): their throwaway session belongs to
# it for as long as the turn runs, so its brain, its apps and its tasks are the ones used. session id -> personality.
_RUNNING_FOR: dict[str, str] = {}


def running_for(session_id: str, pid: str) -> None:
    """A background turn's session belongs to this personality until done_running(session_id)."""
    _RUNNING_FOR[session_id] = pid


def done_running(session_id: str) -> None:
    _RUNNING_FOR.pop(session_id, None)


def of_session(store: Store, session_id: str | None) -> str:
    """The personality a chat thread belongs to; ODIE for an everyday thread, for a thread nobody claimed, and when
    there is no thread at all (a background turn). A background turn run for a personality (running_for) is that
    personality's while it runs.
      a thread Mira started -> Mira's id;  "chat-2026-11-17" -> "";  None -> "";
      Mira's watch turn's session, while it runs -> Mira's id; after -> "" """
    if not session_id:
        return ODIE
    background_owner = _RUNNING_FOR.get(session_id)
    if background_owner is not None:
        return background_owner
    row = store.one("select personality from threads where session_id=?", (session_id,))
    if row is None:
        return ODIE
    return row["personality"] or ODIE


def is_erased(store: Store, session_id: str | None) -> bool:
    """Whether a thread was erased with its personality (delete): its row is kept, empty, with the id of a personality
    that no longer exists. The row keeps the thread's number from being given out again, so a job that was still
    finishing for the erased thread can never write into a new thread that happens to reuse its id.
      a thread of Mira's, Mira still there -> False;  the same thread after Mira was deleted -> True;
      an everyday thread, or one with no row -> False"""
    owner = of_session(store, session_id)
    if owner == ODIE:
        return False
    return get(store, owner) is None


def whose_thread(store: Store, session_id: str | None) -> tuple[str, Personality | None]:
    """Whose thread this is, for code that speaks about a thread outside it (a push, a line posted by a job): the
    owner's id and its record. The record is None for an everyday thread and also for a thread whose personality is
    gone, which is why the id comes too: a thread that is being erased must never be taken for an everyday one.
      an everyday thread, or none          -> ("", None):       speak as everyday Odie
      a thread of Mira's                   -> (her id, Mira):   speak quietly, as Mira (quiet_push)
      a thread of Mira's, Mira just deleted -> (her id, None):  say nothing at all"""
    owner_id = of_session(store, session_id)
    return owner_id, get(store, owner_id)


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


# ── the live stream (/api/events): who hears what ──

def owner_of_event(store: Store, event: dict) -> str:
    """Whose thread a live event is about, from its "session_id"; ODIE for an everyday thread and for an event about
    no thread at all (a task changed, the watch's card)."""
    return of_session(store, event.get("session_id"))


def event_for_stream(event: dict, owner: str, pick: str | None) -> dict | None:
    """What one open stream gets for a live event, or None for nothing. `owner` is whose thread the event is about
    (owner_of_event); `pick` is the personality the stream's app is talking to: "" for a web app on everyday Odie, an
    id for one on a personality, and None for an app that named nobody (the Mac app, the terminal, an older web app).
      an everyday event, any stream                 -> the event, as it is
      Mira's event, a stream that named nobody      -> None (her words never reach it)
      Mira's event, the stream that picked Mira     -> the event, with "personality": her id
      Mira's reply, or her "answered" notice, to a stream on Odie or Coach
                                                    -> {"type": "elsewhere", "personality": her id, "what": "reply"}
      Mira's card waiting for a tap, to that stream -> {"type": "elsewhere", "personality": her id, "what": "card"}
      anything else of Mira's, to that stream       -> None
    An "elsewhere" notice carries no words: it only lets the other chat's header show that she has something."""
    if owner == ODIE:
        return event
    if pick is None:
        return None
    if pick == owner:
        return {**event, "personality": owner}
    kind = event.get("type")
    if kind in ("message", "answered"):
        return {"type": "elsewhere", "personality": owner, "what": "reply"}
    is_a_waiting_card = kind == "approval" and event.get("status") == "pending"
    if is_a_waiting_card:
        return {"type": "elsewhere", "personality": owner, "what": "card"}
    return None


def stream_view(store: Store, event: dict, pick: str | None) -> dict | None:
    """event_for_stream, with the event's owner read from the store."""
    return event_for_stream(event, owner_of_event(store, event), pick)


# ── deleting one ──

def remove_workspace_copy(mid: str) -> bool:
    """A file made in a chat is first written into Odie's workspace and then copied for its card (odie.media). Remove
    that workspace file too, when it is still the file the chat made: the name the card kept, at the top of the
    workspace, with the same bytes. True when it was removed.
      "lighthouse notes.md", untouched since                 -> removed
      "plan.md", since written over with something else      -> left alone (it is no longer that file)
      a card with no file name, or no such file any more     -> nothing to do"""
    from odie import media
    from odie.agent.tools.files import workspace
    found = media.get(mid)
    if found is None:
        return False
    copy, described = found
    name = described.get("filename")
    if not name:
        return False
    original = workspace() / Path(name).name
    if not original.is_file():
        return False
    if original.read_bytes() != copy.read_bytes():
        return False
    original.unlink()
    return True


def tables_with_a_thread_column(store: Store) -> list[str]:
    """Every table of the app's database that has a `session_id` column (approvals, the activity log, a reply's saved
    ticks…), found by asking the database, so a table added later is covered without touching this file."""
    names = [r["name"] for r in store.query("select name from sqlite_master where type='table' and name not like 'sqlite_%'")]
    found = []
    for name in names:
        columns = [c["name"] for c in store.query(f'pragma table_info("{name}")')]
        if "session_id" in columns:
            found.append(name)
    return found


def erase_rows_of(store: Store, session_id: str) -> None:
    """Remove everything the app's database keeps for one thread: its rows in every table with a `session_id` column,
    and the settings kept under its id (the signed-in sites it read, the sites okayed in it). Its `threads` row stays,
    emptied, as the mark that the thread was erased (is_erased)."""
    for table in tables_with_a_thread_column(store):
        if table == "threads":
            store.execute("update threads set title=null, pinned_at=null where session_id=?", (session_id,))
            continue
        store.execute(f'delete from "{table}" where session_id=?', (session_id,))
    # settings kept per thread are named "<what>.<the thread's id>": the key ends with the whole id
    store.execute("delete from settings where length(key) > length(?) and substr(key, -length(?)) = ?",
                  (session_id, session_id, session_id))
    from odie.agent import shell_grant
    shell_grant.forget_chat(session_id)  # its shell passes live in memory, not in the settings


async def delete(store: Store, runner, pid: str) -> dict:
    """Erase a personality and everything Odie keeps for it, for good; there is no bin. Returns {"threads": how many
    threads it had}. Erased: its threads' messages; every row and setting kept for those threads (cards, the activity
    log, saved ticks, Think harder); its reminders; its passages in recall; the files made in its threads (their
    cards, their copies in the workspace, its making jobs' folders) and the pictures uploaded into them; its SOUL and
    memories; its picture; the record itself; and the debug copies of the last few model requests (all of them: they
    carry no thread id, so the ones from its threads can't be told apart), the brain picked for it, its
    connected apps' switches, its own mail watch (odie.watch.owner) and its Workers' jobs (stopped first).
    Not erased, because Odie can't reach them from here: log lines, and anything already sent to a tracing service.
    The record goes first, so no new turn can start in its threads while they are erased (the runner then refuses
    them: SessionGone)."""
    from odie import media, thinking
    from odie.app import images
    found = get(store, pid)
    if found is None:
        raise ValueError("no such personality")
    its_threads = sessions_of(store, pid)
    store.execute("delete from personalities where id=?", (pid,))
    await runner.forget_personality(pid)
    from odie.workers import router as workers_router
    from odie.workers import store as workers_store
    if workers_router.hooks:
        workers_router.stop_for(pid)  # its Workers stop before their threads go
    for session_id in its_threads:
        made, uploads = await runner.erase_thread(session_id)  # waits for a turn still running there
        for mid in made:
            remove_workspace_copy(mid)
            media.delete(mid)
        for iid in uploads:
            images.delete_upload(iid)
        erase_rows_of(store, session_id)
    try:
        from odie.recall.fill import recall_index
        recall_index().drop_sessions(its_threads)
    except Exception:  # noqa: BLE001 (an index that won't open holds nothing we could remove now)
        log.warning("recall: a deleted personality's passages couldn't be removed", exc_info=True)
    from odie.making import jobs
    jobs.erase_jobs_of(its_threads)  # what its making jobs kept in the workspace: briefs, scripts, the made files
    thinking.forget(store, its_threads)
    store.execute("delete from tasks where personality=?", (pid,))
    store.execute("delete from settings where key=?", (f"current:{pid}",))
    from odie import brains
    from odie.plugins import access
    brains.same_as_odie(store, pid)  # its own brain pick
    for server in access.give_back_to_odie(store, pid):  # an app that was its alone: everyday Odie's again
        store.audit("agent", "app_access", result_summary=f"{server} on for everyday Odie: no one else could use it")
    access.forget_personality(store, pid)  # its connected apps' switches
    from odie.watch import owner as watch_owner
    watch_owner.forget(store, pid)  # its own watch: card, place in the mail, sources, Proactive switch
    from odie.loops import ledger
    ledger.forget_personality(store, pid)  # its open loops and their evidence
    workers_store.forget_personality(store, pid)  # its jobs and their records
    await runner.forget_personality(pid)  # again: a turn that was finishing may have noted itself meanwhile
    shutil.rmtree(folder(pid), ignore_errors=True)
    (config.settings.data_dir / f"memory-{pid}.lock").unlink(missing_ok=True)
    persona.delete_picture(found.avatar)
    from odie.agent.model import forget_saved_requests
    forget_saved_requests(config.settings.data_dir / "requests")  # last: no turn of its threads can save one now
    from odie.agent import capture
    capture.forget_all()  # kept calls carry no thread either: they all go with it
    runner.invalidate_prompt()
    return {"threads": len(its_threads)}

