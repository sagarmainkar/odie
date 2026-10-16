"""The voice comes first: each scene is spoken in the voice chosen in Settings, and the length of each spoken scene
(not an estimate) is what times the page."""
import io
import wave

import httpx

from odie import media, voice
from odie.store.db import Store
from odie.video import timeline

NO_ANSWER = "Odie's voice didn't answer (Settings → Voice): "


def first_line(error: Exception) -> str:
    """An error's first line, or its kind when it has no words: httpx's "Client error '401 Unauthorized' for url …
    \nFor more information …" -> its first line; ConnectError("") -> "ConnectError"."""
    lines = str(error).strip().splitlines()
    if not lines:
        return type(error).__name__
    return lines[0]


def wav_seconds(wav: bytes) -> float:
    """A WAV's exact length in seconds, from its frames and rate: 36,000 frames at 24,000 a second -> 1.5."""
    with wave.open(io.BytesIO(wav)) as w:
        return w.getnframes() / w.getframerate()


async def narrate(store: Store, narration: list[str], voice_name: str = "",
                  transport: httpx.AsyncBaseTransport | None = None) -> tuple[bytes, list[float]]:
    """One WAV of the whole narration (a breath of quiet between scenes) and each scene's length in seconds.
    `voice_name` is a voice of the engine chosen in Settings (ValueError, naming Settings, for any other, before
    anything is spoken); empty means the voice chosen in Settings. A voice that can't be reached or says no is a
    VoiceUnavailable in one line: "Odie's voice didn't answer (Settings → Voice): Connection refused"."""
    voice_id = None
    if voice_name:
        voice_id = voice.voice_in_chosen_engine(store, voice_name)["id"]

    parts = []
    for text in narration:
        try:
            parts.append(await voice.speak_wav(store, text, voice=voice_id, transport=transport))
        except httpx.HTTPError as e:
            raise voice.VoiceUnavailable(NO_ANSWER + first_line(e)) from e

    lengths = [wav_seconds(part) for part in parts]
    gap_ms = int(timeline.BREATH * 1000)
    joined, _starts = media.join_wavs(parts, gap_ms=gap_ms)
    return joined, lengths
