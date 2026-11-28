"""The ledger of open loops (proactive design §5, 18 Nov 2026): one row per real-world thing Odie follows (a pull
request, a promise, a bill), from whatever source told of it, with its evidence in loop_events. The model opens,
matches and closes loops; code keeps the rows honest: a close always has a reason, and every change leaves evidence.

Times are the user's local time with offset ("2026-11-18T10:00:00+05:30"), compared as datetimes. A loop's
personality is "" for everyday Odie (stored as NULL, as tasks are)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta

OPEN = ("new", "working", "ready", "waiting")
OWNERS = ("odie", "you", "them")
PRIORITIES = ("high", "normal", "low")
CLOSED_BY_USER = "you"
CLOSED_IN_CHAT = "you in chat"  # his Done said in chat (odie.loops.chat_done): his, and shown in Done today
BY_HIM = (CLOSED_BY_USER, CLOSED_IN_CHAT)
PUT_ASIDE = "rollback"  # closed for a rollback (odie.loops.migrate.before_rollback): nobody's Done, never remembered
REMEMBER_DAYS = 30  # a closed loop is remembered this long after its close, or until its due time, whichever is later
FINISHED_DAYS = REMEMBER_DAYS  # (the name stage 2's prompt uses)
REOPEN_DAYS = 7  # a closed loop may be reopened this long after its close
TICKED = "review_ticked"  # in a loop's card: the reminders of Odie's the evening review's drop ticked (Reopen reopens)
# The reminders a loop may close with it: the ones Odie made (for a loop, a watch thread of old, a reminder with a source
# ref the watch added). His own (no source kind) are never touched.
ODIES_TASKS = ("loop", "watch", "ref")
# Of those, the ones only Odie ever made: 'ref' (a reminder with a source) came from the old watch AND from chat's
# task_add, with nothing to tell them apart (both origin 'agent'); since phase 3 only chat makes one. So Odie's own
# closes (stage 2's "closes", the ladder's drop) tick only these; his Done ticks the 'ref' ones too.
ODIE_ONLY = ("loop", "watch")
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
    loop["card"] = json.loads(loop.pop("card_json", None) or "{}")
    loop["personality"] = loop["personality"] or ""
    return loop


def owner_for(owner: str, playbook: str) -> str:
    """Whose loop it is, given whether Odie has work for it: "odie" only with a playbook (stage 4 looks at it again);
    "odie" without one would sit under "Odie is on it" with nothing ever looking at it, so it is his ("you": a card
    with Done). Anything else stays as it is.
      ("odie", "github-pr") -> "odie";  ("odie", "") -> "you" (a CI mail no pull request was found for);
      ("them", "") -> "them";  ("you", "") -> "you"
    """
    if owner == "odie" and not playbook:
        return "you"
    return owner


def open_loop(store, pid: str, now: datetime, title: str, kind: str, owner: str = "odie", refs: list[str] | None = None,
              next_step: str = "", playbook: str = "", priority: str = "normal", due_at: str | None = None,
              source: str = "model", ref: str = "", fact: str = "", card: dict | None = None,
              state: str = "new", result: str = "") -> int:
    """A new loop for this owner, due for its first look at once, with its first evidence when given. Returns its id.
    card: what its card shows besides the loop's own fields (pile, amount, draft, the mail it came from). state "ready"
    makes it a card at once (shown now)."""
    if owner not in OWNERS:
        owner = "odie"
    if priority not in PRIORITIES:
        priority = "normal"
    if state not in OPEN:
        state = "new"
    at = _at(now)
    shown_at = None
    if state == "ready":
        shown_at = at
    cur = store.execute(
        "insert into loops(personality, title, kind, owner, state, next_step, playbook, priority, due_at, "
        "next_check_at, refs_json, has_news, result, shown_at, card_json, created_at, updated_at) "
        "values (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (pid or None, title.strip()[:200], kind.strip()[:40], owner, state, next_step.strip()[:200], playbook, priority,
         due_at, at, json.dumps(list(dict.fromkeys(refs or []))), 1, result.strip()[:300], shown_at,
         json.dumps(card or {}, ensure_ascii=False), at, at))
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


def is_item_ref(ref: str) -> bool:
    """Whether a ref names one item exactly, so a closed loop may be matched by it: a mail, an event or a pull request
    or issue. "mail:m1", "event:uid1", "example/app#49" -> True; "thread:t1" (a whole conversation: next month's bill
    lands in it too), "note:Inbox/digest.md" (one digest names many things), "task:12" -> False."""
    from odie.loops import github
    if ref.startswith(("mail:", "event:")):
        return True
    return github.parse(ref) is not None


def is_open_ref(ref: str) -> bool:
    """Whether a ref may match an OPEN loop: an item ref, or its mail thread. "thread:t1" -> True; "note:x" -> False
    (a container: never a strong ID); "task:12" -> False."""
    return is_item_ref(ref) or ref.startswith("thread:")


def holding(store, pid: str, ref: str, states: tuple) -> list[dict]:
    """The owner's loops in these states that hold this ref, newest first."""
    mine, values = _whose(pid)
    marks = ",".join("?" for _ in states)
    rows = store.query(f"select * from loops where state in ({marks}) and refs_json like ? and {mine} order by id desc",
                       (*states, f'%"{ref}"%', *values))
    return [lp for lp in (_row(r) for r in rows) if ref in lp["refs"]]


def find_by_refs(store, pid: str, refs: list[str]) -> dict | None:
    """The owner's ONE open loop that holds one of these refs (the same pull request, the same mail thread), or None:
    the same-ID shortcut (design §3). A ref two open loops hold matches neither: the model decides. A note or task ref
    never matches.
      ["example/app#49"] with loop 3 holding it -> loop 3;  ["thread:t9"] held by nobody -> None;
      ["mail:school1"] held by loops 4 and 5 -> None;  a closed loop holding it -> None"""
    for ref in refs:
        if not ref or not is_open_ref(ref):
            continue
        found = holding(store, pid, ref, OPEN)
        if len(found) == 1:
            return found[0]
    return None


def remembered(loop: dict, now: datetime) -> bool:
    """Whether a closed loop is still remembered: for REMEMBER_DAYS after its close, or until its due time has passed,
    whichever is later. Ticked yesterday -> True; ticked 40 days ago for a concert next month -> True; ticked 40 days
    ago, nothing ahead -> False; a birthday's loop a year on -> False (its event id shows again)."""
    closed_at = loop.get("closed_at")
    if not closed_at or loop.get("closed_by") == PUT_ASIDE:
        return False
    until = datetime.fromisoformat(closed_at) + timedelta(days=REMEMBER_DAYS)
    due = loop.get("due_at")
    if due:
        due_at = datetime.fromisoformat(due)
        if due_at.tzinfo is None:
            due_at = due_at.replace(tzinfo=now.tzinfo)
        until = max(until, due_at)
    return now <= until


def closed_holders(store, pid: str, refs: list[str], now: datetime, by_him: bool) -> list[dict]:
    """The owner's remembered closed loops holding one of these item refs (never a thread or a note), newest first:
    his (Done) when by_him, else Odie's (evidence, the ladder's drop)."""
    out: dict[int, dict] = {}
    for ref in refs:
        if not ref or not is_item_ref(ref):
            continue
        for lp in holding(store, pid, ref, ("closed", "dropped")):
            is_his = lp["closed_by"] in BY_HIM
            if is_his == by_him and remembered(lp, now):
                out[lp["id"]] = lp
    return sorted(out.values(), key=lambda lp: lp["id"], reverse=True)


def find_done_by_user(store, pid: str, refs: list[str], now: datetime) -> dict | None:
    """The owner's loop he closed (Done, on a card or in chat) that holds one of these item refs and is still
    remembered (remembered), or None. Later news about it is kept as evidence, quietly. The newest when several hold it.
      ["example/app#49"], #49 closed with Done yesterday -> that loop;  #50 closed as merged -> None;
      ["thread:t1"] -> None (a thread is never enough for a closed loop);  closed 40 days ago, no due ahead -> None"""
    found = closed_holders(store, pid, refs, now, by_him=True)
    if not found:
        return None
    return found[0]


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


def merge_card(store, loop_id: int, now: datetime, fields: dict) -> None:
    """Adds to what a loop's card shows: the fields given replace those of the same name, the rest stay. A pile kept,
    an amount added -> both on the card."""
    loop = get(store, loop_id)
    if loop is None or not fields:
        return
    card = {**loop["card"], **fields}
    store.execute("update loops set card_json=?, updated_at=? where id=?",
                  (json.dumps(card, ensure_ascii=False), _at(now), int(loop_id)))


SEEN = "seen_due"  # in a loop's card fields, never shown: {"event:uid1": "2026-11-21T17:00+05:30"}


def seen_due(loop: dict, ref: str) -> str:
    """The time a mail's or event's thing had when this loop last took it in, or "": {"seen_due": {"event:uid1":
    "2026-11-21T17:00+05:30"}} and "event:uid1" -> that time; a ref it never saw a time for -> ""."""
    seen = loop["card"].get(SEEN)
    if not isinstance(seen, dict):
        return ""
    return str(seen.get(ref) or "")


def note_seen(store, loop_id: int, now: datetime, ref: str, due: str | None, keep_first: bool = False) -> None:
    """Remembers the time a finding gave for its mail or event, so a later "this is new" about the same event can be
    checked against it (odie.loops.consolidate.brings_news). An open loop follows its event (the newest time wins); a
    closed loop keeps the first time it saw (keep_first), which is the time the thing had when he finished it."""
    loop = get(store, loop_id)
    if loop is None or not ref or not due:
        return
    seen = loop["card"].get(SEEN)
    if not isinstance(seen, dict):
        seen = {}
    if keep_first and seen.get(ref):
        return
    merge_card(store, loop_id, now, {SEEN: {**seen, ref: due}})


def add_refs(store, loop_id: int, now: datetime, refs: list[str]) -> None:
    """Adds refs to a loop (none twice), with no evidence and no news: a reminder made for it, say."""
    loop = get(store, loop_id)
    if loop is None:
        return
    held = list(dict.fromkeys([*loop["refs"], *[r for r in refs if r]]))
    store.execute("update loops set refs_json=?, updated_at=? where id=?", (json.dumps(held), _at(now), int(loop_id)))


def update(store, loop_id: int, now: datetime, **fields) -> None:
    """Changes the named fields (only those in CHANGEABLE; anything else raises ValueError). A tap ("tapped") is also
    logged, with the loop's kind, for learning (odie.loops.learn)."""
    unknown = set(fields) - CHANGEABLE
    if unknown:
        raise ValueError(f"not a loop field: {', '.join(sorted(unknown))}")
    if not fields:
        return
    names = ", ".join(f"{name}=?" for name in fields)
    store.execute(f"update loops set {names}, updated_at=? where id=?", (*fields.values(), _at(now), int(loop_id)))
    if fields.get("tapped"):
        from odie.loops import learn
        loop = get(store, loop_id)
        if loop is not None:
            learn.log_tap(store, loop, now, str(fields["tapped"]))


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
    close_its_reminder(store, get(store, loop_id))


def reminders_of(loop: dict) -> list[int]:
    """Every reminder a loop points at ("task:<id>" refs), newest first: an upgrade may have folded three reminders
    for one thing into one loop. ["event:uid1", "task:12", "task:15"] -> [15, 12]; no task ref -> []."""
    out = []
    for ref in loop["refs"]:
        number = ref[len("task:"):]
        if ref.startswith("task:") and number.isdigit():
            out.append(int(number))
    return sorted(out, reverse=True)


def reminder_of(loop: dict) -> int | None:
    """The reminder a loop points at (the newest "task:<id>" ref), or None. ["event:uid1", "task:12"] -> 12; no task
    ref -> None."""
    held = reminders_of(loop)
    if not held:
        return None
    return held[0]


def pointing_at(store, task_id: int) -> dict | None:
    """The loop that points at this reminder, open or closed (the newest), or None."""
    rows = store.query("select * from loops where refs_json like ? order by id desc", (f'%"task:{int(task_id)}"%',))
    for row in rows:
        loop = _row(row)
        if f"task:{int(task_id)}" in loop["refs"]:
            return loop
    return None


def reminder_done(store, task_id: int, now: datetime) -> int | None:
    """He ticked off a reminder a loop points at (on Pulse, in chat): the loop is his Done too, remembered like any
    Done. Returns the loop's id, or None when no open loop points at it. Task #12 of the vote loop ticked -> that loop
    closed by you; his own "Pay rent" -> None."""
    loop = pointing_at(store, task_id)
    if loop is None or loop["state"] not in OPEN:
        return None
    done(store, loop["id"], now)
    update(store, loop["id"], now, tapped="done")
    return loop["id"]


def close_its_reminder(store, loop: dict | None) -> None:
    """A closed loop's reminder closes with it, so it never rings for something finished: on his Done, any reminder
    Odie may have made (ODIES_TASKS); on Odie's own close, only those Odie alone makes (ODIE_ONLY). His own task (no
    source) is never touched."""
    if loop is None:
        return
    kinds = ODIES_TASKS
    if loop.get("closed_by") not in BY_HIM:
        kinds = ODIE_ONLY  # Odie's own close never ticks a reminder he may have asked for in chat
    for task_id in reminders_of(loop):
        row = store.one("select id, status, source_kind from tasks where id=?", (task_id,))
        if row is None or row["status"] not in ("open", "waiting") or row["source_kind"] not in kinds:
            continue
        store.update_task(task_id, status="done")


def done(store, loop_id: int, now: datetime) -> None:
    """The card's Done: off the list, no longer followed (finished, or not doing it)."""
    close(store, loop_id, now, CLOSED_BY_USER, "Done")


def state_after_reopen(loop: dict) -> str:
    """Where a reopened loop goes: one with a playbook is looked at again by stage 4 ("new"); his own (owner you) is a
    card again ("ready"); the rest are followed ("waiting"). A pull request -> "new"; "Reply to Asha" -> "ready"; an
    order on its way -> "waiting"."""
    if loop["playbook"]:
        return "new"
    if loop["owner"] == "you":
        return "ready"
    return "waiting"


def reopen(store, loop_id: int, now: datetime) -> None:
    """Reopen (from Done today): open again and due for a look at once; the wrong close stays in its evidence. A loop
    the evening review merged into another is put back as it was (unmerge)."""
    loop = get(store, loop_id)
    if loop is None:
        return
    if unmerge(store, loop_id, now):
        return
    reopen_ticked(store, loop, now)
    at = _at(now)
    store.execute("update loops set state=?, closed_by=null, closed_why=null, closed_at=null, has_news=1, "
                  "attempts=0, next_check_at=?, hidden_until=null, shown_at=?, tapped='reopen', updated_at=? where id=?",
                  (state_after_reopen(loop), at, at, at, int(loop_id)))
    add_event(store, loop_id, now, CLOSED_BY_USER, "", "Reopened by you")


def reopen_ticked(store, loop: dict, now: datetime) -> None:
    """The reminders the evening review's drop ticked (its card's TICKED) ring again when the loop is reopened, and the
    note is cleared. A dropped order with Odie's "check the delivery" reminder ticked, reopened -> the reminder is open
    again; a loop the review never dropped -> nothing to do."""
    ticked = loop["card"].get(TICKED) or []
    for task_id in ticked:
        row = store.one("select status from tasks where id=?", (int(task_id),))
        if row is not None and row["status"] == "done":
            store.update_task(int(task_id), status="open", completed_at=None)
    if ticked:
        card = {k: v for k, v in loop["card"].items() if k != TICKED}
        store.execute("update loops set card_json=? where id=?", (json.dumps(card, ensure_ascii=False), loop["id"]))


def may_reopen(loop: dict, now: datetime) -> bool:
    """Whether a loop can be reopened now: it is closed, within REOPEN_DAYS of its close. Closed by Odie 2 days ago ->
    True; 8 days ago -> False; still open -> False."""
    if loop["state"] in OPEN or not loop.get("closed_at"):
        return False
    return now - datetime.fromisoformat(loop["closed_at"]) <= timedelta(days=REOPEN_DAYS)


def note_later(store, loop_id: int, now: datetime, until: str) -> None:
    """The card's Later: hidden until then, the tap noted, and a line of evidence (Later is counted from those)."""
    update(store, loop_id, now, hidden_until=until, tapped="later")
    add_event(store, loop_id, now, CLOSED_BY_USER, "later", f"Later: back {until[:16]}")


def laters(store, loop_id: int) -> int:
    """How many times he put this loop off with Later."""
    row = store.one("select count(*) n from loop_events where loop_id=? and ref='later'", (int(loop_id),))
    return int(row["n"])


def split(store, loop_id: int, event_ids: list[int], now: datetime, by: str = CLOSED_BY_USER, why: str = "",
          title: str = "") -> int:
    """A wrong merge undone (design §3): the chosen evidence moves to a new loop of its own, with the refs it brought,
    and the old loop stops holding those refs (so the shortcut no longer sends them there). Both keep a line saying so.
    The new loop takes the old one's kind and owner, its title (unless given) from the first moved line and nothing of
    the old card (draft, amount, suggestion: they were the other thing's); his (owner you) is a card at once. No
    evidence chosen, or none of this loop's -> ValueError. by "odie" (the evening review) says so in both lines and
    keeps what moved on the new loop's card, so unsplit can put it back."""
    loop = get(store, loop_id)
    if loop is None:
        raise ValueError("no such loop")
    wanted = {int(e) for e in event_ids}
    moving = [e for e in events(store, loop_id) if e["id"] in wanted]
    if not moving:
        raise ValueError("choose the evidence that belongs to another thing")
    moved_refs = [e["ref"] for e in moving if e["ref"]]
    state = "waiting"
    if loop["owner"] == "you":
        state = "ready"
    if not title:
        title = moving[0]["fact"][:120]
    card = None
    if by != CLOSED_BY_USER:
        card = {"split_from": loop["id"], "moved": [e["id"] for e in moving]}
    new_id = open_loop(store, loop["personality"], now, title, loop["kind"], owner=loop["owner"], refs=moved_refs,
                       priority=loop["priority"], state=state, result=moving[0]["fact"][:300], card=card)  # no copy
    for e in moving:
        store.execute("update loop_events set loop_id=? where id=?", (new_id, e["id"]))
    kept = [r for r in loop["refs"] if r not in set(moved_refs)]
    store.execute("update loops set refs_json=?, updated_at=? where id=?", (json.dumps(kept), _at(now), int(loop_id)))
    if by == CLOSED_BY_USER:
        add_event(store, loop_id, now, CLOSED_BY_USER, "split", f"Split off into #{new_id}: {title}")
        add_event(store, new_id, now, CLOSED_BY_USER, "split", f"Split off from #{loop_id} by you")
    else:
        reason = ""
        if why:
            reason = f" ({why})"
        add_event(store, loop_id, now, by, "split", f"Evening review: split off into #{new_id}: {title}{reason}")
        add_event(store, new_id, now, by, "split", f"Evening review: split off from #{loop_id}{reason}")
    return new_id


def unsplit(store, loop_id: int, now: datetime) -> bool:
    """Undo of a split Odie made (the evening review): every line of evidence of the split-off loop goes back to the
    loop it came from (its "split off" lines are dropped), with its refs, and the split-off loop is deleted. False
    when this loop wasn't split off by Odie, or either loop is gone or closed (his Done on either stands)."""
    loop = get(store, loop_id)
    if loop is None or not loop["card"].get("split_from") or loop["state"] not in OPEN:
        return False
    home = get(store, int(loop["card"]["split_from"]))
    if home is None or home["state"] not in OPEN:
        return False
    store.execute("delete from loop_events where loop_id=? and ref='split'", (int(loop_id),))
    store.execute("update loop_events set loop_id=? where loop_id=?", (home["id"], int(loop_id)))
    held = list(dict.fromkeys([*home["refs"], *loop["refs"]]))
    store.execute("update loops set refs_json=?, updated_at=? where id=?", (json.dumps(held), _at(now), home["id"]))
    store.execute("delete from loop_taps where loop_id=?", (int(loop_id),))
    store.execute("delete from loops where id=?", (int(loop_id),))
    add_event(store, home["id"], now, CLOSED_BY_USER, "", f"Put back together by you: #{loop_id} was part of this")
    return True


def merge(store, keep_id: int, gone_id: int, now: datetime, why: str) -> list[int]:
    """Two open loops of one owner that are one thing (the evening review): the gone loop's evidence moves to the kept
    one with its refs (and its due time when the kept one has none), and the gone loop closes by Odie, "merged into
    #N", keeping on its card what moved so unmerge (Reopen in Done today, or the review's Undo) can put it back. A
    playbook loop, a closed loop, two owners or one loop twice -> ValueError. Returns the moved evidence ids."""
    keep = get(store, keep_id)
    gone = get(store, gone_id)
    if keep is None or gone is None or keep["id"] == gone["id"]:
        raise ValueError("two different loops")
    if keep["state"] not in OPEN or gone["state"] not in OPEN or keep["personality"] != gone["personality"]:
        raise ValueError("two open loops of one owner")
    if keep["playbook"] or gone["playbook"]:
        raise ValueError("a pull request or a promise is never merged")
    moved = [e["id"] for e in events(store, gone_id)]
    for eid in moved:
        store.execute("update loop_events set loop_id=? where id=?", (keep["id"], eid))
    new_refs = [r for r in gone["refs"] if r not in keep["refs"]]
    store.execute("update loops set refs_json=?, updated_at=? where id=?",
                  (json.dumps([*keep["refs"], *new_refs]), _at(now), keep["id"]))
    changed: dict = {}  # field -> [before, after]: only what this merge changed on the kept loop, for unmerge
    if not keep.get("due_at") and gone.get("due_at"):
        changed["due_at"] = [keep.get("due_at"), gone["due_at"]]
    if gone["state"] == "ready" and keep["state"] != "ready":  # his card stays his card
        changed["state"] = [keep["state"], "ready"]
        if keep["owner"] != "you":
            changed["owner"] = [keep["owner"], "you"]
    if changed:
        update(store, keep["id"], now, **{field: values[1] for field, values in changed.items()})
    if gone["state"] == "ready" and keep["state"] != "ready":
        update(store, keep["id"], now, shown_at=_at(now))
    amount = gone["card"].get("amount")
    if amount and not keep["card"].get("amount"):  # a bill's amount goes with it: two bills stay two (the review's rail)
        merge_card(store, keep["id"], now, {"amount": amount})
        changed["amount"] = [None, amount]
    note = f"Evening review: merged #{gone['id']} ({gone['title'][:80]}) into this"
    if why:
        note += f": {why}"
    add_event(store, keep["id"], now, "odie", "review", note)
    merge_card(store, gone["id"], now, {"merged_into": keep["id"], "moved": moved, "refs_moved": new_refs,
                                        "refs_before": gone["refs"], "kept_changes": changed})
    store.execute("update loops set refs_json='[]' where id=?", (gone["id"],))  # its reminders are the kept loop's now
    close(store, gone["id"], now, "odie", f"Evening review: merged into #{keep['id']} ({keep['title'][:80]})")
    return moved


def undo_changes(store, into: dict, changed: dict, now: datetime) -> None:
    """Puts back what a merge changed on the kept loop, field by field, but only a field that still holds the value
    the merge set: {"due_at": [None, "21 Nov 15:00"]} and still 21 Nov 15:00 -> no due again; moved on to 25 Nov since
    (stage 2 saw his reply) -> left as it is. The amount the merge copied leaves its card the same way."""
    fields = {}
    for field, (before, after) in changed.items():
        if field == "amount":
            if into["card"].get("amount") == after:
                card = {k: v for k, v in into["card"].items() if k != "amount"}
                store.execute("update loops set card_json=? where id=?", (json.dumps(card, ensure_ascii=False), into["id"]))
            continue
        if into.get(field) == after:
            fields[field] = before
    if fields and into["state"] in OPEN:
        update(store, into["id"], now, **fields)


def unmerge(store, loop_id: int, now: datetime) -> bool:
    """Undo of a merge (Reopen on the merged loop, or the review's Undo): its evidence and the refs it brought go back
    from the loop it was merged into, and it opens again where it belongs (state_after_reopen). False when this loop
    wasn't merged."""
    loop = get(store, loop_id)
    if loop is None or not loop["card"].get("merged_into") or loop["state"] in OPEN:
        return False
    into = get(store, int(loop["card"]["merged_into"]))
    for eid in loop["card"].get("moved") or []:
        store.execute("update loop_events set loop_id=? where id=?", (int(loop_id), int(eid)))
    if into is not None:
        brought = set(loop["card"].get("refs_moved") or [])
        kept = [r for r in into["refs"] if r not in brought]
        store.execute("update loops set refs_json=?, updated_at=? where id=?", (json.dumps(kept), _at(now), into["id"]))
        undo_changes(store, into, loop["card"].get("kept_changes") or {}, now)
        add_event(store, into["id"], now, CLOSED_BY_USER, "", f"Put back by you: #{loop_id} is a thing of its own")
    card = {k: v for k, v in loop["card"].items()
            if k not in ("merged_into", "moved", "refs_moved", "refs_before", "kept_changes")}
    at = _at(now)
    store.execute("update loops set state=?, closed_by=null, closed_why=null, closed_at=null, refs_json=?, card_json=?, "
                  "hidden_until=null, shown_at=?, updated_at=? where id=?",
                  (state_after_reopen(loop), json.dumps(loop["card"].get("refs_before") or []),
                   json.dumps(card, ensure_ascii=False), at, at, int(loop_id)))
    add_event(store, loop_id, now, CLOSED_BY_USER, "", "Put back by you: not the same thing")
    return True


def finished(store, pid: str, now: datetime) -> list[dict]:
    """The owner's closed loops still remembered (remembered), newest first: his Done ones and the ones Odie closed.
    Stage 2 reads them, so a later mention of the same thing, from any source, attaches quietly."""
    mine, values = _whose(pid)
    rows = store.query(f"select * from loops where state in ('closed','dropped') and {mine} order by closed_at desc",
                       values)
    return [lp for lp in (_row(r) for r in rows) if remembered(lp, now)]


def finished_line(loop: dict) -> str:
    """One closed loop as stage 2 reads it: "#2 Vote: Northwind ballot · reminder · finished by you 19 Nov 09:10 · refs
    event:uid1"; one Odie closed: "… · closed by Odie 18 Nov 21:04 · …"."""
    when = datetime.fromisoformat(loop["closed_at"])
    who = "finished by you"
    if loop["closed_by"] not in BY_HIM:
        who = "closed by Odie"
    bits = [f"#{loop['id']} {loop['title']}", loop["kind"] or "?", f"{who} {when.day} {when.strftime('%b %H:%M')}"]
    if loop["refs"]:
        bits.append("refs " + ", ".join(loop["refs"][:4]))
    return " · ".join(bits)


def closed_since(store, pid: str, since: datetime) -> list[dict]:
    """The owner's loops Odie closed since then, newest first: what Pulse lists under Done today, each with Reopen.
    The ones the user closed with Done are left out (he knows)."""
    mine, values = _whose(pid)
    rows = store.query(f"select * from loops where state in ('closed','dropped') and closed_by not in (?, ?) and "
                       f"{mine} order by closed_at desc", (CLOSED_BY_USER, PUT_ASIDE, *values))  # his tap he knows
    return [_row(r) for r in rows if datetime.fromisoformat(r["closed_at"]) >= since]


def forget(store, loop_id: int) -> None:
    """His "Forget this": the loop, its evidence, its taps and its PR test's record are deleted, and the reminders only
    Odie makes (ODIE_ONLY) close; his own, and a 'ref' reminder he may have asked for in chat, are never touched.
    Nothing of it is remembered: the same mail again is news."""
    loop = get(store, loop_id)
    if loop is None:
        return
    for task_id in reminders_of(loop):
        row = store.one("select status, source_kind from tasks where id=?", (task_id,))
        if row is not None and row["status"] in ("open", "waiting") and row["source_kind"] in ODIE_ONLY:
            store.update_task(task_id, status="done")
    store.execute("delete from loop_events where loop_id=?", (int(loop_id),))
    store.execute("delete from loop_taps where loop_id=?", (int(loop_id),))
    store.execute("delete from loops where id=?", (int(loop_id),))
    store.execute("delete from settings where key=?", (f"loops.test:{int(loop_id)}",))


def forget_personality(store, pid: str) -> None:
    """A personality was deleted: its loops, their evidence, their PR tests' records and its "Use this" cards go."""
    if not pid:
        return
    ids = [r["id"] for r in store.query("select id from loops where personality=?", (pid,))]
    for lid in ids:
        store.execute("delete from loop_events where loop_id=?", (lid,))
        store.execute("delete from loop_taps where loop_id=?", (lid,))
    store.execute("delete from loops where personality=?", (pid,))
    for lid in ids:
        store.execute("delete from settings where key=?", (f"loops.test:{lid}",))  # its PR tests' records
    offers = store.get_setting("loops.recipe_offers") or {}
    kept = {repo: o for repo, o in offers.items() if (o.get("owner") or "") != pid}  # its "Use this" cards
    store.set_setting("loops.recipe_offers", kept)


def line(loop: dict, evidence: list[dict]) -> str:
    """One loop as the model reads it among the open ones: id, title, kind, owner, state, due, what Odie knows of it,
    refs and the last evidence. "#3 app #49 Threads newest first · pull request · owner odie · waiting · refs
    example/app#49 · last: New commits pushed"; a bill whose mail offered a discount -> "… · known: ₹4,240 due 10-Dec;
    ₹4,200 if paid by 30-Nov · …", so a ₹4,200 receipt can be matched to it (22 Nov: without it, it wasn't)."""
    bits = [f"#{loop['id']} {loop['title']}", loop["kind"] or "?", f"owner {loop['owner']}", loop["state"]]
    if loop.get("due_at"):
        bits.append(f"due {loop['due_at'][:16]}")
    if loop.get("result"):
        bits.append("known: " + loop["result"][:160])
    if loop["refs"]:
        bits.append("refs " + ", ".join(loop["refs"][:4]))
    if evidence:
        bits.append("last: " + evidence[-1]["fact"][:120])
    return " · ".join(bits)
