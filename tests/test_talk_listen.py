"""/api/talk/listen copies frames both ways to the voice server's /stt/stream, behind pairing."""
import asyncio
import json
import socket
import threading
import time

import pytest
import websockets
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from odie import devices, voice, voice_worker
from odie.app.main import create_app
from odie.store.db import Store
from tests.test_api import FakeRunner


@pytest.fixture
def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _app(tmp_path, monkeypatch):
    """Odie with a fresh store, pairing on, a fake brain and no voice worker: the route talks to whatever answers on
    ODIE_VOICE_PORT, as voice.local_available does without a worker."""
    monkeypatch.setenv("ODIE_PAIRING", "on")
    monkeypatch.setattr(voice_worker, "current", None)
    store = Store(tmp_path / "assistant.db")
    store.init_schema()
    return create_app(runner=FakeRunner(), store=store), store


@pytest.fixture
def app_client(isolated_settings, tmp_path, monkeypatch):
    """A paired Mac app: it holds a device cookie and sends no Origin (not a browser)."""
    app, store = _app(tmp_path, monkeypatch)
    key = devices.add_device(store, "Test Mac")
    with TestClient(app) as c:
        c.cookies.set(devices.COOKIE, key)
        yield c


@pytest.fixture
def unpaired_client(isolated_settings, tmp_path, monkeypatch):
    app, _ = _app(tmp_path, monkeypatch)
    with TestClient(app) as c:
        yield c


def fake_voice_server(port: int, got: list, ready: threading.Event, stop: threading.Event):
    """A stand-in /stt/stream: says ready, echoes each binary frame's length as a words event, final on 'end'."""
    async def handle(ws):
        await ws.send(json.dumps({"type": "ready"}))
        async for frame in ws:
            if isinstance(frame, bytes):
                got.append(len(frame))
                await ws.send(json.dumps({"type": "words", "text": f"{len(frame)} bytes", "final": False}))
            else:
                await ws.send(json.dumps({"type": "words", "text": "done", "final": True}))
                return

    async def main():
        async with websockets.serve(handle, "127.0.0.1", port):
            ready.set()
            while not stop.is_set():
                await asyncio.sleep(0.05)

    asyncio.run(main())


@pytest.fixture
def voice_server(monkeypatch, free_port):
    got: list[int] = []
    ready, stop = threading.Event(), threading.Event()
    t = threading.Thread(target=fake_voice_server, args=(free_port, got, ready, stop), daemon=True)
    t.start()
    ready.wait(5)
    monkeypatch.setenv("ODIE_VOICE_PORT", str(free_port))
    yield got
    stop.set()
    t.join(5)


def test_frames_go_through_and_words_come_back(app_client, voice_server):
    with app_client.websocket_connect("/api/talk/listen") as ws:
        assert json.loads(ws.receive_text()) == {"type": "ready"}
        ws.send_bytes(b"\x00" * 640)
        assert json.loads(ws.receive_text()) == {"type": "words", "text": "640 bytes", "final": False}
        ws.send_text(json.dumps({"type": "end"}))
        assert json.loads(ws.receive_text()) == {"type": "words", "text": "done", "final": True}
    assert voice_server == [640]


def test_no_voice_server_closes_with_4503(app_client, monkeypatch, free_port):
    """The route accepts first and then closes with 4503, so the code reaches the Mac (a close before accept is only
    an HTTP 403 there)."""
    monkeypatch.setenv("ODIE_VOICE_PORT", str(free_port))   # nothing listens there
    with pytest.raises(WebSocketDisconnect) as closed, app_client.websocket_connect("/api/talk/listen") as ws:
        ws.receive_text()
    assert closed.value.code == 4503
    assert closed.value.reason == "Odie's local voice isn't running"


def test_an_unpaired_browser_is_refused(unpaired_client):
    with pytest.raises(WebSocketDisconnect) as closed, unpaired_client.websocket_connect("/api/talk/listen"):
        pass
    assert closed.value.code == 4401  # DeviceGate: not paired


def _settled(expected: int) -> bool:
    """The route's count, given a moment to settle (the server side closes on its own thread)."""
    for _ in range(50):
        if voice.hearing_streams == expected:
            return True
        time.sleep(0.02)
    return False


def test_an_open_stream_is_counted_so_the_worker_stays(app_client, voice_server):
    assert voice.hearing_streams == 0
    with app_client.websocket_connect("/api/talk/listen") as ws:
        assert json.loads(ws.receive_text()) == {"type": "ready"}
        assert voice.hearing_streams == 1
    assert _settled(0)


class FakeWorker:
    """voice_worker.VoiceWorker's face as hearing_available sees it: set up or not, running or not."""
    def __init__(self, installed: bool, running: bool, url: str = "http://127.0.0.1:9"):
        self.installed, self.running, self.url = installed, running, url

    async def healthy(self) -> bool:
        return self.running


async def test_hearing_is_offered_while_the_worker_is_merely_set_up(monkeypatch, free_port):
    monkeypatch.setattr(voice_worker, "current", FakeWorker(installed=True, running=False))
    assert await voice.hearing_available()  # read-aloud uses Phonon, so it's stopped: the listen starts it
    monkeypatch.setattr(voice_worker, "current", FakeWorker(installed=False, running=False))
    assert not await voice.hearing_available()


async def test_a_running_worker_says_whether_it_hears(monkeypatch):
    import httpx

    def health(hears):
        return httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True, "hearing": hears}))
    assert await voice.hearing_available(transport=health(True))
    assert not await voice.hearing_available(transport=health(False))
    assert not await voice.hearing_available(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={"ok": True})))


def test_health_says_hearing_to_a_paired_app(app_client, free_port, monkeypatch):
    monkeypatch.setenv("ODIE_VOICE_PORT", str(free_port))  # nothing answers: no hearing
    assert app_client.get("/api/health").json()["hearing"] is False


def test_the_hearing_url_is_the_voice_port_s_stream(monkeypatch):
    monkeypatch.setenv("ODIE_VOICE_PORT", "8771")
    assert voice.hearing_url() == "ws://127.0.0.1:8771/stt/stream"


async def test_settle_leaves_the_worker_running_while_a_talk_listens(monkeypatch):
    stopped = []

    class Worker:
        async def stop(self):
            stopped.append(True)
    monkeypatch.setattr(voice_worker, "current", Worker())
    monkeypatch.setattr(voice, "worker_wanted", lambda store: False)  # read-aloud uses Phonon
    monkeypatch.setattr(voice, "hearing_streams", 1)
    await voice.settle_worker(store=None)
    assert stopped == []
    monkeypatch.setattr(voice, "hearing_streams", 0)
    await voice.settle_worker(store=None)
    assert stopped == [True]
