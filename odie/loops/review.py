"""The evening review (proactive design §8, his approval of 19 Nov in §17): at 19:30, once a day for each proactive
owner (everyday Odie, and each personality with Proactive intelligence on), ONE model call with no tools re-reads the
owner's open loops against tomorrow's calendar (the events the watch already fetched: no new read), the Now list,
the Quiet rules and today's taps, and answers in a fixed schema. Code applies the answer within rails:

  merge     two open loops that are one thing: the older one keeps both's evidence (odie.loops.ledger.merge)
  split     a loop holding two things: the evidence ids named move to a loop of their own
  priority  high / normal / low
  stale     his own loop is only marked (low, and the digest asks); one waiting on someone, or Odie's, is dropped by
            Odie (Reopen in Done today)
  quiet     a Quiet rule proposed as a card; only his tap writes it (odie.loops.quiet)
  now       a Now list proposed as the Now card; only his tap changes it (odie.loops.now)
  skills    an idea for a skill, recorded: the morning learning check reads it (odie.loops.learning)
  digest    the evening digest's words (odie.loops.digest checks them)

Rails: only this owner's OPEN loops, by number; a pull request's or a promise's loop (a playbook) gets priority
only; two loops that both carry an amount (two bills, two orders) are never merged; a split never moves all of a
loop's evidence; it never closes his loops as his Done; at most MOST changes of each kind. Every change leaves an
evidence line "Evening review: …" and a change record he can Undo (on the digest). The loops' words came partly from
mail: they are fenced, and whatever the answer says, the review can only do the above (the call has no tools).

The safety shape of stage 2 (odie.loops.consolidate): the call that has private context can only answer."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

from odie.agent.callbacks import wrap_untrusted
from odie.loops import budget, digest, learn, ledger, quiet
from odie.loops import now as now_list
from odie.loops.secret import secret_in

log = logging.getLogger("odie.loops")
SKILL = Path(__file__).parent / "skill" / "REVIEW.md"  # the prompt: the owner reads and edits it
AT = (19, 30)
DAY = "review.day"  # per owner (odie.watch.owner.key): the day it last ran, "2026-11-19"
CHANGES = "review.changes"  # per owner: {"next": 4, "items": [{"id", "day", "at", "what", "words", "undo", "state"}]}
SKILL_IDEAS = "review.skill_ideas"  # per owner: [{"at", "title", "why"}], newest last
OPEN_SHOWN = 60
EVIDENCE_SHOWN = 4
CLOSED_DAYS = 2
MOST = {"merge": 5, "split": 3, "priority": 20, "stale": 10, "quiet": 2, "skills": 3}
WHY_MOST = 160
STALE_AFTER = timedelta(days=14)  # no evidence for this long, and no due time ahead, before a loop may be stale
KEEP_CHANGES = 60
KEEP_IDEAS = 20
EVIDENCE_ID = re.compile(r"^e?(\d+)$")


def _key(pid: str, name: str) -> str:
    from odie.watch.owner import key
    return key(name, pid)


def instruction() -> str:
    """The prompt's text, after its front matter."""
    return SKILL.read_text().split("---", 2)[-1].strip()


# --- when ---

def due(store, pid: str, now: datetime) -> bool:
    """Whether this owner's review is due: it is AT (19:30) or later today and it hasn't run today. 19:29 -> False;
    19:30 -> True; ran at 19:31, asked at 20:30 -> False; the next evening -> True. (Before midnight only: a Mac that
    wakes at 01:00 doesn't review yesterday.)"""
    if (now.hour, now.minute) < AT:
        return False
    return store.get_setting(_key(pid, DAY)) != now.date().isoformat()


def mark_ran(store, pid: str, now: datetime) -> None:
    store.set_setting(_key(pid, DAY), now.date().isoformat())


def owners_due(store, now: datetime) -> list[str]:
    """The owners whose review is due now: everyday Odie, and each personality with Proactive intelligence on."""
    from odie.loops import clock
    return [pid for pid in clock.owners(store) if due(store, pid, now)]


def worth_a_call(store, pid: str, now: datetime) -> bool:
    """Whether the review has anything to read: an open loop, or one closed today. Nothing open and nothing closed ->
    False (no call: the design's "no call when nothing is new")."""
    if ledger.open_loops(store, pid):
        return True
    return bool(ledger.closed_since(store, pid, digest.start_of_day(now))) or bool(
        digest.facts(store, pid, now)["you_closed"])


# --- what it reads ---

def loop_line(loop: dict, evidence: list[dict], now: datetime) -> str:
    """One open loop for the review, with what the rails care about: "#3 Send the deck · reply owed · owner you ·
    ready · priority normal · due 2026-11-21 · amount ₹2,100 · shown 2 days ago · playbook github-pr", then its last
    EVIDENCE_SHOWN lines, each with its id: "  e12 18 Nov 10:02 mail: Asha asks for the deck"."""
    bits = [f"#{loop['id']} {loop['title']}", loop["kind"] or "?", f"owner {loop['owner']}", loop["state"],
            f"priority {loop['priority']}"]
    if loop.get("due_at"):
        bits.append(f"due {loop['due_at'][:16]}")
    amount = loop["card"].get("amount")
    if isinstance(amount, dict):
        from odie.watch import cards as card_text
        bits.append(f"amount {card_text.money(amount)}")
    if loop["card"].get("sender"):
        bits.append(f"from {loop['card']['sender']}")
    if loop.get("shown_at"):
        bits.append(f"shown {(now - datetime.fromisoformat(loop['shown_at'])).days} days ago")
    if loop["playbook"]:
        bits.append(f"playbook {loop['playbook']} (priority only)")
    lines = [" · ".join(bits)]
    for e in evidence[-EVIDENCE_SHOWN:]:
        at = datetime.fromisoformat(e["at"])
        lines.append(f"  e{e['id']} {at.day} {at.strftime('%b %H:%M')} {e['source']}: {e['fact'][:160]}")
    return "\n".join(lines)


def tomorrow_events(store, pid: str, now: datetime) -> list[str]:
    """Tomorrow's events from the watch's last check (already fetched; nothing is read now): "15:00 Call with Asha"."""
    from odie.watch import report
    card = store.get_setting(_key(pid, report.CARD)) or {}
    tomorrow = (now + timedelta(days=1)).date().isoformat()
    out = []
    for event in card.get("events") or []:
        start = str(event.get("start") or "")
        if start[:10] == tomorrow:
            out.append(f"{start[11:16] or 'all day'} {event.get('title') or ''}".strip())
    return out


def recently_closed(store, pid: str, now: datetime) -> list[str]:
    since = now - timedelta(days=CLOSED_DAYS)
    out = []
    for loop in ledger.finished(store, pid, now):
        if datetime.fromisoformat(loop["closed_at"]) < since:
            continue
        who = "the user"
        if loop["closed_by"] not in ledger.BY_HIM:
            who = "Odie"
        out.append(f"#{loop['id']} {loop['title']} · closed by {who}: {loop['closed_why'] or ''}"[:200])
    return out


def prompt_for(store, pid: str, now: datetime) -> str:
    """What the review reads. Every block that carries words from outside (loop titles and evidence, events, the Now
    list and Quiet rules, which may hold a loop's words, today's taps on cards, the day's facts) is fenced as data."""
    loops = ledger.open_loops(store, pid)[-OPEN_SHOWN:]
    open_text = "\n".join(loop_line(lp, ledger.events(store, lp["id"]), now) for lp in loops)
    tomorrow = now + timedelta(days=1)
    parts = [f"It is {now.strftime('%A %-d %B %Y, %H:%M')}. Tomorrow is {tomorrow.strftime('%A %-d %B')}.",
             f"Open loops (under each, its latest evidence with ids):\n{wrap_untrusted(open_text or '(none)')}",
             f"Closed in the last {CLOSED_DAYS} days:\n"
             f"{wrap_untrusted(chr(10).join(recently_closed(store, pid, now)) or '(none)')}",
             f"Tomorrow's calendar:\n{wrap_untrusted(chr(10).join(tomorrow_events(store, pid, now)) or '(nothing)')}",
             f"Now:\n{wrap_untrusted(now_list.text(store, pid) or '(empty)')}",
             f"Quiet rules:\n{wrap_untrusted(quiet.text_for_model(store, pid) or '(none)')}",
             f"His taps on cards today:\n{wrap_untrusted(learn.today_text(store, pid, now) or '(none)')}",
             f"Today, for the digest:\n{wrap_untrusted(digest.facts_text(digest.facts(store, pid, now)))}"]
    return "\n\n".join(parts)


def parse(text: str) -> dict | None:
    """The model's answer in the fixed schema, from the first JSON object in its reply; None when there is none. A
    part of the wrong shape is empty: lists stay lists of objects, "now" an object or None, "digest" text.
      '{"merge": [{"loops": [1, 2]}], "split": "x", "digest": "Hi"}' -> merge kept, split [], digest "Hi";
      "no idea" -> None"""
    found = re.search(r"\{.*\}", text or "", re.S)
    if found is None:
        return None
    try:
        raw = json.loads(found.group(0))
    except ValueError:
        return None
    if not isinstance(raw, dict):
        return None
    out: dict = {}
    for name in ("merge", "split", "priority", "stale", "quiet", "skills"):
        value = raw.get(name)
        if not isinstance(value, list):
            value = []
        out[name] = [item for item in value if isinstance(item, dict)]
    now_part = raw.get("now")
    if not isinstance(now_part, dict):
        now_part = None
    out["now"] = now_part
    words = raw.get("digest")
    if not isinstance(words, str):
        words = ""
    out["digest"] = words
    return out


# --- the rails ---

def number(value) -> int | None:
    """A loop number as written: 3, "3", "#3" -> 3; "three", None -> None."""
    text = str(value if value is not None else "").strip().lstrip("#")
    if text.isdigit():
        return int(text)
    return None


def mine(store, pid: str, value) -> dict | None:
    """The loop a number names, when it is this owner's and open; anything else -> None (left alone)."""
    n = number(value)
    if n is None:
        return None
    loop = ledger.get(store, n)
    if loop is None or loop["personality"] != pid or loop["state"] not in ledger.OPEN:
        return None
    return loop


def merged_lately(store, loop: dict, now: datetime) -> bool:
    """Whether a loop took part in a merge within REOPEN_DAYS: it absorbed another ("Evening review: merged #5 …") or
    was merged into one and put back. A loop merged yesterday -> True; a merge 8 days ago -> False; never -> False."""
    since = now - timedelta(days=ledger.REOPEN_DAYS)
    for e in ledger.events(store, loop["id"]):
        took_part = e["fact"].startswith(("Evening review: merged #", "Closed: Evening review: merged into"))
        if took_part and datetime.fromisoformat(e["at"]) >= since:
            return True
    return False


def why_not_merge(store, a: dict | None, b: dict | None, now: datetime) -> str | None:
    """Why two loops may not be merged, or None when they may: both this owner's open loops (mine), two different
    ones, neither a playbook's, not both carrying an amount (two bills or orders are two things, whatever the model
    thinks), not two different senders (two people), and neither in a merge this week (no chains: each merge stays
    one Undo).
      "Send the deck" + "Call about the deck" -> None;  a loop and itself -> "the same loop";  a loop + a pull request
      -> "a pull request or a promise";  two loops with amounts -> "two amounts: two bills or orders";  asha@… and
      ravi@… -> "two senders";  a loop that absorbed another yesterday -> "merged lately";  a loop + None -> "not an
      open loop of this owner\""""
    if a is None or b is None:
        return "not an open loop of this owner"
    if a["id"] == b["id"]:
        return "the same loop"
    if a["playbook"] or b["playbook"]:
        return "a pull request or a promise"
    if a["card"].get("amount") and b["card"].get("amount"):
        return "two amounts: two bills or orders"
    sender_a = quiet.sender_of(a)
    sender_b = quiet.sender_of(b)
    if sender_a and sender_b and sender_a != sender_b:
        return "two senders: two people's things"
    if merged_lately(store, a, now) or merged_lately(store, b, now):
        return "merged lately: one merge at a time, so each stays one Undo"
    return None


def evidence_ids(values) -> list[int]:
    """The evidence ids the model named: ["e12", 15, "e x"] -> [12, 15]."""
    if not isinstance(values, list):
        return []
    out = []
    for value in values:
        found = EVIDENCE_ID.match(str(value).strip())
        if found:
            out.append(int(found.group(1)))
    return out


def why_of(item: dict) -> str:
    """The model's reason, as it may be kept in evidence: one line, at most WHY_MOST characters, nothing secret."""
    words = " ".join(str(item.get("why") or "").split())[:WHY_MOST]
    if secret_in(words):
        return ""
    return words


class Applied:
    """What one review did: the change records made, what was refused (and why), how many proposals."""

    def __init__(self):
        self.changes: list[dict] = []
        self.refused: list[str] = []
        self.proposals = 0
        self.touched: set[int] = set()


def record(store, pid: str, now: datetime, what: str, words: str, undo: dict) -> dict:
    """A change the review made, kept with what Undo needs."""
    saved = store.get_setting(_key(pid, CHANGES)) or {}
    nxt = int(saved.get("next") or 1)
    item = {"id": nxt, "day": now.date().isoformat(), "at": now.isoformat(timespec="seconds"), "what": what,
            "words": words[:200], "undo": undo, "state": "done"}
    items = [*(saved.get("items") or []), item][-KEEP_CHANGES:]
    store.set_setting(_key(pid, CHANGES), {"next": nxt + 1, "items": items})
    return item


def changes_of(store, pid: str, day: str) -> list[dict]:
    """The review's changes of one day (the digest lists them, each with Undo)."""
    saved = store.get_setting(_key(pid, CHANGES)) or {}
    return [c for c in saved.get("items") or [] if c["day"] == day and c["state"] == "done"]


def note(store, loop_id: int, now: datetime, words: str) -> None:
    ledger.add_event(store, loop_id, now, "odie", "review", f"Evening review: {words}"[:500])


def do_merge(store, pid: str, now: datetime, item: dict, done: Applied) -> None:
    ids = item.get("loops")
    if not isinstance(ids, list) or len(ids) != 2:
        return
    a = mine(store, pid, ids[0])
    b = mine(store, pid, ids[1])
    reason = why_not_merge(store, a, b, now)
    if reason is None and ({a["id"], b["id"]} & done.touched):
        reason = "changed already in this review"
    if reason is not None:
        done.refused.append(f"merge {ids}: {reason}")
        return
    keep, gone = sorted((a, b), key=lambda lp: lp["id"])  # the older loop is kept: he has seen it longer
    ledger.merge(store, keep["id"], gone["id"], now, why_of(item))
    done.touched.update({keep["id"], gone["id"]})
    done.changes.append(record(store, pid, now, "merge", f"Merged “{gone['title'][:60]}” into “{keep['title'][:60]}”",
                               {"loop": gone["id"]}))


def do_split(store, pid: str, now: datetime, item: dict, done: Applied) -> None:
    loop = mine(store, pid, item.get("loop"))
    if loop is None or loop["playbook"] or loop["id"] in done.touched:
        done.refused.append(f"split {item.get('loop')}: not a loop it may split")
        return
    own = [e["id"] for e in ledger.events(store, loop["id"])]
    picked = [i for i in evidence_ids(item.get("evidence")) if i in own]
    if not picked or len(picked) >= len(own) or len(picked) != len(evidence_ids(item.get("evidence"))):
        done.refused.append(f"split #{loop['id']}: evidence must be some, not all, of its own lines")
        return
    title = " ".join(str(item.get("title") or "").split())[:120]
    if secret_in(title):
        title = ""
    new_id = ledger.split(store, loop["id"], picked, now, by="odie", why=why_of(item), title=title)
    done.touched.update({loop["id"], new_id})
    new_title = ledger.get(store, new_id)["title"]
    done.changes.append(record(store, pid, now, "split", f"Split “{new_title[:60]}” off “{loop['title'][:60]}”",
                               {"loop": new_id}))


def do_priority(store, pid: str, now: datetime, item: dict, done: Applied) -> None:
    loop = mine(store, pid, item.get("loop"))
    to = str(item.get("to") or item.get("priority") or "").strip().lower()
    if loop is None or to not in ledger.PRIORITIES or loop["id"] in done.touched:
        return
    if to == loop["priority"]:
        return
    ledger.update(store, loop["id"], now, priority=to)
    why = why_of(item)
    words = f"priority {to}"
    if why:
        words += f": {why}"
    note(store, loop["id"], now, words)
    done.touched.add(loop["id"])
    done.changes.append(record(store, pid, now, "priority", f"“{loop['title'][:60]}”: priority {to}",
                               {"loop": loop["id"], "priority": loop["priority"]}))


def looks_stale(store, loop: dict, now: datetime) -> bool:
    """Whether a loop may be called stale at all: no due time still ahead, and no evidence in the last STALE_AFTER.
    An order shipped 6 weeks ago, nothing since -> True; a refund due the day after tomorrow -> False; an order with
    news 5 days ago -> False."""
    due = loop.get("due_at")
    if due and datetime.fromisoformat(due) > now:
        return False
    for e in ledger.events(store, loop["id"]):
        if now - datetime.fromisoformat(e["at"]) < STALE_AFTER:
            return False
    return True


def odies_open_reminders(store, loop: dict) -> list[int]:
    """The open reminders only Odie makes (ledger.ODIE_ONLY) that this loop points at: a drop ticks these."""
    out = []
    for task_id in ledger.reminders_of(loop):
        row = store.one("select status, source_kind from tasks where id=?", (task_id,))
        if row is not None and row["status"] in ("open", "waiting") and row["source_kind"] in ledger.ODIE_ONLY:
            out.append(task_id)
    return out


def do_stale(store, pid: str, now: datetime, item: dict, done: Applied) -> None:
    """His loop (owner you) is only marked: priority low, "stale" on its card, the digest asks; never closed. A loop
    waiting on someone, or Odie's, is dropped by Odie, with Reopen; the reminders the drop ticks are kept with it, so
    Undo or Reopen brings them back. Only a loop that looks stale (looks_stale) may be either."""
    loop = mine(store, pid, item.get("loop"))
    if loop is None or loop["playbook"] or loop["id"] in done.touched:
        done.refused.append(f"stale {item.get('loop')}: not a loop it may mark")
        return
    if not looks_stale(store, loop, now):
        done.refused.append(f"stale #{loop['id']}: due ahead, or news within {STALE_AFTER.days} days")
        return
    why = why_of(item) or "nothing new for a long time"
    done.touched.add(loop["id"])
    if loop["owner"] == "you":
        ledger.update(store, loop["id"], now, priority="low")
        ledger.merge_card(store, loop["id"], now, {"stale": why})
        note(store, loop["id"], now, f"looks stale: {why}")
        done.changes.append(record(store, pid, now, "stale", f"“{loop['title'][:60]}” looks stale",
                                   {"loop": loop["id"], "priority": loop["priority"]}))
        return
    ticked = odies_open_reminders(store, loop)
    ledger.close(store, loop["id"], now, "odie", f"Evening review: stale: {why}", state="dropped")
    ledger.merge_card(store, loop["id"], now, {ledger.TICKED: ticked})
    done.changes.append(record(store, pid, now, "drop", f"Dropped “{loop['title'][:60]}”: stale",
                               {"loop": loop["id"], "tasks": ticked}))


def senders(store, pid: str) -> set[str]:
    """The sender addresses on this owner's open loops: a Quiet proposal may name only one of these."""
    return {quiet.sender_of(lp) for lp in ledger.open_loops(store, pid)} - {""}


def propose(store, pid: str, now: datetime, answer: dict, done: Applied) -> None:
    """The proposals: Quiet rules and a Now list as cards for his tap; skill ideas recorded."""
    known = senders(store, pid)
    kinds = {learn.kind_of(lp["kind"]) for lp in ledger.open_loops(store, pid)} - {""}
    for item in answer["quiet"][:MOST["quiet"]]:
        if learn.kind_of(str(item.get("kind") or "")) not in kinds:
            continue  # only a kind on one of his open loops: never words the answer made up
        sender = str(item.get("sender") or "").strip().lower()
        if sender not in known:
            sender = ""  # only an address on one of his loops: never one the answer made up
        if quiet.propose(store, pid, now, str(item.get("kind") or ""), sender, why_of(item)) is not None:
            done.proposals += 1
    wanted = answer["now"]
    if wanted is not None and now_list.open_proposal(store, pid) is None:
        got = now_list.parse(json.dumps({"lines": wanted.get("lines") or [], "why": why_of(wanted)}))
        if got is not None and now_list.offer(store, pid, now, got[0], got[1]) is not None:
            done.proposals += 1
    for item in answer["skills"][:MOST["skills"]]:
        title = " ".join(str(item.get("title") or "").split())[:120]
        if title and not secret_in(title):
            ideas = list(store.get_setting(_key(pid, SKILL_IDEAS)) or [])
            ideas.append({"at": now.isoformat(timespec="seconds"), "title": title, "why": why_of(item)})
            store.set_setting(_key(pid, SKILL_IDEAS), ideas[-KEEP_IDEAS:])
            done.proposals += 1


def skill_ideas(store, pid: str) -> list[dict]:
    """The skill ideas the review recorded (the morning learning check reads the last few)."""
    return list(store.get_setting(_key(pid, SKILL_IDEAS)) or [])


def apply(store, pid: str, now: datetime, answer: dict) -> Applied:
    """Writes the review's answer to the ledger within the rails (this module's notes)."""
    done = Applied()
    for item in answer["merge"][:MOST["merge"]]:
        do_merge(store, pid, now, item, done)
    for item in answer["split"][:MOST["split"]]:
        do_split(store, pid, now, item, done)
    for item in answer["stale"][:MOST["stale"]]:
        do_stale(store, pid, now, item, done)
    for item in answer["priority"][:MOST["priority"]]:
        do_priority(store, pid, now, item, done)
    propose(store, pid, now, answer, done)
    return done


def undo(store, pid: str, change_id: int, now: datetime) -> bool:
    """His Undo on one of the review's changes (this owner's own, once): a merge is put back apart, a split put back
    together, a priority or a stale mark goes back to what it was, a drop is reopened. False when there is no such
    change or it can't be undone any more (the loop is gone)."""
    saved = store.get_setting(_key(pid, CHANGES)) or {}
    items = list(saved.get("items") or [])
    change = next((c for c in items if c["id"] == int(change_id) and c["state"] == "done"), None)
    if change is None:
        return False
    loop = ledger.get(store, int(change["undo"]["loop"]))
    if loop is None or loop["personality"] != pid:
        return False
    what = change["what"]
    ok = False
    if what == "merge":
        ok = ledger.unmerge(store, loop["id"], now)
    elif what == "split":
        ok = ledger.unsplit(store, loop["id"], now)
    elif what in ("priority", "stale"):
        ledger.update(store, loop["id"], now, priority=change["undo"]["priority"])
        if what == "stale":
            card = {k: v for k, v in loop["card"].items() if k != "stale"}
            store.execute("update loops set card_json=? where id=?", (json.dumps(card, ensure_ascii=False), loop["id"]))
        ledger.add_event(store, loop["id"], now, "you", "", f"Undone by you: {change['words']}")
        ok = True
    elif what == "drop" and loop["state"] not in ledger.OPEN:
        ledger.reopen(store, loop["id"], now)
        ok = True
    if ok:
        change["state"] = "undone"
        store.set_setting(_key(pid, CHANGES), {**saved, "items": items})
    return ok


async def run(store, pid: str, now: datetime, think, push=None) -> dict:
    """This owner's evening: learning from taps (code), then the review's one call when there is something to read and
    a call left today, then the digest (the review's words, else code's) and its push when something needs him.
    think(prompt, instruction) is the call with no tools on the owner's brain. Marked as run first: once a day,
    whatever comes of it."""
    mark_ran(store, pid, now)
    learned = learn.learn(store, pid, now)
    called = False
    answer = None
    if worth_a_call(store, pid, now) and budget.spend(store, now):
        called = True
        try:
            answer = parse(await think(prompt_for(store, pid, now), instruction()))
        except Exception:  # noqa: BLE001 (a failed call: the digest in code's words, the ledger untouched)
            log.warning("review: the model call failed", exc_info=True)
    applied = Applied()
    words = None
    if answer is not None:
        applied = apply(store, pid, now, answer)
        words = answer["digest"]
    evening = digest.make_evening(store, pid, now, words)
    said = digest.tell(store, pid, now, evening, push)
    return {"called": called, "learned": learned, "changes": applied.changes, "refused": applied.refused,
            "proposals": applied.proposals, "said": said}
