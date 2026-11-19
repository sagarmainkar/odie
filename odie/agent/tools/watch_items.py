"""Chat acting on a loop's card on Pulse (odie.loops.cards): a card's button sends a chat request that names the loop
("Show the draft for loop #3", "Tell me about loop #3: …"), and these two tools find it. watch_item shows the loop
with its drafted reply and its evidence; watch_close is the user's Done on it, said in chat (remembered like any Done).
Sending a draft is never done here: chat sends it with the mail app's own tools, after the user's approval card.
A personality's chat sees only its own loops."""
from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

from google.adk.tools import FunctionTool, ToolContext

from odie.agent.callbacks import wrap_untrusted
from odie.store.db import Store
from odie.watch.cards import money

NOT_ON_TODAY = "That isn't on Pulse any more (it may have been closed)."
LOOP_NUMBER = re.compile(r"^(?:loop:|#)?(\d+)$")
EVIDENCE_SHOWN = 8


def item_text(loop: dict, evidence: list[dict]) -> str:
    """One loop as chat reads it: its number and where its mail is, then everything the watch wrote from mail (title,
    labels, why, sender, the drafted reply, the evidence) fenced as other people's words."""
    card = loop["card"]
    from_mail = [f"title: {loop['title']}", f"kind: {loop['kind']}", f"whose move: {loop['owner']}",
                 f"state: {loop['state']}"]
    if loop.get("due_at"):
        from_mail.append(f"due: {loop['due_at']}")
    if card.get("pile"):
        from_mail.append(f"pile: {card['pile']}")
    if card.get("amount"):
        from_mail.append(f"amount: {money(card['amount'])}")
    if card.get("suggestion"):
        from_mail.append(f"suggestion: {card['suggestion']}")
    from_mail.append(f"why: {loop['result']}")
    if card.get("from") or card.get("subject"):
        from_mail.append(f"mail: from {card.get('from', '')}, subject {card.get('subject', '')}")
    draft = card.get("draft")
    if draft:
        from_mail.append(f"drafted reply, to {draft.get('to', '')}, subject {draft.get('subject', '')}:\n{draft['body']}")
    said = [f"- {e['at'][:16]} {e['source']}: {e['fact']}" for e in evidence[-EVIDENCE_SHOWN:]]
    if said:
        from_mail.append("evidence:\n" + "\n".join(said))
    where = ""
    mail_refs = [r for r in loop["refs"] if r.startswith("mail:")]
    if card.get("app") and mail_refs:
        where = f" (in {card['app']}, id {mail_refs[0][len('mail:'):]}: open it there)"
    return f"Loop #{loop['id']}{where}\n" + wrap_untrusted("\n".join(from_mail))


def make_watch_item_tools(store: Store) -> list[FunctionTool]:
    from odie import config
    from odie.agent.tools.local import personality_of
    from odie.loops import ledger

    def find(ref: str, pid: str) -> dict | None:
        """The loop a card names: "loop:3", "#3" or "3"; or the open loop holding a mail or event ("mail:m1"). Only
        this chat's personality's own."""
        text = (ref or "").strip()
        number = LOOP_NUMBER.match(text)
        loop = None
        if number:
            loop = ledger.get(store, int(number.group(1)))
        elif text:
            loop = ledger.find_by_refs(store, pid, [text])
        if loop is None or loop["personality"] != pid:
            return None
        return loop

    def watch_item(ref: str, tool_context: ToolContext | None = None) -> str:
        """A card on Pulse by its loop ("loop:3", from "Tell me about loop #3" or "Show the draft for loop #3"): what
        it is, its suggested move, its drafted reply when it has one, and why (its evidence). Use it when the user taps
        a card or asks about one. To send a draft, show it, then use the mail app's draft and send tools: the user
        approves the send."""
        if ref.startswith("task:"):
            return f"{ref} is one of the user's reminders: use task_list and task_update for it."
        loop = find(ref, personality_of(store, tool_context))
        if loop is None:
            return NOT_ON_TODAY
        now = datetime.now(ZoneInfo(config.settings.timezone))
        ledger.update(store, loop["id"], now, tapped="ask")
        return item_text(loop, ledger.events(store, loop["id"]))

    def watch_close(ref: str, why: str, tool_context: ToolContext | None = None) -> str:
        """The user's Done on a card, said in chat (they handled it, or don't want it): Odie stops following it and
        remembers it's finished. why: in the user's words ("not interested", "replied from my phone"). Never a pull
        request's card (he taps Done on it), never from a background check or the terminal."""
        from odie.loops import chat_done
        reason = (why or "").strip()
        if not reason:
            return "Say why it's closed, in the user's words."
        loop = find(ref, personality_of(store, tool_context))
        if loop is None or loop["state"] not in ledger.OPEN:
            return NOT_ON_TODAY
        verdict, words = chat_done.decide(store, loop, tool_context)
        if verdict == chat_done.REFUSE:
            return words
        now = datetime.now(ZoneInfo(config.settings.timezone))
        chat_done.close(store, loop, now, reason)
        return f"Closed loop #{loop['id']}: {reason}."

    def close_needs_tap(ref: str = "", why: str = "", tool_context=None, **_) -> bool:
        """Does closing this card in chat need his tap? Yes when the chat has read outside text (mail, web pages, a
        job's report: odie.loops.chat_done.decide says TAP). "close the venue card" in a clean chat -> no card;
        the same after the chat read a mail -> the approval card. A refused close needs no tap (it doesn't run)."""
        from odie.loops import chat_done
        loop = find(ref, personality_of(store, tool_context))
        if loop is None or loop["state"] not in ledger.OPEN:
            return False
        verdict, _words = chat_done.decide(store, loop, tool_context)
        return verdict == chat_done.TAP

    return [FunctionTool(watch_item), FunctionTool(watch_close, require_confirmation=close_needs_tap)]
