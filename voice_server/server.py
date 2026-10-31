"""Odie's local voice service. Two engines, loaded on first use:

- kokoro: Kokoro-82M (mlx-community/Kokoro-82M-bf16). About 4x faster than real time on an Apple silicon Mac. No expressions.
- maya1:  Maya1 3B (0xhb/maya1-mlx-8bit). About 1.8x slower than real time. Voice described in words; expression tags
          such as <laugh> <sigh> <whisper> <excited>. Unloaded after IDLE_UNLOAD seconds to give its memory back.

And hearing, on the WebSocket /stt/stream: 16 kHz 16-bit mono PCM in, speech on/off and words out (hearing.py), with
Silero VAD and Parakeet TDT 0.6B v3 (mlx-community/parakeet-tdt-0.6b-v3), loaded on the first stream and unloaded after
10 idle minutes.

Every model import is inside a function, so Odie's main environment (no misaki, mlx or torch) can import this file in
its tests.

Listens on 127.0.0.1 only. Odie's server calls it; the phone never does. Odie starts it by itself (odie/voice_worker.py)
on ODIE_VOICE_PORT (8771) and it exits when that Odie does. By hand, for trying it alone:

    uv run uvicorn server:app --host 127.0.0.1 --port 8771
"""
from __future__ import annotations

import asyncio
import contextlib
import gc
import glob
import importlib.util
import json
import os
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np
from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.responses import Response
from pydantic import BaseModel

if __package__:
    from .hearing import Hearing   # imported from the repo as voice_server.server (Odie's tests)
else:
    from hearing import Hearing    # run from this folder: uvicorn server:app

MODELS = {"kokoro": "mlx-community/Kokoro-82M-bf16", "maya1": "0xhb/maya1-mlx-8bit"}
HEARING_MODEL = "mlx-community/parakeet-tdt-0.6b-v3"
IDLE_UNLOAD = {"maya1": 20 * 60, "hearing": 10 * 60}
_loaded: dict[str, object] = {}
_last_used: dict[str, float] = {}
_locks = {k: threading.Lock() for k in [*MODELS, "hearing"]}  # one generation (or transcription) at a time per engine (GPU)
_espeak_ready = False

app = FastAPI(title="odie-voice")


class TtsIn(BaseModel):
    engine: str
    text: str
    voice: str = ""
    lang: str = "a"          # kokoro: a=American, b=British, h=Hindi-accented


def _set_up_espeak() -> None:
    """Kokoro's phonemizer: espeakng_loader's bundled library has a broken built-in data path; use Homebrew's espeak-ng.
    Done once, before the first TTS model loads."""
    global _espeak_ready
    if _espeak_ready:
        return
    import misaki.espeak  # noqa: F401  (sets the bundled library; overridden below)
    from phonemizer.backend.espeak.wrapper import EspeakWrapper

    if Path("/opt/homebrew/lib/libespeak-ng.dylib").exists():
        EspeakWrapper.set_library("/opt/homebrew/lib/libespeak-ng.dylib")
        EspeakWrapper.set_data_path("/opt/homebrew/share/espeak-ng-data")
    _espeak_ready = True


def _model(engine: str):
    _set_up_espeak()
    from mlx_audio.tts.utils import load_model
    if engine not in _loaded:
        _loaded[engine] = load_model(MODELS[engine])
    _last_used[engine] = time.time()
    return _loaded[engine]


def _synth(req: TtsIn) -> bytes:
    from mlx_audio.tts.generate import generate_audio
    with _locks[req.engine]:
        model = _model(req.engine)
        with tempfile.TemporaryDirectory() as d:
            prefix = os.path.join(d, "out")
            kw = {"voice": req.voice or "af_heart", "lang_code": req.lang} if req.engine == "kokoro" else {}
            generate_audio(model=model, text=req.text, file_prefix=prefix, audio_format="wav", verbose=False, join_audio=True, **kw)
            files = sorted(glob.glob(prefix + "*.wav"))
            if not files:
                raise RuntimeError("no audio produced")
            with open(files[0], "rb") as f:
                return f.read()


@app.get("/health")
def health():
    return {"ok": True, "loaded": sorted(_loaded), "engines": sorted(MODELS), "hearing": hearing_possible()}


@app.post("/tts")
async def tts(req: TtsIn):
    if req.engine not in MODELS:
        raise HTTPException(400, f"unknown engine {req.engine}")
    if not req.text.strip():
        raise HTTPException(400, "empty text")
    try:
        audio = await asyncio.to_thread(_synth, req)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(500, f"{type(e).__name__}: {str(e)[:200]}")
    return Response(audio, media_type="audio/wav")


# --- Hearing: /stt/stream ---


_hearing_possible: bool | None = None


def hearing_possible() -> bool:
    """Whether this environment can hear: silero_vad and mlx_audio.stt are installed. Looked up once, then remembered.
    Only looked up, not imported (importing torch would make the first /health take seconds).
    The voice server's own environment -> True; Odie's main environment (no torch, no mlx) -> False."""
    global _hearing_possible
    if _hearing_possible is None:
        try:
            found = importlib.util.find_spec("silero_vad") is not None and importlib.util.find_spec("mlx_audio.stt") is not None
        except ImportError:  # mlx_audio itself missing: find_spec of a submodule imports its parent
            found = False
        _hearing_possible = found
    return _hearing_possible


def load_hearing() -> tuple[Callable, Callable]:
    """The two models behind one stream's Hearing, as plain callables: (vad, transcribe).

    Parakeet (2.5 GB) loads once and is shared by every stream; the janitor unloads it after 10 idle minutes. Silero
    is tiny (12 ms to load once torch is up) but keeps state from chunk to chunk, so each stream gets its own, fresh:
    two streams may be open at once and must not mix their state. Transcriptions share the GPU, so each one takes the
    hearing lock; the lock is per call, never per stream."""
    import mlx.core as mx
    import torch
    from mlx_audio.stt.utils import load_model
    from silero_vad import load_silero_vad

    with _locks["hearing"]:
        if "hearing" not in _loaded:
            _loaded["hearing"] = load_model(HEARING_MODEL)
        parakeet = _loaded["hearing"]
        silero = load_silero_vad()
    _last_used["hearing"] = time.time()

    def vad(chunk: np.ndarray) -> float:
        # 512 float32 samples -> the probability they are speech, e.g. a spoken vowel -> 0.98, room hum -> 0.01.
        # The stream's own Silero (state from its previous chunks), so no lock: it is never shared.
        _last_used["hearing"] = time.time()
        with torch.inference_mode():
            return float(silero(torch.from_numpy(chunk), 16000))

    def transcribe(audio: np.ndarray) -> str:
        # A whole utterance's float32 samples -> its text, e.g. 2 s of speech -> "what is the weather".
        with _locks["hearing"]:
            _last_used["hearing"] = time.time()
            result = parakeet.generate(mx.array(audio))
        return result.text.strip()

    return vad, transcribe


def is_audio(message: dict) -> bool:
    """Whether a WebSocket message is a binary frame (PCM for the hearing).
    {"type": "websocket.receive", "bytes": b"..."} -> True; {"type": "websocket.receive", "text": "..."} -> False."""
    return message["type"] == "websocket.receive" and message.get("bytes") is not None


def asks_to_end(message: dict) -> bool:
    """Whether a WebSocket message is the client's end of the stream: the text {"type": "end"}.
    text '{"type": "end"}' -> True; text '{"type": "hello"}' -> False; text 'end' (not JSON) -> False; bytes -> False."""
    text = message.get("text")
    if message["type"] != "websocket.receive" or text is None:
        return False
    try:
        sent = json.loads(text)
    except ValueError:
        return False
    return isinstance(sent, dict) and sent.get("type") == "end"


async def _send_events(ws, events: list[dict]) -> None:
    for event in events:
        await ws.send_text(json.dumps(event))


async def serve_hearing(ws, hearing: Hearing) -> None:
    """The protocol for one stream, over any object with receive(), send_text() and close() (Starlette's WebSocket,
    or a fake in the tests). Says {"type": "ready"}, then feeds each binary frame to the hearing and sends the events
    it makes, as JSON texts, in order. The text {"type": "end"} closes an open utterance (its speech off and final go
    out) and closes the socket. If the client goes away instead, there is nobody to send to: the hearing is just
    forgotten. Other texts are ignored."""
    await ws.send_text(json.dumps({"type": "ready"}))
    while True:
        message = await ws.receive()
        if message["type"] == "websocket.disconnect":
            hearing.reset()
            return
        if is_audio(message):
            events = await asyncio.to_thread(hearing.feed, message["bytes"])
            await _send_events(ws, events)
        elif asks_to_end(message):
            break
    events = await asyncio.to_thread(hearing.end)
    await _send_events(ws, events)
    await ws.close()


class Inbox:
    """The socket, with everything the client sends read straight away into a queue by a task of its own. While the
    models load, the client's audio waits in the queue; serve_hearing then reads it in order, so nothing said during
    the load is lost. Sending and closing go straight to the socket."""

    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.queue: asyncio.Queue[dict] = asyncio.Queue()
        self.reader = asyncio.create_task(self.read_all())

    async def read_all(self) -> None:
        try:
            while True:
                message = await self.ws.receive()
                self.queue.put_nowait(message)
                if message["type"] == "websocket.disconnect":
                    return
        except Exception:  # noqa: BLE001  (the socket broke: tell the reader the client is gone)
            self.queue.put_nowait({"type": "websocket.disconnect"})

    async def receive(self) -> dict:
        return await self.queue.get()

    async def send_text(self, text: str) -> None:
        await self.ws.send_text(text)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        await self.ws.close(code, reason)

    def stop(self) -> None:
        self.reader.cancel()


@app.websocket("/stt/stream")
async def stt_stream(ws: WebSocket):
    await ws.accept()
    inbox = Inbox(ws)
    try:
        vad, transcribe = await asyncio.to_thread(load_hearing)  # seconds the first time; the client's audio queues
        await serve_hearing(inbox, Hearing(vad=vad, transcribe=transcribe))
    except Exception as e:  # noqa: BLE001
        with contextlib.suppress(Exception):  # the client may already be gone
            await ws.send_text(json.dumps({"type": "error", "text": f"{type(e).__name__}: {str(e)[:200]}"}))
            await ws.close(1011)
    finally:
        inbox.stop()


async def _janitor():
    while True:
        await asyncio.sleep(60)
        for engine, idle in IDLE_UNLOAD.items():
            if engine in _loaded and time.time() - _last_used.get(engine, 0) > idle and not _locks[engine].locked():
                _loaded.pop(engine, None)
                gc.collect()


def _watch_parent() -> None:
    """Started by Odie: exit when that Odie is gone, however it went (the pipe it holds closes)."""
    fd = os.environ.get("ODIE_PARENT_FD")
    if fd:
        def wait():
            try:
                os.read(int(fd), 1)
            finally:
                os._exit(0)
        threading.Thread(target=wait, daemon=True).start()


_watch_parent()


@app.on_event("startup")
async def _start():
    asyncio.create_task(_janitor())
