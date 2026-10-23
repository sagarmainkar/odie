"""Today's "Needs you" (23 Oct 2026): one list of cards, refreshed by every watch check. First the watch's items (what
it found in mail that needs the user, in the order it ranked them), then the user's own open reminders, dues and
to-dos, soonest due first. Each card has two buttons; what a button does is decided here, the app only carries it out:
  "chat": send the value as the user's chat request ("Show the draft for desk item mail:r1");
  "dismiss": take a watch item off and stop following it (POST /api/watch/done with the ref);
  "done_task" / "snooze_task": tick a task off, or move it to tomorrow 09:00."""
from __future__ import annotations

import re
from datetime import datetime

from odie.watch import bills, report, threads
from odie.watch import cards as card_text

MAIL_TITLE = re.compile(r"^Reply to (.+?): (.*)$")  # the title an inbox add-on gives its "reply to" tasks


def cards(store, now: datetime) -> list[dict]:
    """Everything that needs the user, as cards: the watch's open items, then their own open tasks (the watch's
    threads only when the card doesn't show them and they have a date that fires: a bill, a deadline)."""
    card = store.get_setting(report.CARD) or {}
    watch_items = [i for i in card.get("needs_you", []) if not i.get("done")]
    shown = {i["ref"] for i in watch_items}
    out = [watch_card(i) for i in watch_items]
    tasks = [t for t in store.open_tasks(now.isoformat()) if shows_as_task(t, shown)]
    tasks.sort(key=lambda t: t["due_at"] or "9999")
    out += [task_card(t, now) for t in tasks]
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


def watch_card(item: dict) -> dict:
    """One of the watch's items as a card: its suggestion as the main button (else "Tell me more"), its way out as the
    other (else "Dismiss"); both close nothing in chat, a way out takes the item off directly."""
    ref = item["ref"]
    suggestion = item.get("suggestion") or {}
    main = {"label": "Tell me more", "action": "chat", "value": card_text.ask_about(item)}
    if suggestion.get("label") and suggestion.get("run"):
        main = {"label": suggestion["label"], "action": "chat", "value": suggestion["run"]}
    escape = item.get("escape") or {}
    other = {"label": escape.get("label") or "Dismiss", "action": "dismiss", "value": ref}
    return {"ref": ref, "title": item.get("title") or "Needs you", "why": item.get("why", ""),
            "icon": card_text.PILE_ICON.get(item.get("pile", ""), card_text.DEFAULT_ICON),
            "badge": card_text.when_or_amount(item), "ask": card_text.ask_about(item), "main": main, "other": other}


def task_card(task, now: datetime) -> dict:
    """One of the user's open tasks as a card, with Done and Tomorrow; a reply owed from mail ("Reply to Priya Nair:
    Can we move our 1:1?") gets "Open it" (chat opens that email) and Done instead."""
    tid = task["id"]
    detail = (task["detail"] or "").strip().splitlines()
    why = ""  # a plain reminder says it all in its title
    if detail:
        why = detail[-1]
    main = {"label": "Done", "action": "done_task", "value": tid}
    other = {"label": "Tomorrow", "action": "snooze_task", "value": tid}
    mail = MAIL_TITLE.match(task["title"] or "") if task["source_kind"] == "mail" else None
    if mail:
        sender, subject = mail.groups()
        other = main
        main = {"label": "Open it", "action": "chat", "value": f"Open the email from {sender} about {subject}"}
    return {"ref": f"task:{tid}", "title": task["title"], "why": why, "icon": task_icon(task),
            "badge": due_badge(task["due_at"], now), "ask": f"Tell me about task #{tid}: {task['title']}",
            "main": main, "other": other}


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
