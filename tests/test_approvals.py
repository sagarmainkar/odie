import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from odie.app.main import create_app
from odie.app.runner import OdieRunner
from odie.store.db import Store


def _store(tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


def test_store_approval_lifecycle(tmp_path):
    s = _store(tmp_path)
    aid = s.create_approval("chat-2026-10-01", "inv1", "req1", "gmail_send_draft", {"draft_id": "d1"},
                            summary="Send to Priya Nair · Re: 1:1", detail={"body": "Thursday works."}, provenance=[{"kind": "mail", "from": "priya@acme.example"}])
    p = s.pending_approvals()
    assert [r["id"] for r in p] == [aid] and json.loads(p[0]["detail_json"])["body"] == "Thursday works."
    assert s.decide_approval(aid, True) is True and s.decide_approval(aid, True) is False  # second tap is a no-op
    assert s.get_approval(aid)["status"] == "approved" and s.pending_approvals() == []
    old = s.create_approval("chat-2026-09-30", "inv0", "req0", "gmail_trash", {"message_id": "m1"}, summary="Trash", detail={}, provenance=[])
    s.execute("update approvals set created_at='2026-09-29T00:00:00.000Z' where id=?", (old,))
    expired = s.expire_approvals("2026-09-30T01:00:00.000Z")
    assert [r["id"] for r in expired] == [old] and s.get_approval(old)["status"] == "expired"


async def test_chat_stream_emits_approval_and_stores_row(isolated_settings, tmp_path):
    from google.genai import types
    s = _store(tmp_path)
    r = OdieRunner(s)
    sid = r.current_session_id("2026-10-01")
    fc = types.FunctionCall(id="req-1", name="adk_request_confirmation", args={
        "originalFunctionCall": {"id": "c1", "name": "gmail_send_draft", "args": {"draft_id": "d1"}}, "toolConfirmation": {"hint": ""}})
    ev = SimpleNamespace(author="odie", partial=False, invocation_id="inv-1", content=types.Content(role="model", parts=[types.Part(function_call=fc)]))

    async def fake_run(**kw):
        yield ev
    r.runner.run_async = fake_run
    live = []

    async def listen():
        async for e in r.bus.subscribe():
            live.append(e)
    t = asyncio.create_task(listen())
    await asyncio.sleep(0)
    out = [e async for e in r.chat("send it", session_id=sid)]
    await asyncio.sleep(0.01)
    t.cancel()
    kinds = [e["type"] for e in out]
    assert "approval" in kinds and kinds[-1] == "done"
    # also live: the app may have been in the background with the stream cut when the card was raised
    assert [e["type"] for e in live if e["type"] == "approval"] == ["approval"]
    card = next(e for e in out if e["type"] == "approval")
    row = s.get_approval(card["id"])
    assert row["status"] == "pending" and row["invocation_id"] == "inv-1" and row["request_id"] == "req-1" and row["session_id"] == sid
    await r.close()


async def test_resume_approval_replays_and_streams(isolated_settings, tmp_path):
    from google.genai import types
    s = _store(tmp_path)
    r = OdieRunner(s)
    aid = s.create_approval("chat-2026-10-01", "inv-1", "req-1", "gmail_send_draft", {"draft_id": "d1"}, summary="Send", detail={}, provenance=[])
    seen = {}

    async def fake_run(**kw):
        seen.update(kw)
        yield SimpleNamespace(author="odie", partial=False, invocation_id="inv-1", content=types.Content(role="model", parts=[types.Part(text="Sent it.")]))
    r.runner.run_async = fake_run
    got = []

    async def listen():
        async for e in r.bus.subscribe():
            got.append(e)
            if e["type"] == "approval_done":
                break
    t = asyncio.create_task(listen())
    await asyncio.sleep(0)
    res = await r.resume_approval(aid, True)
    await asyncio.wait_for(t, 2)
    assert seen["invocation_id"] == "inv-1" and seen["session_id"] == "chat-2026-10-01"
    fr = seen["new_message"].parts[0].function_response
    assert fr.id == "req-1" and fr.name == "adk_request_confirmation" and fr.response == {"confirmed": True}
    assert res["text"] == "Sent it." and s.get_approval(aid)["status"] == "approved" and s.get_approval(aid)["result_text"] == "Sent it."
    assert [e["type"] for e in got][-2:] == ["message", "approval_done"]
    assert got[-2]["kind"] == "reply"  # the app shows it as her reply, not as a reminder
    assert (await r.resume_approval(aid, True))["error"]  # already decided
    await r.close()


class FakeRunner:
    bus = None

    async def chat(self, text, thinking=False, session_id=None):
        if False:
            yield None

    async def history(self, date, limit=None, before=None):
        return {"items": [], "total": 0, "start": 0}

    async def resume_approval(self, aid, approve):
        FakeRunner.decided = (aid, approve)
        return {"text": "ok"}

    async def post_message(self, text, session_id=None):
        pass

    async def close(self):
        pass


@pytest.fixture
async def client(isolated_settings, tmp_path):
    s = _store(tmp_path)
    app = create_app(runner=FakeRunner(), store=s)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        async with app.router.lifespan_context(app):
            yield c, s


async def test_approval_routes(client):
    c, s = client
    aid = s.create_approval("chat-x", "inv", "req", "gmail_trash", {"message_id": "m1"}, summary="Trash newsletter", detail={}, provenance=[])
    assert (await c.get("/api/approvals")).json()[0]["id"] == aid
    r = await c.post(f"/api/approvals/{aid}/decide", json={"approve": False})
    await asyncio.sleep(0.05)  # the resume runs in its own task
    assert r.status_code == 200 and FakeRunner.decided == (aid, False)
    assert (await c.post("/api/approvals/999/decide", json={"approve": True})).status_code == 404


async def test_run_shell_tool_is_gated_and_bounded(tmp_path):
    from odie.agent.tools.shell import make_shell_tool
    tool = make_shell_tool(home=tmp_path)
    assert tool._require_confirmation is True
    out = await tool.func(command="printf 'hello'", cwd=str(tmp_path))
    assert out.strip().endswith("hello")
    out = await tool.func(command="pwd", cwd="/etc")
    assert "outside" in out.lower()
    big = await tool.func(command="python3 -c \"print('x'*20000)\"", cwd=str(tmp_path))
    assert len(big) <= 8300 and big.endswith("…")


async def test_decide_returns_at_once_while_the_turn_resumes_in_the_background(isolated_settings, tmp_path):
    import asyncio
    import time
    done = []

    class SlowRunner(FakeRunner):
        async def resume_approval(self, aid, approve):
            await asyncio.sleep(0.5)  # the resumed turn can take minutes for real
            done.append(aid)
            return {"text": "ok"}

    s = _store(tmp_path)
    app = create_app(runner=SlowRunner(), store=s)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        async with app.router.lifespan_context(app):
            aid = s.create_approval("chat-x", "inv", "req", "run_shell", {"command": "ls"}, summary="Run ls", detail={}, provenance=[])
            t = time.monotonic()
            r = await c.post(f"/api/approvals/{aid}/decide", json={"approve": True})
            assert r.status_code == 200 and r.json()["status"] == "approved" and time.monotonic() - t < 0.3
            for _ in range(50):
                if done:
                    break
                await asyncio.sleep(0.02)
            assert done == [aid]  # and the turn still resumed
            s.decide_approval(aid, True)
            assert (await c.post(f"/api/approvals/{aid}/decide", json={"approve": True})).status_code == 409


async def test_allow_for_30_min_grants_the_conversation(client):
    from datetime import datetime

    from odie.agent import shell_grant
    c, s = client
    aid = s.create_approval("chat-z", "inv", "req", "run_shell", {"command": "ls"}, summary="Run ls", detail={}, provenance=[])
    r = await c.post(f"/api/approvals/{aid}/decide", json={"approve": True, "allow_minutes": 30})
    assert r.status_code == 200 and r.json()["allowed_until"]
    assert shell_grant.active(s, "chat-z", datetime.now())
    other = s.create_approval("chat-z2", "inv", "req2", "gmail_trash", {}, summary="Trash", detail={}, provenance=[])
    r = await c.post(f"/api/approvals/{other}/decide", json={"approve": True, "allow_minutes": 30})
    assert "allowed_until" not in r.json() and not shell_grant.active(s, "chat-z2", datetime.now())  # shell only


async def test_allow_for_30_min_approves_one_card_only(isolated_settings, tmp_path):
    """One tap = one card: other run_shell cards already waiting in the chat (parallel tool calls, raised before the pass
    existed) stay pending, whatever their command. The pass covers only commands asked from now on."""
    import asyncio
    decided = []

    class Recorder(FakeRunner):
        async def resume_approval(self, aid, approve):
            s.decide_approval(aid, approve)
            decided.append((aid, approve))
            return {"text": "ok"}

    s = _store(tmp_path)
    app = create_app(runner=Recorder(), store=s)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        async with app.router.lifespan_context(app):
            mk = lambda sid, req, cmd: s.create_approval(sid, "inv", req, "run_shell", {"command": cmd}, summary=f"Run {cmd}",
                                                         detail={"command": cmd}, provenance=[])
            first, second = mk("chat-p", "r1", "df -h"), mk("chat-p", "r2", "du -sh ~/Downloads/* | sort -h | tail -5")
            hidden, elsewhere = mk("chat-p", "r3", "echo aWQgPiAvdG1wL3g= | base64 -d | zsh"), mk("chat-q", "r4", "ls")
            r = await c.post(f"/api/approvals/{first}/decide", json={"approve": True, "allow_minutes": 30})
            assert r.json()["allowed_until"] and "also_approved" not in r.json()
            for _ in range(50):
                if decided:
                    break
                await asyncio.sleep(0.02)
            await asyncio.sleep(0.05)
            assert decided == [(first, True)]  # the tapped card, and nothing the user didn't read
            for other in (second, hidden, elsewhere):
                assert s.get_approval(other)["status"] == "pending"
