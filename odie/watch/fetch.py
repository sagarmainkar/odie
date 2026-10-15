"""Reading the user's mail and events through the detected sources, and what changed since the last check (spec part
2's tools, behind new_mail / upcoming_events / read_mail / save_attachment). Results are parsed from the shapes Zapier,
Composio and common MCP servers use into short records; raw copies and long bodies never reach the model."""
from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, UTC
from pathlib import Path


from odie.watch.calls import CallError, call_tool
from odie.watch.sources import Source, saved

log = logging.getLogger("odie.watch")
STATE = "watch.state"
MAX_MAIL = 25
SNIPPET = 300
BODY = 6000
SAFE_NAME = re.compile(r"^[^/\\\x00]{1,200}$")


def _first(d: dict, *keys: str, default=""):
    """The value under the first of `keys` that has one; None, "", [] and {} count as none (0 and False count).
    Example: _first({"id": "", "messageId": "c1"}, "id", "messageId") -> "c1"; no key has a value -> default."""
    for k in keys:
        v = d.get(k)
        if v not in (None, "", [], {}):
            return v
    return default


def _list_in(data) -> list[dict]:
    """The list of records in a result: the top level, or under results / messages / items / events / data."""
    if isinstance(data, list):
        return [x for x in data if isinstance(x, dict)]
    if isinstance(data, dict):
        for k in ("results", "messages", "items", "events", "data", "emails"):
            v = data.get(k)
            got = _list_in(v) if isinstance(v, (list, dict)) else []
            if got:
                return got
    return []


def _who(v) -> str:
    """A sender (or a list of people) as one line of text.
    Example: {"name": "Xyz", "email": "xyz@example.com"} -> "Xyz <xyz@example.com>"; {"address": "a@b.c"} -> "a@b.c";
    a list -> its first three, comma-separated; "a@b.c" -> "a@b.c"; None -> ""."""
    if isinstance(v, dict):
        name = v.get("name") or ""
        email = v.get("email")  # some apps call it "address"
        if not email:
            email = v.get("address")
        if not email:
            email = ""
        if name and email:
            return f"{name} <{email}>"
        return name or email
    if isinstance(v, list):
        return ", ".join(_who(x) for x in v[:3])
    return str(v or "")


@dataclass
class Mail:
    id: str
    frm: str
    subject: str
    at: str
    snippet: str
    attachments: list[dict]
    source: str
    body: str = ""

    def brief(self) -> dict:
        return {"id": self.id, "from": self.frm, "subject": self.subject, "at": self.at, "snippet": self.snippet,
                "attachments": self.attachments}


@dataclass
class Event:
    id: str
    title: str
    start: str
    end: str
    where: str
    attendees: list[str]
    source: str
    change: str | None = None

    def brief(self) -> dict:
        return {"id": self.id, "title": self.title, "start": self.start, "end": self.end, "where": self.where,
                "attendees": self.attendees, "change": self.change}


# Why each field below is looked up under several names: every mail app answers in its own shape, so the same field
# arrives under different keys, and _first takes the first one that has a value, in the order listed.
# Example: Zapier's Gmail sends {"id": "m1", "from": {"name": "Xyz", "email": "xyz@example.com"},
# "date": "2026-10-08T08:40:00Z", "body_plain": "...", "all_attachments": [{"file_name": "q3.pdf", "mime_type": ...}]};
# Composio's sends {"messageId": "c1", "sender": "a@b.c", "messageTimestamp": "2026-10-08T08:00:00Z", "messageText": "..."}.
# Both become a Mail: id "m1" / "c1", from "Xyz <xyz@example.com>" / "a@b.c", and so on.


def _attachment_list(r: dict):
    """A message's attachment records, under the first of its app's names for them that isn't empty.
    Example: Zapier's {"all_attachments": [{"file_name": "q3.pdf"}]} -> that list; no attachments at all -> []."""
    found = r.get("all_attachments")
    if not found:
        found = r.get("attachments")
    if not found:
        found = r.get("attachmentList")
    if not found:
        found = []
    return found


def _attachment(a: dict) -> dict:
    """One attachment in short. Example: {"file_name": "q3.pdf", "mime_type": "application/pdf", "size": 120000}
    -> {"name": "q3.pdf", "type": "application/pdf", "size": 120000}; a missing size -> 0."""
    name = str(_first(a, "file_name", "filename", "name"))
    mime_type = str(_first(a, "mime_type", "mimeType", "type"))
    size = _first(a, "size", default=0)
    return {"name": name, "type": mime_type, "size": size}


def parse_mail(text: str, source: str) -> list[Mail]:
    try:
        rows = _list_in(json.loads(text))
    except ValueError:
        return []
    out = []
    for r in rows:
        mid = str(_first(r, "id", "message_id", "messageId", "msg_id"))
        if not mid:
            continue
        body = str(_first(r, "body_plain", "messageText", "text", "body", "snippet", "preview"))
        atts = []
        for a in _attachment_list(r):
            if isinstance(a, dict):
                atts.append(_attachment(a))
        sender = _who(_first(r, "from", "sender", "from_email", "from__email"))
        subject = str(_first(r, "subject", "title"))
        at = str(_first(r, "date", "messageTimestamp", "internalDate", "received_at"))
        out.append(Mail(id=mid, frm=sender, subject=subject, at=at, snippet=body[:SNIPPET], attachments=atts,
                        source=source, body=body[:BODY]))
    return out


def _attendee(a) -> str:
    """One attendee as text. Example: {"email": "a@example.com"} -> "a@example.com"; {"name": "Asha"} -> "Asha";
    "b@example.com" -> "b@example.com"."""
    if isinstance(a, dict):
        return str(_first(a, "email", "name"))
    return str(a)


def _when(v) -> str:
    if isinstance(v, dict):
        return str(_first(v, "dateTime", "date_time", "date"))
    return str(v or "")


# Line-style calendar apps (a calendar_list_events that answers in text): one event per line, "id | 18:30-19:00 | title | a@x, b@y @ place" or
# "id | all day 2026-10-10 | title", local times, and a "## 2026-10-10" line before each day when it lists several.
_DAY = re.compile(r"^## (\d{4}-\d{2}-\d{2})$")
_LINE = re.compile(r"^(\S+) \| (?:all day (\d{4}-\d{2}-\d{2})|(\d{2}:\d{2})-(\d{2}:\d{2})) \| (.+)$")


def _event_lines(text: str, source: str, day: str, tz) -> list[Event]:
    out = []
    for raw in text.splitlines():
        ln = raw.strip()
        day_heading = _DAY.match(ln)
        if day_heading:
            day = day_heading.group(1)
            continue
        m = _LINE.match(ln)
        if not m:
            continue  # "No events on …", or anything else
        eid, all_day, t0, t1, rest = m.groups()
        title, _, who = rest.partition(" | ")
        where = ""
        if " @ " in (who or title):  # the place ends the line: after the attendees, or the title when there are none
            if who:
                who, _, where = who.rpartition(" @ ")
            else:
                title, _, where = title.rpartition(" @ ")
        if all_day:
            start, end = all_day, ""
        else:
            try:
                d = datetime.fromisoformat(day).date()
            except ValueError:
                continue  # a time with no day to put it on
            starts = datetime.combine(d, time.fromisoformat(t0), tz)
            ends = datetime.combine(d, time.fromisoformat(t1), tz)
            if ends < starts:  # past midnight: "23:30-00:30" ends on the next day
                ends = ends + timedelta(days=1)
            start, end = starts.isoformat(), ends.isoformat()
        attendees = [w.strip() for w in who.split(",") if w.strip()][:5]
        out.append(Event(id=eid, title=title.strip(), start=start, end=end, where=where.strip(), attendees=attendees,
                         source=source))
    return out


def parse_events(text: str, source: str, day: str = "", tz=None) -> list[Event]:
    """JSON from most apps; else event lines (a line-style calendar app), whose times fall on `day` until a "## day" line says otherwise."""
    try:
        rows = _list_in(json.loads(text))
    except ValueError:
        return _event_lines(text, source, day, tz)
    out = []
    for r in rows:
        eid = str(_first(r, "id", "event_id", "eventId"))
        if not eid:
            continue
        attendees = r.get("attendees") or []
        who = [_attendee(a) for a in attendees][:5]
        title = str(_first(r, "summary", "title", "name"))
        start = _when(_first(r, "start", "start_time", "startTime"))
        end = _when(_first(r, "end", "end_time", "endTime"))
        where = str(_first(r, "location", "where"))
        out.append(Event(id=eid, title=title, start=start, end=end, where=where, attendees=who, source=source))
    return out


MAX_ATTACHMENT = 25 * 1024 * 1024


def _within(start: str, lo: datetime, hi: datetime) -> bool:
    try:
        t = datetime.fromisoformat(start.replace("Z", "+00:00"))
    except ValueError:
        return False
    if t.tzinfo is None:
        t = t.replace(tzinfo=lo.tzinfo)
    return lo <= t <= hi


def _over(e: Event, now: datetime) -> bool:
    try:
        return "T" in e.end and datetime.fromisoformat(e.end) < now
    except ValueError:
        return False


def _change_of(e: Event, before: dict[str, str]) -> str | None:
    """How an event differs from the last check, which saved each event's id and start.
    Example: an id the last check didn't have -> "new"; the same id, its start 15:00 now 16:00 -> "moved";
    the same id and start -> None."""
    if e.id not in before:
        return "new"
    if before[e.id] != e.start:
        return "moved"
    return None


async def _download(url: str) -> bytes:
    from odie.net import DownloadError, safe_download
    try:
        body, _ = await safe_download(url, MAX_ATTACHMENT, timeout=60)
    except DownloadError as e:
        raise CallError(f"The attachment: {e}") from None
    return body


class Fetcher:
    def __init__(self, store, now: datetime):
        self.store, self.now = store, now
        self._calendar_ok = False
        self.state = store.get_setting(STATE) or {"last_check": None, "seen": [], "events": {}, "sources": {}}
        self.statuses: dict[str, dict] = {}
        self.first: set[str] = set()
        self._mail: dict[str, Mail] = {}
        self._events: list[Event] = []
        self._servers = None

    def _spec(self, src: Source) -> dict:
        if self._servers is None:
            from odie.plugins.mcp import read_config
            self._servers = read_config()[0]
        spec = self._servers.get(src.server)
        if not isinstance(spec, dict):
            raise CallError(f"{src.app} isn't connected any more")
        return spec

    def _ok(self, src: Source, ok: bool, reason: str = "") -> None:
        self.statuses[src.id] = {"ok": ok, "at": self.now.isoformat(timespec="seconds"), "reason": reason, "app": src.app, "kind": src.kind}
        if src.id not in self.state["sources"]:
            self.first.add(src.id)

    def _since(self, src: Source) -> datetime:
        """This source's last good read (mail that came while it failed is read now), else a day back."""
        a_day_back = self.now - timedelta(hours=24)
        all_sources = self.state.get("sources") or {}
        this_source = all_sources.get(src.id) or {}
        last = this_source.get("last_ok")
        if not last:
            return a_day_back
        try:
            return datetime.fromisoformat(last)
        except ValueError:
            return a_day_back

    async def new_mail(self) -> list[Mail]:
        seen = set(self.state.get("seen") or [])
        got: list[Mail] = []
        for src in (s for s in saved(self.store) if s.kind == "mail"):
            since_dt = self._since(src)
            args = dict(src.fixed)
            query = f"after:{int(since_dt.timestamp())}"
            if src.style == "zapier":
                args["params"] = {**(args.get("params") or {}), src.query_param: query}
            elif src.query_param:
                args[src.query_param] = query
            try:
                res = await call_tool(self._spec(src), src.tool, args)
                if res.is_error:
                    raise CallError(res.text[:200] or "the app said no")
                mails = parse_mail(res.text, src.id)
                self._ok(src, True)
            except CallError as e:
                self._ok(src, False, str(e))
                continue
            got += [m for m in mails if m.id not in seen]
        for m in got:
            self._mail[m.id] = m
        got.sort(key=lambda m: m.at, reverse=True)
        log.info("watch: %d new mails", len(got))
        return got[:MAX_MAIL]

    async def upcoming_events(self, hours: int = 24) -> list[Event]:
        start, end = self.now, self.now + timedelta(hours=hours)
        got: list[Event] = []
        for src in (s for s in saved(self.store) if s.kind == "calendar"):
            args = dict(src.fixed)
            if src.dates:  # whole days (a date_from-style calendar): today to the window's last day
                window = {src.start_param: start.date().isoformat(), src.end_param: end.date().isoformat()}
            else:
                window = {src.start_param: start.isoformat(timespec="seconds"), src.end_param: end.isoformat(timespec="seconds")}
            window = {k: v for k, v in window.items() if k}
            if src.style == "zapier":
                args["params"] = {**(args.get("params") or {}), **window}  # the calendar id stays
            else:
                args.update(window)
            try:
                res = await call_tool(self._spec(src), src.tool, args)
                if res.is_error:
                    raise CallError(res.text[:200] or "the app said no")
                found = parse_events(res.text, src.id, start.date().isoformat(), start.tzinfo)
                if src.dates:  # whole days include what's already over today
                    found = [e for e in found if not _over(e, start)]
                got += found
                self._ok(src, True)
            except CallError as e:
                self._ok(src, False, str(e))
        before: dict[str, str] = self.state.get("events") or {}
        cals = [s.id for s in saved(self.store) if s.kind == "calendar"]
        self._calendar_ok = bool(cals) and all(self.statuses.get(c, {}).get("ok") for c in cals)
        now_ids = {e.id for e in got}
        for e in got:
            e.change = _change_of(e, before)
        if self._calendar_ok:  # a calendar that didn't answer cancels nothing
            for eid, st in before.items():
                if eid not in now_ids and _within(st, start, end):  # gone from the window, not just over
                    got.append(Event(eid, "(cancelled)", st, "", "", [], "", change="cancelled"))
        self._events = got
        return got

    def read_mail(self, mail_id: str) -> Mail | None:
        return self._mail.get(mail_id)

    async def save_attachment(self, mail_id: str, name: str) -> Path:
        from odie.agent.tools.files import workspace
        if not SAFE_NAME.match(name) or name in (".", "..") or "/" in name or "\\" in name or ".." in name:
            raise CallError("That isn't a file name.")
        mail = self._mail.get(mail_id)
        src = next((s for s in saved(self.store) if mail and s.id == mail.source), None)
        if src is None or not src.attachment:
            raise CallError("This app can't fetch attachments.")
        a = src.attachment
        args = dict(a.get("fixed") or {})
        params = {a["id_param"]: mail_id, a["name_param"]: name}
        if src.style == "zapier":
            args["params"] = params
        else:
            args.update(params)
        res = await call_tool(self._spec(src), a["tool"], args)
        data = await self._bytes(res.text)
        folder = (workspace() / "watch" / re.sub(r"[^A-Za-z0-9_-]", "_", mail_id)[:80]).resolve()
        folder.mkdir(parents=True, exist_ok=True)
        path = (folder / name).resolve()
        if folder not in path.parents:
            raise CallError("That isn't a file name.")
        path.write_bytes(data)
        return path

    async def _bytes(self, text: str) -> bytes:
        """The attachment from the app's answer: base64 under data / content / base64, or a download link under url /
        download_url / file (Zapier's). A link is fetched only when it's a public web address, each redirect checked,
        at most 25 MB: never a link an attachment's own text supplies, and never this computer or the home network."""
        try:
            d = json.loads(text)
        except ValueError:
            raise CallError("The app didn't send the file.") from None
        rows = _list_in(d)
        if not rows:  # no list of records: the one record is under "data" when that's an object, else the answer itself
            if isinstance(d, dict) and isinstance(d.get("data"), dict):
                rows = [d.get("data")]
            else:
                rows = [d]
        r = {}
        if rows and isinstance(rows[0], dict):
            r = rows[0]
        for k in ("url", "download_url", "file"):
            v = r.get(k)
            if isinstance(v, str) and v.startswith(("http://", "https://")):
                return await _download(v)
        for k in ("data", "content", "base64"):
            v = r.get(k)
            if isinstance(v, str) and v and not v.startswith(("http://", "https://")):
                try:
                    return base64.b64decode(v, validate=True)
                except ValueError:
                    continue
        raise CallError("The app didn't send the file (it gives no download for attachments).")

    def commit(self) -> None:
        """Save where this check got to, for the next one: the mail ids seen, each event's start, and each source's
        run of failed checks and its last good read."""
        seen_before = self.state.get("seen") or []
        seen = list(dict.fromkeys([*self._mail, *seen_before]))[:500]  # this check's ids first, no repeats

        if self._calendar_ok:
            # Every calendar answered: what they showed now is the list (a cancelled event drops out).
            events = {e.id: e.start for e in self._events if e.change != "cancelled"}
        else:
            # A calendar failed: keep the last good list, updated with whatever did come back.
            last_good = self.state.get("events") or {}
            read_now = {e.id: e.start for e in self._events}
            events = {**last_good, **read_now}

        # Each source's failures in a row, and when it last answered.
        # Example: gmail failed its 2nd check in a row -> fails 2, last_ok stays at its last good check;
        # it answers on the next one -> fails 0, last_ok is now.
        srcs = dict(self.state.get("sources") or {})
        for sid, st in self.statuses.items():
            prev = srcs.get(sid) or {}
            if st["ok"]:
                fails = 0
                last_ok = st["at"]
            else:
                fails = int(prev.get("fails", 0)) + 1
                last_ok = prev.get("last_ok")
            srcs[sid] = {**st, "fails": fails, "last_ok": last_ok}

        self.store.set_setting(STATE, {"last_check": self.now.isoformat(timespec="seconds"), "seen": seen, "events": events, "sources": srcs})
