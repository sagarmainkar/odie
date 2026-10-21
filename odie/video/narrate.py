"""The voice comes first: each scene is spoken in the video voice (voice.video_tts: the pinned video_voice, else the
read-aloud voice chosen in Settings), and the length of each spoken scene (not an estimate) is what times the page.
A scene marked with "|" (odie.video.beats) is spoken one phrase at a time, and the measured phrases give the seconds
at which each beat starts. A scene's first word comes at once: a voice's quiet before it is cut to MAX_LEAD."""
import array
import asyncio
import io
import math
import wave

import httpx

from odie import media, voice
from odie.store.db import Store
from odie.video import beats, timeline

NO_ANSWER = "Odie's voice didn't answer (Settings → Voice): "
MAX_LEAD = 0.2  # seconds of quiet a scene keeps before its first word: a beat, never a lead-in (voices give up to 0.45)
WINDOW = 0.01   # seconds of sound measured at a time when looking for the first word
LOUD = 0.01     # a window is sound when its level is over 1% of full scale (about -40 dB); a voice's quiet is far below


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


def quiet_at_start(wav: bytes) -> float:
    """Seconds of quiet before the first sound of a voice's 16-bit mono WAV, measured in 10 ms windows: a voice that
    waits 0.45 s before its first word -> 0.45; one that starts at once -> 0.0; all quiet -> its whole length. Any
    other kind of WAV -> 0.0 (left as it is)."""
    with wave.open(io.BytesIO(wav)) as w:
        if w.getsampwidth() != 2 or w.getnchannels() != 1:
            return 0.0
        rate = w.getframerate()
        samples = array.array("h", w.readframes(w.getnframes()))
    window = max(1, int(rate * WINDOW))
    loud = 32767 * LOUD
    for start in range(0, len(samples), window):
        chunk = samples[start:start + window]
        level = math.sqrt(sum(x * x for x in chunk) / len(chunk))
        if level > loud:
            return start / rate
    return len(samples) / rate


def lead_cut(wav: bytes, keep: float = MAX_LEAD) -> bytes:
    """The WAV with its quiet before the first word cut to at most `keep` seconds, the rest as it was: 0.45 s of quiet
    -> 0.2 s; 0.1 s -> unchanged (the same bytes); all quiet (nothing said) -> unchanged."""
    quiet = quiet_at_start(wav)
    if quiet <= keep or quiet >= wav_seconds(wav):
        return wav
    with wave.open(io.BytesIO(wav)) as w:
        params = w.getparams()
        w.readframes(round((quiet - keep) * w.getframerate()))  # the quiet over `keep`, skipped
        rest = w.readframes(w.getnframes())
    out = io.BytesIO()
    with wave.open(out, "wb") as cut:
        cut.setparams(params)
        cut.writeframes(rest)
    return out.getvalue()


async def speak(store: Store, text: str, engine: str, voice_id: str, transport: httpx.AsyncBaseTransport | None,
                style: str = "") -> bytes:
    """One piece of speech as a WAV; a voice that can't be reached or says no is a VoiceUnavailable in one line."""
    try:
        return await voice.speak_wav(store, text, voice=voice_id, transport=transport, engine=engine, style=style)
    except httpx.HTTPError as e:
        raise voice.VoiceUnavailable(NO_ANSWER + first_line(e)) from e


OPENAI_AT_ONCE = 6  # OpenAI phrases asked at once: one slow answer then holds up only its own phrase


async def speak_all(store: Store, phrases: list[str], engine: str, voice_id: str,
                    transport: httpx.AsyncBaseTransport | None, style: str = "") -> list[bytes]:
    """Every phrase as a WAV, in the order given. OpenAI's are asked OPENAI_AT_ONCE at a time; the local voice's one at a
    time (its worker speaks one thing at once). 25 phrases at ~40 s each through OpenAI -> about 5 rounds, not 25.
    The first failure stops the rest and is raised."""
    at_once = OPENAI_AT_ONCE if engine == "openai" else 1
    gate = asyncio.Semaphore(at_once)

    async def one(phrase: str) -> bytes:
        async with gate:
            return await speak(store, phrase, engine, voice_id, transport, style)

    tasks = [asyncio.create_task(one(phrase)) for phrase in phrases]
    try:
        return list(await asyncio.gather(*tasks))
    except BaseException:
        for task in tasks:
            task.cancel()
        raise


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
                  transport: httpx.AsyncBaseTransport | None = None,
                  style: str = "") -> tuple[bytes, list[float], list[list[float]]]:
    """One WAV of the whole narration (a breath of quiet between scenes), each scene's length in seconds, and each
    scene's beat starts (seconds into the scene, the first 0.0). Every phrase of a scene ("A | B") is spoken as its
    own piece and the pieces are joined with no quiet between: phrases of 1.0 s and 2.0 s -> a 3.0 s scene with beats
    [0.0, 1.0]; a scene without marks -> beats [0.0]. A scene's first phrase keeps at most MAX_LEAD of quiet before
    its first word (lead_cut), so the video's narration starts at once; a pause before a later phrase stays.
    `voice_name` is a voice of the engine chosen in Settings, when the user asked for one (ValueError, naming Settings,
    for any other, before anything is spoken); empty means the video voice (voice.video_tts). `style` is how an OpenAI
    narrator should sound (the job's own line); empty means Odie's usual instructions, and Kokoro never sees it. A
    voice that can't be reached or says no is a VoiceUnavailable in one line: "Odie's voice didn't answer
    (Settings → Voice): Connection refused"."""
    if voice_name:
        engine, _read_aloud = voice.get_tts(store)
        voice_id = voice.voice_in_chosen_engine(store, voice_name)["id"]
    else:
        engine, voice_id = voice.video_tts(store)

    scene_phrases = [beats.phrases(text) for text in narration]
    every_phrase = [phrase for phrases in scene_phrases for phrase in phrases]
    spoken = iter(await speak_all(store, every_phrase, engine, voice_id, transport, style))

    scenes = []
    lengths = []
    scene_beats = []
    for phrases in scene_phrases:
        pieces = [next(spoken) for _phrase in phrases]
        pieces[0] = lead_cut(pieces[0])
        scene, _piece_starts = media.join_wavs(pieces, gap_ms=0)
        piece_lengths = [wav_seconds(piece) for piece in pieces]
        scenes.append(scene)
        lengths.append(wav_seconds(scene))
        scene_beats.append(beat_starts(piece_lengths))

    gap_ms = int(timeline.BREATH * 1000)
    joined, _starts = media.join_wavs(scenes, gap_ms=gap_ms)
    return joined, lengths, scene_beats
