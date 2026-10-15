"""Tools the trackers skill brings: start, list and stop background checks."""
from google.adk.tools import FunctionTool, ToolContext

from odie import trackers as T


def _fmt(t: dict) -> str:
    when = "every " + (f"{t['schedule']['minutes']} min" if "minutes" in t["schedule"] else ", ".join(t["schedule"]["times"]))
    from odie.trackers.signed_in import shown_summary
    shown = shown_summary(t)
    last = f" Last: {shown}." if shown else ""
    return f"#{t['id']} {t['title']} ({t['status']}, {when}, until {t['until_at'][:10]}).{last}"


async def track(title: str, check: str, every: str, notify: str = "change", condition: str = "", until: str = "",
                page: str = "", tool_context: ToolContext | None = None) -> str | dict:
    """Start a background tracker: Odie checks `check` on a schedule and tells the user (push + a line in Chat) when it
    matters. title: short, e.g. "Arsenal v Spurs". check: what to look up, in plain words, e.g. "Arsenal vs Spurs
    live score and match status". every: "5m", "15m", "2h", "1d", or times like "09:00", "mon 09:00", "weekdays 7:30".
    notify: "change" (default: when the result changes), "always", or "condition" with condition, e.g. "price below 3000".
    until: last date (YYYY-MM-DD); default 14 days. A check can also end it (match over, order delivered).
    page: when this chat read a page of the user's own account (their orders), the address of the one page to check;
    the user then decides whether the tracker may check it signed in."""
    from odie.signin.guard import tab_of
    from odie.trackers import signed_in
    store = T.hooks["store"]
    t = T.create(store, title, check, every, notify, condition, until, tz=T.hooks.get("tz"))
    if isinstance(t, str):
        return t
    row = next(x for x in T.listing(store) if x["id"] == t["id"])
    msg = f"Tracking now (first check within 5 minutes): {_fmt(row)} The user sees it on Today and can pause or stop it there."
    pick = signed_in.propose(store, tab_of(tool_context), page)
    if not pick:
        return msg
    return {"result": f"{msg} A card asks the user whether this tracker may check {pick} signed in to their account; "
                      "tell them in one line.", "media": signed_in.card(store, t["id"], pick)}


async def list_trackers() -> str:
    """The user's trackers: what each checks, how often, its status and the latest result."""
    rows = T.listing(T.hooks["store"])
    return "\n".join(_fmt(r) for r in rows) if rows else "No trackers."


async def stop_tracker(tracker_id: int) -> str:
    """Stop a tracker for good (the user can also pause or stop it on Today)."""
    return "Stopped." if T.set_status(T.hooks["store"], int(tracker_id), "stopped") else f"No tracker #{tracker_id}."


TOOLS = [FunctionTool(track), FunctionTool(list_trackers), FunctionTool(stop_tracker)]
