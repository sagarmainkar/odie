"""Media in replies: what a tool makes to play, see or download (a voice memo, a podcast, a screenshot, a file).

- Each file is stored at <data>/media/<id>.<ext>, with a JSON sidecar beside it (<id>.json) holding its kind, title,
  type, size, creation time and kind-specific details.
- It's served by GET /api/media/{id}, behind device pairing like every API.
- A tool hands it to the chat by returning {"media": <the sidecar>}: the runner streams it as it's made, and history
  keeps it with its reply."""
from __future__ import annotations

import array
import io
import json
import os
import re
import secrets
import sys
import time
import wave
from pathlib import Path

ID_RE = re.compile(r"^[0-9a-f]{16}\Z")
KINDS = ("memo", "podcast", "screenshot", "file", "page", "link", "turn", "tracker", "picture", "video", "audio")  # picture/video/audio: a file a tool made, shown or played inline (odie.agent.tools.files)  # link: a UPI app button; turn: "your turn" to sign in  # page: a deck's slide preview (odie.decks)  # tracker: "check this page signed in?" (odie.trackers.signed_in)


def media_dir() -> Path:
    from odie import config
    return config.settings.data_dir / "media"


def _write(path: Path, data: bytes) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def save(data: bytes, kind: str, ext: str, mime: str, title: str, meta: dict | None = None) -> dict:
    """Stores the file and returns its description (what a tool puts under "media"). The sidecar is written last, so
    a half-written file is never served."""
    if kind not in KINDS or not re.fullmatch(r"[a-z0-9]{1,8}", ext) or ext == "json":  # .json is the sidecar's name
        raise ValueError(f"unknown media kind or extension: {kind}, {ext}")
    d = media_dir()
    d.mkdir(parents=True, exist_ok=True)
    mid = secrets.token_hex(8)
    _write(d / f"{mid}.{ext}", data)
    m = {**(meta or {}), "id": mid, "kind": kind, "title": " ".join(title.split())[:120], "mime": mime, "size": len(data),
         "created": round(time.time(), 3), "ext": ext}
    _write(d / f"{mid}.json", json.dumps(m).encode())
    return m


def get(mid: str) -> tuple[Path, dict] | None:
    """The file and its description, for a well-formed id that was saved; None otherwise."""
    if not isinstance(mid, str) or not ID_RE.match(mid):
        return None
    d = media_dir()
    try:
        m = json.loads((d / f"{mid}.json").read_text())
    except (OSError, ValueError):
        return None
    path = d / f"{mid}.{m.get('ext', '')}"
    return (path, m) if path.is_file() else None


def update(mid: str, extra: dict) -> dict | None:
    """Merges keys into a saved item's description (a deck adds its previews and PowerPoint); the new description."""
    got = get(mid)
    if got is None:
        return None
    m = {**got[1], **extra}
    _write(media_dir() / f"{mid}.json", json.dumps(m).encode())
    return m


def wav_info(data: bytes, bars: int = 48) -> dict:
    """A WAV's length in seconds (one decimal) and `bars` loudness peaks scaled to the loudest (0 to 1), for the
    waveform. ValueError for anything that isn't 16-bit PCM WAV."""
    try:
        with wave.open(io.BytesIO(data)) as w:
            if w.getsampwidth() != 2:
                raise ValueError("only 16-bit audio")
            rate, channels, raw = w.getframerate(), w.getnchannels(), w.readframes(w.getnframes())
    except (wave.Error, EOFError) as e:
        raise ValueError(f"not a WAV: {e}") from None
    samples = array.array("h")
    samples.frombytes(raw[: len(raw) // 2 * 2])
    if sys.byteorder == "big":
        samples.byteswap()
    frames = len(samples) // max(channels, 1)
    step = max(1, len(samples) // bars)
    peaks = [max((abs(x) for x in samples[i * step:(i + 1) * step]), default=0) for i in range(bars)]
    top = max(peaks) or 1
    return {"duration": round(frames / rate, 1) if rate else 0.0, "peaks": [round(p / top, 3) if max(peaks) else 0.0 for p in peaks]}


def join_wavs(parts: list[bytes], gap_ms: int = 300) -> tuple[bytes, list[float]]:
    """The parts one after another, with `gap_ms` of silence between them, and each part's start in seconds (one
    decimal). ValueError when there's nothing to join or the parts' formats differ."""
    if not parts:
        raise ValueError("nothing to join")
    params, chunks, starts, t = None, [], [], 0.0
    for p in parts:
        try:
            with wave.open(io.BytesIO(p)) as w:
                fmt = (w.getnchannels(), w.getsampwidth(), w.getframerate())
                data = w.readframes(w.getnframes())
        except (wave.Error, EOFError) as e:
            raise ValueError(f"not a WAV: {e}") from None
        if params is None:
            params = fmt
        elif fmt != params:
            raise ValueError("the parts' audio formats differ")
        channels, width, rate = params
        if chunks:
            chunks.append(b"\x00" * (int(rate * gap_ms / 1000) * channels * width))
            t += gap_ms / 1000
        starts.append(round(t, 1))
        chunks.append(data)
        t += len(data) / (channels * width * rate)
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(params[0])
        w.setsampwidth(params[1])
        w.setframerate(params[2])
        w.writeframes(b"".join(chunks))
    return out.getvalue(), starts


def pcm_to_wav(pcm: bytes, rate: int = 24000) -> bytes:
    """Raw 16-bit mono PCM (what OpenAI's speech sends as "pcm": 24 kHz) as a WAV."""
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm[: len(pcm) // 2 * 2])
    return out.getvalue()
