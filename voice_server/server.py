"""Odie's local voice service. Two engines, loaded on first use:

- kokoro: Kokoro-82M (mlx-community/Kokoro-82M-bf16). About 4x faster than real time on an Apple silicon Mac. No expressions.
- maya1:  Maya1 3B (0xhb/maya1-mlx-8bit). About 1.8x slower than real time. Voice described in words; expression tags
          such as <laugh> <sigh> <whisper> <excited>. Unloaded after IDLE_UNLOAD seconds to give its memory back.

Listens on 127.0.0.1 only. Odie's server calls it; the phone never does. Odie starts it by itself (odie/voice_worker.py)
on ODIE_VOICE_PORT (8771) and it exits when that Odie does. By hand, for trying it alone:

    uv run uvicorn server:app --host 127.0.0.1 --port 8771
"""
from __future__ import annotations

import asyncio
import gc
import glob
import os
import tempfile
import threading
import time

# Kokoro's phonemizer: espeakng_loader's bundled library has a broken built-in data path; use Homebrew's espeak-ng.
import misaki.espeak  # noqa: F401  (sets the bundled library; overridden below)
from phonemizer.backend.espeak.wrapper import EspeakWrapper

if os.path.exists("/opt/homebrew/lib/libespeak-ng.dylib"):
    EspeakWrapper.set_library("/opt/homebrew/lib/libespeak-ng.dylib")
    EspeakWrapper.set_data_path("/opt/homebrew/share/espeak-ng-data")

from fastapi import FastAPI, HTTPException  # noqa: E402
from fastapi.responses import Response  # noqa: E402
from pydantic import BaseModel  # noqa: E402

MODELS = {"kokoro": "mlx-community/Kokoro-82M-bf16", "maya1": "0xhb/maya1-mlx-8bit"}
IDLE_UNLOAD = {"maya1": 20 * 60}
_loaded: dict[str, object] = {}
_last_used: dict[str, float] = {}
_locks = {k: threading.Lock() for k in MODELS}  # one generation at a time per engine (GPU)

app = FastAPI(title="odie-voice")


class TtsIn(BaseModel):
    engine: str
    text: str
    voice: str = ""
    lang: str = "a"          # kokoro: a=American, b=British, h=Hindi-accented


def _model(engine: str):
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
    return {"ok": True, "loaded": sorted(_loaded), "engines": sorted(MODELS)}


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
