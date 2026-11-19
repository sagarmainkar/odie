"""Whose watch it is (18 Nov 2026). Everyday Odie's watch is as it always was: it reads the mail and calendar apps on for
Odie (and the Mac's own), and keeps its card, state and sources under the settings keys it always had. A personality
with its own mail or calendar app can have a watch of its own: its "Proactive intelligence" switch, off until the user
turns it on. Then the same 30-minute check runs for it, on its own brain, reading only its own apps, and keeps
everything apart under keys carrying its id ("watch.card:<id>"); its threads are its own tasks (tasks.personality).

Each inbox is checked once, never once per personality: an app Odie's watch reads is Odie's to check, and an app two
personalities share goes to the older one that has the switch on."""
from __future__ import annotations

from datetime import datetime

from odie import personalities
from odie.plugins import access

ODIE = personalities.ODIE
PROACTIVE = "proactive"  # settings key prefix: "proactive:<id>" is True when that personality's watch runs
# Every settings key a watch keeps: its card, its place in the mail, its pushes said and held, its sources.
WATCH_KEYS = ("watch.card", "watch.state", "watch.flagged", "watch.held", "watch.sources", "loops.pending")


def key(name: str, owner: str) -> str:
    """The settings key `name` for this owner's watch: everyday Odie keeps the key it always had, a personality's
    carries its id. ("watch.card", "") -> "watch.card"; ("watch.card", "ab12cd34ef56") -> "watch.card:ab12cd34ef56"."""
    if owner == ODIE:
        return name
    return f"{name}:{owner}"


def is_proactive(store, pid: str) -> bool:
    """Whether this personality's own watch runs. Off until switched on; everyday Odie has no such switch (its watch
    runs whenever it has a mail or calendar app), so ODIE -> False here. Mira, never switched -> False; switched on ->
    True; a personality that was deleted -> False."""
    if pid == ODIE or personalities.get(store, pid) is None:
        return False
    return bool(store.get_setting(key(PROACTIVE, pid)))


def set_proactive(store, pid: str, on: bool) -> None:
    store.set_setting(key(PROACTIVE, pid), bool(on))


def proactive_owners(store) -> list[str]:
    """The personalities whose own watch runs, oldest first."""
    return [p.id for p in personalities.list_all(store) if is_proactive(store, p.id)]


def watch_servers(store, configured: dict[str, dict], owner: str) -> dict[str, dict]:
    """The connected apps this owner's watch reads, from mcp.json's servers. Everyday Odie: those on for Odie. A
    personality: those on for it that Odie's watch doesn't read, and that no older personality with its switch on reads
    already (one check per inbox).
      home on for everyone, work Mira's alone, shop Mira's and Coach's, both switched on:
        Odie -> {home};  Mira -> {work, shop};  Coach -> {} (Mira checks shop);  Mira switched off -> Coach: {shop}"""
    on_for_owner = {name: spec for name, spec in configured.items() if access.allowed(store, name, owner)}
    if owner == ODIE:
        return on_for_owner
    out = {}
    for name, spec in on_for_owner.items():
        if access.allowed(store, name, ODIE):
            continue  # Odie's watch reads it
        if read_by_an_older_one(store, name, owner):
            continue
        out[name] = spec
    return out


def read_by_an_older_one(store, server: str, owner: str) -> bool:
    """Whether a personality made before this one, with its switch on, already reads this app (its watch is the one
    that checks it). shop on for Mira (older, switched on) and Coach, asking for Coach -> True; for Mira -> False;
    Mira switched off -> False."""
    for older in personalities.list_all(store):
        if older.id == owner:
            return False  # the list is oldest first: everyone after this one is younger
        if is_proactive(store, older.id) and access.allowed(store, server, older.id):
            return True
    return False


def reads_mail_or_calendar(tools: list[str]) -> bool:
    """Whether an app's tools read mail or a calendar, by the names the watch looks for (odie.watch.sources).
    ["gmail_search", "gmail_read"] -> True; ["calendar_list_events"] -> True; ["search_notes"] -> False."""
    from odie.watch.sources import EVENTS_RE, MAIL_RE
    return any(MAIL_RE.match(t) or EVENTS_RE.match(t) for t in tools)


def own_inbox_apps(store, configured: dict[str, dict], pid: str) -> list[str]:
    """This personality's own mail and calendar apps: on for it, not for everyday Odie, and reading mail or a calendar
    by the tool names they last listed (an app never loaded isn't known yet). The switch is offered only when there is
    one. Mira with work mail (gmail_search) of her own -> ["work"]; Coach with only a notes app -> []; everyday Odie
    -> [] (its watch has no switch)."""
    if pid == ODIE:
        return []
    known = access.known_tools(store)
    out = []
    for name in configured:
        mine_alone = access.allowed(store, name, pid) and not access.allowed(store, name, ODIE)
        if mine_alone and reads_mail_or_calendar(known.get(name, [])):
            out.append(name)
    return out


def last_check(store, owner: str) -> datetime | None:
    """When this owner's watch last checked or last tried (with nothing to read), the later of the two, or None
    (never, or times that can't be read). Checked 09:00, tried 09:30 -> 09:30; neither -> None."""
    state = store.get_setting(key("watch.state", owner)) or {}
    times = []
    for name in ("last_check", "tried_at"):
        try:
            times.append(datetime.fromisoformat(state[name]))
        except (KeyError, TypeError, ValueError):
            continue
    if not times:
        return None
    return max(times)


def next_due(store, now: datetime) -> str | None:
    """The personality whose own watch should check next: of those switched on and due (never checked, or 30 minutes
    since their last check), the one waiting longest; None when none is. Mira checked 09:00 and Coach 09:20, at 10:00
    -> Mira; Mira 09:50 and Coach 09:45 -> None; switched off -> never."""
    from odie.watch.check import INTERVAL
    waiting: list[tuple[datetime, str]] = []
    for pid in proactive_owners(store):
        last = last_check(store, pid)
        if last is None:
            waiting.append((datetime.min.replace(tzinfo=now.tzinfo), pid))
            continue
        if now - last >= INTERVAL:
            waiting.append((last, pid))
    if not waiting:
        return None
    waiting.sort()
    return waiting[0][1]


def forget(store, pid: str) -> None:
    """A personality was deleted: its watch's card, state and sources and its switch go, with its Now list, Odie's
    proposal for it and the week it was made (odie.loops.now), and its "Track this?" offers (odie.loops.offers)."""
    from odie.loops import now as now_list
    from odie.loops import offers
    for name in (*WATCH_KEYS, PROACTIVE, now_list.KEY, now_list.PROPOSAL, now_list.PROPOSED_WEEK, offers.KEY):
        store.execute("delete from settings where key=?", (key(name, pid),))
