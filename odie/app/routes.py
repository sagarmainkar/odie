"""HTTP API. Everything the PWA talks to."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, File, HTTPException, Request, UploadFile, WebSocket
from fastapi.responses import JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from odie import approvals_mode, config, devices, persona, qr
from odie.models import (PRESET_BY_ID, PRESETS, Provider, all_providers, auth_headers, brain_chosen, custom_key_name,
                         list_models, preset_base_url, refresh_fallback, resolve_selection, slug)
from odie.morning.round import add_brief_to_hello, hello_due, hello_for, morning_day, morning_round, round_running
from odie.photos.library import PHOTO_UUID
from odie.secrets import remove_secret, save_secret
from odie.store.db import approval_dict as _approval_dict
from odie.agent.prompt import Who, identity

log = logging.getLogger("odie.api")
SOUL_PATH = config.settings.config_dir / "SOUL.md"  # follows ODIE_CONFIG_DIR, so a test instance has its own
router = APIRouter(prefix="/api")


class ChatIn(BaseModel):
    text: str
    thinking: bool | None = None  # left out: the chat's own Think harder (odie.thinking); given (an older web app): saved first
    images: list[str] = []
    session_id: str | None = None  # continue an older thread; None = today's
    # Who sent it when he didn't type it: "terminal" is the odie command (odie chat), for an agent or script; "tap" is a
    # button or a card the app sent for him (its words came from the model or a mail: never "his typed words").
    via: Literal["terminal", "tap"] | None = None


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
    from odie import update, voice
    brain_reachable = lm or chosen["provider"] != "lmstudio"  # only LM Studio is probed here; a cloud brain has its key
    hearing = await voice.hearing_available()  # the Mac listens through /api/talk/listen when this is true
    return {"status": "ok", "name": "Odie", "version": update.version(), "model": chosen["model"], "provider": chosen["provider"],
            "leaves_mini": chosen["leaves_mini"], "lm_studio": lm, "connections": connections,
            "brain_chosen": brain_chosen(request.app.state.store), "brain_reachable": brain_reachable, "hearing": hearing,
            "build": update.web_build(config.settings.web_dist)}


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


def say_answered_while_away(store, bus, session_id: str | None, text: str) -> None:
    """A reply finished after the app had gone away: a push. An everyday reply: its first words, as before. A reply
    in a personality's thread: who, never the words (odie.personalities.quiet_push), and a wordless "answered" notice
    on the live stream, so a chat with someone else can show that she has something new."""
    from odie import personalities
    from odie.push.send import send_to_all
    owner_id, owner = personalities.whose_thread(store, session_id)
    if owner_id == personalities.ODIE:
        send_to_all(store, f"{persona.get(store)['name']} answered", reply_preview(text) or "Your answer is ready.",
                    url="/#chat", tag="reply")
        return
    if owner is None:  # its personality was deleted while the turn finished: nothing is said
        return
    title, body = personalities.quiet_push(owner.name, "replied")
    send_to_all(store, title, body, url="/#chat", tag="reply")
    if bus is not None:
        bus.emit({"type": "answered", "session_id": session_id})


@router.post("/chat")
async def chat(body: ChatIn, request: Request):
    from odie.app.detached import detached
    store = request.app.state.store

    def answered_while_away(text: str) -> None:
        say_answered_while_away(store, getattr(request.app.state, "bus", None), session_id, text)

    from odie import threads
    if body.session_id is not None and not threads.valid_id(body.session_id):
        raise HTTPException(422, "not a chat thread")
    pick = _personality(request)  # who the app is talking to: everyday Odie, or a personality
    session_id = body.session_id
    if session_id is not None:
        _own_thread(request, session_id)  # a thread named with someone else's pick is "not found"
    elif pick:
        session_id = await request.app.state.runner.session_for(pick, _today())  # its current thread, made if none
    if body.thinking is not None:  # an app that still sends it: the same as choosing it in the menu, then the turn
        await _set_chat_thinking(request, session_id or _chat_meant(request, None), body.thinking)
    kw: dict[str, Any] = {}
    if session_id:
        kw["session_id"] = session_id
    if body.via:
        kw["via"] = body.via
    device = devices.device_for(store, request.cookies.get(devices.COOKIE))
    if devices.is_terminal(device):  # the odie command's key: a terminal turn, whatever the body says
        kw["via"] = "terminal"
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
    """The chat as it opens: everyday Odie's day, or (with a pick) that personality's current thread."""
    pick = _personality(request)
    if pick:
        return await request.app.state.runner.history(date, limit=limit, before=before, personality=pick)
    return await request.app.state.runner.history(date, limit=limit, before=before)


# --- Threads: every conversation, searchable, pinnable, renamable ---
class PinIn(BaseModel):
    pinned: bool


class TitleIn(BaseModel):
    title: str


def _today() -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo(config.settings.timezone)).strftime("%Y-%m-%d")


def _personality(request: Request) -> str:
    """Which personality a request is for (odie.personalities): its `personality` query parameter. The web app sends
    the one picked on that device; the Mac app, the terminal and an older web app send none.
      ?personality=ab12cd (Mira's id) -> "ab12cd";  none, or empty -> "" (everyday Odie);  an id nobody has -> 404"""
    from odie import personalities
    pick = request.query_params.get("personality", "")
    if not pick:
        return personalities.ODIE
    if personalities.get(request.app.state.store, pick) is None:
        raise HTTPException(404, "no such personality")
    return pick


def _own_thread(request: Request, sid: str) -> str:
    """A thread id the request may use: a chat thread that belongs to the request's personality. Anything else is "no
    such thread", so a thread can't be reached by naming it with another pick, or with none. Whose thread it is comes
    from the thread's own row, never from the request.
      Mira's thread with Mira's pick -> the id;  Mira's thread with no pick (the terminal, the Mac app) -> 404;
      an everyday thread with Mira's pick -> 404;  "voice-2026-11-17" -> 404"""
    from odie import personalities, threads
    if not threads.valid_id(sid):
        raise HTTPException(404, "no such thread")
    owner = personalities.of_session(request.app.state.store, sid)
    if owner != _personality(request):
        raise HTTPException(404, "no such thread")
    return sid


def _own_approval(request: Request, approval_id: int):
    """The approval card with this id, when its thread belongs to the request's personality; otherwise "no such
    approval": a personality's card is seen and answered only from that personality's chat."""
    from odie import personalities
    store = request.app.state.store
    row = store.get_approval(approval_id)
    if row is None:
        raise HTTPException(404, "no such approval")
    if personalities.of_session(store, row["session_id"]) != _personality(request):
        raise HTTPException(404, "no such approval")
    return row


@router.get("/threads")
async def threads_list(request: Request, q: str | None = None):
    from odie import threads
    return {"threads": await asyncio.to_thread(threads.list_threads, request.app.state.store, q, _personality(request))}


@router.get("/threads/{sid}/history")
async def thread_history(sid: str, request: Request, limit: int | None = None, before: int | None = None):
    return await request.app.state.runner.session_history(_own_thread(request, sid), limit=limit, before=before)


@router.post("/threads/{sid}/pin")
async def thread_pin(sid: str, body: PinIn, request: Request):
    from odie import threads
    threads.set_pinned(request.app.state.store, _own_thread(request, sid), body.pinned)
    return {"ok": True, "pinned": body.pinned}


@router.post("/threads/{sid}/rename")
async def thread_rename(sid: str, body: TitleIn, request: Request):
    from odie import threads
    threads.rename(request.app.state.store, _own_thread(request, sid), body.title)
    return {"ok": True, "title": " ".join(body.title.split())[:threads.TITLE_MAX]}


class StopIn(BaseModel):
    session_id: str | None = None


class ThinkingIn(BaseModel):
    on: bool
    session_id: str | None = None  # a chat thread; None = today's current chat


def _chat_meant(request: Request, session_id: str | None) -> str | None:
    """The chat a request means: the thread it names (which must belong to its personality: _own_thread), else the
    current chat of whoever it is for: everyday Odie's chat of today (as /api/chat picks it), or a personality's
    current thread, which is None while it has no thread yet."""
    if session_id:
        return _own_thread(request, session_id)
    runner = request.app.state.runner
    pick = _personality(request)
    if pick:
        return runner.current_thread(pick)
    today = _today()
    current = getattr(runner, "current_session_id", None)
    if current is None:
        return f"chat-{today}"
    return current(today)


async def _set_chat_thinking(request: Request, session_id: str, on: bool) -> dict:
    """Save a chat's Think harder (and the default for new chats), and tell every open app."""
    from odie import thinking
    store = request.app.state.store
    thinking.put(store, session_id, on)
    store.audit("user", "think_harder", result_summary=f"{session_id}: {'on' if on else 'off'}", session_id=session_id)
    event = thinking.event(session_id, on)
    await _publish(request, event)
    return {"session_id": session_id, "on": bool(on)}


@router.get("/chat/thinking")
async def chat_thinking_get(request: Request, session_id: str | None = None):
    """This chat's Think harder: {"session_id", "on"}. No session_id: today's current chat."""
    from odie import thinking, threads
    if session_id is not None and not threads.valid_id(session_id):
        raise HTTPException(422, "not a chat thread")
    sid = _chat_meant(request, session_id)
    if sid is None:  # a personality with no thread yet: what its first thread will start with
        return {"session_id": None, "on": thinking.default(request.app.state.store)}
    return {"session_id": sid, "on": thinking.get(request.app.state.store, sid)}


@router.put("/chat/thinking")
async def chat_thinking_put(body: ThinkingIn, request: Request):
    """Turn this chat's Think harder on or off; new chats start with it too, and every open app hears of it."""
    from odie import threads
    if body.session_id is not None and not threads.valid_id(body.session_id):
        raise HTTPException(422, "not a chat thread")
    sid = _chat_meant(request, body.session_id)
    if sid is None:  # a personality with no thread yet: the choice is made on its first thread
        sid = await request.app.state.runner.session_for(_personality(request), _today())
    return await _set_chat_thinking(request, sid, body.on)


@router.post("/chat/stop")
async def chat_stop(body: StopIn, request: Request):
    """The user tapped Stop: the running turn in this chat (today's, or the open thread) ends at its next safe step."""
    from odie import threads
    runner = request.app.state.runner
    if body.session_id is not None and not threads.valid_id(body.session_id):
        raise HTTPException(422, "not a chat thread")
    sid = _chat_meant(request, body.session_id)
    if sid is None:  # a personality with no thread yet: nothing is running there
        return {"ok": True, "session_id": None}
    stop = getattr(runner, "request_stop", None)
    if stop:
        stop(sid)
    return {"ok": True, "session_id": sid}


@router.get("/chat/context")
async def chat_context(request: Request):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    today = datetime.now(ZoneInfo(config.settings.timezone)).strftime("%Y-%m-%d")
    pick = _personality(request)
    if pick:
        return await request.app.state.runner.context_usage(today, personality=pick)
    return await request.app.state.runner.context_usage(today)


@router.post("/chat/new")
async def chat_new(request: Request):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    today = datetime.now(ZoneInfo(config.settings.timezone)).strftime("%Y-%m-%d")
    pick = _personality(request)
    if pick:
        return {"session_id": await request.app.state.runner.new_chat(today, pick)}
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
    """The connected apps, each with its whole-server switches, `canUse`: whether whoever the request picked (a
    personality, or everyday Odie with none) may use it (odie.plugins.access), and `onlyPick`: whether no one else may
    (connecting the same service again then replaces it, mcp_connect)."""
    from odie.plugins import access
    from odie.plugins.mcp import masked, read_config
    pick = _personality(request)
    store = request.app.state.store
    servers, err = read_config()
    live = {e.name: e for e in request.app.state.runner.plugins.get("servers", [])}
    out = []
    for name, spec in servers.items():
        e = live.get(name)
        out.append({"name": name, "spec": masked(spec), "status": e.status if e else "not loaded", "tools": e.tools if e else [],
                    "reason": e.reason if e else "", "alwaysOn": bool(spec.get("alwaysOn")), "enabled": spec.get("enabled", True) is not False,
                    "readsFree": bool(spec.get("readsFree")), "canUse": access.allowed(store, name, pick),
                    "onlyPick": access.only_one_using(store, name, pick)})
    return {"servers": out, "error": err}


@router.post("/mcp")
async def mcp_save(body: ServerIn, request: Request):
    from odie.plugins.mcp import NAME_RE, command_problem, read_config, unmask, write_config
    if not NAME_RE.match(body.name) or not (body.spec.get("url") or body.spec.get("command")):
        raise HTTPException(422, "a lower-case name and a command or url are needed")
    servers, _ = read_config()
    spec = dict(body.spec)
    old = servers.get(body.name) or {}
    try:
        edit = unmask(spec, old)  # masked values coming back keep the real secret
    except ValueError as e:
        raise HTTPException(422, str(e))
    problem = command_problem(edit)
    if problem:
        raise HTTPException(422, problem)
    pick = _personality(request)
    is_new = body.name not in servers
    keep = {k: v for k, v in old.items() if k not in (("command", "args", "env") if edit.get("url") else ("url", "headers"))}
    servers[body.name] = {**keep, **edit}  # switches (enabled, alwaysOn) and hand-written keys stay
    write_config(servers)
    if is_new:
        _app_added(request, body.name, pick)
    runner = request.app.state.runner
    await runner.load_plugins()  # its tool names are known from here on, even when it was refused for a clash
    out: dict[str, Any] = {"ok": True, "switched_off": [], "note": ""}
    if is_new:
        from odie.plugins import access
        before = access.off_for(request.app.state.store, pick)
        note = access.make_room_for(request.app.state.store, body.name, pick, servers)
        if note:  # the picked one's other connection of the service was in the way: off for it now, and loaded again
            out["switched_off"] = sorted(access.off_for(request.app.state.store, pick) - before)
            out["note"] = note
            await runner.load_plugins()
    return out


def _app_added(request: Request, name: str, pick: str) -> None:
    """A connected app was just added: it is for whoever is picked alone (odie.plugins.access.added)."""
    from odie.plugins import access
    store = request.app.state.store
    access.added(store, name, pick)
    store.audit("user", "app_added", result_summary=f"{name} for {pick or 'everyday Odie'}")


class CheckIn(BaseModel):
    name: str = ""  # a saved server being edited: its masked values are restored before the check
    spec: dict


class ConnectIn(BaseModel):
    preset: str
    url: str = Field(max_length=2000)
    key: str = Field("", max_length=500)
    check_only: bool = False  # list the tools, save nothing
    add: bool = False  # another connection to the same service, beside the one there


async def _check(spec: dict, smart: bool = False) -> dict:
    """The server's tools, listed in a throwaway process, and which of them would ask for a tap (under the current
    approvals mode, smart). A failure's reason is scrubbed of the spec's secrets."""
    from odie.plugins import mcp as m
    try:
        listed = await m.probe_tools(spec, 20)
    except Exception as ex:  # noqa: BLE001 (timeouts, refused connections, bad commands, a 401)
        return {"ok": False, "reason": m.scrub(str(ex) or type(ex).__name__, spec)}
    free = bool(spec.get("readsFree"))
    return {"ok": True, "tools": [{"name": t["name"], "read_only": bool(t.get("read_only")), "asks": m.asks(t, free, smart=smart)} for t in listed]}


@router.get("/mcp/presets")
async def mcp_presets() -> list[dict[str, Any]]:
    from odie.plugins.presets import PRESETS
    return [{"id": pid, "title": p["title"], "where": p["where"], "key_label": p["key_label"]} for pid, p in PRESETS.items()]


@router.post("/mcp/check")
async def mcp_check(body: CheckIn, request: Request) -> dict[str, Any]:
    """Lists a server's tools before it is saved (nothing is saved)."""
    from odie.plugins.mcp import command_problem, read_config, unmask
    if not (body.spec.get("url") or body.spec.get("command")):
        raise HTTPException(422, "a command or url is needed")
    try:
        spec = unmask(dict(body.spec), (read_config()[0].get(body.name) or {}) if body.name else {})
    except ValueError as e:
        raise HTTPException(422, str(e))
    problem = command_problem(spec)  # the check runs the program: never a shell or code handed in as text
    if problem:
        raise HTTPException(422, problem)
    return await _check(spec, smart=approvals_mode.is_smart(request.app.state.store))


@router.post("/mcp/connect")
async def mcp_connect(body: ConnectIn, request: Request) -> dict[str, Any]:
    """Zapier or Composio from the link (and key) the user pasted: checked, then saved and loaded. Connecting the same
    service again replaces its connection (a new link, a new code), keeping its switches; add=True adds another.
    A connection is replaced only when whoever is picked is the only one who can use it; otherwise the picked one gets
    a connection of its own and the old one is left as it is, switched off for the picked one (odie.plugins.access):
      Odie's zapier, on for everyone; Mira connects     -> zapier-2, on for Mira alone; zapier unchanged, off for her
      Mira connects again (zapier-2 is hers alone)      -> zapier-2 replaced in place
      no personalities; Odie connects again             -> zapier replaced in place, as before personalities"""
    from odie.plugins import access, presets
    from odie.plugins.mcp import read_config, write_config
    try:
        spec = presets.spec_for(body.preset, body.url, body.key)
    except ValueError as e:
        raise HTTPException(422, str(e))
    checked = await _check(spec, smart=approvals_mode.is_smart(request.app.state.store))
    if not checked["ok"]:
        said = presets.plain_reason(body.preset, checked["reason"])
        raise HTTPException(422, said if said != checked["reason"] else f"{presets.PRESETS[body.preset]['title']} didn't answer: {said}")
    if body.check_only:
        return {"ok": True, "name": None, "tools": checked["tools"]}
    store = request.app.state.store
    pick = _personality(request)
    servers, _ = read_config()
    name = _same_link(servers, spec["url"], store, pick)
    if name is None and not body.add:
        same = [n for n, sp in servers.items() if isinstance(sp, dict) and presets.preset_of(str(sp.get("url") or "")) == body.preset]
        usable = [n for n in same if access.allowed(store, n, pick)]  # the picked one's own; another's is never a candidate
        if len(usable) > 1:
            title = presets.PRESETS[body.preset]["title"]
            raise HTTPException(409, f"You have two {title} connections ({', '.join(usable)}): remove the one you don't use in "
                                     "Settings → Connected apps, then connect again.")
        name = usable[0] if usable else None
    shared = None  # a connection someone else uses too: left as it is, and switched off for the picked one
    if name is not None and not access.only_one_using(store, name, pick):
        shared = name
        name = None
    replaced = name is not None
    name = name or next(n for n in (body.preset, *(f"{body.preset}-{i}" for i in range(2, 100))) if n not in servers)
    old = servers.get(name) or {}
    servers[name] = {**{k: v for k, v in old.items() if k in ("enabled", "alwaysOn", "readsFree")}, **spec}
    write_config(servers)
    if not replaced:
        _app_added(request, name, pick)
    if shared is not None:
        access.set_allowed(store, shared, pick, False)
    await request.app.state.runner.load_plugins()
    return {"ok": True, "name": name, "tools": checked["tools"], "replaced": replaced}


def _same_link(servers: dict, url: str, store, pick: str) -> str | None:
    """The connection a link is for: one with that very link, preferring those the picked one can use, since one link
    can serve several accounts (Zapier's, with a code each).
      Mira's zapier and Odie's zapier-2, the same link; Odie connects it again -> "zapier-2"
      only Mira's has the link; Odie connects it                          -> "zapier" (then left as it is: not his alone)
      no connection has the link                                          -> None"""
    from odie.plugins import access
    with_link = [n for n, sp in servers.items() if isinstance(sp, dict) and sp.get("url") == url]
    usable = [n for n in with_link if access.allowed(store, n, pick)]
    if usable:
        return usable[0]
    if with_link:
        return with_link[0]
    return None


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


@router.post("/mcp/{name}/access")
async def mcp_access(name: str, body: OnIn, request: Request):
    """Whether whoever the request picked (a personality, or everyday Odie with none) may use this app: "Mira can use
    this" in Settings (odie.plugins.access). Read live: no reload is needed."""
    from odie.plugins import access
    from odie.plugins.mcp import read_config
    pick = _personality(request)
    servers, _ = read_config()
    if name not in servers:
        raise HTTPException(404, "no such server")
    store = request.app.state.store
    if body.on:  # one connection of a service at a time for each owner: its tools' names would be listed twice
        taken = access.clash_for(store, name, pick, servers)
        if taken:
            raise HTTPException(409, taken)
    access.set_allowed(store, name, pick, body.on)
    store.audit("user", "app_access", result_summary=f"{name} {'on' if body.on else 'off'} for {pick or 'everyday Odie'}")
    _forget_prompts(request)  # the prompt's capabilities (mail, the vault) follow the apps it may use
    runner = request.app.state.runner
    if _refused_for_a_clash(runner):  # this switch may have cleared it: load again, so it works without a restart
        await runner.load_plugins()
    return {"ok": True}


def _refused_for_a_clash(runner) -> bool:
    """Whether a loaded server was refused because its tool names clash with another server's, which a switch can
    clear: "tool names clash with send_email (mail). Only one of them can be on…" -> True; every server loaded, or one
    that failed to start -> False."""
    from odie.plugins.mcp import CLASH_ADVICE
    return any(e.status == "error" and any(words in e.reason for words in CLASH_ADVICE)
               for e in runner.plugins.get("servers", []))


@router.delete("/mcp/{name}")
async def mcp_delete(name: str, request: Request):
    from odie.plugins import access
    from odie.plugins.mcp import read_config, write_config
    servers, _ = read_config()
    if servers.pop(name, None) is None:
        raise HTTPException(404, "no such server")
    write_config(servers)
    access.forget_server(request.app.state.store, name)
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
    ev = await request.app.state.runner.post_message(notice["text"], media=notice.get("media"), kind="reminder")
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
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from odie.loops import ledger
    ledger.reminder_done(store, task_id, datetime.now(ZoneInfo(config.settings.timezone)))  # its loop: Done, remembered
    note = ""
    if row["source_kind"]:
        from odie.agent.agent import source_done
        note = await source_done(row["source_kind"], row["source_ref"]) or ""
    store.audit("user", "task_done", result_summary=row["title"], approval_id=None)
    await _publish(request, {"type": "task", "id": task_id, "status": "done"})
    return {"ok": True, "ledger": note}


@router.get("/tasks/closed_by_watch")
async def tasks_closed_by_watch(request: Request):
    """The reminders the watch closed in the last three days (a bill it saw paid, an order delivered), with why, for
    Today's To close; the user can reopen one."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    from odie.watch import bills
    since = datetime.now(ZoneInfo(config.settings.timezone)) - timedelta(days=3)
    return bills.closed_by_watch(request.app.state.store, since, _personality(request))


@router.post("/tasks/{task_id}/reopen")
async def task_reopen(task_id: int, request: Request):
    """The watch closed it, wrongly: open again, without the watch's note."""
    from odie.watch import bills
    store = request.app.state.store
    row = store.one("select * from tasks where id=?", (task_id,))
    if row is None:
        raise HTTPException(404, "no such task")
    bills.reopen(store, task_id)
    store.audit("user", "task_reopen", result_summary=row["title"], approval_id=None)
    await _publish(request, {"type": "task", "id": task_id, "status": "open"})
    return {"ok": True}


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


def _stream_pick(request: Request) -> str | None:
    """Who the app that opened a live stream is talking to, for odie.personalities.event_for_stream:
      no `personality` parameter at all (the Mac app, the terminal, an older web app) -> None
      ?personality=        (a web app that knows of personalities, on everyday Odie) -> ""
      ?personality=ab12cd  (Mira's id)                                                -> "ab12cd"
      ?personality=<one that was deleted>                                             -> "" (it hears as Odie's does)"""
    from odie import personalities
    if "personality" not in request.query_params:
        return None
    pick = request.query_params.get("personality") or ""
    if pick and personalities.get(request.app.state.store, pick) is None:
        return ""
    return pick


@router.get("/events")
async def events(request: Request):
    """Live stream: pings, Odie-originated messages, task changes. A device removed while its stream is open loses it
    at the next event or ping. Each stream gets what its app may see (odie.personalities.event_for_stream): a
    personality's events go only to an app that picked it."""
    from odie import personalities
    bus = getattr(request.app.state, "bus", None)
    store, key = request.app.state.store, request.cookies.get(devices.COOKIE)
    pick = _stream_pick(request)

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
                    seen = personalities.stream_view(store, e, pick)
                    if seen is None:  # another personality's: not for this app
                        continue
                    yield {"data": json.dumps(seen, default=str)}
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


# --- Mac apps: Mail, Calendar and Reminders on this Mac, and the permission macOS asks for each ---
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
    if not permissions.offered(app_id):
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
    from odie import machine
    if machine.local_voice_wanted():
        caps.add("local_talk")  # Talk on this Mac: Silero and Parakeet listen (/api/talk/listen), the chosen voice answers
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
    embed_every: int | None = None  # minutes between background embedding passes: 0 (off), 5, 10, 15, 30 or 60


def _vault_view(request: Request) -> dict:
    from odie.vault import settings
    store = request.app.state.store
    ix = settings.index_for(store)
    worker = getattr(request.app.state, "vault_worker", None)
    return {"settings": settings.get(store), "status": ix.status() if ix else None, "memory_file": str(config.settings.memory_file),
            "meaning": _meaning_schedule(store, worker),
            "progress": worker.progress() if worker else {"running": False, "done": 0, "total": 0, "phase": "idle", "error": ""}}


def _meaning_schedule(store, worker) -> dict:
    """How often new notes and pictures are embedded in the background, for Settings: {"every": minutes (0: off),
    "on": bool, "embedded_at": when the last embedding pass started since Odie started (ISO), or None}."""
    from odie.vault import settings
    every = settings.get(store)["embed_every"]
    embedded_at = None
    if worker is not None:
        embedded_at = worker.last_embedded()
    return {"every": every, "on": every != 0, "embedded_at": embedded_at}


def _embed_every_words(minutes: int) -> str:
    """The audit line for the background embedding choice: 0 -> "meaning updates: off"; 15 -> "meaning updates: every 15 min"."""
    if minutes == 0:
        return "meaning updates: off"
    return f"meaning updates: every {minutes} min"


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
            await embed.check(embed.make_embedder(str(e.get("provider", "")), str(e.get("model", "")), store,
                                                  pictures=bool(e.get("pictures")), url=e.get("url")))
        except embed.EmbedError as err:
            raise HTTPException(422, str(err))
    try:
        settings.put(store, **{k: fields[k] for k in ("dir", "ignore", "embeddings", "embed_every") if k in fields})
    except ValueError as err:
        raise HTTPException(422, str(err))
    store.audit("user", "vault_settings", result_summary=str(settings.get(store)))
    if "embed_every" in fields:
        store.audit("user", "vault_settings", result_summary=_embed_every_words(fields["embed_every"]))
    reload = getattr(request.app.state.runner, "reload_vault", None)
    if reload:
        await reload()
    worker = getattr(request.app.state, "vault_worker", None)
    if worker:
        worker.kick()
    return _vault_view(request)


# --- Approvals: Careful (every tap asks) or Smart (routine work runs, risky things still ask) ---
class ApprovalsModeIn(BaseModel):
    mode: str


@router.get("/approvals/mode")
async def approvals_mode_get(request: Request) -> dict[str, str]:
    return {"mode": approvals_mode.mode(request.app.state.store)}


@router.put("/approvals/mode")
async def approvals_mode_put(body: ApprovalsModeIn, request: Request) -> dict[str, str]:
    """Choose Careful or Smart for the whole app; anything else is a 400."""
    try:
        saved = approvals_mode.set_mode(request.app.state.store, body.mode)
    except ValueError as err:
        raise HTTPException(400, str(err))
    return {"mode": saved}


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
    # how pictures are read by meaning: "gemma" (an EmbeddingGemma 2 that sees pictures: Odie's own service, or Ollama's),
    # "text" (an embedder that reads words only), "none" (no embedder set)
    meaning = "none" if embedder is None else ("gemma" if getattr(embedder, "sees_pictures", False) else "text")
    # minutes between background passes that read new pictures by meaning (the notes' setting); 0: paused
    meaning_every = vault_settings.get(store)["embed_every"]
    return {"settings": settings.get(store), "status": status, "meaning": meaning, "meaning_every": meaning_every,
            "progress": worker.progress() if worker else {"running": False, "done": 0, "total": 0, "phase": "idle", "error": ""}}


# --- Where the user is (odie.location) ---
class LocationIn(BaseModel):
    lat: float
    lon: float
    place: str | None = Field(None, max_length=200)  # the device's own name for the point (the Mac app geocodes itself)
    at: str | None = Field(None, max_length=40)       # when the device took the fix, ISO with its own offset


class LocationPut(BaseModel):
    on: bool | None = None
    home: str | None = Field(None, max_length=200)


@router.get("/location")
async def location_get(request: Request) -> dict[str, Any]:
    from odie import location
    return location.view(location.get(request.app.state.store))


@router.post("/location")
async def location_post(body: LocationIn, request: Request) -> dict[str, Any]:
    """A device says where the user is. The place name is the device's own when it sent one, else looked up
    (odie.location.place_for); the point itself is kept on the server and never comes back out."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from odie import location
    store = request.app.state.store
    if not location.point_is_plausible(body.lat, body.lon):
        raise HTTPException(422, "That isn't a place on Earth.")
    place = (body.place or "").strip()
    if not place:
        place = await location.place_for(store, body.lat, body.lon)
    now = datetime.now(ZoneInfo(config.settings.timezone))
    taken = location.fix_time(body.at, now)  # the device's clock when it said so, else the server's
    saved = location.record(store, body.lat, body.lon, place, taken)
    store.audit("user", "location", result_summary=f"seen at {place or '(no name yet)'}")
    return location.view(saved)


@router.put("/location")
async def location_put(body: LocationPut, request: Request) -> dict[str, Any]:
    """Settings: the switch, or a home the user stated."""
    from odie import location
    store = request.app.state.store
    if body.on is not None:
        location.set_on(store, body.on)
        word = "on" if body.on else "off"
        store.audit("user", "location", result_summary=word)
    if body.home is not None:
        location.set_home(store, body.home)
        store.audit("user", "location", result_summary=f"home: {body.home.strip() or '(cleared)'}")
    return location.view(location.get(store))


@router.delete("/location")
async def location_delete(request: Request) -> dict[str, Any]:
    """Forget: the place, the fixes, home and the answer to the ask."""
    from odie import location
    store = request.app.state.store
    saved = location.forget(store)
    store.audit("user", "location", result_summary="forgotten")
    return location.view(saved)


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


class CardIn(BaseModel):
    number: str = ""
    expiry: str = ""
    name: str = ""
    label: str = ""


@router.get("/wallet/cards")
async def cards_list(request: Request) -> dict[str, Any]:
    """Saved cards, without their numbers (odie.signin.wallet): Settings → Vault, and the live view's card button."""
    from odie.signin import wallet
    return {"cards": wallet.listing(request.app.state.store)}


@router.post("/wallet/cards")
async def cards_add(body: CardIn, request: Request) -> dict[str, Any]:
    from datetime import datetime

    from odie.signin import vault, wallet
    store = request.app.state.store
    try:
        wallet.save(store, body.number, body.expiry, body.name, body.label, datetime.now().astimezone())
    except ValueError as err:
        raise HTTPException(422, str(err))
    except vault.VaultError as err:
        raise HTTPException(502, str(err))
    return {"cards": wallet.listing(store)}


@router.delete("/wallet/cards/{card_id}")
async def cards_delete(card_id: str, request: Request) -> dict[str, Any]:
    from odie.signin import wallet
    store = request.app.state.store
    if not wallet.delete(store, card_id):
        raise HTTPException(404, "No such card")
    return {"cards": wallet.listing(store)}


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


@router.get("/setup/server_models")
async def setup_server_models(kind: str, url: str) -> dict[str, Any]:
    """The embedding models a server somewhere else offers, for the address form on the setup screen and in Settings."""
    from odie.vault import embed
    models, problem = await embed.server_models(kind, url)
    return {"models": models, "problem": problem}


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
    libra_style: str | None = Field(None, max_length=40)  # Libra's tone when a reply names none; "" for none
    libra_url: str | None = Field(None, max_length=300)  # where the Libra server answers


class TtsIn(BaseModel):
    text: str
    tone: str | None = Field(None, max_length=40)  # the reply's tone, sent with each sentence of it (the Mac's Talk)


class AskIn(BaseModel):
    question: str


def _voice_guard():
    from odie import voice
    try:
        return voice.api_key()
    except voice.VoiceUnavailable as e:
        raise HTTPException(503, str(e))


def _speakable(text: str) -> str:
    """Markdown to plain speech: drop symbols that would be read out, keeping Libra's voice markup whole
    (odie.voice_libra; the engine that can't use it strips it). "**Hi** <laugh> `x`" -> "Hi <laugh> x"."""
    from odie import voice_libra
    return voice_libra.keeping_markers(_plain_speech, text)


def _plain_speech(text: str) -> str:
    import re
    t = re.sub(r"```.*?```", " ", text, flags=re.S)
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
    return re.sub(r"[*_#`>|]+", "", t).strip()


@router.get("/voice")
async def voice_get(request: Request):
    from odie import machine, voice
    from odie.secrets import load_secret
    store = request.app.state.store
    phonon_ok = await voice.phonon_available()  # Ollama has a phonon model: one quick /api/tags per Settings open
    if phonon_ok:
        await voice.phonon_voices()  # Ollama's list, asked once per process
    engine, current = voice.get_tts(store)
    openai_ok = bool(load_secret("OPENAI_API_KEY"))
    local_ok = await voice.own_server_can_speak() if machine.local_voice_wanted() else False  # not asked for where it can't run
    hidden = voice.disabled()
    voice_settings = store.get_setting("voice") or {}
    libra_url = voice.voice_libra.server_url(voice_settings)
    libra_ok = await voice.voice_libra.available(libra_url)  # one quick /health per Settings open

    def ready(engine_id: str, local: bool) -> bool:
        """Whether an engine can speak now: Phonon when Ollama has it, Libra when its server answers, Odie's own
        server when it can, OpenAI with its key. phonon, Ollama has it -> True; libra, nothing on its address ->
        False; kokoro, voice server not set up -> False; openai, no key -> False."""
        if engine_id == "phonon":
            return phonon_ok
        if engine_id == "libra":
            return libra_ok
        return local_ok if local else openai_ok
    engines = [{"id": k, **v, "available": ready(k, v["local"]), "voices": voice.engine_voices(k, store)}
               for k, v in voice.ENGINES.items() if k not in hidden and (v["local"] or openai_ok)]  # OpenAI only with its key
    # local_voice: whether Odie's own voice is meant to run on this Mac at all (False on an Intel Mac: Settings says why)
    return {"available": openai_ok, "engine": engine, "voice": current, "talk_voice": voice.get_voice(store), "engines": engines,
            "local_voice": machine.local_voice_wanted(),
            "libra": {"url": libra_url, "tone": voice.voice_libra.settings_tone(voice_settings) or "",
                      "tones": voice.voice_libra.TONES, "answering": libra_ok},
            "reminders_spoken": voice.reminders_spoken(store),
            "voices": voice.VOICES, "models": {"tts": voice.tts_model(), "stt": voice.stt_model(), "realtime": voice.REALTIME_MODEL}}


@router.put("/voice")
async def voice_put(body: VoiceIn, request: Request):
    from odie import voice
    store = request.app.state.store
    if body.libra_url is not None:
        problem = voice.voice_libra.url_problem(body.libra_url)
        if problem is not None:
            raise HTTPException(422, problem)
        voice.set_libra(store, url=body.libra_url.strip())
    if body.libra_style is not None:
        tone = body.libra_style.strip().lower()
        if tone and tone not in voice.voice_libra.TONES:
            raise HTTPException(422, f"Libra has no tone called {body.libra_style!r}.")
        voice.set_libra(store, tone=tone)
    engine, v = voice.set_tts(store, body.engine, body.voice)
    await voice.settle_worker(store)  # away from Kokoro: Odie's own voice server stops
    request.app.state.runner.invalidate_prompt()  # to or from Libra: the voice markup rule follows on the next message
    if engine == "openai" and body.voice:
        voice.set_voice(store, body.voice)  # an OpenAI voice is also Talk's voice
    if body.reminders_spoken is not None:
        voice.set_reminders_spoken(store, body.reminders_spoken)
    return {"engine": engine, "voice": v, "reminders_spoken": voice.reminders_spoken(store)}


def _preview_path(request: Request, engine: str, voice_id: str) -> Path:
    """Where a voice's preview is kept: one file per engine, voice, assistant name and user name (a rename makes a new
    one). The voice id goes in as a slug: Phonon's names have spaces, accents and brackets ("Noémie (phonon:fr)")."""
    from odie import persona, profile
    name = persona.get(request.app.state.store)["name"]
    user = profile.get(request.app.state.store)["user_name"]
    folder = config.settings.data_dir / "voice"
    folder.mkdir(parents=True, exist_ok=True)
    ext = "mp3" if engine == "openai" else "wav"
    return folder / f"preview-{_preview_name(engine, voice_id)}-{slug(name)}-{slug(user or 'you')}.{ext}"


def _preview_name(engine: str, voice_id: str) -> str:
    """A voice's part of its preview file name: a readable slug plus a short hash of the exact id, so ids the slug
    makes alike stay apart. "Zoey" and "ZOEY" -> "phonon-zoey-1a2b3c" and "phonon-zoey-9f8e7d"; two Cyrillic names
    (both slug to "custom") -> two files."""
    import hashlib
    exact = hashlib.sha1(voice_id.encode()).hexdigest()[:6]
    return f"{engine}-{slug(voice_id)}-{exact}"


async def _preview(request: Request, engine: str, voice_id: str) -> Response:
    from odie import persona, profile, voice
    store = request.app.state.store
    if engine not in voice.ENGINES or engine in voice.disabled() or voice_id not in {v["id"] for v in voice.engine_voices(engine, store)}:
        raise HTTPException(404, "no such voice")
    name = persona.get(store)["name"]
    user = profile.get(store)["user_name"]
    path = _preview_path(request, engine, voice_id)
    ext = path.suffix.lstrip(".")
    if not path.exists():
        hi = f"Hi {user}" if user else "Hi"
        line = (f"{hi}! <laugh> I'm {name}. This is how I sound when I read to you." if engine == "maya1"
                else f"{hi}, I'm {name}. This is how I'll sound when I read to you.")
        try:
            if engine == "openai":
                audio = await voice.tts(line, voice_id, key=_voice_guard())
            elif engine == "libra":
                audio = await voice.libra_tts(store, f"{line} <chuckle>", voice_id, tone="cheerful")
            else:
                audio = await voice.local_tts(engine, line, voice_id)
        except voice.VoiceUnavailable as e:
            raise HTTPException(503, str(e))
        except httpx.HTTPError as e:
            raise HTTPException(502, f"{engine} preview failed: {type(e).__name__}")
        path.write_bytes(audio)
    return Response(path.read_bytes(), media_type="audio/mpeg" if ext == "mp3" else "audio/wav", headers={"Cache-Control": "public, max-age=86400"})


class PhononCheckIn(BaseModel):
    name: str = Field("", max_length=400)  # longer than a voice name may be: typed_name_problem says why it's refused


@router.post("/voice/phonon/check")
async def voice_phonon_check(body: PhononCheckIn, request: Request):
    """"Another voice": the typed name is tried against the Phonon models Ollama has; the first that speaks it keeps
    it as the chosen voice, and the line it spoke becomes its preview. A name no model has, or one not worth asking
    about, is a 422 that says why in words."""
    from odie import voice
    store = request.app.state.store
    try:
        kept = await voice.check_phonon_voice(store, body.name)
    except ValueError as e:
        raise HTTPException(422, str(e))
    except voice.VoiceUnavailable as e:
        raise HTTPException(503, str(e))
    if kept["audio"] is not None:  # a voice Ollama already lists keeps its own preview
        _preview_path(request, "phonon", kept["id"]).write_bytes(kept["audio"])
    await voice.settle_worker(store)
    engine, current = voice.get_tts(store)
    return {"engine": engine, "voice": current, "voices": voice.engine_voices("phonon", store)}


@router.delete("/voice/phonon/voices/{voice_id}")
async def voice_phonon_forget(voice_id: str, request: Request):
    """Removes a voice kept with "Another voice"; the chosen voice falls back to Phonon's default when it was this one."""
    from odie import voice
    store = request.app.state.store
    voice.forget_phonon_voice(store, voice_id)
    _preview_path(request, "phonon", voice_id).unlink(missing_ok=True)
    engine, current = voice.get_tts(store)
    return {"engine": engine, "voice": current, "voices": voice.engine_voices("phonon", store)}


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
    if not voice.voice_libra.hidden(text):
        raise HTTPException(400, "nothing to say")
    try:
        audio, media = await voice.speak(request.app.state.store, text, tone=body.tone)
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
    async for ev in request.app.state.runner.chat(question, thinking=False, session_id=f"voice-{today}"):  # quick answers
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
    await request.app.state.runner.post_message(text, kind="talk")
    return {"saved": True}


# --- Live hearing: the Mac's microphone through Odie's own voice server (voice_server/server.py, /stt/stream) ---
NOT_RUNNING = "Odie's local voice isn't running"
VOICE_OFF = "Odie's local voice is off (ODIE_VOICE=off)"


def _close_reason(text: str) -> str:
    """A WebSocket close reason fits in 123 bytes: a longer problem is cut there.
    "local voice isn't set up: run `uv sync` in /a/very/long/path/voice_server" -> its first 123 bytes."""
    return text.encode()[:123].decode(errors="ignore")


async def _voice_ears_ready() -> str | None:
    """Whether Odie's own voice server is up and can hear, started first if it is stopped (read-aloud with Phonon leaves
    it stopped); None when it is ready, else why not (the 4503 reason). Stopped but set up -> started, None; never set
    up -> "local voice isn't set up: ..."; running without the hearing models -> "Odie's local voice can't hear ...";
    no worker at all (ODIE_VOICE=off) -> VOICE_OFF: whatever answers on ODIE_VOICE_PORT is someone else's service."""
    from odie import voice, voice_worker
    worker = voice_worker.current
    if worker is None:
        return VOICE_OFF
    if not await worker.ensure():
        return worker.problem or NOT_RUNNING
    if not await voice.hearing_available():  # it runs now, so its /health decides
        return "Odie's local voice can't hear: run `uv sync` in voice_server"
    return None


async def _app_to_voice(websocket: WebSocket, ears) -> None:
    """The app's frames to the voice server as they came: audio as bytes, {"type":"end"} as text. Ends when the app
    goes, or when the voice server has closed the stream (its final words sent)."""
    import websockets
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return
        try:
            if message.get("bytes") is not None:
                await ears.send(message["bytes"])
            elif message.get("text") is not None:
                await ears.send(message["text"])
        except websockets.ConnectionClosedOK:
            return


def _relayed_close(code: int | None) -> int:
    """The close code to pass on to the app when the voice server closed its stream with an error. A code that may be
    sent in a close frame is passed as it is; a missing or reserved one (no close frame, 1005, 1006, 1015) becomes 1011.
    1011 -> 1011; 4500 -> 4500; None -> 1011; 1006 -> 1011."""
    if code is None or code in (1005, 1006, 1015):
        return 1011
    return code


async def _voice_to_app(ears, websocket: WebSocket) -> None:
    """The voice server's events (ready, speech, words, error) to the app. Ends when the voice server closes the stream
    or the app has gone. When the voice server closes with an error (it has sent its `error` event first), the app is
    closed with the same code and reason: the failure is already reported, so no traceback."""
    import websockets
    from starlette.websockets import WebSocketDisconnect
    try:
        async for frame in ears:
            if isinstance(frame, bytes):
                await websocket.send_bytes(frame)
            else:
                await websocket.send_text(frame)
    except WebSocketDisconnect:
        return
    except websockets.ConnectionClosedError as e:
        code = e.rcvd.code if e.rcvd is not None else None
        reason = e.rcvd.reason if e.rcvd is not None else ""
        await _close_app(websocket, _relayed_close(code), _close_reason(reason))


async def _pass_through(websocket: WebSocket, ears) -> None:
    """Copies frames both ways until either side is done, then stops the other copy. A failure in either is raised
    (every finished copy's exception is read first, so none is left "never retrieved"). Cancelled (Odie shutting
    down), both copies are cancelled and awaited, so none is left pending."""
    copies = [asyncio.create_task(_app_to_voice(websocket, ears)), asyncio.create_task(_voice_to_app(ears, websocket))]
    try:
        done, _ = await asyncio.wait(copies, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for copy in copies:
            copy.cancel()
        await asyncio.gather(*copies, return_exceptions=True)
    failures = [copy.exception() for copy in done if not copy.cancelled()]
    for failure in failures:
        if failure is not None:
            raise failure


async def _close_app(websocket: WebSocket, code: int, reason: str = "") -> None:
    """Closes the app's side unless it has already gone (then there's no one to tell).
    The app still connected -> closed with `code`; the app already gone, or going while we close -> nothing."""
    from starlette.websockets import WebSocketDisconnect, WebSocketState
    if websocket.client_state != WebSocketState.CONNECTED or websocket.application_state != WebSocketState.CONNECTED:
        return
    try:
        await websocket.close(code=code, reason=reason)
    except (RuntimeError, OSError, WebSocketDisconnect):
        pass  # it went while we were closing


async def _listen(websocket: WebSocket) -> None:
    """One listen, after the app's socket is accepted: the voice server ready and hearing, then the pass-through."""
    import websockets

    from odie import voice
    why_not = await _voice_ears_ready()
    if why_not:
        await _close_app(websocket, 4503, _close_reason(why_not))
        return
    try:
        ears = await websockets.connect(voice.hearing_url(), max_size=None, open_timeout=5, proxy=None)  # never a proxy
    except (OSError, TimeoutError, websockets.InvalidHandshake):
        await _close_app(websocket, 4503, NOT_RUNNING)
        return
    code = 1000
    try:
        await _pass_through(websocket, ears)
    except Exception:  # the app is told 1011; it falls back to its own listening
        log.warning("talk listen: the pass-through to the voice server failed", exc_info=True)
        code = 1011
    finally:
        await ears.close()
    await _close_app(websocket, code)


@router.websocket("/talk/listen")
async def talk_listen(websocket: WebSocket) -> None:
    """Live hearing for a paired app (behind pairing, like every API): its 16 kHz PCM frames go to Odie's own voice
    server's /stt/stream and that server's ready/speech/words/error events come back, as they are. Nothing is stored
    or logged. 4503 when the voice server can't be started or can't hear; 1011 on an unexpected failure."""
    from odie import voice
    await websocket.accept()  # first, so a 4503 reaches the app (a close before accept is only an HTTP 403 there)
    voice.hearing_streams += 1  # before the worker starts (up to 30 s): settle_worker must not stop it meanwhile
    try:
        await _listen(websocket)
    finally:
        voice.hearing_streams -= 1


# --- Persona: the assistant's name and picture ---
class PersonaIn(BaseModel):
    name: str


def _persona_out(p: dict) -> dict:
    return {"name": p["name"], "avatar_url": f"/api/persona/avatar/{p['avatar']}" if p.get("avatar") else None}


def _personality_out(p) -> dict:
    """A personality's name and picture, in the shape /persona gives for everyday Odie."""
    return _persona_out({"name": p.name, "avatar": p.avatar})


def _picked(request: Request):
    """The personality a request picked (odie.personalities.Personality), or None when it is for everyday Odie."""
    from odie import personalities
    return personalities.get(request.app.state.store, _personality(request))


def _forget_prompts(request: Request) -> None:
    """A name or a SOUL changed: every thread builds its prompt again on its next message."""
    inv = getattr(request.app.state.runner, "invalidate_prompt", None)
    if inv:
        inv()


# The name, picture and SOUL routes below serve whoever the app is talking to: everyday Odie, or (with a pick) that
# personality. Settings shows and edits the picked one with the same boxes.
@router.get("/persona")
async def persona_get(request: Request):
    from odie import persona
    picked = _picked(request)
    if picked is not None:
        return _personality_out(picked)
    return _persona_out(persona.get(request.app.state.store))


@router.put("/persona")
async def persona_put(body: PersonaIn, request: Request):
    from odie import persona, personalities
    store = request.app.state.store
    picked = _picked(request)
    if picked is not None:
        try:
            renamed = personalities.rename(store, picked.id, body.name)
        except ValueError as problem:  # empty, Odie's own name, or one another personality has
            raise HTTPException(422, str(problem))
        _forget_prompts(request)
        store.audit("user", "personality_renamed", result_summary=renamed.name)
        return _personality_out(renamed)
    p = persona.set_name(store, body.name)
    _forget_prompts(request)
    store.audit("user", "persona_renamed", result_summary=p["name"])
    return _persona_out(p)


@router.post("/persona/avatar")
async def persona_avatar(request: Request, file: UploadFile = File(...)):
    from odie import persona, personalities
    store = request.app.state.store
    picked = _picked(request)
    data = await file.read()
    if len(data) > 15 * 1024 * 1024:
        raise HTTPException(413, "Photo too large (15 MB max)")
    try:
        if picked is None:
            return _persona_out(persona.save_avatar(store, data))
        picture = persona.store_picture(data)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(400, f"Not an image I can read: {type(e).__name__}")
    with_picture = personalities.set_avatar(store, picked.id, picture)
    persona.delete_picture(picked.avatar)  # the picture it had before
    return _personality_out(with_picture)


@router.delete("/persona/avatar")
async def persona_avatar_clear(request: Request):
    from odie import persona, personalities
    store = request.app.state.store
    picked = _picked(request)
    if picked is None:
        return _persona_out(persona.clear_avatar(store))
    with_the_orb = personalities.set_avatar(store, picked.id, None)
    persona.delete_picture(picked.avatar)
    return _personality_out(with_the_orb)


# --- Personalities: other ways for the assistant to be (odie.personalities) ---
class PersonalityIn(BaseModel):
    name: str


def _personality_row(store, p) -> dict:
    """One personality for the switcher: its name and picture, how many threads it has, and how many of its cards are
    waiting for a tap (the switcher says "needs you")."""
    from odie import personalities
    its_threads = set(personalities.sessions_of(store, p.id))
    waiting = [a for a in store.pending_approvals() if a["session_id"] in its_threads]
    return {"id": p.id, **_personality_out(p), "threads": len(its_threads), "waiting": len(waiting)}


@router.get("/personalities")
async def personalities_list(request: Request):
    from odie import personalities
    store = request.app.state.store
    # everyday_waiting: everyday Odie's own cards, so a chat with a personality can show that Odie needs a tap
    everyday_cards = [a for a in store.pending_approvals() if personalities.of_session(store, a["session_id"]) == personalities.ODIE]
    return {"personalities": [_personality_row(store, p) for p in personalities.list_all(store)],
            "everyday_waiting": len(everyday_cards)}


@router.post("/personalities")
async def personalities_create(body: PersonalityIn, request: Request):
    """A new personality, with the orb and the default instructions; the app then switches to it."""
    from odie import personalities
    store = request.app.state.store
    try:
        made = personalities.create(store, body.name)
    except ValueError as problem:
        raise HTTPException(422, str(problem))
    store.audit("user", "personality_made", result_summary=made.name)
    return _personality_row(store, made)


@router.delete("/personalities/{pid}")
async def personalities_delete(pid: str, request: Request):
    """Erase a personality with its threads, memory, instructions and picture, for good (odie.personalities.delete).
    The activity log keeps only that one was deleted, not which."""
    from odie import personalities
    store = request.app.state.store
    if personalities.get(store, pid) is None:
        raise HTTPException(404, "no such personality")
    erased = await personalities.delete(store, request.app.state.runner, pid)
    store.audit("user", "personality_deleted", result_summary=f"{erased['threads']} thread(s)")
    return {"ok": True, **erased}


class ProactiveIn(BaseModel):
    on: bool


def _proactive_out(store, pid: str) -> dict:
    """The picked personality's Proactive intelligence switch: offered only with a mail or calendar app of its own
    (odie.watch.owner.own_inbox_apps), and whether it is on. Everyday Odie: never offered (its watch keeps its own
    setting)."""
    from odie.plugins.mcp import read_config
    from odie.watch import owner
    servers, _ = read_config()
    apps = owner.own_inbox_apps(store, servers, pid)
    return {"offered": bool(apps), "on": owner.is_proactive(store, pid), "apps": apps}


@router.get("/proactive")
async def proactive_get(request: Request):
    return _proactive_out(request.app.state.store, _personality(request))


@router.put("/proactive")
async def proactive_put(body: ProactiveIn, request: Request):
    """Switches the picked personality's own background mail and calendar check on or off. 409 when it has no mail or
    calendar app of its own to check (and for everyday Odie, which has no such switch)."""
    from odie.watch import owner
    store = request.app.state.store
    pid = _personality(request)
    if body.on and not _proactive_out(store, pid)["offered"]:
        raise HTTPException(409, "It has no mail or calendar app of its own to check.")
    if pid:
        owner.set_proactive(store, pid, body.on)
        said = "off"
        if body.on:
            said = "on"
        store.audit("user", "proactive", result_summary=said)
    return _proactive_out(store, pid)


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
    from odie import personalities, profile
    picked = _picked(request)
    if picked is not None:  # a personality's own instructions, or the default personality under its name
        own = personalities.load_soul(picked.id)
        text = own or identity(Who(user=profile.get(request.app.state.store)["user_name"], assistant=picked.name))
        path = personalities.folder(picked.id) / "SOUL.md"
        return {"text": text, "custom": own is not None, "path": str(path)}
    custom = SOUL_PATH.exists() and SOUL_PATH.read_text().strip() != ""
    if custom:
        text = SOUL_PATH.read_text()
    else:
        store = request.app.state.store
        text = identity(Who(user=profile.get(store)["user_name"], assistant=persona.get(store)["name"]))
    return {"text": text, "custom": bool(custom), "path": str(SOUL_PATH)}


@router.put("/soul")
async def soul_put(body: SoulIn, request: Request):
    from odie import personalities
    picked = _picked(request)
    if picked is not None:
        custom = personalities.save_soul(picked.id, body.text)
        _forget_prompts(request)
        request.app.state.store.audit("user", "soul_updated", result_summary=f"a personality's ({picked.name})")
        return {"ok": True, "custom": custom}
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
    """The watch's card for Pulse: the last check's line, the next events, each source's status, and how many cards
    are new since Pulse was last opened (loops made cards since then; one put off with Later isn't counted). needs_you
    is always empty now: what needs the user is a loop (GET /api/needs_you)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from odie.loops import cards as loop_cards
    from odie.watch import report
    from odie.watch.owner import key
    store = request.app.state.store
    pid = _personality(request)
    card = store.get_setting(key(report.CARD, pid))  # the picked one's own watch
    if not card:
        return {"off": "The first check runs a minute after Odie starts.", "needs_you": [], "events": [], "unseen": 0}
    now = datetime.now(ZoneInfo(config.settings.timezone))
    seen_at = card.get("seen_at") or ""
    unseen = [lp for lp in loop_cards.ready_loops(store, pid, now) if (lp.get("shown_at") or "") > seen_at]
    shown = {k: v for k, v in card.items() if k != "needs_you"}
    return {**shown, "needs_you": [], "unseen": len(unseen)}


@router.get("/needs_you")
async def needs_you_get(request: Request) -> dict[str, Any]:
    """A Pulse's cards (odie.watch.needs), for whoever is picked: everyday Odie's (as Today always was) or a
    personality's own. With them: the watch's last check for the line under them, what the watch did, what Odie is
    still on (loops it is working on) and the loops it closed today (each with Reopen). Odie's Pulse also lists the
    others as a count only ("Mira: 2 waiting"); a personality's says whether its Proactive intelligence is on."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from odie import personalities
    from odie.loops import cards as loop_cards
    from odie.watch import needs, report
    from odie.watch.owner import key
    store = request.app.state.store
    pid = _personality(request)
    now = datetime.now(ZoneInfo(config.settings.timezone))
    card = store.get_setting(key(report.CARD, pid)) or {}
    watch = {k: card.get(k) for k in ("checked_at", "line", "off", "sources", "events") if k in card}
    if not card and not pid:
        watch = {"off": "The first check runs a minute after Odie starts."}
    items = needs.cards(store, now, pid)
    from odie.workers import cards as job_cards
    on_it = [*job_cards.on_it(store, pid), *loop_cards.on_it(store, pid)]  # running jobs (with Stop), then loops
    out = {"items": items, "counts": needs.counts(items), "watch": watch, "notes": needs.recent_notes(store, now, pid),
           "on_it": on_it, "loops_done": loop_cards.done_today(store, pid, now),
           "jobs_done": job_cards.done_today(store, pid, now)}
    if pid:
        out["proactive"] = _proactive_out(store, pid)
        return out
    others = []
    for p in personalities.list_all(store):
        waiting = len(needs.cards(store, now, p.id))
        if waiting:
            others.append({"id": p.id, "name": p.name, "waiting": waiting})
    out["others"] = others
    return out


@router.post("/loops/{loop_id}/done")
async def loop_done(loop_id: int, request: Request) -> dict[str, Any]:
    """A loop card's Done: off the list and no longer followed. Only the picked one's own loop (else 404)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from odie.loops import ledger
    store = request.app.state.store
    loop = ledger.get(store, loop_id)
    if loop is None or loop["personality"] != _personality(request) or loop["state"] not in ledger.OPEN:
        raise HTTPException(404, "That card isn't there any more.")
    ledger.done(store, loop_id, datetime.now(ZoneInfo(config.settings.timezone)))
    ledger.update(store, loop_id, datetime.now(ZoneInfo(config.settings.timezone)), tapped="done")
    return {"ok": True}


@router.post("/loops/{loop_id}/reopen")
async def loop_reopen(loop_id: int, request: Request) -> dict[str, Any]:
    """Reopen: a loop closed wrongly (by Odie's evidence, or his Done) opens again and is looked at once more; for
    REOPEN_DAYS after its close (odie.loops.ledger.may_reopen)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from odie.loops import ledger
    store = request.app.state.store
    now = datetime.now(ZoneInfo(config.settings.timezone))
    loop = ledger.get(store, loop_id)
    if loop is None or loop["personality"] != _personality(request) or not ledger.may_reopen(loop, now):
        raise HTTPException(404, "Nothing to reopen.")
    ledger.reopen(store, loop_id, now)
    store.audit("user", "loop_reopen", result_summary=loop["title"])
    return {"ok": True}


@router.get("/loops/{loop_id}")
async def loop_get(loop_id: int, request: Request) -> dict[str, Any]:
    """One of the picked one's loops with all its evidence (each line with its id), for Split's chooser."""
    from odie.loops import ledger
    store = request.app.state.store
    loop = ledger.get(store, loop_id)
    if loop is None or loop["personality"] != _personality(request):
        raise HTTPException(404, "That card isn't there any more.")
    lines = [{"id": e["id"], "at": e["at"], "source": e["source"], "fact": e["fact"]}
             for e in ledger.events(store, loop_id) if e["ref"] not in ("later", "split", "pushed")]
    return {"id": loop["id"], "title": loop["title"], "kind": loop["kind"], "state": loop["state"], "evidence": lines}


class SplitIn(BaseModel):
    events: list[int]


@router.post("/loops/{loop_id}/split")
async def loop_split(loop_id: int, body: SplitIn, request: Request) -> dict[str, Any]:
    """Split: a merge was wrong; the evidence he picked becomes a loop of its own (odie.loops.ledger.split)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from odie.loops import ledger
    store = request.app.state.store
    loop = ledger.get(store, loop_id)
    if loop is None or loop["personality"] != _personality(request) or loop["state"] not in ledger.OPEN:
        raise HTTPException(404, "That card isn't there any more.")
    now = datetime.now(ZoneInfo(config.settings.timezone))
    try:
        new_id = ledger.split(store, loop_id, body.events, now)
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    ledger.update(store, loop_id, now, tapped="split")
    store.audit("user", "loop_split", args={"events": body.events}, result_summary=f"#{loop_id} -> #{new_id}")
    return {"ok": True, "id": new_id}


@router.post("/loops/{loop_id}/merge")
async def loop_merge(loop_id: int, request: Request) -> dict[str, Any]:
    """A tested card's [Merge]: his tap is the approval (proactive design §16). The command is code's, pinned to the
    tested commit (odie.loops.merge); the terminal's key can't reach this route, and no model has a tool for it."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from odie.loops import ledger, merge
    store = request.app.state.store
    loop = ledger.get(store, loop_id)
    if loop is None or loop["personality"] != _personality(request):
        raise HTTPException(404, "That card isn't there any more.")
    try:
        why = await merge.merge(store, loop_id, datetime.now(ZoneInfo(config.settings.timezone)))
    except merge.MergeRefused as e:
        raise HTTPException(409, str(e)) from e
    return {"ok": True, "closed": why}


def _own_open_loop(request: Request, loop_id: int) -> dict:
    """The picked one's own open loop by its number, or 404 "That card isn't there any more."."""
    from odie.loops import ledger
    loop = ledger.get(request.app.state.store, loop_id)
    if loop is None or loop["personality"] != _personality(request) or loop["state"] not in ledger.OPEN:
        raise HTTPException(404, "That card isn't there any more.")
    return loop


class TapIn(BaseModel):
    tap: str


@router.post("/loops/{loop_id}/tap")
async def loop_tap(loop_id: int, body: TapIn, request: Request) -> dict[str, Any]:
    """The app tapped a loop card's own move (its chat request, its page): logged for learning (odie.loops.learn). Only
    "move"; it does nothing else (the move itself runs in the app)."""
    from odie.loops import ledger
    if body.tap != "move":
        raise HTTPException(422, "Only a card's move is noted here.")
    _own_open_loop(request, loop_id)
    ledger.update(request.app.state.store, loop_id, _local_now(), tapped="move")
    return {"ok": True}


@router.post("/loops/{loop_id}/less")
async def loop_less(loop_id: int, request: Request) -> dict[str, Any]:
    """"Less like this" in a card's menu: his Quiet rule, in plain words he sees on Pulse and can delete
    (odie.loops.quiet). Only his tap writes one: the terminal's key can't reach this route, and no model has a tool
    for it. A pull request or a promise is never quieted (409)."""
    from odie.loops import quiet
    loop = _own_open_loop(request, loop_id)
    try:
        rule = quiet.less_like_this(request.app.state.store, loop, _local_now())
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    request.app.state.store.audit("user", "quiet_rule", result_summary=rule["text"])
    return {"ok": True, "rule": rule}


@router.post("/loops/{loop_id}/forget")
async def loop_forget(loop_id: int, request: Request) -> dict[str, Any]:
    """"Forget this" in a card's menu: the loop and its evidence are deleted (odie.loops.ledger.forget); nothing of it
    is remembered."""
    from odie.loops import ledger
    loop = _own_open_loop(request, loop_id)
    ledger.forget(request.app.state.store, loop_id)
    request.app.state.store.audit("user", "loop_forget", result_summary=f"#{loop_id}")
    return {"ok": True, "forgot": loop["id"]}


@router.get("/quiet")
async def quiet_get(request: Request) -> dict[str, Any]:
    """The picked one's Quiet rules (his, each deletable) and the kinds Odie learned to put in the digest (each with
    Undo)."""
    from odie.loops import learn, quiet
    store = request.app.state.store
    pid = _personality(request)
    return {"rules": quiet.rules(store, pid), "learned": learn.learned_list(store, pid)}


@router.delete("/quiet/{rule_id}")
async def quiet_delete(rule_id: int, request: Request) -> dict[str, Any]:
    """His delete on a Quiet rule: cards like that come back."""
    from odie.loops import quiet
    if not quiet.delete(request.app.state.store, _personality(request), rule_id):
        raise HTTPException(404, "That rule isn't there any more.")
    return {"ok": True}


@router.post("/quiet/{proposal_id}/accept")
async def quiet_accept(proposal_id: int, request: Request) -> dict[str, Any]:
    """"Add the rule" on a rule the evening review proposed: the rule as the card showed it (kept with the proposal,
    never sent by the app) is written. Only the picked one's own waiting proposal (else 404)."""
    from odie.loops import quiet
    rule = quiet.accept(request.app.state.store, _personality(request), proposal_id, _local_now())
    if rule is None:
        raise HTTPException(404, "That card isn't there any more.")
    request.app.state.store.audit("user", "quiet_rule", result_summary=rule["text"])
    return {"ok": True, "rule": rule}


@router.post("/learned/{entry_id}/undo")
async def learned_undo(entry_id: int, request: Request) -> dict[str, Any]:
    """Undo on "Fewer cards for X" (the notice, or Pulse's Quiet list): that kind is cards again, for good."""
    from odie.loops import learn
    if not learn.undo(request.app.state.store, _personality(request), entry_id):
        raise HTTPException(404, "That card isn't there any more.")
    return {"ok": True}


@router.post("/notices/undo")
async def notice_undo(body: WatchDoneIn, request: Request) -> dict[str, Any]:
    """Undo on a notice, by the card's ref: "rule:3" removes that rule from the picked one's memory
    (odie.memory.rules); "faded:2" brings a put-away skill back (odie.skills.fade, everyday Odie's Pulse only). 404
    when there is no such notice, or it can't be undone any more."""
    from odie.memory import rules
    from odie.skills import builder, fade
    store = request.app.state.store
    pid = _personality(request)
    rule_id = rules.number_of(body.ref)
    if rule_id is not None:
        memory = request.app.state.runner.memory_of(pid)
        if not rules.undo(store, memory, pid, rule_id):
            raise HTTPException(404, "That card isn't there any more.")
        store.audit("user", "rule_undone", result_summary=body.ref)
        return {"ok": True}
    faded_id = fade.number_of(body.ref)
    if faded_id is not None and not pid:
        name = fade.restore(store, faded_id, _local_now(), builder.user_dir())
        if name is None:
            raise HTTPException(404, "That skill can't be brought back: its folder is gone or the name is taken.")
        if builder.hooks.get("reload"):
            await builder.hooks["reload"]()
        store.audit("user", "skill_restored", result_summary=name)
        return {"ok": True, "skill": name}
    raise HTTPException(404, "That card isn't there any more.")


@router.get("/digest")
async def digest_get(request: Request) -> dict[str, Any]:
    """What Pulse shows on opening (odie.loops.digest.for_pulse): today's evening digest (with the review's changes,
    each with Undo) until Got it, or "while you were away" after 3+ hours away; {"digest": null} otherwise."""
    from odie.loops import digest, review
    store = request.app.state.store
    pid = _personality(request)
    now = _local_now()
    changes = [{"id": c["id"], "words": c["words"]} for c in review.changes_of(store, pid, now.date().isoformat())]
    return {"digest": digest.for_pulse(store, pid, now, changes)}


class DigestSeenIn(BaseModel):
    dismiss: bool = False


@router.post("/digest/seen")
async def digest_seen(body: DigestSeenIn, request: Request) -> dict[str, Any]:
    """Pulse was opened (the 3-hour "away" counts from now); dismiss: his Got it on the evening digest."""
    from odie.loops import digest
    digest.seen(request.app.state.store, _personality(request), _local_now(), dismiss=body.dismiss)
    return {"ok": True}


@router.post("/review/{change_id}/undo")
async def review_undo(change_id: int, request: Request) -> dict[str, Any]:
    """Undo on one of the evening review's changes (odie.loops.review.undo): the picked one's own, once."""
    from odie.loops import review
    if not review.undo(request.app.state.store, _personality(request), change_id, _local_now()):
        raise HTTPException(404, "That can't be undone any more.")
    request.app.state.store.audit("user", "review_undo", result_summary=f"change {change_id}")
    return {"ok": True}


@router.post("/offers/{offer_id}/track")
async def offer_track(offer_id: int, request: Request) -> dict[str, Any]:
    """A "Track this?" card's Track: his tap makes the loop (his, with its due time and a reminder at that time,
    odie.loops.offers.track). Only the picked one's own waiting offer (else 404); the terminal's key can't reach this
    route (odie.devices.terminal_may), and no model has a tool for it."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from odie.loops import offers
    store = request.app.state.store
    loop_id = offers.track(store, _personality(request), offer_id, datetime.now(ZoneInfo(config.settings.timezone)))
    if loop_id is None:
        raise HTTPException(404, "That card isn't there any more.")
    store.audit("user", "offer_track", result_summary=f"offer {offer_id} -> loop #{loop_id}")
    return {"ok": True, "loop": loop_id}


class NowIn(BaseModel):
    lines: list[str]
    proposal: int | None = None  # he edited Odie's proposal and saved: it is answered


def _local_now():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    return datetime.now(ZoneInfo(config.settings.timezone))


@router.get("/now")
async def now_get(request: Request) -> dict[str, Any]:
    """The picked one's Now list (odie.loops.now) and Odie's proposal waiting for an answer, if any."""
    from odie.loops import now as now_list
    store = request.app.state.store
    pid = _personality(request)
    proposal = now_list.open_proposal(store, pid)
    return {"lines": now_list.lines(store, pid), "proposal": proposal, "most": now_list.MOST_LINES}


@router.put("/now")
async def now_put(body: NowIn, request: Request) -> dict[str, Any]:
    """His Now list as he wrote it (add, remove, reword, reorder): his tap in the app is the only way it is written.
    422 with words he can read when it is too long or holds a secret. With `proposal`: Odie's proposal he edited is
    answered too."""
    from odie.loops import now as now_list
    store = request.app.state.store
    pid = _personality(request)
    try:
        kept = now_list.save(store, pid, body.lines, _local_now())
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    if body.proposal is not None:
        now_list.edited(store, pid, body.proposal)
    store.audit("user", "now_saved", result_summary=f"{len(kept)} lines")
    return {"ok": True, "lines": kept}


@router.post("/now/draft")
async def now_draft(request: Request) -> dict[str, Any]:
    """"Draft it for me": Odie drafts the list from what it remembers, his own words this week and the week's loops
    (one call with no tools, on the picked one's brain). Nothing is saved: the app shows the draft to edit and Save."""
    from odie import brains
    from odie.loops import now as now_list
    store = request.app.state.store
    runner = request.app.state.runner
    pid = _personality(request)

    async def think(prompt: str, instruction: str) -> str:
        return await runner.background_turn(prompt, timeout=120, instruction=instruction, bare=True, owner=pid)
    try:
        drafted = await now_list.draft(store, pid, _local_now(), think, runner.memory_index(pid))
    except brains.BrainGone as e:
        raise HTTPException(409, str(e)) from e
    if drafted is None:
        raise HTTPException(409, "I couldn't draft it just now. Write a line or two, or try again.")
    return {"lines": drafted}


@router.post("/now/{proposal_id}/accept")
async def now_accept(proposal_id: int, request: Request) -> dict[str, Any]:
    """Accept on Odie's proposal card: its lines, as kept with the proposal (never sent by the app), become the Now
    list. Only the picked one's own waiting proposal (else 404); the terminal's key can't reach this route."""
    from odie.loops import now as now_list
    store = request.app.state.store
    pid = _personality(request)
    if not now_list.accept(store, pid, proposal_id, _local_now()):
        raise HTTPException(404, "That card isn't there any more.")
    store.audit("user", "now_accepted", result_summary=f"proposal {proposal_id}")
    return {"ok": True, "lines": now_list.lines(store, pid)}


class RecipeIn(BaseModel):
    repo: str


def _offer_of(request: Request, repo: str) -> None:
    """A "Use this" card waiting on the picked one's Pulse for this repo; anything else is "no such card"."""
    from odie.loops import recipes
    found = recipes.offered(request.app.state.store, repo)
    if found is None or (found.get("owner") or "") != _personality(request):
        raise HTTPException(404, "That card isn't there any more.")


@router.post("/recipes/use")
async def recipe_use(body: RecipeIn, request: Request) -> dict[str, Any]:
    """"Use this": the test command Odie proposed for a repo (kept with the offer, never sent by the app) is approved,
    once, for that repo; its pull request is looked at again at once."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from odie.loops import recipes
    _offer_of(request, body.repo)
    recipes.use(request.app.state.store, body.repo, datetime.now(ZoneInfo(config.settings.timezone)))
    return {"ok": True}


@router.post("/recipes/no")
async def recipe_no(body: RecipeIn, request: Request) -> dict[str, Any]:
    """No: Odie won't test this repo nor ask again; its pull requests are briefed from GitHub's CI."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from odie.loops import recipes
    _offer_of(request, body.repo)
    recipes.decline(request.app.state.store, body.repo, datetime.now(ZoneInfo(config.settings.timezone)))
    request.app.state.store.audit("user", "test_recipe_declined", result_summary=body.repo)
    return {"ok": True}


# --- Workers (odie.workers): the picked one's own jobs. Every move here is a tap in the app: the terminal's key can't
# reach these routes (odie.devices.terminal_may), and the model has no tool for "allow".

def _own_job(request: Request, job_id: str) -> dict:
    """The job when it is the picked one's own; anyone else's (or none) is "no such job"."""
    from odie.workers import store as jobs_store
    row = jobs_store.get(request.app.state.store, job_id)
    if row is None or (row["personality"] or "") != _personality(request):
        raise HTTPException(404, "no such job")
    return row


def _job_view(j: dict) -> dict:
    """A job row for the app: the columns Pulse shows, the report cut short."""
    from odie.workers import allow as job_allow
    from odie.workers import store as jobs_store
    keys = ("id", "kind", "title", "status", "runs", "outcome", "error", "started_by", "created_at", "started_at",
            "ended_at")
    out = {k: j.get(k) for k in keys}
    out["report"] = (j.get("report") or "")[:300]
    out["needed"] = [job_allow.line(n) for n in jobs_store.needed(j)]
    out["taint"] = j.get("taint") or ""
    out["may_read"] = jobs_store.loads(j.get("read_dirs_json"))
    return out


@router.get("/jobs")
async def jobs_list(request: Request) -> dict[str, Any]:
    """The picked one's jobs: going now (queued, running) and the last few that ended."""
    from odie.workers import store as jobs_store
    mine = jobs_store.of_owner(request.app.state.store, _personality(request), 20)
    running = [_job_view(j) for j in mine if j["status"] in jobs_store.GOING]
    recent = [_job_view(j) for j in mine if j["status"] not in jobs_store.GOING][:8]
    return {"running": running, "recent": recent}


@router.get("/jobs/{job_id}")
async def job_get(job_id: str, request: Request) -> dict[str, Any]:
    """One job with its log: every call its Worker made, with what, and how it went."""
    from odie.workers import store as jobs_store
    row = _own_job(request, job_id)
    acts = [{"ts": a["ts"], "tool": a["tool"], "args": (a.get("args_json") or "")[:200],
             "result_chars": a.get("result_chars"), "refused": a.get("refused"), "error": a.get("error")}
            for a in jobs_store.actions(request.app.state.store, job_id)]
    return {**_job_view(row), "report": row.get("report") or "", "brief": row.get("brief") or "", "actions": acts}


@router.post("/jobs/{job_id}/stop")
async def job_stop(job_id: str, request: Request) -> dict[str, Any]:
    from odie.workers import router as workers_router
    _own_job(request, job_id)
    if not workers_router.stop(job_id):
        raise HTTPException(409, "It isn't running.")
    request.app.state.store.audit("user", "job_stopped", result_summary=job_id)
    return {"ok": True}


@router.post("/jobs/{job_id}/retry")
async def job_retry(job_id: str, request: Request) -> dict[str, Any]:
    """Pulse's Retry: the job again, with nothing extra allowed."""
    from odie.workers import router as workers_router
    _own_job(request, job_id)
    if workers_router.retry(job_id) is None:
        raise HTTPException(409, "It's still going, or it is Odie's own test of a pull request.")
    request.app.state.store.audit("user", "job_retried", result_summary=job_id)
    return {"ok": True}


class AllowIn(BaseModel):
    hash: str = ""


@router.post("/jobs/{job_id}/allow")
async def job_allow_and_retry(job_id: str, request: Request, body: AllowIn | None = None) -> dict[str, Any]:
    """Pulse's "Allow it and run again": the job again, and exactly the steps it was refused (as its card showed them)
    may run on that run only (odie.workers.allow). What is allowed comes from the job's own record, never the request."""
    from odie.workers import cards as job_cards
    from odie.workers import router as workers_router
    from odie.workers import store as jobs_store
    row = _own_job(request, job_id)
    from pathlib import Path

    from odie.workers import allow as job_allow
    allowed = job_cards.allowable(row)  # exactly the steps the card offered, never one only he may do in chat
    if row["status"] in jobs_store.GOING:
        raise HTTPException(409, "It's still going.")
    if not allowed:
        raise HTTPException(409, "There's nothing a tap here can allow.")
    shown = ""
    if body is not None:
        shown = body.hash
    if shown != job_allow.needs_hash(allowed):
        raise HTTPException(409, "Its steps changed since this card was shown: look at them again.")
    allowed = job_allow.bind_files(allowed, Path(row["folder"]))  # the files they run, as they are now
    if workers_router.retry(job_id, allowed=allowed) is None:
        raise HTTPException(409, "This one can't run again from here.")
    request.app.state.store.audit("user", "job_allowed", args={"allowed": allowed}, result_summary=job_id)
    return {"ok": True}


@router.post("/jobs/{job_id}/keep")
async def job_keep(job_id: str, request: Request) -> dict[str, Any]:
    """A finished job's "Keep it in <folder>": what its Worker said is worth keeping is copied, by code, here in Odie's
    own process, into the folder the user named in his request (odie.workers.keep: inside the job's folder only, never
    an overwrite, no link out, nothing run). A tap in the app only: the terminal's key can't reach it and no model tool
    does it. Answers where it went, as the user writes it."""
    import asyncio

    from odie.workers import cards as job_cards
    from odie.workers import keep as job_keep_copy
    _own_job(request, job_id)
    store = request.app.state.store
    try:
        kept = await asyncio.to_thread(job_keep_copy.keep_job, store, job_id)
    except job_keep_copy.KeepStopped as e:  # recorded as partial: the card says what it copied and offers Keep it again
        store.audit("user", "job_kept_partly", args={"path": str(e.path), "stopped": e.reason}, result_summary=job_id)
        raise HTTPException(409, f"Not kept: {e}.") from e
    except job_keep_copy.KeepRefused as e:
        raise HTTPException(409, f"Not kept: {e}.") from e
    store.audit("user", "job_kept", args=job_keep_copy.record_of(kept), result_summary=job_id)
    return {"ok": True, "kept": job_cards.home_form(str(kept.path)), "line": kept.line(job_cards.home_form)}


@router.post("/jobs/{job_id}/clear")
async def job_clear(job_id: str, request: Request) -> dict[str, Any]:
    """A job card's Done: off Pulse."""
    from odie.workers import store as jobs_store
    _own_job(request, job_id)
    jobs_store.clear(request.app.state.store, job_id)
    return {"ok": True}


@router.post("/watch/done")
async def watch_done(body: WatchDoneIn, request: Request) -> dict[str, Any]:
    """A card's "dismiss", on the picked one's Pulse: Sunday's "Still care?" card drops the loops in it; a "Track
    this?" offer's No forgets it ("offer:3"); No on Odie's proposed Now list ("now:2") keeps the list; OK on "Fewer
    cards for X" ("learn:1") says it; No on a proposed Quiet rule ("quiet:2"); a loop's ref ("loop:3"), or the mail or
    event an open loop holds (an older app's card), is that loop's Done (remembered)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from odie.loops import cards as loop_cards
    from odie.loops import learn, ledger, offers, quiet
    from odie.loops import now as now_list
    store = request.app.state.store
    pid = _personality(request)
    now = datetime.now(ZoneInfo(config.settings.timezone))
    if body.ref == loop_cards.BATCH:
        return {"ok": True, "dropped": loop_cards.drop_batch(store, pid, now)}
    offer_id = offers.number_of(body.ref)
    if offer_id is not None:  # a "Track this?" card's No: nothing is tracked
        offers.decline(store, pid, offer_id)
        return {"ok": True}
    proposal_id = now_list.number_of(body.ref)
    if proposal_id is not None:  # No on Odie's proposed Now list: it stays as it is
        now_list.decline(store, pid, proposal_id)
        return {"ok": True}
    notice_id = learn.number_of(body.ref)
    if notice_id is not None:  # OK on "Fewer cards for X": said; the kind stays in the digest
        learn.said(store, pid, notice_id)
        return {"ok": True}
    from odie.memory import rules
    rule_id = rules.number_of(body.ref)
    if rule_id is not None:  # OK on "Rule saved": said; the rule stays
        rules.said(store, pid, rule_id)
        return {"ok": True}
    from odie.skills import fade
    faded_id = fade.number_of(body.ref)
    if faded_id is not None:  # OK on "Put away: X": said; the skill stays put away
        fade.said(store, faded_id)
        return {"ok": True}
    quiet_id = quiet.number_of(body.ref)
    if quiet_id is not None:  # No on a Quiet rule the evening review proposed
        quiet.decline(store, pid, quiet_id)
        return {"ok": True}
    loop = None
    if body.ref.startswith("loop:") and body.ref[len("loop:"):].isdigit():
        loop = ledger.get(store, int(body.ref[len("loop:"):]))
    elif body.ref:
        loop = ledger.find_by_refs(store, pid, [body.ref])
    if loop is not None and loop["personality"] == pid and loop["state"] in ledger.OPEN:
        ledger.done(store, loop["id"], now)
        ledger.update(store, loop["id"], now, tapped="done")
    return {"ok": True}


class LaterIn(BaseModel):
    ref: str


@router.post("/needs_you/later")
async def needs_you_later(body: LaterIn, request: Request) -> dict[str, Any]:
    """A card's Later: hidden until 09:00 tomorrow, then back (odie.watch.needs.later). A loop ("loop:3"; its third
    Later: till Sunday), Sunday's batch, or a task ("task:12"); a card that isn't there -> 404."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from odie.watch import needs
    store = request.app.state.store
    now = datetime.now(ZoneInfo(config.settings.timezone))
    until = needs.later(store, body.ref, now, _personality(request))
    if until is None:
        raise HTTPException(404, "That card isn't there any more.")
    if body.ref.startswith("task:"):
        await _publish(request, {"type": "task", "id": int(body.ref[len("task:"):])})
    return {"ok": True, "until": until}


@router.post("/watch/seen")
async def watch_seen(request: Request) -> dict[str, Any]:
    """A Pulse was opened: every card on it now has been seen (the count on chat's Back to Pulse goes)."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from odie.watch import report
    from odie.watch.owner import key
    store = request.app.state.store
    card_key = key(report.CARD, _personality(request))
    card = store.get_setting(card_key) or {}
    card["seen_at"] = datetime.now(ZoneInfo(config.settings.timezone)).isoformat(timespec="seconds")
    store.set_setting(card_key, card)
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
    """A brief run by hand (the user is looking at it, so no push). When the day's hello is already made, the brief
    joins its summary and open chats rebuild their prompt to read it."""
    from odie.jobs.brief import run_brief
    store = request.app.state.store
    now = morning_now()
    text = await run_brief(store, now, push=False)
    if add_brief_to_hello(store, now, text):
        request.app.state.runner.invalidate_prompt()
    return {"text": text}


# --- Morning hello ---
_morning_tasks: set[asyncio.Task] = set()  # rounds this route started; held here so they aren't garbage-collected
_round_failed_at: datetime | None = None  # when the last round this route started ended with no hello saved
ROUND_COOL_OFF = timedelta(minutes=10)


def morning_now() -> datetime:
    """The clock the morning route reads (tests replace it): now, in the owner's time zone."""
    return datetime.now(ZoneInfo(config.settings.timezone))


def retry_allowed(failed_at: datetime | None, now: datetime) -> bool:
    """Whether the web may start another round after one failed: only once the cool-off has passed, so a page that
    keeps asking doesn't re-run the gathering and the model call every few seconds. No failure yet -> True; failed
    3 minutes ago -> False; failed 11 minutes ago -> True."""
    if failed_at is None:
        return True
    return now - failed_at >= ROUND_COOL_OFF


async def run_web_round(request: Request, now: datetime) -> None:
    """The morning round started from the web, run as the cron's is: beside no running tick, and stopped after
    BRIEF_LIMIT seconds. A round that raised, ran out of time, or ended with no hello saved is logged and starts the
    cool-off."""
    # main imports this module, so these come in when the round starts
    from odie.app.main import BRIEF_LIMIT
    from odie.background import Part

    store = request.app.state.store
    background = request.app.state.background

    async def go() -> None:
        await morning_round(store, now, runner=request.app.state.runner, push=True)

    try:
        if background is None:
            await asyncio.wait_for(go(), BRIEF_LIMIT)
        else:
            await background.exclusive(Part("brief", go, limit=BRIEF_LIMIT))  # never beside a running tick
    except Exception:
        log.warning("morning: the round the web started failed", exc_info=True)

    if hello_for(store, morning_day(now)) is None:
        global _round_failed_at
        _round_failed_at = morning_now()
        log.warning("morning: the round the web started saved no hello; trying again in %s", ROUND_COOL_OFF)


def start_morning_round(request: Request, now: datetime) -> None:
    task = asyncio.create_task(run_web_round(request, now))
    _morning_tasks.add(task)
    task.add_done_callback(_morning_tasks.discard)


@router.get("/morning")
async def morning_get(request: Request):
    """Today's hello for the web card and the Mac app: {"state": "ready" | "making" | "none", "day", "card"}.
    A saved hello -> ready, with its card (the summary is for chats, not sent). Before 05:00 with none saved, or no
    chat model chosen -> none. Otherwise a round is running or this call starts one -> making; the page asks again.
    Two calls while the hello is due start one round: the second sees the first's task still in `_morning_tasks`.
    Within 10 minutes of a failed round -> none, so the page doesn't start another on every poll."""
    store = request.app.state.store
    now = morning_now()
    day = morning_day(now)

    hello = hello_for(store, day)
    if hello is not None:
        from odie.loops import ladder
        card = {key: value for key, value in hello["card"].items() if key != "summary"}
        card["ledger"] = ladder.ledger_lines(store, "", now)  # two lines from the ledger, by code, read now
        return {"state": "ready", "day": day, "card": card}

    if not hello_due(store, now) or not brain_chosen(store):
        return {"state": "none", "day": day, "card": None}

    if round_running() or _morning_tasks:
        return {"state": "making", "day": day, "card": None}
    if not retry_allowed(_round_failed_at, now):
        return {"state": "none", "day": day, "card": None}
    start_morning_round(request, now)
    return {"state": "making", "day": day, "card": None}


# --- Approvals ---
class DecideIn(BaseModel):
    approve: bool
    allow_minutes: int | None = None  # run_shell only: also allow this conversation's commands for this long
    allow_chat: bool = False  # Smart, run_shell only: don't ask again in this chat for this card's kind (30 min)




@router.get("/approvals")
async def approvals_pending(request: Request):
    from odie import personalities
    store = request.app.state.store
    pick = _personality(request)
    waiting = store.pending_approvals()
    return [_approval_dict(r) for r in waiting if personalities.of_session(store, r["session_id"]) == pick]


@router.get("/approvals/{approval_id}")
async def approval_get(approval_id: int, request: Request):
    return _approval_dict(_own_approval(request, approval_id))


_resuming: set[asyncio.Task] = set()  # strong refs to turns resuming after a tap


def chat_pass_kind(store, row) -> str | None:
    """The kind a tap on "don't ask again in this chat" may pass for this card, or None when the card doesn't offer it.
    Offered only on a shell card that Odie itself marked as offering it (its detail, written when the card was made),
    for a kind that may have a pass, while the mode is Smart, and never on a card raised just after Odie read mail (the
    mail may have asked for it; Careful's 30-minute pass isn't offered there either).
      Smart, run_shell card {"asks_because": "deletes or stops something", "chat_pass": true} -> that kind;
      the same card in Careful -> None;  a card that says "reads secrets" -> None;  a mail card -> None;
      the same shell card with risk "from_email" -> None."""
    from odie import approvals_mode
    from odie.agent import shell_grant
    if row["tool"] != "run_shell" or not approvals_mode.is_smart(store):
        return None
    if row["risk"] in ("from_email", "unknown"):
        return None
    try:
        detail = json.loads(row["detail_json"] or "{}")
    except ValueError:
        return None
    if not isinstance(detail, dict) or detail.get("chat_pass") is not True:
        return None
    kind = detail.get("asks_because")
    if not shell_grant.may_pass(kind):
        return None
    return kind


@router.post("/approvals/{approval_id}/decide")
async def approval_decide(approval_id: int, body: DecideIn, request: Request):
    """Answer at once so the card collapses; the paused turn resumes in its own task (it can take minutes) and
    reports through the live stream (approval, message, approval_done)."""
    from odie import brains
    from odie.plugins import access
    row = _own_approval(request, approval_id)
    if row["status"] != "pending":
        raise HTTPException(409, f"already {row['status']}")
    if body.approve:  # a No needs no model and no app: it is recorded whatever has changed
        moved = access.card_moved(request.app.state.store, row)
        if moved:  # a tap is consent for the app the card named; that app is now off here: the card lapses
            await request.app.state.runner.lapse_card(row, moved)
            return {"status": "expired", "text": moved}
        try:
            brains.for_thread(request.app.state.store, row["session_id"])
        except brains.BrainGone as gone:  # the turn couldn't go on: the card keeps waiting, and the words say why
            raise HTTPException(409, str(gone))
    out: dict[str, Any] = {"status": "approved" if body.approve else "rejected"}
    if body.approve and body.allow_chat:
        kind = chat_pass_kind(request.app.state.store, row)
        if kind is None:
            raise HTTPException(400, "This card doesn't offer that.")  # nothing approved: the card stays to tap
        from datetime import datetime

        from odie.agent import shell_grant
        until = shell_grant.grant_kind(row["session_id"], kind, datetime.now())
        request.app.state.store.audit("user", "shell_allowed_for_chat", tool="run_shell",
                                      result_summary=f"{kind} until {until:%H:%M}", session_id=row["session_id"],
                                      approval_id=approval_id)
        out["chat_pass"] = {"kind": kind, "until": until.isoformat()}
    if body.approve and body.allow_minutes and row["tool"] == "run_shell":
        from datetime import datetime

        from odie.agent import shell_grant
        minutes = max(1, min(body.allow_minutes, shell_grant.GRANT_MINUTES))
        until = shell_grant.grant(row["session_id"], datetime.now(), minutes)
        request.app.state.store.audit("user", "shell_allowed", tool="run_shell", result_summary=f"until {until:%H:%M}",
                                      session_id=row["session_id"], approval_id=approval_id)
        out["allowed_until"] = until.isoformat()
        # One tap approves one card. Other run_shell cards already waiting in this chat (parallel tool calls) were
        # raised before the pass existed and stay on screen: the pass covers only commands asked from now on, so a
        # command the user never read is never approved by a tap on another one.

    task = asyncio.create_task(request.app.state.runner.resume_approval(approval_id, body.approve))
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
    """Settings → Brain: every provider's models and the brain of whoever the request picked. With a personality
    picked, the brain says whether it is "Same as Odie" (same_as_odie) or one of its own that is no longer set up
    (gone), and `odie` is everyday Odie's, for the "Same as Odie" choice."""
    store = request.app.state.store
    pick = _personality(request)
    providers = all_providers(store)
    listed = await list_models(providers)
    r = resolve_selection(store, "chat")
    chat = {"provider": r.provider.id, "model": r.model, "leaves_mini": r.leaves_mini,
            "chosen": brain_chosen(store), "reachable": _answers(listed, r.provider.id)}
    out = {"providers": listed, "selection": {"chat": chat}, "creativity": _creativity(store)}
    if pick:
        out["selection"]["chat"] = _its_brain(store, pick, chat, listed)
        out["odie"] = {"provider": r.provider.id, "model": r.model, "leaves_mini": r.leaves_mini}
    return out


def _answers(listed: list[dict], provider_id: str) -> bool:
    """Whether a provider answered the model listing: listed without an error -> True; failed, or not listed -> False."""
    row = next((p for p in listed if p["id"] == provider_id), None)
    return row is not None and row["error"] is None


def _its_brain(store, pick: str, odies: dict, listed: list[dict]) -> dict:
    """A personality's brain as Settings → Brain shows it: everyday Odie's with same_as_odie when it has none of its
    own; its own otherwise, and `gone` (never reachable) when that one's provider is no longer set up."""
    from odie import brains
    own = brains.own_pick(store, pick)
    if own is None:
        return {**odies, "same_as_odie": True, "gone": False}
    try:
        sel = brains.for_personality(store, pick)
    except brains.BrainGone:
        return {"provider": own["provider"], "model": own["model"], "leaves_mini": True, "chosen": True,
                "reachable": False, "same_as_odie": False, "gone": True}
    return {"provider": sel.provider.id, "model": sel.model, "leaves_mini": sel.leaves_mini, "chosen": True,
            "reachable": _answers(listed, sel.provider.id), "same_as_odie": False, "gone": False}


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
    """Choose the brain of whoever the request picked: everyday Odie's (model.chat), or with a personality picked, a
    brain of its own (odie.brains), which leaves Odie's as it is."""
    from odie import brains
    store = request.app.state.store
    pick = _personality(request)
    if body.slot != "chat":
        raise HTTPException(422, "There's one model now: slot is chat.")
    if body.provider not in {p.id for p in all_providers(store)}:
        raise HTTPException(404, "unknown provider")
    if pick:
        brains.choose(store, pick, body.provider, body.model)
        store.audit("user", "model_selected", result_summary=f"{pick}: {body.provider}/{body.model}")
        _apply_models(request)
        sel = brains.for_personality(store, pick)
        return {"ok": True, "slot": "chat", "provider": sel.provider.id, "model": sel.model, "leaves_mini": sel.leaves_mini}
    store.set_setting(f"model.{body.slot}", {"provider": body.provider, "model": body.model})
    store.audit("user", "model_selected", result_summary=f"{body.slot}: {body.provider}/{body.model}")
    apply = getattr(request.app.state.runner, "apply_model_selection", None)
    if apply:
        apply()
    sel = resolve_selection(store, body.slot)
    return {"ok": True, "slot": body.slot, "provider": sel.provider.id, "model": sel.model, "leaves_mini": sel.leaves_mini}


@router.delete("/models/selection")
async def models_same_as_odie(request: Request):
    """A personality's brain back to "Same as Odie". Everyday Odie's own can't be: it is the one the others follow."""
    from odie import brains
    store = request.app.state.store
    pick = _personality(request)
    if not pick:
        raise HTTPException(422, "Everyday Odie's brain is chosen, not followed.")
    brains.same_as_odie(store, pick)
    store.audit("user", "model_selected", result_summary=f"{pick}: same as Odie")
    _apply_models(request)
    return {"ok": True}


def _apply_models(request: Request) -> None:
    """A brain changed: the runner builds its models again from the next message."""
    apply = getattr(request.app.state.runner, "apply_model_selection", None)
    if apply:
        apply()


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
    """Open to any caller (the pairing screen needs it): how many devices are paired is told only to a paired one; an
    unpaired caller learns just whether any is (0 or 1), which is what the screen's wording needs."""
    store = request.app.state.store
    paired = _device(request) is not None
    count = len(devices.list_devices(store))
    shown = count if paired else min(count, 1)
    return {"on": devices.pairing_on(store), "paired": paired, "devices": shown, "passcode": devices.has_passcode(store)}


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
    browsers = [d for d in known if not devices.is_terminal(d)]  # the terminal can't open the app, so it doesn't count
    removing_last_browser = len(browsers) == 1 and browsers[0]["id"] == device_id
    if removing_last_browser and devices.pairing_on(store) and not confirm:
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
