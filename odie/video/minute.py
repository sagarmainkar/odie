"""One-minute videos: a reel, or any video asked for at one minute. Its narration is fitted to exactly SECONDS by
speeding or slowing the recorded voice (pitch kept) within what still sounds like it; the video opens silent on the
question card for COLD_OPEN seconds; the page gets a narration clock, window.__timings.clock = {start, length}, which
the kit turns into s.left() and Video.clockAt(T): 60 at the first word, 0 at the last, null before the first word;
after 0 comes END, the countdown character's blink and Odie's chime, then the hard cut. A 2-6 minute video keeps its
free length and none of this (odie.video.kind)."""
import io
import wave
from dataclasses import dataclass
from pathlib import Path

from odie import media
from odie.video import beats, encode, timeline

SECONDS = 60.0     # a one-minute video's narration, first word to last
COLD_OPEN = 2.5    # seconds the question card holds, silent and without a clock, before the first word
END = 0.8          # seconds after the last word: the blink and the chime, then the cut
SLOWEST = 0.8      # the voice may be slowed to 0.8 times its speed (48 s of speech becomes 60) ...
FASTEST = 1.25     # ... or sped to 1.25 times (75 s becomes 60): past these it stops sounding like itself
FEWEST_WORDS = 115  # a narration for one minute: about 140 words at timeline.WORDS_PER_MINUTE, within these
MOST_WORDS = 170


class DoesntFit(encode.EncodeError):
    """A narration too far from a minute to fit by speeding or slowing the voice; told in the chat."""


def is_one_minute(minutes: int, aspect: str) -> bool:
    """Decides whether a video is made in one-minute mode: asked for at one minute, or a reel (vertical, for Instagram
    or Shorts, is always a minute). (1, "landscape") -> True; (2, "vertical") -> True; (3, "landscape") -> False,
    and that video keeps its free length."""
    return minutes == 1 or aspect == "vertical"


def words_problem(narration: list[str]) -> str | None:
    """Decides whether a one-minute video's narration is about a minute of speech, as the writer submits it: 140 words
    -> None; 90 or 200 -> what to do, in words. The "|" beat marks are not words."""
    words = sum(len(text.split()) for text in beats.spoken(narration))
    if FEWEST_WORDS <= words <= MOST_WORDS:
        return None
    return (f"The narration is {words} words; a one-minute video needs about {timeline.WORDS_PER_MINUTE} "
            f"({FEWEST_WORDS} to {MOST_WORDS}). Odie fits the voice to exactly {SECONDS:.0f} s, so write for a "
            "minute: shorten or lengthen the narration (and its scenes) to fit.")


def tempo_for(spoken: float) -> float | None:
    """How much faster the voice must go for `spoken` seconds of narration to last exactly SECONDS: 66 s -> 1.1;
    60 s -> 1.0; 54 s -> 0.9 (slowed); 80 s or 40 s -> None (too far: it would stop sounding like the voice)."""
    tempo = spoken / SECONDS
    if tempo < SLOWEST or tempo > FASTEST:
        return None
    return round(tempo, 4)


def seconds_of(wav: bytes) -> float:
    """A WAV's length in seconds: 1,440,000 frames at 24,000 a second -> 60.0."""
    with wave.open(io.BytesIO(wav)) as w:
        return w.getnframes() / w.getframerate()


@dataclass
class Fitted:
    """The narration fitted to a minute: the voice, its measured length, and every time the page needs, scaled with it
    (scene lengths, beats, and the breath between scenes)."""
    wav: bytes
    seconds: float
    lengths: list[float]
    beats: list[list[float]]
    breath: float


async def fit(wav: bytes, lengths: list[float], scene_beats: list[list[float]], folder: Path) -> Fitted:
    """The narration sped up or slowed down to last SECONDS, its pitch kept (ffmpeg's atempo), with the page's times
    scaled by what the voice measures after: 66 s of narration (6 s, 30 s and 29 s scenes, two 0.5 s breaths) ->
    60.0 s, scenes of 5.45, 27.27 and 26.36 s, breaths of 0.45 s. Too far from a minute (tempo_for) -> DoesntFit,
    in words for the chat. The voice before and after is kept in `folder` (narration-spoken.wav, narration-fitted.wav)."""
    breaths = timeline.BREATH * (len(lengths) - 1)
    spoken = round(sum(lengths) + breaths, 3)
    tempo = tempo_for(spoken)
    if tempo is None:
        raise DoesntFit(f"The narration came out at {spoken:.1f} s, too far from one minute to fit by speeding or "
                        "slowing the voice. Ask again with a shorter or fuller brief.")
    spoken_path = folder / "narration-spoken.wav"
    fitted_path = folder / "narration-fitted.wav"
    spoken_path.write_bytes(wav)
    command = [encode.ffmpeg(), "-y", "-loglevel", "error", "-i", str(spoken_path), "-af", f"atempo={tempo}",
               "-c:a", "pcm_s16le", str(fitted_path)]
    code, stderr = await encode.run(command)
    if code != 0:
        raise encode.EncodeError(encode.tail(stderr) or f"ffmpeg exited with {code}")
    fitted = fitted_path.read_bytes()
    seconds = round(seconds_of(fitted), 3)
    scale = seconds / spoken
    scaled_lengths = [round(length * scale, 3) for length in lengths]
    scaled_beats = [[round(start * scale, 3) for start in scene] for scene in scene_beats]
    return Fitted(wav=fitted, seconds=seconds, lengths=scaled_lengths, beats=scaled_beats,
                  breath=round(timeline.BREATH * scale, 4))


def on_the_clock(timings: dict, narrated_scenes: int) -> dict:
    """A one-minute video's timings from its narration's: every scene COLD_OPEN later (the question card holds silent
    first), the last narrated scene END longer (the blink and the chime), anything after it (Odie's credits card) moved
    on with it, and the clock: when the first word plays and how long the narration lasts, measured, never a set 60
    and never the video's length. Scenes at [0.0, 6.5] lasting [6.0, 53.5] -> starts [2.5, 9.0], lengths [6.0, 54.3],
    clock {"start": 2.5, "length": 60.0}."""
    last = narrated_scenes - 1
    narration_seconds = round(timings["starts"][last] + timings["lengths"][last], 3)
    starts = []
    for number, start in enumerate(timings["starts"]):
        moved = start + COLD_OPEN
        if number > last:
            moved += END
        starts.append(round(moved, 3))
    lengths = list(timings["lengths"])
    lengths[last] = round(lengths[last] + END, 3)
    return {"starts": starts, "lengths": lengths, "beats": timings["beats"],
            "clock": {"start": COLD_OPEN, "length": narration_seconds}}


def silence_like(wav: bytes, seconds: float) -> bytes:
    """`seconds` of silence in the same WAV format as `wav` (rate, channels, sample width)."""
    with wave.open(io.BytesIO(wav)) as w:
        params = w.getparams()
    frames = round(seconds * params.framerate)
    out = io.BytesIO()
    with wave.open(out, "wb") as quiet:
        quiet.setparams(params)
        quiet.writeframes(b"\x00" * frames * params.sampwidth * params.nchannels)
    return out.getvalue()


def framed(wav: bytes) -> bytes:
    """The narration as a one-minute video plays it: COLD_OPEN of silence before the first word (the question card),
    then the narration, then END of silence (the blink; Odie's chime is mixed over it)."""
    joined, _starts = media.join_wavs([silence_like(wav, COLD_OPEN), wav, silence_like(wav, END)], gap_ms=0)
    return joined
