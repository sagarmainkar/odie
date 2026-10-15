"""Media in replies: what a tool makes to play, see or download is stored under the data folder, served by
/api/media/{id}, streamed to the chat as it's made, and kept with its reply in history."""
import array
import io
import math
import wave

import httpx
import pytest
from google.adk.events import Event
from google.genai import types

from odie import media
from odie.store.db import Store


def make_wav(seconds: float = 1.0, rate: int = 24000, freq: float = 440.0, loud: float = 0.5) -> bytes:
    n = int(seconds * rate)
    samples = array.array("h", (int(loud * 32767 * math.sin(2 * math.pi * freq * i / rate)) for i in range(n)))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.tobytes())
    return buf.getvalue()


def test_save_and_get(isolated_settings):
    m = media.save(b"hello", "file", "txt", "text/plain", "Notes", {"pages": 1})
    assert media.ID_RE.match(m["id"]) and m["kind"] == "file" and m["size"] == 5 and m["pages"] == 1 and m["title"] == "Notes"
    path, meta = media.get(m["id"])
    assert path.read_bytes() == b"hello" and meta == m and path.parent == isolated_settings.data_dir / "media"


@pytest.mark.parametrize("bad", ["", "../etc/passwd", "ABCDEF0123456789", "0123456789abcde", "0123456789abcdef0", "0123456789abcdef/../x"])
def test_get_refuses_bad_ids(isolated_settings, bad):
    assert media.get(bad) is None
    assert media.get("0123456789abcdef") is None  # well formed, but nothing saved


def test_wav_info():
    info = media.wav_info(make_wav(2.0))
    assert info["duration"] == 2.0 and len(info["peaks"]) == 48 and all(0 <= p <= 1 for p in info["peaks"])
    assert max(info["peaks"]) == 1.0  # scaled to the loudest bar
    quiet = media.wav_info(make_wav(1.0, loud=0.0))
    assert quiet["duration"] == 1.0 and set(quiet["peaks"]) == {0.0}
    with pytest.raises(ValueError):
        media.wav_info(b"not a wav")


async def test_media_route(isolated_settings, tmp_path, monkeypatch):
    from odie.app.main import create_app
    from tests.test_api import FakeRunner
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    m = media.save(make_wav(1.0), "memo", "wav", "audio/wav", "Hello")
    app = create_app(runner=FakeRunner(), store=s)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c, app.router.lifespan_context(app):
        r = await c.get(f"/api/media/{m['id']}")
        assert r.status_code == 200 and r.headers["content-type"] == "audio/wav" and len(r.content) == m["size"]
        part = await c.get(f"/api/media/{m['id']}", headers={"Range": "bytes=0-99"})
        assert part.status_code == 206 and len(part.content) == 100
        assert (await c.get("/api/media/0123456789abcdef")).status_code == 404
        assert (await c.get("/api/media/..%2F..%2Fassistant.db")).status_code == 404
        monkeypatch.setenv("ODIE_PAIRING", "on")
        assert (await c.get(f"/api/media/{m['id']}")).status_code == 401  # behind pairing, like every API


MEMO = {"id": "0123456789abcdef", "kind": "memo", "title": "Good morning", "mime": "audio/wav", "size": 10, "created": 1.0, "duration": 1.5}


def _call(name):
    return Event(author="odie", content=types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(name=name, args={}))]))


def _response(name, response):
    return Event(author="odie", content=types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(name=name, response=response))]))


def _text(author, text):
    return Event(author=author, content=types.Content(role="user" if author == "user" else "model", parts=[types.Part(text=text)]))


def test_media_events_stream():
    from odie.app.runner import event_to_sse, media_of
    out = event_to_sse(_response("speak", {"result": "The memo is under your reply.", "media": MEMO}))
    assert out == [{"type": "tool_done", "tool": "speak"}, {"type": "media", "media": MEMO}]
    assert event_to_sse(_response("now", {"result": "9:31"})) == [{"type": "tool_done", "tool": "now"}]
    assert media_of({"media": {"id": "nope"}}) is None and media_of("text") is None and media_of({"media": MEMO}) == MEMO


def test_history_keeps_media_after_later_turns():
    from odie.agent.compaction import compact
    from odie.app.runner import events_to_history
    events = [_text("user", "send me a voice memo saying good morning"), _call("speak"),
              _response("speak", {"result": "The memo is under your reply. " * 20, "media": MEMO}), _text("odie", "Here you go."),
              _text("user", "thanks"), _text("odie", "Any time.")]
    squeezed = compact([e.content for e in events], limit=200, keep=0)  # what a cut does to the model's copy
    assert [p.text for c in squeezed[:2] for p in c.parts] == ["send me a voice memo saying good morning", "Here you go."]
    items = events_to_history(events)
    reply = next(i for i in items if i["role"] == "odie" and i["text"] == "Here you go.")
    assert reply["media"] == [MEMO] and reply["tools"] == ["speak"]
    assert all("media" not in i for i in items if i is not reply)
