"""Which connected app reads the user's mail and calendar, and exactly how to call it (spec part 2): Zapier through
its inspect tool, Composio by its tool names, any other MCP server by tool names and parameters, and add-ons by their
own hook. Write tools are never chosen. What's found is saved, and found again when the apps change or a day passes."""
from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, UTC

from odie.watch.calls import CallError, call_tool, list_tools

log = logging.getLogger("odie.watch")
KEY = "watch.sources"
VERSION = 3  # bumped when detection learns something new, so a saved source is found again (2: calendars that take
# dates; 3: a mail app's read and thread tools)
MAIL_RE = re.compile(r"^(gmail_)?(search|list|find|fetch|get)_?(e?mails?|messages?|inbox)$|^gmail_search$", re.I)
EVENTS_RE = re.compile(r"^(list|find|search|get)_?(calendar_)?events?$|^calendar_(list_)?events$", re.I)
ATTACH_RE = re.compile(r"^(gmail_)?get_?attachments?$", re.I)
READ_RE = re.compile(r"^(gmail_)?(read|get|fetch)_?(e?mail|message)(_by_id)?$|^gmail_read$", re.I)  # opens one message
THREAD_RE = re.compile(r"^(gmail_)?(read|get|fetch)_?thread$", re.I)  # reads a whole thread
COMPOSIO_READER = "GMAIL_FETCH_MESSAGE_BY_MESSAGE_ID"
COMPOSIO_THREAD = "GMAIL_FETCH_MESSAGE_BY_THREAD_ID"
WRITE_RE = re.compile(r"send|reply|forward|delete|trash|archive|create|update|modify|move|add|remove|accept|decline", re.I)


@dataclass
class Source:
    kind: str
    server: str
    app: str
    style: str
    tool: str
    fixed: dict
    query_param: str = ""
    start_param: str = ""
    end_param: str = ""
    attachment: dict | None = None
    dates: bool = False  # the window is whole days (YYYY-MM-DD), not times
    reader: dict | None = None  # {"tool", "id_param"}: opens one whole message
    thread: dict | None = None  # {"tool", "id_param"}: reads a whole thread

    @property
    def id(self) -> str:
        return f"{self.kind}:{self.server}"

    def as_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Source":
        return Source(**{k: d.get(k) for k in Source.__dataclass_fields__ if k in d})


def _props(schema: dict) -> list[str]:
    return list((schema or {}).get("properties", {}))


def _pick(props: list[str], *names: str) -> str:
    """The first of `names` the tool takes, spelled the tool's way (case doesn't matter); "" when it takes none.
    Example: props ["timeMin", "timeMax"] and names ("time_min", "timemin") -> "timeMin"; props ["q"] and ("query",) -> ""."""
    low = {p.lower(): p for p in props}
    for n in names:
        if n.lower() in low:
            return low[n.lower()]
    return ""


def _takes_a_date(name: str, prop: dict) -> bool:
    """A parameter that wants a day, not a time: a calendar's date_from ("YYYY-MM-DD") may refuse a timestamp.
    Example: date_from described "YYYY-MM-DD" -> True; start_date with no format -> True (its name says date);
    time_min -> False; start_datetime -> False (its name says time); a "date" parameter of format date-time -> False."""
    if prop.get("format") == "date" or re.search(r"YYYY-MM-DD(?!T)", str(prop.get("description") or "")):
        return True
    name_says_date = "date" in name.lower() and "time" not in name.lower()
    return name_says_date and prop.get("format") != "date-time"


async def _zapier_calendar(spec: dict, api: str, actions: dict) -> str:
    """The user's primary calendar, from Zapier's Find Calendars; Google's "primary" when that can't say."""
    fc = actions.get("google_calendar_find_calendars")
    if fc:
        try:
            res = await call_tool(spec, "execute_zapier_read_action", {"selected_api": api, "action": fc["key"],
                                                                       "tool_name": fc["tool_name"], "params": {}})
            data = json.loads(res.text)
            if isinstance(data, dict):
                rows = data.get("results")
            else:
                rows = data
            rows = [r for r in rows or [] if isinstance(r, dict) and r.get("id")]
            primaries = [r for r in rows if r.get("primary")]
            if primaries:
                best = primaries[0]
            elif rows:
                best = rows[0]  # none marked primary: the first one
            else:
                best = None
            if best:
                return str(best["id"])
        except (CallError, ValueError, TypeError):
            pass
    return "primary"


async def _zapier(name: str, spec: dict) -> list[Source]:
    def parse(text: str):
        data = json.loads(text)
        return data[0] if isinstance(data, list) and data else data
    top = parse((await call_tool(spec, "inspect_zapier_actions", {})).text)
    out: list[Source] = []
    for app in top.get("apps", []):
        api = app.get("selected_api", "")
        detail = parse((await call_tool(spec, "inspect_zapier_actions", {"selected_api": api})).text)
        actions = {a.get("tool_name"): a for a in detail.get("actions", []) if a.get("action_type") == "search"}

        def fixed(a: dict) -> dict:
            """The arguments that pick one of this app's Zapier actions, sent with every call to it."""
            return {"selected_api": api, "action": a["key"], "tool_name": a["tool_name"]}

        if "gmail_find_email" in actions:
            find_email = fixed(actions["gmail_find_email"])
            att = actions.get("gmail_get_attachment_by_filename")
            attachment = None
            if att:
                attachment = {"tool": "execute_zapier_read_action", "fixed": fixed(att), "id_param": "message_id",
                              "name_param": "attachment_filename"}
            out.append(Source("mail", name, "Zapier", "zapier", "execute_zapier_read_action", find_email,
                              query_param="query", attachment=attachment))
        if "google_calendar_find_events" in actions:
            fe = actions["google_calendar_find_events"]
            cal = fixed(fe)
            if "params" not in fe:  # Zapier lists an app's actions without their parameters: ask for this one
                one = parse((await call_tool(spec, "inspect_zapier_actions", {"selected_api": api, "tool_name": fe["tool_name"]})).text)
                fe = next((x for x in one.get("actions", []) if x.get("tool_name") == fe["tool_name"]), fe)
            params = fe.get("params") or []
            needs_calendar_id = any(p.get("key") == "calendarid" and p.get("required") for p in params)
            if needs_calendar_id:
                cal["params"] = {"calendarid": await _zapier_calendar(spec, api, actions)}  # Find Events needs one
            # Inverted on purpose: Zapier's Find Events takes end_time ("ends after") and start_time ("starts before"),
            # so "from now to 24 hours on" is end_time=now, start_time=now+24h.
            out.append(Source("calendar", name, "Zapier", "zapier", "execute_zapier_read_action", cal,
                              start_param="end_time", end_param="start_time"))
    return out


def _may_read_with(tool_name: str) -> bool:
    """May the watch pick this tool? Not when its name sounds like a write (WRITE_RE), unless the whole name reads as
    a mail or events listing (MAIL_RE, EVENTS_RE). Example: "search_emails" -> True; "list_events" -> True;
    "send_email" -> False; "create_event" -> False."""
    if not WRITE_RE.search(tool_name):
        return True
    return bool(MAIL_RE.match(tool_name) or EVENTS_RE.match(tool_name))


def _id_tool(tool: dict | None, *id_names: str) -> dict | None:
    """A read tool that takes one id, as the source keeps it: {"name": "gmail_read", schema with message_id} ->
    {"tool": "gmail_read", "id_param": "message_id"}; no tool, or none of `id_names` among its parameters -> None
    (called without its id it could only fail)."""
    if tool is None:
        return None
    props = _props(tool["input_schema"])
    id_param = _pick(props, *id_names)
    if not id_param:
        return None
    return {"tool": tool["name"], "id_param": id_param}


def _by_names(name: str, spec: dict, tools: list[dict], style: str, app: str) -> list[Source]:
    byname = {t["name"]: t for t in tools}
    out: list[Source] = []
    if style == "composio":
        mail = byname.get("GMAIL_FETCH_EMAILS")
        cal = byname.get("GOOGLECALENDAR_EVENTS_LIST") or byname.get("GOOGLECALENDAR_FIND_EVENT")
        att = byname.get("GMAIL_GET_ATTACHMENT")
        reader_tool = byname.get(COMPOSIO_READER)
        thread_tool = byname.get(COMPOSIO_THREAD)
    else:
        ok = [t for t in tools if _may_read_with(t["name"])]
        mail = next((t for t in ok if MAIL_RE.match(t["name"])), None)
        cal = next((t for t in ok if EVENTS_RE.match(t["name"])), None)
        att = next((t for t in ok if ATTACH_RE.match(t["name"])), None)
        others = [t for t in ok if mail is None or t["name"] != mail["name"]]  # the listing never also opens one
        reader_tool = next((t for t in others if READ_RE.match(t["name"])), None)
        thread_tool = next((t for t in others if THREAD_RE.match(t["name"])), None)
    if mail:
        props = _props(mail["input_schema"])
        fixed = {}
        if "max_results" in props:
            fixed = {"max_results": 25}
        query_param = _pick(props, "query", "q", "search")
        attachment = None
        if att:
            att_props = _props(att["input_schema"])
            attachment = {"tool": att["name"], "fixed": {},
                          "id_param": _pick(att_props, "message_id", "messageId", "id"),
                          "name_param": _pick(att_props, "filename", "file_name", "attachment_filename", "name")}
        reader = _id_tool(reader_tool, "message_id", "messageId", "id")
        thread = _id_tool(thread_tool, "thread_id", "threadId", "id")
        out.append(Source("mail", name, app, style, mail["name"], fixed, query_param=query_param, attachment=attachment,
                          reader=reader, thread=thread))
    if cal:
        props = _props(cal["input_schema"])
        start = _pick(props, "time_min", "timeMin", "start", "after", "start_time", "date_from", "from_date", "start_date")
        end = _pick(props, "time_max", "timeMax", "end", "before", "end_time", "date_to", "to_date", "end_date")
        schema = (cal["input_schema"] or {}).get("properties", {})
        whole_days = False
        if start:
            whole_days = _takes_a_date(start, schema.get(start) or {})
        out.append(Source("calendar", name, app, style, cal["name"], {}, start_param=start, end_param=end, dates=whole_days))
    return out


async def detect(servers: dict[str, dict]) -> list[Source]:
    from odie.plugins.presets import preset_of
    out: list[Source] = []
    for name, spec in servers.items():
        if not isinstance(spec, dict) or spec.get("enabled") is False:
            continue
        try:
            preset = preset_of(str(spec.get("url") or ""))
            tools = await list_tools(spec)
            names = {t["name"] for t in tools}
            if preset == "zapier" or {"inspect_zapier_actions", "execute_zapier_read_action"} <= names:
                out += await _zapier(name, spec)
            elif preset == "composio" or any(n.startswith(("GMAIL_", "GOOGLECALENDAR_")) for n in names):
                out += _by_names(name, spec, tools, "composio", "Composio")
            else:
                out += _by_names(name, spec, tools, "plain", str(spec.get("title") or name))
        except (CallError, ValueError, KeyError, TypeError) as e:
            log.warning("watch: %s couldn't be read for mail or calendar: %s", name, e)
    return out


def _config_hash() -> str:
    from odie.plugins.mcp import read_config
    servers, _ = read_config()
    return hashlib.sha256(json.dumps(servers, sort_keys=True).encode()).hexdigest()[:16]


def native_sources(available=None, status=None) -> list[Source]:
    """Apple Mail and the Mac's calendars as sources, on a Mac, for each app the user has allowed. A Linux box, or
    a Mac where neither is allowed -> []; Mail allowed only -> [mail:mac]."""
    from odie.mac import permissions, scripts
    if not (available or scripts.available)():
        return []
    ask = status or permissions.status
    out: list[Source] = []
    if ask("mail") == permissions.GRANTED:
        out.append(Source("mail", "mac", "Apple Mail", "native", "mac_mail_new", {}))
    if ask("calendar") == permissions.GRANTED:
        out.append(Source("calendar", "mac", "Calendar", "native", "mac_calendar_events", {}, start_param="start", end_param="end"))
    return out


find_native_sources = native_sources  # the function itself, for tests (the name above is switched off under pytest)


def forget(store) -> None:
    """Drops the saved sources, so the next check finds them again (a Mac app was just allowed or refused)."""
    store.set_setting(KEY, None)


async def detect_and_save(store) -> list[Source]:
    from odie import addons
    from odie.plugins.mcp import read_config
    servers, _ = read_config()
    found = await detect(servers)
    for got in addons.call("watch_sources", store):
        found += list(got or [])
    found += native_sources()
    store.set_setting(KEY, {"at": datetime.now(UTC).isoformat(timespec="seconds"), "config": _config_hash(), "v": VERSION,
                            "sources": [s.as_dict() for s in found]})
    return found


def saved(store) -> list[Source]:
    return [Source.from_dict(d) for d in (store.get_setting(KEY) or {}).get("sources", [])]


def stale(store, now: datetime) -> bool:
    """Should the sources be found again? Yes when none are saved (or the save is unreadable), when detection has
    learned something since (VERSION), when the connected apps changed, or when the save is over a day old.
    Example: found at 09:00 -> False at 15:00 the same day; True at 09:01 the next day; True as soon as an app is added."""
    got = store.get_setting(KEY)
    if not got:
        return True
    try:
        at = datetime.fromisoformat(got["at"])
    except (KeyError, ValueError):
        return True
    if got.get("v") != VERSION:
        return True  # detection has learned something since
    if got.get("config") != _config_hash():
        return True  # the connected apps changed
    return now - at > timedelta(hours=24)
