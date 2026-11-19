"""A promise Odie made in chat, carried out when due (proactive design §17, phase 4): one background turn that may
only read; done -> a follow-up in that chat; anything more -> his card. A promise never makes Odie take a step that
needs his tap."""
import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from odie.loops import budget, cards, chat_read, clock, ledger, promise_run
from odie.store.db import Store
from odie.watch import pushes

TZ = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 11, 19, 21, 5, tzinfo=TZ)
TONIGHT = "2026-11-19T21:00:00+05:30"


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


def a_promise(store, pid=""):
    lid = ledger.open_loop(store, pid, NOW - timedelta(hours=10), "Check the build again", "promise", owner="odie",
                           playbook="promise", state="waiting", due_at=TONIGHT, source="chat", ref="chat:chat-1",
                           fact="Odie said in chat: “I'll look at the build again tonight”",
                           card={"chat": "chat-1", "said": "I'll look at the build again tonight", "asked": "is it green?"})
    ledger.update(store, lid, NOW - timedelta(hours=10), has_news=0, next_check_at=TONIGHT)
    return ledger.get(store, lid)


class Recorder:
    def __init__(self, reply="", error=None):
        self.reply, self.error = reply, error
        self.calls, self.told, self.pushed = [], [], []

    async def act(self, prompt, instruction, keep, guard):
        self.calls.append((prompt, instruction, keep, guard))
        if self.error:
            raise self.error
        return self.reply

    async def tell(self, session_id, text):
        self.told.append((session_id, text))

    def push(self, title, body):
        self.pushed.append((title, body))


def test_a_promise_is_due_at_its_time_and_not_before(store):
    loop = a_promise(store)
    assert not clock.is_due(loop, NOW - timedelta(hours=1))
    assert clock.is_due(loop, NOW)


async def test_done_posts_the_follow_up_in_that_chat_and_closes_the_loop(store):
    loop = a_promise(store)
    r = Recorder('Looked again. {"done": true, "message": "The build is green now: the flaky test passed."}')
    assert await promise_run.run(store, loop, NOW, r.act, r.tell, r.push) == "done"
    assert r.told == [("chat-1", "The build is green now: the flaky test passed.")]
    closed = ledger.get(store, loop["id"])
    assert closed["state"] == "closed" and closed["closed_by"] == "odie" and closed["closed_why"].startswith("Did it")
    assert r.pushed == [("Check the build again", "The build is green now: the flaky test passed.")]
    assert pushes.sent_today(store, NOW) == 1  # the shared three a day


async def test_not_done_becomes_his_card_with_check_now(store):
    loop = a_promise(store)
    r = Recorder('{"done": false, "why": "the build runs on your machine; I can only read"}')
    assert await promise_run.run(store, loop, NOW, r.act, r.tell, r.push) == "card"
    after = ledger.get(store, loop["id"])
    assert after["owner"] == "you" and after["state"] == "ready" and after["playbook"] == ""
    assert "couldn't on my own: the build runs on your machine" in after["result"]
    card = cards.card(after)
    assert card["main"] == {"label": "Check now", "action": "chat", "value": f"Loop #{loop['id']}: Check now"}
    assert card["other"]["action"] == "loop_done" and card["later"]["action"] == "later"
    assert not clock.is_due(after, NOW + timedelta(days=1))  # the clock is done with it
    assert r.told == []


async def test_a_failed_or_muddled_turn_becomes_his_card(store):
    for r in (Recorder(error=RuntimeError("down")), Recorder("I looked but forgot the JSON.")):
        loop = a_promise(store)
        assert await promise_run.run(store, loop, NOW, r.act, r.tell, r.push) == "card"
        assert ledger.get(store, loop["id"])["state"] == "ready"


async def test_no_push_at_night(store):
    loop = a_promise(store)
    r = Recorder('{"done": true, "message": "Green."}')
    await promise_run.run(store, loop, NOW.replace(hour=23), r.act, r.tell, r.push)
    assert r.pushed == [] and r.told


async def test_at_most_eight_a_day_then_his_card_without_a_call(store):
    for _ in range(promise_run.PROMISE_DAILY):
        assert promise_run.spend(store, NOW)
    loop = a_promise(store)
    r = Recorder('{"done": true, "message": "Green."}')
    assert await promise_run.run(store, loop, NOW, r.act, r.tell, r.push) == "card"
    assert r.calls == []
    assert budget.used_today(store, NOW) == promise_run.PROMISE_DAILY  # each spent from the 150


async def test_the_turn_is_handed_only_the_reads_and_the_guard(store):
    loop = a_promise(store)
    r = Recorder('{"done": true, "message": "Green."}')
    await promise_run.run(store, loop, NOW, r.act, r.tell, r.push)
    prompt, instruction, keep, guard = r.calls[0]
    assert "I'll look at the build again tonight" in prompt and "is it green?" in prompt
    assert "You can only read" in instruction
    assert keep is promise_run.keeps


def test_only_reads_are_kept():
    for name in ("web_search", "web_fetch", "recall", "fetch_memory", "jobs_status", "watch_item", "mac_mail_read",
                 "gmail_find_email", "GMAIL_FETCH_EMAILS", "now"):
        assert promise_run.keeps(name), name
    for name in ("task_add", "task_update", "update_memory", "forget_memory", "start_job", "stop_job", "run_shell",
                 "watch_close", "track", "make_research", "make_deck", "install_skill", "draft_skill",
                 "gmail_send_email", "calendar_create_event", "mac_calendar_add", "mac_reminder_add", "speak",
                 "browser_open", "get_or_create_contact", "COMPOSIO_MULTI_EXECUTE_TOOL"):
        assert not promise_run.keeps(name), name


def test_the_guard_refuses_any_step_that_needs_a_tap(store):
    guard = promise_run.guard_for()
    ctx = SimpleNamespace(state={}, session=None)
    assert guard(SimpleNamespace(name="task_add"), {}, ctx) is not None  # not a read
    assert guard(SimpleNamespace(name="run_shell"), {}, ctx) is not None
    asks = SimpleNamespace(name="gmail_find_email", _asks_in_careful=True)  # an app read that asks in Careful
    assert guard(asks, {}, ctx) is not None
    assert guard(SimpleNamespace(name="web_search"), {"query": "ci status"}, ctx) is None


def test_no_web_once_it_read_something_of_his(store):
    guard = promise_run.guard_for()
    ctx = SimpleNamespace(state={}, session=None)
    assert guard(SimpleNamespace(name="recall"), {"query": "build"}, ctx) is None
    assert guard(SimpleNamespace(name="jobs_status"), {}, ctx) is None
    assert guard(SimpleNamespace(name="web_fetch"), {"url": "https://example.com/?q=x"}, ctx) is not None
    fresh = promise_run.guard_for()  # each turn keeps its own
    assert fresh(SimpleNamespace(name="web_search"), {"query": "x"}, ctx) is None


def flat_tools(tools):
    from google.adk.tools.base_toolset import BaseToolset
    out = []
    for t in tools:
        if isinstance(t, BaseToolset):
            try:
                out += asyncio.run(t.get_tools(None))
            except Exception:  # noqa: BLE001
                continue
        else:
            out.append(t)
    return out


def test_whatever_tools_the_agent_has_a_promise_runs_only_reads(store):
    from odie.agent.agent import build_agent
    guard = promise_run.guard_for()
    ctx = SimpleNamespace(state={}, session=None)
    every = flat_tools(list(build_agent(store).tools))
    runs = sorted({t.name for t in every if promise_run.keeps(t.name) and guard(t, {}, ctx) is None})
    assert set(runs) <= promise_run.READS, f"not a read: {sorted(set(runs) - promise_run.READS)}"
    assert "task_add" not in runs and "start_job" not in runs and "update_memory" not in runs


async def test_the_clock_hands_a_due_promise_to_its_turn_not_to_github(store):
    loop = a_promise(store)
    r = Recorder('{"done": true, "message": "Green."}')

    def think_for(pid):
        async def think(prompt, instruction):
            raise AssertionError("a promise never goes to stage 4's GitHub call")
        return think
    ran = await clock.run(store, NOW, think_for, act_for=lambda pid: r.act, tell=r.tell)
    assert ran == [(loop["id"], "done")]


async def test_without_a_turn_to_run_it_a_promise_waits(store):
    a_promise(store)

    def think_for(pid):
        async def think(prompt, instruction):
            raise AssertionError("never")
        return think
    assert await clock.run(store, NOW, think_for) == []


async def test_from_chat_to_follow_up(store):
    import json

    async def think(prompt, instruction):
        return json.dumps({"odie": [{"what": "Check the build again", "when": TONIGHT,
                                     "said": "I'll look at the build again tonight"}], "you": []})
    got = await chat_read.read(store, "chat-1", NOW - timedelta(hours=10), typed="is it green?",
                               reply="One test failed. I'll look at the build again tonight.", think=think)
    r = Recorder('{"done": true, "message": "Green now."}')
    ran = await clock.run(store, NOW, lambda pid: think, act_for=lambda pid: r.act, tell=r.tell)
    assert ran == [(got["promises"][0], "done")] and r.told == [("chat-1", "Green now.")]


def test_he_may_call_off_a_promise_in_chat_with_his_tap(store):
    from odie.agent import turns
    from odie.loops import chat_done
    loop = a_promise(store)
    ctx = SimpleNamespace(session=SimpleNamespace(id="chat-1"), state={})
    assert chat_done.decide(store, loop, ctx)[0] == chat_done.TAP
    turns.mark("chat-1", turns.TERMINAL)
    try:
        assert chat_done.decide(store, loop, ctx)[0] == chat_done.REFUSE
    finally:
        turns.unmark("chat-1")


async def test_the_background_runs_a_promise_on_its_owners_brain_with_only_reads(store):
    from odie.agent.callbacks import OPEN
    from odie.app import main
    loop = a_promise(store)
    turns, posts = [], []

    class Runner:
        bus = SimpleNamespace(emit=lambda event: None)

        async def background_turn(self, prompt, **kw):
            turns.append(kw)
            return '{"done": true, "message": "Green now."}'

        async def post_message(self, text, session_id=None, **kw):
            posts.append((text, session_id, kw))
    await main.run_loops(store, Runner(), NOW)
    [kw] = turns
    assert kw["keep"] is promise_run.keeps and callable(kw["guard"]) and not kw.get("bare") and kw["owner"] == ""
    [(text, session_id, more)] = posts
    assert session_id == "chat-1" and text.startswith(OPEN) and more["shown"] == "Green now."
    assert ledger.get(store, loop["id"])["state"] == "closed"


def test_no_mail_can_reach_a_promise_loop(store):
    from odie.loops import consolidate
    loop = a_promise(store)
    stranger = {"from_github": False}
    assert consolidate.may_touch(loop, stranger) is False  # stage 2 can't close, retitle or move it
