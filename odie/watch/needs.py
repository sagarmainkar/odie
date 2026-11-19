"""Pulse's "Needs you" (23 Oct 2026; a view of the ledger since 19 Nov 2026, proactive design phase 3): one list of
cards. First the loops that need the user (odie.loops.cards: everything the watch found, one card per real thing),
then the "Track this?" offers from chat (odie.loops.offers), then jobs that need him, then his own open reminders, dues and to-dos, soonest due first (a reminder Odie made for a
loop is that loop's, never a card of its own). Every card has the same three buttons (18 Nov 2026): its one move
("main"), Done ("other": off the list and no longer followed, whether it was done or won't be) and Later ("later":
hidden until 09:00 the next morning, then back). What a button does is decided here, the app only carries it out:
  "chat": send the value as the user's chat request ("Show the draft for loop #3");
  "dismiss": Sunday's "Still care?" card's "Drop them", a "Track this?" offer's No (POST /api/watch/done with its ref);
  "track": a "Track this?" offer's Track (POST /api/offers/<id>/track: a loop of his, with its reminder);
  "now_accept" / "now_edit": Odie's proposed Now list taken as it is (POST /api/now/<id>/accept), or opened to change;
  "quiet_accept": a Quiet rule the evening review proposed, written (POST /api/quiet/<id>/accept);
  "learn_undo": "Fewer cards for X" undone: that kind is cards again (POST /api/learned/<id>/undo);
  "loop_done": a loop's Done (POST /api/loops/<id>/done);
  "done_task" / "snooze_task": tick a task off, or move it to tomorrow 09:00;
  "later": put the card off until 09:00 the next morning (POST /api/needs_you/later with the card's ref).
A loop's card also has a small menu ("more"), which the Mac app doesn't read yet: "split", "less_like_this" (his Quiet
rule: POST /api/loops/<id>/less) and "forget" (the loop and its evidence deleted: POST /api/loops/<id>/forget).
Every card also says where it belongs and how it should be shown (25 Oct 2026, for the Mac app's buckets):
  "pile": one of report.PILES ("bills", "orders", "alerts", ...);
  "since": when the card started needing the user, as ISO with an offset ("2026-10-21T09:00:00+05:30"), or "";
  "decide": true when Odie has no move to offer, so the choice is the user's (two equal buttons)."""
from __future__ import annotations

import re
from datetime import datetime, time, timedelta

from odie.watch import bills, report, threads
from odie.watch import cards as card_text
from odie.watch.owner import ODIE, key

NOTES_HOURS = 24  # what the watch told the user stays under Needs you for a day
MAIL_TITLE = re.compile(r"^Reply to (.+?): (.*)$")  # the title an inbox add-on gives its "reply to" tasks
PILE_OF_ICON = {"rupee": "bills", "ticket": "orders"}  # a task's pile follows its icon; every other icon is "alerts"
LATER_AT = time(9, 0)  # Later brings a card back at this hour of the next day (the owner's choice, 18 Nov 2026)
TELL_ME_MORE = "Tell me more"


def cards(store, now: datetime, owner: str = ODIE) -> list[dict]:
    """Everything that needs the user, as cards: the loops in "ready" (one each), the jobs that need him, then his own
    open tasks. Everyday Odie's Pulse (owner ""), or a personality's: its own loops and tasks, never the everyday ones
    (they are on Odie's)."""
    from odie.loops import cards as loop_cards
    from odie.loops import learn, offers, quiet
    from odie.loops import now as now_list
    out = loop_cards.cards(store, owner, now)  # one card per ready loop, first
    out += offers.cards(store, owner, now)  # "Track this?": his own words from chat, tracked only on his tap
    out += now_list.cards(store, owner)  # "Update your Now?": Odie's weekly proposal, changed only on his tap
    out += quiet.proposal_cards(store, owner)  # "Quiet these?": the evening review's proposal, a rule only on his tap
    out += learn.notice_cards(store, owner)  # "Fewer cards for X": said once, with Undo
    from odie.workers import cards as job_cards
    out += job_cards.cards(store, owner, now)  # a job that failed, got stuck or needed his OK
    a_loops = loops_reminders(store, owner)
    tasks = [t for t in owners_tasks(store, now, owner) if shows_as_task(t, a_loops)]
    tasks.sort(key=lambda t: t["due_at"] or "9999")
    out += [task_card(t, now) for t in tasks]
    return out


def loops_reminders(store, owner: str) -> set[int]:
    """The reminders Odie made that open loops point at: their cards are the loops'. Only Odie's own (made for a loop,
    a watch thread of old, a reminder the watch added): his own task is never hidden behind a loop, whatever points at
    it. The vote loop's reminder -> hidden (the loop is the card); his "Renew passport" -> always its own card."""
    from odie.loops import ledger
    pointed = set()
    for loop in ledger.open_loops(store, owner):
        pointed.update(ledger.reminders_of(loop))
    out = set()
    for task_id in pointed:
        row = store.one("select source_kind from tasks where id=?", (task_id,))
        if row is not None and row["source_kind"] in ledger.ODIES_TASKS:
            out.add(task_id)
    return out


def owners_tasks(store, now: datetime, owner: str) -> list:
    """The open tasks on this owner's Pulse: everyday Odie's (no personality) for Odie; a personality's own alone for
    it ("Pay rent", set in Mira's chat -> on Mira's Pulse only; "Call the plumber", everyday -> on Odie's only)."""
    if owner == ODIE:
        return store.open_tasks(now.isoformat())
    every_one_it_sees = store.open_tasks(now.isoformat(), owner)
    return [t for t in every_one_it_sees if t["personality"] == owner]


def hidden(item: dict, now: datetime) -> bool:
    """Whether a watch item is put off (Later) at this moment: its "hidden_until" is still ahead. Hidden until 09:00
    tomorrow, asked at 12:00 today -> True; asked at 09:00 tomorrow -> False; never put off -> False; a time that
    can't be read -> False (shown, rather than lost)."""
    until = item.get("hidden_until")
    if not until:
        return False
    try:
        back_at = datetime.fromisoformat(until)
    except ValueError:
        return False
    if back_at.tzinfo is None:
        back_at = back_at.replace(tzinfo=now.tzinfo)
    return now < back_at


def later_until(now: datetime) -> str:
    """When a card put off with Later comes back: 09:00 the next day, on the user's clock. 23 Oct 23:50 ->
    "2026-10-24T09:00:00+05:30"; 31 Oct 08:00 -> "2026-11-01T09:00:00+05:30" (always the next day, as asked)."""
    tomorrow = now.date() + timedelta(days=1)
    return datetime.combine(tomorrow, LATER_AT, now.tzinfo).isoformat(timespec="seconds")


def later(store, ref: str, now: datetime, owner: str = ODIE) -> str | None:
    """Puts a card off until later_until(now) and says until when, or None when there is no such card. A loop
    ("loop:3") is hidden till then (its third Later: till Sunday, odie.loops.cards.later); Sunday's batch goes to next
    Sunday; a task ("task:12") is snoozed as the old Tomorrow button did, so it also rings then."""
    from odie.loops import cards as loop_cards
    until = later_until(now)
    if ref == loop_cards.BATCH:
        return loop_cards.later_batch(store, owner, now)
    if ref.startswith("loop:"):
        loop_id = ref[len("loop:"):]
        if not loop_id.isdigit():
            return None
        return loop_cards.later(store, int(loop_id), until, owner, now)
    if ref.startswith("task:"):
        task_id = ref[len("task:"):]
        if not task_id.isdigit():
            return None
        mine, values = bills.whose_tasks(owner)  # only a task on this owner's Pulse: never another one's
        if store.one(f"select id from tasks where id=? and {mine}", (int(task_id), *values)) is None:
            return None
        store.snooze_task(int(task_id), until)
        return until
    return None


def counts(cards: list[dict]) -> dict[str, int]:
    """How many cards sit in each pile, every pile listed (in report.PILES order) even when it has none. One alerts
    card, one bills card and one personal card -> {"alerts": 1, "bills": 1, "events": 0, "personal": 1, "orders": 0};
    no cards -> every pile 0."""
    out = {pile: 0 for pile in report.PILES}
    for card in cards:
        out[card["pile"]] += 1
    return out


def shows_as_task(task, loops_reminders: set[int]) -> bool:
    """Whether an open task gets its own card: the user's own always do; a reminder Odie made that a loop points at,
    or one of the watch's threads of old, never (its loop is the card). "Pay rent" (his) -> True; the vote's reminder Odie made for
    its loop -> False; the watch's old "Gas bill" thread -> False."""
    if task["id"] in loops_reminders:
        return False
    return task["source_kind"] != threads.SOURCE_KIND


def later_button(ref: str) -> dict:
    """Every card's Later button: puts the card with this ref off until 09:00 the next morning."""
    return {"label": "Later", "action": "later", "value": ref}


def task_card(task, now: datetime) -> dict:
    """One of the user's open tasks as a card: "Tell me more" (a reply owed from mail, "Reply to Priya Nair: Can we
    move our 1:1?", gets "Open it": chat opens that email), then Done and Later."""
    tid = task["id"]
    ref = f"task:{tid}"
    detail = (task["detail"] or "").strip().splitlines()
    why = ""  # a plain reminder says it all in its title
    if detail:
        why = detail[-1]
    ask = f"Tell me about task #{tid}: {task['title']}"
    main = {"label": TELL_ME_MORE, "action": "chat", "value": ask}
    mail = MAIL_TITLE.match(task["title"] or "") if task["source_kind"] == "mail" else None
    if mail:
        sender, subject = mail.groups()
        main = {"label": "Open it", "action": "chat", "value": f"Open the email from {sender} about {subject}"}
    done = {"label": "Done", "action": "done_task", "value": tid}
    decide = main["label"] == TELL_ME_MORE  # only "Tell me more": Odie has no move, the choice is the user's
    icon = task_icon(task)
    return {"ref": ref, "title": task["title"], "why": why, "icon": icon,
            "badge": due_badge(task["due_at"], now), "ask": ask, "main": main, "other": done, "later": later_button(ref),
            "pile": pile_of_task(icon), "since": local_since(task["created_at"], now), "decide": decide}


def pile_of_task(icon: str) -> str:
    """The pile a task's card goes in, from its icon: "rupee" -> "bills", "ticket" -> "orders", "mail" or "bell" ->
    "alerts"."""
    return PILE_OF_ICON.get(icon, "alerts")


def local_since(created_at: str | None, now: datetime) -> str:
    """When a task was created, on the user's clock: "2026-10-21T03:30:00.000Z" with now in IST ->
    "2026-10-21T09:00:00+05:30"; no time, or one that can't be read ("yesterday") -> ""."""
    if not created_at:
        return ""
    try:
        created = datetime.fromisoformat(created_at)
    except ValueError:
        return ""
    if created.tzinfo is None:
        created = created.replace(tzinfo=now.tzinfo)
    return created.astimezone(now.tzinfo).isoformat(timespec="seconds")


def task_icon(task) -> str:
    """A task's icon: a due from the ledger or a bill -> "rupee"; an order -> "ticket"; a reply from mail -> "mail";
    anything else -> "bell"."""
    title = task["title"] or ""
    if title.lower().startswith("order"):
        return "ticket"
    if task["source_kind"] == "ledger" or bills.is_bill_or_order(title):
        return "rupee"
    if task["source_kind"] == "mail":
        return "mail"
    return "bell"


def due_badge(due_at: str | None, now: datetime) -> str:
    """A task's pill: past its day -> "Overdue"; else its day ("2026-10-30T09:00" -> "30 Oct, 09:00"); no date -> ""."""
    if not due_at:
        return ""
    if due_at[:10] < now.strftime("%Y-%m-%d"):
        return "Overdue"
    return card_text.day(due_at)


def recent_notes(store, now: datetime, owner: str = ODIE) -> list[dict]:
    """What the watch did for a Watch for entry and said was worth telling, in the last NOTES_HOURS, newest first, for
    Today's "done while you were away": "Added a heads-up for the recital" (told, an hour ago) -> listed with any files;
    "HN: still no reply" (not told), or a told note from two days ago -> left out."""
    card = store.get_setting(key(report.CARD, owner)) or {}
    since = now - timedelta(hours=NOTES_HOURS)
    out = []
    for note in card.get("done", []):
        if not note.get("told"):
            continue
        try:
            at = datetime.fromisoformat(note["at"])
        except (KeyError, ValueError):
            continue
        if at.tzinfo is None:
            at = at.replace(tzinfo=now.tzinfo)
        if at < since:
            continue
        out.append({"at": note["at"], "message": note.get("message", ""), "media": note.get("media", [])})
    out.reverse()
    return out

