"""Bills, payments and orders, as the watch keeps them (the owner's ask, 21 Oct 2026): a bill goes on the calendar with
a reminder; a payment confirmation for the same biller and amount closes the reminder and marks the event paid; an
order gets an event on its delivery day that follows its status. The calendar event's title carries the done mark
("✓ Paid · …", "✓ Delivered · …", "✗ Cancelled · …"), which Up next shows as done. The watch may close a reminder only
through close(), which says why in the reminder's notes, so Today can show it and the user can reopen it."""
from __future__ import annotations

import re
from datetime import UTC, datetime

CATCH_UP = "2026-10-21b"  # the catch-up's version: a check runs it once while the watch state holds another one
# ("b": again, now that the check can write to the calendar app; the first ran without its tools)
CATCH_UP_DAYS = 30
CATCH_UP_MOST = 25  # the most catch-up mails one check reads (its turn has the usual 280 s)
CATCH_UP_TRIES = 2  # a catch-up whose turn fails this many times is given up: new mail only from then on
# A Gmail-style search for the same words LOOKS_LIKE knows (the subject filter below still decides)
CATCH_UP_QUERY = ("subject:(bill OR statement OR invoice OR payment OR paid OR receipt OR due OR order OR shipped OR "
                  "dispatched OR delivered OR delivery OR refund OR cancelled)")
LOOKS_LIKE = re.compile(r"\b(bills?|statements?|invoices?|payments?|paid|receipts?|due|orders?|ordered|shipped|dispatched|"
                        r"delivered|delivery|deliveries|refunds?|cancelled|canceled|emi|recharge)\b", re.I)
AMOUNT = re.compile(r"(₹|\brs\.?\s?|\binr\b)\s?[\d,]+", re.I)
CLOSED_NOTE = "Closed by the watch: "
DONE_MARKS = (("✓ Paid · ", "paid"), ("✓ Delivered · ", "delivered"), ("✗ Cancelled · ", "cancelled"))


def looks_like_bill_or_order(subject: str) -> bool:
    """Whether a mail's subject looks like a bill, a statement, a payment, or an order and its delivery: the mail the
    catch-up reads. "Your electricity bill of Rs 4,280 is due" -> True; "Your order has shipped" -> True; "Payment
    received" -> True; "Lunch tomorrow?" -> False; "Diwali sale: 50% off" -> False."""
    return bool(LOOKS_LIKE.search(subject or ""))


def done_state(title: str) -> tuple[str | None, str]:
    """An event title's done mark and the title without it: "✓ Paid · Pay bill - Rs 4,280" -> ("paid", "Pay bill -
    Rs 4,280"); "✗ Cancelled · Order: Earbuds" -> ("cancelled", "Order: Earbuds"); "Pay bill" -> (None, "Pay bill")."""
    for mark, state in DONE_MARKS:
        if title.startswith(mark):
            return state, title[len(mark):]
    return None, title


def is_bill_or_order(title: str) -> bool:
    """Whether an open reminder (or an event) is a bill to pay or an order to receive, for matching a payment or an
    order update to it: words like those of a bill or an order, or an amount. "Pay electricity bill - Rs 4,280" ->
    True; "Order: Wireless Earbuds" -> True; "Buy medicine" -> False."""
    return looks_like_bill_or_order(title) or bool(AMOUNT.search(title or ""))


def open_bills_and_orders(store) -> list[dict]:
    """The open reminders that are bills or orders: id, title, due; the dated ones first, soonest due first."""
    rows = store.query("select id, title, due_at from tasks where status in ('open', 'waiting') "
                       "order by due_at is null, due_at, created_at")
    return [{"id": r["id"], "title": r["title"], "due": r["due_at"]} for r in rows if is_bill_or_order(r["title"])]


def close(store, task_id: int, why: str) -> str:
    """Closes an open reminder because a mail showed it's done, and keeps why in its notes. The only way the watch
    changes a task. (#27, "paid: confirmation mail 21 Oct") -> "Closed reminder #27."; a closed one, an unknown one or
    no reason -> says so and changes nothing."""
    reason = (why or "").strip()
    if not reason:
        return "Say why it's done (which mail showed it)."
    row = store.one("select id, status from tasks where id=?", (int(task_id),))
    if row is None:
        return f"No reminder #{task_id}."
    if row["status"] not in ("open", "waiting"):
        return f"Reminder #{task_id} is already closed."
    store.update_task(int(task_id), status="done", notes=CLOSED_NOTE + reason)
    return f"Closed reminder #{task_id}."


def closed_by_watch(store, since: datetime) -> list[dict]:
    """Reminders the watch closed since then, newest first: id, title, why, closed (when)."""
    since_utc = since.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")
    rows = store.query("select id, title, notes, completed_at from tasks where status = 'done' and notes like ? "
                       "and completed_at >= ? order by completed_at desc", (CLOSED_NOTE + "%", since_utc))
    return [{"id": r["id"], "title": r["title"], "why": r["notes"][len(CLOSED_NOTE):], "closed": r["completed_at"]}
            for r in rows]


def reopen(store, task_id: int) -> None:
    """The user says the watch was wrong: the reminder is open again and the watch's note goes."""
    store.update_task(int(task_id), status="open", notes=None, completed_at=None)
