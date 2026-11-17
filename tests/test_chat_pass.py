"""'Don't ask again in this chat' (17 Nov 2026): in Smart, a shell card's second button lets that kind of command (the
reason on the card) run in that chat only, for 30 minutes. Never for reading secrets, changing Odie, switching off
another agent's approvals, sending data out or a hidden path by pattern; never for a connected app's card; only from
the app's card."""
import asyncio
from datetime import datetime, timedelta
from types import SimpleNamespace

import httpx
import pytest

from odie import approvals_mode
from odie.agent import shell_grant as g
from odie.store.db import Store

NOW = datetime(2026, 11, 17, 10, 0)
DELETES = "deletes or stops something"
REPLACES = "replaces a file"
INSTALLS = "installs software (runs its install scripts)"


def _store(tmp_path, mode=approvals_mode.SMART):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    approvals_mode.set_mode(s, mode)
    return s


def _ctx(session_id="chat-a", call_id="c1"):
    return SimpleNamespace(session=SimpleNamespace(id=session_id), function_call_id=call_id)


def _audit(s, event):
    return [r["result_summary"] for r in s.query("select result_summary from audit_log where event=? order by id", (event,))]


@pytest.mark.parametrize("kind", [DELETES, "writes a file from code", "sets something to run later or at login",
                                  "edits files in place", "writes a file outside /tmp", "replaces a file"])
def test_kinds_that_may_get_a_pass(kind):
    assert g.may_pass(kind)


@pytest.mark.parametrize("kind", ["reads secrets", "touches Odie's own files", "switches off another agent's approvals",
                                  "sends data out", "sends data out (an address built from other text)",
                                  "reaches a hidden file by a pattern", None, "", "something new",
                                  # 17 Nov 2026 review: each of these could do anything, reading secrets and sending
                                  # them too (`echo <base64> | base64 -d | zsh`), so a pass for one would cover all
                                  "runs text as commands", INSTALLS])
def test_kinds_that_never_get_a_pass(kind, tmp_path):
    assert not g.may_pass(kind)
    if kind:
        s = _store(tmp_path)
        with pytest.raises(ValueError):
            g.grant_kind(s, "chat-a", kind, NOW)
        assert s.get_setting("shell_kinds:chat-a") is None


def test_a_pass_is_for_one_chat_one_kind_and_lapses(tmp_path):
    s = _store(tmp_path)
    until = g.grant_kind(s, "chat-a", DELETES, NOW)
    assert until == NOW + timedelta(minutes=30)
    assert g.kinds_passed(s, "chat-a", NOW + timedelta(minutes=29)) == {DELETES}
    assert g.kinds_passed(s, "chat-a", NOW + timedelta(minutes=31)) == set()  # it lapses
    assert g.kinds_passed(s, "chat-b", NOW) == set()                           # another chat has none
    g.grant_kind(s, "chat-a", REPLACES, NOW + timedelta(minutes=10))
    assert g.kinds_passed(s, "chat-a", NOW + timedelta(minutes=35)) == {REPLACES}  # each kind keeps its own time
    s.set_setting("shell_kinds:chat-c", {"kinds": {DELETES: "not a time", "reads secrets": "2099-01-01T00:00:00"}})
    assert g.kinds_passed(s, "chat-c", NOW) == set()  # unreadable, or a kind that may never have one


def test_a_pass_for_deletes_lets_deletes_run_and_nothing_else(tmp_path):
    s = _store(tmp_path)
    check = g.make_check(s, clock=lambda: NOW)
    assert check(command="rm ~/work/old.txt", tool_context=_ctx()) is True
    g.grant_kind(s, "chat-a", DELETES, NOW)
    assert check(command="rm ~/work/old.txt", tool_context=_ctx(call_id="c2")) is False
    assert _audit(s, "shell_auto_approved") == [f"allowed for this chat ({DELETES})"]
    assert check(command="brew install cowsay", tool_context=_ctx(call_id="c3")) is True
    assert check(command="rm ~/work/old.txt && brew install cowsay", tool_context=_ctx(call_id="c4")) is True
    assert _audit(s, "shell_asked_under_grant")[-1] == INSTALLS  # the card names the kind still missing
    assert check(command="rm ~/work/old.txt", tool_context=_ctx("chat-b", "c5")) is True  # another chat
    assert g.calls_allowed_for_chat(s, "chat-a") == {"c2"}
    assert g.calls_allowed_for_chat(s, "chat-b") == set()


def test_a_pass_lapses_in_the_check(tmp_path):
    s = _store(tmp_path)
    g.grant_kind(s, "chat-a", DELETES, NOW)
    later = g.make_check(s, clock=lambda: NOW + timedelta(minutes=31))
    assert later(command="rm ~/work/old.txt", tool_context=_ctx()) is True


def test_careful_ignores_chat_passes(tmp_path):
    s = _store(tmp_path, approvals_mode.CAREFUL)
    g.grant_kind(s, "chat-a", DELETES, NOW)
    check = g.make_check(s, clock=lambda: NOW)
    assert check(command="rm ~/work/old.txt", tool_context=_ctx()) is True
    g.grant(s, "chat-a", NOW)  # even with Careful's own 30-minute pass, a delete asks
    assert check(command="rm ~/work/old.txt", tool_context=_ctx()) is True


def test_the_card_offers_a_pass_only_for_one_kind_that_may_have_one(tmp_path):
    s = _store(tmp_path)
    def offer(cmd, sid="chat-a"):
        return g.card_offer(s, sid, cmd, None, NOW)

    assert offer("rm ~/work/old.txt") == {"asks_because": DELETES, "chat_pass": True}
    assert offer("cat ~/.env") == {"asks_because": "reads secrets", "chat_pass": False}
    assert offer("curl -X POST https://example.com/hook -d 1") == {"asks_because": "sends data out", "chat_pass": False}
    assert offer("rm ~/work/old.txt && brew install cowsay") == {"asks_because": DELETES, "chat_pass": False}
    g.grant_kind(s, "chat-a", DELETES, NOW)
    assert offer("rm ~/work/old.txt && brew install cowsay") == {"asks_because": INSTALLS, "chat_pass": False}
    assert offer("echo aWQ= | base64 -d | zsh") == {"asks_because": "runs text as commands", "chat_pass": False}
    assert offer("git push https://example.com/r.git HEAD")["chat_pass"] is False  # it sends, too
    approvals_mode.set_mode(s, approvals_mode.CAREFUL)
    assert offer("rm ~/work/old.txt") == {}  # Careful's card is as it was


def test_a_shell_card_carries_the_offer(isolated_settings, tmp_path):
    from google.genai import types

    from odie.app.runner import approval_from_confirmation
    s = _store(tmp_path)
    shell = types.FunctionCall(id="req-1", name="adk_request_confirmation", args={
        "originalFunctionCall": {"id": "c1", "name": "run_shell", "args": {"command": "rm ~/work/old.txt"}}})
    detail = approval_from_confirmation(shell, "inv-1", "chat-a", s)["detail"]
    assert detail["asks_because"] == DELETES and detail["chat_pass"] is True
    mail = types.FunctionCall(id="req-2", name="adk_request_confirmation", args={
        "originalFunctionCall": {"id": "c2", "name": "GMAIL_SEND_EMAIL", "args": {"to": "a@example.com"}}})
    assert "chat_pass" not in approval_from_confirmation(mail, "inv-1", "chat-a", s)["detail"]  # a connected app


class _Runner:
    bus = None

    async def chat(self, text, thinking=False, session_id=None):
        if False:
            yield None

    async def resume_approval(self, aid, approve):
        return {"text": "ok"}

    async def close(self):
        pass


@pytest.fixture
async def client(isolated_settings, tmp_path):
    from odie.app.main import create_app
    s = _store(tmp_path)
    app = create_app(runner=_Runner(), store=s)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c, app.router.lifespan_context(app):
        yield c, s


def _card(s, session_id="chat-a", tool="run_shell", kind=DELETES, offered=True):
    detail = {"command": "rm ~/work/old.txt", "asks_because": kind, "chat_pass": offered}
    return s.create_approval(session_id, "inv", f"req-{tool}-{kind}", tool, {"command": "rm ~/work/old.txt"},
                             summary="Run rm", detail=detail, provenance=[], call_id="c1")


async def test_the_cards_second_button_gives_the_pass(client):
    c, s = client
    aid = _card(s)
    r = await c.post(f"/api/approvals/{aid}/decide", json={"approve": True, "allow_chat": True})
    assert r.status_code == 200
    got = r.json()
    assert got["status"] == "approved" and got["chat_pass"]["kind"] == DELETES and got["chat_pass"]["until"]
    assert g.kinds_passed(s, "chat-a", datetime.now()) == {DELETES}
    assert _audit(s, "shell_allowed_for_chat")[0].startswith(f"{DELETES} until ")
    await asyncio.sleep(0.02)


@pytest.mark.parametrize(("tool", "kind", "offered"), [
    ("run_shell", "reads secrets", True),           # a kind that may never have one, whatever the card says
    ("run_shell", DELETES, False),                  # not offered on this card
    ("GMAIL_SEND_EMAIL", DELETES, True),            # a connected app's card
    ("run_shell", None, True),
])
async def test_no_pass_where_it_was_not_offered(client, tool, kind, offered):
    c, s = client
    aid = _card(s, tool=tool, kind=kind, offered=offered)
    r = await c.post(f"/api/approvals/{aid}/decide", json={"approve": True, "allow_chat": True})
    assert r.status_code == 400
    assert s.get_approval(aid)["status"] == "pending"  # nothing was approved either
    assert s.get_setting("shell_kinds:chat-a") is None


async def test_no_pass_in_careful_or_on_a_refusal(client):
    c, s = client
    aid = _card(s)
    r = await c.post(f"/api/approvals/{aid}/decide", json={"approve": False, "allow_chat": True})
    assert r.status_code == 200 and "chat_pass" not in r.json()
    approvals_mode.set_mode(s, approvals_mode.CAREFUL)
    other = _card(s, session_id="chat-b")
    r = await c.post(f"/api/approvals/{other}/decide", json={"approve": True, "allow_chat": True})
    assert r.status_code == 400
    assert s.get_setting("shell_kinds:chat-a") is None and s.get_setting("shell_kinds:chat-b") is None
    await asyncio.sleep(0.02)


async def test_the_terminal_key_cannot_give_a_pass(isolated_settings, tmp_path, monkeypatch):
    from odie import devices
    from odie.app.main import create_app
    monkeypatch.setenv("ODIE_PAIRING", "on")
    s = _store(tmp_path)
    terminal = devices.add_terminal(s)
    aid = _card(s)
    app = create_app(runner=_Runner(), store=s)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c, app.router.lifespan_context(app):
        c.cookies.set(devices.COOKIE, terminal)
        r = await c.post(f"/api/approvals/{aid}/decide", json={"approve": True, "allow_chat": True})
        assert r.status_code == 403
    assert s.get_approval(aid)["status"] == "pending" and s.get_setting("shell_kinds:chat-a") is None


async def test_an_erased_thread_loses_its_passes(tmp_path):
    from odie import personalities
    s = _store(tmp_path)
    g.grant_kind(s, "chat-2026-11-17-p", DELETES, NOW)
    g.grant_kind(s, "chat-2026-11-17-q", DELETES, NOW)
    personalities.erase_rows_of(s, "chat-2026-11-17-p")
    assert g.kinds_passed(s, "chat-2026-11-17-p", NOW) == set()
    assert g.kinds_passed(s, "chat-2026-11-17-q", NOW) == {DELETES}  # another thread keeps its own


def test_the_receipt_says_allowed_for_this_chat(tmp_path):
    from odie.app.runner import marked_chat_pass, steps_with_allowed
    s = _store(tmp_path)
    g.grant_kind(s, "chat-a", DELETES, NOW)
    check = g.make_check(s, clock=lambda: NOW)
    assert check(command="rm ~/work/old.txt", tool_context=_ctx(call_id="c7")) is False
    assert check(command="ls ~/work", tool_context=_ctx(call_id="c8")) is False  # Smart alone: no pass needed
    done = {"type": "tool_done", "tool": "run_shell", "id": "c7", "result": "", "allowed": {"by": "pass"}}
    assert marked_chat_pass(s, "chat-a", done)["allowed"] == {"by": "chat"}
    plain = {"type": "tool_done", "tool": "run_shell", "id": "c8", "result": "", "allowed": {"by": "pass"}}
    assert marked_chat_pass(s, "chat-a", plain)["allowed"] == {"by": "pass"}
    lines = [{"role": "odie", "inv": "e-1", "steps": [
        {"name": "run_shell", "id": "c7", "args": {}, "result": "", "allowed": {"by": "pass"}, "state": "done"},
        {"name": "run_shell", "id": "c8", "args": {}, "result": "", "allowed": {"by": "pass"}, "state": "done"}]}]
    steps = steps_with_allowed(s, "chat-a", lines)[0]["steps"]
    assert [step["allowed"] for step in steps] == [{"by": "chat"}, {"by": "pass"}]


async def test_no_pass_on_a_card_raised_right_after_reading_mail(client):
    """Like Careful's 30-minute pass, the chat pass is never offered on a card raised just after Odie read mail: the
    mail may have asked for the command."""
    c, s = client
    aid = s.create_approval("chat-a", "inv", "req-m", "run_shell", {"command": "rm ~/work/old.txt"}, summary="Run rm",
                            detail={"asks_because": DELETES, "chat_pass": True}, provenance=[{"from": "a@example.com"}],
                            risk="from_email", call_id="c1")
    r = await c.post(f"/api/approvals/{aid}/decide", json={"approve": True, "allow_chat": True})
    assert r.status_code == 400 and s.get_setting("shell_kinds:chat-a") is None
