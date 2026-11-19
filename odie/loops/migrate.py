"""The upgrade to phase 3 of the proactive design (19 Nov 2026): what the watch kept in three places becomes loops, one
per real thing, so a Done is remembered whatever source mentions the thing again.

THE RULE: the upgrade never changes whether a thing is open — except the one re-made reminder (remade) — and never
puts two different open things in one loop. Each old thing becomes its own loop in its own state; it joins another
loop only when both are the same open or the same closed thing (the same mail, the same event), or when it is a pull
request's old thread or card item and the PR's open loop already holds its exact thread (evidence only).

  the watch's threads (tasks, source_kind 'watch'), open or closed in the last CARRY_DAYS -> a loop each, pointing at
      its task (a bill's or a deadline's reminder still rings as it always did)
  the Needs-you items of watch.card[:<owner>] -> a loop each, or joined to the loop of the same thing: the same mail,
      the same mail thread, or the same pull request (the old "PR #46" item joins that PR's loop); Later times, drafts,
      suggestions, piles and amounts are kept; an item ticked done is a loop he finished
  the reminders the watch added (tasks, source_kind 'ref'), open or closed lately -> one loop per thing: the same
      source ref, or the same title written the same way, are one ("Vote: …" made three times is one loop, finished
      by him if he ticked any of them)
  watch.flagged (pushed once) -> each loop holding a pushed ref is flagged as pushed, and its day-before push counted
      as said: nothing pushed before is pushed again
  the loops already there -> kept; the rest join them

It runs once at startup (KEY holds the version it ran), is safe to run twice (every loop it makes or joins holds the
task or mail it came from, so a second run finds it), writes only loops, loop_events and the flags, and leaves the old
rows and settings where they were (nothing deleted, no table rewritten), so a rollback finds them as they were.

    uv run python -m odie.loops.migrate --dry-run --db <a copy of odie.db>     (prints what it would do; writes nothing)"""
from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from odie.loops import findings, github, ledger

log = logging.getLogger("odie.loops")
VERSION = 1
KEY = "loops.migrated"  # {"version": 1, "at": "…", "lines": n}
CARRY_DAYS = 30  # closed threads and reminders this recent come along (so a Done is remembered); older ones don't
USER_CLOSED = "Closed by the user: "
WATCH_CLOSED = "Closed by the watch: "
KEPT = "\nKept for a reopen: "
PILE_KIND = {"bills": "bill", "orders": "order", "events": "event", "personal": "personal", "alerts": "needs you"}
THREAD_PILE = {"bill": "bills", "order": "orders", "reply": "personal", "deadline": "alerts"}
SUBJECT_PR = re.compile(r"\[([A-Za-z0-9][\w.-]*/[\w.-]+)\].*?#(\d+)")


class Run:
    """One migration's notes: what it did (or would do), line by line."""

    def __init__(self, now: datetime):
        self.now = now
        self.lines: list[str] = []

    def say(self, text: str) -> None:
        self.lines.append(text)


def local(utc_text: str | None, now: datetime) -> datetime:
    """A tasks-table time (UTC, "2026-11-19T04:30:00.000Z") on the user's clock; unreadable or none -> now."""
    if not utc_text:
        return now
    try:
        at = datetime.fromisoformat(utc_text.replace("Z", "+00:00"))
    except ValueError:
        return now
    if at.tzinfo is None:
        at = at.replace(tzinfo=ZoneInfo("UTC"))
    return at.astimezone(now.tzinfo)


def zoned(text: str | None, now: datetime) -> str | None:
    """A time as the ledger keeps it, always with a zone (a naive one is on the user's clock): "2026-11-20T09:00:00" ->
    "2026-11-20T09:00:00+05:30"; "2026-11-20T09:00" -> "2026-11-20T09:00+05:30"; with a zone -> as it is; a date
    "2026-11-21" -> 09:00 that day; unreadable -> None."""
    text = str(text or "").strip()
    if not text:
        return None
    if len(text) == 10:
        return findings.when_of(text)
    try:
        at = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if at.tzinfo is not None:
        return text  # already on a clock with a zone: kept as written
    spec = "minutes"
    if text.count(":") >= 2:
        spec = "seconds"
    return at.replace(tzinfo=now.tzinfo).isoformat(timespec=spec)


def recent(row, now: datetime) -> bool:
    """Whether a task comes along: open, or closed and still remembered (the ledger's rule: 30 days after its close, or
    until its due time, whichever is later). Closed 2 days ago -> True; 60 days ago, due long past -> False; ticked
    40 days ago for something due next week -> True."""
    if row["status"] in ("open", "waiting"):
        return True
    closed = local(row["completed_at"] or row["updated_at"], now)
    until = closed + timedelta(days=CARRY_DAYS)
    due = zoned(row["due_at"], now)
    if due:
        until = max(until, datetime.fromisoformat(due))
    return now <= until


def owners(store) -> list[str]:
    """Everyday Odie ("") and every personality that still exists and has anything to carry."""
    from odie import personalities
    found = [""]
    for r in store.query("select distinct personality p from tasks where personality is not null"):
        found.append(r["p"])
    for r in store.query("select key from settings where key like 'watch.card:%'"):
        found.append(r["key"][len("watch.card:"):])
    for r in store.query("select distinct personality p from loops where personality is not null"):
        found.append(r["p"])
    out = []
    for pid in dict.fromkeys(found):
        if pid and personalities.get(store, pid) is None:
            continue  # deleted: nothing of it is carried
        out.append(pid)
    return out


def whose(pid: str) -> tuple[str, tuple]:
    if not pid:
        return "personality is null", ()
    return "personality = ?", (pid,)


def all_loops(store, pid: str) -> list[dict]:
    mine, values = whose(pid)
    return [ledger._row(r) for r in store.query(f"select * from loops where {mine} order by id", values)]


UPGRADE = "upgrade"  # the evidence source of a thing the upgrade made a loop from
JOINED = "upgrade-join"  # the evidence source of a thing the upgrade added to another loop


def carried_into(store, pid: str, ident: str) -> dict | None:
    """The loop an earlier run carried this very thing into, found ONLY by the upgrade's own evidence row (source
    upgrade or upgrade-join, ref = its "task:<id>" or a card item's ref) — never by a loop's refs, which other things
    share. So a second run finds it and never makes a second loop, and never mistakes another loop for it."""
    row = store.one("select loop_id from loop_events where source in (?, ?) and ref = ? order by id limit 1",
                    (UPGRADE, JOINED, ident))
    if row is None:
        return None
    loop = ledger.get(store, row["loop_id"])
    if loop is None or loop["personality"] != pid:
        return None
    return loop


def made_it(store, loop: dict, ident: str) -> bool:
    """Whether the upgrade made this loop FROM this thing (its first evidence), not merely added it there. Only a loop
    a thing made may take that thing's Done or Later."""
    row = store.one("select ref, source from loop_events where loop_id=? order by id limit 1", (loop["id"],))
    return row is not None and row["source"] == UPGRADE and row["ref"] == ident


def pr_loop_holding(store, pid: str, thread: str) -> dict | None:
    """The OPEN pull request loop (a playbook) that already holds this exact mail thread (code put it there from
    GitHub's own mail in phase 1), or None: the one thread join the upgrade makes, evidence only, whatever the old
    thing's state (a ticked old item never closes the PR's loop). A card item names its thread, or its mail ref is
    the thread's id (Gmail's first mail of a thread)."""
    if not thread:
        return None
    for loop in all_loops(store, pid):
        if loop["playbook"] and loop["state"] in ledger.OPEN and f"thread:{thread}" in loop["refs"]:
            return loop
    return None


def needs_you_of(store, pid: str) -> list[dict]:
    """The Needs-you items of an owner's old watch card, whatever shape the setting has: the dicts of its
    "needs_you" list. A card that is a list, a text or a number, or a "needs_you" that is no list -> []."""
    from odie.watch.owner import key
    card = store.get_setting(key("watch.card", pid))
    if not isinstance(card, dict):
        return []
    items = card.get("needs_you")
    if not isinstance(items, list):
        return []
    return [item for item in items if isinstance(item, dict)]


def says_the_same(first: str, second: str) -> bool:
    """Whether two titles name one thing: every word of one is in the other. "Cloudbase invoice #A-11 — $58.58" and
    "Pay Cloudbase invoice #A-11 — $58.58" -> True; "PTM on Saturday" and "Pay term fee Rs 12,000" -> False; an
    empty title -> False."""
    one = set(same_words(first).split())
    two = set(same_words(second).split())
    if not one or not two:
        return False
    return one <= two or two <= one


def same_thing_loop(store, pid: str, ref: str, is_open: bool, title: str) -> dict | None:
    """The loop the upgrade made from another old thing about the same exact mail or event, for a card item to join.
    Two closed things on one mail are one. An open item joins an open loop only when that loop shows a card (ready)
    and their titles name one thing (says_the_same): otherwise the item's card would be lost. Different states never
    join (each keeps its own loop and its own state).
      an open item "Cloudbase invoice" and the open thread "Pay Cloudbase invoice" on mail:b1 -> the thread's loop
      an open item "PTM on Saturday" and the open thread "Pay term fee" on one mail -> None: two cards
      an open item "Delivery failed" on the mail of an order Odie follows (waiting, no card) -> None: its own card
      a ticked item ("PTM") and an open thread ("Pay term fee") on one mail -> None: two loops
      an open item and a closed thread on one mail -> None: the item is a card of its own"""
    if not ref.startswith(("mail:", "event:")):
        return None
    for loop in all_loops(store, pid):
        if ref not in loop["refs"] or loop["playbook"]:
            continue
        made = store.one("select 1 from loop_events where loop_id=? and source=?", (loop["id"], UPGRADE))
        if made is None:
            continue
        loop_open = loop["state"] in ledger.OPEN
        if loop_open != is_open:
            continue
        if is_open and not (loop["state"] == "ready" and says_the_same(loop["title"], title)):
            continue
        return loop
    return None


def join_evidence(store, loop: dict, run, at: datetime, ident: str, fact: str, refs: list[str]) -> None:
    """Adds an old thing to a loop as evidence (the upgrade-join row that finds it again), with its refs; nothing of
    the loop's state, title, result or Later changes."""
    if loop["playbook"]:
        refs = []  # a pull request's loop keeps its own refs
    new = [r for r in refs if r not in loop["refs"]]
    if new:
        ledger.add_refs(store, loop["id"], run.now, new)
    ledger.add_event(store, loop["id"], at, JOINED, ident, fact)


def has_evidence(store, loop_id: int, ref: str) -> bool:
    return store.one("select 1 from loop_events where loop_id=? and ref=?", (loop_id, ref)) is not None


def make_loop(store, pid: str, run: Run, title: str, kind: str, owner: str, refs: list[str], created: datetime,
              fact: str, fact_ref: str, card: dict | None = None, due: str | None = None) -> int:
    """A loop made by the upgrade: open and shown now (the follow-up ladder, nudges included, starts at the upgrade,
    not at the old item's day), with its first evidence at the time the old thing was made."""
    owner = ledger.owner_for(owner, "")  # the upgrade makes no playbook loops: never Odie's
    state = findings_state(owner)
    lid = ledger.open_loop(store, pid, created, title, kind, owner=owner, refs=refs, due_at=zoned(due, run.now),
                           source="upgrade", ref=fact_ref, fact=fact, card=card, state=state)
    shown = run.now.isoformat(timespec="seconds")
    store.execute("update loops set has_news=0, next_check_at=null, shown_at=?, updated_at=? where id=?",
                  (shown, run.now.isoformat(timespec="seconds"), lid))
    return lid


def findings_state(owner: str) -> str:
    from odie.loops import consolidate
    return consolidate.state_for(owner, "")


def close_as(store, lid: int, by: str, why: str, at: datetime) -> None:
    ledger.close(store, lid, at, by, why or "Done")


def why_of(notes: str | None) -> tuple[str, str]:
    """Who closed a task and why, from its notes: "Closed by the user: dismissed" -> ("you", "dismissed"); "Closed by
    the watch: delivered 18 Nov" -> ("odie", "delivered 18 Nov"); anything else -> ("you", "Done") (he ticked it)."""
    first = (notes or "").split(KEPT, 1)[0]
    if first.startswith(USER_CLOSED):
        return "you", first[len(USER_CLOSED):].strip() or "Done"
    if first.startswith(WATCH_CLOSED):
        return "odie", first[len(WATCH_CLOSED):].strip() or "closed"
    return "you", "Done"


def thread_facts(notes: str | None) -> dict:
    """What a watch thread knew about its mail (its open notes, or what a closed one kept for a reopen)."""
    text = notes or ""
    if KEPT in text:
        text = text.split(KEPT, 1)[1]
    try:
        got = json.loads(text)
    except ValueError:
        return {}
    if not isinstance(got, dict):
        return {}
    return got


def carry_threads(store, pid: str, run: Run) -> None:
    """The watch's threads (step 1 of this module's notes)."""
    mine, values = whose(pid)
    rows = store.query(f"select * from tasks where source_kind='watch' and {mine} order by id", values)
    for row in rows:
        if not recent(row, run.now):
            continue
        facts = thread_facts(row["notes"])
        kind_key = str(facts.get("kind") or "reply")
        kind, owner = findings.THREAD_KINDS.get(kind_key, ("reply owed", "you"))
        refs = [f"task:{row['id']}", row["source_ref"] or ""]
        if facts.get("thread"):
            refs.append(f"thread:{facts['thread']}")
        refs = [r for r in refs if r]
        ident = f"task:{row['id']}"
        stage = row["detail"] or ""
        fact = f"Followed by the watch: {row['title']}"
        if stage:
            fact += f" ({stage})"
        if carried_into(store, pid, ident) is not None:
            continue  # carried by an earlier run
        pr = pr_loop_holding(store, pid, str(facts.get("thread") or ""))
        if pr is not None:  # a pull request's old thread: evidence on its open loop
            join_evidence(store, pr, run, local(row["created_at"], run.now), ident, fact, refs)
            run.say(f"merge watch thread #{row['id']} {row['title']!r} into loop #{pr['id']} {pr['title']!r}")
            continue
        card = {"pile": THREAD_PILE.get(kind_key, "alerts")}
        if facts.get("thread"):
            card["thread"] = facts["thread"]
        if facts.get("sender"):
            card["sender"] = facts["sender"]
        due = facts.get("due") or row["due_at"]
        lid = make_loop(store, pid, run, row["title"], kind, owner, refs, local(row["created_at"], run.now), fact,
                        f"task:{row['id']}", card, due)
        if row["status"] in ("open", "waiting"):
            run.say(f"create loop #{lid} {row['title']!r} ({kind}, {owner}) from watch thread #{row['id']}")
            continue
        by, why = why_of(row["notes"])
        close_as(store, lid, by, why, local(row["completed_at"], run.now))
        run.say(f"create loop #{lid} {row['title']!r} closed by {by} ({why}) from watch thread #{row['id']}")


same_words = findings.same_words


def ref_of_source(source_ref: str) -> str:
    """A 'ref' reminder's source as a loop ref: "event:uid1" and "mail:m1" as they are; a notes path ->
    "note:Inbox/Digest.md"; any other text ("calendar: Northwind window") -> "note:…" too (a container)."""
    text = (source_ref or "").strip()
    if not text:
        return ""
    if text.split(":", 1)[0] in ("event", "mail", "thread", "note", "task"):
        return text
    return f"note:{text}"


def item_ref(row) -> str:
    """A reminder's source when it names ONE item (a mail or an event), else "": a digest note, a notes path or a
    calendar text names many things and never joins two reminders. "event:uid1" -> "event:uid1"; "Inbox/d.md" -> ""."""
    ref = ref_of_source(row["source_ref"])
    if ref.startswith(("event:", "mail:")):
        return ref
    return ""


def same_due(row, seed) -> bool:
    """Whether two reminders have one due time: both have one, and it is the same. Neither has one -> False (no due
    is not "the same due")."""
    return bool(row["due_at"]) and row["due_at"] == seed["due_at"]


def joins(row, seed) -> bool:
    """Whether a closed reminder is the same thing as a group's first reminder: the same mail or event; or the same
    title written the same way with the same due time (both have one), when at least one of the two names no single
    item (a digest note, a calendar text). Two items that differ are two things, whatever their titles.
      two digests' "Vote…" for one due time -> True;  the event's "Vote…" and a digest's "Vote…", one due -> True
      "Pay credit card bill" from one bank's mail and from another's, same due -> False
      "Renew the parking permit" twice from one note, no due on either -> False"""
    mine, theirs = item_ref(row), item_ref(seed)
    if mine and theirs:
        return mine == theirs
    return same_words(row["title"]) == same_words(seed["title"]) and same_due(row, seed)


def same_thing_for_remade(sibling, current) -> bool:
    """The stricter test the re-made rule needs: the same mail or event; or, when NEITHER names a single item, the same
    title and the same due time. A digest's "Pay credit card bill" he ticked is not the bank mail's open one."""
    mine, theirs = item_ref(sibling), item_ref(current)
    if mine or theirs:
        return bool(mine) and mine == theirs
    return same_words(sibling["title"]) == same_words(current["title"]) and same_due(sibling, current)


def groups_of(rows: list) -> list[list]:
    """The 'ref' reminders grouped by thing (19 Nov 2026, after the data-safety review): each OPEN reminder is one
    group of its own (two open ones are never one loop); a closed one joins the first open group it is the same thing
    as (joins), else the first closed group it is, else it starts a closed group. No chaining: a closed reminder is
    compared with each group's first member only."""
    opened = [[r] for r in rows if r["status"] in ("open", "waiting")]
    loose: list[list] = []
    for row in rows:
        if row["status"] in ("open", "waiting"):
            continue
        group = next((g for g in opened if joins(row, g[0])), None)
        if group is None:
            group = next((g for g in loose if joins(row, g[0])), None)
        if group is None:
            loose.append([row])
            continue
        group.append(row)
    return [sorted(g, key=lambda r: r["id"]) for g in [*opened, *loose]]


def his(row) -> bool:
    """Whether he finished this reminder himself: ticked done (not closed by the watch), and not a "Heads-up" (a
    heads-up done is the heads-up seen, not the thing done)."""
    if row["status"] != "done" or why_of(row["notes"])[0] != "you":
        return False
    return not (row["title"] or "").lower().startswith("heads-up")


def remade(group: list, now: datetime):
    """The open reminder of a group that the old watch made again after he had finished the same thing, or None: a
    sibling he finished (his) with the same due time, the same thing by same_thing_for_remade, completed before the
    open one was made. The vote ticked at
    09:10, made again at 10:33 for the same 08:30 deadline -> that open one; next month's bill (another due time) ->
    None; only a "Heads-up" ticked -> None."""
    opened = [r for r in group if r["status"] in ("open", "waiting")]
    if len(opened) != 1:
        return None
    current = opened[0]
    made = local(current["created_at"], now)
    for sibling in group:
        if sibling is current or not his(sibling) or not same_due(sibling, current):
            continue
        if not same_thing_for_remade(sibling, current):
            continue
        if local(sibling["completed_at"], now) < made:
            return current
    return None


def closed_twin(store, pid: str, title: str, due: str | None) -> dict | None:
    """A closed loop of this owner that is the same thing as a closed reminder group (the vote as a watch thread and
    as reminders): one title is the other with more words after it, and both have the same due time."""
    words = same_words(title)
    for loop in all_loops(store, pid):
        if loop["state"] in ledger.OPEN:
            continue
        theirs = same_words(loop["title"])
        if not theirs or not (words.startswith(theirs) or theirs.startswith(words)):
            continue
        if not due or not loop["due_at"] or not loop["closed_at"]:
            continue  # with no due time to agree on, a prefix title alone ("Pay electricity bill [for the shop]")
        if zoned(due, datetime.fromisoformat(loop["closed_at"])) != loop["due_at"]:
            continue
        return loop
    return None


def carry_reminders(store, pid: str, run: Run) -> None:
    """The reminders the watch added (step 3 of this module's notes)."""
    mine, values = whose(pid)
    rows = [r for r in store.query(f"select * from tasks where source_kind='ref' and origin='agent' and {mine} "
                                   "order by id", values) if recent(r, run.now)]
    for group in groups_of(rows):
        opened = [r for r in group if r["status"] in ("open", "waiting")]
        lead = opened[0] if opened else group[-1]
        refs = [f"task:{r['id']}" for r in group] + [ref_of_source(r["source_ref"]) for r in group]
        refs = list(dict.fromkeys(r for r in refs if r))
        found = None
        for ident in (r for r in refs if r.startswith("task:")):
            found = found or carried_into(store, pid, ident)
        if found is None and not opened:
            found = closed_twin(store, pid, lead["title"], lead["due_at"])
            if found is not None:
                run.say(f"merge {len(group)} closed reminder(s) " + " ".join(f"#{r['id']}" for r in group)
                        + f" into loop #{found['id']} {found['title']!r} (the same thing, both closed)")
        made_now = found is None
        if found is None:
            lid = make_loop(store, pid, run, lead["title"], "reminder", "you", refs, local(group[0]["created_at"], run.now),
                            f"Reminder #{group[0]['id']}: {group[0]['title']}", f"task:{group[0]['id']}",
                            {"pile": "alerts"}, lead["due_at"])
            found = ledger.get(store, lid)
            run.say(f"create loop #{lid} {lead['title']!r} (reminder) from {len(group)} reminder(s): "
                    + " ".join(f"#{r['id']}" for r in group))
        new_refs = [r for r in refs if r not in found["refs"]]
        if new_refs:
            ledger.add_refs(store, found["id"], run.now, new_refs)
        for r in group:
            if not has_evidence(store, found["id"], f"task:{r['id']}"):
                ledger.add_event(store, found["id"], local(r["created_at"], run.now), "upgrade", f"task:{r['id']}",
                                 f"Reminder #{r['id']}: {r['title']} ({r['status']}, from {r['source_ref']})")
        found = ledger.get(store, found["id"])
        if not made_now:
            continue  # carried before: the upgrade never changes whether a thing is open (THE RULE)
        again = remade(group, run.now)
        if again is not None:
            store.update_task(again["id"], status="done", notes="Ticked by the upgrade: re-made after you finished it")
            run.say(f"  tick reminder #{again['id']}, re-made after you finished it")
            if found["state"] in ledger.OPEN:
                close_as(store, found["id"], "you", "Done", run.now)
                run.say(f"  remember loop #{found['id']} {found['title']!r} as closed by you")
            continue
        if opened or found["state"] not in ledger.OPEN:
            continue
        closer = max(group, key=lambda r: r["completed_at"] or "")
        by = "odie"
        why = why_of(closer["notes"])[1]
        if any(why_of(r["notes"])[0] == "you" for r in group):
            by, why = "you", "Done"
        close_as(store, found["id"], by, why, local(closer["completed_at"], run.now))
        run.say(f"  remember loop #{found['id']} {found['title']!r} as closed by {by}")


def pr_ref_of(item: dict) -> str:
    """The pull request an old card item was about, from its subject or title, only when its mail was GitHub's own
    (the sender the card kept): "Re: [example/app] Threads newest first (PR #46)" from notifications@github.com ->
    "example/app#46"; the same subject from anyone else -> ""; "Reply to Asha" -> ""."""
    if not github.is_from_github(str(item.get("sender") or "")):
        return ""
    for text in (item.get("subject") or "", item.get("title") or ""):
        found = SUBJECT_PR.search(text)
        if found is None:
            continue
        ref = github.parse(f"{found.group(1)}#{found.group(2)}")
        if ref is not None:
            return str(ref)
    return ""


def item_card(item: dict) -> dict:
    """What an old card item's card showed, kept on its loop."""
    card = {}
    for name in ("pile", "amount", "draft", "from", "subject", "when", "gist", "badges", "app", "thread", "sender",
                 "due"):
        if item.get(name):
            card[name] = item[name]
    suggestion = item.get("suggestion") or {}
    if isinstance(suggestion, dict) and suggestion.get("label"):
        card["suggestion"] = suggestion["label"]
    return card


def carry_items(store, pid: str, run: Run) -> None:
    """The Needs-you items of the owner's watch card (step 2 of this module's notes, and THE RULE above): each makes
    its own loop in its own state, or joins the loop of the same thing in the same state (same_thing_loop), or a pull
    request's open loop holding its thread (evidence only). Only a loop an item made takes its Done or its Later."""
    for item in needs_you_of(store, pid):
        ref = str(item.get("ref") or "")
        if not ref:
            continue
        is_open = not item.get("done")
        refs = [ref]
        if item.get("thread"):
            refs.append(f"thread:{item['thread']}")
        pr = pr_ref_of(item)
        if pr:
            refs.append(pr)
        at = run.now
        if zoned(item.get("at"), run.now):
            at = datetime.fromisoformat(zoned(item.get("at"), run.now))
        title = str(item.get("title") or "Needs you")[:120]
        fact = f"On the card: {title}"
        if item.get("why"):
            fact += f": {item['why']}"
        found = carried_into(store, pid, ref)
        if found is None:
            target = pr_loop_holding(store, pid, str(item.get("thread") or "") or ref.removeprefix("mail:"))
            if target is None:
                target = same_thing_loop(store, pid, ref, is_open, title)
            if target is not None:
                join_evidence(store, target, run, at, ref, fact, refs)
                if not target["playbook"]:
                    fields = item_card(item)
                    ledger.merge_card(store, target["id"], run.now,
                                      {k: v for k, v in fields.items() if k not in target["card"]})
                run.say(f"merge card item {ref} {title!r} into loop #{target['id']} {target['title']!r}")
                continue  # a joined loop takes nothing of the item's Done or Later
            pile = str(item.get("pile") or "alerts")
            due = findings.when_of(item.get("due"))
            lid = make_loop(store, pid, run, title, PILE_KIND.get(pile, "needs you"), "you", refs, at, fact, ref,
                            item_card(item), due)
            ledger.update(store, lid, run.now, result=str(item.get("why") or "")[:300])
            found = ledger.get(store, lid)
            run.say(f"create loop #{lid} {title!r} from card item {ref}")
        if not made_it(store, found, ref):
            continue
        # Each of the card's taps is carried once (a second run carries one made since, never one carried before:
        # a Done he reopened under the new code stays reopened).
        done_mark, later_mark = f"card-done:{ref}", f"card-later:{ref}"
        if item.get("done") and found["state"] in ledger.OPEN and not has_evidence(store, found["id"], done_mark):
            close_as(store, found["id"], "you", "Done", at)
            ledger.add_event(store, found["id"], at, JOINED, done_mark, "Ticked on the old card")
            run.say(f"  remember loop #{found['id']} as finished by you (ticked on the card)")
            continue
        until = zoned(item.get("hidden_until"), run.now)
        carried_later = has_evidence(store, found["id"], later_mark)
        if until and found["state"] in ledger.OPEN and not found.get("hidden_until") and not carried_later:
            ledger.update(store, found["id"], run.now, hidden_until=until)
            ledger.add_event(store, found["id"], run.now, JOINED, later_mark, f"Later on the old card: {until[:16]}")
            run.say(f"  keep Later on loop #{found['id']} until {until[:16]}")


def carry_flags(store, pid: str, run: Run) -> None:
    """What was pushed before (step 4 of this module's notes)."""
    from odie.loops import ladder
    from odie.watch.owner import key
    flagged_key = key("watch.flagged", pid)
    flagged = list(store.get_setting(flagged_key) or [])
    pushed_refs = [r for r in flagged if not r.startswith("loop:")]
    added = []
    for loop in all_loops(store, pid):
        if not set(pushed_refs) & set(loop["refs"]):
            continue
        name = f"loop:{loop['id']}"
        if name not in flagged and name not in added:
            added.append(name)
        if not ladder.has_step(store, loop["id"], ladder.DUE_PUSH):
            ledger.add_event(store, loop["id"], run.now, "upgrade", ladder.DUE_PUSH, "Pushed before the upgrade")
            run.say(f"flag loop #{loop['id']} {loop['title']!r} as pushed")
    if added:
        store.set_setting(flagged_key, [*added, *flagged][:500])


def finished_meanwhile(store, pid: str, loop: dict, kept: dict) -> bool:
    """Whether he finished a put-aside loop while the older code ran: one of the reminders that were open when it was
    put aside is now ticked or dropped, or one of its card items that were not done then is done now. What was
    already done before the rollback (a reminder that rang and he acted on, a Done he then reopened) never counts.
      the rent reminder, open at the rollback, ticked under the old code -> True
      a card item open at the rollback and gone from the older Odie's list now (he tapped Done there) -> True
      a reminder already done before the rollback, the loop still open -> False"""
    for task_id in kept.get("reminders") or []:
        row = store.one("select status from tasks where id=?", (int(task_id),))
        if row is not None and row["status"] in ("done", "dropped"):
            return True
    still_open_then = set(kept.get("items") or [])
    items = needs_you_of(store, pid)
    if any(item.get("done") and item.get("ref") in still_open_then for item in items):
        return True
    # The older Odie's Done (on Pulse, in chat, or "you replied") takes the item out of the list. A full list also
    # drops its oldest item unfinished, so a missing item counts only while the list is under its cap.
    listed = {item.get("ref") for item in items}
    return len(items) < OLD_CARD_CAP and any(ref not in listed for ref in still_open_then)


def bring_back(store, pid: str, run: Run) -> None:
    """After a rollback, the upgrade again: each loop put aside (closed by "rollback") opens again where it was, or,
    when he finished it meanwhile (finished_meanwhile), closes as his Done. What the older code tracked in between is
    carried over by the usual steps (they find what they carried before by its task or item)."""
    records = store.get_setting(ROLLBACK) or {}
    for loop in all_loops(store, pid):
        if loop["closed_by"] != ROLLBACK_CLOSER:
            continue
        at = run.now.isoformat(timespec="seconds")
        kept = records.get(str(loop["id"])) or {}
        if isinstance(kept, str):
            kept = {"state": kept}
        if finished_meanwhile(store, pid, loop, kept):
            store.execute("update loops set closed_by=?, closed_why=?, closed_at=?, updated_at=? where id=?",
                          (ledger.CLOSED_BY_USER, "Done (while the older Odie ran)", at, at, loop["id"]))
            run.say(f"keep loop #{loop['id']} {loop['title']!r} closed: you finished it while the older Odie ran")
            continue
        state = kept.get("state") or ledger.state_after_reopen(loop)
        store.execute("update loops set state=?, closed_by=null, closed_why=null, closed_at=null, updated_at=? "
                      "where id=?", (state, at, loop["id"]))
        run.say(f"bring back loop #{loop['id']} {loop['title']!r} ({state})")


def run(store, now: datetime) -> list[str]:
    """The upgrade, whatever version ran before, as ONE transaction: everything it writes, the version included, lands
    together or not at all (a crash midway leaves the database as it was, and the next start does it again). Returns
    what it did, line by line."""
    notes = Run(now)
    store.execute("begin immediate")
    try:
        for pid in owners(store):
            bring_back(store, pid, notes)
        store.set_setting(ROLLBACK, {})  # brought back: the next rollback starts from an empty record
        for pid in owners(store):
            carry_threads(store, pid, notes)
            carry_reminders(store, pid, notes)
            carry_items(store, pid, notes)
            carry_flags(store, pid, notes)
        store.set_setting(KEY, {"version": VERSION, "at": now.isoformat(timespec="seconds"), "lines": len(notes.lines)})
        store.execute("commit")
    except BaseException:
        store.execute("rollback")
        raise
    return notes.lines


def run_once(store, now: datetime) -> list[str] | None:
    """At startup: the upgrade when this database hasn't had it yet (KEY below VERSION), else None. A failure is
    logged and leaves the version unrecorded, so the next start tries again (the steps are safe to repeat)."""
    done = store.get_setting(KEY) or {}
    if int(done.get("version") or 0) >= VERSION:
        return None
    try:
        lines = run(store, now)
    except Exception:  # noqa: BLE001 (Odie starts anyway; the old cards are where they were)
        log.warning("loops: the upgrade failed; it runs again at the next start", exc_info=True)
        return None
    log.info("loops: upgraded the watch's threads and cards to loops (%d steps)", len(lines))
    return lines


NO_ORPHANS = "loops.no_orphans"  # {"version": 1, "at": "…", "loops": n}: the pass below ran
NO_ORPHANS_VERSION = 1


def no_orphans_once(store, now: datetime) -> list[str] | None:
    """At startup, once (NO_ORPHANS below NO_ORPHANS_VERSION): every open loop Odie owned with nothing for Odie to do
    (owner "odie", no playbook: ledger.owner_for) becomes his card ("you", ready, shown now), so it leaves "Odie is on
    it" for a card with Done. A pull request's loop, a closed loop and anyone else's are untouched. Returns what it
    did, line by line; None when it ran before.
      an open "Fix CI on PR" (odie, no playbook) -> his card;  a second start -> None, nothing changes"""
    done = store.get_setting(NO_ORPHANS) or {}
    if int(done.get("version") or 0) >= NO_ORPHANS_VERSION:
        return None
    at = now.isoformat(timespec="seconds")
    lines = []
    rows = store.query("select id, title from loops where owner='odie' and playbook='' and "
                       "state in ('new','working','ready','waiting') order by id")
    for row in rows:
        store.execute("update loops set owner='you', state='ready', shown_at=?, updated_at=? where id=?",
                      (at, at, row["id"]))
        ledger.add_event(store, row["id"], now, "upgrade", "", "Odie had nothing to do for it: now yours, with Done")
        lines.append(f"give loop #{row['id']} {row['title']!r} to you (Odie had no work for it)")
    store.set_setting(NO_ORPHANS, {"version": NO_ORPHANS_VERSION, "at": at, "loops": len(lines)})
    if lines:
        log.info("loops: %d loop(s) Odie had no work for are now cards", len(lines))
    return lines


OLD_CARD_CAP = 30  # the older Odie keeps at most this many Needs-you items (odie.watch.report: items[-30:])
ROLLBACK = "loops.rollback"  # {loop id: the state it had} for the loops before_rollback put aside
ROLLBACK_CLOSER = ledger.PUT_ASIDE


AFTER_ROLLBACK = "Start the older Odie now. If the newer one starts first, run this again."


def open_reminders(store, loop: dict) -> list[int]:
    """The reminders of Odie's this loop points at that are open now."""
    out = []
    for task_id in ledger.reminders_of(loop):
        row = store.one("select status, source_kind from tasks where id=?", (task_id,))
        if row is not None and row["source_kind"] in ledger.ODIES_TASKS and row["status"] in ("open", "waiting"):
            out.append(task_id)
    return out


def open_items(store, pid: str, loop: dict) -> list[str]:
    """The old card items this loop carried that are not done now."""
    carried = {e["ref"] for e in ledger.events(store, loop["id"]) if e["ref"] and e["source"] in (UPGRADE, JOINED)}
    return [str(i.get("ref")) for i in needs_you_of(store, pid) if not i.get("done") and i.get("ref") in carried]


def before_rollback(store, now: datetime) -> list[str]:
    """Readies the database for the code from before this upgrade (it knew loops only for pull requests, and read the
    Needs-you items from watch.card), so it shows nothing twice and nothing he closed:
      every open loop that isn't a pull request's is put aside (closed by "rollback", which the old code doesn't
        list and the new one never takes for his Done). ROLLBACK keeps, per loop, the state it had and what of its
        old self was still open at this moment (its open reminders, its card items not done), so the next upgrade
        counts only what he finishes from now on (finished_meanwhile); its reminders are left as they are;
      every old card item whose loop is closed gets done: true, so the old code doesn't bring it back;
      the upgrade's version is cleared, so the next start of the new code upgrades again (bring_back).
    One transaction; returns what it did, line by line, ending with what to do next. Twice -> the same."""
    lines: list[str] = []
    at = now.isoformat(timespec="seconds")
    store.execute("begin immediate")
    try:
        earlier = dict(store.get_setting(ROLLBACK) or {})
        record = {}
        for row in store.query("select id from loops where closed_by = ?", (ROLLBACK_CLOSER,)):
            if str(row["id"]) in earlier:  # put aside by a run of this step that the older Odie hasn't followed yet
                record[str(row["id"])] = earlier[str(row["id"])]
        for row in store.query("select id from loops where playbook = '' and "
                               "state in ('new','working','ready','waiting') order by id"):
            loop = ledger.get(store, row["id"])
            record[str(loop["id"])] = {"state": loop["state"], "reminders": open_reminders(store, loop),
                                       "items": open_items(store, loop["personality"], loop)}
            store.execute("update loops set state='closed', closed_by=?, closed_why=?, closed_at=?, updated_at=? "
                          "where id=?", (ROLLBACK_CLOSER, f"Put aside before a rollback (was {loop['state']})",
                                         at, at, loop["id"]))
            lines.append(f"put aside loop #{loop['id']} {loop['title']!r} (was {loop['state']})")
        store.set_setting(ROLLBACK, record)
        store.execute("delete from settings where key=?", (KEY,))  # the next start of the new code upgrades again
        for pid in owners(store):
            from odie.watch.owner import key
            card_key = key("watch.card", pid)
            card = store.get_setting(card_key)
            if not isinstance(card, dict) or not isinstance(card.get("needs_you"), list):
                continue
            changed = False
            for item in card["needs_you"]:
                if not isinstance(item, dict) or item.get("done"):
                    continue
                loop = carried_into(store, pid, str(item.get("ref") or ""))
                if loop is None or loop["state"] in ledger.OPEN or loop["closed_by"] == ROLLBACK_CLOSER:
                    continue
                item["done"] = True
                changed = True
                lines.append(f"mark card item {item.get('ref')} {item.get('title', '')!r} done (loop #{loop['id']} "
                             "is closed)")
            if changed:
                store.set_setting(card_key, card)
        store.execute("commit")
    except BaseException:
        store.execute("rollback")
        raise
    lines.append(AFTER_ROLLBACK)
    return lines


def on_a_copy(db: Path, now: datetime, step) -> list[str]:
    """What a step (run, before_rollback) would do to this database, done on a throwaway copy of it (the file given
    is only read)."""
    from odie.store.db import Store
    folder = Path(tempfile.mkdtemp(prefix="odie-migrate-dry-"))
    try:
        copy = folder / "copy.db"
        source = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        target = sqlite3.connect(copy)
        source.backup(target)
        source.close()
        target.close()
        store = Store(copy)
        store.init_schema()
        lines = step(store, now)
        store.close()
        return lines
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def dry_run(db: Path, now: datetime) -> list[str]:
    """What the upgrade would do to this database (on_a_copy)."""
    return on_a_copy(db, now, run)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m odie.loops.migrate", description=__doc__.split("\n\n")[0])
    parser.add_argument("--db", required=True, help="the database file (use a copy)")
    parser.add_argument("--dry-run", action="store_true", help="print what it would do; write nothing")
    parser.add_argument("--before-rollback", action="store_true",
                        help="ready the database for the code from before the upgrade (before_rollback)")
    parser.add_argument("--now", default="", help="the time to run as, ISO with offset (default: now, the user's zone)")
    args = parser.parse_args(argv)
    db = Path(args.db)
    if not db.is_file():
        print(f"No database at {db}")
        return 2
    now = datetime.now().astimezone()
    if args.now:
        now = datetime.fromisoformat(args.now)
    step = run
    if args.before_rollback:
        step = before_rollback
    if args.dry_run:
        lines = on_a_copy(db, now, step)
        print(f"Would make these changes ({len(lines)}):")
        for line in lines:
            print(f"  would {line}")
        return 0
    from odie.store.db import Store
    store = Store(db)
    store.init_schema()
    for line in step(store, now):
        print(line)
    store.close()
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
