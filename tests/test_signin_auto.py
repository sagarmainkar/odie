"""Signing in by itself (spec "Sign in for me", Part 4): a sign-in page of a site with a saved login, in a chat turn,
is filled by the engine and the model reads the page after; never twice in 10 minutes, never in background work,
and the model never sees the username or the password."""
import json
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from odie.agent import turn
from odie.agent.tools import browser as btools
from odie.browser.engine import Page
from odie.signin import box, state, vault
from odie.store.db import Store

NOW = datetime(2026, 10, 8, 9, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
SHOT = b"\xff\xd8\xff\xe0" + b"\x00" * 200
SECRET, USER = "pw-auto-secret", "asha.private@example.com"


class Engine:
    def __init__(self, answer="signed_in"):
        self.answer, self.signins = answer, []

    async def open(self, tab, url, isolated=False):
        return Page(url="https://www.example.com/login", title="Sign in", text="Email\nPassword", shot=SHOT, login=True, signin=True)

    async def sign_in(self, tab, site, username, password):
        self.signins.append((tab, site, username, password))
        return {"status": self.answer}

    async def click(self, tab, text):
        return await self.open(tab, "")

    async def look(self, tab):
        return Page(url="https://www.example.com/orders", title="Your orders", text="Order 402-77 ships today", shot=SHOT)


@pytest.fixture
def store(isolated_settings, tmp_path, keychain):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    state.turn_on(s, accepted=True, version=state.VERSION, now=NOW)
    vault.save(s, "example.com", USER, SECRET, NOW)
    return s


@pytest.fixture
def chat():
    token = turn.USER_TEXT.set("where is my order")
    yield
    turn.USER_TEXT.reset(token)


async def run(store, engine):
    tools = {t.name: t for t in btools.make_browser_tools(store, browser_for=lambda: engine)}
    return await tools["browser_open"].run_async(args={"url": "https://www.example.com/orders"},
                                                 tool_context=SimpleNamespace(session=SimpleNamespace(id="chat-1")))


async def test_a_saved_login_signs_in_by_itself(store, chat):
    engine = Engine()
    out = await run(store, engine)
    assert engine.signins == [("chat-1", "example.com", USER, SECRET)]
    assert "(Signed in to example.com with the user's saved login.)" in out["result"] and "Order 402-77" in out["result"]
    assert out["media"]["kind"] == "turn" and out["media"]["state"] == "done" and out["media"]["auto"] is True


async def test_the_model_never_sees_the_login(store, chat):
    for answer in ("signed_in", "failed", "code"):
        box.for_store(store).forget()
        out = await run(store, Engine(answer))
        assert SECRET not in json.dumps(out) and USER not in json.dumps(out)


async def test_only_once_every_ten_minutes(store, chat):
    engine = Engine("failed")
    first = await run(store, engine)
    assert first["media"]["state"] == "failed" and first["media"]["why"] == "example.com didn't take the saved login."
    await run(store, engine)
    assert len(engine.signins) == 1  # a wrong saved password is tried once, then the user is asked


async def test_a_code_step_hands_over(store, chat):
    out = await run(store, Engine("code"))
    assert out["media"]["state"] == "code" and "their turn" in out["result"]
    assert "chat-1" in box.for_store(store)._pending  # the code card's code goes to this login


async def test_background_work_never_signs_in(store):
    engine = Engine()
    await run(store, engine)  # no chat turn: turn.USER_TEXT is None
    assert engine.signins == []


async def test_no_saved_login_brings_the_card(store, chat):
    """Found live: glm flash offered to type a practice site's published password instead of calling browser_sign_in.
    A sign-in page in a chat step brings the Sign in card itself (once per site every 5 minutes)."""
    vault.delete(store, "example.com")
    engine = Engine()
    out = await run(store, engine)
    assert engine.signins == [] and out["media"]["kind"] == "turn" and out["media"]["site"] == "example.com"
    assert "state" not in out["media"] and "Sign in card for example.com is in the chat" in out["result"]
    again = await run(store, engine)
    assert again["media"]["kind"] == "screenshot" and "browser_sign_in" in again["result"]  # no second card so soon


@pytest.mark.parametrize("how", ["click", "open"])
async def test_logging_out_isnt_undone(store, chat, how):
    """Found live: after "click Logout", the site showed its login page and Odie signed straight back in. Logging out
    (a click on Log out / Sign out, or a logout address) leaves the site signed out: no automatic sign-in, no card."""
    engine = Engine()
    tools = {t.name: t for t in btools.make_browser_tools(store, browser_for=lambda: engine)}
    ctx = SimpleNamespace(session=SimpleNamespace(id="chat-1"))
    if how == "click":
        out = await tools["browser_click"].run_async(args={"text": "Log out"}, tool_context=ctx)
    else:
        out = await tools["browser_open"].run_async(args={"url": "https://www.example.com/logout"}, tool_context=ctx)
    assert engine.signins == [] and out["media"]["kind"] == "screenshot" and "Signed out of example.com" in out["result"]
    await run(store, engine)  # the same turn: no signing straight back in
    assert engine.signins == []
    token = turn.USER_TEXT.set("now show my orders")  # the user's next request: a new turn may sign in again
    try:
        await run(store, engine)
    finally:
        turn.USER_TEXT.reset(token)
    assert len(engine.signins) == 1


async def test_a_logout_click_that_changed_nothing_isnt_a_sign_out(store, chat):
    class Stays(Engine):
        async def click(self, tab, text):  # the click didn't go anywhere: still the signed-in page
            return await self.look(tab)
    engine = Stays()
    tools = {t.name: t for t in btools.make_browser_tools(store, browser_for=lambda: engine)}
    ctx = SimpleNamespace(session=SimpleNamespace(id="chat-1"))
    from odie.signin import guard
    guard.LAST_URL["chat-1"] = "https://www.example.com/orders"
    out = await tools["browser_click"].run_async(args={"text": "Log out"}, tool_context=ctx)
    assert "Signed out" not in out["result"]


async def test_a_new_turn_may_sign_in_again(store, chat):
    """Found live: after a successful automatic sign-in and a logout, the next request showed the card. The 10-minute
    wait is for a failed attempt; after a success, only the same turn waits (no loop when a site keeps logging out)."""
    engine = Engine()
    await run(store, engine)
    await run(store, engine)  # the same turn: no second automatic sign-in
    assert len(engine.signins) == 1
    token = turn.USER_TEXT.set("where is my other order")
    try:
        await run(store, engine)
    finally:
        turn.USER_TEXT.reset(token)
    assert len(engine.signins) == 2


async def test_one_card_not_two(store, chat):
    """Found live: after the step's "saved password didn't work" card, the model called browser_sign_in too, and a
    second card appeared. The tool points to the card already there."""
    engine = Engine("failed")
    await run(store, engine)
    sign_in = {t.name: t for t in btools.make_signin_tools(store)}["browser_sign_in"]
    out = await sign_in.run_async(args={"why": "sign in"}, tool_context=SimpleNamespace(session=SimpleNamespace(id="chat-1")))
    assert "media" not in out and "already in the chat" in out["result"]
