"""What the user sent closes what it answers (18 Nov 2026). Every check reads the user's own sent mail since the last
check (fetch.Fetcher.sent_mail). Closing it takes two steps:
  1. here, in code, before the model runs: a sent mail in the same mail thread as an open reply closes it, with the
     reason in the user's words ("you replied 18 Nov 14:20"): the watch's thread for it, and its card item;
  2. what closed nothing goes to the check as "What you sent" (the watch's what_you_sent tool), with the skill's rule:
     close an item when what the user sent answers it (to the same person, about the same thing).
A bill or an order is never closed by a reply in its thread (a question about a bill doesn't pay it): only the model
closes those, from the mail. What closes shows in Done today (the watch's closed list and its notes), never silently
gone."""
from __future__ import annotations

from datetime import datetime

from odie.watch import report, threads
from odie.watch.fetch import Mail, when_of

STAYS_OPEN = frozenset({"bill", "bills", "order", "orders"})  # thread kinds and card piles a reply doesn't close


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


def close_answered(store, now: datetime, sent: list[Mail], owner: str = "") -> list[Mail]:
    """Closes every open item whose mail thread the user wrote in (step 1 above) and returns the sent mails that
    closed nothing, for the check's "What you sent". The newest of the user's mails in a thread gives the reason.
      a reply owed to A Person in thread t1, the user's mail in t1 at 14:20 -> the thread closed ("you replied
        18 Nov 14:20"), its card item gone, the close listed in Done today; nothing returned for it
      a card item in thread t2 with no thread followed -> taken off, with a told note "Reply to Sam: you replied …"
      a bill in thread t5, the user's mail in t5 -> stays open; that mail is returned for the model to judge
    owner: whose watch it is (odie.watch.owner); only its own threads and card change."""
    from odie.watch.owner import key
    newest_in: dict[str, Mail] = {}
    for mail in sorted(sent, key=lambda m: when_of(m.at)):
        if mail.thread:
            newest_in[mail.thread] = mail  # the latest one wins
    closed_threads: set[str] = set()
    for followed in threads.open_threads(store, now, owner):
        mail = newest_in.get(followed["thread"])
        if mail is None or not closes_by_its_thread(followed["kind"]):
            continue
        threads.close(store, followed["ref"], replied_words(mail, now), owner=owner)
        closed_threads.add(mail.thread)
    card = store.get_setting(key(report.CARD, owner)) or {}
    for item in list(card.get("needs_you", [])):
        mail = newest_in.get(item.get("thread", ""))
        if mail is None or not closes_by_its_thread(item.get("pile", "")):
            continue
        report.drop_item(store, item["ref"], owner)
        title = item.get("title") or "An item"
        report.keep_done(store, now, f"{title}: {replied_words(mail, now)}", told=True, owner=owner)
        closed_threads.add(mail.thread)
    return [m for m in sent if m.thread not in closed_threads]
