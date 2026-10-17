"""Photos for decks: public addresses only (each redirect checked), images only, size-capped, re-encoded to JPEG at
most 2000 px with EXIF dropped, cached by address, credited; screenshots and uploads by id; failures reported."""
import io

import httpx
import pytest
from PIL import Image

from odie import net
from odie.decks import photos


def jpeg(w=3000, h=2000, exif=True) -> bytes:
    img = Image.new("RGB", (w, h), (30, 90, 60))
    out = io.BytesIO()
    ex = Image.Exif()
    if exif:
        ex[0x010F] = "SecretCam"  # Make
    img.save(out, "JPEG", exif=ex.tobytes())
    return out.getvalue()


@pytest.fixture
def web(monkeypatch, isolated_settings, tmp_path):
    """safe_download answered by a table of url -> (status, content-type, body), public-address check included."""
    table = {}

    async def fake(url, max_bytes, referer=None, timeout=30):
        if "10.0.0.1" in url or "localhost" in url:
            raise net.DownloadError("The link isn't a public web address.")
        status, ctype, body = table.get(url, (404, "text/html", b""))
        if status != 200:
            raise net.DownloadError(f"The link answered {status}.")
        if len(body) > max_bytes:
            raise net.DownloadError("too big")
        return body, ctype
    monkeypatch.setattr(photos, "safe_download", fake)
    from odie.agent.tools.files import workspace_root
    assert str(tmp_path) in str(workspace_root())
    return table


async def test_a_photo_is_reencoded_capped_and_cached(web):
    web["https://ex.com/a.jpg"] = (200, "image/jpeg", jpeg())
    p = await photos.fetch("https://ex.com/a.jpg", credit="Chalo Hoppo")
    assert (p.width, p.height) == (2000, 1333) and p.credit == "Chalo Hoppo"
    img = Image.open(p.path)
    assert img.format == "JPEG" and 0x010F not in img.getexif()  # EXIF dropped
    web.clear()  # the second time comes from the cache
    again = await photos.fetch("https://ex.com/a.jpg")
    assert again.path == p.path and again.data_uri().startswith("data:image/jpeg;base64,")


async def test_the_credit_defaults_to_the_site(web):
    web["https://www.esikkimtourism.in/x.jpg"] = (200, "image/jpeg", jpeg(800, 600))
    assert (await photos.fetch("https://www.esikkimtourism.in/x.jpg")).credit == "esikkimtourism.in"


async def test_photos_are_public_addresses_only(web):
    for bad in ("http://10.0.0.1/a.jpg", "http://localhost/a.jpg", "file:///etc/passwd", "ftp://ex.com/a.jpg",
                "javascript:alert(1)"):
        with pytest.raises(photos.PhotoError):
            await photos.fetch(bad)


async def test_not_an_image_is_refused(web):
    web["https://ex.com/page"] = (200, "text/html", b"<html>hi</html>")
    web["https://ex.com/fake.jpg"] = (200, "image/jpeg", b"not really a jpeg")
    for u in ("https://ex.com/page", "https://ex.com/fake.jpg"):
        with pytest.raises(photos.PhotoError):
            await photos.fetch(u)


async def test_fetch_all_reports_the_failures(web):
    web["https://ex.com/ok.jpg"] = (200, "image/jpeg", jpeg(400, 300))
    got, failed = await photos.fetch_all([("https://ex.com/ok.jpg", ""), ("https://ex.com/gone.jpg", "x")])
    assert list(got) == ["https://ex.com/ok.jpg"] and failed == ["https://ex.com/gone.jpg"]


async def test_screenshots_and_uploads_by_id(web):
    from odie import media
    from odie.app.images import prepare_image, uploads_dir
    m = media.save(jpeg(1280, 900, exif=False), "screenshot", "jpg", "image/jpeg", "maps.google.com · Shillong",
                   {"url": "https://maps.google.com/x"})
    shot = await photos.fetch(f"screenshot:{m['id']}")
    assert shot.credit == "maps.google.com" and shot.width == 1280
    up = prepare_image(jpeg(900, 600, exif=False), uploads_dir())
    mine = await photos.fetch(f"upload:{up['id']}")
    assert mine.credit == "" and mine.width == 900  # the user's own photo needs no credit
    for bad in ("screenshot:../../etc", "upload:nope", f"screenshot:{'0' * 16}"):
        with pytest.raises(photos.PhotoError):
            await photos.fetch(bad)


async def test_safe_download_checks_every_redirect(monkeypatch):
    async def resolve(host):
        return {"ex.com": ["93.184.216.34"], "inside.example": ["192.168.1.5"]}.get(host, [])
    monkeypatch.setattr(net, "resolve_host", resolve)

    def handler(req):
        if req.url.path == "/hop":
            return httpx.Response(302, headers={"location": "http://inside.example/secret"})
        return httpx.Response(200, headers={"content-type": "image/jpeg"}, content=b"x" * 10)
    monkeypatch.setattr(net, "_transport", httpx.MockTransport(handler))
    with pytest.raises(net.DownloadError, match="public"):
        await net.safe_download("https://ex.com/hop", 1000)
    body, ctype = await net.safe_download("https://ex.com/ok", 1000)
    assert body == b"x" * 10 and ctype == "image/jpeg"
    with pytest.raises(net.DownloadError, match="over"):
        await net.safe_download("https://ex.com/ok", 5)


def test_the_readme_says_whose_photos_they_are():
    from pathlib import Path
    text = (Path(__file__).parent.parent / "README.md").read_text()
    assert "Designed decks" in text and "belong to their owners" in text  # spec part 3: the repo ships no photos


# The user's own pictures, by photo:<id>: the library's big copy, through the real index (rows from a stand-in library).

UUID = "0F1E2D3C-4B5A-6978-8899-AABBCCDDEEFF"


@pytest.fixture
def library(isolated_settings, tmp_path, monkeypatch):
    """Photos switched on, a store the background jobs would use, and index_rows(rows) to put library rows in the
    real index; the copies are files under tmp_path."""
    from odie.making import jobs
    from odie.photos import settings as photo_settings
    from odie.store.db import Store
    from odie.vault import settings as vault_settings
    store = Store(tmp_path / "assistant.db")
    store.init_schema()
    photo_settings.put(store, on=True)
    monkeypatch.setitem(jobs.hooks, "store", store)
    copies = tmp_path / "library"
    copies.mkdir()

    def index_rows(rows):
        vault_settings.index_for(store).index_photos(rows)

    return copies, index_rows


def library_row(uuid, big, kind="photo"):
    from odie.photos.library import PhotoRow
    return PhotoRow(uuid=uuid, kind=kind, taken="2026-05-12T10:00:00", people=["Asha"], labels=[], place="Nathula",
                    city="", country="India", albums=[], big=str(big) if big else None)


async def test_a_library_picture_is_its_big_copy_upright_and_uncredited(library):
    copies, index_rows = library
    big = copies / "x_1_102_o.jpeg"
    big.write_bytes(jpeg(2048, 1536))
    index_rows([library_row(UUID, big)])
    got = await photos.fetch(f"photo:{UUID}", credit="Photo by Asha")
    assert (got.width, got.height) == (2000, 1500) and got.credit == ""
    assert got.ref == f"photo:{UUID}" and 0x010F not in Image.open(got.path).getexif()  # the camera isn't carried


async def test_a_library_picture_with_only_a_small_copy_is_refused_with_what_to_do(library):
    copies, index_rows = library
    thumb = copies / "x_4_5005_c.jpeg"
    thumb.write_bytes(jpeg(360, 270))
    index_rows([library_row(UUID, thumb)])
    with pytest.raises(photos.PhotoError) as e:
        await photos.fetch(f"photo:{UUID}")
    assert str(e.value) == (f"photo:{UUID} has only a small copy on this Mac (360 px); open it in Photos once so the "
                            "full picture comes down")


async def test_a_library_picture_odie_cant_use_is_refused_in_words(library, monkeypatch):
    copies, index_rows = library
    heic = copies / "IMG_1.HEIC"
    heic.write_bytes(b"ftypheic not something Pillow reads here")
    video = "11111111-2222-3333-4444-555555555555"
    gone = "22222222-2222-3333-4444-555555555555"
    index_rows([library_row(UUID, heic), library_row(video, copies / "v.jpeg", kind="video"),
                library_row(gone, copies / "gone.jpeg")])
    cases = {
        f"photo:{UUID}": f"photo:{UUID} is a HEIC Odie can't read here; export it as JPEG from Photos",
        f"photo:{video}": f"photo:{video} is a video; only photos from the library can go in",
        f"photo:{gone}": f"photo:{gone} has no copy on this Mac; open it in Photos once so the full picture comes down",
        "photo:33333333-2222-3333-4444-555555555555": "There's no picture photo:33333333-2222-3333-4444-555555555555 "
                                                      "in the user's Photos library here.",
    }
    for ref, words in cases.items():
        with pytest.raises(photos.PhotoError) as e:
            await photos.fetch(ref)
        assert str(e.value) == words


async def test_library_pictures_work_in_a_private_chat(library):
    from odie.agent import turn
    copies, index_rows = library
    big = copies / "x_1_102_o.jpeg"
    big.write_bytes(jpeg(1200, 1600))
    index_rows([library_row(UUID, big)])
    token = turn.PRIVATE.set({"amazon.in"})
    try:
        got = await photos.fetch(f"photo:{UUID}")
    finally:
        turn.PRIVATE.reset(token)
    assert (got.width, got.height) == (1200, 1600)


async def test_without_photos_set_up_a_library_picture_is_said_missing(isolated_settings, monkeypatch):
    from odie.making import jobs
    monkeypatch.setitem(jobs.hooks, "store", None)
    with pytest.raises(photos.PhotoError, match="There's no picture photo:abc in the user's Photos library here."):
        await photos.fetch("photo:abc")


async def test_a_link_that_cant_be_reached_is_a_download_error(monkeypatch):
    async def resolve(host):
        return ["93.184.216.34"]

    def handler(req):
        raise httpx.ReadTimeout("timed out", request=req)

    monkeypatch.setattr(net, "resolve_host", resolve)
    monkeypatch.setattr(net, "_transport", httpx.MockTransport(handler))
    with pytest.raises(net.DownloadError, match="The link couldn't be reached."):
        await net.safe_download("https://ex.com/slow.jpg", 1000)


async def test_one_address_fetched_twice_at_once_is_fine(web):
    import asyncio
    web["https://ex.com/same.jpg"] = (200, "image/jpeg", jpeg(2400, 1600))
    first, second = await asyncio.gather(photos.fetch("https://ex.com/same.jpg"),
                                         photos.fetch("https://ex.com/same.jpg"))
    assert first.path == second.path and (first.width, second.width) == (2000, 2000)
    assert [p.name for p in first.path.parent.iterdir() if p.suffix == ".tmp"] == []  # no temporary file left
