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
    from odie.plugins import mcp
    mcp.write_config({"home-mail": {"url": "https://home.example.invalid/mcp", "title": "Home mail"},
                      "work-mail": {"url": "https://work.example.invalid/mcp", "title": "Work mail"}})
    access.remember_tools(store, {"home-mail": ["read_home"], "work-mail": ["read_work"]})  # nothing in common
    mira = personalities.create(store, "Mira")
    access.set_allowed(store, "home-mail", mira.id, False)
    access.set_allowed(store, "home-mail", ODIE, False)
    access.added(store, "work-mail", mira.id)
    r = OdieRunner(store)
    try:
        await personalities.delete(store, r, mira.id)
    finally:
        await r.close()
    assert store.one("select * from app_access where personality=?", (mira.id,)) is None
    assert not access.allowed(store, "home-mail", ODIE)  # Odie's own switch stays
    assert access.allowed(store, "work-mail", ODIE)  # hers alone: back to Odie (give_back_to_odie)


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


ODIES_LINK = "https://mcp.zapier.com/api/mcp/s/odies-link/mcp"
MIRAS_LINK = "https://mcp.zapier.com/api/mcp/s/miras-link/mcp"


@pytest.fixture
def connecting(runner, monkeypatch):
    """Connecting a preset without starting anything: the check always answers, and no servers are loaded."""
    from odie.app import routes

    async def no_reload():
        return runner.plugins

    async def answers(spec, smart=False):
        return {"ok": True, "tools": []}
    monkeypatch.setattr(runner, "load_plugins", no_reload)
    monkeypatch.setattr(routes, "_check", answers)


def _links() -> dict[str, str]:
    from odie.plugins import mcp
    return {name: spec["url"] for name, spec in mcp.read_config()[0].items()}


async def test_connecting_never_replaces_another_ones_connection(api, store, connecting):
    """Odie's zapier is on for everyone; Mira connects her own link: she gets a connection of her own and Odie's stays
    as it was (now off for her). Then each reconnecting their own replaces it in place."""
    from odie.plugins import mcp
    mcp.write_config({"zapier": {"url": ODIES_LINK, "title": "Zapier"}})
    mira = personalities.create(store, "Mira")
    hers = await api.post(f"/api/mcp/connect?personality={mira.id}", json={"preset": "zapier", "url": MIRAS_LINK})
    assert hers.status_code == 200 and hers.json()["replaced"] is False
    assert hers.json()["name"] == "zapier-2"
    assert _links() == {"zapier": ODIES_LINK, "zapier-2": MIRAS_LINK}  # Odie's link untouched
    assert access.allowed(store, "zapier-2", mira.id) and not access.allowed(store, "zapier-2", ODIE)
    assert not access.allowed(store, "zapier", mira.id) and access.allowed(store, "zapier", ODIE)
    rows = (await api.get(f"/api/mcp?personality={mira.id}")).json()["servers"]
    assert {r["name"]: r["onlyPick"] for r in rows} == {"zapier": False, "zapier-2": True}  # what Settings tells her

    newer = MIRAS_LINK.replace("miras-link", "miras-new")
    again = await api.post(f"/api/mcp/connect?personality={mira.id}", json={"preset": "zapier", "url": newer})
    assert (again.json()["name"], again.json()["replaced"]) == ("zapier-2", True)  # hers alone: replaced in place
    assert _links() == {"zapier": ODIES_LINK, "zapier-2": newer}

    odies_new = ODIES_LINK.replace("odies-link", "odies-new")
    odie = await api.post("/api/mcp/connect", json={"preset": "zapier", "url": odies_new})
    assert (odie.json()["name"], odie.json()["replaced"]) == ("zapier", True)  # Odie's alone now: replaced in place
    assert _links() == {"zapier": odies_new, "zapier-2": newer}


async def test_odie_reconnecting_a_connection_she_shares_gets_his_own(api, store, connecting):
    from odie.plugins import mcp
    mcp.write_config({"zapier": {"url": ODIES_LINK, "title": "Zapier"}})
    mira = personalities.create(store, "Mira")
    odies_new = ODIES_LINK.replace("odies-link", "odies-new")
    odie = await api.post("/api/mcp/connect", json={"preset": "zapier", "url": odies_new})
    assert (odie.json()["name"], odie.json()["replaced"]) == ("zapier-2", False)
    assert _links() == {"zapier": ODIES_LINK, "zapier-2": odies_new}  # the one she uses is left as it was
    assert access.allowed(store, "zapier", mira.id) and not access.allowed(store, "zapier", ODIE)


async def test_with_no_personalities_reconnecting_replaces_as_before(api, store, connecting):
    from odie.plugins import mcp
    mcp.write_config({"zapier": {"url": ODIES_LINK, "title": "Zapier"}})
    odies_new = ODIES_LINK.replace("odies-link", "odies-new")
    odie = await api.post("/api/mcp/connect", json={"preset": "zapier", "url": odies_new})
    assert (odie.json()["name"], odie.json()["replaced"]) == ("zapier", True)
    assert _links() == {"zapier": odies_new}


async def test_deleting_the_one_an_app_belonged_to_gives_it_back_to_odie(store):
    """work-mail was added with Mira picked (hers alone). With her gone no one could use it, and with no personalities
    left its switch wouldn't even show, so it goes back on for everyday Odie, and the log says so. An app another
    personality still uses stays as it is."""
    from odie.app.runner import OdieRunner
    from odie.plugins import mcp
    mcp.write_config({"work-mail": {"url": "https://work.example.invalid/mcp", "title": "Work mail"},
                      "coach-app": {"url": "https://coach.example.invalid/mcp", "title": "Coach"}})
    mira = personalities.create(store, "Mira")
    coach = personalities.create(store, "Coach")
    access.added(store, "work-mail", mira.id)
    access.added(store, "coach-app", coach.id)
    r = OdieRunner(store)
    try:
        await personalities.delete(store, r, mira.id)
    finally:
        await r.close()
    assert access.allowed(store, "work-mail", ODIE)
    assert not access.allowed(store, "coach-app", ODIE)  # Coach still uses it: Odie's switch is left alone
    said = [row["result_summary"] for row in store.query("select result_summary from audit_log where event='app_access'")]
    assert said == ["work-mail on for everyday Odie: no one else could use it"]


def test_which_app_a_tool_call_reaches(store, monkeypatch):
    from odie.plugins import mcp
    monkeypatch.setattr(mcp, "TOOL_SERVERS", {"echo": ["tester"]})
    odies = "chat-2026-11-17"
    named = SimpleNamespace(name="echo")  # an object with no stamp: looked up by its name
    stamped = SimpleNamespace(name="echo", _odie_server="tester-2")  # the toolset said where it goes: that wins
    skill = SimpleNamespace(name="load_skill")
    assert access.server_called(store, named, {"text": "x"}, odies) == "tester"
    assert access.server_called(store, stamped, {"text": "x"}, odies) == "tester-2"
    assert access.server_called(store, skill, {"skill_name": "mcp-tester"}, odies) == "tester"
    assert access.server_called(store, skill, {"skill_name": "trackers"}, odies) is None
    assert access.server_called(store, skill, {}, odies) is None
    assert access.server_called(store, skill, None, odies) is None
    assert access.server_called(store, SimpleNamespace(name="run_shell"), {"command": "ls"}, odies) is None


async def test_a_tapped_call_whose_object_reaches_another_app_than_its_card_lapses(runner, store):
    """The last guard, as the tapped call is about to run: its object must reach the very server the card named."""
    mira = await _home_and_work_mail(runner, store)
    del mira
    odies = runner.current_session_id(D)
    aid = store.create_approval(odies, "inv-1", "req-1", "send_email", {"text": "hi"}, summary="Send email in Home mail",
                                detail={"server": "mail", "app": "Home mail"}, provenance=[], call_id="call-7")
    store.decide_approval(aid, True)
    tapped = SimpleNamespace(session=SimpleNamespace(id=odies), function_call_id="call-7",
                             tool_confirmation=SimpleNamespace(confirmed=True))
    work_object = SimpleNamespace(name="send_email", _odie_server="mail-2")
    refused = await runner.plugin.before_tool_callback(tool=work_object, tool_args={"text": "hi"}, tool_context=tapped)
    assert refused == {"error": LAPSED}
    assert store.get_approval(aid)["status"] == "expired"
    home_object = SimpleNamespace(name="send_email", _odie_server="mail")
    aid2 = store.create_approval(odies, "inv-2", "req-2", "send_email", {"text": "hi"}, summary="Send email in Home mail",
                                 detail={"server": "mail", "app": "Home mail"}, provenance=[], call_id="call-8")
    store.decide_approval(aid2, True)
    tapped.function_call_id = "call-8"
    assert await runner.plugin.before_tool_callback(tool=home_object, tool_args={"text": "hi"}, tool_context=tapped) is None


# ── two connections of one service, one for each owner ──

MAIL = str(Path(__file__).parent / "fixtures" / "mcp_account_mail.py")
HOME_MAIL = {"command": sys.executable, "args": [MAIL], "env": {"MAIL_ACCOUNT": "home"}, "title": "Home mail"}
WORK_MAIL = {"command": sys.executable, "args": [MAIL], "env": {"MAIL_ACCOUNT": "work"}, "title": "Work mail"}


async def _home_and_work_mail(runner, store):
    """Everyday Odie's home mail (`mail`) and Mira's work mail (`mail-2`): the same tool names, one owner each."""
    from odie.plugins import mcp
    mcp.write_config({"mail": HOME_MAIL, "mail-2": WORK_MAIL})
    mira = personalities.create(store, "Mira")
    access.added(store, "mail-2", mira.id)  # hers alone
    access.set_allowed(store, "mail", mira.id, False)  # and Odie's isn't hers
    await runner.load_plugins()
    return mira


def _sent(steps: list[dict]) -> str:
    """What the send_email call of a turn answered, as text."""
    return str(steps[-1]["results"]["send_email"])


async def test_two_connections_with_the_same_tools_both_load_and_each_thread_reaches_its_own(runner, store):
    mira = await _home_and_work_mail(runner, store)
    status = {e.name: (e.status, e.reason) for e in runner.plugins["servers"]}
    assert status == {"mail": ("ok", ""), "mail-2": ("ok", "")}
    miras = await runner.session_for(mira.id, D)
    Plays.script = {"Mira": [("load_skill", {"skill_name": "mcp-mail-2"}), ("send_email", {"text": "hi"}), "Sent."],
                    "Odie": [("load_skill", {"skill_name": "mcp-mail"}), ("send_email", {"text": "hi"}), "Sent."]}
    await asyncio.gather(_say(runner, "Mira sends a mail", miras),
                         _say(runner, "Odie sends a mail", runner.current_session_id(D)))
    assert {s["who"] for s in Plays.seen[:2]} == {"Mira", "Odie"}  # side by side
    assert "the work account" in _sent(_of("Mira")) and "home" not in _sent(_of("Mira"))
    assert "the home account" in _sent(_of("Odie")) and "work" not in _sent(_of("Odie"))
    assert "mcp-mail-2" in _of("Mira")[0]["system"] and "mcp-mail\n" not in _of("Mira")[0]["system"]


async def test_two_connections_both_on_for_one_owner_still_clash_as_before(runner, store):
    from odie.plugins import mcp
    mcp.write_config({"mail": HOME_MAIL, "mail-2": WORK_MAIL})  # nobody switched anything: both are everyday Odie's
    from odie.plugins.mcp import ONE_OF_TWO
    await runner.load_plugins()
    status = {e.name: (e.status, e.reason) for e in runner.plugins["servers"]}
    assert status["mail"] == ("ok", "")
    assert status["mail-2"] == ("error", "tool names clash with find_email (mail). " + ONE_OF_TWO)  # today's words, and what to do


async def test_a_remembered_call_resolves_to_the_owners_own_connection(runner, store):
    mira = await _home_and_work_mail(runner, store)
    miras = await runner.session_for(mira.id, D)
    odies = runner.current_session_id(D)
    send = SimpleNamespace(name="send_email")
    assert access.server_of_tool(store, "send_email", odies) == "mail"
    assert access.server_of_tool(store, "send_email", miras) == "mail-2"
    assert await runner.plugin.before_tool_callback(tool=send, tool_args={"text": "x"}, tool_context=_ctx(odies)) is None
    assert await runner.plugin.before_tool_callback(tool=send, tool_args={"text": "x"}, tool_context=_ctx(miras)) is None
    access.set_allowed(store, "mail", ODIE, False)  # now both are off for Odie
    refused = await runner.plugin.before_tool_callback(tool=send, tool_args={"text": "x"}, tool_context=_ctx(odies))
    assert refused == {"error": access.OFF_HERE.format(app="mail", name="Odie")}


async def test_the_card_and_the_log_name_her_connection(runner, store):
    from odie.app.runner import approval_from_confirmation
    mira = await _home_and_work_mail(runner, store)
    miras = await runner.session_for(mira.id, D)

    call = SimpleNamespace(id="c1", args={"originalFunctionCall": {"name": "send_email", "args": {"text": "hi"}}})
    assert approval_from_confirmation(call, "inv-1", miras, store)["detail"]["app"] == "Work mail"
    assert approval_from_confirmation(call, "inv-1", runner.current_session_id(D), store)["detail"]["app"] == "Home mail"
    await runner.plugin.after_tool_callback(tool=SimpleNamespace(name="send_email"), tool_args={"text": "hi"},
                                            tool_context=_ctx(miras), result={"content": []})
    logged = store.one("select result_summary from audit_log where event='tool_call' and session_id=?", (miras,))
    assert logged["result_summary"].startswith("mail-2: ")


async def test_the_load_hint_points_to_her_connections_skill(runner, store):
    mira = await _home_and_work_mail(runner, store)
    miras = await runner.session_for(mira.id, D)
    hint = await runner.plugin.on_tool_error_callback(tool=SimpleNamespace(name="send_email"), tool_args={},
                                                      tool_context=_ctx(miras), error=ValueError("Tool 'send_email' not found."))
    assert 'load_skill("mcp-mail-2")' in hint["error"] and "Work mail" in hint["error"]


MAIL_TOOLS = {"mail": ["find_email", "send_email"], "mail-2": ["find_email", "send_email"]}  # what each listed


@pytest.mark.parametrize("always_on", [False, True], ids=["on demand", "always on"])
async def test_switching_on_a_second_connection_for_one_owner_is_refused_in_words(api, runner, store, always_on):
    from odie.plugins import mcp
    mcp.write_config({"mail": {**HOME_MAIL, "alwaysOn": bool(always_on)}, "mail-2": {**WORK_MAIL, "alwaysOn": bool(always_on)}})
    access.remember_tools(store, MAIL_TOOLS)
    mira = personalities.create(store, "Mira")
    access.added(store, "mail-2", mira.id)
    access.set_allowed(store, "mail", mira.id, False)
    refused = await api.post(f"/api/mcp/mail/access?personality={mira.id}", json={"on": True})
    assert refused.status_code == 409
    assert refused.json()["detail"] == "Mira already has these tools from 'mail-2'; switch that one off for Mira first."
    assert not access.allowed(store, "mail", mira.id)  # nothing changed
    assert (await api.post(f"/api/mcp/mail-2/access?personality={mira.id}", json={"on": False})).status_code == 200
    assert (await api.post(f"/api/mcp/mail/access?personality={mira.id}", json={"on": True})).status_code == 200
    assert (await api.post(f"/api/mcp/mail/access?personality={mira.id}", json={"on": False})).status_code == 200  # off: never refused


def test_a_new_personality_never_starts_with_a_clash(store):
    """She copies everyday Odie's switches, and Odie never has two connections of a service on: neither does she."""
    configured = {"mail": HOME_MAIL, "mail-2": WORK_MAIL, "notes": {"url": "https://notes.example.invalid/mcp"}}
    access.remember_tools(store, {**MAIL_TOOLS, "notes": ["read_note"]})
    access.added(store, "mail-2", "")  # an old pick of Odie's: mail-2 his alone
    access.set_allowed(store, "mail", ODIE, False)
    mira = personalities.create(store, "Mira")
    on_for_her = [s for s in configured if access.allowed(store, s, mira.id)]
    assert on_for_her == ["mail-2", "notes"]
    assert all(access.clash_for(store, s, mira.id, configured) is None for s in on_for_her)


async def test_deleting_her_doesnt_give_odie_a_second_connection_of_his_service(store):
    from odie.app.runner import OdieRunner
    from odie.plugins import mcp
    mcp.write_config({"mail": HOME_MAIL, "mail-2": WORK_MAIL})
    access.remember_tools(store, MAIL_TOOLS)
    mira = personalities.create(store, "Mira")
    access.added(store, "mail-2", mira.id)
    access.set_allowed(store, "mail", mira.id, False)
    r = OdieRunner(store)
    try:
        await personalities.delete(store, r, mira.id)
    finally:
        await r.close()
    assert not access.allowed(store, "mail-2", ODIE)  # Odie has mail on: its switch shows instead (off for him)
    assert access.allowed(store, "mail", ODIE)


async def test_the_watch_reads_only_odies_connection_of_a_service(runner, store):
    """Home mail is Odie's, work mail Mira's, with the same tools: the watch, Odie's background work, finds and calls
    only the home one."""
    from datetime import UTC, datetime

    from odie.watch import sources
    from odie.watch.calls import CallError
    from odie.watch.fetch import Fetcher
    await _home_and_work_mail(runner, store)
    looked_at = []
    real_detect = sources.detect

    async def detect(servers):
        looked_at.extend(servers)
        return await real_detect(servers)
    sources.detect, saved = detect, sources.detect
    try:
        await sources.detect_and_save(store)
    finally:
        sources.detect = saved
    assert looked_at == ["mail"]
    fetcher = Fetcher(store, datetime.now(UTC))
    work = sources.Source("mail", "mail-2", "Work mail", "plain", "find_email", {})
    with pytest.raises(CallError, match="switched off for Odie"):
        fetcher._spec(work)


async def test_her_own_connected_service_loads_and_is_the_one_her_thread_uses(api, runner, store, monkeypatch):
    """Fix 1's flow end to end: Odie has zapier; Mira connects her own link; both load, and her thread's calls go to
    hers."""
    from odie.app import routes
    from odie.plugins import mcp

    async def answers(spec, smart=False):
        return {"ok": True, "tools": []}

    async def zapier_lists(spec, timeout):
        return [{"name": "inspect_zapier_actions"}, {"name": "execute_zapier_read_action"}]
    monkeypatch.setattr(routes, "_check", answers)
    monkeypatch.setattr(mcp, "probe_tools", zapier_lists)
    mcp.write_config({"zapier": {"url": ODIES_LINK, "title": "Zapier"}})
    mira = personalities.create(store, "Mira")
    made = await api.post(f"/api/mcp/connect?personality={mira.id}", json={"preset": "zapier", "url": MIRAS_LINK})
    assert made.json()["name"] == "zapier-2"
    status = {e.name: e.status for e in runner.plugins["servers"]}
    assert status == {"zapier": "ok", "zapier-2": "ok"}
    miras = await runner.session_for(mira.id, D)
    assert access.server_of_tool(store, "execute_zapier_read_action", miras) == "zapier-2"
    assert access.server_of_tool(store, "execute_zapier_read_action", runner.current_session_id(D)) == "zapier"
    assert access.skills_off_in(store, miras) == frozenset({"mcp-zapier"})  # her catalog shows only her own


# ── a tap is consent for the account the card named, and nothing else ──

@pytest.fixture
def sending_asks(monkeypatch):
    """send_email waits for a tap, as a real send does; the rest run without one."""
    from odie.plugins import mcp
    monkeypatch.setattr(mcp, "asks", lambda tool, free, smart=False: tool["name"] == "send_email")


SEND_SCRIPT = {"Odie": [("load_skill", {"skill_name": "mcp-mail"}), ("send_email", {"text": "hi"}), "Sent.", "Sent."],
               "Mira": [("load_skill", {"skill_name": "mcp-mail-2"}), ("find_email", {"query": "q"}), "Found."]}


async def _odies_card(runner) -> dict:
    """Odie asks to send a mail from his home account; the turn pauses on its card."""
    Plays.script = dict(SEND_SCRIPT)
    events = [e async for e in runner.chat("Odie sends a mail", session_id=runner.current_session_id(D))]
    [card] = [e for e in events if e["type"] == "approval"]
    return card


def _move_odie_to_work_mail(store) -> None:
    """The owner switches everyday Odie from home mail to work mail."""
    access.set_allowed(store, "mail", ODIE, False)
    access.set_allowed(store, "mail-2", ODIE, True)


def _accounts_that_sent() -> list[str]:
    """Which account answered each send_email that ran, from the tool results the model was shown."""
    sent = []
    for step in Plays.seen:
        said = str(step["results"].get("send_email", ""))
        for account in ("home", "work"):
            if f"sent from the {account} account" in said:
                sent.append(account)
    return sent


LAPSED = "This card was for Home mail, which is now off for Odie. Ask again."


async def test_a_tap_runs_on_the_account_the_card_named(runner, store, sending_asks):
    await _home_and_work_mail(runner, store)
    card = await _odies_card(runner)
    assert card["detail"]["app"] == "Home mail" and card["detail"]["server"] == "mail"
    await runner.resume_approval(card["id"], True)
    assert _accounts_that_sent() == ["home"]


async def test_a_tap_after_the_owner_moved_odie_to_another_account_sends_nothing(runner, store, sending_asks):
    await _home_and_work_mail(runner, store)
    card = await _odies_card(runner)
    _move_odie_to_work_mail(store)
    got = await runner.resume_approval(card["id"], True)
    assert _accounts_that_sent() == []
    assert got == {"error": LAPSED}
    row = store.get_approval(card["id"])
    assert (row["status"], row["result_text"]) == ("expired", LAPSED)
    assert store.one("select 1 from audit_log where event='approval_lapsed' and approval_id=?", (card["id"],))


async def test_another_turn_between_the_card_and_the_tap_changes_nothing(runner, store, sending_asks):
    mira = await _home_and_work_mail(runner, store)
    card = await _odies_card(runner)
    await _say(runner, "Mira finds a mail", await runner.session_for(mira.id, D))  # lists the apps again
    _move_odie_to_work_mail(store)
    assert await runner.resume_approval(card["id"], True) == {"error": LAPSED}
    assert _accounts_that_sent() == []


async def test_a_pending_card_after_a_restart_is_held_to_its_account(store, sending_asks, monkeypatch):
    from odie.app import runner as runner_mod
    monkeypatch.setattr(runner_mod, "model_for", lambda selection, thinking, room=None: Plays(model="plays"))
    Plays.seen = []
    first = runner_mod.OdieRunner(store)
    try:
        await _home_and_work_mail(first, store)
        card = await _odies_card(first)
    finally:
        await first.close()
    _move_odie_to_work_mail(store)
    second = runner_mod.OdieRunner(store)  # Odie restarted with the card still waiting
    try:
        await second.load_plugins()
        assert await second.resume_approval(card["id"], True) == {"error": LAPSED}
    finally:
        await second.close()
    assert _accounts_that_sent() == []


async def test_a_switch_flipped_while_the_model_writes_the_call_stops_it(runner, store, monkeypatch):
    """The model's request listed home mail; the owner moves Odie to work mail before the call comes back: the call
    reaches the server it was listed from (home), which is now off for Odie, so it is refused and nothing is sent."""
    await _home_and_work_mail(runner, store)
    real = Plays.generate_content_async

    async def flips_while_writing(self, llm_request, stream=False):
        odies_steps = len([s for s in Plays.seen if s["who"] == "Odie"])
        if odies_steps == 1:
            _move_odie_to_work_mail(store)
        async for reply in real(self, llm_request, stream):
            yield reply
    monkeypatch.setattr(Plays, "generate_content_async", flips_while_writing)
    Plays.script = {"Odie": [("load_skill", {"skill_name": "mcp-mail"}), ("send_email", {"text": "hi"}), "Not sent."]}
    await _say(runner, "Odie sends a mail", runner.current_session_id(D))
    assert _accounts_that_sent() == []
    refused = Plays.seen[-1]["results"]["send_email"]
    assert refused == {"error": access.OFF_HERE.format(app="mail", name="Odie")}
    logged = store.one("select result_summary from audit_log where event='tool_refused' and tool='send_email'")
    assert logged["result_summary"] == "mail switched off here"


async def test_tapping_a_card_whose_app_moved_answers_it_as_lapsed(api, runner, store):
    await _home_and_work_mail(runner, store)
    odies = runner.current_session_id(D)
    aid = store.create_approval(odies, "inv-1", "req-1", "send_email", {"text": "hi"}, summary="Send email in Home mail",
                                detail={"server": "mail", "app": "Home mail"}, provenance=[], call_id="call-7")
    _move_odie_to_work_mail(store)
    tapped = await api.post(f"/api/approvals/{aid}/decide", json={"approve": True})
    assert tapped.status_code == 200 and tapped.json() == {"status": "expired", "text": LAPSED}
    assert store.get_approval(aid)["status"] == "expired"


async def test_an_apps_tools_are_listed_again_at_each_step_and_carry_their_server(isolated_settings):
    """ADK keeps a toolset's tools for the whole turn unless the toolset says not to: an app's are listed again at each
    step, so a switch or the approvals mode changed mid-turn shows on the next step, and each tool says its server."""
    from odie.plugins import mcp
    smart = {"on": False}
    toolset = mcp.toolset_for("tester", TESTER, smart=lambda session_id: smart["on"])
    step = SimpleNamespace(session=SimpleNamespace(id="chat-2026-11-17"), invocation_id="inv-1", state={}, agent_name="odie")
    try:
        first = {t.name: t for t in await toolset.get_tools_with_prefix(step)}
        smart["on"] = True  # Smart from the next step on, in the same turn
        second = {t.name: t for t in await toolset.get_tools_with_prefix(step)}
    finally:
        await toolset.close()
    assert first["echo"]._odie_server == "tester" and second["echo"]._odie_server == "tester"
    assert first["echo"] is not second["echo"]  # listed again, not ADK's copy from the turn's first step
    assert first["echo"]._require_confirmation is True and second["echo"]._require_confirmation is False


# ── what a server could clash with, when its listing failed or it is off ──

async def _deleting_mira_after(runner, store, odies_mail: dict) -> None:
    """Home mail (Odie's) and work mail (Mira's) both listed once; then home mail is changed to `odies_mail` (broken,
    or switched off) and loaded again, and Mira is deleted."""
    from odie.plugins import mcp
    await _home_and_work_mail(runner, store)
    mcp.write_config({"mail": odies_mail, "mail-2": WORK_MAIL})
    await runner.load_plugins()
    mira = next(p for p in personalities.list_all(store) if p.name == "Mira")
    await personalities.delete(store, runner, mira.id)


@pytest.mark.parametrize("odies_mail", [{**HOME_MAIL, "command": "/nonexistent/mail-server"}, {**HOME_MAIL, "enabled": False}],
                         ids=["home mail failed to list", "home mail switched off"])
async def test_her_mail_isnt_given_to_odie_while_his_own_is_configured(runner, store, odies_mail):
    await _deleting_mira_after(runner, store, odies_mail)
    status = {e.name: e.status for e in runner.plugins["servers"]}
    assert status["mail"] in ("failed", "disabled")
    assert not access.allowed(store, "mail-2", ODIE)  # her business mail never becomes everyday Odie's
    assert access.allowed(store, "mail", ODIE)


async def test_switching_on_is_judged_by_the_last_known_tools(api, runner, store):
    from odie.plugins import mcp
    mira = await _home_and_work_mail(runner, store)
    mcp.write_config({"mail": {**HOME_MAIL, "command": "/nonexistent/mail-server"}, "mail-2": WORK_MAIL})
    await runner.load_plugins()  # home mail fails to list now: its tools are still known
    refused = await api.post(f"/api/mcp/mail/access?personality={mira.id}", json={"on": True})
    assert refused.status_code == 409
    assert refused.json()["detail"] == "Mira already has these tools from 'mail-2'; switch that one off for Mira first."


def test_with_nothing_known_two_connections_of_one_service_count_as_clashing(store):
    """Tools never listed (both failed since they were added): the same link's host, title, preset or program means
    the same service, so switching the second on is refused rather than risked."""
    configured = {"mail": {"url": "https://mail.example.invalid/mcp/home"},
                  "mail-2": {"url": "https://mail.example.invalid/mcp/work"},
                  "notes": {"url": "https://notes.example.invalid/mcp"}}
    mira = personalities.create(store, "Mira")
    access.added(store, "mail-2", mira.id)
    assert access.clash_for(store, "mail", mira.id, configured) == \
        "Mira already has these tools from 'mail-2'; switch that one off for Mira first."
    assert access.clash_for(store, "notes", mira.id, configured) is None
    same_program = {"mail": HOME_MAIL, "mail-2": WORK_MAIL}  # one program, two accounts
    assert access.clash_for(store, "mail", mira.id, same_program) is not None


# ── adding her own mail by hand while she is picked ──

async def test_her_own_mail_added_by_hand_works_at_once(api, runner, store):
    """Home mail is on for everyone; with Mira picked the owner adds work mail by the custom form. Work mail is hers,
    home mail is switched off for her (the response says so), both load without a restart, and each thread reaches its
    own account."""
    from odie.plugins import mcp
    mcp.write_config({"mail": HOME_MAIL})
    await runner.load_plugins()
    mira = personalities.create(store, "Mira")
    saved = await api.post(f"/api/mcp?personality={mira.id}", json={"name": "work-mail", "spec": dict(WORK_MAIL)})
    assert saved.status_code == 200
    assert saved.json()["switched_off"] == ["mail"]
    assert saved.json()["note"] == "mail is now off for Mira, so Mira uses work-mail instead."
    status = {e.name: (e.status, e.reason) for e in runner.plugins["servers"]}
    assert status == {"mail": ("ok", ""), "work-mail": ("ok", "")}
    miras = await runner.session_for(mira.id, D)
    Plays.script = {"Mira": [("load_skill", {"skill_name": "mcp-work-mail"}), ("send_email", {"text": "hi"}), "Sent."],
                    "Odie": [("load_skill", {"skill_name": "mcp-mail"}), ("send_email", {"text": "hi"}), "Sent."]}
    await _say(runner, "Mira sends a mail", miras)
    await _say(runner, "Odie sends a mail", runner.current_session_id(D))
    assert "the work account" in _sent(_of("Mira")) and "the home account" in _sent(_of("Odie"))


async def test_a_switch_that_clears_a_clash_loads_the_refused_server_again(api, runner, store):
    from odie.plugins import mcp
    mcp.write_config({"mail": HOME_MAIL, "mail-2": WORK_MAIL})  # both everyday Odie's: the second is refused
    await runner.load_plugins()
    status = {e.name: (e.status, e.reason) for e in runner.plugins["servers"]}
    said = "tool names clash with find_email (mail). Only one of them can be on for each one: switch one of the two off, " \
        "or off for whoever has both."
    assert status["mail-2"] == ("error", said)
    assert (await api.post("/api/mcp/mail/access", json={"on": False})).status_code == 200
    status = {e.name: e.status for e in runner.plugins["servers"]}
    assert status == {"mail": "ok", "mail-2": "ok"}  # loaded again: no restart needed


ZAPIER_SHARED_LINK = "https://mcp.zapier.com/api/mcp/mcp"  # one link for every account; the code says whose


async def test_reconnecting_with_a_new_code_replaces_ones_own_connection_of_a_shared_link(api, store, connecting):
    from odie.plugins import mcp
    mira = personalities.create(store, "Mira")
    hers = await api.post(f"/api/mcp/connect?personality={mira.id}", json={"preset": "zapier", "url": ZAPIER_SHARED_LINK,
                                                                             "key": "business-1234"})
    odies = await api.post("/api/mcp/connect", json={"preset": "zapier", "url": ZAPIER_SHARED_LINK, "key": "personal-1234"})
    assert (hers.json()["name"], odies.json()["name"]) == ("zapier", "zapier-2")
    again = await api.post("/api/mcp/connect", json={"preset": "zapier", "url": ZAPIER_SHARED_LINK, "key": "personal-5678"})
    assert (again.json()["name"], again.json()["replaced"]) == ("zapier-2", True)  # his own, as Settings said
    saved = mcp.read_config()[0]
    assert set(saved) == {"zapier", "zapier-2"}
    assert saved["zapier"]["headers"] == {"Authorization": "Bearer business-1234"}  # hers untouched
    assert saved["zapier-2"]["headers"] == {"Authorization": "Bearer personal-5678"}


async def test_a_wrong_skill_name_is_answered_only_with_skills_usable_in_that_thread(store, monkeypatch):
    from odie.agent.callbacks import OdiePlugin
    from odie.plugins import mcp
    for registry in ("TOOL_APP", "TOOL_SKILL", "TOOL_SERVERS", "SERVER_TITLE", "SERVER_SKILL"):
        monkeypatch.setattr(mcp, registry, {})
    tools = ["tide_times"]
    mcp.remember_loaded([mcp.ServerEntry("tides", "stdio", "Tides", "ok", tools=tools, title="Work tides",
                                         skill=mcp._skill_for("tides", "Tides", tools)),
                         mcp.ServerEntry("tides-home", "stdio", "Tides", "ok", tools=tools, title="Home tides",
                                         skill=mcp._skill_for("tides-home", "Tides", tools))])
    mira = personalities.create(store, "Mira")
    access.added(store, "tides", mira.id)  # hers
    access.set_allowed(store, "tides-home", mira.id, False)  # his
    personalities.claim(store, "chat-2026-11-17-2", mira.id)
    plugin = OdiePlugin(store)
    not_found = {"error": "Skill 'tides' not found.", "error_code": "SKILL_NOT_FOUND"}

    async def hint_in(session_id: str) -> str:
        out = await plugin.after_tool_callback(tool=SimpleNamespace(name="load_skill"), tool_args={"skill_name": "tides"},
                                               tool_context=_ctx(session_id), result=dict(not_found))
        return out["error"]
    odies_hint = await hint_in("chat-2026-11-17")
    assert "mcp-tides-home" in odies_hint and "mcp-tides," not in odies_hint and not odies_hint.endswith("mcp-tides.")
    hers = await hint_in("chat-2026-11-17-2")
    assert "mcp-tides" in hers and "mcp-tides-home" not in hers


async def test_with_nothing_known_of_odies_other_server_hers_stays_off_for_him(store):
    """Nothing at all is known of a server Odie has a switch for (no tools ever listed, no spec to compare): her
    server could be the same service, so it is not handed to him."""
    from odie.app.runner import OdieRunner
    from odie.plugins import mcp
    mcp.write_config({"mail-2": WORK_MAIL})
    mira = personalities.create(store, "Mira")
    access.added(store, "mail-2", mira.id)
    access.set_allowed(store, "mail", mira.id, False)  # a server of Odie's that Odie knows nothing more about
    r = OdieRunner(store)
    try:
        await personalities.delete(store, r, mira.id)
    finally:
        await r.close()
    assert not access.allowed(store, "mail-2", ODIE)
