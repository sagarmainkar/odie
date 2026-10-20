"""Setup's screen-driven steps: every step shows its own question, its choices (with what each needs: a key form, an
app form, a folder), and Skip. A choice made on the screen is saved by code, never by the model, so the checklist only
says what is really saved; Odie's next line is written by code too. Setup finishes itself when nothing is left, with a
summary of what was saved. The real home is never touched: ODIE_SETUP_HOME is tmp_path."""
import json

import httpx
import pytest

from odie import persona, profile
from odie.setup import chat, panels, state
from odie.store.db import Store


@pytest.fixture
def store(isolated_settings, tmp_path, monkeypatch):
    monkeypatch.setenv("ODIE_SETUP_HOME", str(tmp_path / "home"))
    (tmp_path / "home" / "Documents").mkdir(parents=True)
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    s.set_setting("model.chat", {"provider": "ollama", "model": "glm-test"})
    state.mark(s, "brain", "done")
    return s


def no_models():
    """No LM Studio or Ollama on this computer, and no model is ever asked."""
    def handler(request):
        if request.url.path.endswith("/chat/completions"):
            raise AssertionError("a choice on the screen never calls the model")
        return httpx.Response(404)
    return httpx.MockTransport(handler)


def ids(p):
    return [c["id"] for c in p["choices"]]


async def through_names(store):
    return await chat.choose(store, "names", "save", {"user_name": "Asha", "assistant_name": "Odie"}, transport=no_models())


async def test_every_step_has_a_question_choices_and_skip(store):
    await through_names(store)
    seen = {}
    for step in ("vault", "embeddings", "photos", "search", "voice", "apps", "phone"):
        p = await panels.panel(store, step, transport=no_models())
        assert p["step"] == step and p["question"] and p["skip"], step
        if step not in ("embeddings", "phone") or p["choices"]:  # no phone address yet: only Skip
            assert p["choices"] and all(c["label"] for c in p["choices"]), step
        seen[step] = p
    assert "new" in ids(seen["vault"]) and "elsewhere" in ids(seen["vault"])
    assert ids(seen["search"]) == ["tavily", "brave", "ollama"] and "free search" in seen["search"]["skip"]  # Skip is the free one
    assert ids(seen["voice"]) == ["kokoro", "openai"] and ids(seen["apps"]) == ["zapier", "composio"]
    names = await panels.panel(store, "names", transport=no_models())
    assert names["skip"] is None and [f["id"] for f in names["fields"]] == ["user_name", "assistant_name"]


async def test_the_embeddings_question_says_what_it_is(store):
    p = await panels.panel(store, "embeddings", transport=no_models())
    words = (p["question"] + " " + p["explain"]).lower()
    assert "meaning" in words and "embedding model" in words and "separate from the chat model" in words
    openai = next(c for c in p["choices"] if c["id"] == "openai:text-embedding-3-small")
    assert openai["needs"] == {"type": "key", "provider": "openai", "kind": "provider", "label": "OpenAI", "note": openai["needs"]["note"]}


async def test_the_zapier_form_says_what_to_do_there(store):
    p = await panels.panel(store, "apps", transport=no_models())
    zap = next(c for c in p["choices"] if c["id"] == "zapier")["needs"]
    assert zap["type"] == "app" and zap["app"] == "zapier"
    steps = " ".join(zap["steps"]).lower()
    assert "mcp.zapier.com" in steps and "other" in steps and "gmail" in steps and "link" in steps and "code" in steps
    assert "code" in zap["key_label"].lower()


async def test_a_choice_on_the_screen_is_saved_by_code_and_odie_asks_the_next(store):
    out = await through_names(store)
    assert profile.get(store)["user_name"] == "Asha" and persona.get(store)["name"] == "Odie"
    assert out["state"]["steps"]["names"] == "done" and out["state"]["current"] == "vault"
    assert out["reply"].startswith("✓") and out["panel"]["step"] == "vault" and out["panel"]["question"] in out["reply"]
    out = await chat.choose(store, "voice", "kokoro", transport=no_models())
    assert out["state"]["steps"]["voice"] == "done"
    from odie import voice
    assert voice.get_tts(store)[0] == "kokoro"


async def test_a_choice_that_fails_says_why_and_saves_nothing(store):
    await through_names(store)
    out = await chat.choose(store, "voice", "openai", transport=no_models())  # no OpenAI key
    assert out["error"] and "key" in out["error"].lower() and out["state"]["steps"]["voice"] == "todo"
    out = await chat.choose(store, "search", "tavily", transport=no_models())  # chosen before its key was saved
    assert out["error"] and out["state"]["steps"]["search"] == "todo"
    out = await chat.choose(store, "apps", "zapier", transport=no_models())  # nothing connected yet
    assert out["error"] and out["state"]["steps"]["apps"] == "todo"
    with pytest.raises(ValueError):
        await chat.choose(store, "voice", "a-voice-that-isnt-there", transport=no_models())
    with pytest.raises(ValueError):
        await chat.choose(store, "brain", "x", transport=no_models())


async def test_skipping_is_a_choice_too(store):
    await through_names(store)
    out = await chat.choose(store, "voice", "skip", transport=no_models())
    assert out["state"]["steps"]["voice"] == "skipped" and "Settings" in out["reply"]
    with pytest.raises(ValueError):
        await chat.choose(store, "names", "skip", transport=no_models())


async def test_setup_finishes_itself_with_a_summary_of_what_was_saved(store):
    await through_names(store)
    await chat.choose(store, "vault", "new", transport=no_models())
    for step in ("embeddings", "photos", "apps", "phone"):
        await chat.choose(store, step, "skip", transport=no_models())
    await chat.choose(store, "search", "skip", transport=no_models())
    out = await chat.choose(store, "voice", "kokoro", transport=no_models())
    assert out["state"]["done"] is True and out["panel"] is None
    reply = out["reply"]
    assert "Asha" in reply and "Odie Vault" in reply and "Kokoro" in reply and "skipped" in reply.lower()
    assert "Search by meaning: skipped" in reply


async def test_the_model_cant_finish_with_steps_left(store):
    from odie.setup import tools
    await through_names(store)
    out = await tools.run("finish_setup", {}, store)
    assert "error" in out and "vault" in out["error"] and state.is_done(store) is False


async def test_the_phone_step_knows_about_tailscale(store, monkeypatch):
    from odie import config
    import dataclasses
    monkeypatch.setattr(panels, "tailscale_installed", lambda: False)
    p = await panels.panel(store, "phone", transport=no_models())
    assert p["phone"]["tailscale"] is False and "tailscale.com/download" in json.dumps(p)
    monkeypatch.setattr(panels, "tailscale_installed", lambda: True)
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, public_url="http://localhost:8000"))
    p = await panels.panel(store, "phone", transport=no_models())  # the default address is this computer's own
    assert p["phone"]["serving"] is False and p["phone"]["address"] == "" and p["choices"] == []
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, public_url="https://mac.example.ts.net"))
    p = await panels.panel(store, "phone", transport=no_models())
    assert p["phone"]["address"] == "https://mac.example.ts.net" and p["phone"]["serving"] is True
    assert [c["id"] for c in p["choices"]] == ["paired"] and len(p["phone"]["steps"]) == 3


async def test_paired_means_a_phone_really_paired(store, monkeypatch):
    import dataclasses

    from odie import config, devices
    monkeypatch.setenv("ODIE_PAIRING", "on")
    monkeypatch.setattr(panels, "tailscale_installed", lambda: True)
    monkeypatch.setattr(config, "settings", dataclasses.replace(config.settings, public_url="https://mac.example.ts.net"))
    await through_names(store)
    devices.add_device(store, "This Mac")  # the Mac that runs setup; no phone yet
    out = await chat.choose(store, "phone", "paired", transport=no_models())
    assert out["error"] and "scan" in out["error"].lower() and out["state"]["steps"]["phone"] == "todo"


async def test_tool_calls_are_kept_for_the_transcript_but_never_shown(store):
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        if len(seen) == 1:
            return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
                {"id": "c1", "type": "function", "function": {"name": "set_voice", "arguments": json.dumps({"engine": "kokoro"})}}]}}]})
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "Kokoro it is."}}]})
    await chat.turn(store, "kokoro please", transport=httpx.MockTransport(handler))
    thread = state.get(store)["thread"]
    logs = [m for m in thread if m["role"] == "log"]
    assert logs and "set_voice" in logs[0]["text"] and "kokoro" in logs[0]["text"]
    assert all(m["role"] != "log" for m in chat.public_state(store)["thread"])
    await chat.turn(store, "thanks", transport=httpx.MockTransport(handler))
    assert all(m["role"] in ("system", "user", "assistant", "tool") for m in seen[-1]["messages"])
    assert not any("set_voice(" in str(m.get("content")) for m in seen[-1]["messages"])


async def test_the_model_is_told_the_steps_real_choices(store):
    await through_names(store)
    prompt = await chat.prompt_for(store, transport=no_models())
    assert "Current step: vault" in prompt and "new" in prompt and "Never say a step is saved" in prompt


async def test_choose_route(isolated_settings, tmp_path, monkeypatch):
    from odie.app.main import create_app
    from tests.test_api import FakeRunner
    monkeypatch.setenv("ODIE_SETUP_HOME", str(tmp_path / "home"))
    s = Store(tmp_path / "a.db")
    s.init_schema()
    state.mark(s, "brain", "done")
    app = create_app(runner=FakeRunner(), store=s)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        async with app.router.lifespan_context(app):
            got = (await c.get("/api/setup")).json()
            assert got["panel"]["step"] == "names"
            r = await c.post("/api/setup/choose", json={"step": "names", "choice": "save", "value": {"user_name": "Asha"}})
            assert r.status_code == 200 and r.json()["state"]["current"] == "vault"
            assert (await c.post("/api/setup/choose", json={"step": "voice", "choice": "nope"})).status_code == 422


async def test_the_old_finish_route_refuses_with_steps_left(isolated_settings, tmp_path, monkeypatch):
    from odie.app.main import create_app
    from tests.test_api import FakeRunner
    s = Store(tmp_path / "a.db")
    s.init_schema()
    state.mark(s, "brain", "done")
    app = create_app(runner=FakeRunner(), store=s)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        async with app.router.lifespan_context(app):
            r = await c.post("/api/setup/finish")
            assert r.status_code == 422 and state.is_done(s) is False


async def test_failing_names_are_never_skipped(store):
    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": None, "tool_calls": [
            {"id": "c1", "type": "function", "function": {"name": "set_names", "arguments": json.dumps({"user_name": ""})}}]}}]})
    for _ in range(4):
        await chat.turn(store, "call me", transport=httpx.MockTransport(handler))
    assert state.get(store)["steps"]["names"] == "todo" and state.is_done(store) is False


async def test_paired_is_only_a_choice_when_the_phone_step_is_ready(store, monkeypatch):
    monkeypatch.setattr(panels, "tailscale_installed", lambda: False)
    await through_names(store)
    with pytest.raises(ValueError):
        await chat.choose(store, "phone", "paired", transport=no_models())
    assert state.get(store)["steps"]["phone"] == "todo"


async def test_a_done_step_isnt_skipped_afterwards(store):
    await through_names(store)
    await chat.choose(store, "voice", "kokoro", transport=no_models())
    with pytest.raises(ValueError):
        await chat.choose(store, "voice", "skip", transport=no_models())
    assert state.get(store)["steps"]["voice"] == "done"


def test_the_transcript_masks_every_key_shape():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("conversation", Path(__file__).parent.parent / "scripts" / "conversation.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    secrets = ["sk-proj-AbCdEf0123456789AbCdEf0123456789", "AIzaSyA-bcdEFGhijk_lmnoPQRstu-vwxYZ01234", "ck_AbCdEf0123456789xy",
               "tvly-dev-AbCdEf0123456789", "BSAabcdefGHIJKLmnop0123456", "https://mcp.zapier.com/api/mcp/s/Zx9-Kq2LmN8pQr4StUv6WxYz1AbC/mcp",
               "https://x.example.com/hook?token=abc123def456"]
    out = mod.mask("keys: " + " , ".join(secrets) + " and the vault /Users/asha/Documents/Odie Vault")
    assert not any(s in out for s in secrets), out
    assert "/Users/asha/Documents/Odie Vault" in out and "https://mcp.zapier.com/api/v1/connect" in mod.mask("https://mcp.zapier.com/api/v1/connect")


async def test_settings_can_open_a_steps_panel_after_setup(isolated_settings, tmp_path, monkeypatch):
    from odie.app.main import create_app
    from tests.test_api import FakeRunner
    monkeypatch.setenv("ODIE_SETUP_HOME", str(tmp_path / "home"))
    (tmp_path / "home" / "Documents").mkdir(parents=True)
    s = Store(tmp_path / "a.db")
    s.init_schema()
    state.mark(s, "brain", "done")
    await chat.choose(s, "names", "save", {"user_name": "Asha"}, transport=no_models())
    for step in ("vault", "photos", "search", "voice", "apps", "phone"):
        await chat.choose(s, step, "skip", transport=no_models())
    assert state.is_done(s)
    app = create_app(runner=FakeRunner(), store=s)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        async with app.router.lifespan_context(app):
            p = (await c.get("/api/setup/panel/vault")).json()
            assert p["step"] == "vault" and "new" in [x["id"] for x in p["choices"]]
            r = (await c.post("/api/setup/choose", json={"step": "vault", "choice": "new"})).json()
            assert r["state"]["steps"]["vault"] == "done" and r["state"]["done"] is True  # setup stays done
            assert (await c.get("/api/setup/panel/brain")).status_code == 404


async def test_no_search_is_recommended_for_now(store):
    p = await panels.panel(store, "search", transport=no_models())
    assert not any(c["recommended"] for c in p["choices"])


async def test_nothing_is_recommended_for_now(store):
    await through_names(store)
    for step in ("vault", "embeddings", "photos", "search", "voice", "apps", "phone"):
        p = await panels.panel(store, step, transport=no_models())
        assert not any(c["recommended"] for c in p["choices"]), step


async def test_an_install_that_was_set_up_can_leave_setup_again(store):
    await through_names(store)
    for step in ("vault", "photos", "search", "voice", "apps", "phone"):
        await chat.choose(store, step, "skip", transport=no_models())
    assert state.is_done(store)
    state.restart(store)  # Settings → Run setup again
    assert state.is_done(store) is False and chat.public_state(store)["can_leave"] is True
    state.leave(store)
    assert state.is_done(store) is True


async def test_a_new_install_cant_leave_setup(store):
    assert chat.public_state(store)["can_leave"] is False
    with pytest.raises(ValueError):
        state.leave(store)


async def test_an_install_with_chats_can_leave_even_if_reset_earlier(store, monkeypatch):
    monkeypatch.setattr(store, "has_chats", lambda: True)
    state.restart(store)  # reset before this was remembered
    store.set_setting("setup", {**state.get(store), "was_done": False})
    assert chat.public_state(store)["can_leave"] is True


async def test_leave_route(isolated_settings, tmp_path, monkeypatch):
    from odie.app.main import create_app
    from tests.test_api import FakeRunner
    s = Store(tmp_path / "a.db")
    s.init_schema()
    app = create_app(runner=FakeRunner(), store=s)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        async with app.router.lifespan_context(app):
            assert (await c.post("/api/setup/leave")).status_code == 422  # never set up: setup can't be left
            s.set_setting("setup", {**state.get(s), "was_done": True})
            r = await c.post("/api/setup/leave")
            assert r.status_code == 200 and r.json()["done"] is True


async def test_setup_again_brings_back_only_the_skipped_steps(store):
    await through_names(store)
    await chat.choose(store, "voice", "kokoro", transport=no_models())
    for step in ("vault", "photos", "search", "apps", "phone"):
        await chat.choose(store, step, "skip", transport=no_models())
    assert state.is_done(store)
    state.restart(store)
    s = state.get(store)["steps"]
    assert s["brain"] == s["names"] == s["voice"] == "done"  # what's set stays done
    assert s["vault"] == s["embeddings"] == s["search"] == s["apps"] == s["phone"] == "todo"  # what was skipped comes back
    assert state.current(state.get(store)) == "vault"
    for step in ("vault", "photos", "search", "apps", "phone"):
        await chat.choose(store, step, "skip", transport=no_models())
    assert state.is_done(store)  # done again once the skipped ones are


async def test_setup_again_with_nothing_skipped_goes_through_everything(store):
    await through_names(store)
    for step, choice in (("vault", "new"), ("voice", "kokoro")):
        await chat.choose(store, step, choice, transport=no_models())
    for step in ("embeddings", "search", "apps", "phone"):
        state.mark(store, step, "done")
    state.restart(store)
    s = state.get(store)["steps"]
    assert s["brain"] == "done" and s["names"] == "todo" and s["voice"] == "todo"  # all again, the brain kept


def test_settings_says_what_setup_again_will_do(store):
    state.mark(store, "brain", "done")
    for step in ("names", "voice"):
        state.mark(store, step, "done")
    for step in ("vault", "embeddings", "search", "apps", "phone"):
        state.mark(store, step, "skipped")
    assert chat.public_state(store)["skipped"] == ["vault", "embeddings", "search", "apps", "phone"]


async def test_the_voice_step_offers_only_openai_where_the_local_voice_cannot_run(store, monkeypatch):
    monkeypatch.setenv("ODIE_VOICE", "off")  # an Intel Mac
    await through_names(store)
    p = await panels.panel(store, "voice", transport=no_models())
    assert ids(p) == ["openai"]
    with pytest.raises(ValueError, match="isn't a choice"):  # Kokoro is not a choice here, like any unknown one
        await chat.choose(store, "voice", "kokoro", transport=no_models())
    assert state.get(store)["steps"]["voice"] == "todo"
