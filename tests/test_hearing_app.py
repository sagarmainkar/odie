"""The voice server's /stt/stream route, through Starlette's TestClient, with the models replaced by fakes."""
import json
import time

import numpy as np
import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from voice_server import server


def tone(seconds: float) -> bytes:
    t = np.arange(int(16000 * seconds)) / 16000
    return (np.sin(2 * np.pi * 440 * t) * 16000).astype(np.int16).tobytes()


def silence(seconds: float) -> bytes:
    return np.zeros(int(16000 * seconds), np.int16).tobytes()


def fake_models():
    """A VAD that hears the tone (0.9 for a loud chunk, 0.0 for silence) and a recogniser that always hears the same."""
    def vad(chunk):
        if np.abs(chunk).max() > 0.1:
            return 0.9
        return 0.0
    return vad, lambda audio: "what is the weather"


def slow_load():
    time.sleep(0.3)  # a cold load: the client's audio arrives meanwhile
    return fake_models()


def events_until_closed(ws) -> tuple[list[dict], int]:
    """Every event the server sends, then the close code."""
    events = []
    while True:
        try:
            events.append(json.loads(ws.receive_text()))
        except WebSocketDisconnect as closed:
            return events, closed.code


def test_audio_sent_while_the_models_load_is_heard(monkeypatch):
    monkeypatch.setattr(server, "load_hearing", slow_load)
    with TestClient(server.app).websocket_connect("/stt/stream") as ws:
        ws.send_bytes(tone(0.5))      # all of it before "ready": the models are still loading
        ws.send_bytes(silence(0.5))
        ws.send_text(json.dumps({"type": "end"}))
        events, code = events_until_closed(ws)
    assert events[0] == {"type": "ready"}
    assert {"type": "speech", "on": True} in events
    assert {"type": "words", "text": "what is the weather", "final": True} in events
    assert code == 1000


def test_a_failed_load_sends_an_error_and_closes_with_1011(monkeypatch):
    def broken_load():
        raise RuntimeError("no weights")
    monkeypatch.setattr(server, "load_hearing", broken_load)
    with TestClient(server.app).websocket_connect("/stt/stream") as ws:
        events, code = events_until_closed(ws)
    assert events == [{"type": "error", "text": "RuntimeError: no weights"}]
    assert code == 1011


def _settled(expected: int) -> bool:
    """The open-stream count, given a moment to settle (the route ends on the test client's own thread)."""
    for _ in range(50):
        if server._open_streams == expected:
            return True
        time.sleep(0.02)
    return False


def test_an_open_stream_is_counted_so_the_janitor_keeps_parakeet(monkeypatch):
    monkeypatch.setattr(server, "load_hearing", fake_models)
    assert server._open_streams == 0
    with TestClient(server.app).websocket_connect("/stt/stream") as ws:
        assert json.loads(ws.receive_text()) == {"type": "ready"}
        assert server._open_streams == 1
    assert _settled(0)


@pytest.mark.parametrize(("open_streams", "keep"), [(1, True), (0, False)])
def test_hearing_in_use_follows_the_open_streams(open_streams, keep):
    assert server.hearing_in_use(open_streams) is keep
