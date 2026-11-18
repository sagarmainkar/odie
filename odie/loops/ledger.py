"""The ledger of open loops (proactive design §5, 18 Nov 2026): one row per real-world thing Odie follows (a pull
request, a promise, a bill), from whatever source told of it, with its evidence in loop_events. The model opens,
matches and closes loops; code keeps the rows honest: a close always has a reason, and every change leaves evidence.

Times are the user's local time with offset ("2026-11-18T10:00:00+05:30"), compared as datetimes. A loop's
personality is "" for everyday Odie (stored as NULL, as tasks are)."""
from __future__ import annotations

import json
from datetime import datetime

OPEN = ("new", "working", "ready", "waiting")
OWNERS = ("odie", "you", "them")
PRIORITIES = ("high", "normal", "low")
CLOSED_BY_USER = "you"
# The fields code may change on a loop (update); the rest change only through open/attach/close/reopen.
CHANGEABLE = frozenset({"title", "kind", "owner", "state", "next_step", "playbook", "priority", "due_at",
                        "next_check_at", "hidden_until", "has_news", "result", "brief", "link", "nudges", "attempts",
                        "shown_at", "tapped"})


def _at(now: datetime) -> str:
    return now.isoformat(timespec="seconds")


def _whose(pid: str) -> tuple[str, tuple]:
    """The SQL condition for one owner's loops: everyday Odie's have no personality, a personality's carry its id.
    "" -> ("personality is null", ()); "ab12" -> ("personality = ?", ("ab12",))."""
    if not pid:
        return "personality is null", ()
    return "personality = ?", (pid,)


def _row(row) -> dict | None:
    if row is None:
        return None
    loop = dict(row)
    loop["refs"] = json.loads(loop.pop("refs_json") or "[]")
    loop["personality"] = loop["personality"] or ""
    return loop


def open_loop(store, pid: str, now: datetime, title: str, kind: str, owner: str = "odie", refs: list[str] | None = None,
              next_step: str = "", playbook: str = "", priority: str = "normal", due_at: str | None = None,
              source: str = "model", ref: str = "", fact: str = "") -> int:
    """A new loop for this owner, due for its first look at once, with its first evidence when given. Returns its id."""
    if owner not in OWNERS:
        owner = "odie"
    if priority not in PRIORITIES:
        priority = "normal"
    at = _at(now)
    cur = store.execute(
        "insert into loops(personality, title, kind, owner, next_step, playbook, priority, due_at, next_check_at, "
        "refs_json, has_news, created_at, updated_at) values (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (pid or None, title.strip()[:200], kind.strip()[:40], owner, next_step.strip()[:200], playbook, priority, due_at,
         at, json.dumps(list(dict.fromkeys(refs or []))), 1, at, at))
    lid = int(cur.lastrowid)
    if fact:
        add_event(store, lid, now, source, ref, fact)
    return lid


def add_event(store, loop_id: int, now: datetime, source: str, ref: str, fact: str) -> None:
    store.execute("insert into loop_events(loop_id, at, source, ref, fact) values (?,?,?,?,?)",
                  (loop_id, _at(now), source, ref, fact.strip()[:500]))


def get(store, loop_id: int) -> dict | None:
    return _row(store.one("select * from loops where id=?", (int(loop_id),)))


def events(store, loop_id: int) -> list[dict]:
    return [dict(r) for r in store.query("select * from loop_events where loop_id=? order by id", (int(loop_id),))]


def open_loops(store, pid: str) -> list[dict]:
    """One owner's loops that are still open, oldest first."""
    mine, values = _whose(pid)
    rows = store.query(f"select * from loops where state in ('new','working','ready','waiting') and {mine} order by id",
                       values)
    return [_row(r) for r in rows]


def find_by_refs(store, pid: str, refs: list[str]) -> dict | None:
    """The owner's open loop that already holds one of these refs (the same pull request, the same mail thread), or
    None: the same-ID shortcut (design §3). ["example/app#49"] with loop 3 holding it -> loop 3; ["thread:t9"] held by
    nobody -> None; a closed loop holding it -> None (a new thing about a closed one is a new loop, or a reopen)."""
    wanted = {r for r in refs if r}
    for loop in open_loops(store, pid):
        if wanted & set(loop["refs"]):
            return loop
    return None


def find_done_by_user(store, pid: str, refs: list[str]) -> dict | None:
    """The owner's loop the user closed with Done that holds one of these refs, or None. Later mail about it is kept
    as evidence, quietly: Done means "stop following", so it opens no new loop and no card. A loop Odie closed by
    evidence (merged) is not one: news about it is the model's to judge.
      ["example/app#49"], #49 closed with Done -> that loop;  #50 closed as merged -> None;  #49 still open -> None"""
    wanted = {r for r in refs if r}
    if not wanted:
        return None
    mine, values = _whose(pid)
    rows = store.query(f"select * from loops where state in ('closed','dropped') and closed_by = ? and {mine} "
                       "order by id desc", (CLOSED_BY_USER, *values))
    for row in rows:
        loop = _row(row)
        if wanted & set(loop["refs"]):
            return loop
    return None


def attach(store, loop_id: int, now: datetime, source: str, ref: str, fact: str, refs: list[str] | None = None,
           news: bool = True) -> None:
    """Evidence for a loop: the fact, any new refs it brings, and "has news" so the clock looks at it again."""
    loop = get(store, loop_id)
    if loop is None:
        return
    held = list(dict.fromkeys([*loop["refs"], *(refs or [])]))
    has_news = loop["has_news"]
    if news:
        has_news = 1
    store.execute("update loops set refs_json=?, has_news=?, updated_at=? where id=?",
                  (json.dumps(held), has_news, _at(now), int(loop_id)))
    add_event(store, loop_id, now, source, ref, fact)


def update(store, loop_id: int, now: datetime, **fields) -> None:
    """Changes the named fields (only those in CHANGEABLE; anything else raises ValueError)."""
    unknown = set(fields) - CHANGEABLE
    if unknown:
        raise ValueError(f"not a loop field: {', '.join(sorted(unknown))}")
    if not fields:
        return
    names = ", ".join(f"{name}=?" for name in fields)
    store.execute(f"update loops set {names}, updated_at=? where id=?", (*fields.values(), _at(now), int(loop_id)))


def close(store, loop_id: int, now: datetime, by: str, why: str, state: str = "closed") -> None:
    """Closes a loop. A close always says why ("merged 18 Nov 21:04", "you replied 20 Nov 11:02"): no reason raises
    ValueError. by: "odie" (evidence the model or code saw) or "you" (Done). state: "closed" or "dropped"."""
    reason = (why or "").strip()
    if not reason:
        raise ValueError("a loop closes only with a reason")
    if state not in ("closed", "dropped"):
        state = "closed"
    at = _at(now)
    store.execute("update loops set state=?, closed_by=?, closed_why=?, closed_at=?, has_news=0, updated_at=? where id=?",
                  (state, by, reason[:300], at, at, int(loop_id)))
    add_event(store, loop_id, now, by, "", f"Closed: {reason}")


def done(store, loop_id: int, now: datetime) -> None:
    """The card's Done: off the list, no longer followed (finished, or not doing it)."""
    close(store, loop_id, now, CLOSED_BY_USER, "Done")


def reopen(store, loop_id: int, now: datetime) -> None:
    """Reopen (from Done today): open again and due for a look at once; the wrong close stays in its evidence."""
    at = _at(now)
    store.execute("update loops set state='new', closed_by=null, closed_why=null, closed_at=null, has_news=1, "
                  "attempts=0, next_check_at=?, hidden_until=null, updated_at=? where id=?", (at, at, int(loop_id)))
    add_event(store, loop_id, now, CLOSED_BY_USER, "", "Reopened by you")


def closed_since(store, pid: str, since: datetime) -> list[dict]:
    """The owner's loops Odie closed since then, newest first: what Pulse lists under Done today, each with Reopen.
    The ones the user closed with Done are left out (he knows)."""
    mine, values = _whose(pid)
    rows = store.query(f"select * from loops where state in ('closed','dropped') and closed_by != ? and {mine} "
                       "order by closed_at desc", (CLOSED_BY_USER, *values))
    return [_row(r) for r in rows if datetime.fromisoformat(r["closed_at"]) >= since]


def forget_personality(store, pid: str) -> None:
    """A personality was deleted: its loops, their evidence, their PR tests' records and its "Use this" cards go."""
    if not pid:
        return
    ids = [r["id"] for r in store.query("select id from loops where personality=?", (pid,))]
    for lid in ids:
        store.execute("delete from loop_events where loop_id=?", (lid,))
    store.execute("delete from loops where personality=?", (pid,))
    for lid in ids:
        store.execute("delete from settings where key=?", (f"loops.test:{lid}",))  # its PR tests' records
    offers = store.get_setting("loops.recipe_offers") or {}
    kept = {repo: o for repo, o in offers.items() if (o.get("owner") or "") != pid}  # its "Use this" cards
    store.set_setting("loops.recipe_offers", kept)


def line(loop: dict, evidence: list[dict]) -> str:
    """One loop as the model reads it among the open ones: id, title, kind, owner, state, due, refs and the last
    evidence. "#3 app #49 Threads newest first · pull request · owner odie · waiting · refs example/app#49 · last:
    New commits pushed"."""
    bits = [f"#{loop['id']} {loop['title']}", loop["kind"] or "?", f"owner {loop['owner']}", loop["state"]]
    if loop.get("due_at"):
        bits.append(f"due {loop['due_at'][:16]}")
    if loop["refs"]:
        bits.append("refs " + ", ".join(loop["refs"][:4]))
    if evidence:
        bits.append("last: " + evidence[-1]["fact"][:120])
    return " · ".join(bits)
