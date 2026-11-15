"""odie chat / threads / show (odie.cli_chat): the terminal's key, the turn as a person and a program see it, a refused
terminal, and the "via Terminal" mark from the request to the history."""
from __future__ import annotations

import io
import json
import stat
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import httpx
import pytest
from google.adk.events import Event
from google.genai import types

from odie import cli, cli_chat, devices
from odie.app.runner import VIA_TERMINAL, events_to_history
from odie.store.db import Store

REAL_HOME = Path.home() / ".odie"


@pytest.fixture
def inst(tmp_path):
    i = cli.install_from({"ODIE_HOME": str(tmp_path / "home"), "ODIE_PORT": "8999", "ODIE_SERVICE_LABEL": "dev.odie.unittest",
                          "ODIE_BIN_DIR": str(tmp_path / "bin"), "ODIE_LAUNCH_AGENTS": str(tmp_path / "agents")})
    assert i.home != REAL_HOME and REAL_HOME not in i.home.parents  # never the real data folder
    assert cli_chat.key_file(i).is_relative_to(tmp_path)
    i.database.parent.mkdir(parents=True)
    store = Store(i.database)
    store.init_schema()
    store.close()
    return i


def device_names(inst) -> list[str]:
    store = Store(inst.database)
    try:
        return [d["name"] for d in devices.list_devices(store)]
    finally:
        store.close()


# ── the key ──

def test_the_first_command_pairs_the_terminal_once_and_keeps_the_key_private(inst):
    err = io.StringIO()
    key = cli_chat.key_for(inst, err)
    assert key and "Paired this terminal" in err.getvalue()
    path = cli_chat.key_file(inst)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert device_names(inst) == [devices.TERMINAL_NAME]
    store = Store(inst.database)
    assert devices.device_for(store, key) is not None  # the key is one Odie's gate lets in
    store.close()
    again = io.StringIO()
    assert cli_chat.key_for(inst, again) == key  # the second command reuses it
    assert again.getvalue() == "" and device_names(inst) == [devices.TERMINAL_NAME]


def test_a_leftover_key_file_gets_the_private_mode_too(inst):
    path = cli_chat.key_file(inst)
    path.write_text("")  # empty: read as no key
    path.chmod(0o644)
    cli_chat.key_for(inst, io.StringIO())
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_the_terminal_doesnt_count_as_a_paired_browser(inst):
    store = Store(inst.database)
    link = devices.setup_link(store, "http://t")
    token = link.split("token=")[1]
    store.close()
    cli_chat.key_for(inst, io.StringIO())  # an agent runs odie chat before the owner opens the link
    store = Store(inst.database)
    try:
        assert devices.redeem_setup(store, token)  # the owner's browser still pairs with it
    finally:
        store.close()


# ── odie chat ──

class FakeApi:
    def __init__(self, events, refuse=False):
        self.events = events
        self.refuse = refuse
        self.sent: list[tuple[str, dict]] = []

    def stream(self, path, body):
        self.sent.append((path, body))
        if self.refuse:
            raise cli_chat.Refused("no")
        yield from self.events

    def post(self, path, body):
        self.sent.append((path, body))
        return {"session_id": "chat-2026-11-15-2"}

    def get(self, path):
        self.sent.append((path, {}))
        return {"threads": [{"id": "chat-2026-11-15", "title": "Plans", "messages": 4, "pinned": True}],
                "items": [{"role": "user", "text": "hi", "ts": 0, "via": "terminal"},
                          {"role": "odie", "text": "Hello.", "ts": 0, "steps": [{"name": "web_search"}]},
                          {"role": "approval", "approval": {"summary": "Send mail", "status": "pending"}}]}


def test_an_error_event_shows_its_message(inst):
    events = [{"type": "error", "message": "The model didn't answer."}, {"type": "done", "text": ""}]
    err = io.StringIO()
    assert cli_chat.run(inst, chat_args("hi"), io.StringIO(), err, api=FakeApi(events)) == 1
    assert "! The model didn't answer." in err.getvalue()
    out = io.StringIO()
    cli_chat.run(inst, chat_args("hi", as_json=True), out, io.StringIO(), api=FakeApi(events))
    assert json.loads(out.getvalue())["errors"] == ["The model didn't answer."]


REPLY = [{"type": "tool_start", "tool": "web_search"},
         {"type": "token", "text": "It's ", "session_id": "chat-2026-11-15"},
         {"type": "token", "text": "sunny.", "session_id": "chat-2026-11-15"},
         {"type": "text", "text": "It's sunny.", "session_id": "chat-2026-11-15"},
         {"type": "done", "text": "It's sunny."}]


def chat_args(text, thread=None, new=False, as_json=False, events=False):
    return SimpleNamespace(command="chat", text=text, thread=thread, new=new, json=as_json, events=events)


def test_chat_prints_the_reply_once_and_marks_the_message_as_from_the_terminal(inst):
    api, out, err = FakeApi(REPLY), io.StringIO(), io.StringIO()
    assert cli_chat.run(inst, chat_args("weather?"), out, err, api=api) == 0
    assert out.getvalue() == "It's sunny.\n"  # streamed, and the whole text that follows isn't printed again
    assert "· web_search" in err.getvalue() and "(thread chat-2026-11-15)" in err.getvalue()
    assert api.sent == [("/api/chat", {"text": "weather?", "via": "terminal"})]  # today's chat: no session_id


def test_chat_json_is_one_answer_for_a_program(inst):
    out = io.StringIO()
    assert cli_chat.run(inst, chat_args("weather?", as_json=True), out, io.StringIO(), api=FakeApi(REPLY)) == 0
    assert json.loads(out.getvalue()) == {"thread": "chat-2026-11-15", "text": "It's sunny.", "needs_tap": [], "errors": []}


def test_chat_events_are_json_lines(inst):
    out = io.StringIO()
    cli_chat.run(inst, chat_args("weather?", events=True), out, io.StringIO(), api=FakeApi(REPLY))
    assert [json.loads(line)["type"] for line in out.getvalue().splitlines()] == ["tool_start", "token", "token", "text", "done"]


def test_a_turn_at_a_card_says_tap_it_in_the_app_and_exits_3(inst):
    events = [{"type": "approval", "id": 7, "summary": "Send mail to the bank"},
              {"type": "done", "text": "", "session_id": "chat-2026-11-15"}]  # no words: the thread comes with done
    err = io.StringIO()
    assert cli_chat.run(inst, chat_args("pay it"), io.StringIO(), err, api=FakeApi(events)) == cli_chat.NEEDS_TAP
    assert "needs your tap: Send mail to the bank" in err.getvalue()
    out = io.StringIO()
    assert cli_chat.run(inst, chat_args("pay it", as_json=True), out, io.StringIO(), api=FakeApi(events)) == 3
    assert json.loads(out.getvalue())["needs_tap"] == ["Send mail to the bank"]
    assert json.loads(out.getvalue())["thread"] == "chat-2026-11-15"


def test_chat_new_and_thread(inst):
    api = FakeApi(REPLY)
    cli_chat.run(inst, chat_args("start over", new=True), io.StringIO(), io.StringIO(), api=api)
    assert api.sent == [("/api/chat/new", {}), ("/api/chat", {"text": "start over", "via": "terminal", "session_id": "chat-2026-11-15-2"})]
    api = FakeApi(REPLY)
    cli_chat.run(inst, chat_args("and then?", thread="chat-2026-11-01"), io.StringIO(), io.StringIO(), api=api)
    assert api.sent[0][1]["session_id"] == "chat-2026-11-01"


def test_chat_reads_stdin_for_a_dash_and_refuses_nothing(inst):
    api = FakeApi(REPLY)
    cli_chat.run(inst, chat_args("-"), io.StringIO(), io.StringIO(), stdin=io.StringIO("long\ntext\n"), api=api)
    assert api.sent[0][1]["text"] == "long\ntext"
    err = io.StringIO()
    assert cli_chat.run(inst, chat_args("  "), io.StringIO(), err, api=FakeApi(REPLY)) == 2
    assert "Nothing to send" in err.getvalue()


def test_a_removed_terminal_is_told_how_to_pair_again(inst):
    err = io.StringIO()
    assert cli_chat.run(inst, chat_args("hi"), io.StringIO(), err, api=FakeApi([], refuse=True)) == 1
    assert "Settings → Devices" in err.getvalue() and f"rm {cli_chat.key_file(inst)}" in err.getvalue()


# ── odie threads / show ──

def test_threads_and_show(inst):
    out = io.StringIO()
    api = FakeApi([])
    assert cli_chat.run(inst, SimpleNamespace(command="threads", q="plans", json=False), out, io.StringIO(), api=api) == 0
    assert "★ chat-2026-11-15" in out.getvalue() and "Plans" in out.getvalue()
    assert api.sent[0][0] == "/api/threads?q=plans"
    out = io.StringIO()
    assert cli_chat.run(inst, SimpleNamespace(command="show", thread="chat-2026-11-15", lines=2, json=False), out,
                        io.StringIO(), api=api) == 0
    shown = out.getvalue()
    assert "── You (via Terminal)" in shown and "── Odie" in shown and "· web_search" in shown
    assert "Send mail [pending]" in shown
    assert api.sent[-1][0] == "/api/threads/chat-2026-11-15/history?limit=2"


# ── the real HTTP path: urllib against a real server ──

class Fake(BaseHTTPRequestHandler):
    seen: ClassVar[list] = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        Fake.seen.append((self.path, self.headers.get("Cookie"), body))
        if self.headers.get("Cookie") != f"{devices.COOKIE}=good":
            self.send_response(401)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        if body.get("text") == "cut":
            self.wfile.write(b"data: {\"type\": \"tok")  # Odie restarted halfway through a line
            return
        self.wfile.write(b": ping\n\ndata: {\"type\": \"token\", \"text\": \"Hi\"}\n\ndata: {\"type\": \"done\", \"text\": \"Hi\"}\n\n")

    def log_message(self, *a):
        pass


@pytest.fixture
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_the_api_streams_server_sent_events_with_the_device_cookie(server):
    got = list(cli_chat.Api(server, "good").stream("/api/chat", {"text": "hi", "via": "terminal"}))
    assert got == [{"type": "token", "text": "Hi"}, {"type": "done", "text": "Hi"}]  # the ping is skipped
    assert Fake.seen[-1] == ("/api/chat", f"{devices.COOKIE}=good", {"text": "hi", "via": "terminal"})
    with pytest.raises(cli_chat.Refused):
        list(cli_chat.Api(server, "stale").stream("/api/chat", {"text": "hi"}))


def test_a_stream_cut_off_halfway_is_a_line_not_a_traceback(server):
    with pytest.raises(cli_chat.ApiError, match="cut off"):
        list(cli_chat.Api(server, "good").stream("/api/chat", {"text": "cut"}))


def test_nothing_answering_says_so():
    with pytest.raises(cli_chat.ApiError, match="isn't answering"):
        cli_chat.Api("http://127.0.0.1:9", None).get("/api/threads")


# ── the mark: the route passes it on, history shows it ──

def test_history_labels_a_terminal_message_and_hides_the_note():
    sent = "weather?\n\n[context: now 09:30 Sun 15 Nov]" + VIA_TERMINAL
    typed = "and you?\n\n[context: now 09:31 Sun 15 Nov]"
    events = [Event(author="user", invocation_id="a", content=types.Content(role="user", parts=[types.Part(text=sent)])),
              Event(author="user", invocation_id="b", content=types.Content(role="user", parts=[types.Part(text=typed)]))]
    first, second = events_to_history(events)
    assert first["text"] == "weather?" and first["via"] == "terminal"
    assert second["text"] == "and you?" and "via" not in second


class ViaRunner:
    seen: ClassVar[dict] = {}

    async def chat(self, text, thinking=None, session_id=None, images=None, via=None):
        ViaRunner.seen = {"text": text, "via": via}
        yield {"type": "done", "text": "ok"}

    async def history(self, date, limit=None, before=None):
        return {"items": [], "total": 0, "start": 0}

    async def close(self):
        pass


async def test_the_chat_route_passes_via_on_and_refuses_anything_else(isolated_settings, tmp_path):
    from odie.app.main import create_app
    store = Store(tmp_path / "assistant.db")
    store.init_schema()
    app = create_app(runner=ViaRunner(), store=store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c, app.router.lifespan_context(app):
        async with c.stream("POST", "/api/chat", json={"text": "hi", "via": "terminal"}) as resp:
            [x async for x in resp.aiter_text()]
        assert ViaRunner.seen == {"text": "hi", "via": "terminal"}
        bad = await c.post("/api/chat", json={"text": "hi", "via": "phone"})
        assert bad.status_code == 422


# ── the terminal's key reaches only chat and threads ──

def test_terminal_may_only_chat_and_read_threads():
    assert devices.terminal_may("POST", "/api/chat")
    assert devices.terminal_may("POST", "/api/chat/new")
    assert devices.terminal_may("GET", "/api/threads")
    assert devices.terminal_may("GET", "/api/threads/chat-2026-11-15/history")
    assert not devices.terminal_may("POST", "/api/approvals/7/decide")
    assert not devices.terminal_may("PUT", "/api/approvals/mode")
    assert not devices.terminal_may("POST", "/api/threads/chat-2026-11-15/pin")
    assert not devices.terminal_may("GET", "/api/devices")
    assert not devices.terminal_may("DELETE", "/api/devices/1")


async def test_the_gate_holds_the_terminal_to_its_routes(isolated_settings, tmp_path, monkeypatch):
    from odie.app.main import create_app
    monkeypatch.setenv("ODIE_PAIRING", "on")
    store = Store(tmp_path / "assistant.db")
    store.init_schema()
    terminal = devices.add_terminal(store)
    phone = devices.add_device(store, "iPhone, Safari")
    app = create_app(runner=ViaRunner(), store=store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c, app.router.lifespan_context(app):
        c.cookies.set(devices.COOKIE, terminal)
        assert (await c.get("/api/threads")).status_code == 200
        refused = await c.put("/api/approvals/mode", json={"mode": "relaxed"})
        assert refused.status_code == 403
        assert (await c.post("/api/approvals/1/decide", json={"decision": "yes"})).status_code == 403
        assert (await c.get("/api/devices")).status_code == 403
        c.cookies.set(devices.COOKIE, phone)
        assert (await c.get("/api/devices")).status_code == 200  # a browser is not held to them


async def test_removing_the_last_browser_still_warns_with_the_terminal_paired(isolated_settings, tmp_path, monkeypatch):
    from odie.app.main import create_app
    monkeypatch.setenv("ODIE_PAIRING", "on")
    store = Store(tmp_path / "assistant.db")
    store.init_schema()
    devices.add_terminal(store)
    phone = devices.add_device(store, "iPhone, Safari")
    phone_id = devices.device_for(store, phone)["id"]
    app = create_app(runner=ViaRunner(), store=store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c, app.router.lifespan_context(app):
        c.cookies.set(devices.COOKIE, phone)
        assert (await c.delete(f"/api/devices/{phone_id}")).status_code == 409
