"""The voice comes first: each scene is spoken in the voice chosen in Settings, and the length of each spoken scene
(not an estimate) is what times the page. A scene marked with "|" (odie.video.beats) is spoken one phrase at a time,
and the measured phrases give the seconds at which each beat starts."""
import io
import wave

import httpx

from odie import media, voice
from odie.store.db import Store
from odie.video import beats, timeline

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


async def speak(store: Store, text: str, voice_id: str | None, transport: httpx.AsyncBaseTransport | None) -> bytes:
    """One piece of speech as a WAV; a voice that can't be reached or says no is a VoiceUnavailable in one line."""
    try:
        return await voice.speak_wav(store, text, voice=voice_id, transport=transport)
    except httpx.HTTPError as e:
        raise voice.VoiceUnavailable(NO_ANSWER + first_line(e)) from e


def beat_starts(piece_lengths: list[float]) -> list[float]:
    """Where each phrase starts, in seconds into its scene, from the phrases' lengths: [1.0, 2.0, 0.5] ->
    [0.0, 1.0, 3.0]; one phrase -> [0.0]."""
    starts = []
    t = 0.0
    for length in piece_lengths:
        starts.append(round(t, 3))
        t += length
    return starts


async def narrate(store: Store, narration: list[str], voice_name: str = "",
                  transport: httpx.AsyncBaseTransport | None = None) -> tuple[bytes, list[float], list[list[float]]]:
    """One WAV of the whole narration (a breath of quiet between scenes), each scene's length in seconds, and each
    scene's beat starts (seconds into the scene, the first 0.0). Every phrase of a scene ("A | B") is spoken as its
    own piece and the pieces are joined with no quiet between: phrases of 1.0 s and 2.0 s -> a 3.0 s scene with beats
    [0.0, 1.0]; a scene without marks -> beats [0.0].
    `voice_name` is a voice of the engine chosen in Settings (ValueError, naming Settings, for any other, before
    anything is spoken); empty means the voice chosen in Settings. A voice that can't be reached or says no is a
    VoiceUnavailable in one line: "Odie's voice didn't answer (Settings → Voice): Connection refused"."""
    voice_id = None
    if voice_name:
        voice_id = voice.voice_in_chosen_engine(store, voice_name)["id"]

    scenes = []
    lengths = []
    scene_beats = []
    for text in narration:
        pieces = []
        for phrase in beats.phrases(text):
            pieces.append(await speak(store, phrase, voice_id, transport))
        scene, _piece_starts = media.join_wavs(pieces, gap_ms=0)
        piece_lengths = [wav_seconds(piece) for piece in pieces]
        scenes.append(scene)
        lengths.append(wav_seconds(scene))
        scene_beats.append(beat_starts(piece_lengths))

    gap_ms = int(timeline.BREATH * 1000)
    joined, _starts = media.join_wavs(scenes, gap_ms=gap_ms)
    return joined, lengths, scene_beats
