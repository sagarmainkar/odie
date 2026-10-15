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
    for bad in ("http://10.0.0.1/a.jpg", "http://localhost/a.jpg", "file:///etc/passwd", "ftp://ex.com/a.jpg", "javascript:alert(1)"):
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
    m = media.save(jpeg(1280, 900, exif=False), "screenshot", "jpg", "image/jpeg", "maps.google.com · Shillong", {"url": "https://maps.google.com/x"})
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
