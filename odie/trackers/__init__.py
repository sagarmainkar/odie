"""Trackers: checks Odie runs in the background (a match, an order, a price) and tells the user about when something
worth knowing happens. A check is one short agent turn on the Jobs model; it ends with a small JSON state, and code
(not the model) compares it with the last one to decide whether to notify. Background checks can't do anything
that needs the user's tap."""
from __future__ import annotations

import json
import logging
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta, tzinfo

from odie.store.db import Store
from odie.trackers.schedule import next_due, parse_every

log = logging.getLogger("odie.trackers")
MAX_ACTIVE, MAX_FAILS, DEFAULT_DAYS, PER_RUN = 10, 3, 14, 3
DUE_EARLY = timedelta(seconds=30)
hooks: dict = {"store": None, "tz": None}  # set by the runner, for the trackers skill's tools


def _iso(dt: datetime) -> str:
    return dt.astimezone(UTC).isoformat(timespec="seconds")


def get(store: Store, tid: int) -> dict | None:
    r = store.one("select * from trackers where id=?", (tid,))
    return dict(r) if r else None


def listing(store: Store) -> list[dict]:
    """Active and paused trackers, newest first, plus anything that ended in the last day."""
    rows = store.query("select * from trackers where status in ('active','paused') or (last_checked_at >= ?) order by id desc",
                       (_iso(datetime.now(UTC) - timedelta(days=1)),))
    out = []
    for r in rows:
        d = dict(r)
        d["schedule"] = json.loads(d.pop("schedule_json"))
        d["blocks"] = json.loads(d.pop("last_blocks_json") or "null")
        out.append(d)
    return out


def set_status(store: Store, tid: int, status: str) -> bool:
    return store.execute("update trackers set status=? where id=?", (status, tid)).rowcount > 0


def create(store: Store, title: str, check: str, every: str, notify: str = "change", condition: str = "",
           until: str = "", now: datetime | None = None, tz: tzinfo | None = None) -> dict | str:
    """The new tracker, or one sentence on why not."""
    now = now or datetime.now(UTC)
    spec = parse_every(every)
    if not spec:
        return ("I can't read that 'every'. Use an interval of 5 minutes to 7 days (5m, 2h, 1d) or times "
                "(09:00, mon 09:00, weekdays 7:30, daily 08:00,20:00).")
    if notify not in ("change", "always", "condition"):
        return "notify must be change, always or condition."
    if notify == "condition" and not condition.strip():
        return "Say the condition to watch for (e.g. 'price below 3000')."
    if not title.strip() or not check.strip():
        return "Give the tracker a short title and what to check."
    if store.one("select count(*) n from trackers where status='active'")["n"] >= MAX_ACTIVE:
        return f"There are already {MAX_ACTIVE} active trackers; stop one first."
    try:
        if until:
            end = datetime.fromisoformat(until)
        else:
            end = now + timedelta(days=DEFAULT_DAYS)
        if not end.tzinfo:  # a plain date ("2026-10-20"): the end of that day where the user is
            user_tz = tz
            if not user_tz:
                user_tz = hooks.get("tz")
            if not user_tz:
                user_tz = UTC
            end = end.replace(hour=23, minute=59, tzinfo=user_tz)
    except ValueError:
        return "until must be a date like 2026-10-20."
    cur = store.execute(
        "insert into trackers(title, check_text, schedule_json, notify, condition, until_at, next_check_at, created_at) "
        "values (?,?,?,?,?,?,?,?)",
        (title.strip()[:80], check.strip()[:500], json.dumps(spec), notify, condition.strip()[:200], _iso(end), _iso(now), _iso(now)))
    store.audit("agent", "tracker_created", result_summary=title[:80])
    return get(store, cur.lastrowid)


def due(store: Store, now: datetime) -> list[dict]:
    """Active trackers whose check is due; ones past their end date are marked done instead."""
    n = _iso(now)
    store.execute("update trackers set status='done' where status='active' and until_at < ?", (n,))
    soon = _iso(now + DUE_EARLY)  # the 5-minute tick lands a few seconds early or late: a 5-minute tracker runs on each one
    return [dict(r) for r in store.query("select * from trackers where status='active' and next_check_at <= ? order by next_check_at", (soon,))]


def parse_reply(text: str) -> dict | None:
    """The check's JSON verdict: the last JSON object in the reply that has a state. It looks in the ```json blocks
    first and, only when there are none, at any flat {...} that mentions "state".
    Example: 'It ended 2-1.\n```json\n{"state": "2-1 FT", "done": true}\n```' -> {"state": "2-1 FT",
    "summary": "2-1 FT", "done": True, "met": False, "tell": True, "blocks": None}; a reply with no state anywhere -> None.
    tell is False only when the check says so ("tell": false); left out, it is True and the state comparison decides."""
    reply = text or ""
    candidates = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", reply, re.S)
    if not candidates:  # no ```json block: a bare {...} with "state" in it
        candidates = re.findall(r"(\{[^{}]*\"state\"[^{}]*\})", reply, re.S)
    for c in reversed(candidates):
        try:
            d = json.loads(c)
        except ValueError:
            continue
        if not isinstance(d, dict):
            continue
        state = str(d.get("state", "")).strip()
        if not state:
            continue
        summary = d.get("summary")
        if not summary:  # no summary: the state says it
            summary = d["state"]
        blocks = None
        if isinstance(d.get("blocks"), list):
            blocks = d["blocks"]
        return {"state": state[:200], "summary": str(summary).strip()[:200],
                "done": d.get("done") is True, "met": d.get("met") is True, "tell": d.get("tell") is not False,
                "blocks": blocks}
    return None


def _norm(s: str | None) -> str:
    return " ".join((s or "").lower().split())


def _should_notify(row: dict, result: dict) -> bool:
    """Does the user hear about this check? Always when the tracker is done; otherwise as its notify setting says:
    "always" -> every check; "change" -> when the state differs from the last one (never on the first check) and the
    check didn't say there is nothing to tell; "condition" -> when the model says the condition holds (met).
    Example: notify="change", last state "Shipped", now "Out for delivery" -> True; now " shipped " -> False (case
    and spaces don't count); now "Still shipped, no news" with "tell": false -> False (the words moved, the facts
    didn't); the first check -> False; done -> True whatever the setting."""
    if result["done"]:
        return True
    if row["notify"] == "always":
        return True
    if row["notify"] == "change":
        first = row["last_state"] is None
        if first:
            return False
        if not result["tell"]:
            return False
        return _norm(result["state"]) != _norm(row["last_state"])
    if row["notify"] == "condition":
        return bool(result["met"])
    return False


def record(store: Store, row: dict, result: dict, now: datetime, tz: tzinfo) -> bool:
    """Save a check's result and say whether the user should hear about it."""
    notify = _should_notify(row, result)
    nxt = next_due(json.loads(row["schedule_json"]), now.astimezone(tz))
    status = "done" if result["done"] else "active"
    blocks_json = None
    if result["blocks"]:
        blocks_json = json.dumps(result["blocks"])
    # A pause or stop the user made while this check ran wins: only an active tracker changes state here.
    store.execute("update trackers set last_state=?, last_summary=?, last_blocks_json=?, last_checked_at=?, next_check_at=?, "
                  "fails=0, status=case when status='active' then ? else status end where id=?",
                  (result["state"], result["summary"], blocks_json, _iso(now), _iso(nxt), status, row["id"]))
    return notify


def record_failure(store: Store, row: dict, now: datetime, tz: tzinfo) -> bool:
    """Count a failed check; True when this one pauses the tracker."""
    fails = row["fails"] + 1
    paused = fails >= MAX_FAILS
    nxt = next_due(json.loads(row["schedule_json"]), now.astimezone(tz))
    status = "paused" if paused else "active"
    store.execute("update trackers set fails=?, last_checked_at=?, next_check_at=?, status=case when status='active' then ? else status end "
                  "where id=?", (fails, _iso(now), _iso(nxt), status, row["id"]))
    return paused


REPLY_FORMAT = ("End your reply with exactly one ```json block:\n"
                '{"state": "<short and comparable: only the facts that matter, e.g. \\"2-1 FT\\" or \\"Out for delivery\\">", '
                '"summary": "<one line for a phone notification>", '
                '"done": <true when there is nothing left to track: match over, order delivered>, '
                '"met": <true if the notify condition holds now, else false>, '
                '"tell": <false only when the facts are the same as the previous state and only the wording differs; '
                'otherwise true>, '
                '"blocks": <optional odie-blocks list for the Today card, e.g. one kpis block; omit if not useful>}')


def prompt_for(row: dict) -> str:
    cond = f"\nNotify condition: {row['condition']}. Set met to true only when it holds now." if row["notify"] == "condition" else ""
    prev = row["last_state"] or "none (this is the first check)"
    return (f"Background tracker check for the user. Nobody is waiting: don't ask questions, don't chat.\n"
            f"Tracker: {row['title']}\nCheck: {row['check_text']}{cond}\nPrevious state: {prev}\n\n"
            "Use your tools (web search, skills, apps) to find the current facts. You can't send, delete, invite or run "
            "anything that needs the user's tap; don't try.\n" + REPLY_FORMAT)


Turn = Callable[[str], Awaitable[str]]
Notify = Callable[[dict, str], Awaitable[None]]


_RUNNING: set[int] = set()  # trackers being checked right now (Check now and the schedule never overlap)


def begin_check(tid: int) -> bool:
    if tid in _RUNNING:
        return False
    _RUNNING.add(tid)
    return True


def end_check(tid: int) -> None:
    _RUNNING.discard(tid)


async def check(store: Store, row: dict, turn: Turn, notify: Notify, now: datetime, tz: tzinfo) -> None:
    if not begin_check(row["id"]):
        return
    try:
        await _check(store, row, turn, notify, now, tz)
    finally:
        end_check(row["id"])


async def _check(store: Store, row: dict, turn: Turn, notify: Notify, now: datetime, tz: tzinfo) -> None:
    if row.get("signin_allowed") and row.get("page_url"):
        from odie.trackers import signed_in
        await signed_in.check(store, row, turn, notify, now, tz)
        return
    try:
        result = parse_reply(await turn(prompt_for(row)))
    except Exception:  # noqa: BLE001 (a model or tool failure must not stop the other trackers)
        log.warning("tracker %s check failed", row["id"], exc_info=True)
        result = None
    if result is None:
        if record_failure(store, row, now, tz):
            await notify(row, f"I paused this tracker: the last {MAX_FAILS} checks found nothing usable.")
        return
    if record(store, row, result, now, tz):
        await notify(row, result["summary"])


async def run_due(store: Store, turn: Turn, notify: Notify, now: datetime, tz: tzinfo, limit: int = PER_RUN) -> int:
    rows = [r for r in due(store, now) if r["id"] not in _RUNNING][:limit]
    for row in rows:
        await check(store, row, turn, notify, now, tz)
    return len(rows)


def guard(tool, args, tool_context) -> dict | None:
    """before_tool_callback for background checks: refuse anything that would need the user's tap (nobody is there
    to tap). A tool is refused when it is always gated (run_shell, install_skill, an add-on's gated tools such as
    sending mail), or when its own require_confirmation says it would ask (background_asks).
    Example: a price tracker calls web_search -> None (runs); run_shell -> refused; gmail_send_draft -> refused."""
    from odie import addons
    from odie.agent.agent import GATED_TOOLS
    from odie.signin.guard import background_asks
    always_gated = tool.name in GATED_TOOLS | addons.gated_tools()
    is_skill_install = tool.name == "install_skill"
    is_the_users_item = tool.name == "watch_close"  # only the user takes a watch item off Today
    if always_gated or is_skill_install or is_the_users_item or background_asks(tool, args, tool_context):
        return {"error": "Not allowed in a background check: this needs the user's tap. Skip it and report what you found."}
    return None
