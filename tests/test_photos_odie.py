"""Odie with the user's photos: the switch (off until setup or Settings turns it on), the capability and the rule, one
search tool over notes and pictures, the library read in the background by the same worker as the notes, the routes
(settings, status, thumbnails), and the setup step that asks once."""
import asyncio
import shutil
from pathlib import Path

import httpx
import pytest

from odie.photos.library import LibraryError, PhotoRow
from odie.store.db import Store

SAMPLE = Path(__file__).parent / "fixtures" / "sample-vault"
UUID_A = "0F1E2D3C-4B5A-6978-8899-AABBCCDDEEFF"
UUID_B = "11111111-2222-3333-4444-555555555555"


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


@pytest.fixture
def library(tmp_path, monkeypatch):
    """A pretend Photos library: two pictures with small copies on disk, read by a fake reader instead of osxphotos."""
    thumbs = tmp_path / "lib"
    thumbs.mkdir()
    (thumbs / "a_4_5005_c.jpeg").write_bytes(b"\xff\xd8thumb-a")
    (thumbs / "a_1_102_o.jpeg").write_bytes(b"\xff\xd8big-a")
    rows = [
        PhotoRow(uuid=UUID_A, kind="photo", taken="2024-05-16T11:09:23", people=["Asha"], labels=["Beach", "Sea"],
                 place="Baga Beach, Goa, India", city="Goa", country="India", albums=["Goa 2024"], extras={"season": ["Summer"]},
                 thumb=str(thumbs / "a_4_5005_c.jpeg"), big=str(thumbs / "a_1_102_o.jpeg")),
        PhotoRow(uuid=UUID_B, kind="video", taken="2023-11-12T18:00:00", people=[], labels=["Lamp"], place="Pune, India",
                 city="Pune", country="India", albums=[], extras={"holidays": ["Diwali"]}, screenshot=False),
    ]
    calls = []

    def fake_read(include_screenshots=False, progress=None, dbfile=None):
        calls.append(include_screenshots)
        if progress:
            progress(len(rows), len(rows))
        return list(rows)
    from odie.photos import library as lib
    monkeypatch.setattr(lib, "read_library", fake_read)
    return {"rows": rows, "calls": calls, "dir": thumbs}


def _names(tools):
    return {getattr(t, "name", "") for t in tools}


def _tool(tools, name):
    return next(t for t in tools if getattr(t, "name", "") == name).func


# ── the switch, the capability, the tools ──
def test_off_by_default_and_on_means_the_capability_and_the_tools(store):
    from odie import capabilities
    from odie.agent.agent import build_agent
    from odie.photos import settings
    assert settings.get(store) == {"on": False, "screenshots": False}
    assert "photos" not in capabilities.detect([], store)
    assert "search_everything" not in _names(build_agent(store).tools)
    settings.put(store, on=True)
    assert settings.get(store) == {"on": True, "screenshots": False} and settings.is_on(store)
    assert "photos" in capabilities.detect([], store)
    assert {"search_everything", "index_status"} <= _names(build_agent(store).tools)  # photos alone, no notes folder
    settings.put(store, screenshots=True)
    assert settings.get(store) == {"on": True, "screenshots": True}


def test_search_notes_is_now_search_everything(store, vault):
    from odie.agent.agent import build_agent
    from odie.vault import settings as vault_settings
    vault_settings.put(store, dir=str(vault))
    names = _names(build_agent(store).tools)
    assert "search_everything" in names and "search_notes" not in names
    assert {"read_note", "related_notes", "index_status"} <= names


def test_rule_wording_names_the_one_search_and_the_photos(store):
    from odie.agent.prompt import Who, rules_text

    def text(*caps):
        return rules_text(Who(caps=frozenset(caps)), gated=True)
    built_in = text("vault", "vault_index")
    assert "search_everything" in built_in and "search_notes" not in built_in
    assert "Photos and videos" not in built_in  # the pictures rule only when photos are on
    with_photos = text("vault", "vault_index", "photos")
    rule = next(line for line in with_photos.splitlines() if "Photos and videos" in line and "search_everything" in line)
    assert "odie-images" in rule and "/api/photos/" in rule and "more" in rule
    assert "search_everything" in text("photos")  # photos without a notes folder


async def test_search_everything_answers_notes_and_pictures_together(store, vault, library):
    from odie.photos import settings
    from odie.vault import settings as vault_settings
    from odie.vault.tools import make_vault_tools
    vault_settings.put(store, dir=str(vault))
    settings.put(store, on=True)
    ix = vault_settings.index_for(store)
    ix.scan()
    ix.index_photos(library["rows"])
    search = _tool(make_vault_tools(store), "search_everything")
    out = await search(query="goa")
    assert "[note] " in out and "Trip" in out  # the sample vault's Goa trip note
    assert "[photo] " in out and f"/api/photos/{UUID_A}/thumb" in out
    assert f"/thumb · photo:{UUID_A}\n" in out  # the address make_video and decks take, bare, to copy as it is
    assert "photo:<id> is the address a video or a deck takes" in out  # what it's for, said once, not in the address
    assert "16 May 2024" in out and "Baga Beach, Goa, India" in out and "Asha" in out and "Beach, Sea" in out
    assert "odie-images block (url: the /api/photos/… address" in out  # how to show them: not by photo:<id>
    only = await search(query="", only="videos")
    assert "[video] 12 Nov 2023 · Pune, India" in only and "also Diwali" in only and "[note]" not in only
    assert UUID_B not in only and "no copy on this computer" in only  # nothing of it here: nothing to show
    assert UUID_A not in await search(query="", people=["Asha"], since="2024-06-01")
    none = await search(query="xylophone")
    assert "Nothing" in none and "photos" in none.lower()
    photos_only = await search(query="trip", only="photos")
    assert "[note]" not in photos_only
    assert "[photo]" not in await search(query="goa", only="docs")


def hit(kind="photo", has_thumb=True):
    from odie.vault.index import PhotoHit
    return PhotoHit(uuid=UUID_A, kind=kind, taken="2024-05-16", place="Baga Beach, Goa, India", people=["Asha"],
                    labels=["Beach"], albums=[], extras=[], has_thumb=has_thumb, score=1.0)


def test_a_photo_line_carries_its_gallery_address_and_its_address_for_a_video_or_a_deck():
    from odie.vault.tools import picture_line
    # the photo: address ends the line, bare: copied into a make_video or deck line, it names the picture and only it
    assert picture_line(hit()) == ("[photo] 16 May 2024 · Baga Beach, Goa, India · with Asha · shows Beach · "
                                   f"/api/photos/{UUID_A}/thumb · photo:{UUID_A}")
    assert "photo:" not in picture_line(hit(kind="video"))  # make_video and decks take photos only
    assert "photo:" not in picture_line(hit(has_thumb=False))  # nothing of it on this computer to put in


def test_search_everything_says_what_the_photo_address_is_for(store):
    from odie.vault.tools import make_vault_tools
    search = next(t for t in make_vault_tools(store) if getattr(t, "name", "") == "search_everything")
    assert "photo:<id>" in search.func.__doc__ and "make_video" in search.func.__doc__


async def test_search_everything_without_photos_says_so_and_a_video_has_no_thumb_line(store, vault, library):
    from odie.vault import settings as vault_settings
    from odie.vault.tools import make_vault_tools
    vault_settings.put(store, dir=str(vault))
    vault_settings.index_for(store).scan()
    search = _tool(make_vault_tools(store), "search_everything")
    out = await search(query="goa", only="photos")
    assert "Photos aren't on" in out and "Settings" in out
    assert "[photo]" not in await search(query="goa")  # photos off: notes alone, no need to say only=docs


async def test_more_than_the_limit_is_counted_not_listed(store, library):
    from odie.photos import settings
    from odie.vault import settings as vault_settings
    from odie.vault.tools import make_vault_tools
    settings.put(store, on=True)
    ix = vault_settings.index_for(store)
    many = [PhotoRow(uuid=f"{i:08X}-0000-0000-0000-000000000000", kind="photo", taken=f"2024-01-{i + 1:02d}T10:00:00", people=[],
                     labels=["Dog"], place="", city="", country="", albums=[]) for i in range(9)]
    ix.index_photos(many)
    search = _tool(make_vault_tools(store), "search_everything")
    out = await search(query="dog")
    assert out.count("[photo]") == 6 and "3 more pictures match" in out and out.count("/thumb") == 0  # no copies: no address
    assert "no copy on this computer" in out and "odie-images" not in out  # nothing to show, so no how-to line
    out = await search(query="dog", photos=12)
    assert out.count("[photo]") == 9 and "more pictures" not in out


# ── the worker ──
async def test_the_worker_reads_the_library_when_photos_are_on(store, library):
    from odie.photos import settings
    from odie.vault import settings as vault_settings
    from odie.vault.worker import VaultWorker
    w = VaultWorker(store)
    await w.run_once()
    assert vault_settings.index_for(store) is None and library["calls"] == []  # off: nothing read, no index
    settings.put(store, on=True)
    await w.run_once()
    assert library["calls"] == [False]
    st = vault_settings.index_for(store).status()
    assert st["photos"] == 1 and st["videos"] == 1 and st["notes"] == 0
    assert w.progress()["phase"] == "idle" and w.progress()["error"] == ""
    await w.run_once()
    assert library["calls"] == [False]  # read again only after a while, or when kicked for photos
    w.kick(photos=True)
    await w.run_once()
    assert library["calls"] == [False, False]
    settings.put(store, screenshots=True)
    w.kick(photos=True)
    await w.run_once()
    assert library["calls"][-1] is True


async def test_switching_photos_off_forgets_them_and_a_library_error_is_said_plainly(store, library, monkeypatch):
    from odie.photos import library as lib, settings
    from odie.vault import settings as vault_settings
    from odie.vault.worker import VaultWorker
    settings.put(store, on=True)
    w = VaultWorker(store)
    await w.run_once()
    ix = vault_settings.index_for(store)
    assert ix.status()["photos"] == 1
    settings.put(store, on=False)
    await w.run_once()
    assert ix.status()["photos"] == 0 and ix.status()["photos_at"] is None

    def refuse(include_screenshots=False, progress=None, dbfile=None):
        raise LibraryError("macOS didn't let Odie read the Photos library.")
    monkeypatch.setattr(lib, "read_library", refuse)
    settings.put(store, on=True)
    w.kick(photos=True)
    await w.run_once()
    assert "macOS didn't let" in w.progress()["error"] and w.progress()["running"] is False


# ── the routes ──
async def _client(store, runner=None):
    from odie.app.main import create_app
    from tests.test_api import FakeRunner
    app = create_app(runner=runner or FakeRunner(), store=store)
    return app, httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def test_photos_routes_switch_report_and_serve_thumbnails(store, library):
    app, c = await _client(store)
    async with c, app.router.lifespan_context(app):
        got = (await c.get("/api/photos")).json()
        assert got["settings"] == {"on": False, "screenshots": False} and got["status"] is None
        r = await c.put("/api/photos", json={"on": True})
        assert r.status_code == 200 and r.json()["settings"]["on"] is True
        for _ in range(100):
            got = (await c.get("/api/photos")).json()
            if got["status"] and got["status"]["photos"] and not got["progress"]["running"]:
                break
            await asyncio.sleep(0.02)
        assert got["status"]["photos"] == 1 and got["status"]["videos"] == 1 and got["status"]["photos_at"]
        r = await c.get(f"/api/photos/{UUID_A}/thumb")
        assert r.status_code == 200 and r.content == b"\xff\xd8thumb-a" and r.headers["content-type"] == "image/jpeg"
        r = await c.get(f"/api/photos/{UUID_A}/big")
        assert r.status_code == 200 and r.content == b"\xff\xd8big-a"
        assert (await c.get(f"/api/photos/{UUID_B}/thumb")).status_code == 404  # nothing of it on this computer
        assert (await c.get("/api/photos/../../etc/passwd/thumb")).status_code in (404, 422)
        assert (await c.get("/api/photos/nope/thumb")).status_code == 404
        r = await c.put("/api/photos", json={"screenshots": True})
        assert r.json()["settings"] == {"on": True, "screenshots": True}
        r = await c.put("/api/photos", json={"on": False})
        assert r.json()["settings"]["on"] is False
        for _ in range(100):
            got = (await c.get("/api/photos")).json()
            if not got["progress"]["running"] and (got["status"] is None or not got["status"]["photos"]):
                break
            await asyncio.sleep(0.02)
        assert got["status"] is None or got["status"]["photos"] == 0
        assert (await c.get(f"/api/photos/{UUID_A}/thumb")).status_code == 404  # forgotten with the switch


# ── setup ──
async def test_setup_asks_once_about_photos_after_meaning(store, library, monkeypatch):
    from odie.setup import panels, state, tools
    assert state.STEPS.index("photos") == state.STEPS.index("embeddings") + 1 and "photos" in state.SKIPPABLE
    state.mark(store, "brain", "done")
    p = await panels.panel(store, "photos")
    words = (p["question"] + " " + p["explain"]).lower()
    assert "photos" in words and "people" in words and "nothing leaves" in words
    assert [c["id"] for c in p["choices"]] == ["yes"] and p["skip"]
    assert p["label"] == "Photos"
    line = await panels.apply(store, "photos", "yes")
    from odie.photos import settings
    assert settings.is_on(store) and state.get(store)["steps"]["photos"] == "done" and "background" in line.lower()
    assert "set_photos" in tools.TOOLS and any(d["function"]["name"] == "set_photos" for d in tools.DECLARATIONS)
    assert "Photos: on" in panels.summary(store)
    state.mark(store, "photos", "todo")
    settings.put(store, on=False)
    assert "Skipped" in await panels.apply(store, "photos", "skip")
    assert not settings.is_on(store) and state.get(store)["steps"]["photos"] == "skipped"
