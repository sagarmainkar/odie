"""Odie speaks first when the user comes back after a while: one message in the chat saying what it did while they
were away, what waits on them and what's next, with a button per offer. Built by code from the store, no model.
The app asks (POST /api/chat/welcome) when it opens or comes back to the screen; nothing is posted when the gap is
short, when there is nothing to say, or when a welcome was posted since the user last wrote."""
from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

from odie.store.db import Store
from odie.workers import store as jobs

log = logging.getLogger("odie.workers")

GAP_HOURS = 3
MAX_LISTED = 4


def _at(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def last_user_message_at(store: Store) -> datetime | None:
    row = store.one("select ts from audit_log where actor='user' and event='message' order by id desc limit 1")
    return _at(row["ts"]) if row else None


def last_welcome_at(store: Store) -> datetime | None:
    row = store.one("select ts from audit_log where event='welcome' order by id desc limit 1")
    return _at(row["ts"]) if row else None


def away_since(store: Store, now: datetime) -> datetime | None:
    """When the user was last here, if that is long enough ago for a welcome: the later of their last message and
    the last welcome, when it is GAP_HOURS or more before now. Never wrote -> None; wrote 20 minutes ago -> None;
    wrote 5 hours ago, no welcome since -> that time; welcomed 10 minutes ago -> None."""
    last = last_user_message_at(store)
    if last is None:
        return None
    welcomed = last_welcome_at(store)
    if welcomed and welcomed > last:
        last = welcomed
    if now - last < timedelta(hours=GAP_HOURS):
        return None
    return last


def gather(store: Store, since: datetime, now: datetime) -> dict:
    """What there is to say: jobs that ended since, cards waiting on the user, today's events still ahead."""
    from odie.watch import needs, report
    ended = [j for j in jobs.recent(store, 20) if j["status"] in ("done", "failed") and _at(j["ended_at"]) and _at(j["ended_at"]) > since]
    done = [j for j in ended if j["status"] == "done" and j["outcome"] != "blocked"]
    stuck = [j for j in ended if j["status"] == "failed" or j["outcome"] == "blocked"]
    cards = needs.cards(store, now)
    card = store.get_setting(report.CARD) or {}
    today = now.date().isoformat()
    events = [e for e in card.get("events", []) if str(e.get("start", "")).startswith(today) and str(e.get("start", ""))[11:16] >= now.strftime("%H:%M")]
    return {"done": done, "stuck": stuck, "cards": cards, "events": events[:3]}


def _why(job: dict) -> str:
    text = job.get("error") or (job.get("report") or "").splitlines()[0] if (job.get("error") or job.get("report")) else ""
    return text[:80]


def compose(found: dict, hours: float) -> str:
    """The message, or "" when there is nothing worth saying. Worked example: 2 done, 1 stuck, 3 cards, 1 event ->
    "Welcome back. While you were away (5 h):\\n✅ Done: Primes script, Mac health check\\n❌ Didn't finish: Portfolio
    pull (needs the API key)\\nWaiting on you (3): Reply to Asha, Electricity bill, Portfolio pull\\nUp next: Dentist
    16:00" and an actions block with Retry and "What needs me?"."""
    done, stuck, cards, events = found["done"], found["stuck"], found["cards"], found["events"]
    if not (done or stuck or cards or events):
        return ""
    lines = [f"Welcome back. While you were away ({hours:g} h):"]
    if done:
        lines.append("✅ Done: " + ", ".join(j["title"] for j in done[:MAX_LISTED]) + (f" and {len(done) - MAX_LISTED} more" if len(done) > MAX_LISTED else ""))
    for j in stuck[:MAX_LISTED]:
        lines.append(f"❌ Didn't finish: {j['title']} ({_why(j)})" if _why(j) else f"❌ Didn't finish: {j['title']}")
    if cards:
        names = ", ".join(c["title"] for c in cards[:MAX_LISTED])
        more = f" and {len(cards) - MAX_LISTED} more" if len(cards) > MAX_LISTED else ""
        lines.append(f"Waiting on you ({len(cards)}): {names}{more}")
    if events:
        lines.append("Up next: " + ", ".join(f"{e['title']} {str(e.get('start', ''))[11:16]}" for e in events))
    actions = [{"label": f"Retry {j['title']}"[:40], "run": f"retry {j['id']}"} for j in stuck[:2]]
    if cards:
        actions.append({"label": "What needs me?", "run": "What needs me today, and what would you do first?"})
    if done:
        actions.append({"label": "Show what you did", "run": "Show me what the jobs did while I was away."})
    if actions:
        lines.append("```odie-blocks\n" + json.dumps([{"type": "actions", "items": actions[:4]}]) + "\n```")
    return "\n".join(lines)


async def welcome(store: Store, runner, now: datetime | None = None) -> bool:
    """Post the welcome into today's chat when one is due and there is something to say. True when posted."""
    now = now or datetime.now(UTC)
    since = away_since(store, now)
    if since is None:
        return False
    text = compose(gather(store, since, now), round((now - since).total_seconds() / 3600, 1))
    if not text:
        store.audit("agent", "welcome", result_summary="nothing to say")  # so the app doesn't ask again for a while
        return False
    await runner.post_message(text, kind="welcome")
    store.audit("agent", "welcome", result_summary=text[:200])
    return True
