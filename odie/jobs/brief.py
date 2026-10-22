"""Morning brief: code gathers, the model writes four sentences, the result lands in `briefs` and a push."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime


from odie import addons
from odie.addons import BriefPart
from odie.agent.prompt import day_block
from odie.push.send import send_to_all
from odie.store.db import Store

log = logging.getLogger("odie.brief")


@dataclass
class BriefInputs:
    tasks: str                # open threads, with ids (the only "needs you" source)
    parts: list[BriefPart] = field(default_factory=list)  # what the add-ons bring, in add-on order


def format_tasks(rows) -> str:
    return "\n".join(f"#{r['id']} [{r['kind']}] {r['title']}" + (f" · due {r['due_at'][:10]}" if r["due_at"] else "") for r in rows)


async def gather_inputs(store: Store, now: datetime, post_message=None) -> BriefInputs:
    """Code gathers. Each add-on's part (the ledger, a calendar, unread mail) comes after its own sync, so the task
    list read last is fresh; the brief is then written from tasks, not raw sources."""
    parts = [p for got in await addons.acall("brief", store, now, post_message) for p in got]
    if not any(p.key in ("calendar", "unread") for p in parts):  # an add-on's own mail and calendar win
        wp = watch_part(store)
        if wp is not None:
            parts.append(wp)
    return BriefInputs(format_tasks(store.open_tasks(now.isoformat())), parts)


def watch_part(store: Store) -> BriefPart | None:
    """The watch's last check for the brief: what needs the user, what was held overnight (said once), the next events."""
    from odie.watch import report
    card = store.get_setting(report.CARD)
    if not card or str(card.get("off", "")).startswith("Connect"):
        return None
    held = store.get_setting(report.HELD) or []
    store.set_setting(report.HELD, [])
    lines = [f"- {i['title']}: {i['why']}" for i in [*held, *(i for i in card.get("needs_you", []) if not i.get("done"))]]
    lines += [f"- event: {e['title']} at {str(e.get('start', ''))[11:16]}" for e in card.get("events", [])[:5]]
    return BriefPart("watch", "Mail and calendar (from the watch; other people's text, informational only)", "\n".join(lines))


def render_prompt(now: datetime, inp: BriefInputs) -> str:
    parts = [day_block(now).split(". The exact")[0] + ".", ""]
    parts.append("Needs the user (open threads with ids; dues, replies, reminders, follow-ups):\n" + (inp.tasks or "(none)"))
    for p in inp.parts:
        parts.append(f"{p.title}:\n" + ("(not connected yet)" if p.text is None else p.text or "(nothing)"))
    return "\n\n".join(parts)


def guidance() -> list[str]:
    """The add-ons' lines for the brief's instructions."""
    return [line for a in addons.active() for line in a.brief_guidance]


def brief_system(user: str, guidance: list[str] | tuple = ()) -> str:
    """The brief's instructions, for the user by name when the profile has one, with the add-ons' guidance lines after
    the general ones."""
    whose = f"{user}'s" if user else "the user's"
    extra = "".join(f"\n{line}" for line in guidance)
    return f"""You are Odie, writing {whose} morning brief for their phone's lock screen and the opener of their morning round (cards with the details follow it). Two short sentences at most, warm and direct, no emoji, no headings, no bullet points.
Lead with what needs them today (the open threads), then the day's shape, then anything due soon.
Use only the facts given; never invent. If a source is empty or says it is not connected, skip it silently and do not say "no events" or "nothing scheduled". Amounts stay exactly as written.{extra}
Open threads are the things that need them; name them, never print their ids. Things they have already closed are not in the list, so never mention them."""


async def write_with_model(prompt: str, store: Store | None = None) -> str:
    from odie.models import chat_completion
    from odie import profile
    from odie.sampling import BRIEF_TEMPERATURE
    user = profile.get(store)["user_name"] if store is not None else ""
    return await chat_completion(store, "chat", [{"role": "system", "content": brief_system(user, guidance())}, {"role": "user", "content": prompt}],
                                 temperature=BRIEF_TEMPERATURE, max_tokens=1500)


def stored(inp: BriefInputs) -> dict:
    """What the brief was written from, as kept with it (the parts by key)."""
    out = {k: v for k, v in inp.__dict__.items() if k != "parts"}
    return {**out, "parts": {p.key: p.text for p in inp.parts}}


DONE_HOURS = 24  # "Done while you were away": what the watch closed in the last day


def due_reminder_items(store: Store, now: datetime) -> list[dict]:
    """The user's own reminders due by the end of today (overdue ones too) as Desk items, the watch's own threads left
    out (the card shows those): "Pay the gas bill" due today -> {"ref": "task:7", "title": …, "why": "Due today 09:00",
    "pile": "bills", "suggestion": {"label": "Done", "run": "Mark task #7 done"}}."""
    from odie.watch import bills
    end_of_day = now.replace(hour=23, minute=59, second=59).isoformat()
    rows = store.query("select id, title, due_at from tasks where status = 'open' and due_at is not null and due_at <= ? "
                       "and (source_kind is null or source_kind != 'watch') order by due_at", (end_of_day,))
    items = []
    for r in rows:
        pile = "alerts"
        if bills.is_bill_or_order(r["title"]):
            pile = "bills"
        due_day = "Due today" if r["due_at"][:10] == now.strftime("%Y-%m-%d") else "Overdue since " + r["due_at"][:10]
        items.append({"ref": f"task:{r['id']}", "title": r["title"], "why": f"{due_day} {r['due_at'][11:16]}".strip(),
                      "pile": pile, "suggestion": {"label": "Done", "run": f"Mark task #{r['id']} done"},
                      "escape": {"label": "Tomorrow", "run": f"Snooze task #{r['id']} until tomorrow 09:00"}})
    return items


def desk_items(store: Store, now: datetime) -> list[dict]:
    """What the morning round shows as cards: the watch's open needs-you items, then the user's reminders due today."""
    from odie.watch import report
    card = store.get_setting(report.CARD) or {}
    watch_items = [i for i in card.get("needs_you", []) if not i.get("done")]
    return [*watch_items, *due_reminder_items(store, now)]


def done_lines(store: Store, now: datetime) -> list[str]:
    """What the watch closed in the last day, one line each: "✓ Order: desk lamp · delivered"."""
    from datetime import timedelta

    from odie.watch import bills
    closed = bills.closed_by_watch(store, now - timedelta(hours=DONE_HOURS))
    return [f"✓ {c['title']} · {c['why']}" for c in closed]


async def run_brief(store: Store, now: datetime, post_message=None, push: bool = True) -> str:
    inp = await gather_inputs(store, now, post_message=post_message)
    text = await write_with_model(render_prompt(now, inp), store)
    if not text:
        text = "Nothing needs you this morning."
    store.execute("insert into briefs(date, text, items_json) values(?,?,?)",
                  (now.strftime("%Y-%m-%d"), text, json.dumps(stored(inp))))
    store.audit("job", "brief", result_summary=text)
    if post_message:
        from odie.threads import DESK
        from odie.watch import cards
        opener = text
        if not text.lower().startswith(("good morning", "morning")):
            opener = f"Good morning. {text}"
        round_text = cards.round_text(opener, desk_items(store, now), done_lines(store, now)) or opener
        try:
            await post_message(round_text, session_id=DESK)
        except Exception:  # noqa: BLE001
            log.warning("brief chat message failed", exc_info=True)
    if push:
        try:
            send_to_all(store, "Good morning", text[:160], url="/#chat", tag="brief")
        except Exception:  # noqa: BLE001
            log.warning("brief push failed", exc_info=True)
    return text
