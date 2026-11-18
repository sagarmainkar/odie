"""Today's "Needs you" (23 Oct 2026): one list of cards, refreshed by every watch check. First the watch's items (what
it found in mail that needs the user, in the order it ranked them), then the user's own open reminders, dues and
to-dos, soonest due first. Every card has the same three buttons (18 Nov 2026): its one move ("main": the watch's
label, "Open it" for a reply owed from mail, else "Tell me more"), Done ("other": off the list and no longer followed,
whether it was done or won't be) and Later ("later": hidden until 09:00 the next morning, then back). What a button
does is decided here, the app only carries it out:
  "chat": send the value as the user's chat request ("Show the draft for watch item mail:r1");
  "dismiss": take a watch item off and stop following it (POST /api/watch/done with the ref);
  "done_task" / "snooze_task": tick a task off, or move it to tomorrow 09:00;
  "later": put the card off until 09:00 the next morning (POST /api/needs_you/later with the card's ref).
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
    """Everything that needs the user, as cards: the watch's open items, then their own open tasks (the watch's
    threads only when the card doesn't show them and they have a date that fires: a bill, a deadline). Everyday Odie's
    Pulse (owner "") as it always was; a personality's: its own watch's card and its own tasks, never the everyday
    ones (they are on Odie's)."""
    card = store.get_setting(key(report.CARD, owner)) or {}
    on_the_card = [i for i in card.get("needs_you", []) if not i.get("done")]
    shown = {i["ref"] for i in on_the_card}  # a hidden item's thread stays off the list too
    watch_items = [i for i in on_the_card if not hidden(i, now)]
    from odie.loops import cards as loop_cards
    out = loop_cards.cards(store, owner, now)  # one card per ready loop (a pull request with its facts), first
    out += [watch_card(i) for i in watch_items]
    tasks = [t for t in owners_tasks(store, now, owner) if shows_as_task(t, shown)]
    tasks.sort(key=lambda t: t["due_at"] or "9999")
    out += [task_card(t, now) for t in tasks]
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
    """Puts a card off until later_until(now) and says until when, or None when there is no such card. A task
    ("task:12") is snoozed as the old Tomorrow button did, so it also rings then; a watch item gets a "hidden_until"
    on the card, which the next checks keep (report.apply never rewrites an item it has)."""
    until = later_until(now)
    if ref.startswith("loop:"):
        from odie.loops import cards as loop_cards
        loop_id = ref[len("loop:"):]
        if not loop_id.isdigit() or not loop_cards.later(store, int(loop_id), until, owner, now):
            return None
        return until
    if ref.startswith("task:"):
        task_id = ref[len("task:"):]
        if not task_id.isdigit() or store.one("select id from tasks where id=?", (int(task_id),)) is None:
            return None
        store.snooze_task(int(task_id), until)
        return until
    card_key = key(report.CARD, owner)
    card = store.get_setting(card_key) or {}
    items = card.get("needs_you", [])
    found = next((i for i in items if i.get("ref") == ref), None)
    if found is None:
        return None
    found["hidden_until"] = until
    store.set_setting(card_key, card)
    return until


def counts(cards: list[dict]) -> dict[str, int]:
    """How many cards sit in each pile, every pile listed (in report.PILES order) even when it has none. One alerts
    card, one bills card and one personal card -> {"alerts": 1, "bills": 1, "events": 0, "personal": 1, "orders": 0};
    no cards -> every pile 0."""
    out = {pile: 0 for pile in report.PILES}
    for card in cards:
        out[card["pile"]] += 1
    return out


def shows_as_task(task, on_the_card: set[str]) -> bool:
    """Whether an open task gets its own card. The user's own tasks always do; the watch's threads only when its card
    doesn't already show them and they have a due date (a bill or a deadline). "Pay rent" (the user's) -> True; the
    watch's "Order: desk lamp" in transit (no due date) -> False; its "Reply to Asha" on the card -> False; its "Gas bill"
    due 25 Oct, not on the card -> True."""
    if task["source_kind"] != threads.SOURCE_KIND:
        return True
    if task["source_ref"] in on_the_card:
        return False
    return task["due_at"] is not None


def offers_a_move(item: dict) -> bool:
    """Whether the watch gave an item a move of its own (a labelled suggestion with something to run). A bill with
    "Remind me Thursday" -> True; a declined payment with only an escape ("It was me") -> False."""
    suggestion = item.get("suggestion") or {}
    return bool(suggestion.get("label") and suggestion.get("run"))


def pile_of_item(item: dict) -> str:
    """The pile a watch item belongs to: one of report.PILES as it is; anything else, or none, is "alerts".
    "bills" -> "bills"; "urgent" -> "alerts"; missing -> "alerts"."""
    pile = item.get("pile", "")
    if pile in report.PILES:
        return pile
    return "alerts"


def later_button(ref: str) -> dict:
    """Every card's Later button: puts the card with this ref off until 09:00 the next morning."""
    return {"label": "Later", "action": "later", "value": ref}


def watch_card(item: dict) -> dict:
    """One of the watch's items as a card: its suggestion as the main button (else "Tell me more"), then Done (off the
    list, no longer followed) and Later. An older item's own way out ("Not now") is no longer a button."""
    ref = item["ref"]
    suggestion = item.get("suggestion") or {}
    ask = card_text.ask_about(item)
    main = {"label": TELL_ME_MORE, "action": "chat", "value": ask}
    if offers_a_move(item):
        main = {"label": suggestion["label"], "action": "chat", "value": suggestion["run"]}
    done = {"label": "Done", "action": "dismiss", "value": ref}
    # With no move Odie can make, the choice is the user's: "Tell me more" and Done show as equal buttons.
    decide = not offers_a_move(item)
    return {"ref": ref, "title": item.get("title") or "Needs you", "why": item.get("why", ""),
            "icon": card_text.PILE_ICON.get(item.get("pile", ""), card_text.DEFAULT_ICON),
            "badge": card_text.when_or_amount(item), "ask": ask, "main": main, "other": done,
            "later": later_button(ref), "pile": pile_of_item(item), "since": item.get("at", ""), "decide": decide}


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

