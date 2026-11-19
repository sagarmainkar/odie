"""The upgrade to phase 3 of the proactive design (19 Nov 2026): what the watch kept in three places becomes loops, one
per real thing, so a Done is remembered whatever source mentions the thing again.

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


def carried_into(store, pid: str, ident: str) -> dict | None:
    """The loop an earlier run carried this very thing into (its "task:<id>", or a card item's own ref, in the loop's
    refs or evidence), whatever its state now: so a second run finds it and never makes a second loop."""
    for loop in all_loops(store, pid):
        if ident in loop["refs"]:
            return loop
    row = store.one("select loop_id from loop_events where ref = ? order by id limit 1", (ident,))
    if row is None:
        return None
    loop = ledger.get(store, row["loop_id"])
    if loop is None or loop["personality"] != pid:
        return None
    return loop


def join_target(store, pid: str, refs: list[str], is_open: bool) -> dict | None:
    """The loop another old thing joins by the same mail or the same pull request, never by a mail thread alone (one
    biller's thread holds every month's bill, and other bills too): an open thing only an OPEN loop (never one he or
    Odie closed); a closed thing any loop. The oldest that matches; None for none.
      Nov's open bill in thread T, Oct's loop (closed) holding T -> None;  the gas bill's item in T, Nov's open
      electricity loop holding T -> None;  an open card item for mail:r1, the open reply thread holding mail:r1 ->
      that loop;  the old "PR #46" item from GitHub, the PR's loop holding example/app#46 -> that loop"""
    wanted = {r for r in refs if r and not r.startswith("thread:")}  # a thread holds a biller's every month
    for loop in all_loops(store, pid):
        if is_open and loop["state"] not in ledger.OPEN:
            continue
        if wanted & set(loop["refs"]):
            return loop
    return None


def has_evidence(store, loop_id: int, ref: str) -> bool:
    return store.one("select 1 from loop_events where loop_id=? and ref=?", (loop_id, ref)) is not None


def make_loop(store, pid: str, run: Run, title: str, kind: str, owner: str, refs: list[str], created: datetime,
              fact: str, fact_ref: str, card: dict | None = None, due: str | None = None) -> int:
    """A loop made by the upgrade: open and shown now (the follow-up ladder, nudges included, starts at the upgrade,
    not at the old item's day), with its first evidence at the time the old thing was made."""
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
        is_open = row["status"] in ("open", "waiting")
        found = carried_into(store, pid, f"task:{row['id']}") or join_target(store, pid, refs[1:], is_open)
        stage = row["detail"] or ""
        fact = f"Followed by the watch: {row['title']}"
        if stage:
            fact += f" ({stage})"
        if found is not None:
            if f"task:{row['id']}" not in found["refs"]:
                ledger.add_refs(store, found["id"], run.now, refs)
                ledger.add_event(store, found["id"], local(row["created_at"], run.now), "upgrade", f"task:{row['id']}", fact)
                run.say(f"merge watch thread #{row['id']} {row['title']!r} into loop #{found['id']} {found['title']!r}")
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


def joins(row, seed) -> bool:
    """Whether a closed reminder is the same thing as a group's first reminder: the same mail or event; or the same
    title written the same way with the same due time, when at least one of the two names no single item (a digest
    note, a calendar text). Two items that differ are two things, whatever their titles.
      two digests' "Vote…" for one due time -> True;  the event's "Vote…" and a digest's "Vote…", one due -> True
      "Pay credit card bill" from one bank's mail and from another's, same due -> False
      "Pay rent" of October and of November (other due times) -> False"""
    mine, theirs = item_ref(row), item_ref(seed)
    if mine and theirs:
        return mine == theirs
    return same_words(row["title"]) == same_words(seed["title"]) and row["due_at"] == seed["due_at"]


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
    sibling he finished (his) with the same due time, completed before the open one was made. The vote ticked at
    09:10, made again at 10:33 for the same 08:30 deadline -> that open one; next month's bill (another due time) ->
    None; only a "Heads-up" ticked -> None."""
    opened = [r for r in group if r["status"] in ("open", "waiting")]
    if len(opened) != 1:
        return None
    current = opened[0]
    made = local(current["created_at"], now)
    for sibling in group:
        if sibling is current or not his(sibling) or sibling["due_at"] != current["due_at"]:
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
        if not due or not loop["due_at"]:
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
    """The Needs-you items of the owner's watch card (step 2 of this module's notes)."""
    from odie.watch.owner import key
    card = store.get_setting(key("watch.card", pid)) or {}
    for item in card.get("needs_you") or []:
        ref = str(item.get("ref") or "")
        if not ref:
            continue
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
        found = carried_into(store, pid, ref) or join_target(store, pid, refs, not item.get("done"))
        if found is None:
            pile = str(item.get("pile") or "alerts")
            due = findings.when_of(item.get("due"))
            lid = make_loop(store, pid, run, title, PILE_KIND.get(pile, "needs you"), "you", refs, at, fact, ref,
                            item_card(item), due)
            ledger.update(store, lid, run.now, result=str(item.get("why") or "")[:300])
            found = ledger.get(store, lid)
            run.say(f"create loop #{lid} {title!r} from card item {ref}")
        elif not has_evidence(store, found["id"], ref):
            ledger.add_refs(store, found["id"], run.now, [r for r in refs if r not in found["refs"]])
            ledger.add_event(store, found["id"], at, "upgrade", ref, fact)
            if not found["playbook"]:
                fields = item_card(item)
                ledger.merge_card(store, found["id"], run.now, {k: v for k, v in fields.items() if k not in found["card"]})
                if item.get("why") and not found["result"]:
                    ledger.update(store, found["id"], run.now, result=str(item["why"])[:300])
            run.say(f"merge card item {ref} {title!r} into loop #{found['id']} {found['title']!r}")
        found = ledger.get(store, found["id"])  # (carried by an earlier run too: its Done and Later still apply)
        if item.get("done") and found["state"] in ledger.OPEN and not found["playbook"]:
            close_as(store, found["id"], "you", "Done", at)
            run.say(f"  remember loop #{found['id']} as finished by you (ticked on the card)")
            continue
        until = zoned(item.get("hidden_until"), run.now)
        if until and found["state"] in ledger.OPEN and not found.get("hidden_until"):
            ledger.update(store, found["id"], run.now, hidden_until=until)
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


def finished_meanwhile(store, pid: str, loop: dict) -> bool:
    """Whether he finished a put-aside loop while the older code ran: a reminder of Odie's it points at was ticked or
    dropped, or an old card item it carried is now done. The rent reminder ticked under the old code -> True; the
    school fee's reminder still open -> False."""
    for task_id in ledger.reminders_of(loop):
        row = store.one("select status, source_kind from tasks where id=?", (task_id,))
        if row is not None and row["source_kind"] in ledger.ODIES_TASKS and row["status"] in ("done", "dropped"):
            return True
    from odie.watch.owner import key
    card = store.get_setting(key("watch.card", pid)) or {}
    carried = {e["ref"] for e in ledger.events(store, loop["id"]) if e["ref"]}
    return any(item.get("done") and item.get("ref") in carried for item in card.get("needs_you") or [])


def bring_back(store, pid: str, run: Run) -> None:
    """After a rollback, the upgrade again: each loop put aside (closed by "rollback") opens again where it was, or,
    when he finished it meanwhile (finished_meanwhile), closes as his Done. What the older code tracked in between is
    carried over by the usual steps (they find what they carried before by its task or item)."""
    states = store.get_setting(ROLLBACK) or {}
    for loop in all_loops(store, pid):
        if loop["closed_by"] != ROLLBACK_CLOSER:
            continue
        at = run.now.isoformat(timespec="seconds")
        if finished_meanwhile(store, pid, loop):
            store.execute("update loops set closed_by=?, closed_why=?, closed_at=?, updated_at=? where id=?",
                          (ledger.CLOSED_BY_USER, "Done (while the older Odie ran)", at, at, loop["id"]))
            run.say(f"keep loop #{loop['id']} {loop['title']!r} closed: you finished it while the older Odie ran")
            continue
        state = states.get(str(loop["id"])) or ledger.state_after_reopen(loop)
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


ROLLBACK = "loops.rollback"  # {loop id: the state it had} for the loops before_rollback put aside
ROLLBACK_CLOSER = ledger.PUT_ASIDE


def before_rollback(store, now: datetime) -> list[str]:
    """Readies the database for the code from before this upgrade (it knew loops only for pull requests, and read the
    Needs-you items from watch.card), so it shows nothing twice and nothing he closed:
      every open loop that isn't a pull request's is put aside (closed by "rollback", which the old code doesn't
        list and the new one never takes for his Done; the state it had kept in ROLLBACK) — its reminders are left as
        they are, so they still ring;
      every old card item whose loop is closed gets done: true, so the old code doesn't bring it back;
      the upgrade's version is cleared, so the next start of the new code upgrades again (bring_back).
    One transaction; returns what it did, line by line."""
    lines: list[str] = []
    at = now.isoformat(timespec="seconds")
    store.execute("begin immediate")
    try:
        put_aside = dict(store.get_setting(ROLLBACK) or {})
        for row in store.query("select id, title, state, personality from loops where playbook = '' and "
                               "state in ('new','working','ready','waiting') order by id"):
            put_aside[str(row["id"])] = row["state"]
            store.execute("update loops set state='closed', closed_by=?, closed_why=?, closed_at=?, updated_at=? "
                          "where id=?", (ROLLBACK_CLOSER, f"Put aside before a rollback (was {row['state']})",
                                         at, at, row["id"]))
            lines.append(f"put aside loop #{row['id']} {row['title']!r} (was {row['state']})")
        store.set_setting(ROLLBACK, put_aside)
        store.execute("delete from settings where key=?", (KEY,))  # the next start of the new code upgrades again
        for pid in owners(store):
            from odie.watch.owner import key
            card_key = key("watch.card", pid)
            card = store.get_setting(card_key) or {}
            changed = False
            for item in card.get("needs_you") or []:
                if item.get("done"):
                    continue
                loop = carried_into(store, pid, str(item.get("ref") or ""))
                if loop is None or loop["state"] in ledger.OPEN or str(loop["id"]) in put_aside:
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
