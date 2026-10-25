"""Pictures by meaning (2026-10-14): each photo or video gets one vector from its words (people, what Photos saw, place,
albums, date) and its pixels together, through Odie's own service; a picture with no copy on this Mac gets the vector
of its words alone. Search is then one vector lookup over notes and pictures, ordered by likeness, with the filters
applied after; words alone are the fallback when no embedder is set."""
import hashlib
import shutil
from pathlib import Path

import httpx
import pytest

from odie.photos.library import PhotoRow
from odie.vault.embed import EmbedError, make_embedder
from odie.vault.index import VaultIndex
from tests.test_vault_embed import FakeEmbedder

SAMPLE = Path(__file__).parent / "fixtures" / "sample-vault"


class FakePictureEmbedder(FakeEmbedder):
    """Words hashed like the notes fake, plus a mark for the image file's name so pixels count for something."""
    sees_pictures = True

    async def embed_pictures(self, items):
        self.pictures = getattr(self, "pictures", []) + [items]
        out = []
        for text, image in items:
            [v] = await self.embed([text + (" " + Path(image).stem if image else "")])
            out.append(v)
        return out


def row(uuid, taken, labels=(), people=(), place="", albums=(), kind="photo", thumb=None, big=None):
    return PhotoRow(uuid=uuid, kind=kind, taken=taken, people=list(people), labels=list(labels), place=place, city="", country="",
                    albums=list(albums), thumb=thumb, big=big)


@pytest.fixture
def pics(tmp_path):
    (tmp_path / "goa_beach.jpeg").write_bytes(b"\xff\xd8x")
    (tmp_path / "goa_thumb.jpeg").write_bytes(b"\xff\xd8y")
    return [
        row("A1", "2024-05-16T11:00:00", labels=["Beach", "Sea"], people=["Asha"], place="Goa, India", albums=["Goa 2024"],
            thumb=str(tmp_path / "goa_thumb.jpeg"), big=str(tmp_path / "goa_beach.jpeg")),
        row("B2", "2023-11-12T18:00:00", labels=["Lamp", "Celebration"], people=["Dev"], place="Pune, India"),  # no copy here
        row("V3", "2024-05-16T17:00:00", labels=["Sea", "Boat"], kind="video", thumb=str(tmp_path / "goa_thumb.jpeg")),
    ]


@pytest.fixture
def index(tmp_path, pics):
    vault = tmp_path / "vault"
    shutil.copytree(SAMPLE, vault)
    ix = VaultIndex(tmp_path / "odie-index.db", vault)
    ix.scan()
    ix.index_photos(pics)
    return ix


async def test_each_picture_gets_one_vector_from_words_and_pixels(index, tmp_path):
    e = FakePictureEmbedder()
    await index.embed_pending(e)
    assert await index.embed_pending_pictures(e) == 3
    [batch] = e.pictures
    texts = {text for text, _ in batch}
    assert any("Asha" in t and "Beach, Sea" in t and "Goa, India" in t and "Goa 2024" in t and "16 May 2024" in t for t in texts)
    assert dict(batch)[next(t for t in texts if "Asha" in t)] == str(tmp_path / "goa_beach.jpeg")  # the big copy, not the thumb
    assert dict(batch)[next(t for t in texts if "Lamp" in t)] is None  # no copy: words alone
    assert dict(batch)[next(t for t in texts if "Boat" in t)] == str(tmp_path / "goa_thumb.jpeg")  # a video: its poster
    st = index.status()
    assert st["photo_vectors"] == 3 and st["vectors"] == st["chunks"]
    assert await index.embed_pending_pictures(e) == 0  # nothing left


async def test_the_notes_document_carries_its_title(index):
    e = FakePictureEmbedder()
    await index.embed_pending(e)
    assert any(isinstance(t, dict) and t.get("title") == "Goa trip" for t in e.documents)  # the note's own title, not its file name


async def test_search_is_one_vector_lookup_over_everything(index):
    e = FakePictureEmbedder()
    await index.embed_pending(e)
    await index.embed_pending_pictures(e)
    hits = await index.search_all("goa beach", embedder=e)
    kinds = [h.kind for h in hits]
    assert "note" in kinds and "photo" in kinds  # the trip note and the beach photo, in one ranked list
    assert hits == sorted(hits, key=lambda h: -h.score)
    photo = next(h for h in hits if h.kind == "photo")
    assert photo.ref == "A1" and photo.photo.place == "Goa, India"
    note = next(h for h in hits if h.kind == "note")
    assert note.note.path == "1-Projects/Trip to Goa.md"
    assert all(h.kind == "note" for h in await index.search_all("goa beach", embedder=e, only="docs"))
    assert all(h.kind in ("photo", "video") for h in await index.search_all("goa beach", embedder=e, only="media"))
    assert [h.ref for h in await index.search_all("sea", embedder=e, only="videos")] == ["V3"]
    assert all(h.ref != "A1" for h in await index.search_all("goa", embedder=e, people=["Dev"]))  # filters apply after
    assert [h.ref for h in await index.search_all("lamp", embedder=e, only="media")][0] == "B2"  # found by its words' vector
    assert await index.search_all("", embedder=e) == []


async def test_without_an_embedder_search_all_falls_back_to_words(index):
    hits = await index.search_all("goa", embedder=None)
    assert {h.kind for h in hits} >= {"note", "photo"}
    assert [h.ref for h in await index.search_all("", embedder=None, only="media", people=["Dev"])] == ["B2"]  # filters alone


async def test_ollama_reads_pictures_when_its_model_sees_them(isolated_settings, tmp_path):
    """EmbeddingGemma 2 on Ollama embeds a picture with its words through /api/embed items of {"text", "image"} (25 Oct
    2026): the image goes as base64 JPEG no wider than 1024 px. A text-only Ollama model keeps words only."""
    import base64, io, json
    from PIL import Image
    seen = []

    def handler(request: httpx.Request):
        seen.append(json.loads(request.content))
        n = len(seen[-1]["input"])
        return httpx.Response(200, json={"embeddings": [[1.0, 0.0]] * n})
    t = httpx.MockTransport(handler)
    words_only = make_embedder("ollama", "nomic-embed-text", transport=t)
    assert words_only.sees_pictures is False
    with pytest.raises(EmbedError, match="EmbeddingGemma 2"):
        await words_only.embed_pictures([("x", None)])
    big = tmp_path / "a.jpeg"
    Image.new("RGB", (2000, 1000), "red").save(big)
    gemma = make_embedder("ollama", "embeddinggemma-2:740m", transport=t, pictures=True)
    assert gemma.sees_pictures is True
    assert await gemma.embed_pictures([("Asha · Beach", str(big)), ("words only", None)]) == [[1.0, 0.0], [1.0, 0.0]]
    sent = seen[-1]
    assert sent["model"] == "embeddinggemma-2:740m" and [x["text"] for x in sent["input"]] == ["Asha · Beach", "words only"]
    assert "image" not in sent["input"][1]
    img = Image.open(io.BytesIO(base64.b64decode(sent["input"][0]["image"])))
    assert img.format == "JPEG" and img.size == (1024, 512)
    await gemma.embed([{"title": "Trip", "text": "Day 1"}])
    assert seen[-1]["input"] == ["Trip\nDay 1"] and "kind" not in seen[-1]  # notes go as before


async def test_a_picture_that_cannot_be_read_goes_by_its_words(isolated_settings, tmp_path):
    import json
    seen = []

    def handler(request: httpx.Request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"embeddings": [[1.0, 0.0]]})
    broken = tmp_path / "b.jpeg"
    broken.write_bytes(b"not a picture")
    gemma = make_embedder("ollama", "embeddinggemma-2:740m", transport=httpx.MockTransport(handler), pictures=True)
    assert await gemma.embed_pictures([("Asha", str(broken))]) == [[1.0, 0.0]]
    assert seen[-1]["input"] == [{"text": "Asha"}]


def test_the_setting_remembers_whether_the_model_sees_pictures(isolated_settings, tmp_path):
    from odie.store.db import Store
    from odie.vault import settings
    store = Store(tmp_path / "assistant.db")
    store.init_schema()
    settings.put(store, embeddings={"provider": "ollama", "model": "embeddinggemma-2:740m", "pictures": True})
    assert settings.get(store)["embeddings"] == {"provider": "ollama", "model": "embeddinggemma-2:740m", "pictures": True}
    assert settings.embedder_for(store).sees_pictures is True
    settings.put(store, embeddings={"provider": "ollama", "model": "nomic-embed-text"})
    assert settings.get(store)["embeddings"] == {"provider": "ollama", "model": "nomic-embed-text", "pictures": False}
    assert settings.embedder_for(store).sees_pictures is False


# ── the worker ──
@pytest.fixture
def store(isolated_settings, tmp_path):
    from odie.store.db import Store
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    return s


async def test_the_worker_reads_pictures_by_meaning_after_the_notes(store, pics, tmp_path, monkeypatch):
    from odie.photos import library as lib, settings as photo_settings
    from odie.vault import settings as vault_settings
    from odie.vault.worker import VaultWorker
    vault = tmp_path / "vault"
    shutil.copytree(SAMPLE, vault)
    vault_settings.put(store, dir=str(vault), embeddings={"provider": "ollama", "model": "nomic-embed-text"})
    photo_settings.put(store, on=True)
    monkeypatch.setattr(lib, "read_library", lambda include_screenshots=False, progress=None, dbfile=None: list(pics))
    phases = []
    text_only = FakeEmbedder()
    monkeypatch.setattr(vault_settings, "embedder_and_reason", lambda s: (text_only, ""))
    w = VaultWorker(store)
    real_update = w._count

    def counting(phase):
        phases.append(phase)
        return real_update(phase)
    monkeypatch.setattr(w, "_count", counting)
    await w.run_once()
    ix = vault_settings.index_for(store)
    assert ix.status()["vectors"] == ix.status()["chunks"] and ix.status()["photo_vectors"] == 0  # a text-only embedder: words only
    assert "pictures" not in phases
    sees = FakePictureEmbedder()
    monkeypatch.setattr(vault_settings, "embedder_and_reason", lambda s: (sees, ""))
    await w.run_once()
    assert ix.status()["photo_vectors"] == 3 and "pictures" in phases and w.progress()["error"] == ""
    hits = await ix.search_all("beach", embedder=sees)
    assert any(h.kind == "photo" for h in hits) and any(h.kind == "note" for h in hits)


def test_the_model_only_ever_gets_an_image_file(tmp_path):
    """A row indexed before the fix may still name a movie as its big copy: the thumbnail is used instead."""
    import sqlite3
    from odie.vault.index import picture_file
    (tmp_path / "clip.mov").write_bytes(b"\x00" * 10)
    (tmp_path / "poster.jpeg").write_bytes(b"\xff\xd8")
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("create table photos (big text, thumb text)")
    c.execute("insert into photos values (?, ?)", (str(tmp_path / "clip.mov"), str(tmp_path / "poster.jpeg")))
    c.execute("insert into photos values (?, ?)", (str(tmp_path / "clip.mov"), None))
    rows = c.execute("select * from photos").fetchall()
    assert picture_file(rows[0]) == str(tmp_path / "poster.jpeg")
    assert picture_file(rows[1]) is None
