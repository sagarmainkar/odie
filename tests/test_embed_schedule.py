"""How often the background indexer embeds new notes and pictures (the vault setting's embed_every), or not at all:
the decision, the wait between passes, what off skips and keeps, the setting and the route."""
import asyncio
import shutil
from pathlib import Path

import httpx
import pytest

from odie.store.db import Store
from tests.test_vault_embed import FakeEmbedder

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


class PictureEmbedder(FakeEmbedder):
    sees_pictures = True


def _recording(monkeypatch):
    """Count the two embedding phases (each loads the model), and let the note phase really embed."""
    from odie.vault.index import VaultIndex
    calls = {"meaning": 0, "pictures": 0}
    real_meaning = VaultIndex.embed_pending

    async def meaning(self, embedder, progress=None):
        calls["meaning"] += 1
        return await real_meaning(self, embedder, progress=progress)

    async def pictures(self, embedder, progress=None):
        calls["pictures"] += 1
    monkeypatch.setattr(VaultIndex, "embed_pending", meaning)
    monkeypatch.setattr(VaultIndex, "embed_pending_pictures", pictures)
    return calls


def _photos_on(store, monkeypatch):
    from odie.photos import library, settings as photo_settings
    photo_settings.put(store, on=True)
    monkeypatch.setattr(library, "read_library", lambda include_screenshots=False, progress=None, dbfile=None: [])


# ── the decision and the wait ──
def test_embed_due_worked_examples(store):
    from odie.vault.worker import VaultWorker
    w = VaultWorker(store)
    assert w.embed_due(1000.0, 15) is True       # never embedded since start
    assert w.embed_due(1000.0, 0) is False       # off
    w._embedded_at, w._embed_every_seen = 1000.0, 15
    assert w.embed_due(1000.0 + 6 * 60, 15) is False   # every 15, 6 minutes ago
    assert w.embed_due(1000.0 + 16 * 60, 15) is True   # every 15, 16 minutes ago
    assert w.embed_due(1000.0 + 15 * 60 - 0.01, 15) is True  # a timer firing a hair early still counts
    assert w.embed_due(1000.0 + 6 * 60, 10) is True    # the interval just changed
    w._embed_every_seen = 0
    assert w.embed_due(1000.0 + 6 * 60, 15) is True    # just switched on
    w._embed_every_seen = 15
    w.kick()
    assert w.embed_due(1000.0 + 6 * 60, 15) is True    # a setting changed or the user asked
    assert w.embed_due(1000.0 + 6 * 60, 0) is False    # ... but off stays off


def test_the_wait_lines_up_with_the_embedding_interval(store):
    from odie.vault.worker import VaultWorker
    w = VaultWorker(store, every=300)
    assert w.seconds_to_wait(1000.0, 10) == 300  # nothing embedded yet: the keyword interval
    w._embedded_at = 1000.0
    assert w.seconds_to_wait(1000.0 + 7 * 60, 0) == 300    # off
    assert w.seconds_to_wait(1000.0 + 10 * 60, 60) == 300  # due in 50 minutes: the keyword interval first
    assert w.seconds_to_wait(1000.0 + 7 * 60, 10) == 180   # due in 3 minutes: wake then, not at 15
    assert w.seconds_to_wait(1000.0 + 11 * 60, 10) == 0    # overdue: straight away


# ── what a pass does ──
async def test_off_skips_both_embedding_phases_keeps_keywords_and_forgets_nothing(store, vault, monkeypatch):
    from odie.vault import settings
    from odie.vault.worker import VaultWorker
    settings.put(store, dir=str(vault))
    _photos_on(store, monkeypatch)
    calls = _recording(monkeypatch)
    embedder = PictureEmbedder()
    monkeypatch.setattr(settings, "embedder_and_reason", lambda s: (embedder, ""))
    w = VaultWorker(store)
    await w.run_once()
    ix = settings.index_for(store)
    assert calls == {"meaning": 1, "pictures": 1}
    embedded = ix.status()["vectors"]
    assert embedded and embedded == ix.status()["chunks"] and w.last_embedded()

    settings.put(store, embed_every=0)
    (vault / "Packing.md").write_text("# Packing\nTake the blue raincoat to the coast.\n")
    w.kick()
    await w.run_once()
    assert calls == {"meaning": 1, "pictures": 1}  # neither phase ran: the model stays unloaded
    assert ix.keyword("raincoat")[0].path == "Packing.md"  # the new note is found by its words
    st = ix.status()
    assert st["vectors"] == embedded and st["chunks"] > embedded  # nothing forgotten; the new passage waits
    assert st["model"] == embedder.name  # still reads by meaning: not switched to keyword only
    assert w.progress()["error"] == ""

    settings.put(store, embed_every=10)  # back on: the waiting passage is caught up on the next pass
    await w.run_once()
    assert calls == {"meaning": 2, "pictures": 2}
    assert ix.status()["vectors"] == ix.status()["chunks"]


async def test_on_embeds_at_most_once_per_interval(store, vault, monkeypatch):
    from odie.vault import settings
    from odie.vault.worker import VaultWorker
    settings.put(store, dir=str(vault), embed_every=15)
    calls = _recording(monkeypatch)
    monkeypatch.setattr(settings, "embedder_and_reason", lambda s: (FakeEmbedder(), ""))
    w = VaultWorker(store)
    await w.run_once()
    await w.run_once()  # a keyword pass a moment later
    assert calls["meaning"] == 1
    w._embedded_at -= 15 * 60  # fifteen minutes on
    await w.run_once()
    assert calls["meaning"] == 2


async def test_odie_writing_a_note_reads_its_words_now_and_its_meaning_later(store, vault, monkeypatch):
    from odie.vault import settings
    from odie.vault.worker import VaultWorker
    settings.put(store, dir=str(vault))
    calls = _recording(monkeypatch)
    monkeypatch.setattr(settings, "embedder_and_reason", lambda s: (FakeEmbedder(), ""))
    w = VaultWorker(store, every=3600)
    w.start()
    try:
        for _ in range(100):
            if calls["meaning"] and not w.progress()["running"]:
                break
            await asyncio.sleep(0.02)
        assert calls["meaning"] == 1
        note = vault / "Memories.md"
        note.write_text("# Memories\nThe user prefers aisle seats.\n")
        w.touch(note)
        for _ in range(100):
            if settings.index_for(store).keyword("aisle"):
                break
            await asyncio.sleep(0.02)
        assert settings.index_for(store).keyword("aisle")[0].path == "Memories.md"
        assert calls["meaning"] == 1  # the memory write didn't load the embedding model
    finally:
        await w.stop()


# ── the setting and the route ──
def test_the_setting_defaults_to_five_and_survives_other_saves(store, vault):
    from odie.vault import settings
    assert settings.get(store)["embed_every"] == 5  # an install that never chose: as before
    settings.put(store, dir=str(vault), embed_every=30)
    settings.put(store, ignore=["Recipes"])
    settings.put(store, embeddings=None)
    assert settings.get(store)["embed_every"] == 30 and settings.get(store)["ignore"] == ["Recipes"]
    settings.put(store, embed_every=0)
    assert settings.get(store)["embed_every"] == 0
    for bad in (7, -5, True, None, "15"):
        with pytest.raises(ValueError, match="every 5, 10, 15, 30 or 60"):
            settings.put(store, embed_every=bad)
    assert settings.get(store)["embed_every"] == 0


async def test_the_route_saves_the_choice_refuses_others_and_kicks(store, vault, monkeypatch):
    from odie.app.main import create_app
    from odie.vault.worker import VaultWorker
    from tests.test_api import FakeRunner
    kicks = []
    real_kick = VaultWorker.kick

    def kick(self, photos=False):
        kicks.append(photos)
        real_kick(self, photos)
    monkeypatch.setattr(VaultWorker, "kick", kick)
    app = create_app(runner=FakeRunner(), store=store)
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")
    async with c, app.router.lifespan_context(app):
        got = (await c.get("/api/vault")).json()
        assert got["settings"]["embed_every"] == 5 and got["meaning"]["every"] == 5 and got["meaning"]["on"] is True
        r = await c.put("/api/vault", json={"dir": str(vault), "embed_every": 0})
        assert r.status_code == 200
        assert r.json()["settings"]["embed_every"] == 0 and r.json()["meaning"]["on"] is False
        assert kicks
        for bad in (7, None, True, "soon"):
            r = await c.put("/api/vault", json={"embed_every": bad})
            assert r.status_code == 422, bad
        assert (await c.get("/api/vault")).json()["settings"]["embed_every"] == 0
        r = await c.put("/api/vault", json={"embed_every": 15})
        assert r.status_code == 200 and r.json()["meaning"]["every"] == 15 and r.json()["meaning"]["on"] is True
        rows = store.query("select result_summary from audit_log where event='vault_settings'")
        said = [row["result_summary"] for row in rows]
        assert "meaning updates: off" in said and "meaning updates: every 15 min" in said
        photos = (await c.get("/api/photos")).json()
        assert photos["meaning_every"] == 15
