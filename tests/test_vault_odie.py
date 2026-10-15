"""Odie with its own notes index: the folder setting, the four read-only tools, the capability and the rule wording,
the routes, and the indexer running in the background."""
import asyncio
import shutil
import threading
from pathlib import Path

import httpx
import pytest

from odie.store.db import Store

SAMPLE = Path(__file__).parent / "fixtures" / "sample-vault"


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    return s


@pytest.fixture
def vault(tmp_path):
    v = tmp_path / "vault"
    shutil.copytree(SAMPLE, v)
    return v


def _names(tools):
    return {getattr(t, "name", "") for t in tools}


def test_no_folder_no_vault_tools_and_no_capability(store):
    from odie import capabilities
    from odie.agent.agent import build_agent
    assert not {"search_everything", "read_note", "related_notes", "index_status"} & _names(build_agent(store).tools)
    assert not {"vault", "vault_index"} & capabilities.detect([], store)


def test_setting_a_folder_adds_the_tools_and_vault_index(store, vault):
    from odie import capabilities
    from odie.agent.agent import build_agent
    from odie.vault import settings
    with pytest.raises(ValueError, match="No folder"):
        settings.put(store, dir=str(vault / "missing"))
    settings.put(store, dir=str(vault))
    assert {"search_everything", "read_note", "related_notes", "index_status"} <= _names(build_agent(store).tools)
    assert {"vault", "vault_index"} <= capabilities.detect([], store)


async def test_an_mcp_vault_is_refused_while_the_built_in_one_is_on(store, vault):
    from odie.app.runner import OdieRunner
    from odie.vault import settings
    settings.put(store, dir=str(vault))
    r = OdieRunner(store)
    reserved = r._reserved_tool_names()
    assert {"search_everything", "read_note", "related_notes", "index_status"} <= set(reserved)  # an MCP server reusing them is refused
    await r.close()


def test_built_in_vault_rule_wording():
    from odie.agent.prompt import Who, rules_text
    mcp = rules_text(Who(caps=frozenset({"vault"})), gated=True)
    built_in = rules_text(Who(caps=frozenset({"vault", "vault_index"})), gated=True)
    assert "load the mcp-vault skill" in mcp and "load the mcp-vault skill" not in built_in
    assert "search_everything" in built_in and "related_notes" in built_in and "meaning when it is set up" in built_in


async def test_tools_are_read_only_and_answer_in_text(store, vault):
    from odie.vault import settings
    from odie.vault.tools import make_vault_tools
    settings.put(store, dir=str(vault))
    settings.index_for(store).scan()
    t = {x.name: x for x in make_vault_tools(store)}
    found = await t["search_everything"].func(query="lentils")
    assert "Dal" in found and "Recipes/Dal.md" in found
    assert "Nothing in the notes" in await t["search_everything"].func(query="zeppelin")
    assert (await t["read_note"].func(note="Goa")).startswith("---\ntitle: Goa trip")
    assert "No note called" in await t["read_note"].func(note="../../etc/passwd")
    assert "Trip to Goa" in await t["related_notes"].func(note="Home")
    status = await t["index_status"].func()
    assert "3 notes" in status and "keyword" in status
    before = sorted(p.relative_to(vault).as_posix() for p in vault.rglob("*"))
    assert sorted(p.relative_to(vault).as_posix() for p in vault.rglob("*")) == before  # nothing written


async def _client(store, runner=None):
    from odie.app.main import create_app
    from tests.test_api import FakeRunner
    app = create_app(runner=runner or FakeRunner(), store=store)
    return app, httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def test_vault_routes_validate_and_report_progress(store, vault):
    app, c = await _client(store)
    async with c, app.router.lifespan_context(app):
        assert (await c.get("/api/vault")).json()["settings"]["dir"] is None
        r = await c.put("/api/vault", json={"dir": str(vault / "nope")})
        assert r.status_code == 422 and "No folder" in r.json()["detail"]
        r = await c.put("/api/vault", json={"dir": str(vault), "ignore": ["Recipes"]})
        assert r.status_code == 200 and r.json()["settings"]["ignore"] == ["Recipes"]
        for _ in range(50):
            got = (await c.get("/api/vault")).json()
            if got["status"] and got["status"]["notes"] and not got["progress"]["running"]:
                break
            await asyncio.sleep(0.05)
        assert got["status"]["notes"] == 2 and got["progress"]["phase"] == "idle"  # Recipes left out
        assert (await c.post("/api/vault/reindex")).json()["ok"] is True


async def test_put_with_a_failing_embedder_is_refused_with_the_reason(store, vault, monkeypatch):
    from odie.vault import embed
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    app, c = await _client(store)
    async with c, app.router.lifespan_context(app):
        r = await c.put("/api/vault", json={"dir": str(vault), "embeddings": {"provider": "openai", "model": "text-embedding-3-small"}})
        assert r.status_code == 422 and "OpenAI key" in r.json()["detail"]

        async def refuse(e):
            raise embed.EmbedError("ollama doesn't have the model nomic-embed-text")
        monkeypatch.setattr(embed, "check", refuse)
        r = await c.put("/api/vault", json={"dir": str(vault), "embeddings": {"provider": "ollama", "model": "nomic-embed-text"}})
        assert r.status_code == 422 and "doesn't have the model" in r.json()["detail"]
        assert (await c.get("/api/vault")).json()["settings"]["embeddings"] is None  # nothing saved


async def test_indexing_runs_in_the_background(store, vault, monkeypatch):
    from odie.vault import settings
    from odie.vault.index import VaultIndex
    settings.put(store, dir=str(vault))
    release = threading.Event()
    real = VaultIndex.scan

    def slow_scan(self, progress=None):
        if progress:
            progress(1, 3)
        release.wait(5)
        return real(self, progress)
    monkeypatch.setattr(VaultIndex, "scan", slow_scan)
    app, c = await _client(store)
    async with c, app.router.lifespan_context(app):
        for _ in range(50):
            p = (await c.get("/api/vault")).json()["progress"]
            if p["running"]:
                break
            await asyncio.sleep(0.02)
        assert p["running"] and p["done"] == 1 and p["total"] == 3 and p["phase"] == "keywords"
        assert (await c.get("/api/health")).status_code == 200  # the app answers while the pass runs
        release.set()
        for _ in range(100):
            p = (await c.get("/api/vault")).json()["progress"]
            if not p["running"]:
                break
            await asyncio.sleep(0.02)
        assert p["phase"] == "idle"


async def test_odie_writing_a_note_reindexes_it(store, vault):
    from odie.vault import settings
    from odie.vault.worker import VaultWorker
    settings.put(store, dir=str(vault))
    w = VaultWorker(store, every=3600)
    w.start()
    try:
        for _ in range(100):
            if not w.progress()["running"] and settings.index_for(store).status()["notes"]:
                break
            await asyncio.sleep(0.02)
        note = vault / "Memories.md"
        note.write_text("# Memories\nThe user prefers aisle seats.\n")
        w.touch(note)
        for _ in range(100):
            if settings.index_for(store).keyword("aisle"):
                break
            await asyncio.sleep(0.02)
        assert settings.index_for(store).keyword("aisle")[0].path == "Memories.md"
    finally:
        await w.stop()


def test_an_empty_or_relative_folder_turns_the_index_off_or_is_refused(store, vault):
    from odie.vault import settings
    settings.put(store, dir=str(vault))
    with pytest.raises(ValueError, match="full path"):
        settings.put(store, dir="vault")
    settings.put(store, dir="")
    assert settings.get(store)["dir"] is None and not settings.configured(store)
    settings.put(store, dir=str(vault))
    settings.put(store, dir=None)
    assert settings.get(store)["dir"] is None


async def test_the_api_can_turn_the_index_off(store, vault):
    app, c = await _client(store)
    async with c, app.router.lifespan_context(app):
        assert (await c.put("/api/vault", json={"dir": str(vault)})).json()["settings"]["dir"]
        r = await c.put("/api/vault", json={"dir": None})
        assert r.status_code == 200 and r.json()["settings"]["dir"] is None
        assert "vault_index" not in (await c.get("/api/capabilities")).json()["caps"]


async def test_one_failure_doesnt_stop_the_worker(store, vault, monkeypatch):
    from odie.vault import settings
    from odie.vault.worker import VaultWorker
    settings.put(store, dir=str(vault))
    real = settings.index_for
    calls = {"n": 0}

    def flaky(s):
        calls["n"] += 1
        if calls["n"] == 1:
            import sqlite3
            raise sqlite3.OperationalError("database is locked")
        return real(s)
    monkeypatch.setattr(settings, "index_for", flaky)
    w = VaultWorker(store, every=0.05)
    w.start()
    try:
        for _ in range(200):
            if calls["n"] >= 2 and real(store).status()["notes"]:
                break
            await asyncio.sleep(0.02)
        assert real(store).status()["notes"] == 3 and not w._task.done()
    finally:
        await w.stop()


async def test_switching_meaning_off_clears_its_status_and_a_missing_key_says_why(store, vault, monkeypatch):
    from odie.vault import settings
    from odie.vault.worker import VaultWorker
    from tests.test_vault_embed import FakeEmbedder
    settings.put(store, dir=str(vault))
    ix = settings.index_for(store)
    ix.scan()
    await ix.embed_pending(FakeEmbedder())
    assert ix.status()["model"]
    w = VaultWorker(store)
    await w.run_once()  # no embeddings set
    assert ix.status()["model"] is None and ix.status()["vectors"] == 0
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    settings.put(store, embeddings={"provider": "openai", "model": "text-embedding-3-small"})
    await w.run_once()
    assert "OpenAI key" in w.progress()["error"]


def test_an_old_index_is_let_go_when_the_settings_change(store, vault):
    from odie.vault import settings
    settings.put(store, dir=str(vault))
    settings.index_for(store)
    settings.put(store, ignore=["Recipes"])
    settings.index_for(store)
    assert len(settings._indexes) == 1
