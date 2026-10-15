import io
import struct
import zlib
from types import SimpleNamespace

import httpx
import pytest

from odie.app.main import create_app
from odie.app.runner import events_to_history, strip_trailer
from odie.store.db import Store


def png_bytes(w=1800, h=1200):
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * w for _ in range(h))
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def test_prepare_image_downscales_and_jpegs(tmp_path):
    from odie.app.images import prepare_image
    out = prepare_image(png_bytes(1800, 1200), tmp_path)
    assert out["w"] == 1280 and out["h"] == 853 and out["mime"] == "image/jpeg"
    assert (tmp_path / f"{out['id']}.jpg").stat().st_size < 200_000


def test_history_lifts_image_markers_out_of_text():
    from google.genai import types
    ev = SimpleNamespace(author="user", partial=False, timestamp=1.0, content=types.Content(role="user", parts=[
        types.Part(text="what is this?\n[image:abc123]\n\n[context: now 10:00 Thu 1 Oct]"),
        types.Part(inline_data=types.Blob(mime_type="image/jpeg", data=b"xx"))]))
    h = events_to_history([ev])
    assert h[0]["text"] == "what is this?" and h[0]["images"] == ["abc123"]
    assert strip_trailer("hi\n[image:a]\n\n[context: x]") == "hi\n[image:a]"


async def test_old_images_go_only_in_a_cut(tmp_path):
    from google.genai import types
    from odie.agent.compaction import compact
    contents = [
        types.Content(role="user", parts=[types.Part(text="old photo"), types.Part(inline_data=types.Blob(mime_type="image/jpeg", data=b"a" * 1000))]),
        types.Content(role="model", parts=[types.Part(text="a cat")]),
        types.Content(role="user", parts=[types.Part(text="new photo"), types.Part(inline_data=types.Blob(mime_type="image/jpeg", data=b"b" * 1000))]),
    ]
    assert compact(contents) == contents  # a short chat: the old photo goes as it went, so the cache still holds
    out = compact(contents, limit=5_000)  # a cut: ~6k before the new photo
    assert out[0].parts[1].inline_data is None and "[image omitted" in (out[0].parts[1].text or "")
    assert out[2].parts[1].inline_data is not None  # current turn keeps its image
    assert contents[0].parts[1].inline_data is not None  # the session's own copy is untouched


class FakeRunner:
    seen = None

    async def chat(self, text, thinking=False, session_id=None, images=None):
        FakeRunner.seen = (text, images)
        yield {"type": "done", "text": "ok"}

    async def history(self, date, limit=None, before=None):
        return {"items": [], "total": 0, "start": 0}

    async def close(self):
        pass


@pytest.fixture
async def client(isolated_settings, tmp_path):
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    app = create_app(runner=FakeRunner(), store=s)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c:
        async with app.router.lifespan_context(app):
            yield c


async def test_upload_serve_and_chat_with_image(client):
    r = await client.post("/api/upload", files={"file": ("p.png", png_bytes(400, 300), "image/png")})
    assert r.status_code == 200
    j = r.json()
    assert j["w"] == 400 and j["url"].startswith("/api/uploads/")
    g = await client.get(j["url"])
    assert g.status_code == 200 and g.headers["content-type"].startswith("image/jpeg")
    assert (await client.post("/api/upload", files={"file": ("x.txt", b"hello", "text/plain")})).status_code == 415
    async with client.stream("POST", "/api/chat", json={"text": "what is this?", "images": [j["id"]]}) as resp:
        [c async for c in resp.aiter_text()]
    assert FakeRunner.seen[0] == "what is this?" and FakeRunner.seen[1] == [j["id"]]
