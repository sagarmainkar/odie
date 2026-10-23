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
    return BriefInputs(format_tasks(users_open_tasks(store, now)), parts)


def users_open_tasks(store: Store, now: datetime) -> list:
    """The open tasks the brief lists as needing the user: all but the watch's own threads, which the watch's card
    already shows when they need the user. "Answer Asha" (the user's) -> listed; "Order: desk lamp" the watch follows
    while it ships -> left out (it needs nobody until it is late, and then the card says so)."""
    from odie.watch import threads
    rows = store.open_tasks(now.isoformat())
    return [r for r in rows if r["source_kind"] != threads.SOURCE_KIND]


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
    return f"""You are Odie, writing {whose} morning brief for their phone's lock screen (the cards with the details are on Today). Two short sentences at most, warm and direct, no emoji, no headings, no bullet points.
Lead with what needs them today (the open threads), then the day's shape, then anything due soon.
Use only the facts given; never invent. If a source is empty or says it is not connected, skip it silently and do not say "no events" or "nothing scheduled". Amounts stay exactly as written.{extra}
Open threads are the things that need them; name them, never print their ids. Things they have already closed are not in the list, so never mention them."""


async def write_with_model(prompt: str, store: Store | None = None) -> str:
    from odie import profile
    from odie.models import chat_completion
    from odie.sampling import BRIEF_TEMPERATURE
    user = profile.get(store)["user_name"] if store is not None else ""
    return await chat_completion(store, "chat", [{"role": "system", "content": brief_system(user, guidance())}, {"role": "user", "content": prompt}],
                                 temperature=BRIEF_TEMPERATURE, max_tokens=1500)


def stored(inp: BriefInputs) -> dict:
    """What the brief was written from, as kept with it (the parts by key)."""
    out = {k: v for k, v in inp.__dict__.items() if k != "parts"}
    return {**out, "parts": {p.key: p.text for p in inp.parts}}


async def run_brief(store: Store, now: datetime, post_message=None, push: bool = True) -> str:
    inp = await gather_inputs(store, now, post_message=post_message)
    text = await write_with_model(render_prompt(now, inp), store)
    if not text:
        text = "Nothing needs you this morning."
    store.execute("insert into briefs(date, text, items_json) values(?,?,?)",
                  (now.strftime("%Y-%m-%d"), text, json.dumps(stored(inp))))
    store.audit("job", "brief", result_summary=text)
    if push:
        try:
            send_to_all(store, ping_title(store, now), text[:160], url="/#today", tag="brief")
        except Exception:  # noqa: BLE001
            log.warning("brief push failed", exc_info=True)
    return text


def ping_title(store: Store, now: datetime) -> str:
    """The morning ping's title: how many cards Today's Needs you has. 2 -> "2 things need you"; 1 -> "1 thing needs
    you"; none -> "Good morning"."""
    from odie.watch import needs
    n = len(needs.cards(store, now))
    if n == 0:
        return "Good morning"
    if n == 1:
        return "1 thing needs you"
    return f"{n} things need you"


BRIEF_AT = (7, 30)  # the morning round's time, the user's clock
CATCH_UP_UNTIL = 12  # a round missed while the computer was off still goes out when Odie starts before noon


def missed_today(store: Store, now: datetime) -> bool:
    """Whether Odie, starting now, owes today's morning round: past 07:30, before noon, and none written today. The Mac
    was off at 07:30 and Odie starts at 11:21 -> True; starting at 07:00 (its time hasn't come), at 12:30 (too late for
    a morning round), or when today's already ran -> False."""
    if (now.hour, now.minute) < BRIEF_AT or now.hour >= CATCH_UP_UNTIL:
        return False
    ran = store.one("select 1 from briefs where date = ?", (now.strftime("%Y-%m-%d"),))
    return ran is None

