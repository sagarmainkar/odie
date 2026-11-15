"""What a bot is doing right now, in a few words, for the live team card in the chat (spike, Nov 2026). Grok shows its
agents at work side by side; Odie's card shows each bot's last step from its record (job_actions), the question it
waits on, or the first line of its report, and the chat's app asks again every few seconds while the job runs."""
from __future__ import annotations

import json
from urllib.parse import urlsplit

from odie.store.db import Store
from odie.workers import store as jobs

HEAD_MAX = 140
WAITING_WORDS = {"tap": "waiting for your tap", "sign_in": "waiting for you to sign in", "secret": "waiting for your code"}


def _args(action: dict) -> dict:
    try:
        got = json.loads(action.get("args_json") or "{}")
    except ValueError:
        return {}
    return got if isinstance(got, dict) else {}


def _host(url: str) -> str:
    """A page's site for a line: "https://www.zigwheels.com/honda" -> "zigwheels.com"; "" -> "a page"."""
    host = urlsplit(url or "").hostname or ""
    host = host.removeprefix("www.")
    return host or "a page"


def _short(text: str, limit: int = 60) -> str:
    one = " ".join(str(text or "").split())
    if len(one) <= limit:
        return one
    return one[: limit - 1].rstrip() + "…"


def activity_line(action: dict) -> str:
    """One step of a bot in plain words. Worked examples:
      web_search {"query": "CB350 price Bangalore"}       -> 'searching "CB350 price Bangalore"'
      web_fetch {"url": "https://www.zigwheels.com/x"}    -> "reading zigwheels.com"
      browser_click {"text": "Next"}                      -> 'clicking "Next"'
      ask_bots {"asks": [{…}, {…}, {…}]}                  -> "asking 3 bots"
      make_bot {"name": "skeptic"}                        -> "adding skeptic to the team"
      a refused step                                       -> "refused: <why>"
      report                                               -> "writing the answer"
      anything else (run_shell)                            -> "running a command\""""
    tool = action.get("tool") or ""
    args = _args(action)
    if action.get("refused"):
        return f"refused: {_short(action['refused'])}"
    words = {
        "web_search": lambda: f'searching "{_short(args.get("query", ""))}"',
        "web_fetch": lambda: f"reading {_host(args.get('url', ''))}",
        "browser_open": lambda: f"opening {_host(args.get('url', ''))}",
        "browser_click": lambda: f'clicking "{_short(args.get("text", ""), 40)}"',
        "browser_type": lambda: f'typing into "{_short(args.get("field", ""), 40)}"',
        "browser_scroll": lambda: "scrolling the page",
        "browser_sign_in": lambda: "waiting for you to sign in",
        "find_images": lambda: f'finding photos of "{_short(args.get("query", ""), 40)}"',
        "ask_bots": lambda: f"asking {len(args.get('asks') or [])} bots",
        "make_bot": lambda: f"adding {args.get('name', 'a bot')} to the team",
        "list_bots": lambda: "looking at the team",
        "read_file": lambda: f"reading its {args.get('name', 'notes')}",
        "write_file": lambda: f"writing {args.get('name', 'a file')}",
        "run_shell": lambda: "running a command",
        "user_tap": lambda: f"you said {args.get('said', '')}",
        "report": lambda: "writing the answer",
    }
    make = words.get(tool)
    if make is None:
        return f"using {tool}" if tool else "starting"
    return make()


def now_line(store: Store, row: dict) -> str:
    """What one bot's job shows now: waiting on the user's tap first, else a chief waiting on its teammates ("waiting
    for 3 bots"), else a running job's last step, else how it ended (the report's first line, or why it failed).
    A queued job -> "waiting for a turn"."""
    from odie.workers import asks
    status = row["status"]
    if status in ("queued",):
        return "waiting for a turn"
    waiting = asks.open_for(store, row["id"])
    if waiting:
        return WAITING_WORDS.get(waiting[0]["kind"], "waiting for you")
    if status == "running":
        busy = store.one("select count(*) as n from jobs where parent_id=? and status in ('queued','running')",
                         (row["id"],))["n"]
        if busy:  # a chief inside ask_bots: its own last step was before it asked
            return f"waiting for {busy} bot{'' if busy == 1 else 's'}"
        acts = jobs.actions(store, row["id"])
        return activity_line(acts[-1]) if acts else "starting"
    if status == "waiting":
        return f"next run at {(row.get('next_run_at') or '')[11:16]} UTC"
    if status == "failed":
        return f"didn't finish: {_short(row.get('error') or '', HEAD_MAX)}"
    if status == "stopped":
        return "stopped"
    head = (row.get("report") or "").strip().splitlines()
    first = head[0] if head else "done"
    return _short(first.strip("*# "), HEAD_MAX)


def model_words(store: Store, bot_name: str) -> str:
    """The model a bot runs on, short: its pick ("lfm3:latest"), else the chat's ("deepseek-v4.1-flash:1017-cloud")."""
    from odie.models import resolve_selection
    from odie.workers import bots
    bot = bots.get(store, bot_name)
    if bot is not None and bot.model:
        return bot.model["model"]
    try:
        return resolve_selection(store, "chat").model
    except Exception:  # noqa: BLE001 (no model chosen yet: the card just leaves it out)
        return ""


def member(store: Store, row: dict) -> dict:
    """One bot's line on the card."""
    from odie.workers import bots
    found = bots.get(store, row.get("bot") or "")
    look = found.as_dict()["look"] if found else None
    own_model = bool(found and found.model)  # the card names a model only when it isn't the chat's
    return {"job": row["id"], "bot": row.get("bot") or row.get("kind") or "worker", "look": look, "own_model": own_model, "status": row["status"],
            "outcome": row.get("outcome"), "now": now_line(store, row), "model": model_words(store, row.get("bot") or ""),
            "report": (row.get("report") or row.get("error") or "")[:4000],
            "calls": store.one("select count(*) as n from job_actions where job_id=?", (row["id"],))["n"],
            "started_at": row.get("started_at"), "ended_at": row.get("ended_at"), **browser_of(row["id"])}


def browser_of(job_id: str) -> dict:
    """A bot's browser tab (named by its job) and page, when it has opened one: Watch opens it live. The tab is the
    job's id (each Worker's session is its job): {"tab": "job-3f9a2c", "url": "https://amazon.in/…"}; none -> nulls."""
    from odie.signin import guard
    url = guard.LAST_URL.get(job_id)
    if not url:
        return {"tab": None, "url": None}
    return {"tab": job_id, "url": url}


def team_view(store: Store, job_id: str) -> dict | None:
    """The whole card: the lead (the chief, or the one bot asked) and its teammates in the order asked; None for an
    unknown job."""
    row = jobs.get(store, job_id)
    if row is None:
        return None
    mates = [dict(r) for r in store.query("select * from jobs where parent_id=? order by created_at", (job_id,))]
    return {"lead": member(store, row), "team": [member(store, m) for m in mates], "title": row["title"],
            "made": bots_made(store, job_id)}


def bots_made(store: Store, job_id: str) -> list[str]:
    """The bots a chief's turn made (its make_bot calls that worked), for a "Meet …" chip under its answer:
    one make_bot "stocks" -> ["stocks"]; a make_bot refused (a name taken) -> not listed; none -> []."""
    from odie.workers import bots
    out = []
    for a in jobs.actions(store, job_id):
        if a["tool"] != "make_bot" or a.get("refused") or a.get("error"):
            continue
        name = bots.clean_name(str(_args(a).get("name") or ""))
        if name and name not in out and bots.get(store, name) is not None:
            out.append(name)
    return out
