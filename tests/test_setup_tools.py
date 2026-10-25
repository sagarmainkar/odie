"""Setup's pieces: the checklist state, the key catcher, and the setup-only tools (names, vault, embeddings, search,
voice, apps, phone, key cards, skip and finish). The real home is never touched: ODIE_SETUP_HOME is tmp_path."""
import json
from pathlib import Path

import httpx
import pytest

from odie.setup import keys, state, tools
from odie.store.db import Store


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    return s


@pytest.fixture
def home(tmp_path, monkeypatch):
    h = tmp_path / "home"
    (h / "Documents").mkdir(parents=True)
    monkeypatch.setenv("ODIE_SETUP_HOME", str(h))
    return h


@pytest.mark.parametrize("text", [
    "Call me Asha", "My vault is at /Users/asha/Documents/Notes", "https://example.com/some/long/path?with=query&x=1",
    "supercalifragilisticexpialidocious and antidisestablishmentarianism", "commit 9f86d081884c7d659a2feaa0c55ad015a3bf4f1b",
    "Use the sk model please", "my email is asha@example.com", "see https://example.com/blog/2026-10-06-meeting-notes",
    "docs at https://github.com/modelcontextprotocol/servers/tree/main/src",
    "https://docs.google.com/document/d/1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789/edit",
    "see https://github.com/x/y/commit/9f86d081884c7d659a2feaa0c55ad015a3bf4f1b",
    "https://www.notion.so/My-Page-1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d", "https://example.com/Project-Alpha-2026-v2-server/",
])
def test_ordinary_text_is_not_a_key(text):
    assert keys.key_in(text) is None


@pytest.mark.parametrize("text, provider", [
    ("here: sk-proj-AbCdEf0123456789AbCdEf0123456789", "openai"), ("sk-ant-api03-AbCdEf0123456789AbCdEf01", "anthropic"),
    ("tvly-dev-AbCdEf0123456789xyz", "tavily"), ("AIzaSyAbCdEf0123456789AbCdEf012345678", "gemini"),
    ("ck_AbCdEf0123456789AbCd", "composio"), ("BSAAbCdEf0123456789AbCdEf01", "brave"),
    ("Authorization: Bearer abcdefghijklmnop0123456789", "bearer"), ("x7Kq9LmN2pR4sT6vW8yZ0aB3cD5eF7gH9jK", "unknown"),
    ("my zapier link https://mcp.zapier.com/api/mcp/s/ZjM4NzQ1YTMtOWQ2Yi00ZTEyLWE3ZjAtZDc5YTBk/mcp", "app_link"),
    ("https://mcp.composio.dev/composio/server/2f1c9a3e-8b7d-4e6f-9a1b-3c5d7e9f1a2b/mcp?user_id=asha", "app_link"),
    ("https://apps.example.net/mcp?token=ZjM4NzQ1YTMtOWQ2Yi00ZTEyLWE3", "app_link"),
])
def test_each_key_shape_is_caught(text, provider):
    assert keys.key_in(text) == provider


def test_an_install_with_history_is_already_set_up(store):
    assert state.is_done(store) is False
    store.audit("user", "message", result_summary="hello")
    assert state.is_done(store) is True  # the owner's install: chats already, never sees Setup
    state.restart(store)
    assert state.is_done(store) is False  # unless they ask to run it again


async def test_set_names_saves_both(store):
    from odie import persona, profile
    out = await tools.run("set_names", {"user_name": "Asha", "assistant_name": "Iris"}, store)
    assert "error" not in out and profile.get(store)["user_name"] == "Asha" and persona.get(store)["name"] == "Iris"
    assert state.get(store)["steps"]["names"] == "done"
    assert "error" in await tools.run("set_names", {"user_name": "  "}, store)


async def test_vault_options_read_obsidians_list(store, home, tmp_path):
    notes = tmp_path / "Notes"
    notes.mkdir()
    cfg = home / "Library" / "Application Support" / "obsidian"
    cfg.mkdir(parents=True)
    (cfg / "obsidian.json").write_text(json.dumps({"vaults": {"a1": {"path": str(notes), "ts": 1}, "b2": {"path": str(tmp_path / "gone"), "ts": 2}}}))
    out = (await tools.run("vault_options", {}, store))["result"]
    assert out["known"] == [{"name": "Notes", "path": str(notes)}]  # a vault whose folder is gone isn't offered
    assert out["new_path"] == str(home / "Documents" / "Odie Vault")


async def test_a_new_vault_is_created_and_never_overwrites(store, home):
    from odie.vault import settings
    out = await tools.run("set_vault", {"choice": "new"}, store)
    v = home / "Documents" / "Odie Vault"
    assert "error" not in out and (v / "Welcome.md").is_file() and (v / "Odie" / "Memories.md").is_file()
    assert settings.get(store)["dir"] == str(v.resolve()) and state.get(store)["steps"]["vault"] == "done"
    (v / "Welcome.md").write_text("mine")
    again = await tools.run("set_vault", {"choice": "new"}, store)
    assert "already" in again["error"] and (v / "Welcome.md").read_text() == "mine"


async def test_an_existing_folder_must_be_a_full_path_that_exists(store, home, tmp_path):
    assert "full path" in (await tools.run("set_vault", {"choice": "elsewhere", "path": "Notes"}, store))["error"]
    assert "No folder" in (await tools.run("set_vault", {"choice": "elsewhere", "path": str(tmp_path / "nope")}, store))["error"]
    (tmp_path / "Mine").mkdir()
    assert "error" not in await tools.run("set_vault", {"choice": "existing", "path": str(tmp_path / "Mine")}, store)
    assert "error" not in await tools.run("set_vault", {"choice": "skip"}, store)
    assert state.get(store)["steps"]["vault"] == "skipped"


async def test_embedding_options_list_local_models_and_openai(store, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def handler(request):
        if request.url.port == 1234:
            return httpx.Response(200, json={"data": [{"id": "text-embedding-nomic-embed-text-v1.5"}, {"id": "gemma-4-12b"}]})
        return httpx.Response(200, json={"models": [{"name": "nomic-embed-text:latest"}, {"name": "glm-5.3-flash:cloud"}]})
    out = (await tools.run("embedding_options", {}, store, transport=httpx.MockTransport(handler)))["result"]
    got = {(o["provider"], o["model"]) for o in out["options"]}
    assert ("lmstudio", "text-embedding-nomic-embed-text-v1.5") in got and ("ollama", "nomic-embed-text:latest") in got
    assert ("lmstudio", "gemma-4-12b") not in got and ("ollama", "glm-5.3-flash:cloud") not in got
    openai = next(o for o in out["options"] if o["provider"] == "openai")
    assert openai["needs_key"] is True and "OpenAI" in openai["note"]


async def test_set_embeddings_checks_first(store, tmp_path, monkeypatch):
    from odie.vault import embed, settings
    (tmp_path / "Mine").mkdir()
    assert "vault" in (await tools.run("set_embeddings", {"provider": "ollama", "model": "nomic-embed-text"}, store))["error"]
    settings.put(store, dir=str(tmp_path / "Mine"))

    async def refuse(e):
        raise embed.EmbedError("ollama doesn't have the model nomic-embed-text")
    monkeypatch.setattr(embed, "check", refuse)
    out = await tools.run("set_embeddings", {"provider": "ollama", "model": "nomic-embed-text"}, store)
    assert "doesn't have the model" in out["error"] and settings.get(store)["embeddings"] is None

    async def ok(e):
        return 768
    monkeypatch.setattr(embed, "check", ok)
    assert "error" not in await tools.run("set_embeddings", {"provider": "ollama", "model": "nomic-embed-text"}, store)
    assert settings.get(store)["embeddings"] == {"provider": "ollama", "model": "nomic-embed-text", "pictures": False}
    assert state.get(store)["steps"]["embeddings"] == "done"


async def test_set_embeddings_asks_ollama_whether_the_model_sees_pictures(store, tmp_path, monkeypatch):
    """EmbeddingGemma 2 on Ollama lists "vision" among its capabilities (ollama show); such a model reads pictures by
    their look, a text-only one by their words. Odie's own service always sees pictures."""
    from odie.vault import embed, settings
    (tmp_path / "Mine").mkdir()
    settings.put(store, dir=str(tmp_path / "Mine"))

    async def ok(e):
        return 768
    monkeypatch.setattr(embed, "check", ok)

    def handler(request):
        if request.url.path == "/api/show":
            model = json.loads(request.content)["model"]
            caps = ["embedding", "vision", "audio"] if model.startswith("embeddinggemma-2") else ["embedding"]
            return httpx.Response(200, json={"capabilities": caps})
        return httpx.Response(404)
    t = httpx.MockTransport(handler)
    assert "error" not in await tools.run("set_embeddings", {"provider": "ollama", "model": "embeddinggemma-2:740m"}, store, transport=t)
    assert settings.get(store)["embeddings"]["pictures"] is True
    assert "error" not in await tools.run("set_embeddings", {"provider": "ollama", "model": "nomic-embed-text"}, store, transport=t)
    assert settings.get(store)["embeddings"]["pictures"] is False
    assert "error" not in await tools.run("set_embeddings", {"provider": "lmstudio", "model": "text-embedding-x"}, store, transport=t)
    assert settings.get(store)["embeddings"]["pictures"] is False


async def test_request_key_is_a_card_not_a_key(store):
    out = await tools.run("request_key", {"provider": "tavily"}, store)
    assert out["card"] == {"type": "key", "provider": "tavily", "kind": "search", "label": "Tavily", "note": out["card"]["note"]}
    assert "on the screen" in out["result"] and "key" not in json.dumps(out["result"]).replace("key form", "")
    assert (await tools.run("request_key", {"provider": "openai"}, store))["card"]["kind"] == "provider"
    assert "error" in await tools.run("request_key", {"provider": "nowhere"}, store)


async def test_skip_and_finish(store):
    assert "error" in await tools.run("skip_step", {"step": "names"}, store)
    assert "error" not in await tools.run("skip_step", {"step": "voice"}, store)
    assert state.get(store)["steps"]["voice"] == "skipped"
    await tools.run("set_names", {"user_name": "Asha"}, store)
    assert "error" in await tools.run("finish_setup", {}, store)  # steps are left: never finished over them
    for step in ("brain", "vault", "embeddings", "photos", "search", "apps", "phone"):
        state.mark(store, step, "done" if step == "brain" else "skipped")
    assert state.is_done(store) is True  # nothing left: setup finished by itself
    assert "error" not in await tools.run("finish_setup", {}, store)


async def test_a_tool_error_counts_as_a_failure_of_its_step(store):
    await tools.run("set_vault", {"choice": "elsewhere", "path": "relative"}, store)
    await tools.run("set_vault", {"bogus": 1}, store)  # bad arguments
    assert state.get(store)["fails"]["vault"] == 2
    assert "error" in await tools.run("no_such_tool", {}, store)


async def test_the_other_steps_say_what_is_there(store):
    for name in ("search_status", "voice_options", "apps_options", "phone_status"):
        out = await tools.run(name, {}, store)
        assert "error" not in out and out["result"], name
    assert "error" not in await tools.run("set_voice", {"engine": "kokoro"}, store)
    assert "OpenAI key" in (await tools.run("set_voice", {"engine": "openai"}, store))["error"]
    names = {d["function"]["name"] for d in tools.DECLARATIONS}
    assert {"set_names", "vault_options", "set_vault", "embedding_options", "server_models", "set_embeddings", "set_photos", "search_status",
            "voice_options", "set_voice", "apps_options", "connect_app", "phone_status", "request_key", "skip_step", "finish_setup"} == names


async def test_new_vault_names_and_paths_stay_inside(store, home, tmp_path, monkeypatch):
    from odie import persona
    persona.set_name(store, "..")
    out = await tools.run("set_vault", {"choice": "new"}, store)
    created = home / "Documents" / ".. Vault"
    assert not (home / "Documents" / "Memories.md").exists() and not (home / "Memories.md").exists()
    assert "error" in out or all(p.resolve().is_relative_to(created.resolve()) for p in created.rglob("*"))
    persona.set_name(store, "/etc/odie")
    await tools.run("set_vault", {"choice": "new", "path": str(tmp_path / "V2")}, store)
    vaults = [(home / "Documents").resolve(), (tmp_path / "V2").resolve()]
    memories = [p.resolve() for p in tmp_path.rglob("Memories.md")]
    assert memories and all(any(m.is_relative_to(v) and m.parent.parent.name.endswith(("Vault", "V2")) for v in vaults) for m in memories)
    assert not Path("/etc/odie").exists()
    monkeypatch.chdir(tmp_path)
    rel = await tools.run("set_vault", {"choice": "new", "path": "relative-vault"}, store)
    assert "full path" in rel["error"] and not (tmp_path / "relative-vault").exists()
    (tmp_path / "afile").write_text("x")
    assert "error" in await tools.run("set_vault", {"choice": "new", "path": str(tmp_path / "afile")}, store)


async def test_an_unexpected_tool_failure_is_a_plain_reason(store, monkeypatch):
    async def boom(store):
        raise OSError("disk full")
    monkeypatch.setitem(tools.TOOLS, "vault_options", boom)
    out = await tools.run("vault_options", {}, store)
    assert "disk full" in out["error"] and state.get(store)["fails"]["vault"] == 1


async def test_finish_needs_the_names(store):
    out = await tools.run("finish_setup", {}, store)
    assert "name" in out["error"] and state.is_done(store) is False
    await tools.run("set_names", {"user_name": "Asha"}, store)
    assert "brain" in (await tools.run("finish_setup", {}, store))["error"]  # and every other step done or skipped


def test_an_openrouter_key_shape():
    assert keys.key_in("sk-or-v1-0123456789abcdefABCDEF0123") == "openrouter"


async def test_connect_app_is_a_card(store):
    out = await tools.run("connect_app", {"app": "zapier"}, store)
    card = out["card"]
    assert card["type"] == "app" and card["app"] == "zapier" and card["label"] == "Zapier" and "mcp.zapier.com" in card["where"]
    assert "never see" in out["result"] or "told" in out["result"]
    assert "error" in await tools.run("connect_app", {"app": "nope"}, store)
    assert "connect_app" in {d["function"]["name"] for d in tools.DECLARATIONS}


async def test_embedding_options_offer_odies_own_service_when_it_is_installed(store, monkeypatch):
    from odie import embed_worker

    def handler(request):
        return httpx.Response(200, json={"data": [], "models": []})
    monkeypatch.setattr(embed_worker.EmbedWorker, "installed", property(lambda self: True))
    out = (await tools.run("embedding_options", {}, store, transport=httpx.MockTransport(handler)))["result"]
    last = out["options"][-1]  # the heaviest choice comes last
    assert (last["provider"], last["model"], last["local"]) == ("gemma", "google/embeddinggemma-2", True)
    assert "this Mac" in last["note"] and "1.5 GB" in last["note"]
    monkeypatch.setattr(embed_worker.EmbedWorker, "installed", property(lambda self: False))
    out = (await tools.run("embedding_options", {}, store, transport=httpx.MockTransport(handler)))["result"]
    assert all(o["provider"] != "gemma" for o in out["options"])


async def test_choosing_odies_own_service_before_its_model_is_here_says_it_is_downloading(store, tmp_path, monkeypatch):
    from odie.vault import embed, settings
    (tmp_path / "Mine").mkdir()
    settings.put(store, dir=str(tmp_path / "Mine"))

    async def preparing(e):
        return 0
    monkeypatch.setattr(embed, "check", preparing)
    monkeypatch.setattr(embed, "make_embedder", lambda provider, model, store=None, transport=None, **kw: object())
    out = await tools.run("set_embeddings", {"provider": "gemma", "model": "google/embeddinggemma-2"}, store)
    assert "error" not in out and "download" in out["result"]["note"].lower() and "1.5 GB" in out["result"]["note"]
    assert settings.get(store)["embeddings"] == {"provider": "gemma", "model": "google/embeddinggemma-2", "pictures": True}
    assert state.get(store)["steps"]["embeddings"] == "done"


async def test_voice_options_and_set_voice_without_a_local_voice(store, monkeypatch):
    monkeypatch.setenv("ODIE_VOICE", "off")  # an Intel Mac: Kokoro is not offered and not accepted
    out = (await tools.run("voice_options", {}, store))["result"]
    assert [o["engine"] for o in out["options"]] == ["openai"]
    refused = await tools.run("set_voice", {"engine": "kokoro"}, store)
    assert "Apple Silicon" in refused["error"]


async def test_embedding_options_hide_odies_own_service_where_it_cannot_run(store, monkeypatch):
    from odie import embed_worker

    def handler(request):
        return httpx.Response(200, json={"data": [], "models": []})
    monkeypatch.setattr(embed_worker.EmbedWorker, "installed", property(lambda self: True))
    monkeypatch.setenv("ODIE_EMBED", "off")  # built once on this Mac, switched off since: not offered
    out = (await tools.run("embedding_options", {}, store, transport=httpx.MockTransport(handler)))["result"]
    assert [o["provider"] for o in out["options"]] == ["openai"]
    monkeypatch.setattr(embed_worker.EmbedWorker, "installed", property(lambda self: False))


async def test_set_embeddings_keeps_the_servers_address(store, tmp_path, monkeypatch):
    """A server somewhere else: the address is saved with the model, the check and the pictures question go to that
    address, and the embedder is built for it."""
    from odie.vault import embed, settings
    (tmp_path / "Mine").mkdir()
    settings.put(store, dir=str(tmp_path / "Mine"))
    seen = []

    def handler(request):
        seen.append(str(request.url))
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"capabilities": ["embedding", "vision"]})
        if request.url.path == "/api/embed":
            return httpx.Response(200, json={"embeddings": [[1.0, 0.0, 0.0]]})
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0, 0.0, 0.0]}]})
    t = httpx.MockTransport(handler)
    out = await tools.run("set_embeddings", {"provider": "ollama", "model": "embeddinggemma-2", "url": "http://studio.local:11434/"}, store, transport=t)
    assert "error" not in out
    assert settings.get(store)["embeddings"] == {"provider": "ollama", "model": "embeddinggemma-2", "pictures": True, "url": "http://studio.local:11434"}
    assert all(u.startswith("http://studio.local:11434/") for u in seen)
    assert settings.embedder_for(store).url == "http://studio.local:11434/api/embed"
    out = await tools.run("set_embeddings", {"provider": "server", "model": "text-embedding-x", "url": "http://192.168.1.20:1234/v1"}, store, transport=t)
    assert "error" not in out
    assert settings.get(store)["embeddings"] == {"provider": "server", "model": "text-embedding-x", "pictures": False, "url": "http://192.168.1.20:1234/v1"}
    out = await tools.run("server_models", {"kind": "ollama", "url": "http://studio.local:11434"}, store, transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"models": [{"name": "embeddinggemma-2:740m"}]})))
    assert out["result"] == {"models": ["embeddinggemma-2:740m"], "problem": ""}
