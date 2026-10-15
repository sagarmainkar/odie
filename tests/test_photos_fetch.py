"""Fetching a picture's original from iCloud on request (odie.photos.fetch): a tap on a video (or Full size on a photo)
asks Photos, through PhotoKit, to download the original into Odie's data folder; the chat polls until it's there and
then plays or shows it. The index must know the uuid; the download itself is faked here."""
import asyncio
import shutil
from pathlib import Path

import httpx
import pytest

from odie.photos import fetch
from odie.photos.library import PhotoRow
from odie.store.db import Store

UUID_V = "11111111-2222-3333-4444-555555555555"
UUID_P = "0F1E2D3C-4B5A-6978-8899-AABBCCDDEEFF"


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    return s


@pytest.fixture
def indexed(store, tmp_path):
    from odie.photos import settings
    from odie.vault import settings as vault_settings
    settings.put(store, on=True)
    (tmp_path / "poster.jpeg").write_bytes(b"\xff\xd8poster")
    rows = [PhotoRow(uuid=UUID_V, kind="video", taken="2024-01-06T10:00:00", people=[], labels=["Sea"], place="Goa, India", city="Goa",
                     country="India", albums=[], thumb=str(tmp_path / "poster.jpeg"), big=str(tmp_path / "poster.jpeg")),
            PhotoRow(uuid=UUID_P, kind="photo", taken="2024-05-16T11:00:00", people=["Asha"], labels=["Beach"], place="", city="", country="", albums=[])]
    vault_settings.index_for(store).index_photos(rows)
    return rows


@pytest.fixture
def fake_download(tmp_path, monkeypatch):
    """The PhotoKit step, replaced: writes a small .MOV where the real one would land, after a moment."""
    calls = []

    def download(uuid: str, folder: Path) -> Path:
        calls.append(uuid)
        if uuid == UUID_P:
            raise fetch.FetchError("Photos couldn't fetch it: not in iCloud any more")
        out = folder / f"{uuid}.MOV"
        out.write_bytes(bytes(range(256)) * 4)
        return out
    monkeypatch.setattr(fetch, "download", download)
    return calls


async def _client(store):
    from odie.app.main import create_app
    from tests.test_api import FakeRunner
    app = create_app(runner=FakeRunner(), store=store)
    return app, httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t")


async def test_info_says_what_a_picture_is_and_whether_its_original_is_here(store, indexed):
    app, c = await _client(store)
    async with c, app.router.lifespan_context(app):
        r = await c.get(f"/api/photos/{UUID_V}/info")
        assert r.status_code == 200
        d = r.json()
        assert d["kind"] == "video" and d["taken"] == "2024-01-06" and d["place"] == "Goa, India" and d["has_big"] is True
        assert d["original"] == {"state": "missing", "error": ""}
        assert (await c.get(f"/api/photos/{UUID_P}/info")).json()["has_big"] is False
        assert (await c.get("/api/photos/nope/info")).status_code == 404
        assert (await c.get(f"/api/photos/{UUID_V}/original")).status_code == 404  # nothing fetched yet


async def test_a_fetch_runs_in_the_background_and_the_original_then_streams(store, indexed, fake_download):
    app, c = await _client(store)
    async with c, app.router.lifespan_context(app):
        r = await c.post(f"/api/photos/{UUID_V}/fetch")
        assert r.status_code == 200 and r.json()["state"] in ("fetching", "ready")
        for _ in range(100):
            d = (await c.get(f"/api/photos/{UUID_V}/fetch")).json()
            if d["state"] == "ready":
                break
            await asyncio.sleep(0.02)
        assert d["state"] == "ready" and fake_download == [UUID_V]
        assert (await c.post(f"/api/photos/{UUID_V}/fetch")).json()["state"] == "ready"  # already here: no second download
        assert fake_download == [UUID_V]
        r = await c.get(f"/api/photos/{UUID_V}/original", headers={"Range": "bytes=0-9"})
        assert r.status_code == 206 and r.content == bytes(range(10)) and r.headers["content-type"] == "video/quicktime"
        assert (await c.get(f"/api/photos/{UUID_V}/info")).json()["original"]["state"] == "ready"
        assert (await c.get(f"/api/photos/{UUID_V}/original")).headers["accept-ranges"] == "bytes"


async def test_a_failed_fetch_says_why_and_can_be_tried_again(store, indexed, fake_download):
    app, c = await _client(store)
    async with c, app.router.lifespan_context(app):
        await c.post(f"/api/photos/{UUID_P}/fetch")
        for _ in range(100):
            d = (await c.get(f"/api/photos/{UUID_P}/fetch")).json()
            if d["state"] == "failed":
                break
            await asyncio.sleep(0.02)
        assert d["state"] == "failed" and "not in iCloud" in d["error"]
        assert (await c.get(f"/api/photos/{UUID_P}/original")).status_code == 404
        await c.post(f"/api/photos/{UUID_P}/fetch")  # a retry asks again
        await asyncio.sleep(0.05)
        assert fake_download.count(UUID_P) == 2


def test_fetched_files_are_found_by_uuid_whatever_their_extension(tmp_path):
    folder = tmp_path / "photos-fetched"
    folder.mkdir()
    (folder / f"{UUID_V}.MOV").write_bytes(b"x")
    assert fetch.fetched_file(UUID_V, folder) == folder / f"{UUID_V}.MOV"
    assert fetch.fetched_file(UUID_P, folder) is None
    assert fetch.media_type(folder / f"{UUID_V}.MOV") == "video/quicktime"
    assert fetch.media_type(Path("a.mp4")) == "video/mp4" and fetch.media_type(Path("a.heic")) == "image/heic"


def test_a_denied_photokit_is_said_plainly():
    assert "Privacy & Security" in fetch.plain_reason(Exception("PHPhotosErrorDomain error 3311: not authorized"))
    assert "iCloud" in fetch.plain_reason(Exception("The file isn’t in the cloud"))
