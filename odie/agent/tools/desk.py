"""Chat acting on the Desk's cards (odie.watch.cards): a card's button sends a chat request that names the item
("Show the draft for desk item mail:<id>", "Close desk item mail:<id>: not interested"), and these two tools find it.
desk_item shows the item with its drafted reply; desk_close takes it off the card and closes the watch's thread for it.
Sending a draft is never done here: chat sends it with the mail app's own tools, after the user's approval card."""
from __future__ import annotations

from google.adk.tools import FunctionTool

from odie.agent.callbacks import wrap_untrusted
from odie.store.db import Store
from odie.watch.cards import money

NOT_ON_DESK = "That isn't on the Desk any more (it may have been closed)."


def item_text(item: dict) -> str:
    """One Desk item as chat reads it: its ref, then everything the watch wrote from the mail (title, labels, why,
    sender, the drafted reply) fenced as other people's words, because the watch wrote it from mail."""
    from_mail = [f"title: {item.get('title', '')}"]
    for key in ("pile", "due"):
        if item.get(key):
            from_mail.append(f"{key}: {item[key]}")
    if item.get("amount"):
        from_mail.append(f"amount: {money(item['amount'])}")
    for key in ("suggestion", "escape"):
        if item.get(key):
            from_mail.append(f"{key}: {item[key]['label']}")
    from_mail.append(f"why: {item.get('why', '')}")
    if item.get("from") or item.get("subject"):
        from_mail.append(f"mail: from {item.get('from', '')}, subject {item.get('subject', '')}")
    draft = item.get("draft")
    if draft:
        from_mail.append(f"drafted reply, to {draft.get('to', '')}, subject {draft.get('subject', '')}:\n{draft['body']}")
    return f"Desk item {item['ref']}\n" + wrap_untrusted("\n".join(from_mail))


def make_desk_tools(store: Store) -> list[FunctionTool]:
    from odie.watch import report, threads

    def open_items() -> list[dict]:
        card = store.get_setting(report.CARD) or {}
        return [i for i in card.get("needs_you", []) if not i.get("done")]

    def desk_item(ref: str) -> str:
        """A Desk card's item by its ref ("mail:<id>"): what it is, its suggestion and escape, and its drafted reply
        when it has one. Use it when the user taps a card or asks about a desk item. To send a draft, show it, then
        use the mail app's draft and send tools: the user approves the send."""
        if ref.startswith("task:"):
            return f"{ref} is one of the user's reminders: use task_list and task_update for it."
        item = next((i for i in open_items() if i.get("ref") == ref), None)
        if item is None:
            return NOT_ON_DESK
        return item_text(item)

    def desk_close(ref: str, why: str) -> str:
        """Takes a Desk item off (the user handled it, or doesn't want it) and closes the watch's thread for it.
        why: in the user's words ("not interested", "replied from my phone")."""
        reason = (why or "").strip()
        if not reason:
            return "Say why it's closed, in the user's words."
        card = store.get_setting(report.CARD) or {}
        items = card.get("needs_you", [])
        kept = [i for i in items if i.get("ref") != ref]
        if len(kept) == len(items):
            return NOT_ON_DESK
        card["needs_you"] = kept
        store.set_setting(report.CARD, card)
        threads.close(store, ref, reason, by_user=True)
        return f"Closed {ref}: {reason}."

    return [FunctionTool(desk_item), FunctionTool(desk_close)]
