"""Odie's own voice worker: Odie starts it as a child process (from its own voice_server folder, on its own port),
restarts it if it dies, stops it with itself (and it dies with Odie however Odie exits), reuses another Odie's worker
already on the port, and never uses some other service that happens to answer there (another app's voice server, say)."""
import asyncio
import os
import socket
import subprocess
import sys
import time

import pytest

from odie import voice
from odie.voice_worker import VoiceWorker

FAKE = '''
import json, os, sys, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
port, title = int(sys.argv[1]), sys.argv[2]
if os.environ.get("ODIE_PARENT_FD"):  # the same contract as voice_server/server.py: gone when the parent is
    fd = int(os.environ["ODIE_PARENT_FD"])
    threading.Thread(target=lambda: (os.read(fd, 1), os._exit(0)), daemon=True).start()
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if title == "html":
            self.send_response(404); self.end_headers(); self.wfile.write(b"<html>not found</html>"); return
        body = {"/health": {"ok": True}, "/openapi.json": {"info": {"title": title}}}.get(self.path)
        self.send_response(200 if body else 404)
        self.end_headers()
        if body: self.wfile.write(json.dumps(body).encode())
    def log_message(self, *a): pass
HTTPServer(("127.0.0.1", port), H).serve_forever()
'''


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def answering(port: int, timeout: float = 10.0) -> bool:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.05)
    return False


@pytest.fixture
def fake(tmp_path):
    script = tmp_path / "fake_voice.py"
    script.write_text(FAKE)
    return script


@pytest.fixture
def workers():
    made = []
    yield made
    for w in made:  # a failed test leaves nothing running
        if w.proc is not None and w.proc.poll() is None:
            w.proc.kill()


def worker(fake, port, made, title="odie-voice"):
    w = VoiceWorker(port=port, cmd=[sys.executable, str(fake), str(port), title], log=fake.parent / "voice.log")
    made.append(w)
    return w


def other(fake, port, title):
    p = subprocess.Popen([sys.executable, str(fake), str(port), title])
    assert answering(port)
    return p


async def test_starts_and_stops_its_own_worker(fake, workers):
    w = worker(fake, free_port(), workers)
    await w.start()
    assert await w.ready(10) and w.proc is not None and await w.healthy()
    proc = w.proc
    await w.stop()
    assert proc.poll() is not None and not await w.healthy()


async def test_reuses_another_odies_worker(fake, workers):
    port = free_port()
    running = other(fake, port, "odie-voice")
    try:
        w = worker(fake, port, workers)
        await w.start()
        assert w.proc is None and await w.healthy()  # nothing spawned: the one there is Odie's
        await w.stop()
        assert running.poll() is None  # and it isn't ours to stop
    finally:
        running.kill()


async def test_never_uses_some_other_service_on_its_port(fake, workers):
    port = free_port()
    stranger = other(fake, port, "other-voice")
    try:
        w = worker(fake, port, workers)
        await w.start()
        assert w.proc is None and not await w.healthy() and "other-voice" in w.problem
    finally:
        stranger.kill()


async def test_a_service_that_isnt_fastapi_is_someone_else(fake, workers):
    port = free_port()
    html = other(fake, port, "html")
    try:
        w = worker(fake, port, workers)
        await w.start()
        assert w.proc is None and w.problem and not await w.ensure(2) and w.spawned == 0
    finally:
        html.kill()


async def test_restarts_after_a_crash(fake, workers):
    w = worker(fake, free_port(), workers)
    await w.start()
    assert await w.ready(10)
    w.proc.kill()
    w.proc.wait()
    assert await w.ensure(10)  # the next speech asks for it: it comes back
    await w.stop()


async def test_the_worker_dies_with_its_odie(fake, workers):
    w = worker(fake, free_port(), workers)
    await w.start()
    assert await w.ready(10)
    proc = w.proc
    os.close(w._parent_w)  # what Odie dying (a kill -9, a second Ctrl-C) does to the pipe it holds
    for _ in range(50):
        if proc.poll() is not None:
            break
        await asyncio.sleep(0.1)
    assert proc.poll() is not None


async def test_two_at_once_start_one_worker(fake, workers):
    w = worker(fake, free_port(), workers)
    assert all(await asyncio.gather(w.ensure(10), w.ensure(10), w.ensure(10)))
    assert w.spawned == 1 and w.proc.poll() is None
    await w.stop()


async def test_a_broken_environment_never_stops_odie(tmp_path):
    w = VoiceWorker(port=free_port(), cmd=[str(tmp_path / "gone" / "uvicorn")], log=tmp_path / "voice.log")
    await w.start()  # no exception: voice never decides whether Odie starts
    assert w.proc is None and "couldn't start" in w.problem and not await w.ensure(1)


async def test_without_its_environment_local_voice_is_off(tmp_path):
    w = VoiceWorker(folder=tmp_path / "voice_server", port=free_port())
    await w.start()
    assert w.proc is None and not w.installed and "uv sync" in w.problem and not await w.ensure(1)


async def test_speech_says_why_local_voice_is_off(isolated_settings, monkeypatch, tmp_path):
    from odie import voice_worker
    monkeypatch.setattr(voice_worker, "current", VoiceWorker(folder=tmp_path / "voice_server", port=free_port()))
    with pytest.raises(voice.VoiceUnavailable) as e:
        await voice.local_tts("kokoro", "hello", "af_heart")
    assert "uv sync" in str(e.value)
    assert await voice.local_available() is False


def test_the_voice_calls_go_to_odies_port(monkeypatch):
    monkeypatch.setenv("ODIE_VOICE_PORT", "8999")
    assert voice.local_url() == "http://127.0.0.1:8999"
    monkeypatch.delenv("ODIE_VOICE_PORT")
    assert voice.local_url() == "http://127.0.0.1:8771"  # its own port, not the 8770 other voice servers use
