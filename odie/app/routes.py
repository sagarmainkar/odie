"""HTTP API. Everything the PWA talks to."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, File, HTTPException, Request, UploadFile, WebSocket
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from odie import config, devices, persona, qr
from odie.models import (PRESET_BY_ID, PRESETS, Provider, all_providers, auth_headers, brain_chosen, custom_key_name,
                         list_models, preset_base_url, refresh_fallback, resolve_selection, slug)
from odie.photos.library import PHOTO_UUID
from odie.secrets import remove_secret, save_secret
from odie.store.db import approval_dict as _approval_dict
from odie.agent.prompt import Who, identity

log = logging.getLogger("odie.api")
SOUL_PATH = config.settings.config_dir / "SOUL.md"  # follows ODIE_CONFIG_DIR, so a test instance has its own
router = APIRouter(prefix="/api")


class ChatIn(BaseModel):
    text: str
    thinking: bool = False
    images: list[str] = []
    session_id: str | None = None  # continue an older thread; None = today's


class Keys(BaseModel):
    p256dh: str
    auth: str


class SubscriptionIn(BaseModel):
    endpoint: str
    keys: Keys


def _sse(events):
    async def gen():
        async for e in events:
            yield {"data": json.dumps(e)}
    return EventSourceResponse(gen(), sep="\n")  # the PWA splits on LF; sse-starlette defaults to CRLF


async def _lm_studio_ok() -> bool:
    s = config.settings
    try:
        async with httpx.AsyncClient(timeout=2) as c:
            r = await c.get(s.lm_studio_base_url + "/models")
            return r.status_code == 200 and any(m.get("id") == s.model_id for m in r.json().get("data", []))
    except Exception:  # noqa: BLE001
        return False


@router.get("/health")
async def health(request: Request) -> dict[str, Any]:
    if devices.pairing_on(request.app.state.store) and _device(request) is None:
        return {"status": "ok"}  # no data for a browser that isn't paired
    lm = await _lm_studio_ok()
    cur = getattr(request.app.state.runner, "current_model", None)
    chosen = cur() if cur else {"provider": "lmstudio", "model": config.settings.model_id, "leaves_mini": False}
    connections: dict[str, bool] = {}
    from odie import addons
    for more in await addons.acall("connections"):
        connections.update(more)
    from odie import update
    brain_reachable = lm or chosen["provider"] != "lmstudio"  # only LM Studio is probed here; a cloud brain has its key
    return {"status": "ok", "name": "Odie", "version": update.version(), "model": chosen["model"], "provider": chosen["provider"],
            "leaves_mini": chosen["leaves_mini"], "lm_studio": lm, "connections": connections,
            "brain_chosen": brain_chosen(request.app.state.store), "brain_reachable": brain_reachable}


@router.get("/update")
async def update_get(force: bool = False) -> dict[str, Any]:
    """Whether a newer Odie is on origin: the app asks hourly (a cached answer) and on "Check now" (force)."""
    from odie import update
    if not update.can_update():
        raise HTTPException(503, "This Odie isn't the installed copy, so it can't update itself.")
    try:
        state = await update.check(force)
    except RuntimeError as e:
        raise HTTPException(502, f"Couldn't check for a new version: {e}") from None
    return {**state, "running": update.running()}


@router.post("/update")
async def update_post() -> dict[str, Any]:
    """Starts `odie update`. The server restarts during it; the app watches /api/health for the new version."""
    from odie import update
    if not update.can_update():
        raise HTTPException(503, "This Odie isn't the installed copy, so it can't update itself.")
    if update.running():
        raise HTTPException(409, "An update is already running.")
    return {"started": True, "pid": update.start(), "from": update.version()}


def reply_preview(text: str, limit: int = 140) -> str:
    """The first words of a reply for a push: before any chart or image block, Markdown marks dropped."""
    plain = re.sub(r"[*_`#>]", "", text.split("```", 1)[0]).strip()
    plain = re.sub(r"\s+", " ", plain)
    return plain if len(plain) <= limit else plain[: limit - 1].rstrip() + "…"


@router.post("/chat")
async def chat(body: ChatIn, request: Request):
    from odie.app.detached import detached
    from odie.push.send import send_to_all
    store = request.app.state.store

    def answered_while_away(text: str) -> None:
        send_to_all(store, f"{persona.get(store)['name']} answered", reply_preview(text) or "Your answer is ready.",
                    url="/#chat", tag="reply")

    from odie import threads
    if body.session_id is not None and not threads.valid_id(body.session_id):
        raise HTTPException(422, "not a chat thread")
    kw = {"session_id": body.session_id} if body.session_id else {}
    turn = request.app.state.runner.chat(body.text, thinking=body.thinking, images=body.images or None, **kw)
    return _sse(detached(turn, on_orphaned_done=answered_while_away))


@router.post("/upload")
async def upload(file: UploadFile = File(...)):
    from odie.app.images import prepare_image, uploads_dir
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(415, "images only")
    data = await file.read()
    if len(data) > 25_000_000:
        raise HTTPException(413, "image too large")
    try:
        out = prepare_image(data, uploads_dir())
    except Exception as e:  # noqa: BLE001
        raise HTTPException(422, f"could not read image: {type(e).__name__}") from e
    return {"id": out["id"], "w": out["w"], "h": out["h"], "url": f"/api/uploads/{out['id']}"}


@router.get("/uploads/{iid}")
async def uploaded(iid: str):
    from odie.app.images import load_image
    got = load_image(iid)
    if not got:
        raise HTTPException(404, "no such image")
    return Response(content=got[0], media_type=got[1], headers={"Cache-Control": "private, max-age=31536000"})


@router.get("/media/{mid}")
async def media_file(mid: str):
    """What a tool made (odie.media): played or shown inline; a file is offered as a download."""
    from fastapi.responses import FileResponse
    from odie import media
    got = media.get(mid)
    if got is None:
        raise HTTPException(404, "no such media")
    path, m = got
    safe = {"X-Content-Type-Options": "nosniff"}
    if m["kind"] == "file":  # always a download, sandboxed: an HTML file never runs on Odie's address
        return FileResponse(path, media_type=m["mime"], filename=m.get("filename") or m["title"] or "file",
                            headers={**safe, "Content-Security-Policy": "sandbox"})
    if m["kind"] == "picture":  # shown inline; sandboxed too, so an SVG opened on its own can't run anything
        return FileResponse(path, media_type=m["mime"], headers={**safe, "Content-Security-Policy": "sandbox", "Cache-Control": "private, max-age=86400"})
    return FileResponse(path, media_type=m["mime"], headers={**safe, "Cache-Control": "private, max-age=86400"})  # ranges served: a video scrubs


@router.get("/history")
async def history(date: str, request: Request, limit: int | None = None, before: int | None = None):
    return await request.app.state.runner.history(date, limit=limit, before=before)


# --- Threads: every conversation, searchable, pinnable, renamable ---
class PinIn(BaseModel):
    pinned: bool


class TitleIn(BaseModel):
    title: str


def _thread_id(sid: str) -> str:
    from odie import threads
    if not threads.valid_id(sid):
        raise HTTPException(404, "no such thread")
    return sid


@router.get("/threads")
async def threads_list(request: Request, q: str | None = None):
    from odie import threads
    return {"threads": await asyncio.to_thread(threads.list_threads, request.app.state.store, q)}


@router.get("/threads/{sid}/history")
async def thread_history(sid: str, request: Request, limit: int | None = None, before: int | None = None):
    return await request.app.state.runner.session_history(_thread_id(sid), limit=limit, before=before)


@router.post("/threads/{sid}/pin")
async def thread_pin(sid: str, body: PinIn, request: Request):
    from odie import threads
    threads.set_pinned(request.app.state.store, _thread_id(sid), body.pinned)
    return {"ok": True, "pinned": body.pinned}


@router.post("/threads/{sid}/rename")
async def thread_rename(sid: str, body: TitleIn, request: Request):
    from odie import threads
    threads.rename(request.app.state.store, _thread_id(sid), body.title)
    return {"ok": True, "title": " ".join(body.title.split())[:threads.TITLE_MAX]}


class StopIn(BaseModel):
    session_id: str | None = None


@router.post("/chat/stop")
async def chat_stop(body: StopIn, request: Request):
    """The user tapped Stop: the running turn in this chat (today's, or the open thread) ends at its next safe step."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from odie import threads
    runner = request.app.state.runner
    if body.session_id is not None and not threads.valid_id(body.session_id):
        raise HTTPException(422, "not a chat thread")
    today = datetime.now(ZoneInfo(config.settings.timezone)).strftime("%Y-%m-%d")
    current = getattr(runner, "current_session_id", None)
    sid = body.session_id or (current(today) if current else f"chat-{today}")
    stop = getattr(runner, "request_stop", None)
    if stop:
        stop(sid)
    return {"ok": True, "session_id": sid}


@router.get("/chat/context")
async def chat_context(request: Request):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    today = datetime.now(ZoneInfo(config.settings.timezone)).strftime("%Y-%m-%d")
    return await request.app.state.runner.context_usage(today)


@router.post("/chat/new")
async def chat_new(request: Request):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    today = datetime.now(ZoneInfo(config.settings.timezone)).strftime("%Y-%m-%d")
    return {"session_id": await request.app.state.runner.new_chat(today)}


@router.get("/tasks")
async def tasks(request: Request, status: str = "open"):
    store = request.app.state.store
    rows = store.open_tasks() if status == "open" else store.list_tasks(None if status == "all" else status)
    return [dict(r) for r in rows]


@router.get("/tasks/closed_today")
async def tasks_closed_today(request: Request):
    from datetime import UTC, datetime
    from zoneinfo import ZoneInfo
    tz = ZoneInfo(config.settings.timezone)
    midnight = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(UTC)
    return {"count": request.app.state.store.closed_today(midnight.strftime("%Y-%m-%dT%H:%M:%S.000Z"))}


class EnabledIn(BaseModel):
    enabled: bool


class OnIn(BaseModel):
    on: bool


class ServerIn(BaseModel):
    name: str
    spec: dict


def _skill_json(e) -> dict:
    from odie.skills.registry import shown_as
    title, summary = shown_as(e)
    return {"name": e.name, "title": title, "summary": summary, "description": e.description, "source": e.source,
            "status": e.status, "tools": e.tools, "reason": e.reason}


@router.get("/skills")
async def skills_list(request: Request):
    from odie.skills.registry import discover
    return {"skills": [_skill_json(e) for e in discover(request.app.state.store)]}


@router.post("/skills/{name}/trust")
async def skills_trust(name: str, request: Request):
    from odie.skills.registry import discover, trust
    e = next((x for x in discover(request.app.state.store) if x.name == name), None)
    if e is None or e.source != "user" or not e.code_hash:
        raise HTTPException(404, "no such skill with code")
    trust(request.app.state.store, e)
    request.app.state.store.audit("user", "skill_trusted", result_summary=f"{name} {e.code_hash[:12]}")
    await request.app.state.runner.load_plugins()
    return {"ok": True}


@router.post("/skills/{name}/enabled")
async def skills_enabled(name: str, body: EnabledIn, request: Request):
    from odie.skills.registry import set_enabled
    set_enabled(request.app.state.store, name, body.enabled)
    await request.app.state.runner.load_plugins()
    return {"ok": True}


@router.get("/mcp")
async def mcp_list(request: Request):
    from odie.plugins.mcp import masked, read_config
    servers, err = read_config()
    live = {e.name: e for e in request.app.state.runner.plugins.get("servers", [])}
    out = []
    for name, spec in servers.items():
        e = live.get(name)
        out.append({"name": name, "spec": masked(spec), "status": e.status if e else "not loaded", "tools": e.tools if e else [],
                    "reason": e.reason if e else "", "alwaysOn": bool(spec.get("alwaysOn")), "enabled": spec.get("enabled", True) is not False,
                    "readsFree": bool(spec.get("readsFree"))})
    return {"servers": out, "error": err}


@router.post("/mcp")
async def mcp_save(body: ServerIn, request: Request):
    from odie.plugins.mcp import NAME_RE, read_config, unmask, write_config
    if not NAME_RE.match(body.name) or not (body.spec.get("url") or body.spec.get("command")):
        raise HTTPException(422, "a lower-case name and a command or url are needed")
    servers, _ = read_config()
    spec = dict(body.spec)
    old = servers.get(body.name) or {}
    try:
        edit = unmask(spec, old)  # masked values coming back keep the real secret
    except ValueError as e:
        raise HTTPException(422, str(e))
    keep = {k: v for k, v in old.items() if k not in (("command", "args", "env") if edit.get("url") else ("url", "headers"))}
    servers[body.name] = {**keep, **edit}  # switches (enabled, alwaysOn) and hand-written keys stay
    write_config(servers)
    await request.app.state.runner.load_plugins()
    return {"ok": True}


class CheckIn(BaseModel):
    name: str = ""  # a saved server being edited: its masked values are restored before the check
    spec: dict


class ConnectIn(BaseModel):
    preset: str
    url: str = Field(max_length=2000)
    key: str = Field("", max_length=500)
    check_only: bool = False  # list the tools, save nothing
    add: bool = False  # another connection to the same service, beside the one there


async def _check(spec: dict) -> dict:
    """The server's tools, listed in a throwaway process, and which of them would ask for a tap. A failure's reason is
    scrubbed of the spec's secrets."""
    from odie.plugins import mcp as m
    try:
        listed = await m.probe_tools(spec, 20)
    except Exception as ex:  # noqa: BLE001 (timeouts, refused connections, bad commands, a 401)
        return {"ok": False, "reason": m.scrub(str(ex) or type(ex).__name__, spec)}
    free = bool(spec.get("readsFree"))
    return {"ok": True, "tools": [{"name": t["name"], "read_only": bool(t.get("read_only")), "asks": m.asks(t, free)} for t in listed]}


@router.get("/mcp/presets")
async def mcp_presets() -> list[dict[str, Any]]:
    from odie.plugins.presets import PRESETS
    return [{"id": pid, "title": p["title"], "where": p["where"], "key_label": p["key_label"]} for pid, p in PRESETS.items()]


@router.post("/mcp/check")
async def mcp_check(body: CheckIn) -> dict[str, Any]:
    """Lists a server's tools before it is saved (nothing is saved)."""
    from odie.plugins.mcp import read_config, unmask
    if not (body.spec.get("url") or body.spec.get("command")):
        raise HTTPException(422, "a command or url is needed")
    try:
        spec = unmask(dict(body.spec), (read_config()[0].get(body.name) or {}) if body.name else {})
    except ValueError as e:
        raise HTTPException(422, str(e))
    return await _check(spec)


@router.post("/mcp/connect")
async def mcp_connect(body: ConnectIn, request: Request) -> dict[str, Any]:
    """Zapier or Composio from the link (and key) the user pasted: checked, then saved and loaded. Connecting the same
    service again replaces its connection (a new link, a new code), keeping its switches; add=True adds another."""
    from odie.plugins import presets
    from odie.plugins.mcp import read_config, write_config
    try:
        spec = presets.spec_for(body.preset, body.url, body.key)
    except ValueError as e:
        raise HTTPException(422, str(e))
    checked = await _check(spec)
    if not checked["ok"]:
        said = presets.plain_reason(body.preset, checked["reason"])
        raise HTTPException(422, said if said != checked["reason"] else f"{presets.PRESETS[body.preset]['title']} didn't answer: {said}")
    if body.check_only:
        return {"ok": True, "name": None, "tools": checked["tools"]}
    servers, _ = read_config()
    name = next((n for n, sp in servers.items() if isinstance(sp, dict) and sp.get("url") == spec["url"]), None)
    if name is None and not body.add:
        same = [n for n, sp in servers.items() if isinstance(sp, dict) and presets.preset_of(str(sp.get("url") or "")) == body.preset]
        if len(same) > 1:
            title = presets.PRESETS[body.preset]["title"]
            raise HTTPException(409, f"You have two {title} connections ({', '.join(same)}): remove the one you don't use in "
                                     "Settings → Connected apps, then connect again.")
        name = same[0] if same else None
    replaced = name is not None
    name = name or next(n for n in (body.preset, *(f"{body.preset}-{i}" for i in range(2, 100))) if n not in servers)
    old = servers.get(name) or {}
    servers[name] = {**{k: v for k, v in old.items() if k in ("enabled", "alwaysOn", "readsFree")}, **spec}
    write_config(servers)
    await request.app.state.runner.load_plugins()
    return {"ok": True, "name": name, "tools": checked["tools"], "replaced": replaced}


@router.post("/mcp/{name}/reads_free")
async def mcp_reads_free(name: str, body: OnIn, request: Request):
    """The server's "Reading doesn't need a tap" switch (odie.plugins.mcp.asks)."""
    return await _mcp_flag(request, name, "readsFree", body.on)


@router.post("/mcp/{name}/enabled")
async def mcp_enabled(name: str, body: EnabledIn, request: Request):
    return await _mcp_flag(request, name, "enabled", body.enabled)


@router.post("/mcp/{name}/always_on")
async def mcp_always_on(name: str, body: OnIn, request: Request):
    return await _mcp_flag(request, name, "alwaysOn", body.on)


async def _mcp_flag(request: Request, name: str, key: str, value: bool):
    from odie.plugins.mcp import read_config, write_config
    servers, _ = read_config()
    if name not in servers:
        raise HTTPException(404, "no such server")
    servers[name][key] = value
    write_config(servers)
    await request.app.state.runner.load_plugins()
    return {"ok": True}


@router.delete("/mcp/{name}")
async def mcp_delete(name: str, request: Request):
    from odie.plugins.mcp import read_config, write_config
    servers, _ = read_config()
    if servers.pop(name, None) is None:
        raise HTTPException(404, "no such server")
    write_config(servers)
    await request.app.state.runner.load_plugins()
    return {"ok": True}


@router.post("/plugins/reload")
async def plugins_reload(request: Request):
    p = await request.app.state.runner.load_plugins()
    return {"skills": [_skill_json(e) for e in p["skills"]], "servers": [{"name": e.name, "status": e.status, "reason": e.reason} for e in p["servers"]]}


@router.get("/news")
async def news(request: Request):
    from odie.news import fetch as nf
    return nf.news_batch(request.app.state.store)


@router.post("/news/refresh")
async def news_refresh(request: Request):
    from odie.news import fetch as nf
    return await nf.refresh_news(request.app.state.store)


class SnoozeIn(BaseModel):
    until: str


async def _publish(request: Request, event: dict) -> None:
    bus = getattr(request.app.state, "bus", None)
    if bus:
        await bus.publish(event)


def _notice(row) -> dict:
    """A fired reminder as the app shows it on the curtain."""
    from odie.jobs.reminders import phrase
    media = json.loads(row["notice_media"]) if row["notice_media"] else None
    return {"id": row["id"], "text": phrase(row), "kind": row["kind"], "delivered_at": row["delivered_at"], **({"media": media} if media else {})}


@router.get("/reminders/pending")
async def reminders_pending(request: Request):
    """Reminders that fired and nobody has answered: the app shows them as curtains when it opens, oldest first."""
    return [_notice(r) for r in request.app.state.store.pending_notices()]


@router.post("/reminders/{task_id}/act")
async def reminder_act(task_id: int, request: Request):
    """Act on a reminder: it lands in the chat as Odie's message (with its spoken memo when there is one), the curtain
    is done with it, and a timed ping closes; a follow-up stays open for the user."""
    store = request.app.state.store
    row = store.one("select * from tasks where id=?", (task_id,))
    if not row:
        raise HTTPException(404, "No such reminder.")
    notice = _notice(row)
    ev = await request.app.state.runner.post_message(notice["text"], media=notice.get("media"))
    store.mark_seen(task_id)
    if row["kind"] == "reminder" and not row["snoozed_until"]:
        store.update_task(task_id, status="done")
    await _publish(request, {"type": "task", "id": task_id})
    return {"ok": True, "session_id": getattr(ev, "session_id", None), "text": notice["text"]}


@router.post("/reminders/{task_id}/dismiss")
async def reminder_dismiss(task_id: int, request: Request):
    """Dismiss a reminder's curtain: it stays open on Today under Now, for the user to tick off there."""
    store = request.app.state.store
    if not store.one("select id from tasks where id=?", (task_id,)):
        raise HTTPException(404, "No such reminder.")
    store.mark_seen(task_id)
    return {"ok": True}


@router.post("/tasks/{task_id}/done")
async def task_done(task_id: int, request: Request):
    store = request.app.state.store
    row = store.one("select * from tasks where id=?", (task_id,))
    if row is None:
        raise HTTPException(404, "no such task")
    store.update_task(task_id, status="done")
    note = ""
    if row["source_kind"]:
        from odie.agent.agent import source_done
        note = await source_done(row["source_kind"], row["source_ref"]) or ""
    store.audit("user", "task_done", result_summary=row["title"], approval_id=None)
    await _publish(request, {"type": "task", "id": task_id, "status": "done"})
    return {"ok": True, "ledger": note}


@router.post("/tasks/{task_id}/snooze")
async def task_snooze(task_id: int, body: SnoozeIn, request: Request):
    from zoneinfo import ZoneInfo

    from odie.agent.tools.local import parse_when
    store = request.app.state.store
    if store.one("select id from tasks where id=?", (task_id,)) is None:
        raise HTTPException(404, "no such task")
    until = parse_when(body.until, ZoneInfo(config.settings.timezone))
    if not until:
        raise HTTPException(422, "until must be an ISO datetime")
    store.snooze_task(task_id, until)
    await _publish(request, {"type": "task", "id": task_id, "status": "snoozed", "until": until})
    return {"ok": True, "until": until}


PING_EVERY = 25  # seconds between pings on the live stream


@router.get("/events")
async def events(request: Request):
    """Live stream: pings, Odie-originated messages, task changes. A device removed while its stream is open loses it
    at the next event or ping."""
    bus = getattr(request.app.state, "bus", None)
    store, key = request.app.state.store, request.cookies.get(devices.COOKIE)

    def still_in() -> bool:
        return not devices.pairing_on(store) or devices.device_for(store, key) is not None

    async def gen():
        if bus is None:
            while still_in() and not await request.is_disconnected():
                yield {"data": json.dumps({"type": "ping"})}
                await asyncio.sleep(PING_EVERY)
            return
        q = bus.queue()
        try:
            while still_in() and not await request.is_disconnected():
                try:
                    e = await asyncio.wait_for(q.get(), PING_EVERY)
                    yield {"data": json.dumps(e, default=str)}
                except asyncio.TimeoutError:
                    yield {"data": json.dumps({"type": "ping"})}
        finally:
            bus.release(q)
    return EventSourceResponse(gen(), sep="\n")


@router.get("/push/public-key")
async def push_public_key(request: Request):
    return {"publicKey": request.app.state.vapid_public_key}


@router.post("/push/test")
async def push_test(request: Request):
    from odie.push.send import send_to_all
    from odie import persona
    n = send_to_all(request.app.state.store, persona.get(request.app.state.store)["name"], "Connected to this phone. Reminders and briefs will land here.", url="/#settings", tag="test")
    return {"sent": n}


# --- Mac apps: Mail, Calendar, Reminders and Contacts on this Mac, and the permission macOS asks for each ---
class CalendarIn(BaseModel):
    name: str


def _mac_view(store) -> dict:
    from odie.mac import calendar as mac_calendar
    from odie.mac import permissions, scripts
    on_mac = scripts.available()
    return {"mac": on_mac, "apps": [r.as_dict() for r in permissions.rows()] if on_mac else [],
            "default_calendar": mac_calendar.chosen(store)}


@router.get("/mac/apps")
async def mac_apps(request: Request) -> dict:
    """Each Mac app with whether Odie may read it (granted, denied, unknown), and the calendar events go into."""
    return _mac_view(request.app.state.store)


@router.post("/mac/apps/{app_id}/allow")
async def mac_apps_allow(app_id: str, request: Request) -> dict:
    """Asks macOS for the app: its dialog appears on this Mac's screen; the answer comes back with the rows. A grant
    or a refusal makes the watch find its sources again."""
    from odie.mac import permissions, scripts
    from odie.watch import sources
    if not scripts.available():
        raise HTTPException(400, "This Odie isn't on a Mac.")
    if app_id not in permissions.APPS:
        raise HTTPException(404, "no such app")
    await permissions.request(app_id)
    sources.forget(request.app.state.store)
    return _mac_view(request.app.state.store)


@router.get("/mac/calendars")
async def mac_calendars(request: Request) -> dict:
    """The Mac's calendars events may go into (opens Calendar if it isn't running), for the Settings picker."""
    from odie.mac import calendar as mac_calendar
    from odie.mac import permissions, scripts
    if not scripts.available() or permissions.status("calendar") != permissions.GRANTED:
        return {"calendars": []}
    try:
        return {"calendars": await mac_calendar.calendars()}
    except scripts.MacError as e:
        raise HTTPException(502, str(e)) from None


@router.put("/mac/calendar")
async def mac_calendar_choose(body: CalendarIn, request: Request) -> dict:
    """The calendar events Odie adds go into ("" = the first writable one)."""
    from odie.mac import calendar as mac_calendar
    request.app.state.store.set_setting(mac_calendar.SETTING, body.name.strip()[:120])
    return {"ok": True, "default_calendar": body.name.strip()[:120]}


@router.get("/capabilities")
async def capabilities_get(request: Request) -> dict[str, Any]:
    """What this install can do (the web app shows only what's there), and each add-on's state."""
    from odie import addons, capabilities
    servers = getattr(request.app.state.runner, "plugins", {}).get("servers", [])
    from odie import voice
    caps = set(capabilities.detect(servers, request.app.state.store))
    if voice.dictation_available():
        caps.add("dictation")  # live dictation through OpenAI; without it the phone uses its own, or says what's missing
    if voice.dictation_available() and not voice.TALK_HELD_BACK:
        caps.add("talk")       # the Speak button: a live conversation through OpenAI (held back for now)
    from odie import update
    if update.can_update():
        caps.add("update")  # this is the installed copy: the app can check for and start an update
    return {"caps": sorted(caps), "country": config.settings.country,
            "addons": [{"name": f.name, "status": f.status, "reason": f.reason} for f in addons.found()]}


# --- Notes: the vault folder, its index and how indexing is going ---
class VaultIn(BaseModel):
    dir: str | None = None
    ignore: list[str] | None = None
    embeddings: dict | None = None  # {"provider", "model"}; null switches meaning search off; leave it out to keep it


def _vault_view(request: Request) -> dict:
    from odie.vault import settings
    store = request.app.state.store
    ix = settings.index_for(store)
    worker = getattr(request.app.state, "vault_worker", None)
    return {"settings": settings.get(store), "status": ix.status() if ix else None, "memory_file": str(config.settings.memory_file),
            "progress": worker.progress() if worker else {"running": False, "done": 0, "total": 0, "phase": "idle", "error": ""}}


@router.get("/vault")
async def vault_get(request: Request) -> dict[str, Any]:
    return _vault_view(request)


@router.put("/vault")
async def vault_put(body: VaultIn, request: Request) -> dict[str, Any]:
    """Set the folder, the folders to leave out, and the embedding model (checked by embedding one sentence first)."""
    from odie.vault import embed, settings
    store = request.app.state.store
    fields = body.model_dump(exclude_unset=True)
    if fields.get("embeddings"):
        e = fields["embeddings"]
        try:
            await embed.check(embed.make_embedder(str(e.get("provider", "")), str(e.get("model", "")), store))
        except embed.EmbedError as err:
            raise HTTPException(422, str(err))
    try:
        settings.put(store, **{k: fields[k] for k in ("dir", "ignore", "embeddings") if k in fields})
    except ValueError as err:
        raise HTTPException(422, str(err))
    store.audit("user", "vault_settings", result_summary=str(settings.get(store)))
    reload = getattr(request.app.state.runner, "reload_vault", None)
    if reload:
        await reload()
    worker = getattr(request.app.state, "vault_worker", None)
    if worker:
        worker.kick()
    return _vault_view(request)


@router.post("/vault/reindex")
async def vault_reindex(request: Request) -> dict[str, Any]:
    worker = getattr(request.app.state, "vault_worker", None)
    if worker:
        worker.kick()
    return {"ok": True}


# --- Photos (odie.photos): the user's Photos library read into the same index, on only when they said yes ---
class PhotosIn(BaseModel):
    on: bool | None = None
    screenshots: bool | None = None


PHOTO_TYPES = {".jpeg": "image/jpeg", ".jpg": "image/jpeg", ".png": "image/png", ".heic": "image/heic", ".gif": "image/gif",
               ".webp": "image/webp", ".tiff": "image/tiff", ".tif": "image/tiff"}


def _photos_view(request: Request) -> dict:
    from odie.photos import settings
    from odie.vault import settings as vault_settings
    store = request.app.state.store
    ix = vault_settings.index_for(store)
    st = ix.status() if ix else None
    status = {k: st[k] for k in ("photos", "videos", "photo_vectors", "photos_at")} if st else None
    worker = getattr(request.app.state, "vault_worker", None)
    embedder = vault_settings.embedder_for(store)
    # how pictures are read by meaning: "gemma" (Odie's own service sees pictures), "text" (an embedder that reads words
    # only), "none" (no embedder set)
    meaning = "none" if embedder is None else ("gemma" if getattr(embedder, "sees_pictures", False) else "text")
    return {"settings": settings.get(store), "status": status, "meaning": meaning,
            "progress": worker.progress() if worker else {"running": False, "done": 0, "total": 0, "phase": "idle", "error": ""}}


@router.get("/photos")
async def photos_get(request: Request) -> dict[str, Any]:
    return _photos_view(request)


@router.put("/photos")
async def photos_put(body: PhotosIn, request: Request) -> dict[str, Any]:
    """Switch reading the Photos library on or off, or include screenshots; the library is read (or forgotten) straight away."""
    from odie.photos import settings
    store = request.app.state.store
    fields = body.model_dump(exclude_unset=True)
    settings.put(store, **{k: fields[k] for k in ("on", "screenshots") if k in fields})
    store.audit("user", "photos_settings", result_summary=str(settings.get(store)))
    reload = getattr(request.app.state.runner, "reload_vault", None)
    if reload:
        await reload()
    worker = getattr(request.app.state, "vault_worker", None)
    if worker:
        worker.kick(photos=True)
    return _photos_view(request)


def _known_photo(request: Request, uuid: str) -> dict:
    from odie.vault import settings as vault_settings
    if not PHOTO_UUID.match(uuid):
        raise HTTPException(404, "no such picture")
    ix = vault_settings.index_for(request.app.state.store)
    row = ix.photo(uuid) if ix else None
    if row is None:
        raise HTTPException(404, "no such picture")
    return row


@router.get("/photos/{uuid}/info")
async def photo_info(uuid: str, request: Request) -> dict[str, Any]:
    """What a picture is (the chat's large view asks): photo or video, when and where, whether a big copy is on this
    Mac, and where its original stands (odie.photos.fetch)."""
    import json as _json

    from odie.photos import fetch
    row = _known_photo(request, uuid)
    return {"uuid": uuid, "kind": row["kind"], "taken": (row["taken"] or "")[:10], "place": row["place"] or "",
            "people": _json.loads(row["people"] or "[]"), "has_big": bool(row["big"] and Path(row["big"]).is_file()),
            "original": fetch.status(uuid)}


@router.get("/photos/{uuid}/fetch")
async def photo_fetch_status(uuid: str, request: Request) -> dict[str, Any]:
    from odie.photos import fetch
    _known_photo(request, uuid)
    return fetch.status(uuid)


@router.post("/photos/{uuid}/fetch")
async def photo_fetch(uuid: str, request: Request) -> dict[str, Any]:
    """Ask Photos to download the original from iCloud (a tap on a video); poll GET until ready, then /original."""
    from odie.photos import fetch
    _known_photo(request, uuid)
    return fetch.start(uuid)


@router.get("/photos/{uuid}/original")
async def photo_original(uuid: str, request: Request):
    """The fetched original, streamed with byte ranges (a video scrubs); 404 until it has been fetched."""
    from fastapi.responses import FileResponse
    from odie.photos import fetch
    _known_photo(request, uuid)
    path = fetch.fetched_file(uuid, fetch.fetched_dir())
    if path is None:
        raise HTTPException(404, "not fetched yet")
    return FileResponse(path, media_type=fetch.media_type(path), headers={"Cache-Control": "private, max-age=86400"})


@router.get("/photos/{uuid}/{size}")
async def photo_file(uuid: str, size: str, request: Request):
    """A picture's small copy (thumb) or its largest one on this Mac (big), by the uuid the index knows. Only files
    the index recorded are served: the uuid must be in it, and the copy must still be there."""
    from fastapi.responses import FileResponse
    from odie.vault import settings as vault_settings
    if size not in ("thumb", "big") or not PHOTO_UUID.match(uuid):
        raise HTTPException(404, "no such picture")
    ix = vault_settings.index_for(request.app.state.store)
    row = ix.photo(uuid) if ix else None
    path = Path(row[size]) if row and row.get(size) else None
    if path is None or not path.is_file():
        raise HTTPException(404, "no copy of that picture on this computer")
    media_type = PHOTO_TYPES.get(path.suffix.lower(), "application/octet-stream")
    return FileResponse(path, media_type=media_type, headers={"Cache-Control": "private, max-age=86400"})


# --- Signed-in browsing (odie.signin): off by default, on only with the risks accepted; turning it off signs out ---
class SignInIn(BaseModel):
    accepted: bool = False
    version: int = 0


class UpiIn(BaseModel):
    upi_id: str = ""


def _signin_view(store) -> dict:
    from odie.signin import state
    return {**state.get(store), "version": state.VERSION, "disclaimer": state.DISCLAIMER, "upi_id": state.upi_id(store)}


def _sites_view(store) -> dict:
    from odie.signin import sites
    return {"sites": sites.listing(store)}


def _signin_needed(store) -> None:
    from odie.signin import state
    if not state.is_on(store):
        raise HTTPException(403, "Signed-in browsing is off")


async def _sign_out(store, domains: list[str] | None) -> str | None:
    """Clear Odie's browser's cookies and storage: these sites', or everything (None). The reason, if it couldn't."""
    from odie.browser import shared
    from odie.signin import sites
    try:
        await shared().sign_out(domains, origins=[o for d in domains or () for o in sites.origins_of(store, d)])
    except Exception as e:  # noqa: BLE001
        log.warning("browser sign-out failed", exc_info=True)
        return f"Odie's browser couldn't sign out ({type(e).__name__}). Try again in a moment."
    return None


async def _reload_signin(request: Request) -> None:
    reload = getattr(request.app.state.runner, "reload_signin", None)
    if reload:
        await reload()  # the sign-in tool and its rules come and go with the switch


@router.get("/browser/signin")
async def signin_get(request: Request) -> dict[str, Any]:
    return _signin_view(request.app.state.store)


@router.post("/browser/signin")
async def signin_turn_on(body: SignInIn, request: Request) -> dict[str, Any]:
    from datetime import datetime

    from odie.signin import state
    store = request.app.state.store
    try:
        state.turn_on(store, accepted=body.accepted, version=body.version, now=datetime.now().astimezone())
    except ValueError as err:
        raise HTTPException(422, str(err))
    await _reload_signin(request)
    return _signin_view(store)


@router.post("/browser/signin/off")
async def signin_turn_off(request: Request) -> dict[str, Any]:
    """Off signs out of everything first; it goes off even if the browser can't be reached (and says so)."""
    from odie.signin import state
    store = request.app.state.store
    live = getattr(request.app.state, "live", None)
    if live is not None:
        await live.close("off")  # no one keeps driving a signed-in tab with it off
    problem = await _sign_out(store, None)
    state.turn_off(store)
    await _reload_signin(request)
    return {**_signin_view(store), **({"warning": problem} if problem else {})}


@router.get("/browser/sites")
async def signin_sites(request: Request) -> dict[str, Any]:
    _signin_needed(request.app.state.store)
    return _sites_view(request.app.state.store)


@router.post("/browser/sites/{domain}/signout")
async def signin_site_sign_out(domain: str, request: Request) -> dict[str, Any]:
    from odie.signin import sites, vault
    store = request.app.state.store
    _signin_needed(store)
    site = sites.site_of(domain)
    if site not in {s["domain"] for s in sites.listing(store)}:
        raise HTTPException(404, f"Odie isn't signed in to {domain}")
    if problem := await _sign_out(store, [site]):
        raise HTTPException(502, problem)
    sites.remove(store, site)
    vault.delete(store, site)  # else Odie would sign straight back in
    from odie.trackers import signed_in as tracked
    tracked.revoke(store, site, f"You signed out of {site}.")
    store.audit("user", "signin_signed_out", result_summary=site)
    return _sites_view(store)


@router.post("/browser/signout")
async def signin_sign_out_all(request: Request) -> dict[str, Any]:
    from odie.signin import sites, vault
    store = request.app.state.store
    _signin_needed(store)
    if problem := await _sign_out(store, None):
        raise HTTPException(502, problem)
    store.set_setting(sites.KEY, {})
    vault.forget_all(store)
    from odie.trackers import signed_in as tracked
    tracked.revoke(store, None, "You signed out of every site.")
    store.audit("user", "signin_signed_out", result_summary="everything")
    return _sites_view(store)


TAB_NAME = re.compile(r"[A-Za-z0-9._-]{1,80}")


@router.websocket("/browser/live/{tab}")
async def live_view(tab: str, websocket: WebSocket) -> None:
    """The live view (odie.signin.live): frames out, the user's taps and typing in. Behind pairing, like every API."""
    from odie.signin import state
    if not state.is_on(websocket.app.state.store) or not TAB_NAME.fullmatch(tab):
        await websocket.close(code=4403)  # signed-in browsing is off: there's no live view
        return
    await websocket.accept()
    await websocket.app.state.live.serve(tab, websocket)


async def _live_finish(tab: str, request: Request, done: bool) -> dict[str, Any]:
    _signin_needed(request.app.state.store)
    try:
        return await request.app.state.live.finish(tab, done)
    except LookupError:
        raise HTTPException(404, "Nothing is live on that tab")


@router.post("/browser/live/{tab}/done")
async def live_done(tab: str, request: Request) -> dict[str, Any]:
    return await _live_finish(tab, request, True)


@router.post("/browser/live/{tab}/cancel")
async def live_cancel(tab: str, request: Request) -> dict[str, Any]:
    return await _live_finish(tab, request, False)


@router.put("/browser/upi")
async def upi_put(body: UpiIn, request: Request) -> dict[str, Any]:
    """The UPI ID for payment collect requests (spec Part 4): a payment setting, never a memory."""
    from odie.signin import state
    store = request.app.state.store
    try:
        state.set_upi_id(store, body.upi_id)
    except ValueError as err:
        raise HTTPException(422, str(err))
    return _signin_view(store)


class LoginIn(BaseModel):
    site: str = ""
    username: str = ""
    password: str = ""
    remember: bool = True


class CodeIn(BaseModel):
    code: str = ""


def _logins_view(store) -> dict:
    from odie.signin import vault
    return {"logins": vault.listing(store)}


@router.post("/browser/sign-in/{tab}")
async def sign_in_box(tab: str, body: LoginIn, request: Request) -> dict[str, Any]:
    """Odie's own sign-in box: the login goes to Odie's browser, never to the AI (odie.signin.box)."""
    from odie.browser.engine import BrowserError
    store = request.app.state.store
    _signin_needed(store)
    if not TAB_NAME.fullmatch(tab):
        raise HTTPException(404, "No such tab")
    if not body.username.strip() or not body.password or not body.site.strip():
        raise HTTPException(422, "Type the username and the password.")
    try:
        return await request.app.state.signin_box.submit(tab, body.site, body.username.strip(), body.password, body.remember)
    except BrowserError as e:
        raise HTTPException(409, str(e))


@router.post("/browser/sign-in/{tab}/code")
async def sign_in_code(tab: str, body: CodeIn, request: Request) -> dict[str, Any]:
    from odie.browser.engine import BrowserError
    _signin_needed(request.app.state.store)
    if not body.code.strip():
        raise HTTPException(422, "Type the code.")
    try:
        return await request.app.state.signin_box.code(tab, body.code)
    except BrowserError as e:
        raise HTTPException(409, str(e))


@router.get("/browser/logins")
async def logins_list(request: Request) -> dict[str, Any]:
    _signin_needed(request.app.state.store)
    return _logins_view(request.app.state.store)


@router.post("/browser/logins")
async def logins_add(body: LoginIn, request: Request) -> dict[str, Any]:
    from datetime import datetime

    from odie.signin import vault
    store = request.app.state.store
    _signin_needed(store)
    try:
        vault.save(store, body.site, body.username, body.password, datetime.now().astimezone())
    except ValueError as err:
        raise HTTPException(422, str(err))
    except vault.VaultError as err:
        raise HTTPException(502, str(err))
    return _logins_view(store)


@router.delete("/browser/logins/{site}")
async def logins_delete(site: str, request: Request) -> dict[str, Any]:
    from odie.signin import vault
    store = request.app.state.store
    _signin_needed(store)
    if not vault.delete(store, site):
        raise HTTPException(404, f"No saved login for {site}")
    from odie.signin import sites
    from odie.trackers import signed_in as tracked
    tracked.revoke(store, site, f"The saved login for {sites.site_of(site)} was deleted.")
    return _logins_view(store)


@router.post("/browser/logins/forget")
async def logins_forget(request: Request) -> dict[str, Any]:
    from odie.signin import vault
    store = request.app.state.store
    _signin_needed(store)
    vault.forget_all(store)
    from odie.trackers import signed_in as tracked
    tracked.revoke(store, None, "Your saved logins were deleted.")
    return _logins_view(store)


# --- Setup: the checklist and the setup conversation (keys go to the key routes, never here) ---
class SetupChatIn(BaseModel):
    text: str


class SetupEventIn(BaseModel):
    kind: str
    provider: str = ""


class SetupStepIn(BaseModel):
    step: str


class SetupChooseIn(BaseModel):
    step: str
    choice: str
    value: Any = None


@router.get("/setup")
async def setup_get(request: Request) -> dict[str, Any]:
    from odie.setup import chat
    return await chat.view(request.app.state.store)


@router.get("/setup/panel/{step}")
async def setup_panel(step: str, request: Request) -> dict[str, Any]:
    """One step's controls, for Settings to change it after setup (the notes when the vault was skipped)."""
    from odie.setup import panels, state
    if step not in state.STEPS or step == "brain":
        raise HTTPException(404, "no such step")
    return await panels.panel(request.app.state.store, step)


@router.post("/setup/choose")
async def setup_choose(body: SetupChooseIn, request: Request) -> dict[str, Any]:
    """A choice made on the setup screen: saved by code, and Odie's next line comes back."""
    from odie.setup import chat
    try:
        out = await chat.choose(request.app.state.store, body.step, body.choice, body.value, runner=request.app.state.runner)
    except ValueError as e:
        raise HTTPException(422, str(e))
    invalidate = getattr(request.app.state.runner, "invalidate_prompt", None)
    if invalidate:
        invalidate()  # names and settings may have changed
    return out


@router.post("/setup/brain")
async def setup_brain(request: Request) -> dict[str, Any]:
    """The brain step is done: a model was chosen (and checked)."""
    from odie.setup import chat, state
    state.mark(request.app.state.store, "brain", "done")
    return chat.public_state(request.app.state.store)


@router.post("/setup/chat")
async def setup_chat(body: SetupChatIn, request: Request) -> dict[str, Any]:
    from odie.setup import chat
    out = await chat.turn(request.app.state.store, body.text[:4000], runner=request.app.state.runner)
    invalidate = getattr(request.app.state.runner, "invalidate_prompt", None)
    if invalidate:
        invalidate()  # names and settings may have changed
    return out


@router.post("/setup/event")
async def setup_event(body: SetupEventIn, request: Request) -> dict[str, Any]:
    from odie.setup import chat
    try:
        out = await chat.event(request.app.state.store, body.kind, body.provider, runner=request.app.state.runner)
    except ValueError as e:
        raise HTTPException(422, str(e))
    invalidate = getattr(request.app.state.runner, "invalidate_prompt", None)
    if invalidate:
        invalidate()
    return out


@router.post("/setup/skip")
async def setup_skip(body: SetupStepIn, request: Request) -> dict[str, Any]:
    from odie.setup import chat, state
    if body.step not in state.SKIPPABLE:
        raise HTTPException(422, "The brain and the names can't be skipped.")
    state.mark(request.app.state.store, body.step, "skipped")
    return chat.public_state(request.app.state.store)


@router.post("/setup/finish")
async def setup_finish(request: Request) -> dict[str, Any]:
    from odie.setup import chat, tools
    out = await tools.run("finish_setup", {}, request.app.state.store)
    if "error" in out:
        raise HTTPException(422, out["error"])  # never finished over steps left to do
    return chat.public_state(request.app.state.store)


@router.post("/setup/leave")
async def setup_leave(request: Request) -> dict[str, Any]:
    """Leave setup that was run again, keeping everything as it is."""
    from odie.setup import chat, state
    try:
        state.leave(request.app.state.store)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return chat.public_state(request.app.state.store)


@router.post("/setup/restart")
async def setup_restart(request: Request) -> dict[str, Any]:
    from odie.setup import chat, state
    state.restart(request.app.state.store)
    return chat.public_state(request.app.state.store)


# --- The brain check: try a model on what Odie needs before it becomes the brain ---
class BrainCheckIn(BaseModel):
    provider: str
    model: str


@router.post("/brain/check")
async def brain_check_run(body: BrainCheckIn, request: Request) -> dict[str, Any]:
    """About 30 seconds: tool calls, using a result, speed, context. The last report per model is kept."""
    from dataclasses import asdict

    from odie import brain_check
    from odie.models import Selection
    store = request.app.state.store
    providers = {p.id: p for p in all_providers(store)}
    if body.provider not in providers:
        raise HTTPException(404, "unknown provider")
    try:
        report = asdict(await brain_check.check(Selection(providers[body.provider], body.model, "chat")))
    except Exception as e:  # noqa: BLE001
        log.warning("brain check failed", exc_info=True)
        unknown = [{"name": n, "status": "unknown", "detail": "not checked"} for n in ("tools", "result", "speed", "context")]
        report = {"provider": body.provider, "model": body.model, "verdict": "fail",
                  "sentence": f"{body.model}: Couldn't check it: {type(e).__name__}.", "parts": unknown, "checked_at": ""}
    kept = store.get_setting("brain.checks") or {}
    kept[f"{body.provider}/{body.model}"] = report
    store.set_setting("brain.checks", kept)
    store.audit("user", "brain_check", result_summary=report["sentence"][:200])
    return report


@router.get("/brain/checks")
async def brain_checks(request: Request) -> dict[str, Any]:
    return request.app.state.store.get_setting("brain.checks") or {}


@router.post("/push/subscribe")
async def push_subscribe(sub: SubscriptionIn, request: Request):
    me = _device(request)  # removing the device ends its pushes
    created = request.app.state.store.add_subscription(sub.endpoint, sub.keys.p256dh, sub.keys.auth, me["id"] if me else None)
    return {"created": created}


# --- Voice: OpenAI read-aloud, dictation and realtime talk ---
class VoiceIn(BaseModel):
    voice: str | None = None
    engine: str | None = None
    reminders_spoken: bool | None = None


class TtsIn(BaseModel):
    text: str


class AskIn(BaseModel):
    question: str


def _voice_guard():
    from odie import voice
    try:
        return voice.api_key()
    except voice.VoiceUnavailable as e:
        raise HTTPException(503, str(e))


def _speakable(text: str) -> str:
    """Markdown to plain speech: drop symbols that would be read out."""
    import re
    t = re.sub(r"```.*?```", " ", text, flags=re.S)
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
    return re.sub(r"[*_#`>|]+", "", t).strip()


@router.get("/voice")
async def voice_get(request: Request):
    from odie import machine, voice
    from odie.secrets import load_secret
    store = request.app.state.store
    engine, current = voice.get_tts(store)
    openai_ok = bool(load_secret("OPENAI_API_KEY"))
    local_ok = await voice.local_available() if machine.local_voice_wanted() else False  # not asked for where it can't run
    hidden = voice.disabled()
    engines = [{"id": k, **v, "available": local_ok if v["local"] else openai_ok, "voices": voice.engine_voices(k)}
               for k, v in voice.ENGINES.items() if k not in hidden and (v["local"] or openai_ok)]  # OpenAI only with its key
    # local_voice: whether Odie's own voice is meant to run on this Mac at all (False on an Intel Mac: Settings says why)
    return {"available": openai_ok, "engine": engine, "voice": current, "talk_voice": voice.get_voice(store), "engines": engines,
            "local_voice": machine.local_voice_wanted(),
            "reminders_spoken": voice.reminders_spoken(store),
            "voices": voice.VOICES, "models": {"tts": voice.TTS_MODEL, "stt": voice.STT_MODEL, "realtime": voice.REALTIME_MODEL}}


@router.put("/voice")
async def voice_put(body: VoiceIn, request: Request):
    from odie import voice
    store = request.app.state.store
    engine, v = voice.set_tts(store, body.engine, body.voice)
    if engine == "openai" and body.voice:
        voice.set_voice(store, body.voice)  # an OpenAI voice is also Talk's voice
    if body.reminders_spoken is not None:
        voice.set_reminders_spoken(store, body.reminders_spoken)
    return {"engine": engine, "voice": v, "reminders_spoken": voice.reminders_spoken(store)}


async def _preview(request: Request, engine: str, voice_id: str) -> Response:
    from odie import persona, voice
    if engine not in voice.ENGINES or engine in voice.disabled() or voice_id not in {v["id"] for v in voice.engine_voices(engine)}:
        raise HTTPException(404, "no such voice")
    from odie import profile
    name = persona.get(request.app.state.store)["name"]
    user = profile.get(request.app.state.store)["user_name"]
    folder = config.settings.data_dir / "voice"
    folder.mkdir(parents=True, exist_ok=True)
    ext = "mp3" if engine == "openai" else "wav"
    path = folder / f"preview-{engine}-{voice_id}-{slug(name)}-{slug(user or 'you')}.{ext}"  # a rename makes a new one
    if not path.exists():
        hi = f"Hi {user}" if user else "Hi"
        line = (f"{hi}! <laugh> I'm {name}. This is how I sound when I read to you." if engine == "maya1"
                else f"{hi}, I'm {name}. This is how I'll sound when I read to you.")
        try:
            if engine == "openai":
                audio = await voice.tts(line, voice_id, key=_voice_guard())
            else:
                audio = await voice.local_tts(engine, line, voice_id)
        except voice.VoiceUnavailable as e:
            raise HTTPException(503, str(e))
        except httpx.HTTPError as e:
            raise HTTPException(502, f"{engine} preview failed: {type(e).__name__}")
        path.write_bytes(audio)
    return Response(path.read_bytes(), media_type="audio/mpeg" if ext == "mp3" else "audio/wav", headers={"Cache-Control": "public, max-age=86400"})


@router.get("/voice/preview/{voice_id}")
async def voice_preview(voice_id: str, request: Request):
    return await _preview(request, "openai", voice_id)


@router.get("/voice/preview/{engine}/{voice_id}")
async def voice_preview_engine(engine: str, voice_id: str, request: Request):
    return await _preview(request, engine, voice_id)


@router.post("/tts")
async def tts_route(body: TtsIn, request: Request):
    from odie import voice
    engine, _ = voice.get_tts(request.app.state.store)
    if engine == "openai":
        _voice_guard()
    text = _speakable(body.text)
    if not text:
        raise HTTPException(400, "nothing to say")
    try:
        audio, media = await voice.speak(request.app.state.store, text)
    except voice.VoiceUnavailable as e:
        raise HTTPException(503, str(e))
    except httpx.HTTPError as e:
        raise HTTPException(502, f"{engine} speech failed: {type(e).__name__}")
    return Response(audio, media_type=media)


@router.post("/stt")
async def stt_route(file: UploadFile = File(...)):
    from odie import voice
    key = _voice_guard()
    data = await file.read()
    if not data:
        raise HTTPException(400, "empty recording")
    try:
        text = await voice.stt(data, file.filename or "speech.webm", file.content_type or "audio/webm", key=key)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"OpenAI transcription failed: {type(e).__name__}")
    return {"text": text}


def _talk_guard() -> None:
    """Talk is held back for now: its session endpoint says so instead of minting a key."""
    from odie import voice
    if voice.TALK_HELD_BACK:
        raise HTTPException(503, "Talk isn't available in this version of Odie.")


@router.post("/voice/dictation")
async def voice_dictation(request: Request):
    """A short-lived secret for live dictation (a transcription-only realtime session): the phone shows the words as
    the user talks. 503 without an OpenAI key, so the app falls back before anyone speaks."""
    from odie import voice
    key = _voice_guard()
    try:
        return await voice.dictation_session(key=key)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"OpenAI realtime failed: {type(e).__name__}")


@router.post("/voice/session")
async def voice_session(request: Request):
    """A short-lived realtime client secret for the phone, with Odie's persona and today's context."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from odie import voice
    key = _voice_guard()
    _talk_guard()
    runner = request.app.state.runner
    context = ""
    prep = getattr(runner, "_prepare_prompt", None)
    if prep:
        today = datetime.now(ZoneInfo(config.settings.timezone)).strftime("%Y-%m-%d")
        context = prep(runner.current_session_id(today), "")
    soul = runner.load_soul() if hasattr(runner, "load_soul") else None
    try:
        caps = runner.who().caps if hasattr(runner, "who") else None
        out = await voice.realtime_session(request.app.state.store, context=context, soul=soul, key=key, caps=caps)
    except httpx.HTTPError as e:
        raise HTTPException(502, f"OpenAI realtime failed: {type(e).__name__}")
    request.app.state.store.audit("user", "voice_session", result_summary=f"{out['model']} {out['voice']}")
    return out


@router.post("/voice/ask")
async def voice_ask(body: AskIn, request: Request):
    """The realtime model's one tool: a normal Odie turn (tools, approvals, memory), in a short voice session of its own
    (the day's long chat made each answer take 30-40 s). The call's transcript is saved to the chat when it ends."""
    from datetime import datetime
    from zoneinfo import ZoneInfo
    question = (body.question or "").strip()
    if len(question) < 3:
        return {"text": "I didn't get a question. Ask them to say it again."}
    today = datetime.now(ZoneInfo(config.settings.timezone)).strftime("%Y-%m-%d")
    final, cards = "", 0
    async for ev in request.app.state.runner.chat(question, session_id=f"voice-{today}"):
        if ev.get("type") == "done":
            final = ev.get("text", "")
        elif ev.get("type") == "approval":
            cards += 1
        elif ev.get("type") == "error":
            final = f"That didn't work: {ev.get('message', '')}"
    if cards:
        final = (final + " " if final else "") + f"There is {'an approval card' if cards == 1 else f'{cards} approval cards'} waiting in the app."
    return {"text": final or "Done."}


class TranscriptLine(BaseModel):
    who: str
    text: str


class TranscriptIn(BaseModel):
    lines: list[TranscriptLine]
    started_at: float | None = None


@router.post("/voice/transcript")
async def voice_transcript(body: TranscriptIn, request: Request):
    """When a Talk call ends, save what was said into today's chat as one message."""
    from odie import persona
    lines = [x for x in body.lines if x.text.strip()][-60:]
    if not lines:
        return {"saved": False}
    name = persona.get(request.app.state.store)["name"]
    text = "**Talk**\n\n" + "\n\n".join(f"**{'You' if x.who == 'you' else name}:** {x.text.strip()}" for x in lines)
    await request.app.state.runner.post_message(text)
    return {"saved": True}


# --- Persona: the assistant's name and picture ---
class PersonaIn(BaseModel):
    name: str


def _persona_out(p: dict) -> dict:
    return {"name": p["name"], "avatar_url": f"/api/persona/avatar/{p['avatar']}" if p.get("avatar") else None}


@router.get("/persona")
async def persona_get(request: Request):
    from odie import persona
    return _persona_out(persona.get(request.app.state.store))


@router.put("/persona")
async def persona_put(body: PersonaIn, request: Request):
    from odie import persona
    p = persona.set_name(request.app.state.store, body.name)
    inv = getattr(request.app.state.runner, "invalidate_prompt", None)
    if inv:
        inv()
    request.app.state.store.audit("user", "persona_renamed", result_summary=p["name"])
    return _persona_out(p)


@router.post("/persona/avatar")
async def persona_avatar(request: Request, file: UploadFile = File(...)):
    from odie import persona
    data = await file.read()
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(413, "Photo too large (15 MB max)")
    try:
        p = persona.save_avatar(request.app.state.store, data)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Not an image I can read: {type(e).__name__}")
    return _persona_out(p)


@router.delete("/persona/avatar")
async def persona_avatar_clear(request: Request):
    from odie import persona
    return _persona_out(persona.clear_avatar(request.app.state.store))


@router.get("/persona/avatar/{aid}")
async def persona_avatar_file(aid: str):
    from fastapi.responses import FileResponse
    from odie import persona
    path = persona.avatar_path(aid)
    if path is None:
        raise HTTPException(404, "no such picture")
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "public, max-age=31536000, immutable"})


# --- Profile: the user's name, and where the computer says they are ---
class ProfileIn(BaseModel):
    user_name: str


@router.get("/profile")
async def profile_get(request: Request):
    from odie import profile
    return profile.get(request.app.state.store)


@router.put("/profile")
async def profile_put(body: ProfileIn, request: Request):
    from odie import profile
    p = profile.set_user_name(request.app.state.store, body.user_name)
    inv = getattr(request.app.state.runner, "invalidate_prompt", None)
    if inv:
        inv()  # the next message's prompt uses the new name
    request.app.state.store.audit("user", "profile_saved", result_summary="name")
    return p


# --- SOUL.md: Odie's personality, editable from Settings ---
class SoulIn(BaseModel):
    text: str


@router.get("/soul")
async def soul_get(request: Request):
    """The user's SOUL.md, or (none yet) the default personality with their name and the assistant's filled in."""
    from odie import profile
    custom = SOUL_PATH.exists() and SOUL_PATH.read_text().strip() != ""
    if custom:
        text = SOUL_PATH.read_text()
    else:
        store = request.app.state.store
        text = identity(Who(user=profile.get(store)["user_name"], assistant=persona.get(store)["name"]))
    return {"text": text, "custom": bool(custom), "path": str(SOUL_PATH)}


@router.put("/soul")
async def soul_put(body: SoulIn, request: Request):
    text = body.text.strip()
    if text:
        SOUL_PATH.parent.mkdir(parents=True, exist_ok=True)
        SOUL_PATH.write_text(body.text)
        custom = True
    else:
        SOUL_PATH.unlink(missing_ok=True)
        custom = False
    inv = getattr(request.app.state.runner, "invalidate_prompt", None)
    if inv:
        inv()
    request.app.state.store.audit("user", "soul_updated", result_summary=text[:120])
    return {"ok": True, "custom": custom}


# --- Morning brief ---
@router.get("/background")
async def background_get(request: Request) -> dict[str, Any]:
    """The background agent: running now, the last tick, the next one, and each part's last run, success and error."""
    bg = getattr(request.app.state, "background", None)
    if bg is None:
        return {"running": False, "off": True}
    sched = getattr(request.app.state, "scheduler", None)
    job = sched.get_job("background") if sched else None
    nxt = job.next_run_time.isoformat(timespec="seconds") if job and job.next_run_time else None
    return {**bg.status(), "next_tick": nxt}


class WatchDoneIn(BaseModel):
    ref: str


@router.get("/watch")
async def watch_get(request: Request) -> dict[str, Any]:
    """The watch's card for Today: the last check's line, the needs-you items, the next events, each source's status,
    and how many needs-you items are new since Today was last opened."""
    from odie.watch import report
    store = request.app.state.store
    card = store.get_setting(report.CARD)
    if not card:
        return {"off": "The first check runs a minute after Odie starts.", "needs_you": [], "events": [], "unseen": 0}
    return {**card, "unseen": sum(1 for i in card.get("needs_you", []) if not i.get("done") and not i.get("seen"))}


@router.post("/watch/done")
async def watch_done(body: WatchDoneIn, request: Request) -> dict[str, Any]:
    from odie.watch import report
    store = request.app.state.store
    card = store.get_setting(report.CARD) or {}
    card["needs_you"] = [i for i in card.get("needs_you", []) if i.get("ref") != body.ref]
    store.set_setting(report.CARD, card)
    return {"ok": True}


@router.post("/watch/seen")
async def watch_seen(request: Request) -> dict[str, Any]:
    """Today was opened: everything on the card now has been seen (the count on chat's Back to Today goes)."""
    from odie.watch import report
    store = request.app.state.store
    card = store.get_setting(report.CARD) or {}
    card["needs_you"] = [{**i, "seen": True} for i in card.get("needs_you", [])]
    store.set_setting(report.CARD, card)
    return {"ok": True}


@router.get("/brief")
async def brief_get(request: Request):
    row = request.app.state.store.one("select * from briefs order by id desc limit 1")
    if not row:
        return {"text": None}
    try:
        items = json.loads(row["items_json"] or "{}")
        calendar = (items.get("parts") or {}).get("calendar", items.get("calendar"))
    except (ValueError, AttributeError):
        calendar = None
    # calendar: the raw calendar text the brief was written from (today and tomorrow), None if not connected
    return {"date": row["date"], "text": row["text"], "created_at": row["created_at"], "calendar": calendar}


@router.post("/brief/run")
async def brief_run(request: Request):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from odie.jobs.brief import run_brief
    text = await run_brief(request.app.state.store, datetime.now(ZoneInfo(config.settings.timezone)), push=False)  # The user is looking at it
    return {"text": text}


# --- Approvals ---
class DecideIn(BaseModel):
    approve: bool
    allow_minutes: int | None = None  # run_shell only: also allow this conversation's commands for this long




@router.get("/approvals")
async def approvals_pending(request: Request):
    return [_approval_dict(r) for r in request.app.state.store.pending_approvals()]


@router.get("/approvals/{approval_id}")
async def approval_get(approval_id: int, request: Request):
    r = request.app.state.store.get_approval(approval_id)
    if r is None:
        raise HTTPException(404, "no such approval")
    return _approval_dict(r)


_resuming: set[asyncio.Task] = set()  # strong refs to turns resuming after a tap


def _covered_by_new_pass(card: dict, tapped_id: int, session_id: str) -> bool:
    """The user just tapped 'Allow for 30 min' on one run_shell card: does the new pass cover this other pending card
    too? Yes when it's another run_shell card in the same chat, and its command isn't on the always-ask list.
    Example: tapped #7; pending #8 `du -sh ~` in the same chat -> True; #9 `rm a.txt` in the same chat -> False
    (always asks); a run_shell card from another chat -> False; #7 itself -> False (it's already being approved)."""
    from odie.agent import shell_grant
    if card["id"] == tapped_id:
        return False
    if card["session_id"] != session_id:
        return False
    if card["tool"] != "run_shell":
        return False
    args = card.get("args") or {}
    command = str(args.get("command", ""))
    return shell_grant.always_ask(command) is None


@router.post("/approvals/{approval_id}/decide")
async def approval_decide(approval_id: int, body: DecideIn, request: Request):
    """Answer at once so the card collapses; the paused turn resumes in its own task (it can take minutes) and
    reports through the live stream (approval, message, approval_done)."""
    row = request.app.state.store.get_approval(approval_id)
    if row is None:
        raise HTTPException(404, "no such approval")
    if row["status"] != "pending":
        raise HTTPException(409, f"already {row['status']}")
    out: dict[str, Any] = {"status": "approved" if body.approve else "rejected"}
    if body.approve and body.allow_minutes and row["tool"] == "run_shell":
        from datetime import datetime

        from odie.agent import shell_grant
        minutes = max(1, min(body.allow_minutes, shell_grant.GRANT_MINUTES))
        until = shell_grant.grant(request.app.state.store, row["session_id"], datetime.now(), minutes)
        request.app.state.store.audit("user", "shell_allowed", tool="run_shell", result_summary=f"until {until:%H:%M}",
                                      session_id=row["session_id"], approval_id=approval_id)
        out["allowed_until"] = until.isoformat()
        # Cards asked in the same step as this one (parallel tool calls) were raised before the grant existed:
        # approve those too, unless they are on the always-ask list.
        pending = [_approval_dict(r) for r in request.app.state.store.pending_approvals()]
        out["also_approved"] = [card["id"] for card in pending if _covered_by_new_pass(card, approval_id, row["session_id"])]

    async def resume_in_order() -> None:
        runner = request.app.state.runner
        await runner.resume_approval(approval_id, body.approve)
        for other in out.get("also_approved", []):
            await runner.resume_approval(other, True)  # one at a time, as if tapped in turn
    task = asyncio.create_task(resume_in_order())
    _resuming.add(task)
    task.add_done_callback(_resuming.discard)
    return out


# --- Models: providers and the one model ---
class SelectionIn(BaseModel):
    slot: str
    provider: str
    model: str


class ProviderIn(BaseModel):
    name: str
    base_url: str
    api_key: str | None = None
    reasoning: str | None = None  # older clients still send it; litellm knows how each model thinks


def _creativity(store) -> dict:
    """The chat temperature as Settings → Brain shows it: the value, and the slider's range."""
    from odie import sampling
    return {"value": sampling.chat_temperature(store), "default": sampling.CHAT_TEMPERATURE_DEFAULT,
            "min": sampling.CHAT_TEMPERATURE_MIN, "max": sampling.CHAT_TEMPERATURE_MAX, "step": sampling.CHAT_TEMPERATURE_STEP}


@router.get("/models")
async def models_get(request: Request):
    store = request.app.state.store
    providers = all_providers(store)
    listed = await list_models(providers)
    r = resolve_selection(store, "chat")
    row = next((p for p in listed if p["id"] == r.provider.id), None)
    reachable = row is not None and row["error"] is None
    chat = {"provider": r.provider.id, "model": r.model, "leaves_mini": r.leaves_mini,
            "chosen": brain_chosen(store), "reachable": reachable}
    return {"providers": listed, "selection": {"chat": chat}, "creativity": _creativity(store)}


class CreativityIn(BaseModel):
    temperature: float = Field(ge=0.0, le=1.2)


@router.put("/models/creativity")
async def models_creativity(body: CreativityIn, request: Request):
    """Settings → Brain → Creativity: the temperature for chat turns, used from the next message."""
    from odie.sampling import CHAT_TEMPERATURE_SETTING
    store = request.app.state.store
    temperature = round(body.temperature, 1)  # the slider's steps; a float like 0.7000000001 reads badly in the log
    store.set_setting(CHAT_TEMPERATURE_SETTING, temperature)
    store.audit("user", "creativity_set", result_summary=f"chat temperature {temperature}")
    return {"ok": True, "creativity": _creativity(store)}


@router.get("/models/usage")
async def models_usage(request: Request):
    """The latest reply's token counts: how much of its input came from the provider's prompt cache."""
    from odie.agent.usage import last_usage
    return {"usage": last_usage(request.app.state.store)}


@router.put("/models/selection")
async def models_select(body: SelectionIn, request: Request):
    store = request.app.state.store
    if body.slot != "chat":
        raise HTTPException(422, "There's one model now: slot is chat.")
    if body.provider not in {p.id for p in all_providers(store)}:
        raise HTTPException(404, "unknown provider")
    store.set_setting(f"model.{body.slot}", {"provider": body.provider, "model": body.model})
    store.audit("user", "model_selected", result_summary=f"{body.slot}: {body.provider}/{body.model}")
    apply = getattr(request.app.state.runner, "apply_model_selection", None)
    if apply:
        apply()
    sel = resolve_selection(store, body.slot)
    return {"ok": True, "slot": body.slot, "provider": sel.provider.id, "model": sel.model, "leaves_mini": sel.leaves_mini}


@router.post("/models/providers")
async def providers_add(body: ProviderIn, request: Request):
    store = request.app.state.store
    customs = store.get_setting("providers.custom", []) or []
    pid = slug(body.name)
    if pid in PRESET_BY_ID or pid in ("lmstudio", "ollama"):
        raise HTTPException(422, "That name is taken by a built-in provider.")
    legacy = next((c.get("api_key") for c in customs if c["id"] == pid and c.get("api_key")), None)
    key = body.api_key or legacy  # an older entry kept its key inline: move it to .env rather than lose it
    if key:
        try:
            save_secret(custom_key_name(pid), key)
        except ValueError as e:
            raise HTTPException(422, str(e))
    customs = [c for c in customs if c["id"] != pid] + [{"id": pid, "name": body.name, "base_url": body.base_url.rstrip("/")}]
    store.set_setting("providers.custom", customs)
    _models_changed(request)
    return {"ok": True, "id": pid}


@router.delete("/models/providers/{pid}")
async def providers_remove(pid: str, request: Request):
    store = request.app.state.store
    store.set_setting("providers.custom", [c for c in (store.get_setting("providers.custom", []) or []) if c["id"] != pid])
    remove_secret(custom_key_name(pid))
    _models_changed(request)
    return {"ok": True}


# --- Providers: which ones Odie can use, and their keys (kept in ~/.odie/.env, never sent back) ---
class KeyIn(BaseModel):
    api_key: str


_fallback_refreshes: set[asyncio.Task] = set()


def _models_changed(request: Request) -> None:
    apply = getattr(request.app.state.runner, "apply_model_selection", None)
    if apply:
        apply()  # the chat model may use the provider whose key just changed
    task = asyncio.create_task(refresh_fallback(request.app.state.store))  # the providers on offer changed
    _fallback_refreshes.add(task)
    task.add_done_callback(_fallback_refreshes.discard)


async def check_key(provider: Provider) -> str | None:
    """None if the provider accepts the key (or can't be reached to say), else one sentence."""
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(provider.base_url + "/models", headers=auth_headers(provider))
    except httpx.HTTPError:
        return None
    return f"{provider.name} didn't accept that key." if r.status_code in (401, 403) else None


# --- Up next: calendar, SMS dues and notices, confirmation mails and dated tasks, merged ---
@router.get("/upcoming")
async def upcoming_get(request: Request):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from odie import upcoming
    return await upcoming.build(request.app.state.store, datetime.now(ZoneInfo(config.settings.timezone)))


# --- Trackers: background checks the user can see, pause, stop or run now ---
@router.get("/trackers")
async def trackers_get(request: Request):
    from odie import trackers
    return {"trackers": trackers.listing(request.app.state.store)}


class TrackerSignInIn(BaseModel):
    allow: bool


@router.post("/trackers/{tid}/signin")
async def tracker_signin(tid: int, body: TrackerSignInIn, request: Request):
    """The user's tap: may this tracker check its page signed in? (odie.trackers.signed_in). No tool reaches this."""
    from odie import trackers
    from odie.trackers import signed_in
    store = request.app.state.store
    if trackers.get(store, tid) is None:
        raise HTTPException(404, "no such tracker")
    if why := signed_in.allow(store, tid, body.allow):
        raise HTTPException(409, why)
    return {"ok": True, "tracker": next((t for t in trackers.listing(store) if t["id"] == tid), None)}


@router.post("/trackers/{tid}/{action}")
async def tracker_action(tid: int, action: str, request: Request):
    from datetime import UTC, datetime

    from odie import trackers
    store = request.app.state.store
    row = trackers.get(store, tid)
    if row is None:
        raise HTTPException(404, "no such tracker")
    if action in ("pause", "resume", "stop"):
        trackers.set_status(store, tid, {"pause": "paused", "resume": "active", "stop": "stopped"}[action])
        if action == "resume":
            store.execute("update trackers set fails=0 where id=?", (tid,))
        return {"ok": True, "status": trackers.get(store, tid)["status"]}
    if action == "check":
        runner = request.app.state.runner
        if not hasattr(runner, "background_turn"):
            raise HTTPException(503, "checks aren't available")
        if tid in trackers._RUNNING:
            return {"ok": True, "status": row["status"], "checking": True}  # one is already running
        task = asyncio.create_task(trackers.check(store, row, runner.background_turn, runner.tracker_notify, datetime.now(UTC), runner.tz))
        request.app.state.__dict__.setdefault("tracker_tasks", set()).add(task)
        task.add_done_callback(request.app.state.tracker_tasks.discard)
        return {"ok": True, "status": row["status"], "checking": True}
    raise HTTPException(422, "action must be pause, resume, stop or check")


@router.get("/blocks/catalog")
async def blocks_catalog():
    from odie.blocks import load_catalog
    return load_catalog()


# --- Block state: what the user did to a block in a reply (a checklist's ticks), saved per reply ---
# A reply is named by its chat session and its ADK event id; a block by its fence and its place in that fence.
MESSAGE_KEY_RE = r"^[A-Za-z0-9_-]{1,64}$"                        # an ADK event id: "3f2b9c1e-…"
BLOCK_PATH_RE = r"^\d{1,2}/\d{1,3}(\.children\.\d{1,3}){0,3}$"   # "0/2", "1/0.children.3"


class BlockStateIn(BaseModel):
    session_id: str = Field(max_length=40)
    message_key: str = Field(pattern=MESSAGE_KEY_RE)
    block_path: str = Field(pattern=BLOCK_PATH_RE)
    value: Any


def _chat_session(sid: str) -> str:
    """Block state belongs to chat replies only: "chat-2026-10-11" or "chat-2026-10-11-2" → kept; "eval-x" → 422."""
    from odie import threads
    if not threads.valid_id(sid):
        raise HTTPException(422, "session_id must be a chat session")
    return sid


@router.get("/block-state")
async def block_state_get(session_id: str, message_key: str, request: Request):
    """Every saved value in one reply: {"values": {"0/2": [0, 3]}}."""
    if not re.match(MESSAGE_KEY_RE, message_key):
        raise HTTPException(422, "bad message_key")
    values = request.app.state.store.block_state(_chat_session(session_id), message_key)
    return {"values": values}


@router.put("/block-state")
async def block_state_put(body: BlockStateIn, request: Request):
    """Saves one block's value in one reply (the app sends the whole value: a checklist's ticked items, [0, 3])."""
    try:
        request.app.state.store.save_block_state(_chat_session(body.session_id), body.message_key, body.block_path, body.value)
    except ValueError as e:
        raise HTTPException(413, str(e)) from None
    return {"ok": True}


# --- Web search: whichever key is set is used (Tavily, then Brave, then Ollama); none working means the free fallback ---
@router.get("/search")
async def search_get(request: Request):
    from odie.agent.tools.web import FREE, PROVIDERS, key_source
    rows = []
    for p in PROVIDERS:
        _, where = key_source(p)
        rows.append({"id": p.id, "name": p.name, "connected": where is not None, "source": where, "key_page": p.key_page})
    first = next((r["id"] for r in rows if r["connected"]), FREE)
    return {"providers": rows, "next": first, "last": request.app.state.store.get_setting("search.last")}


@router.put("/search/{pid}/key")
async def search_key_put(pid: str, body: KeyIn, request: Request):
    from odie.agent.tools.web import PROVIDER_BY_ID, check_search_key
    from odie.secrets import VALUE_RE
    p = PROVIDER_BY_ID.get(pid)
    if not p:
        raise HTTPException(404, "unknown search provider")
    key = body.api_key.strip()
    if not VALUE_RE.match(key):
        raise HTTPException(422, "That doesn't look like a key (spaces, quotes or # in it).")
    if problem := await check_search_key(pid, key):
        raise HTTPException(422, problem)
    save_secret(p.env, key)
    request.app.state.store.audit("user", "search_key_saved", result_summary=p.name)
    return {"ok": True}


@router.delete("/search/{pid}/key")
async def search_key_delete(pid: str, request: Request):
    from odie.agent.tools.web import PROVIDER_BY_ID, key_source
    p = PROVIDER_BY_ID.get(pid)
    if not p:
        raise HTTPException(404, "unknown search provider")
    removed = remove_secret(p.env)
    request.app.state.store.audit("user", "search_key_removed", result_summary=p.name)
    return {"ok": True, "removed": removed, "still_set": key_source(p)[1]}


@router.get("/providers")
async def providers_get(request: Request):
    store = request.app.state.store
    from odie import models as models_mod  # through the module, so tests' stand-in for the local servers applies
    have = {p.id for p in all_providers(store)}
    answering = {row["id"] for row in await models_mod.ask_local_providers() if row["error"] is None}  # running now
    rows = [{"id": "lmstudio", "name": "LM Studio", "kind": "local", "connected": "lmstudio" in answering},
            {"id": "ollama", "name": "Ollama", "kind": "local", "connected": "ollama" in answering}]
    rows += [{"id": p.id, "name": p.name, "kind": "preset", "connected": p.id in have,
              "from_env": bool(os.environ.get(p.env))} for p in PRESETS]
    rows += [{"id": c["id"], "name": c.get("name") or c["id"], "kind": "custom", "connected": True, "base_url": c["base_url"]}
             for c in store.get_setting("providers.custom", []) or []]
    return {"providers": rows}


@router.put("/providers/{pid}/key")
async def provider_key_put(pid: str, body: KeyIn, request: Request):
    preset = PRESET_BY_ID.get(pid)
    if not preset:
        raise HTTPException(404, "unknown provider")
    key = body.api_key.strip()
    from odie.secrets import VALUE_RE
    if not VALUE_RE.match(key):
        raise HTTPException(422, "That doesn't look like a key (spaces, quotes or # in it).")
    problem = await check_key(Provider(preset.id, preset.name, preset_base_url(preset), key, False))
    if problem:
        raise HTTPException(422, problem)
    save_secret(preset.env, key)
    request.app.state.store.audit("user", "provider_key_saved", result_summary=preset.name)
    _models_changed(request)
    return {"ok": True, "connected": True}


@router.delete("/providers/{pid}/key")
async def provider_key_delete(pid: str, request: Request):
    preset = PRESET_BY_ID.get(pid)
    if not preset:
        raise HTTPException(404, "unknown provider")
    removed = remove_secret(preset.env)
    _models_changed(request)
    return {"ok": True, "removed": removed, "still_set": bool(os.environ.get(preset.env))}


# ── paired devices (odie.devices) ──
class PairCodeIn(BaseModel):
    code: str = Field(max_length=40)
    name: str = Field("", max_length=80)


class PasscodeIn(BaseModel):
    passcode: str = Field(max_length=200)
    name: str = Field("", max_length=80)


class PairingIn(BaseModel):
    on: bool


def _device(request: Request) -> dict | None:
    return devices.device_for(request.app.state.store, request.cookies.get(devices.COOKIE))


def _paired(request: Request, resp: Response, name: str | None = None) -> Response:
    """Pairs this browser: a new device, and its key in the cookie (Secure when the request came over HTTPS)."""
    key = devices.add_device(request.app.state.store, name or devices.name_from(request.headers.get("user-agent")))
    https = request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "").split(",")[0].strip() == "https"
    resp.set_cookie(devices.COOKIE, key, max_age=devices.COOKIE_AGE, path="/", httponly=True, samesite="lax", secure=https)
    return resp


def _base_url(request: Request) -> str:
    """Where a new device reaches Odie: this browser's address, or the phone address when this browser is on the
    computer itself."""
    local = ("localhost", "127.0.0.1", "::1")
    public = config.settings.public_url.rstrip("/")
    if request.url.hostname in local and httpx.URL(public).host not in local:
        return public
    return str(request.base_url).rstrip("/")


@router.get("/pair/status")
async def pair_status(request: Request) -> dict[str, Any]:
    store = request.app.state.store
    return {"on": devices.pairing_on(store), "paired": _device(request) is not None, "devices": len(devices.list_devices(store)),
            "passcode": devices.has_passcode(store)}


@router.post("/pair/code")
async def pair_code(body: PairCodeIn, request: Request):
    if not devices.redeem_code(request.app.state.store, body.code):
        raise HTTPException(401, "That code didn't work. A code works once, for 10 minutes.")
    return _paired(request, JSONResponse({"ok": True}), body.name)


@router.post("/pair/passcode")
async def pair_passcode(body: PasscodeIn, request: Request):
    ok = devices.try_passcode(request.app.state.store, body.passcode)
    if ok is None:
        raise HTTPException(429, "Too many wrong tries. Wait 10 minutes and try again.")
    if not ok:
        raise HTTPException(401, "That passcode didn't match.")
    return _paired(request, JSONResponse({"ok": True}), body.name)


@router.get("/pair/setup")
async def pair_setup(request: Request, token: str = ""):
    """The installer's one-time link: pairs the first browser, then opens the app."""
    if not devices.redeem_setup(request.app.state.store, token):
        return RedirectResponse("/?pair=used", status_code=303)
    return _paired(request, RedirectResponse("/", status_code=303))


@router.get("/devices")
async def devices_list(request: Request) -> list[dict[str, Any]]:
    me = _device(request)
    return [{**d, "this": bool(me) and d["id"] == me["id"]} for d in devices.list_devices(request.app.state.store)]


@router.delete("/devices/{device_id}")
async def devices_remove(device_id: int, request: Request, confirm: bool = False):
    store = request.app.state.store
    known = devices.list_devices(store)
    if not any(d["id"] == device_id for d in known):
        raise HTTPException(404, "No such device.")
    if len(known) == 1 and devices.pairing_on(store) and not confirm:
        raise HTTPException(409, "This is the last paired device. Without it, only the recovery passcode lets a browser in.")
    devices.remove_device(store, device_id)
    devices.offer_setup(store)
    return {"ok": True}


@router.post("/devices/code")
async def devices_code(request: Request) -> dict[str, Any]:
    code = devices.new_code(request.app.state.store)
    url = f"{_base_url(request)}/#pair={code}"
    return {"code": code, "url": url, "svg": qr.svg(qr.encode(url)), "expires_in": devices.CODE_TTL}


@router.post("/devices/passcode")
async def devices_passcode(request: Request) -> dict[str, Any]:
    return {"passcode": devices.new_passcode(request.app.state.store)}


@router.put("/devices/pairing")
async def devices_pairing(body: PairingIn, request: Request):
    """Turning pairing on from a browser that isn't paired pairs it first, so it keeps its way in."""
    store = request.app.state.store
    devices.set_pairing(store, body.on)
    resp = JSONResponse({"on": devices.pairing_on(store)})
    if body.on and _device(request) is None:
        _paired(request, resp)
    devices.offer_setup(store)
    return resp
