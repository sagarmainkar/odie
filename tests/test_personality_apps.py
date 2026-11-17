"""Connected apps (MCP servers) per personality (docs: personality-brain-and-apps design). Each server is on or off
for everyday Odie and for each personality. Off means off everywhere in that thread: not in the skills catalog its
prompt shows, its skill won't load, its tools aren't listed, and a call to one of them is refused before it runs.
Who a thread belongs to is read from its row, never from the client."""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import ClassVar

import pytest
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from odie import personalities
from odie.plugins import access
from odie.store.db import Store

ODIE = personalities.ODIE


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    return s


# ── the switches ──

def test_every_server_is_on_for_everyone_until_switched(store):
    mira = personalities.create(store, "Mira")
    assert access.allowed(store, "home-mail", ODIE) and access.allowed(store, "home-mail", mira.id)
    access.set_allowed(store, "home-mail", mira.id, False)
    assert not access.allowed(store, "home-mail", mira.id)
    assert access.allowed(store, "home-mail", ODIE)  # one switch per who
    assert access.off_for(store, mira.id) == frozenset({"home-mail"})
    assert access.off_for(store, ODIE) == frozenset()
    access.set_allowed(store, "home-mail", mira.id, True)
    assert access.allowed(store, "home-mail", mira.id)


def test_a_new_personality_copies_odies_switches_as_they_are_then(store):
    access.set_allowed(store, "home-mail", ODIE, False)
    mira = personalities.create(store, "Mira")
    assert not access.allowed(store, "home-mail", mira.id)  # off for Odie when she was made: off for her
    assert access.allowed(store, "calendar", mira.id)
    access.set_allowed(store, "home-mail", ODIE, True)
    access.set_allowed(store, "calendar", ODIE, False)
    assert not access.allowed(store, "home-mail", mira.id)  # a copy, not a link: later changes to Odie's stay Odie's
    assert access.allowed(store, "calendar", mira.id)


def test_a_server_added_while_a_personality_is_picked_is_hers_alone(store):
    mira = personalities.create(store, "Mira")
    coach = personalities.create(store, "Coach")
    access.added(store, "work-mail", mira.id)
    assert access.allowed(store, "work-mail", mira.id)
    assert not access.allowed(store, "work-mail", ODIE)
    assert not access.allowed(store, "work-mail", coach.id)
    later = personalities.create(store, "Asha")
    assert not access.allowed(store, "work-mail", later.id)  # she copies Odie's: off


def test_a_server_added_with_odie_picked_is_odies_alone(store):
    mira = personalities.create(store, "Mira")
    access.added(store, "home-mail", ODIE)
    assert access.allowed(store, "home-mail", ODIE)
    assert not access.allowed(store, "home-mail", mira.id)


def test_who_a_thread_belongs_to_decides(store):
    mira = personalities.create(store, "Mira")
    personalities.claim(store, "chat-2026-11-17-2", mira.id)
    access.set_allowed(store, "home-mail", mira.id, False)
    assert not access.allowed_in(store, "home-mail", "chat-2026-11-17-2")
    assert access.allowed_in(store, "home-mail", "chat-2026-11-17")
    assert access.allowed_in(store, "home-mail", None)  # a background check is Odie's
    assert access.off_in(store, "chat-2026-11-17-2") == frozenset({"home-mail"})


def test_removing_a_server_removes_its_switches(store):
    mira = personalities.create(store, "Mira")
    access.added(store, "work-mail", mira.id)
    access.forget_server(store, "work-mail")
    assert store.one("select * from app_access where server='work-mail'") is None
    assert access.allowed(store, "work-mail", ODIE)  # a server added again later starts afresh


async def test_deleting_a_personality_removes_its_switches(store):
    from odie.app.runner import OdieRunner
    mira = personalities.create(store, "Mira")
    access.set_allowed(store, "home-mail", mira.id, False)
    access.added(store, "work-mail", mira.id)
    r = OdieRunner(store)
    try:
        await personalities.delete(store, r, mira.id)
    finally:
        await r.close()
    assert store.one("select * from app_access where personality=?", (mira.id,)) is None
    assert not access.allowed(store, "work-mail", ODIE)  # Odie's own switches stay


# ── off means off in that thread ──

TESTER = {"command": sys.executable, "args": [str(Path(__file__).parent / "fixtures" / "mcp_tester.py")],
          "description": "Test tools"}
APP_TOOLS = {"echo", "write_note"}
D = "2026-11-17"


class Plays(BaseLlm):
    """A stand-in model that plays a script for each turn, picked by the turn's first words, and notes what each
    request showed it: the system instruction, the tools listed and the tool results that came back. It lets the other
    turn run before it answers, so two turns at once really interleave."""
    seen: ClassVar[list[dict]] = []
    script: ClassVar[dict[str, list]] = {}

    async def generate_content_async(self, llm_request, stream: bool = False):
        from odie.agent.compaction import turn_start
        contents = llm_request.contents or []
        start = turn_start(contents)
        words = contents[start].parts[0].text or ""
        steps = next(s for q, s in Plays.script.items() if words.startswith(q))
        results = [p.function_response for c in contents[start:] for p in c.parts or [] if p.function_response]
        tools = {f.name for t in llm_request.config.tools or [] for f in t.function_declarations or []}
        Plays.seen.append({"who": words.split()[0], "system": str(llm_request.config.system_instruction), "tools": tools,
                           "results": {r.name: r.response for r in results}})
        await asyncio.sleep(0.02)
        step = steps[len(results)]
        if isinstance(step, str):
            part = types.Part(text=step)
        else:
            part = types.Part(function_call=types.FunctionCall(id=f"call-{len(Plays.seen)}", name=step[0], args=step[1]))
        yield LlmResponse(content=types.Content(role="model", parts=[part]))


def _ctx(session_id: str) -> SimpleNamespace:
    return SimpleNamespace(session=SimpleNamespace(id=session_id), invocation_id="inv-1")


@pytest.fixture
async def runner(store, monkeypatch):
    from odie.app import runner as runner_mod
    from odie.plugins import mcp
    Plays.seen = []
    monkeypatch.setattr(runner_mod, "model_for", lambda selection, thinking, room=None: Plays(model="plays"))
    monkeypatch.setattr(mcp, "asks", lambda tool, free, smart=False: False)  # these tests are about who, not taps
    r = runner_mod.OdieRunner(store)
    yield r
    await r.close()


async def _say(runner, words: str, session_id: str) -> list[dict]:
    events = [e async for e in runner.chat(words, session_id=session_id)]
    assert not [e for e in events if e["type"] == "error"], events
    return events


def _of(who: str) -> list[dict]:
    return [s for s in Plays.seen if s["who"] == who]


async def test_off_in_her_thread_and_on_in_odies_at_the_same_time(runner, store):
    from odie.plugins import mcp
    mcp.write_config({"tester": TESTER})
    mira = personalities.create(store, "Mira")
    access.set_allowed(store, "tester", mira.id, False)
    await runner.load_plugins()
    miras = await runner.session_for(mira.id, D)
    Plays.script = {"Mira": [("load_skill", {"skill_name": "mcp-tester"}), "I can't use that here."],
                    "Odie": [("load_skill", {"skill_name": "mcp-tester"}), ("echo", {"text": "hi"}), "hi"]}
    await asyncio.gather(_say(runner, "Mira wants an echo", miras),
                         _say(runner, "Odie wants an echo", runner.current_session_id(D)))
    hers, odies = _of("Mira"), _of("Odie")
    assert {s["who"] for s in Plays.seen[:2]} == {"Mira", "Odie"}  # side by side
    assert "mcp-tester" not in hers[0]["system"]  # not in her catalog
    assert "mcp-tester" in odies[0]["system"]
    refused = hers[-1]["results"]["load_skill"]
    assert "error" in refused and "Mira" in refused["error"]  # its skill won't load there
    assert all(not APP_TOOLS & s["tools"] for s in hers)  # its tools are never listed there
    assert APP_TOOLS <= odies[-1]["tools"] and odies[-1]["results"]["echo"]  # everyday Odie's turn used it
    audited = store.query("select tool, session_id from audit_log where event='tool_refused'")
    assert [(r["tool"], r["session_id"]) for r in audited] == [("load_skill", miras)]


async def test_a_call_to_an_off_servers_tool_is_refused_before_it_runs(runner, store):
    """The model may remember a tool name from before the switch went off: the call never reaches the server."""
    from odie.plugins import mcp
    mcp.write_config({"tester": TESTER})
    mira = personalities.create(store, "Mira")
    await runner.load_plugins()
    miras = await runner.session_for(mira.id, D)
    access.set_allowed(store, "tester", mira.id, False)
    echo = SimpleNamespace(name="echo")
    refused = await runner.plugin.before_tool_callback(tool=echo, tool_args={"text": "x"}, tool_context=_ctx(miras))
    assert refused == {"error": access.OFF_HERE.format(app="tester", name="Mira")}
    assert await runner.plugin.before_tool_callback(tool=echo, tool_args={"text": "x"},
                                                    tool_context=_ctx(runner.current_session_id(D))) is None
    audited = store.query("select tool, session_id, result_summary from audit_log where event='tool_refused'")
    assert [(r["tool"], r["session_id"]) for r in audited] == [("echo", miras)]


async def test_an_always_on_servers_tools_are_not_listed_where_it_is_off(runner, store):
    from odie.plugins import mcp
    mcp.write_config({"tester": {**TESTER, "alwaysOn": True}})
    mira = personalities.create(store, "Mira")
    access.set_allowed(store, "tester", mira.id, False)
    await runner.load_plugins()
    miras = await runner.session_for(mira.id, D)
    Plays.script = {"Mira": ["Hello."], "Odie": ["Hello."]}
    await _say(runner, "Mira says hello", miras)
    await _say(runner, "Odie says hello", runner.current_session_id(D))
    assert not APP_TOOLS & _of("Mira")[0]["tools"]
    assert APP_TOOLS <= _of("Odie")[0]["tools"]


async def test_her_prompt_doesnt_claim_an_app_she_cant_use(runner, store):
    from odie.plugins.mcp import ServerEntry
    runner.plugins = {"skills": [], "servers": [ServerEntry("vault", "stdio", "Notes", "ok")]}
    mira = personalities.create(store, "Mira")
    assert "vault" in runner.who(mira.id).caps
    access.set_allowed(store, "vault", mira.id, False)
    assert "vault" not in runner.who(mira.id).caps
    assert "vault" in runner.who().caps


# ── the mail watch is everyday Odie's ──

async def test_the_watch_uses_only_the_servers_on_for_odie(store, monkeypatch):
    from datetime import UTC, datetime

    from odie.plugins import mcp
    from odie.watch import sources
    from odie.watch.calls import CallError
    from odie.watch.fetch import Fetcher
    mcp.write_config({"home-mail": {"url": "https://mail.invalid/mcp"}, "work-mail": {"url": "https://work.invalid/mcp"}})
    mira = personalities.create(store, "Mira")
    access.added(store, "work-mail", mira.id)  # hers alone
    looked_at = []

    async def detect(servers):
        looked_at.extend(servers)
        return []
    monkeypatch.setattr(sources, "detect", detect)
    monkeypatch.setattr(sources, "native_sources", lambda *a, **k: [])
    await sources.detect_and_save(store)
    assert looked_at == ["home-mail"]
    now = datetime.now(UTC)
    assert not sources.stale(store, now)
    access.set_allowed(store, "home-mail", personalities.ODIE, False)
    assert sources.stale(store, now)  # a switch changed: the sources are found again
    fetcher = Fetcher(store, now)
    work = sources.Source("mail", "work-mail", "work-mail", "plain", "search_mail", {})
    with pytest.raises(CallError, match="switched off for Odie"):
        fetcher._spec(work)


async def test_a_background_check_uses_only_odies_apps(runner, store):
    """A background check (the watch's, a tracker's) runs as everyday Odie: an app off for Odie is not in its catalog,
    its skill won't load and its tools never run, even when the app is on for a personality."""
    from odie.plugins import mcp
    mcp.write_config({"tester": TESTER})
    mira = personalities.create(store, "Mira")
    access.added(store, "tester", mira.id)  # hers alone
    await runner.load_plugins()
    Plays.script = {"It is ": [("load_skill", {"skill_name": "mcp-tester"}), ("echo", {"text": "x"}), "Done."]}
    await runner.background_turn("Check the thing")
    first, *_, last = Plays.seen
    assert "mcp-tester" not in first["system"]
    assert "error" in last["results"]["load_skill"]
    assert not APP_TOOLS & last["tools"]
    assert "echo" not in last["results"] or "error" in last["results"]["echo"]  # never ran


# ── Settings → Connected apps, for whoever is picked ──

@pytest.fixture
async def api(runner, monkeypatch):
    import httpx

    from odie.app.main import create_app
    monkeypatch.setenv("ODIE_SCHEDULER", "0")
    app = create_app(runner=runner, store=runner.store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c, \
            app.router.lifespan_context(app):
        yield c


def _can_use(listing: dict) -> dict[str, bool]:
    return {row["name"]: row["canUse"] for row in listing["servers"]}


async def test_the_apps_list_and_switch_follow_the_pick(api, runner, store, monkeypatch):
    from odie.plugins import mcp

    async def no_reload():
        return runner.plugins
    monkeypatch.setattr(runner, "load_plugins", no_reload)  # no servers are started here
    mcp.write_config({"home-mail": {"url": "https://mail.invalid/mcp"}})
    mira = personalities.create(store, "Mira")
    assert _can_use((await api.get("/api/mcp")).json()) == {"home-mail": True}
    off = await api.post(f"/api/mcp/home-mail/access?personality={mira.id}", json={"on": False})
    assert off.status_code == 200
    assert _can_use((await api.get(f"/api/mcp?personality={mira.id}")).json()) == {"home-mail": False}
    assert _can_use((await api.get("/api/mcp")).json()) == {"home-mail": True}  # Odie's stays on
    assert (await api.post("/api/mcp/nothing/access", json={"on": False})).status_code == 404
    assert (await api.post("/api/mcp/home-mail/access?personality=nobody", json={"on": False})).status_code == 404

    added = await api.post(f"/api/mcp?personality={mira.id}", json={"name": "work-mail",
                                                                    "spec": {"url": "https://work.invalid/mcp"}})
    assert added.status_code == 200
    assert _can_use((await api.get(f"/api/mcp?personality={mira.id}")).json()) == {"home-mail": False, "work-mail": True}
    assert _can_use((await api.get("/api/mcp")).json()) == {"home-mail": True, "work-mail": False}
    edited = await api.post("/api/mcp", json={"name": "work-mail", "spec": {"url": "https://work2.invalid/mcp"}})
    assert edited.status_code == 200  # editing it with Odie picked doesn't hand it to Odie
    assert _can_use((await api.get("/api/mcp")).json())["work-mail"] is False

    assert (await api.delete("/api/mcp/work-mail")).status_code == 200
    assert store.one("select * from app_access where server='work-mail'") is None


async def test_connecting_a_service_while_she_is_picked_is_hers(api, runner, store, monkeypatch):
    from odie.app import routes
    from odie.plugins import mcp

    async def no_reload():
        return runner.plugins

    async def answers(spec, smart=False):
        return {"ok": True, "tools": []}
    monkeypatch.setattr(runner, "load_plugins", no_reload)
    monkeypatch.setattr(routes, "_check", answers)
    mira = personalities.create(store, "Mira")
    made = await api.post(f"/api/mcp/connect?personality={mira.id}",
                          json={"preset": "zapier", "url": "https://mcp.zapier.com/api/mcp/s/abc/mcp"})
    assert made.status_code == 200
    name = made.json()["name"]
    assert access.allowed(store, name, mira.id) and not access.allowed(store, name, ODIE)
    again = await api.post("/api/mcp/connect", json={"preset": "zapier", "url": "https://mcp.zapier.com/api/mcp/s/new/mcp"})
    assert again.json()["replaced"] is True and not access.allowed(store, name, ODIE)  # a new link keeps the switches
    assert mcp.read_config()[0][name]["url"].endswith("/new/mcp")
