"""A voice server, named by its address: any server with the OpenAI audio API (/v1/audio/speech,
/v1/audio/transcriptions, /v1/models). voiced (one local server for every voice model, which loads a model when it is
asked for and unloads it when idle) is the one Odie expects, and it also describes each model's voices and styles in
its listing. Odie never starts or installs the server; it only asks it."""
from __future__ import annotations

import asyncio
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import httpx

DEFAULT_URL = "http://127.0.0.1:12000"
CHECK_WAIT = 2.0     # seconds to wait when only asking whether the server is there
SPEAK_WAIT = 300.0   # a long sentence on a model that has to load first
HEAR_WAIT = 120.0


@dataclass(frozen=True)
class Model:
    """One model the server offers. kind: "tts" (speaks) or "stt" (hears). voices: {"id", "label", "group", "note"}
    as Settings shows them. styles: the tones it can speak in (Libra's warm, wry, …), empty for most."""
    name: str
    kind: str
    voices: list[dict] = field(default_factory=list)
    styles: list[str] = field(default_factory=list)


def base(url: str) -> str:
    """The server's address without spaces, a trailing slash or /v1, so every path is added the same way.
    " http://h:12000/v1/ " -> "http://h:12000"; "http://h:12000" -> unchanged."""
    cleaned = url.strip().rstrip("/")
    return cleaned.removesuffix("/v1")


def url_problem(url: str) -> str | None:
    """Whether a typed server address can be used: None when it can, else what's wrong.
    "http://127.0.0.1:12000" -> None; "http://studio.local:12000/v1" -> None; "studio.local:12000" -> "Start the
    address with http:// …"; "" -> "Type the voice server's address first."."""
    typed = url.strip()
    if not typed:
        return "Type the voice server's address first."
    if not re.match(r"^https?://[A-Za-z0-9.\-\[\]:]+(:\d+)?(/v1)?/?$", typed):
        return f"Start the address with http:// and give only the host and port, for example {DEFAULT_URL}"
    return None


async def available(url: str, transport: httpx.AsyncBaseTransport | None = None) -> bool:
    """Whether a voice server answers at `url`: its /health, else its model list (a server that has no /health).
    voiced running -> True; nothing on the port -> False."""
    root = base(url)
    try:
        async with httpx.AsyncClient(timeout=CHECK_WAIT, transport=transport) as client:
            reply = await client.get(f"{root}/health")
            if reply.status_code == 200:
                return True
            reply = await client.get(f"{root}/v1/models")
    except httpx.HTTPError:
        return False
    return reply.status_code == 200


def _voice(listed) -> dict:
    """One voice as Settings shows it, from the server's entry: a name with gender and accent, or a plain name.
    {"name": "bm_george", "gender": "male", "accent": "British"} -> id bm_george, label "Bm_george", group male,
    note British; "zoey" -> id zoey, label "Zoey", no group or note."""
    if isinstance(listed, str):
        return {"id": listed, "label": listed.capitalize(), "group": "", "note": ""}
    name = str(listed.get("name") or listed.get("id") or "")
    return {"id": name, "label": name.capitalize(), "group": str(listed.get("gender") or ""),
            "note": str(listed.get("accent") or "")}


def _model(entry: dict) -> Model:
    """A model from one entry of the listing. Without a kind (a server that only follows OpenAI's shape) it counts as a
    speaking model; without a usage block it lists no voices or styles."""
    usage = entry.get("usage") or {}
    voices = [_voice(v) for v in usage.get("voices") or []]
    styles = [str(s) for s in usage.get("styles") or []]
    return Model(str(entry.get("id")), str(entry.get("kind") or "tts"), voices, styles)


async def models(url: str, transport: httpx.AsyncBaseTransport | None = None) -> list[Model]:
    """Every model the server lists, in its order. An error reaching it propagates (the caller says it's down)."""
    async with httpx.AsyncClient(timeout=CHECK_WAIT * 3, transport=transport) as client:
        reply = await client.get(f"{base(url)}/v1/models")
    reply.raise_for_status()
    return [_model(entry) for entry in reply.json().get("data") or []]


def refusal(reply: httpx.Response) -> str:
    """The message in a refused request (OpenAI's error shape), else the start of the plain body."""
    try:
        return str(reply.json()["error"]["message"])
    except (ValueError, KeyError, TypeError):
        return reply.text[:200]


async def speak(url: str, model: str, voice: str, text: str, style: str | None = None, extra: dict | None = None,
                transport: httpx.AsyncBaseTransport | None = None) -> bytes:
    """`text` spoken by `model` in `voice`, as a WAV. `style` is the tone for a model that has styles; `extra` holds
    any other field that model takes (Libra's trim). A refused request (4xx) raises ValueError with the server's
    words; a server that isn't there raises httpx.ConnectError."""
    body = {"model": model, "input": text, "voice": voice, "response_format": "wav"}
    if style:
        body["style"] = style
    body.update(extra or {})
    async with httpx.AsyncClient(timeout=SPEAK_WAIT, transport=transport) as client:
        reply = await client.post(f"{base(url)}/v1/audio/speech", json=body)
    if 400 <= reply.status_code < 500:
        raise ValueError(refusal(reply))
    reply.raise_for_status()
    return reply.content


async def to_wav16k(audio: bytes) -> bytes:
    """Any recording (a phone's mp4/aac, a browser's webm/opus) as 16 kHz mono 16-bit WAV, the one format every
    hearing model decodes. ffmpeg writes to a file because a WAV piped out has no lengths in its header."""
    with tempfile.TemporaryDirectory() as folder:
        out = Path(folder) / "heard.wav"
        process = await asyncio.create_subprocess_exec(
            "ffmpeg", "-loglevel", "error", "-i", "pipe:0", "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(out),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE)
        _, problem = await process.communicate(audio)
        if process.returncode != 0:
            raise ValueError(f"Couldn't read that recording: {problem.decode(errors='replace')[:200]}")
        return out.read_bytes()


async def transcribe(url: str, model: str, audio: bytes, filename: str, mime: str,
                     transport: httpx.AsyncBaseTransport | None = None) -> str:
    """The words in a recording, heard by `model`. The recording is made a 16 kHz WAV first (to_wav16k), so `filename`
    and `mime` only say what came in."""
    wav = await to_wav16k(audio)
    files = {"file": ("speech.wav", wav, "audio/wav")}
    fields = {"model": model, "response_format": "json"}
    async with httpx.AsyncClient(timeout=HEAR_WAIT, transport=transport) as client:
        reply = await client.post(f"{base(url)}/v1/audio/transcriptions", files=files, data=fields)
    if 400 <= reply.status_code < 500:
        raise ValueError(refusal(reply))
    reply.raise_for_status()
    return str(reply.json().get("text") or "").strip()
