import asyncio
import json

import numpy as np
import pytest

from voice_server import hearing as hmod
from voice_server.hearing import Hearing


class FakeSocket:
    """What Starlette's WebSocket gives the protocol: bytes and texts in, texts out."""

    def __init__(self, frames):
        self.frames = list(frames)
        self.sent: list[str] = []
        self.closed = False

    async def receive(self):
        if not self.frames:
            return {"type": "websocket.disconnect"}
        frame = self.frames.pop(0)
        return {"type": "websocket.receive", "bytes": frame} if isinstance(frame, bytes) else {"type": "websocket.receive", "text": frame}

    async def send_text(self, text: str):
        self.sent.append(text)

    async def close(self, code: int = 1000, reason: str = ""):
        self.closed = True


def tone(seconds: float) -> bytes:
    t = np.arange(int(16000 * seconds)) / 16000
    return (np.sin(2 * np.pi * 440 * t) * 16000).astype(np.int16).tobytes()


@pytest.mark.asyncio
async def test_ready_then_speech_then_words_then_end():
    from voice_server.server import serve_hearing
    h = Hearing(vad=lambda c: 0.9 if np.abs(c).max() > 0.1 else 0.0, transcribe=lambda a: "what is the weather")
    ws = FakeSocket([tone(0.5), np.zeros(16000 // 2, np.int16).tobytes(), json.dumps({"type": "end"})])
    await serve_hearing(ws, h)
    events = [json.loads(s) for s in ws.sent]
    assert events[0] == {"type": "ready"}
    assert {"type": "speech", "on": True} in events
    assert events[-1] == {"type": "words", "text": "what is the weather", "final": True}
    assert ws.closed
