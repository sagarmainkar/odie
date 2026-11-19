"""What the user sent closes what it answers (18 Nov 2026). Every check reads the user's own sent mail since the last
check (fetch.Fetcher.sent_mail). Closing it takes two steps:
  1. here, in code, before the model runs: a sent mail in the same mail thread as an open loop's mail, to its sender,
     closes that loop, with the reason in the user's words ("you replied 18 Nov 14:20");
  2. what closed nothing goes to the check as "What you sent" (the watch's what_you_sent tool): the model writes a
     finding for what answers someone, and stage 2 closes the loop it answers (odie.loops.consolidate).
A bill or an order is never closed by a reply in its thread (a question about a bill doesn't pay it): only the model
closes those, from the mail. What closes shows in Done today (loops Odie closed today, each with Reopen), never
silently gone."""
from __future__ import annotations

from datetime import datetime

from odie.watch.fetch import Mail, when_of

STAYS_OPEN = frozenset({"bill", "bills", "order", "orders"})  # thread kinds and card piles a reply doesn't close


def answers(mail: Mail, sender: str) -> bool:
    """Whether the user's mail in an item's thread went to the person the item is about: a reply, not a forward or a
    note to someone else. To "Asha <ASHA@example.com>, Priya <…>" for sender asha@example.com -> True; a forward to
    Priya only -> False; an item with no sender kept (made before this was noted) -> False: the model judges it from
    "What you sent" instead."""
    wanted = (sender or "").strip().lower()
    if not wanted:
        return False
    return wanted in (mail.to or "").lower()


def newest_reply(mails: list[Mail], sender: str) -> Mail | None:
    """Of the user's mails in one thread (oldest first), the newest that answers the sender (answers), or None. A reply
    to Asha at 14:20 then a forward to Priya at 14:30 -> the 14:20 reply; only the forward -> None."""
    replies = [m for m in mails if answers(m, sender)]
    if not replies:
        return None
    return replies[-1]


def closes_by_its_thread(kind_or_pile: str) -> bool:
    """Whether the user's own mail in an item's thread closes it in code, by the thread's kind or the card item's pile.
    A reply owed ("reply"), an alert, a personal item, a deadline or an item with no pile ("") -> True; a bill or an
    order ("bill", "bills", "order", "orders") -> False: replying about a bill doesn't pay it."""
    return kind_or_pile not in STAYS_OPEN


def replied_words(mail: Mail, now: datetime) -> str:
    """Why an item closed, in the user's words, on their clock: sent 08:50 UTC on 18 Nov, the user in India ->
    "you replied 18 Nov 14:20"; a time that can't be read -> "you replied"."""
    sent_at = when_of(mail.at)
    if sent_at.year < 2000:  # when_of's "earliest time": the app's date couldn't be read
        return "you replied"
    local = sent_at.astimezone(now.tzinfo)
    return f"you replied {local.day} {local.strftime('%b %H:%M')}"


def thread_and_sender(loop: dict) -> tuple[str, str]:
    """The mail thread a loop's card came from and that mail's sender (kept on its card: odie.loops.findings), or
    ("", "") for a loop from no mail. A loop with no thread on its card but a "thread:t1" ref -> ("t1", its sender)."""
    card = loop.get("card") or {}
    thread = str(card.get("thread") or "")
    if not thread:
        held = [r for r in loop["refs"] if r.startswith("thread:")]
        if held:
            thread = held[0][len("thread:"):]
    return thread, str(card.get("sender") or "")


def kind_or_pile(loop: dict) -> str:
    """What decides whether a reply closes a loop: its card's pile when it has one ("bills"), else its kind in the
    model's words, read for a bill or an order: "electricity bill", "invoice" -> "bill"; "order delivery" -> "order";
    "reply owed" -> "reply owed"."""
    pile = str((loop.get("card") or {}).get("pile") or "")
    if pile:
        return pile
    kind = (loop["kind"] or "").strip().lower()
    if any(word in kind for word in ("bill", "invoice", "payment")):
        return "bill"
    if any(word in kind for word in ("order", "delivery", "shipment")):
        return "order"
    return kind


def close_answered(store, now: datetime, sent: list[Mail], owner: str = "") -> list[Mail]:
    """Closes every open loop whose mail thread the user wrote in, to that mail's sender (step 1 above), and returns
    the sent mails that closed nothing, for the check's "What you sent". The newest of the user's mails in a thread
    gives the reason.
      a reply owed to A Person in thread t1, the user's mail in t1 at 14:20 -> closed ("you replied 18 Nov 14:20"),
        listed in Done today; nothing returned for it
      a forward in t1 to someone else -> stays open; the mail is returned for the model to judge
      a bill in thread t5, the user's mail in t5 -> stays open; that mail is returned for the model to judge
    owner: whose watch it is (odie.watch.owner); only its own loops change."""
    from odie.loops import ledger
    in_thread: dict[str, list[Mail]] = {}
    for mail in sorted(sent, key=lambda m: when_of(m.at)):
        if mail.thread:
            in_thread.setdefault(mail.thread, []).append(mail)  # oldest first
    closed_threads: set[str] = set()
    for loop in ledger.open_loops(store, owner):
        if loop["playbook"]:
            continue  # a pull request closes by GitHub's facts, never by a mail
        thread, sender = thread_and_sender(loop)
        mail = newest_reply(in_thread.get(thread, []), sender)
        if mail is None or not closes_by_its_thread(kind_or_pile(loop)):
            continue
        ledger.attach(store, loop["id"], now, "sent", f"mail:{mail.id}", f"You wrote: {mail.subject[:120]}", news=False)
        ledger.close(store, loop["id"], now, "odie", replied_words(mail, now))
        closed_threads.add(mail.thread)
    return [m for m in sent if m.thread not in closed_threads]
