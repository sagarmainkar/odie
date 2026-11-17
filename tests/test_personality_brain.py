"""A brain of its own for each personality (docs: personality-brain-and-apps design). Every model call made for a
personality's thread goes to that thread's brain: the chat turn, a turn resumed by a tap, the trim's numbers, the
memory review and a making job's writer. A brain picked for a personality never falls back to another one, and two
chats at once never cross brains."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import ClassVar

import pytest
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from odie import brains, personalities
from odie.models import FALLBACK_SETTING
from odie.store.db import Store

D = "2026-11-17"
WORK_BOX = {"id": "work-box", "name": "Work box", "base_url": "http://127.0.0.1:8001/v1"}


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    s.set_setting("model.chat", {"provider": "lmstudio", "model": "odies-model"})
    s.set_setting("providers.custom", [WORK_BOX])
    return s


# ── whose brain ──

def test_same_as_odie_by_default_and_a_pick_of_its_own(store):
    mira = personalities.create(store, "Mira")
    assert brains.own_pick(store, mira.id) is None
    assert brains.for_personality(store, mira.id).model == "odies-model"  # "Same as Odie"
    brains.choose(store, mira.id, "work-box", "miras-model")
    chosen = brains.for_personality(store, mira.id)
    assert (chosen.provider.id, chosen.model) == ("work-box", "miras-model")
    assert brains.for_personality(store, personalities.ODIE).model == "odies-model"  # Odie's is untouched
    brains.same_as_odie(store, mira.id)
    assert brains.for_personality(store, mira.id).model == "odies-model"


def test_a_threads_brain_is_its_owners(store):
    mira = personalities.create(store, "Mira")
    brains.choose(store, mira.id, "work-box", "miras-model")
    personalities.claim(store, "chat-2026-11-17-2", mira.id)
    assert brains.for_thread(store, "chat-2026-11-17-2").model == "miras-model"
    assert brains.for_thread(store, "chat-2026-11-17").model == "odies-model"
    assert brains.for_thread(store, None).model == "odies-model"  # a background check is Odie's


def test_a_picked_brain_whose_provider_is_gone_never_falls_back(store):
    mira = personalities.create(store, "Mira")
    brains.choose(store, mira.id, "work-box", "miras-model")
    store.set_setting(FALLBACK_SETTING, {"provider": "ollama", "model": "some-cloud-model:cloud"})
    store.set_setting("providers.custom", [])  # the work box was removed in Settings → Providers
    with pytest.raises(brains.BrainGone) as gone:
        brains.for_personality(store, mira.id)
    assert str(gone.value) == ("Mira's brain (miras-model on work-box) isn't set up any more, so Mira can't answer. "
                               "Pick another brain for Mira in Settings → Brain, or set it to \"Same as Odie\".")


def test_odies_own_fallback_is_unchanged(store):
    store.set_setting("model.chat", {"provider": "work-box", "model": "gone-model"})
    store.set_setting("providers.custom", [])
    store.set_setting(FALLBACK_SETTING, {"provider": "ollama", "model": "fallback-model"})
    assert brains.for_personality(store, personalities.ODIE).model == "fallback-model"  # as resolve_selection always did
    mira = personalities.create(store, "Mira")
    assert brains.for_personality(store, mira.id).model == "fallback-model"  # "Same as Odie" is the same, fallback too


def test_a_deleted_personalitys_thread_has_no_brain(store):
    mira = personalities.create(store, "Mira")
    personalities.claim(store, "chat-2026-11-17-2", mira.id)
    store.execute("delete from personalities where id=?", (mira.id,))
    with pytest.raises(brains.BrainGone):
        brains.for_thread(store, "chat-2026-11-17-2")


# ── the chat turn: every model call of a turn goes to its thread's brain ──

class Brain(BaseLlm):
    """A stand-in brain. Each turn: one call of the `now` tool, then "Done.". It notes every call it gets (its own
    name, the name the request was built for, and the turn's first words), and lets the other turn run before it
    answers, so two turns at once really interleave."""
    calls: ClassVar[list[tuple[str, str, str]]] = []

    async def generate_content_async(self, llm_request, stream: bool = False):
        from odie.agent.compaction import turn_start
        contents = llm_request.contents or []
        start = turn_start(contents)
        words = (contents[start].parts[0].text or "").split("\n")[0]
        Brain.calls.append((self.model, llm_request.model, words))
        await asyncio.sleep(0.02)
        answered = any(p.function_response for c in contents[start:] for p in c.parts or [])
        if answered:
            part = types.Part(text="Done.")
        else:
            part = types.Part(function_call=types.FunctionCall(id=f"call-{len(Brain.calls)}", name="now", args={}))
        yield LlmResponse(content=types.Content(role="model", parts=[part]))


@pytest.fixture
async def runner(store, monkeypatch):
    from odie.app import runner as runner_mod
    Brain.calls = []
    monkeypatch.setattr(runner_mod, "model_for", lambda selection, thinking, room=None: Brain(model=selection.model))
    r = runner_mod.OdieRunner(store)
    yield r
    await r.close()


async def _say(runner, words: str, session_id: str) -> list[dict]:
    return [e async for e in runner.chat(words, session_id=session_id)]


def _brains_of(words: str) -> list[str]:
    """The brain each model call of the turn that starts with these words went to."""
    return [brain for brain, _, said in Brain.calls if said.startswith(words)]


async def test_a_personalitys_turn_goes_to_its_own_brain_and_same_as_odie_to_odies(runner, store):
    mira = personalities.create(store, "Mira")
    coach = personalities.create(store, "Coach")
    brains.choose(store, mira.id, "work-box", "miras-model")
    miras = await runner.session_for(mira.id, D)
    coachs = await runner.session_for(coach.id, D)
    await _say(runner, "Mira asks the time", miras)
    await _say(runner, "Coach asks the time", coachs)
    await _say(runner, "Odie asks the time", runner.current_session_id(D))
    assert _brains_of("Mira asks") == ["miras-model", "miras-model"]  # the tool call, then the answer
    assert _brains_of("Coach asks") == ["odies-model", "odies-model"]  # "Same as Odie"
    assert _brains_of("Odie asks") == ["odies-model", "odies-model"]
    assert all(brain == built_for for brain, built_for, _ in Brain.calls)  # the request names the model that got it


async def test_two_turns_at_once_never_cross_brains(runner, store):
    """A reminder firing in one thread while the owner chats in another: each turn's every model call goes to the brain
    of its own thread, for the whole turn, whatever the other is doing."""
    mira = personalities.create(store, "Mira")
    brains.choose(store, mira.id, "work-box", "miras-model")
    miras = await runner.session_for(mira.id, D)
    await asyncio.gather(_say(runner, "Mira asks the time", miras),
                         _say(runner, "Odie asks the time", runner.current_session_id(D)))
    first_two = {said.split()[0] for _, _, said in Brain.calls[:2]}
    assert first_two == {"Mira", "Odie"}  # the turns really ran side by side
    assert _brains_of("Mira asks") == ["miras-model", "miras-model"]
    assert _brains_of("Odie asks") == ["odies-model", "odies-model"]
    assert all(brain == built_for for brain, built_for, _ in Brain.calls)


async def test_a_turn_whose_own_brain_is_gone_is_refused_with_no_model_called(runner, store):
    mira = personalities.create(store, "Mira")
    brains.choose(store, mira.id, "work-box", "miras-model")
    miras = await runner.session_for(mira.id, D)
    store.set_setting("providers.custom", [])
    store.set_setting(FALLBACK_SETTING, {"provider": "ollama", "model": "fallback-model"})
    events = await _say(runner, "Mira asks the time", miras)
    errors = [e["message"] for e in events if e["type"] == "error"]
    assert errors == [brains.GONE.format(name="Mira", model="miras-model", provider="work-box")]
    assert Brain.calls == []  # no model at all: not hers, not the fallback, not Odie's
    await _say(runner, "Odie asks the time", runner.current_session_id(D))
    assert _brains_of("Odie asks") == ["odies-model", "odies-model"]  # everyday Odie goes on as before


async def test_with_the_real_adk_and_litellm_models_each_turn_reaches_its_own_server(store, monkeypatch):
    """The same two turns at once, with nothing stood in for between the runner and the wire: the real ChatAgent, ADK's
    flow and LiteLlm models built by model_for, down to the HTTP request. Each request lands on the address of its own
    thread's brain and names that brain's model."""
    import httpx

    from odie.app.runner import OdieRunner
    from tests.model_fakes import Reply, Script, openai_handler
    servers = {"localhost:1234": Script([Reply(tool="now"), Reply(text="Done.")]),         # LM Studio: Odie's
               "127.0.0.1:8001": Script([Reply(tool="now"), Reply(text="Done.")])}         # the work box: Mira's
    landed: list[tuple[str, str, str]] = []

    async def send(self, request, **kw):
        import json
        where = f"{request.url.host}:{request.url.port}"
        body = json.loads(request.content)
        first_user = next(m for m in body["messages"] if m["role"] == "user")
        words = first_user["content"] if isinstance(first_user["content"], str) else first_user["content"][0]["text"]
        landed.append((where, body["model"], words.split()[0]))
        await asyncio.sleep(0.02)  # let the other turn go
        response = openai_handler(servers[where], httpx)(request)
        response.request = request
        return response
    monkeypatch.setattr(httpx.AsyncClient, "send", send)
    mira = personalities.create(store, "Mira")
    brains.choose(store, mira.id, "work-box", "miras-model")
    r = OdieRunner(store)
    try:
        miras = await r.session_for(mira.id, D)
        await asyncio.gather(_say(r, "Mira asks the time", miras), _say(r, "Odie asks the time", r.current_session_id(D)))
    finally:
        await r.close()
    assert {who for _, _, who in landed[:2]} == {"Mira", "Odie"}  # side by side
    assert sorted(landed) == [("127.0.0.1:8001", "miras-model", "Mira")] * 2 + [("localhost:1234", "odies-model", "Odie")] * 2


def test_the_chat_agent_hands_adk_the_turns_real_model(store):
    """What ADK checks on the model it is handed still sees a LiteLlm: tool calls pair with their results by id
    (google/adk/flows/llm_flows/context/_contents.py, _is_id_pairing_model)."""
    from google.adk.flows.llm_flows.context._contents import _is_id_pairing_model

    from odie.agent import turn
    from odie.agent.agent import build_agent
    from odie.agent.model import model_for
    agent = build_agent(store)
    miras = model_for(brains.for_personality(store, ""), False)
    token = turn.MODEL.set(miras)
    try:
        assert agent.canonical_model is miras
        assert _is_id_pairing_model(agent.canonical_model)
    finally:
        turn.MODEL.reset(token)
    assert agent.canonical_model is agent.model  # outside a turn: the model it was built with


# ── every other model call made for a thread ──

async def test_a_tap_resumes_the_turn_on_its_threads_brain(runner, store):
    mira = personalities.create(store, "Mira")
    brains.choose(store, mira.id, "work-box", "miras-model")
    miras = await runner.session_for(mira.id, D)
    aid = store.create_approval(miras, "inv-1", "req-1", "run_shell", {"command": "ls"}, summary="List", detail={},
                                provenance=[])
    used = []

    async def resumed(**kw):
        used.append(runner.agent.canonical_model.model)
        yield SimpleNamespace(author="odie", partial=False, invocation_id="inv-1",
                              content=types.Content(role="model", parts=[types.Part(text="Listed.")]))
    runner.runner.run_async = resumed
    assert (await runner.resume_approval(aid, True))["text"] == "Listed."
    assert used == ["miras-model"]


async def test_a_tap_whose_brain_is_gone_is_not_resumed_on_another(runner, store):
    mira = personalities.create(store, "Mira")
    brains.choose(store, mira.id, "work-box", "miras-model")
    miras = await runner.session_for(mira.id, D)
    aid = store.create_approval(miras, "inv-1", "req-1", "run_shell", {"command": "ls"}, summary="List", detail={},
                                provenance=[])
    store.set_setting("providers.custom", [])
    ran = []

    async def resumed(**kw):
        ran.append(runner.agent.canonical_model.model)
        yield SimpleNamespace(author="odie", partial=False, invocation_id="inv-1",
                              content=types.Content(role="model", parts=[types.Part(text="Listed.")]))
    runner.runner.run_async = resumed
    got = await runner.resume_approval(aid, True)
    assert got == {"error": brains.GONE.format(name="Mira", model="miras-model", provider="work-box")}
    assert ran == []
    assert store.get_approval(aid)["status"] == "pending"  # the tap isn't used up: it can be tapped again
    store.set_setting("providers.custom", [WORK_BOX])  # the work box is back
    assert (await runner.resume_approval(aid, True))["text"] == "Listed."
    assert ran == ["miras-model"] and store.get_approval(aid)["status"] == "approved"


async def test_the_trim_reads_the_window_of_the_threads_brain(runner, store, monkeypatch):
    from odie.app import runner as runner_mod
    windows = {"odies-model": 1_048_576, "miras-model": 70_000}
    asked = []

    async def window(sel, transport=None):
        asked.append(sel.model)
        return windows[sel.model]
    monkeypatch.setattr(runner_mod, "context_window", window)
    mira = personalities.create(store, "Mira")
    brains.choose(store, mira.id, "work-box", "miras-model")
    miras = await runner.session_for(mira.id, D)
    assert await runner._history_limit(miras) == 52_500  # 3/4 of her 70k
    assert await runner._history_limit(runner.current_session_id(D)) == 300_000  # Odie's 1M, capped
    assert (await runner.context_usage(D, mira.id))["limit"] == 52_500  # her chat's ring
    assert (await runner.context_usage(D))["limit"] == 300_000
    assert set(asked) == {"odies-model", "miras-model"}


async def test_the_memory_review_after_her_chat_uses_her_brain(runner, store, monkeypatch):
    from odie.agent import model as model_mod
    reviewed_with = []

    async def complete(selection, messages, **kw):
        reviewed_with.append(selection.model)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="[]"), finish_reason="stop")])
    monkeypatch.setattr(model_mod, "complete", complete)
    runner.review_every = 1
    mira = personalities.create(store, "Mira")
    brains.choose(store, mira.id, "work-box", "miras-model")
    miras = await runner.session_for(mira.id, D)
    await _say(runner, "Mira asks the time", miras)
    await runner._review_task
    await _say(runner, "Odie asks the time", runner.current_session_id(D))
    await runner._review_task
    assert reviewed_with == ["miras-model", "odies-model"]


async def test_a_making_job_started_in_her_thread_is_written_on_her_brain(runner, store, monkeypatch):
    from odie.app import runner as runner_mod

    class Writes(BaseLlm):
        async def generate_content_async(self, llm_request, stream: bool = False):
            yield LlmResponse(content=types.Content(role="model", parts=[types.Part(text=f"Written by {self.model}.")]))
    monkeypatch.setattr(runner_mod, "model_for", lambda selection, thinking, room=None: Writes(model=selection.model))
    mira = personalities.create(store, "Mira")
    brains.choose(store, mira.id, "work-box", "miras-model")
    miras = await runner.session_for(mira.id, D)
    assert await runner.focused_turn("Write it.", "You write.", [], session_id=miras) == "Written by miras-model."
    assert await runner.focused_turn("Write it.", "You write.", []) == "Written by odies-model."
    store.set_setting("providers.custom", [])
    with pytest.raises(brains.BrainGone):
        await runner.focused_turn("Write it.", "You write.", [], session_id=miras)


async def test_the_making_queue_hands_the_writer_its_jobs_thread(isolated_settings, tmp_path, monkeypatch):
    from odie.making import jobs
    handed = []

    class Runner:
        async def focused_turn(self, prompt, instruction, tools, timeout=600, session_id=None, **kw):
            handed.append(session_id)
            return ""

        async def post_message(self, text, session_id=None, media=None, kind="system"):
            pass

    async def write(job, turn, browser):
        await turn("Write it.", "You write.", [])
        job.title = "Tides"

    async def make(job, browser, transport):
        return {"kind": "note"}
    store = Store(tmp_path / "assistant.db")
    store.init_schema()
    monkeypatch.setitem(jobs.hooks, "runner", Runner())
    monkeypatch.setitem(jobs.hooks, "store", store)
    monkeypatch.setitem(jobs.KINDS, "note", jobs.Kind(word="note", folder="notes", write=write, make=make))
    monkeypatch.setattr(jobs, "send_to_all", lambda *a, **k: 0)
    job = jobs.Job(slug="tides", title="tides", session_id="chat-2026-11-17-2", folder=tmp_path / "tides", kind="note")
    job.folder.mkdir()
    await jobs.run(job, browser=object())
    assert handed == ["chat-2026-11-17-2"]


def test_a_writers_brain_gone_is_told_in_words(store):
    from odie.making import jobs
    gone = brains.BrainGone(brains.GONE.format(name="Mira", model="miras-model", provider="work-box"))
    assert jobs.one_line(gone, ()) == ("Mira's brain (miras-model on work-box) isn't set up any more, so Mira can't "
                                       "answer. Pick another brain for Mira in Settings → Brain, or set it to \"Same "
                                       "as Odie\"")


async def test_deleting_her_removes_her_brain_pick(runner, store):
    mira = personalities.create(store, "Mira")
    brains.choose(store, mira.id, "work-box", "miras-model")
    await personalities.delete(store, runner, mira.id)
    assert store.one("select key from settings where key like 'brain:%'") is None


# ── Settings → Brain, for whoever is picked ──

@pytest.fixture
async def api(runner, monkeypatch):
    """The real app around the runner, with no background jobs, and every provider's model list made up."""
    import httpx

    from odie.app import routes
    from odie.app.main import create_app

    async def listing(providers, transport=None):
        return [{"id": p.id, "name": p.name, "local": p.local, "models": [{"id": "odies-model", "local": True},
                                                                           {"id": "miras-model", "local": True}],
                 "error": None, "base_url": p.base_url, "base_url_env": None} for p in providers]
    monkeypatch.setattr(routes, "list_models", listing)
    monkeypatch.setenv("ODIE_SCHEDULER", "0")
    app = create_app(runner=runner, store=runner.store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c, \
            app.router.lifespan_context(app):
        yield c


async def test_the_brain_screen_answers_for_whoever_is_picked(api, store):
    mira = personalities.create(store, "Mira")
    odies = (await api.get("/api/models")).json()["selection"]["chat"]
    assert (odies["provider"], odies["model"]) == ("lmstudio", "odies-model")
    assert "same_as_odie" not in odies  # everyday Odie's answer is as it always was
    hers = (await api.get(f"/api/models?personality={mira.id}")).json()
    assert hers["selection"]["chat"]["model"] == "odies-model" and hers["selection"]["chat"]["same_as_odie"] is True
    assert hers["odie"] == {"provider": "lmstudio", "model": "odies-model", "leaves_mini": False}

    picked = await api.put(f"/api/models/selection?personality={mira.id}",
                           json={"slot": "chat", "provider": "work-box", "model": "miras-model"})
    assert picked.status_code == 200 and picked.json()["model"] == "miras-model"
    assert brains.own_pick(store, mira.id) == {"provider": "work-box", "model": "miras-model"}
    assert store.get_setting("model.chat") == {"provider": "lmstudio", "model": "odies-model"}  # Odie's untouched
    hers = (await api.get(f"/api/models?personality={mira.id}")).json()["selection"]["chat"]
    assert (hers["provider"], hers["model"], hers["same_as_odie"], hers["reachable"]) == ("work-box", "miras-model", False, True)

    store.set_setting("providers.custom", [])  # the work box was removed
    hers = (await api.get(f"/api/models?personality={mira.id}")).json()["selection"]["chat"]
    assert hers["gone"] is True and hers["reachable"] is False and hers["model"] == "miras-model"

    assert (await api.delete(f"/api/models/selection?personality={mira.id}")).status_code == 200
    assert brains.own_pick(store, mira.id) is None
    assert (await api.get(f"/api/models?personality={mira.id}")).json()["selection"]["chat"]["same_as_odie"] is True
    assert (await api.delete("/api/models/selection")).status_code == 422  # Odie can't be "the same as Odie"
    nobody = await api.put("/api/models/selection?personality=nobody", json={"slot": "chat", "provider": "lmstudio",
                                                                            "model": "x"})
    assert nobody.status_code == 404


def test_the_terminals_key_cant_reach_these_routes():
    from odie import devices
    for method, path in (("GET", "/api/models"), ("PUT", "/api/models/selection"), ("DELETE", "/api/models/selection"),
                         ("GET", "/api/mcp"), ("POST", "/api/mcp/work-mail/access"), ("POST", "/api/mcp")):
        assert not devices.terminal_may(method, path, "personality=abc")
        assert not devices.terminal_may(method, path, "")


async def test_a_tap_on_a_card_whose_brain_is_gone_is_answered_in_words_and_the_card_waits(api, store):
    mira = personalities.create(store, "Mira")
    brains.choose(store, mira.id, "work-box", "miras-model")
    personalities.claim(store, "chat-2026-11-17-2", mira.id)
    aid = store.create_approval("chat-2026-11-17-2", "inv-1", "req-1", "run_shell", {"command": "ls"}, summary="List",
                                detail={}, provenance=[])
    store.set_setting("providers.custom", [])
    tapped = await api.post(f"/api/approvals/{aid}/decide?personality={mira.id}", json={"approve": True})
    assert tapped.status_code == 409
    assert tapped.json()["detail"] == brains.GONE.format(name="Mira", model="miras-model", provider="work-box")
    assert store.get_approval(aid)["status"] == "pending"
