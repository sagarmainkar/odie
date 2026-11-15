"""Bots (odie.workers.bots, team, asks): named Worker templates, the chief that makes and asks them side by side, and
the questions a bot waits on (a tap, a sign-in) that only the app's buttons answer. Through the real ADK with stand-in
models, one script per bot."""
from __future__ import annotations

import asyncio
from typing import ClassVar

import httpx
import pytest
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types

from odie import devices
from odie.store.db import Store
from odie.workers import asks, bots, nudge, router, team, watchdog, worker
from odie.workers import store as jobs
from tests.test_workers import Chat


class Team(BaseLlm):
    """Plays one script per bot, picked by the "You are <name>," its system prompt starts with. Each entry is a tool
    call (name, args) or a text. A bot with no script left says "done" (and is nudged to report)."""
    scripts: ClassVar[dict[str, list]] = {}
    seen: ClassVar[dict[str, list]] = {}
    turns: ClassVar[dict[str, list]] = {}  # per bot: (private sites, reads, USER_TEXT) as each model call saw them

    async def generate_content_async(self, llm_request, stream: bool = False):
        from odie.agent import turn
        prompt = str(llm_request.config.system_instruction)
        name = prompt.removeprefix("You are ").split(",", 1)[0]
        Team.seen.setdefault(name, []).append(llm_request)
        Team.turns.setdefault(name, []).append((turn.private_sites(), turn.read_sources(), turn.USER_TEXT.get()))
        script = Team.scripts.get(name, [])
        step = script.pop(0) if script else "done"
        await asyncio.sleep(0)
        if isinstance(step, str):
            part = types.Part(text=step)
        else:
            tool, args = step
            part = types.Part(function_call=types.FunctionCall(id=f"{name}-{len(Team.seen[name])}", name=tool, args=args))
        yield LlmResponse(content=types.Content(role="model", parts=[part]))


@pytest.fixture
def world(isolated_settings, tmp_path, monkeypatch):
    """A store with the workers' tables and the chief, a chat to post to, no pushes, one script per bot."""
    store = Store(tmp_path / "assistant.db")
    store.init_schema()
    jobs.ensure(store)
    bots.ensure_chief(store)
    chat = Chat()
    monkeypatch.setattr(worker, "send_to_all", lambda *a, **k: None)
    monkeypatch.setattr(asks, "_push", lambda *a, **k: None)
    monkeypatch.setattr(worker, "model_for_bot", lambda store, bot: Team(model="team"))
    Team.scripts = {}
    Team.seen = {}
    Team.turns = {}
    router.hooks.update(store=store, runner=chat)
    return store, chat


def tool_names(request) -> list[str]:
    return sorted(f.name for t in request.config.tools for f in t.function_declarations)


# ── the bots store ───────────────────────────────────────────────────────────

def test_names_powers_and_models_are_cleaned():
    assert bots.clean_name("Researcher") == "researcher"
    assert bots.clean_name(" @fact-checker ") == "fact-checker"
    assert bots.clean_name("x") is None and bots.clean_name("my bot") is None and bots.clean_name("") is None
    assert bots.clean_powers(["Browser", "web", "mail"]) == ["web", "browser"]
    assert bots.clean_model({"provider": "ollama", "model": "lfm3:latest", "x": 1}) == {"provider": "ollama", "model": "lfm3:latest"}
    assert bots.clean_model({"provider": "ollama"}) is None and bots.clean_model(None) is None


def test_the_chief_is_made_once_and_stays(world):
    store, _ = world
    bots.ensure_chief(store)
    assert [b.name for b in bots.all_bots(store)] == ["chief"]
    chief = bots.get(store, "chief")
    assert chief.is_chief and chief.powers == ["web"] and chief.model is None and chief.made_by == "odie"
    assert not bots.delete(store, "chief")
    bots.edit(store, "chief", prompt="Be brief.")
    bots.ensure_chief(store)  # a chief the user changed is left as it is
    assert bots.get(store, "chief").prompt == "Be brief."


def test_make_refuses_a_bad_name_a_twin_a_missing_role_and_a_full_team(world, monkeypatch):
    store, _ = world
    made = bots.make(store, "Researcher", "finds sources", "Cite every claim.", ["web", "mail"])
    assert made.name == "researcher" and made.powers == ["web"] and made.made_by == "chief" and not made.edited_by_user
    assert "already a bot" in bots.make(store, "researcher", "again", "", ["web"])
    assert "one word" in bots.make(store, "my bot", "x", "", [])
    assert "role" in bots.make(store, "writer", "  ", "", [])
    monkeypatch.setattr(bots, "MAX_BOTS", 2)
    assert "full" in bots.make(store, "writer", "writes", "", [])
    assert [b.name for b in bots.all_bots(store)] == ["chief", "researcher"]  # the chief first


def test_the_users_edit_replaces_what_is_given_and_makes_the_bot_theirs(world):
    store, _ = world
    bots.make(store, "researcher", "finds sources", "Cite.", ["web"], model={"provider": "ollama", "model": "lfm3:latest"})
    got = bots.edit(store, "researcher", powers=["web", "browser"])
    assert got.powers == ["web", "browser"] and got.model == {"provider": "ollama", "model": "lfm3:latest"}  # model not sent: kept
    assert got.edited_by_user and got.prompt == "Cite."
    got = bots.edit(store, "researcher", model=None, model_given=True)
    assert got.model is None  # sent as none: the chat's model
    assert bots.edit(store, "nobody", prompt="x") is None
    assert bots.delete(store, "researcher") and bots.get(store, "researcher") is None


# ── a bot's kind and tools ───────────────────────────────────────────────────

def a_bot_job(store, name, brief="Find it.", session_id="chat-1", parent_id=""):
    budget = team.TEAMMATE_BUDGET if parent_id else team.BOT_BUDGET
    return jobs.create(store, "bot", f"{name} job", brief, session_id, bots.folder_of(name), budget, bot=name,
                       parent_id=parent_id)


def test_powers_decide_the_tools_and_only_the_chief_leads(world):
    store, _ = world
    bots.make(store, "reader", "reads", "", [])
    bots.make(store, "coder", "codes", "", ["shell", "files"])
    bots.make(store, "shopper", "shops", "", ["browser"])

    def names(name):
        bot = bots.get(store, name)
        return sorted(t.name for t in team.tools_for(bot, store, a_bot_job(store, name)))
    assert names("reader") == ["read_file", "write_file"]  # its notes, whatever its powers
    assert names("coder") == ["read_file", "run_shell", "write_file"]
    assert {"browser_open", "browser_click", "browser_type", "browser_sign_in"} <= set(names("shopper"))
    assert "run_shell" not in names("shopper") and "ask_bots" not in names("shopper")
    assert names("chief") == ["ask_bots", "list_bots", "make_bot", "read_file", "web_fetch", "web_search", "write_file"]


def test_a_bots_guarded_tools_ask_through_the_job_not_adk(world):
    store, _ = world
    bots.make(store, "shopper", "shops", "", ["browser"])
    tools = {t.name: t for t in team.tools_for(bots.get(store, "shopper"), store, a_bot_job(store, "shopper"))}
    click = tools["browser_click"]
    assert click._require_confirmation is False and callable(click._odie_asks)
    assert not hasattr(tools["browser_scroll"], "_odie_asks")  # never asked in chat either


def test_the_instruction_carries_name_role_rules_and_its_own_prompt(world):
    store, _ = world
    bots.make(store, "shopper", "compares prices", "Prefer Indian shops.", ["browser"])
    text = team.instruction_for(bots.get(store, "shopper"))
    assert text.startswith("You are shopper, one of the user's bots: compares prices")
    assert "waits for the user's tap" in text and text.endswith("Prefer Indian shops.")
    assert "{folder}" in text and "ask_bots" not in text
    assert "ask_bots runs several at once" in team.instruction_for(bots.get(store, "chief"))


def test_check_asks_reads_the_team(world):
    store, _ = world
    bots.make(store, "researcher", "finds", "", ["web"])
    pairs, wrong = team.check_asks(store, [{"bot": "researcher", "brief": "find tides"}])
    assert wrong is None and [(b.name, brief) for b, brief in pairs] == [("researcher", "find tides")]
    assert team.check_asks(store, [])[1] == "Ask at least one bot."
    assert team.check_asks(store, [{"bot": "researcher", "brief": "x"}] * 5)[1] == "At most 4 at once."
    assert team.check_asks(store, [{"bot": "chief", "brief": "x"}])[1] == "You can't ask yourself."
    assert "no bot called nobody" in team.check_asks(store, [{"bot": "nobody", "brief": "x"}])[1]
    assert team.check_asks(store, [{"bot": "researcher", "brief": " "}])[1] == "Give researcher a brief."


# ── the chief at work ────────────────────────────────────────────────────────

async def test_the_chief_makes_a_specialist_asks_two_side_by_side_and_reports_once(world):
    store, chat = world
    bots.make(store, "checker", "checks numbers", "", [])
    Team.scripts = {
        "chief": [("list_bots", {}),
                  ("make_bot", {"name": "researcher", "role": "finds sources", "prompt": "Cite.", "powers": ["web"]}),
                  ("ask_bots", {"asks": [{"bot": "researcher", "brief": "Find tide times in Goa."},
                                         {"bot": "checker", "brief": "Check: high tide 06:10."}]}),
                  ("report", {"outcome": "ready", "text": "High tide 06:10, checked."})],
        "researcher": [("report", {"outcome": "ready", "text": "06:10 per the port site."})],
        "checker": [("report", {"outcome": "ready", "text": "Agrees."})],
    }
    job = router.start_bot("chief", "Goa tides", "When is high tide in Goa?", "chat-1")
    await asyncio.wait_for(router._tasks[job.id], 5)
    row = jobs.get(store, job.id)
    assert (row["status"], row["bot"], row["report"]) == ("done", "chief", "High tide 06:10, checked.")
    kids = [dict(r) for r in store.query("select * from jobs where parent_id=? order by bot", (job.id,))]
    assert [(k["bot"], k["status"], k["report"]) for k in kids] == [("checker", "done", "Agrees."),
                                                                    ("researcher", "done", "06:10 per the port site.")]
    assert all(k["budget_seconds"] == team.TEAMMATE_BUDGET for k in kids)
    assert bots.get(store, "researcher").made_by == "chief"
    # the chat hears once, from the chief, not from its teammates
    assert [p["text"] for p in chat.posts] == [f"✅ Chief done: Goa tides ({job.id})\n\nHigh tide 06:10, checked."]
    # ask_bots handed the chief both reports, in the order asked
    last = Team.seen["chief"][-1]
    answers = [p.function_response.response for c in last.contents for p in c.parts or [] if p.function_response]
    reports = answers[-1]["reports"]
    assert [(r["bot"], r["report"]) for r in reports] == [("researcher", "06:10 per the port site."), ("checker", "Agrees.")]
    # the teammates saw their own brief only, with their own tools
    assert "Find tide times in Goa." in str(Team.seen["researcher"][0].contents[-1])
    assert tool_names(Team.seen["researcher"][0]) == ["read_file", "report", "web_fetch", "web_search", "write_file"]
    assert tool_names(Team.seen["checker"][0]) == ["read_file", "report", "write_file"]


async def test_teammates_run_side_by_side(world, monkeypatch):
    store, _ = world
    bots.make(store, "a-bot", "a", "", [])
    bots.make(store, "b-bot", "b", "", [])
    started: list[str] = []
    both = asyncio.Event()
    real_run = worker.run

    async def run(job, store, runner, kind=None, model=None):
        if job.parent_id:
            started.append(job.bot)
            if len(started) == 2:
                both.set()
            await asyncio.wait_for(both.wait(), 2)  # neither finishes until both have started
        return await real_run(job, store, runner, kind, model)
    monkeypatch.setattr(worker, "run", run)
    Team.scripts = {"chief": [("ask_bots", {"asks": [{"bot": "a-bot", "brief": "x"}, {"bot": "b-bot", "brief": "y"}]}),
                              ("report", {"outcome": "ready", "text": "ok"})],
                    "a-bot": [("report", {"outcome": "ready", "text": "a"})],
                    "b-bot": [("report", {"outcome": "ready", "text": "b"})]}
    job = router.start_bot("chief", "Both", "do both", "chat-1")
    await asyncio.wait_for(router._tasks[job.id], 5)
    assert sorted(started) == ["a-bot", "b-bot"] and jobs.get(store, job.id)["status"] == "done"


async def test_a_bot_runs_from_the_chat_with_ask_bot_and_an_unknown_one_is_named(world):
    from odie.workers.tools import make_worker_tools
    store, chat = world
    bots.make(store, "writer", "writes", "", [])
    tools = {t.name: t for t in make_worker_tools(store)}
    Team.scripts = {"writer": [("report", {"outcome": "ready", "text": "Drafted."})]}
    got = await tools["ask_bot"].func(bot="@Writer", title="Draft", request="Draft a note.", tool_context=Ctx())
    assert got["bot"] == "writer"
    await asyncio.wait_for(router._tasks[got["job_id"]], 5)
    assert chat.posts[-1]["text"] == f"✅ Writer done: Draft ({got['job_id']})\n\nDrafted."
    assert "The bots: chief, writer" in (await tools["ask_bot"].func(bot="nobody", title="x", request="y"))["error"]


async def test_a_deleted_bots_job_fails_with_why(world):
    store, _ = world
    bots.make(store, "temp", "t", "", [])
    job = a_bot_job(store, "temp")
    bots.delete(store, "temp")
    assert await worker.run(job, store, router.hooks["runner"]) == "failed"
    assert "no bot called temp" in jobs.get(store, job.id)["error"]


def test_a_bot_runs_on_its_own_model_while_its_provider_is_there(world):
    from odie.models import all_providers, resolve_selection
    store, _ = world
    provider = all_providers(store)[0]
    bots.make(store, "local", "l", "", [], model={"provider": provider.id, "model": "tiny:latest"})
    picked = worker.selection_for_bot(store, bots.get(store, "local"))
    assert (picked.provider.id, picked.model) == (provider.id, "tiny:latest")
    bots.make(store, "gone", "g", "", [], model={"provider": "no-such-provider", "model": "x"})
    fallback = worker.selection_for_bot(store, bots.get(store, "gone"))
    chat_pick = resolve_selection(store, "chat")
    assert (fallback.provider.id, fallback.model) == (chat_pick.provider.id, chat_pick.model)


# ── a bot waits on the user ──────────────────────────────────────────────────

class Asking:
    """A guarded tool as asking() leaves it: a name and the chat's predicate."""

    def __init__(self, name, needs):
        self.name = name
        self._odie_asks = lambda **_: needs


def test_needs_users_tap_reads_only_the_kept_predicate():
    assert worker.needs_users_tap(Asking("browser_click", True), {"text": "Place order"}, None)
    assert not worker.needs_users_tap(Asking("browser_click", False), {"text": "Next"}, None)

    class Plain:
        name = "write_file"
    assert not worker.needs_users_tap(Plain(), {}, None)

    def broken(**_):
        raise ValueError
    odd = Asking("browser_type", False)
    odd._odie_asks = broken
    assert worker.needs_users_tap(odd, {}, None)  # can't tell: asks


async def test_a_tap_waits_for_the_user_and_yes_lets_the_call_run(world, monkeypatch):
    store, chat = world
    bots.make(store, "shopper", "shops", "", ["browser"])
    job = a_bot_job(store, "shopper")
    monkeypatch.setattr("odie.signin.guard.card", lambda tool, args, tab, store: ('Click "Place order" on amazon.in', {"why": "may order"}))
    guard = worker.guard_for(store, job, chat)
    waiting = guard(Asking("browser_click", True), {"text": "Place order"}, None)
    assert asyncio.iscoroutine(waiting)
    task = asyncio.create_task(waiting)
    await asyncio.sleep(0.01)
    [ask] = asks.open_for(store)
    assert (ask["job_id"], ask["kind"], ask["text"]) == (job.id, "tap", 'Click "Place order" on amazon.in')
    assert chat.posts[-1]["text"].startswith(f"✋ shopper waits for your tap ({job.id})")
    assert asks.waits_on_user(store, job.id)
    assert asks.answer(store, ask["id"], "yes")
    assert await task is None  # runs
    assert not asks.answer(store, ask["id"], "no")  # answered already
    assert asks.open_for(store) == []


async def test_no_refuses_the_call_and_silence_counts_as_no(world, monkeypatch):
    store, chat = world
    job = a_bot_job(store, "chief")
    monkeypatch.setattr("odie.signin.guard.card", lambda tool, args, tab, store: ("Type into Search on amazon.in", {}))
    guard = worker.guard_for(store, job, chat)
    args = {"text": "x"}
    task = asyncio.create_task(guard(Asking("browser_type", True), args, None))
    await asyncio.sleep(0.01)
    asks.answer(store, asks.open_for(store)[0]["id"], "no")
    refused = await task
    assert "the user said no" in refused["error"]
    assert jobs.actions(store, job.id)[-1]["refused"].startswith("the user said no")
    said = await asks.ask(store, chat, job, "tap", "Click Buy", wait_seconds=0.01)
    assert said == "no"
    assert store.one("select status from job_asks order by created_at desc limit 1")["status"] == "expired"


async def test_an_answer_must_be_yes_or_no_and_a_restart_expires_what_was_open(world):
    store, chat = world
    job = a_bot_job(store, "chief")
    task = asyncio.create_task(asks.ask(store, chat, job, "sign_in", "amazon.in: sign in", {"card": {"id": "m1"}}))
    await asyncio.sleep(0.01)
    [ask] = asks.open_for(store)
    assert chat.posts[-1]["text"].startswith("🔑 chief needs you to sign in") and "Sign in from Today" in chat.posts[-1]["text"]
    assert ask["detail"] == {"card": {"id": "m1"}}
    assert not asks.answer(store, ask["id"], "approve")
    assert not asks.answer(store, "ask-nothere", "yes")
    assert asks.expire_all(store) == 1
    assert asks.open_for(store) == []
    task.cancel()


async def test_recover_expires_questions_and_closes_teammates(world):
    store, chat = world
    chief_job = a_bot_job(store, "chief")
    kid = a_bot_job(store, "chief", parent_id=chief_job.id)
    store.execute("insert into job_asks(id,job_id,kind,text,status,created_at) values('ask-1',?,'tap','x','open','t')", (kid.id,))
    lines = await router.recover()
    assert "1 question(s) to the user expired" in lines
    assert jobs.get(store, kid.id)["status"] == "failed"
    assert [p["text"] for p in chat.posts] == [f"❌ chief job didn't finish ({chief_job.id}): Odie restarted. "
                                               f"Say \"retry {chief_job.id}\" to start it again."]
    assert router.retry(kid.id) is None  # a teammate's part is retried through its chief


def test_the_watchdog_leaves_waiting_jobs_and_teammates_alone(world):
    store, _ = world
    chief_job = a_bot_job(store, "chief")
    plain = a_bot_job(store, "chief")
    kid = a_bot_job(store, "chief", parent_id=chief_job.id)
    store.execute("update jobs set status='running'")
    assert not watchdog.watched(store, jobs.get(store, chief_job.id))  # its teammate is at work
    assert not watchdog.watched(store, jobs.get(store, kid.id))
    assert watchdog.watched(store, jobs.get(store, plain.id))
    store.execute("insert into job_asks(id,job_id,kind,text,status,created_at) values('ask-2',?,'tap','x','open','t')", (plain.id,))
    assert not watchdog.watched(store, jobs.get(store, plain.id))


async def test_a_teammates_signed_in_read_makes_the_chief_and_its_chat_private(world, monkeypatch):
    from odie.signin import guard
    store, _ = world
    bots.make(store, "shopper", "shops", "", ["browser"])
    real_run = worker.run

    async def run(job, store, runner, kind=None, model=None):
        if job.bot == "shopper":
            guard.remember(store, job.id, "amazon.in")  # what a signed-in page read leaves behind
        return await real_run(job, store, runner, kind, model)
    monkeypatch.setattr(worker, "run", run)
    Team.scripts = {"chief": [("ask_bots", {"asks": [{"bot": "shopper", "brief": "my orders"}]}),
                              ("report", {"outcome": "ready", "text": "Two orders."})],
                    "shopper": [("report", {"outcome": "ready", "text": "Two orders on amazon.in."})]}
    job = router.start_bot("chief", "Orders", "what did I order?", "chat-1")
    await asyncio.wait_for(router._tasks[job.id], 5)
    assert guard.private_of(store, job.id) == {"amazon.in"}  # the chief's later web steps would ask
    assert guard.private_of(store, "chat-1") == {"amazon.in"}  # and so would the chat's


# ── the chat ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("text", "expected"), [
    ("@chief compare the three e-bikes", "chief"),
    ("@Writer draft it", "writer"),
    ("@nobody hello", None),
    ("mail @chief later", None),
    ("hi", None),
])
def test_addressed_bot(text, expected):
    assert nudge.addressed_bot(text, {"chief", "writer"}) == expected


def test_the_bot_nudge_rides_on_a_message_to_a_bot(world, monkeypatch):
    from odie.app.runner import OdieRunner
    store, _ = world
    monkeypatch.setenv("ODIE_WORKERS", "1")
    r = OdieRunner.__new__(OdieRunner)
    r.store = store
    assert r._job_nudge("chat-1", "@chief which phone should I buy?") == "\n" + nudge.BOT_NUDGE.format(name="chief")
    assert r._job_nudge("chat-1", "@ghost hi") == ""


# ── the app's routes, and what the terminal's key can't reach ────────────────

async def test_the_bots_and_asks_routes(isolated_settings, tmp_path, monkeypatch):
    from odie.app.main import create_app
    from tests.test_models import FakeRunner
    monkeypatch.setenv("ODIE_WORKERS", "1")
    store = Store(tmp_path / "assistant.db")
    store.init_schema()
    jobs.ensure(store)
    bots.ensure_chief(store)
    app = create_app(runner=FakeRunner(), store=store)
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        got = (await c.get("/api/bots")).json()
        assert [b["name"] for b in got["bots"]] == ["chief"] and got["powers"] == list(bots.POWERS)
        made = await c.post("/api/bots", json={"name": "Writer", "role": "writes", "prompt": "Short.", "powers": ["files"]})
        assert made.status_code == 200 and made.json()["bot"]["edited_by_user"]
        assert (await c.post("/api/bots", json={"name": "writer", "role": "again"})).status_code == 422
        edited = await c.put("/api/bots/writer", json={"model": {"provider": "ollama", "model": "lfm3:latest"}, "model_given": True})
        assert edited.json()["bot"]["model"] == {"provider": "ollama", "model": "lfm3:latest"}
        assert (await c.put("/api/bots/ghost", json={"prompt": "x"})).status_code == 404
        assert (await c.delete("/api/bots/chief")).status_code == 409
        assert (await c.delete("/api/bots/writer")).status_code == 200
        job = a_bot_job(store, "chief")
        store.execute("insert into job_asks(id,job_id,kind,text,detail_json,status,created_at) "
                      "values('ask-9',?,'tap','Click Buy','{\"why\": \"may order\"}','open','t')", (job.id,))
        listed = (await c.get("/api/jobs")).json()["asks"]
        assert listed == [{"id": "ask-9", "job_id": job.id, "kind": "tap", "text": "Click Buy", "why": "may order",
                           "site": None, "card": None, "created_at": "t", "bot": "chief", "conv": None}]
        assert (await c.post("/api/jobs/asks/ask-9", json={"answer": "maybe"})).status_code == 422
        assert (await c.post("/api/jobs/asks/ask-9", json={"answer": "yes"})).status_code == 200
        assert (await c.post("/api/jobs/asks/ask-9", json={"answer": "yes"})).status_code == 409
        monkeypatch.delenv("ODIE_WORKERS")
        assert (await c.get("/api/bots")).status_code == 404


def test_the_terminals_key_cant_answer_a_bot_or_change_one():
    assert not devices.terminal_may("POST", "/api/jobs/asks/ask-1")
    assert not devices.terminal_may("GET", "/api/bots")
    assert not devices.terminal_may("PUT", "/api/bots/chief")
    assert not devices.terminal_may("POST", "/api/jobs/job-1/retry")


async def test_through_adk_a_bot_pauses_at_a_tap_and_goes_on_after_yes(world, monkeypatch):
    """The real ADK awaits the guard's wait: the tool runs only after the user's yes, and the bot then reports."""
    from google.adk.tools import FunctionTool
    store, chat = world
    bots.make(store, "buyer", "buys", "", [])
    ran: list[str] = []

    async def place_order(item: str) -> dict:
        """Place the order."""
        ran.append(item)
        return {"placed": item}
    tool = FunctionTool(place_order)
    tool._odie_asks = lambda **_: True
    monkeypatch.setattr(team, "tools_for", lambda bot, store, job: [tool])
    monkeypatch.setattr("odie.signin.guard.card", lambda tool, args, tab, store: (f"Order {args['item']}", {}))
    Team.scripts = {"buyer": [("place_order", {"item": "kettle"}), ("report", {"outcome": "ready", "text": "Ordered."})]}
    job = router.start_bot("buyer", "Kettle", "order the kettle", "chat-1")
    for _ in range(100):
        if asks.open_for(store):
            break
        await asyncio.sleep(0.01)
    [ask] = asks.open_for(store)
    assert ask["text"] == "Order kettle" and ran == []  # waiting: nothing ran yet
    asks.answer(store, ask["id"], "yes")
    await asyncio.wait_for(router._tasks[job.id], 5)
    assert ran == ["kettle"] and jobs.get(store, job.id)["report"] == "Ordered."


# ── a bot on a schedule, and the team on Today ───────────────────────────────

async def test_a_bot_on_a_schedule_runs_again_told_its_last_report(world, monkeypatch):
    from odie.workers.tools import make_worker_tools
    store, chat = world
    bots.make(store, "watcher", "watches prices", "", [])
    naps: list[float] = []

    async def no_sleep(seconds):
        naps.append(seconds)
        if len(naps) >= 2:
            router.stop(job_id)
            await asyncio.sleep(3600)
    monkeypatch.setattr(router, "sleep", no_sleep)
    Team.scripts = {"watcher": [("report", {"outcome": "ready", "text": "₹2.44L", "state": "2.44L"}),
                                ("report", {"outcome": "ready", "text": "₹2.40L, down", "state": "2.40L"})]}
    tools = {t.name: t for t in make_worker_tools(store)}
    got = await tools["ask_bot"].func(bot="watcher", title="CB350 price", request="Check the CB350 price.",
                                      every_minutes=60, notify="change", tool_context=Ctx())
    job_id = got["job_id"]
    assert "every 60 minutes" in got["repeats"]
    await asyncio.wait_for(asyncio.gather(router._tasks[job_id], return_exceptions=True), 5)
    row = jobs.get(store, job_id)
    assert (row["every_minutes"], row["notify"], row["runs"], row["budget_seconds"]) == (60, "change", 2, team.TEAMMATE_BUDGET)
    assert [p["text"].split("\n")[0] for p in chat.posts] == [f"🔁 Report 1: CB350 price ({job_id})",
                                                              f"🔁 Report 2: CB350 price ({job_id})"]
    second = Team.seen["watcher"][-1]
    first_message = second.contents[0].parts[0].text
    assert "This is run 2. Your last report:\n₹2.44L" in first_message
    assert "runs again on a schedule" in str(second.config.system_instruction)


def test_budget_for():
    assert team.budget_for(teammate=True, repeats=False) == team.TEAMMATE_BUDGET
    assert team.budget_for(teammate=False, repeats=True) == team.TEAMMATE_BUDGET
    assert team.budget_for(teammate=False, repeats=False) == team.BOT_BUDGET


async def test_a_chiefs_card_on_today_shows_its_team(isolated_settings, tmp_path, monkeypatch):
    from odie.app.main import create_app
    from tests.test_models import FakeRunner
    monkeypatch.setenv("ODIE_WORKERS", "1")
    store = Store(tmp_path / "assistant.db")
    store.init_schema()
    jobs.ensure(store)
    bots.ensure_chief(store)
    app = create_app(runner=FakeRunner(), store=store)
    chief_job = a_bot_job(store, "chief")
    done_kid = a_bot_job(store, "chief", parent_id=chief_job.id)
    busy_kid = a_bot_job(store, "chief", parent_id=chief_job.id)
    store.execute("update jobs set status='running' where id in (?,?)", (chief_job.id, busy_kid.id))
    jobs.ended(store, done_kid.id, "done", outcome="ready", report="found it")
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        listed = (await c.get("/api/jobs")).json()
        assert listed["running"] == [] and listed["recent"] == []  # a bot's jobs live with the bot, not in Jobs
        one = (await c.get(f"/api/jobs/{chief_job.id}")).json()
        assert [(t["id"], t["status"], t["report"]) for t in one["teammates"]] == [(done_kid.id, "done", "found it"),
                                                                                    (busy_kid.id, "running", "")]



# ── privacy goes with the brief (the review of 15 Nov) ───────────────────────

class Ctx:
    """A tool_context in chat "chat-1"."""
    class session:
        id = "chat-1"


async def test_a_bot_asked_from_a_private_chat_starts_private(world):
    from odie.signin import guard
    from odie.workers.tools import make_worker_tools
    store, _ = world
    bots.make(store, "researcher", "finds", "", ["web"])
    guard.remember(store, "chat-1", "amazon.in")
    guard.remember_read(store, "chat-1", "your mail")
    Team.scripts = {"researcher": [("report", {"outcome": "ready", "text": "ok"})]}
    tools = {t.name: t for t in make_worker_tools(store)}
    got = await tools["ask_bot"].func(bot="researcher", title="x", request="look up my order", tool_context=Ctx())
    await answer_when_asked(store, "no")
    await asyncio.wait_for(router._tasks[got["job_id"]], 5)
    sites, reads, _ = Team.turns["researcher"][0]
    assert sites == {"amazon.in"} and reads == {"your mail"}  # Deny: its web steps ask, as the chat's do
    assert guard.private_of(store, "bot:researcher") == {"amazon.in"}  # and its notes stay private for later jobs


async def answer_when_asked(store, said: str) -> dict:
    """Wait for a bot's question to open, answer it, and return it."""
    for _ in range(200):
        open_now = asks.open_for(store)
        if open_now:
            asks.answer(store, open_now[0]["id"], said)
            return open_now[0]
        await asyncio.sleep(0.01)
    raise AssertionError("no question was asked")


async def test_one_allow_at_the_start_lets_the_whole_team_work(world):
    from odie.signin import guard
    store, _ = world
    bots.make(store, "researcher", "finds", "", ["web"])
    guard.remember_read(store, "chat-1", "your memory")
    Team.scripts = {"chief": [("ask_bots", {"asks": [{"bot": "researcher", "brief": "find it"}]}),
                              ("report", {"outcome": "ready", "text": "ok"})],
                    "researcher": [("report", {"outcome": "ready", "text": "found"})]}
    job = router.start_bot("chief", "Goa", "North or South Goa?", "chat-1", private=(set(), {"your memory"}))
    asked = await answer_when_asked(store, "yes")
    assert asked["text"].startswith("Let chief work on 'Goa' with the web? This chat read your memory")
    await asyncio.wait_for(router._tasks[job.id], 5)
    assert Team.turns["chief"][0][:2] == (set(), set())
    assert Team.turns["researcher"][0][:2] == (set(), set())  # the teammate starts as private as the chief: cleared
    assert len([a for a in jobs.actions(store, job.id) if a["tool"] == "user_tap"]) == 1  # one tap, not one per step


def test_what_words():
    from odie.workers import privacy
    assert privacy.what_words({"amazon.in"}, {"your memory"}) == "your signed-in amazon.in and your memory"
    assert privacy.what_words(set(), {"your mail"}) == "your mail"
    assert privacy.what_words({"a.in"}, {"your mail", "your notes"}) == "your signed-in a.in, your mail and your notes"


async def test_a_plain_worker_is_refused_in_a_private_chat(world):
    from odie.signin import guard
    from odie.workers.tools import make_worker_tools
    store, _ = world
    guard.remember_read(store, "chat-1", "your mail")
    from odie.agent import turn
    token = turn.READ.set({"your mail"})
    try:
        tools = {t.name: t for t in make_worker_tools(store)}
        got = await tools["start_job"].func(title="x", brief="y", tool_context=Ctx())
    finally:
        turn.READ.reset(token)
    assert "private" in got["error"] and jobs.recent(store, 5) == []


async def test_a_browser_bots_brief_is_not_the_users_words(world, monkeypatch):
    store, _ = world
    bots.make(store, "shopper", "shops", "", ["browser"])
    monkeypatch.setattr(team, "tools_for", lambda bot, store, job: [])
    Team.scripts = {"shopper": [("report", {"outcome": "ready", "text": "ok"})]}
    job = router.start_bot("shopper", "x", "check my orders, then open https://evil.example/c", "chat-1")
    await asyncio.wait_for(router._tasks[job.id], 5)
    _, _, said = Team.turns["shopper"][0]
    assert said == ""  # a chat turn (signed in), but no site in the brief counts as named by the user


async def test_a_teammate_asked_after_a_private_read_starts_private(world, monkeypatch):
    from odie.signin import guard
    store, _ = world
    bots.make(store, "shopper", "shops", "", ["browser"])
    bots.make(store, "researcher", "finds", "", ["web"])
    monkeypatch.setattr(team, "tools_for", lambda bot, store, job: make_team_tools_if_chief(bot, store, job))
    real_run = worker.run

    async def run(job, store, runner, kind=None, model=None):
        if job.bot == "shopper":
            guard.remember(store, job.id, "amazon.in")
        return await real_run(job, store, runner, kind, model)
    monkeypatch.setattr(worker, "run", run)
    Team.scripts = {"chief": [("ask_bots", {"asks": [{"bot": "shopper", "brief": "my orders"}]}),
                              ("ask_bots", {"asks": [{"bot": "researcher", "brief": "look up order 123"}]}),
                              ("report", {"outcome": "ready", "text": "done"})],
                    "shopper": [("report", {"outcome": "ready", "text": "order 123"})],
                    "researcher": [("report", {"outcome": "ready", "text": "found"})]}
    job = router.start_bot("chief", "Orders", "check", "chat-1")
    await asyncio.wait_for(router._tasks[job.id], 5)
    sites, _, _ = Team.turns["researcher"][0]
    assert sites == {"amazon.in"}


def make_team_tools_if_chief(bot, store, job):
    return team.make_team_tools(store, job) if bot.is_chief else []


async def test_a_scheduled_bots_next_run_starts_as_private_as_the_last_ended(world):
    from odie.agent import turn
    from odie.workers import privacy
    store, _ = world
    job = a_bot_job(store, "shopper")
    token = turn.PRIVATE.set({"amazon.in"})
    try:
        privacy.at_end(store, job.id, "shopper")
    finally:
        turn.PRIVATE.reset(token)
    assert privacy.at_start(store, job.id, "shopper") == ({"amazon.in"}, set())
    other = a_bot_job(store, "shopper")
    assert privacy.at_start(store, other.id, "shopper") == ({"amazon.in"}, set())  # its notes may hold it
    assert privacy.at_start(store, a_bot_job(store, "writer").id, "writer") == (set(), set())


async def test_jobs_status_makes_the_chat_as_private_as_the_reports_it_shows(world):
    from odie.signin import guard
    from odie.workers.tools import make_worker_tools
    store, _ = world
    job = a_bot_job(store, "shopper")
    jobs.ended(store, job.id, "done", outcome="ready", report="order 123")
    guard.remember(store, job.id, "amazon.in")
    tools = {t.name: t for t in make_worker_tools(store)}
    await tools["jobs_status"].func(tool_context=Ctx())
    assert guard.private_of(store, "chat-1") == {"amazon.in"}


async def test_a_chiefs_leftover_teammates_are_closed(world):
    store, _ = world
    chief_job = a_bot_job(store, "chief")
    waiting = a_bot_job(store, "chief", parent_id=chief_job.id)
    team.close_teammates(store, chief_job.id)
    row = jobs.get(store, waiting.id)
    assert (row["status"], row["error"]) == ("stopped", "the chief's job ended")


def test_the_welcome_leaves_out_teammates_and_private_reports(world):
    from datetime import UTC, datetime, timedelta

    from odie.signin import guard
    from odie.workers import welcome
    store, _ = world
    chief_job = a_bot_job(store, "chief")
    kid = a_bot_job(store, "chief", parent_id=chief_job.id)
    shop = a_bot_job(store, "shopper")
    for j in (chief_job, kid):
        jobs.ended(store, j.id, "failed", error="Odie restarted")
    jobs.ended(store, shop.id, "done", outcome="blocked", report="Order 123 to 4 Elm St is stuck")
    guard.remember(store, shop.id, "amazon.in")
    found = welcome.gather(store, datetime.now(UTC) - timedelta(hours=1), datetime.now(UTC))
    stuck = {j["id"]: j for j in found["stuck"]}
    assert set(stuck) == {chief_job.id, shop.id}
    assert stuck[shop.id]["report"] is None


async def test_a_question_whose_post_fails_doesnt_stay_open(world):
    store, _ = world
    job = a_bot_job(store, "chief")

    class Broken:
        async def post_message(self, *a, **k):
            raise RuntimeError("bus down")
    with pytest.raises(RuntimeError):
        await asks.ask(store, Broken(), job, "tap", "Click Buy")
    assert asks.open_for(store) == []



def test_the_starter_team_is_made_once(world):
    store, _ = world
    bots.ensure_starters(store)
    assert [b.name for b in bots.all_bots(store)] == ["chief", "checker", "contrarian", "researcher"]
    assert all(b.made_by == "odie" and b.powers == ["web", "files"] for b in bots.all_bots(store) if not b.is_chief)
    bots.delete(store, "checker")
    bots.ensure_starters(store)  # the next start: a deleted starter stays deleted
    assert bots.get(store, "checker") is None


# ── the live team card ───────────────────────────────────────────────────────

@pytest.mark.parametrize(("tool", "args", "refused", "expected"), [
    ("web_search", {"query": "CB350 price Bangalore"}, None, 'searching "CB350 price Bangalore"'),
    ("web_fetch", {"url": "https://www.zigwheels.com/x"}, None, "reading zigwheels.com"),
    ("browser_click", {"text": "Next"}, None, 'clicking "Next"'),
    ("ask_bots", {"asks": [{}, {}, {}]}, None, "asking 3 bots"),
    ("make_bot", {"name": "skeptic"}, None, "adding skeptic to the team"),
    ("report", {}, None, "writing the answer"),
    ("run_shell", {"command": "ls"}, None, "running a command"),
    ("browser_click", {"text": "Buy"}, "the user said no", "refused: the user said no"),
])
def test_activity_line(tool, args, refused, expected):
    import json

    from odie.workers import progress
    assert progress.activity_line({"tool": tool, "args_json": json.dumps(args), "refused": refused}) == expected


async def test_the_team_card_follows_the_lead_and_its_teammates(world):
    from odie.workers import progress
    from odie.workers.tools import make_worker_tools
    store, _ = world
    bots.make(store, "researcher", "finds", "", ["web"])
    tools = {t.name: t for t in make_worker_tools(store)}
    Team.scripts = {"chief": [("ask_bots", {"asks": [{"bot": "researcher", "brief": "find it"}]}),
                              ("report", {"outcome": "ready", "text": "**High tide 06:10.**\nMore below."})],
                    "researcher": [("web_search", {"query": "tides goa"}), ("report", {"outcome": "ready", "text": "06:10"})]}
    got = await tools["ask_bot"].func(bot="chief", title="Tides", request="When is high tide?", tool_context=Ctx())
    assert got["media"]["kind"] == "team"
    from odie import media
    assert media.get(got["media"]["id"])[1]["job"] == got["job_id"]
    first = progress.team_view(store, got["job_id"])
    assert first["title"] == "Tides" and first["lead"]["now"] == "waiting for a turn"
    await asyncio.wait_for(router._tasks[got["job_id"]], 5)
    view = progress.team_view(store, got["job_id"])
    assert (view["lead"]["bot"], view["lead"]["status"], view["lead"]["now"]) == ("chief", "done", "High tide 06:10.")
    [mate] = view["team"]
    assert (mate["bot"], mate["now"], mate["calls"]) == ("researcher", "06:10", 2)
    assert progress.team_view(store, "job-none") is None


def test_a_chief_waiting_on_its_team_says_so(world):
    from odie.workers import progress
    store, _ = world
    chief_job = a_bot_job(store, "chief")
    kid = a_bot_job(store, "chief", parent_id=chief_job.id)
    store.execute("update jobs set status='running' where id in (?,?)", (chief_job.id, kid.id))
    jobs.record_action(store, chief_job.id, "web_search", {"query": "goa"})
    assert progress.now_line(store, jobs.get(store, chief_job.id)) == "waiting for 1 bot"
    jobs.ended(store, kid.id, "done", outcome="ready", report="x")
    assert progress.now_line(store, jobs.get(store, chief_job.id)) == 'searching "goa"'


# ── conversations with a bot (Fable's design) ────────────────────────────────

async def test_a_conversation_keeps_its_history_and_the_reply_lands_in_it(world):
    from odie.workers import convs
    store, chat = world
    bots.make(store, "writer", "writes", "", [])
    conv = convs.make(store, "writer")
    Team.scripts = {"writer": [("report", {"outcome": "ready", "text": "**Dear Asha,** thank you."}),
                               ("report", {"outcome": "ready", "text": "Shorter: Thanks, Asha!"})]}
    job = convs.send(store, conv, "Draft a thank-you note to Asha")
    assert job.conv_id == conv and job.session_id is None
    assert "still answering" in convs.send(store, conv, "again")  # one turn at a time
    await asyncio.wait_for(router._tasks[job.id], 5)
    row = convs.get(store, conv)
    assert (row["title"], row["preview"], row["unread"]) == ("Draft a thank-you note to Asha", "Dear Asha, thank you.", 1)
    assert [(m["role"], m["text"]) for m in convs.messages(store, conv)] == [
        ("user", "Draft a thank-you note to Asha"), ("bot", "**Dear Asha,** thank you.")]
    assert chat.posts == []  # a conversation's job never posts into Odie's chat
    assert "a conversation with the user" in str(Team.seen["writer"][0].config.system_instruction)
    job2 = convs.send(store, conv, "Make it shorter")
    await asyncio.wait_for(router._tasks[job2.id], 5)
    second = Team.seen["writer"][-1].contents[0].parts[0].text
    assert "The user: Draft a thank-you note to Asha" in second and "You: **Dear Asha,** thank you." in second
    assert second.rstrip().endswith("Make it shorter")
    convs.mark_read(store, conv)
    assert convs.get(store, conv)["unread"] == 0


async def test_a_question_shows_in_the_conversation_not_in_odies_chat(world):
    from odie.workers import convs
    store, chat = world
    conv = convs.make(store, "chief")
    job = jobs.create(store, "bot", "x", "y", None, bots.folder_of("chief"), 60, bot="chief", conv_id=conv)
    task = asyncio.create_task(asks.ask(store, chat, job, "tap", 'Click "Buy" on amazon.in', {"why": "may order"}))
    await asyncio.sleep(0.01)
    [ask_msg] = [m for m in convs.messages(store, conv) if m["role"] == "ask"]
    assert ask_msg["text"] == 'Click "Buy" on amazon.in' and ask_msg["media"]["status"] == "open"
    assert ask_msg["media"]["why"] == "may order"
    assert chat.posts == []
    assert convs.list_row(store, "chief")["needs_you"]
    asks.answer(store, ask_msg["media"]["ask"], "yes")
    assert await task == "yes"
    assert [m for m in convs.messages(store, conv) if m["role"] == "ask"][0]["media"]["status"] == "yes"


async def test_at_chief_from_odies_chat_is_in_the_chiefs_history_too(world):
    from odie.workers import convs
    from odie.workers.tools import make_worker_tools
    store, chat = world
    Team.scripts = {"chief": [("report", {"outcome": "ready", "text": "Done."})]}
    tools = {t.name: t for t in make_worker_tools(store)}
    got = await tools["ask_bot"].func(bot="chief", title="Tides", request="When is high tide?", tool_context=Ctx())
    await asyncio.wait_for(router._tasks[got["job_id"]], 5)
    [conv] = convs.of_bot(store, "chief")
    assert (conv["origin"], conv["title"]) == ("chat", "Tides")
    assert [m["role"] for m in convs.messages(store, conv["id"])] == ["user", "bot"]
    assert len(chat.posts) == 1  # and the chat heard, as before


def test_looks_are_kept_and_a_small_team_has_no_two_colours_alike(world):
    store, _ = world
    bots.ensure_starters(store)
    bots.ensure_looks(store)
    looks = {b.name: b.look for b in bots.all_bots(store)}
    assert looks["chief"] == bots.CHIEF_LOOK
    colours = [looks[n]["color"] for n in ("researcher", "checker", "contrarian")]
    assert len(set(colours)) == 3
    assert all(looks[n]["shape"] in bots.LOOK_SHAPES and looks[n]["eyes"] in bots.LOOK_EYES for n in looks)
    again = bots.look_for("researcher", set())
    assert again["shape"] == looks["researcher"]["shape"] and again["eyes"] == looks["researcher"]["eyes"]
    assert bots.name_hash("ab") == (ord("a") * 31 + ord("b"))


async def test_the_conversation_routes(isolated_settings, tmp_path, monkeypatch):
    from odie.app.main import create_app
    from odie.workers import convs
    from tests.test_models import FakeRunner
    monkeypatch.setenv("ODIE_WORKERS", "1")
    store = Store(tmp_path / "assistant.db")
    store.init_schema()
    jobs.ensure(store)
    bots.ensure_chief(store)
    app = create_app(runner=FakeRunner(), store=store)
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        listed = (await c.get("/api/bots")).json()["bots"]
        chief = next(b for b in listed if b["name"] == "chief")
        assert chief["look"] == bots.CHIEF_LOOK and chief["conversation"] is None and not chief["working"]
        made = (await c.post("/api/bots/chief/conversations")).json()["id"]
        assert (await c.post("/api/bots/ghost/conversations")).status_code == 404
        convs.add(store, made, "user", "hi")
        convs.add(store, made, "bot", "hello **there**")
        one = (await c.get(f"/api/conversations/{made}")).json()
        assert [m["role"] for m in one["messages"]] == ["user", "bot"] and one["running"] is None
        assert one["bot"]["name"] == "chief" and one["bot"]["unread"]
        drawer = (await c.get("/api/bots/chief/conversations")).json()
        assert [x["id"] for x in drawer["conversations"]] == [made] and drawer["conversations"][0]["preview"] == "hello there"
        assert (await c.post(f"/api/conversations/{made}/read")).status_code == 200
        assert (await c.get("/api/conversations/conv-none")).status_code == 404
        assert (await c.post(f"/api/conversations/{made}/messages", json={"text": ""})).status_code == 422


def test_the_terminals_key_cant_reach_bot_conversations():
    assert not devices.terminal_may("GET", "/api/conversations/conv-1")
    assert not devices.terminal_may("POST", "/api/conversations/conv-1/messages")
    assert not devices.terminal_may("GET", "/api/bots/chief/conversations")


async def test_bots_show_in_capabilities_and_notes_are_readable(isolated_settings, tmp_path, monkeypatch):
    from odie.app.main import create_app
    from tests.test_models import FakeRunner
    monkeypatch.setenv("ODIE_WORKERS", "1")
    store = Store(tmp_path / "assistant.db")
    store.init_schema()
    jobs.ensure(store)
    bots.ensure_chief(store)
    (bots.folder_of("chief") / "notes.md").write_text("Prefers Indian shops.")
    app = create_app(runner=FakeRunner(), store=store)
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        assert "bots" in (await c.get("/api/capabilities")).json()["caps"]
        assert (await c.get("/api/bots/chief/notes")).json() == {"text": "Prefers Indian shops."}
        assert (await c.get("/api/bots/ghost/notes")).status_code == 404
        monkeypatch.delenv("ODIE_WORKERS")
        assert "bots" not in (await c.get("/api/capabilities")).json()["caps"]


# ── the notes & photos power ─────────────────────────────────────────────────

def test_the_notes_power_gives_the_notes_and_photos_search(world):
    store, _ = world
    bots.make(store, "journal", "finds what I wrote", "", ["notes"])
    names = sorted(t.name for t in team.tools_for(bots.get(store, "journal"), store, a_bot_job(store, "journal")))
    assert names == ["read_file", "read_note", "related_notes", "search_everything", "write_file"]
    assert bots.clean_powers(["notes", "web"]) == ["web", "notes"]


def test_reading_a_note_marks_the_run_so_its_web_steps_ask(world):
    from odie.agent import turn
    store, _ = world
    job = a_bot_job(store, "journal")
    after = worker.after_for(store, job)
    token = turn.READ.set(set())
    try:
        after(Asking("search_everything", False), {"query": "goa"}, None, "Goa trip.md: …")
        after(Asking("web_search", False), {"query": "x"}, None, "results")
        assert turn.read_sources() == {"your notes"}
    finally:
        turn.READ.reset(token)
    assert [a["tool"] for a in jobs.actions(store, job.id)] == ["search_everything", "web_search"]


async def test_a_notes_only_bot_is_never_asked_to_work_past(world):
    from odie.signin import guard
    store, chat = world
    bots.make(store, "journal", "finds what I wrote", "", ["notes"])
    guard.remember_read(store, "bot:journal", "your notes")  # it read notes in an earlier job
    job = a_bot_job(store, "journal")
    await worker.ask_to_work_past(store, chat, job, bots.get(store, "journal"))
    assert asks.open_for(store) == [] and chat.posts == []
    assert worker.reaches_out(bots.get(store, "chief")) and not worker.reaches_out(bots.get(store, "journal"))


async def test_a_restart_tells_a_conversations_turn_there_not_in_odies_chat(world):
    from odie.workers import convs
    store, chat = world
    conv = convs.make(store, "chief")
    convs.add(store, conv, "user", "what are people using?")
    job = jobs.create(store, "bot", "x", "y", None, bots.folder_of("chief"), 60, bot="chief", conv_id=conv)
    store.execute("update jobs set status='running' where id=?", (job.id,))
    await router.recover()
    assert chat.posts == []  # nothing in Odie's chat ("❌ Hi didn't finish", 15 Nov)
    last = convs.messages(store, conv)[-1]
    assert last["role"] == "bot" and last["text"].startswith("I was cut off (Odie restarted)")
    assert convs.running_job(store, conv) is None  # the user can send again at once


# ── the browser: watch, take control, hand back; a secret; a bot check ───────

class JobCtx:
    """A tool_context inside a bot's job: its session (and browser tab) is the job's id."""
    def __init__(self, job_id):
        self.session = type("S", (), {"id": job_id})()


class HeldBrowser:
    def __init__(self):
        self.holds = {}
        self.typed = []

    def held_by(self, tab):
        return self.holds.get(tab)

    async def type_secret(self, tab, field, text):
        from odie.browser.engine import BrowserError
        if field != "Enter OTP":
            raise BrowserError(f'There is no field called "{field}" on the page now.')
        self.typed.append((tab, field, text))

    async def close(self):
        pass


async def test_a_bots_browser_step_waits_while_the_user_drives_then_runs(world, monkeypatch):
    import odie.browser
    store, chat = world
    b = HeldBrowser()
    monkeypatch.setattr(odie.browser, "_shared", b)
    job = a_bot_job(store, "shopper")
    b.holds[job.id] = "user"
    guard = worker.guard_for(store, job, chat)
    waiting = guard(Asking("browser_click", False), {"text": "Next"}, JobCtx(job.id))
    task = asyncio.create_task(waiting)
    await asyncio.sleep(0.05)
    assert not task.done()  # the user has the page: the bot waits
    b.holds.pop(job.id)
    assert await asyncio.wait_for(task, 3) is None  # handed back: the step runs
    assert jobs.actions(store, job.id)[-1]["tool"] == "handed_back"
    assert guard(Asking("browser_click", False), {"text": "Next"}, JobCtx(job.id)) is None  # nobody driving: no wait


async def test_a_secret_goes_into_the_page_and_nowhere_else(world, monkeypatch):
    import odie.browser
    from odie.signin import guard
    from odie.workers import convs
    store, chat = world
    b = HeldBrowser()
    monkeypatch.setattr(odie.browser, "_shared", b)
    bots.make(store, "banker", "banks", "", ["browser"])
    conv = convs.make(store, "banker")
    job = jobs.create(store, "bot", "x", "y", None, bots.folder_of("banker"), 60, bot="banker", conv_id=conv)
    guard.LAST_URL[job.id] = "https://netbanking.hdfcbank.com/otp"
    tools = {t.name: t for t in team.make_bot_signin_tool(store, job)}
    task = asyncio.create_task(tools["ask_user_to_type"].func(field="Enter OTP", why="HDFC sent a code", tool_context=JobCtx(job.id)))
    await asyncio.sleep(0.02)
    [ask] = asks.open_for(store)
    assert ask["kind"] == "secret" and ask["detail"]["field"] == "Enter OTP" and ask["detail"]["tab"] == job.id
    from odie.app.routes import type_users_secret
    from fastapi import HTTPException
    with pytest.raises(HTTPException):
        await type_users_secret({**ask["detail"], "field": "Nope"}, "123456")
    await type_users_secret(ask["detail"], "123456")
    asks.answer(store, ask["id"], "yes")
    got = await asyncio.wait_for(task, 3)
    assert "typed it" in got["result"] and "123456" not in str(got)
    assert b.typed == [(job.id, "Enter OTP", "123456")]
    everything = str(store.query("select * from job_asks")) + str(store.query("select * from bot_msgs")) + str(store.query("select * from job_actions"))
    assert "123456" not in everything  # kept nowhere
    guard.LAST_URL.pop(job.id, None)


async def test_the_answer_route_types_a_secret_and_never_audits_it(isolated_settings, tmp_path, monkeypatch):
    import odie.browser
    from odie.app.main import create_app
    from tests.test_models import FakeRunner
    monkeypatch.setenv("ODIE_WORKERS", "1")
    b = HeldBrowser()
    monkeypatch.setattr(odie.browser, "_shared", b)
    store = Store(tmp_path / "assistant.db")
    store.init_schema()
    jobs.ensure(store)
    app = create_app(runner=FakeRunner(), store=store)
    store.execute("insert into job_asks(id,job_id,kind,text,detail_json,status,created_at) values('ask-s','job-1','secret','x',"
                  "'{\"tab\": \"job-1\", \"field\": \"Enter OTP\"}','open','t')")
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        assert (await c.post("/api/jobs/asks/ask-s", json={"answer": "yes"})).status_code == 409  # nothing typed
        assert (await c.post("/api/jobs/asks/ask-s", json={"answer": "yes", "secret": "987654"})).status_code == 200
    assert b.typed == [("job-1", "Enter OTP", "987654")]
    assert "987654" not in str(store.query("select * from audit_log"))


def test_a_bot_at_a_bot_check_is_told_to_hand_it_over():
    from odie.agent.tools import browser
    from odie.browser import engine
    assert browser.BOT_CHECK_SAID in engine.BOT_NOTE  # the words the step looks for are the engine's own


def test_the_team_card_names_a_bots_browser_tab(world):
    from odie.signin import guard
    from odie.workers import progress
    store, _ = world
    job = a_bot_job(store, "shopper")
    assert progress.browser_of(job.id) == {"tab": None, "url": None}
    guard.LAST_URL[job.id] = "https://www.amazon.in/orders"
    try:
        assert progress.browser_of(job.id) == {"tab": job.id, "url": "https://www.amazon.in/orders"}
    finally:
        guard.LAST_URL.pop(job.id, None)


class WatchEngine:
    """The live view's browser, as tests/test_signin_live.py has it, plus watching and taking control."""
    def __init__(self):
        self.calls = []
        self.holds = {}

    def hold(self, tab, holder):
        self.holds[tab] = holder

    def release(self, tab, holder=None):
        self.holds.pop(tab, None)

    def held_by(self, tab):
        return self.holds.get(tab)

    def on_upi(self, fn):
        pass

    async def live_start(self, tab, width, height, on_frame, on_page, emulate=True):
        self.calls.append(("start", tab, emulate))
        await on_page({"url": "https://www.amazon.in/", "title": "Amazon", "loading": False})
        await on_frame("/9j/AAAA", {"deviceWidth": width, "deviceHeight": height})

    async def live_control(self, tab, width, height):
        self.calls.append(("control", tab, width, height))

    async def live_input(self, tab, msg):
        self.calls.append(("input", tab, msg))

    async def live_stop(self, tab):
        self.calls.append(("stop", tab))

    async def close(self):
        pass


def test_watch_then_take_control_then_close(isolated_settings, tmp_path, monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    import odie.browser
    from fastapi.testclient import TestClient

    from odie.app.main import create_app
    from odie.signin import live, state
    from tests.test_api import FakeRunner as ApiRunner
    store = Store(tmp_path / "a.db")
    store.init_schema()
    state.turn_on(store, accepted=True, version=state.VERSION, now=datetime(2026, 11, 15, 9, 0, tzinfo=ZoneInfo("Asia/Kolkata")))
    e = WatchEngine()
    monkeypatch.setattr(odie.browser, "_shared", e)
    app = create_app(runner=ApiRunner(), store=store)
    with TestClient(app) as c, c.websocket_connect("/api/browser/live/job-abc123") as ws:
        ws.send_json({"t": "hello", "w": 390, "h": 844, "watch": True})
        assert ws.receive_json()["t"] == "page" and ws.receive_json()["t"] == "frame"
        assert e.calls[0] == ("start", "job-abc123", False) and e.held_by("job-abc123") is None  # the bot keeps working
        ws.send_json({"t": "tap", "x": 10, "y": 10})  # watching: nothing reaches the page
        ws.send_json({"t": "ping"})
        assert ws.receive_json() == {"t": "pong"}
        assert not [x for x in e.calls if x[0] == "input"]
        ws.send_json({"t": "control"})
        assert ws.receive_json() == {"t": "control"}
        assert e.held_by("job-abc123") and ("control", "job-abc123", 390, 844) in e.calls  # the bot's steps wait now
        ws.send_json({"t": "forward"})
        ws.send_json({"t": "ping"})
        assert ws.receive_json() == {"t": "pong"}
        assert ("input", "job-abc123", {"t": "forward"}) in e.calls
        ws.send_json({"t": "close"})
    assert e.held_by("job-abc123") is None and ("stop", "job-abc123") in e.calls  # handed back
    assert live.clean({"t": "forward"}) == {"t": "forward"} and live.clean({"t": "control"}) == {"t": "control"}



def test_a_reply_the_user_reads_may_draw_blocks_a_teammates_report_doesnt(world):
    store, _ = world
    chief = bots.get(store, "chief")
    lead = team.kind_for(chief, conversation=True).instruction
    mate = team.kind_for(chief, teammate=True).instruction
    assert "odie-blocks" in lead and "odie-blocks" not in mate
    assert "{folder}" in lead  # still a placeholder; the Worker fills it with replace, braces in the JSON untouched


# ── routines: bots that run by themselves ────────────────────────────────────

def test_a_schedule_is_cleaned_and_said_in_words():
    from odie.workers import routines
    assert routines.clean_schedule({"kind": "daily", "at": "8:30"}) == {"kind": "daily", "at": "08:30", "days": [0, 1, 2, 3, 4, 5, 6]}
    assert routines.clean_schedule({"kind": "daily", "at": "25:00"}) == "A time like 08:30."
    assert routines.clean_schedule({"kind": "daily", "at": "08:00", "days": []}) == "Pick at least one day."
    assert routines.clean_schedule({"kind": "every", "hours": 0}) == "Every 1 to 168 hours."
    assert routines.clean_schedule({"kind": "weekly"}) == "Say when: daily at a time, or every few hours."
    assert routines.when_words({"kind": "daily", "at": "08:30", "days": list(range(7))}) == "Every day at 08:30"
    assert routines.when_words({"kind": "daily", "at": "09:15", "days": [0, 1, 2, 3, 4]}) == "Weekdays at 09:15"
    assert routines.when_words({"kind": "daily", "at": "07:00", "days": [0, 3]}) == "Mon, Thu at 07:00"
    assert routines.when_words({"kind": "every", "hours": 1}) == "Every hour"


def test_next_run_lands_on_the_right_local_day_and_time():
    from datetime import UTC, datetime, timedelta
    from zoneinfo import ZoneInfo

    from odie.workers import routines
    ist = ZoneInfo("Asia/Kolkata")
    daily = {"kind": "daily", "at": "08:30", "days": list(range(7))}
    weekdays = {"kind": "daily", "at": "08:30", "days": [0, 1, 2, 3, 4]}
    mon_0800 = datetime(2026, 11, 16, 8, 0, tzinfo=ist).astimezone(UTC)
    mon_0900 = datetime(2026, 11, 16, 9, 0, tzinfo=ist).astimezone(UTC)
    fri_0900 = datetime(2026, 11, 20, 9, 0, tzinfo=ist).astimezone(UTC)
    assert routines.next_run(daily, mon_0800, ist) == datetime(2026, 11, 16, 8, 30, tzinfo=ist)
    assert routines.next_run(daily, mon_0900, ist) == datetime(2026, 11, 17, 8, 30, tzinfo=ist)
    assert routines.next_run(weekdays, fri_0900, ist) == datetime(2026, 11, 23, 8, 30, tzinfo=ist)  # Monday
    assert routines.next_run({"kind": "every", "hours": 3}, mon_0800, ist) == mon_0800 + timedelta(hours=3)


async def test_a_routine_runs_when_due_in_its_own_conversation_and_only_once_after_a_sleep(world):
    from datetime import UTC, datetime

    from odie.workers import convs, routines
    store, chat = world
    bots.make(store, "markets", "morning market note", "", [])
    made = routines.make(store, "markets", "Morning note", "Tell me what moved in my watchlist.",
                         {"kind": "every", "hours": 3}, now=datetime(2026, 11, 16, 0, 0, tzinfo=UTC))
    assert made["when"] == "Every 3 hours" and made["next_run_at"] == "2026-11-16T03:00:00+00:00"
    assert convs.get(store, made["conv_id"])["origin"] == "routine"
    assert await routines.tick(store, now=datetime(2026, 11, 16, 2, 0, tzinfo=UTC)) == []  # not yet
    Team.scripts = {"markets": [("report", {"outcome": "ready", "text": "Nifty flat; HDFC −2%."})]}
    later = datetime(2026, 11, 16, 9, 0, tzinfo=UTC)  # the Mac slept through two runs
    [line] = await routines.tick(store, now=later)
    job_id = line.split("started ")[1]
    await asyncio.wait_for(router._tasks[job_id], 5)
    msgs = convs.messages(store, made["conv_id"])
    assert [m["role"] for m in msgs] == ["note", "note", "bot"] and msgs[-1]["text"] == "Nifty flat; HDFC −2%."
    assert msgs[1]["text"].startswith("⏰ Morning note")
    assert routines.get(store, made["id"])["next_run_at"] == "2026-11-16T12:00:00+00:00"  # from now: once, not twice
    first_brief = Team.seen["markets"][0].contents[0].parts[0].text
    assert "scheduled run" in first_brief and "Tell me what moved" in first_brief
    assert chat.posts == []


def test_pause_resume_delete_and_a_deleted_bot_takes_its_routines(world):
    from datetime import UTC, datetime

    from odie.workers import routines
    store, _ = world
    bots.make(store, "markets", "notes", "", [])
    r = routines.make(store, "markets", "Note", "Do it.", {"kind": "daily", "at": "08:30"})
    assert "no bot" in routines.make(store, "ghost", "x", "y", {"kind": "every", "hours": 2})
    assert "Say what" in routines.make(store, "markets", "x", " ", {"kind": "every", "hours": 2})
    paused = routines.edit(store, r["id"], paused=True)
    assert paused["paused"] and paused["next_run_at"] is None
    assert routines.due(store, datetime(2030, 1, 1, tzinfo=UTC)) == []
    resumed = routines.edit(store, r["id"], paused=False, schedule={"kind": "every", "hours": 6})
    assert resumed["when"] == "Every 6 hours" and resumed["next_run_at"]
    bots.delete(store, "markets")
    assert routines.of_bot(store, "markets") == []


async def test_the_routine_routes_and_the_chat_tool(isolated_settings, tmp_path, monkeypatch):
    from odie.app.main import create_app
    from odie.workers.tools import make_worker_tools
    from tests.test_models import FakeRunner
    monkeypatch.setenv("ODIE_WORKERS", "1")
    monkeypatch.setattr(worker, "model_for_bot", lambda store, bot: Team(model="team"))
    store = Store(tmp_path / "assistant.db")
    store.init_schema()
    jobs.ensure(store)
    bots.ensure_chief(store)
    app = create_app(runner=FakeRunner(), store=store)
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        router.hooks.update(store=store, runner=FakeRunner())
        made = await c.post("/api/bots/chief/routines", json={"title": "Daily brief", "brief": "Brief me.",
                                                              "schedule": {"kind": "daily", "at": "07:30", "days": [0, 1, 2, 3, 4]}})
        assert made.status_code == 200 and made.json()["routine"]["when"] == "Weekdays at 07:30"
        rid = made.json()["routine"]["id"]
        assert (await c.post("/api/bots/chief/routines", json={"brief": "x", "schedule": {"kind": "daily", "at": "99"}})).status_code == 422
        assert [r["id"] for r in (await c.get("/api/bots/chief/routines")).json()["routines"]] == [rid]
        assert (await c.put(f"/api/routines/{rid}", json={"paused": True})).json()["routine"]["paused"]
        Team.scripts = {"chief": [("report", {"outcome": "ready", "text": "Morning!"})]}
        ran = await c.post(f"/api/routines/{rid}/run")
        assert ran.status_code == 200
        await asyncio.wait_for(router._tasks[ran.json()["job"]], 5)
        assert (await c.delete(f"/api/routines/{rid}")).status_code == 200
        assert (await c.delete(f"/api/routines/{rid}")).status_code == 404
    tools = {t.name: t for t in make_worker_tools(store)}
    got = await tools["make_routine"].func(bot="chief", title="Market note", request="What moved?", at="09:15", days=[0, 1, 2, 3, 4])
    assert got["when"] == "Weekdays at 09:15"
    assert "no bot" in (await tools["make_routine"].func(bot="ghost", title="x", request="y", every_hours=2))["error"]
    assert not devices.terminal_may("POST", "/api/routines/rt-1/run")
