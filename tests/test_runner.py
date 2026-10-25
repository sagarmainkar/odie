import asyncio
import importlib
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from odie.app.runner import NEW_CHAT, OdieRunner, event_to_sse, session_id_for
from odie.store.db import Store

IST = ZoneInfo("Asia/Kolkata")


def test_session_id_per_day():
    assert session_id_for(datetime(2026, 9, 30, 23, 59, tzinfo=IST)) == "chat-2026-09-30"
    assert session_id_for(datetime(2026, 10, 1, 0, 1, tzinfo=IST)) == "chat-2026-10-01"


def _ev(parts, partial=False, author="odie"):
    return SimpleNamespace(author=author, partial=partial, content=SimpleNamespace(parts=parts))


def _part(text=None, fc=None, fr=None):
    return SimpleNamespace(text=text, function_call=fc, function_response=fr)


def test_event_to_sse_maps_kinds():
    assert event_to_sse(_ev([_part(text="Hel")], partial=True)) == [{"type": "token", "text": "Hel"}]
    fc = SimpleNamespace(name="gmail_search", args={"query": "x"}, id="1")
    assert event_to_sse(_ev([_part(fc=fc)])) == [{"type": "tool_start", "tool": "gmail_search", "args": {"query": "x"}}]
    fr = SimpleNamespace(name="gmail_search", response={"result": "3 hits"}, id="1")
    assert event_to_sse(_ev([_part(fr=fr)])) == [{"type": "tool_done", "tool": "gmail_search"}]
    assert event_to_sse(_ev([_part(text="Final")])) == [{"type": "text", "text": "Final"}]
    assert event_to_sse(_ev([_part(text="you")], author="user")) == []


def test_event_to_sse_ignores_partial_tool_chunks():
    fc = SimpleNamespace(name="gmail_search", args={"query": "x"}, id="1")
    assert event_to_sse(_ev([_part(fc=fc)], partial=True)) == []
    fr = SimpleNamespace(name="gmail_search", response={"result": "ok"}, id="1")
    assert event_to_sse(_ev([_part(fr=fr)], partial=True)) == []


async def test_chat_stream_error_event(isolated_settings, monkeypatch, tmp_path):
    monkeypatch.setenv("LM_STUDIO_BASE_URL", "http://127.0.0.1:9")  # nothing listens
    import odie.config as c
    importlib.reload(c)
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    r = OdieRunner(s)
    events = [e async for e in r.chat("hi")]
    assert events[-1]["type"] == "error" and events[-1]["message"]
    await r.close()
    monkeypatch.delenv("LM_STUDIO_BASE_URL")
    importlib.reload(c)


async def test_chat_honours_explicit_session_id(isolated_settings, tmp_path):
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    r = OdieRunner(s)
    seen = {}

    async def fake_run(**kw):
        seen.update(kw)
        if False:
            yield None
    r.runner.run_async = fake_run
    events = [e async for e in r.chat("hi", session_id="eval-abc")]
    assert seen["session_id"] == "eval-abc" and events[-1]["type"] == "done"
    await r.close()


async def test_session_created_on_demand(isolated_settings, tmp_path):
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    r = OdieRunner(s)
    assert await r._ensure_session("chat-2099-01-01") == "chat-2099-01-01"
    assert (await r.history("2099-01-01"))["items"] == []
    await r.close()


async def test_memory_index_in_static_prompt_and_prefetch_in_trailer(isolated_settings, tmp_path):
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    r = OdieRunner(s)
    r.memory.update("Flight Seat Preference", "Asha prefers aisle seats.", topic="Identity", source="test")
    trailer = r._prepare_prompt("chat-2026-10-01", "book me a seat on the flight")
    assert "- Flight Seat Preference (" in r._current_prompt and "aisle" not in r._current_prompt
    assert "aisle" in trailer and trailer.startswith("[context: now ")
    assert r._prepare_prompt("chat-2026-10-01", "hello") .startswith("[context: now ") and "aisle" not in r._prepare_prompt("chat-2026-10-01", "hello")
    await r.close()


async def test_review_triggers_every_n_turns(isolated_settings, tmp_path, monkeypatch):
    import odie.app.runner as rmod
    calls = []

    async def fake_review(memory, turns, index, on_change=None, store=None):
        calls.append(len(turns))
    monkeypatch.setattr(rmod, "run_review", fake_review)
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    r = OdieRunner(s)
    r.review_every = 3
    for i in range(3):
        r._note_turn(f"u{i}", f"a{i}")
    await asyncio.sleep(0)
    assert calls == [3] and r._turns == []
    await r.close()


def test_history_shape_includes_timestamps():
    from odie.app.runner import events_to_history
    from types import SimpleNamespace as NS
    from google.genai import types
    evs = [
        NS(author="user", partial=False, timestamp=1790800000.0, content=types.Content(role="user", parts=[types.Part(text="hi\n\n[context: now 07:45 Thu 1 Oct]")])),
        NS(author="odie", partial=False, timestamp=1790800003.0, content=types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(id="1", name="now", args={}))])),
        NS(author="odie", partial=False, timestamp=1790800005.0, content=types.Content(role="model", parts=[types.Part(text="It is 07:45.")])),
    ]
    h = events_to_history(evs)
    assert h[0] == {"role": "user", "text": "hi", "tools": [], "ts": 1790800000.0, "images": []}
    assert h[1]["role"] == "odie" and h[1]["tools"] == ["now"] and h[1]["text"] == "It is 07:45." and h[1]["ts"] == 1790800003.0


async def test_a_memory_update_keeps_this_chats_system_prompt(isolated_settings, tmp_path):
    """A memory saved mid-chat doesn't rebuild the system prompt (that would change the start of every later request,
    so the model would read the whole chat again); the next message's [memories] block finds it, and the next chat's
    system prompt lists it."""
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    r = OdieRunner(s)
    r._prepare_prompt("chat-2026-10-01", "hello")
    before = r._current_prompt
    tool = next(t for t in r.agent.tools if getattr(t, "name", "") == "update_memory")
    tool.func(title="Dentist", content="Smile Dental, Baner.", topic="Health")
    trailer = r._prepare_prompt("chat-2026-10-01", "Which dentist do I go to?")
    assert r._current_prompt == before and "Dentist" not in before
    assert "Smile Dental" in trailer
    r._prepare_prompt("chat-2026-10-02", "hi")
    assert "Dentist" in r._current_prompt
    await r.close()


async def test_a_chats_limit_is_read_at_its_first_turn_and_kept(isolated_settings, tmp_path, monkeypatch):
    """No more rollover: a long chat stays one segment, and its limit (odie.agent.compaction) is pinned at its first
    turn, so switching models mid-chat never moves the cut."""
    import odie.app.runner as runner_mod
    sizes = {"deepseek-v4.1-flash:cloud": 1_048_576, "gemma-4-26b-a4b-it-qat": 70_000}

    async def fake_window(sel, transport=None):
        return sizes.get(sel.model)
    monkeypatch.setattr(runner_mod, "context_window", fake_window)
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    s.set_setting("model.chat", {"provider": "ollama", "model": "deepseek-v4.1-flash:cloud"})
    r = OdieRunner(s)
    assert await r._history_limit("chat-2026-10-15") == 300_000           # DeepSeek's 1M: 300k tokens, the cap
    s.set_setting("model.chat", {"provider": "lmstudio", "model": "gemma-4-26b-a4b-it-qat"})
    assert await r._history_limit("chat-2026-10-15") == 300_000           # the same chat keeps its limit
    assert await r._history_limit("chat-2026-10-16") == 52_500            # a new chat reads Gemma's 70k
    assert not hasattr(r, "maybe_rollover")
    await r.close()


async def test_an_unknown_window_is_asked_again_next_turn_not_pinned(isolated_settings, tmp_path, monkeypatch):
    """23 Oct: Ollama didn't say DeepSeek's window at the chat's first turn, so the chat kept the 50k 'can't say' limit
    all day and was trimmed hard, until a restart read 1M and the limit jumped to 300k. Now an unknown window is read
    again at the next turn, and pinned only once it is known."""
    import odie.app.runner as runner_mod
    answers = iter([None, None, 1_048_576, 70_000])

    async def fake_window(sel, transport=None):
        return next(answers)
    monkeypatch.setattr(runner_mod, "context_window", fake_window)
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    s.set_setting("model.chat", {"provider": "ollama", "model": "deepseek-v4.1-flash:cloud"})
    r = OdieRunner(s)
    assert await r._history_limit("chat-2026-10-23") == 50_000            # not known yet: the 'can't say' limit
    assert await r._history_limit("chat-2026-10-23") == 50_000            # asked again (None again)
    assert await r._history_limit("chat-2026-10-23") == 300_000           # known now, and pinned:
    assert await r._history_limit("chat-2026-10-23") == 300_000           # the 70,000 answer is never asked for
    sid = await r._ensure_session("chat-2026-10-23")
    monkeypatch.setattr(r, "current_session_id", lambda date: sid)
    assert (await r.context_usage("2026-10-23"))["limit"] == 300_000      # the ring shows this chat's limit
    await r.close()


async def test_new_chat_starts_a_clean_segment(isolated_settings, tmp_path):
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    r = OdieRunner(s)
    sid = await r._ensure_session(r.current_session_id("2026-10-01"))
    await r.post_message("something went badly here", session_id=sid)
    new = await r.new_chat("2026-10-01")
    assert new == "chat-2026-10-01-2" and r.current_session_id("2026-10-01") == new
    sess = await r.session_service.get_session(app_name=isolated_settings.app_name, user_id=isolated_settings.user_id, session_id=new)
    texts = [p.text for e in sess.events for p in (e.content.parts or []) if p.text]
    assert texts == [NEW_CHAT]  # nothing from the old segment is carried over
    usage = await r.context_usage("2026-10-01")
    assert usage["limit"] == r.history_limit and usage["used"] < 10  # the ring empties with a new chat
    h = (await r.history("2026-10-01"))["items"]
    assert h[0]["text"].startswith("something") and h[-1]["text"] == NEW_CHAT  # old turns still visible above
    await r.close()


async def test_context_tokens_use_the_models_real_count(isolated_settings, tmp_path):
    import time
    import uuid

    from google.adk.events import Event
    from google.genai import types
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    r = OdieRunner(s)
    sid = await r._ensure_session(r.current_session_id("2026-10-01"))
    await r.post_message("short", session_id=sid)
    assert (await r.context_usage("2026-10-01"))["used"] < 10  # no reply yet: the estimate
    sess = await r.session_service.get_session(app_name=isolated_settings.app_name, user_id=isolated_settings.user_id, session_id=sid)
    ev = Event(author="odie", invocation_id=f"t-{uuid.uuid4().hex[:6]}", timestamp=time.time(),
               content=types.Content(role="model", parts=[types.Part(text="a reply")]),
               usage_metadata=types.GenerateContentResponseUsageMetadata(prompt_token_count=14000, candidates_token_count=400, total_token_count=14400))
    await r.session_service.append_event(session=sess, event=ev)
    assert (await r.context_usage("2026-10-01"))["used"] == 14400  # what the model really read and wrote
    await r.close()


async def test_history_keeps_decided_approvals_in_place(isolated_settings, tmp_path):
    import time
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    r = OdieRunner(s)
    sid = await r._ensure_session(r.current_session_id("2026-10-01"))
    await r.post_message("before the command", session_id=sid)
    time.sleep(0.01)
    aid = s.create_approval(sid, "inv", "req", "run_shell", {"command": "ls"}, summary="Run ls", detail={}, provenance=[])
    s.decide_approval(aid, True)
    time.sleep(0.01)
    await r.post_message("after the command", session_id=sid)
    s.create_approval("chat-2026-09-30", "inv", "req2", "run_shell", {}, summary="other day", detail={}, provenance=[])
    items = (await r.history("2026-10-01"))["items"]
    assert [i["role"] for i in items] == ["odie", "approval", "odie"]
    assert items[1]["approval"]["id"] == aid and items[1]["approval"]["status"] == "approved"
    assert items[1]["approval"]["args"] == {"command": "ls"}  # parsed like /api/approvals
    await r.close()


def test_history_hides_confirmation_pseudo_tool():
    from odie.app.runner import events_to_history
    from types import SimpleNamespace as NS
    from google.genai import types
    evs = [NS(author="odie", partial=False, timestamp=1.0, content=types.Content(role="model", parts=[
        types.Part(function_call=types.FunctionCall(id="1", name="gmail_search", args={"query": "x"})),
        types.Part(function_call=types.FunctionCall(id="2", name="adk_request_confirmation", args={}))]))]
    assert events_to_history(evs)[0]["tools"] == ["gmail_search"]


async def test_the_limit_follows_the_chosen_models_context(isolated_settings, tmp_path, monkeypatch):
    import odie.app.runner as runner_mod
    sizes = {"glm-5.3:cloud": 1_048_576, "qwen3.8-27b-splash": 75_000}

    async def fake_window(sel, transport=None):
        return sizes.get(sel.model)
    monkeypatch.setattr(runner_mod, "context_window", fake_window)
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    r = OdieRunner(s)
    s.set_setting("model.chat", {"provider": "ollama", "model": "glm-5.3:cloud"})
    assert (await r.context_usage("2026-10-01"))["limit"] == 300_000  # 1M window, capped
    s.set_setting("model.chat", {"provider": "lmstudio", "model": "qwen3.8-27b-splash"})
    assert (await r.context_usage("2026-10-01"))["limit"] == 56_250  # 3/4 of 75k
    await r.close()


async def test_lm_studio_is_rechecked_because_its_loaded_size_can_change(isolated_settings, tmp_path, monkeypatch):
    import odie.app.runner as runner_mod
    answers = iter([262_144, 32_000])  # first: not loaded yet (reports the maximum); then: loaded with 32k

    async def fake_window(sel, transport=None):
        return next(answers)
    monkeypatch.setattr(runner_mod, "context_window", fake_window)
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    s.set_setting("model.chat", {"provider": "lmstudio", "model": "gemma-4-26b-a4b-it-qat"})
    r = OdieRunner(s)
    assert await r.refresh_history_limit() == 196_608
    assert await r.refresh_history_limit() == 24_000
    await r.close()


async def test_load_plugins_swaps_in_skills_and_servers(isolated_settings, tmp_path):
    import sys
    from pathlib import Path

    from google.adk.tools.skill_toolset import SkillToolset

    from odie.plugins import mcp as m
    tester = {"command": sys.executable, "args": [str(Path(__file__).parent / "fixtures" / "mcp_tester.py")]}
    m.write_config({"tester": tester, "pinned": {**tester, "alwaysOn": True}})
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    r = OdieRunner(s)
    try:
        p = await r.load_plugins()
        assert {e.name: e.status for e in p["servers"]} == {"tester": "ok", "pinned": "error"}  # pinned clashes with tester
        sts = [t for t in r.agent.tools if isinstance(t, SkillToolset)]
        assert len(sts) == 1 and "mcp-tester" in sts[0]._skills and "stocks" in sts[0]._skills
        first = r._plugin_toolsets[:]
        await r.load_plugins()  # reload: still one SkillToolset, and the old server connection was closed
        assert len([t for t in r.agent.tools if isinstance(t, SkillToolset)]) == 1
        assert r._plugin_toolsets and r._plugin_toolsets[0] is not first[0]
    finally:
        await r.close()


async def _plugin_runner(tmp_path):
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    return OdieRunner(s)


async def test_reloads_run_one_at_a_time_and_the_latest_config_wins(isolated_settings, tmp_path):
    import asyncio
    import sys
    from pathlib import Path

    from odie.plugins import mcp as m
    tester = {"command": sys.executable, "args": [str(Path(__file__).parent / "fixtures" / "mcp_tester.py")]}
    m.write_config({"tester": tester})
    r = await _plugin_runner(tmp_path)
    r.close_grace = 0
    try:
        first = asyncio.create_task(r.load_plugins())
        await asyncio.sleep(0.05)
        m.write_config({"tester": {**tester, "enabled": False}})
        await asyncio.gather(first, r.load_plugins())
        assert {e.name: e.status for e in r.plugins["servers"]} == {"tester": "disabled"}
    finally:
        await r.close()


async def test_old_connections_close_after_a_grace_period(isolated_settings, tmp_path):
    import asyncio
    import sys
    from pathlib import Path

    from odie.plugins import mcp as m
    m.write_config({"tester": {"command": sys.executable, "args": [str(Path(__file__).parent / "fixtures" / "mcp_tester.py")]}})
    r = await _plugin_runner(tmp_path)
    r.close_grace = 0.3
    try:
        await r.load_plugins()
        old = r._plugin_toolsets[0]
        closed = []
        orig = old.close

        async def spy():
            closed.append(True)
            await orig()
        old.close = spy
        await r.load_plugins()
        assert closed == []  # a turn still using the old list keeps working
        await asyncio.sleep(0.6)
        assert closed == [True]
    finally:
        await r.close()


async def test_a_failed_server_is_retried_in_the_background(isolated_settings, tmp_path, monkeypatch):
    import asyncio

    from odie.plugins import mcp as m
    m.write_config({"tester": {"url": "http://127.0.0.1:9/mcp"}})
    r = await _plugin_runner(tmp_path)
    r.retry_every = 0.2
    calls = []
    real = r.load_plugins

    async def counting():
        calls.append(1)
        return await real()
    try:
        await r.load_plugins()
        assert r.plugins["servers"][0].status == "failed"
        monkeypatch.setattr(r, "load_plugins", counting)
        await asyncio.sleep(0.7)
        assert len(calls) >= 1  # it tried again by itself
    finally:
        await r.close()
