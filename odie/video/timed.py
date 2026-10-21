"""A timed segment: a stretch of a video that must last exactly N seconds, first word to last (a countdown character's
minute, say), inside a video of any length. make_video asks for one (job.data["timed_segment"] = {"seconds": 60,
"tolerance": 0.10}); the writer marks its first and last scene in Video.scenes (timed_start: true, timed_end: true);
only that segment's recorded voice is sped or slowed (pitch kept) to last exactly N seconds, and only when it is within
the tolerance; the scenes before and after keep their natural length. The page gets window.ODIE_TIMED = {start, seconds,
end} (the segment's first word, N, its last word), which the kit turns into s.left() and Video.clockAt(T): N at the
first word, 0 at the last, null before. Odie's chime plays at 0. A video without a timed segment has none of this."""
import array
import io
import wave
from dataclasses import dataclass
from pathlib import Path

from odie.video import beats, encode, narrate, timeline

TOLERANCE = 0.10  # how far the segment's speech may be from its seconds and still be fitted: 10%, either way
BLINK = 0.8       # seconds after the last word when the segment ends the video: the blink and the chime, then the cut
FEWEST_SHARE = 0.82  # the segment's words, as a share of what its seconds hold at timeline.WORDS_PER_MINUTE: 60 s ->
MOST_SHARE = 1.215   # about 140 words, from 115 to 170


class DoesntFit(encode.EncodeError):
    """A segment whose speech is too far from its seconds to fit by speeding or slowing the voice; told in the chat."""


@dataclass(frozen=True)
class Segment:
    """What the job asked for: the segment's length in seconds, and how far its speech may be from it."""
    seconds: float
    tolerance: float = TOLERANCE


def segment_of(data: dict) -> Segment | None:
    """The timed segment a job's data asks for, or None (the video's free length, as every video before):
    {"timed_segment": {"seconds": 60, "tolerance": 0.1}} -> Segment(60, 0.1); {} -> None; a malformed one
    ({"seconds": "soon"}) -> None."""
    asked = data.get("timed_segment")
    if not isinstance(asked, dict):
        return None
    try:
        seconds = float(asked.get("seconds"))
        tolerance = float(asked.get("tolerance", TOLERANCE))
    except (TypeError, ValueError):
        return None
    if seconds <= 0:
        return None
    return Segment(seconds=seconds, tolerance=tolerance)


def marks_problem(starts: list[int], ends: list[int], seconds: float) -> str | None:
    """Decides whether the page marks one timed segment: the scenes (from 1) that carry timed_start and timed_end must
    be one each, the start's scene no later than the end's. ([2], [3]) -> None; ([3], [3]) -> None (a segment of one
    scene); ([], []) -> how to mark it; ([1, 2], [3]) -> "only one scene with timed_start …"; ([4], [2]) -> the end
    comes before the start."""
    how = (f"Mark the {seconds:.0f}-second segment in Video.scenes: timed_start: true on its first scene and "
           "timed_end: true on its last (both on one scene when the segment is one scene).")
    if not starts and not ends:
        return how
    if not starts:
        return f"No scene has timed_start. {how}"
    if not ends:
        return f"No scene has timed_end. {how}"
    if len(starts) > 1:
        scenes = ", ".join(map(str, starts))
        return f"Scenes {scenes} all have timed_start: there must be only one scene with timed_start."
    if len(ends) > 1:
        scenes = ", ".join(map(str, ends))
        return f"Scenes {scenes} all have timed_end: there must be only one scene with timed_end."
    if ends[0] < starts[0]:
        return (f"timed_end (scene {ends[0]}) comes before timed_start (scene {starts[0]}): the segment runs from its "
                "timed_start scene to its timed_end scene.")
    return None


def segment_scenes(starts: list[int], ends: list[int]) -> tuple[int, int]:
    """The segment's first and last scene, 0-based, from marks that passed marks_problem: ([2], [3]) -> (1, 2)."""
    return starts[0] - 1, ends[0] - 1


def clock_from(timings: dict, first: int, last: int, seconds: float) -> dict:
    """The segment clock from timings as they are (the page check's estimated ones): from scene `first`'s start to
    scene `last`'s end, 0-based. Starts [0.0, 6.5, 36.0], lengths [6.0, 29.0, 30.0], scenes 1 to 2 ->
    {"start": 6.5, "seconds": 60, "end": 66.0}."""
    start = timings["starts"][first]
    end = round(timings["starts"][last] + timings["lengths"][last], 3)
    return {"start": start, "seconds": seconds, "end": end}


def word_budget(seconds: float) -> tuple[int, int, int]:
    """About how many words the segment's seconds hold, and the range the writer must keep to: 60 s ->
    (140, 115, 170); 30 s -> (70, 57, 85)."""
    words = round(seconds / 60 * timeline.WORDS_PER_MINUTE)
    return words, round(words * FEWEST_SHARE), round(words * MOST_SHARE)


def words_problem(narration: list[str], first: int, last: int, seconds: float) -> str | None:
    """Decides whether the segment's narration (scenes first to last, 0-based) is about its seconds of speech; the
    scenes before and after don't count. 140 words for 60 s -> None; 30 -> what to do, in words. "|" marks are not
    words."""
    spoken = beats.spoken(narration)[first:last + 1]
    words = sum(len(text.split()) for text in spoken)
    wanted, fewest, most = word_budget(seconds)
    if fewest <= words <= most:
        return None
    return (f"The timed segment's narration is {words} words; {seconds:.0f} seconds needs about {wanted} ({fewest} "
            f"to {most}). Odie fits the segment's voice to exactly {seconds:.0f} s, so write the scenes from "
            "timed_start to timed_end for that long; the scenes before and after keep their own length.")


def starts_with_gaps(lengths: list[float], gaps: list[float]) -> tuple[list[float], float]:
    """Each scene's start and the video's length, from the scenes' lengths and the gap before each scene after the
    first: ([6.0, 30.0, 30.0], [0.5, 0.45]) -> ([0.0, 6.5, 36.95], 66.95)."""
    starts = []
    t = 0.0
    for number, length in enumerate(lengths):
        if number:
            t += gaps[number - 1]
        starts.append(round(t, 3))
        t += length
    return starts, round(t, 3)


def quiet_at_end(wav: bytes) -> float:
    """Seconds of quiet after the last sound of a 16-bit mono WAV: a voice that trails 0.3 s of quiet -> 0.3; one that
    ends on a word -> 0.0 (measured as narrate.quiet_at_start measures the start, the other way round)."""
    with wave.open(io.BytesIO(wav)) as w:
        params = w.getparams()
        frames = w.readframes(w.getnframes())
    if params.sampwidth != 2 or params.nchannels != 1:
        return 0.0
    samples = array.array("h", frames)
    samples.reverse()
    return narrate.quiet_at_start(wav_from(params, samples.tobytes()))


@dataclass
class Fitted:
    """The narration with its timed segment fitted: the voice, every scene's length, beats and the gap before each
    scene after the first (the segment's breaths are sped or slowed with it), and the clock for the page:
    {"start": its first word, "seconds": N, "end": its last word}, in seconds into the video."""
    wav: bytes
    lengths: list[float]
    beats: list[list[float]]
    gaps: list[float]
    clock: dict


def split_frames(wav: bytes, start: float, end: float) -> tuple:
    """A WAV's format and its frames before `start`, from `start` to `end`, and after `end` (seconds)."""
    with wave.open(io.BytesIO(wav)) as w:
        params = w.getparams()
        frames = w.readframes(w.getnframes())
    size = params.sampwidth * params.nchannels
    first = round(start * params.framerate) * size
    last = round(end * params.framerate) * size
    return params, frames[:first], frames[first:last], frames[last:]


def wav_from(params, frames: bytes) -> bytes:
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setparams(params)
        w.writeframes(frames)
    return out.getvalue()


async def stretched(wav: bytes, tempo: float, folder: Path) -> bytes:
    """The WAV sped up (tempo over 1) or slowed down, its pitch kept (ffmpeg's atempo); the voice before and after is
    kept in `folder` (segment-spoken.wav, segment-fitted.wav)."""
    spoken_path = folder / "segment-spoken.wav"
    fitted_path = folder / "segment-fitted.wav"
    spoken_path.write_bytes(wav)
    command = [encode.ffmpeg(), "-y", "-loglevel", "error", "-i", str(spoken_path), "-af", f"atempo={tempo}",
               "-c:a", "pcm_s16le", str(fitted_path)]
    code, stderr = await encode.run(command)
    if code != 0:
        raise encode.EncodeError(encode.tail(stderr) or f"ffmpeg exited with {code}")
    return fitted_path.read_bytes()


async def fit(wav: bytes, lengths: list[float], scene_beats: list[list[float]], first: int, last: int,
              segment: Segment, folder: Path) -> Fitted:
    """The narration (narrate's joined voice, a breath between scenes) with only scenes first to last (0-based) sped or
    slowed so their speech, first word to last and the breaths between them included, lasts exactly segment.seconds;
    every other scene as it was. Cold open 6 s, segment scenes of 30 s and 35.5 s (66 s with the breath), pause 2 s ->
    the cold open still 6 s, the segment 60.0 s (scenes of 27.27 and 32.27 s, its breath 0.45 s), the pause 2 s, and
    the clock {"start": 6.5, "seconds": 60, "end": 66.5}. Speech further than the tolerance from its seconds ->
    DoesntFit: "segment narration is 71.2 s; needs 60 s"."""
    breath = timeline.BREATH
    gaps = [breath] * (len(lengths) - 1)
    starts, _total = starts_with_gaps(lengths, gaps)
    segment_start = starts[first]
    segment_end = starts[last] + lengths[last]
    params, before, middle, after = split_frames(wav, segment_start, segment_end)
    middle_wav = wav_from(params, middle)
    middle_seconds = narrate.wav_seconds(middle_wav)
    lead = narrate.quiet_at_start(middle_wav)
    tail = quiet_at_end(middle_wav)
    spoken = round(middle_seconds - lead - tail, 3)  # first word to last
    off = abs(spoken - segment.seconds) / segment.seconds
    if off > segment.tolerance:
        raise DoesntFit(f"segment narration is {spoken:.1f} s; needs {segment.seconds:.0f} s. Ask again with the "
                        "segment's scenes shorter or fuller.")
    tempo = round(spoken / segment.seconds, 5)
    fitted = await stretched(middle_wav, tempo, folder)
    with wave.open(io.BytesIO(fitted)) as w:
        fitted_frames = w.readframes(w.getnframes())
    fitted_seconds = narrate.wav_seconds(fitted)
    scale = fitted_seconds / middle_seconds
    new_lengths = list(lengths)
    new_beats = [list(scene) for scene in scene_beats]
    for scene in range(first, last + 1):
        new_lengths[scene] = round(lengths[scene] * scale, 3)
        new_beats[scene] = [round(start * scale, 3) for start in scene_beats[scene]]
    for gap in range(first, last):  # the gaps before scenes first + 1 to last: inside the segment
        gaps[gap] = round(breath * scale, 4)
    clock_start = round(segment_start + narrate.quiet_at_start(fitted), 3)
    clock_end = round(segment_start + fitted_seconds - quiet_at_end(fitted), 3)
    joined = wav_from(params, before + fitted_frames + after)
    return Fitted(wav=joined, lengths=new_lengths, beats=new_beats, gaps=gaps,
                  clock={"start": clock_start, "seconds": segment.seconds, "end": clock_end})


def ends_the_video(last_scene: int, narrated_scenes: int) -> bool:
    """Decides whether the segment ends the video's narration, so its last scene needs BLINK more for the blink and the
    chime after its last word. Ending on scene 2 of 2 (0-based last_scene 1) -> True; on scene 2 of 4, a pause and a
    closing card after it -> False: those scenes hold the blink."""
    return last_scene == narrated_scenes - 1


def blink_silence(wav: bytes) -> bytes:
    """The narration with BLINK of quiet after it, for a segment that ends the video (Odie's chime is mixed over it)."""
    with wave.open(io.BytesIO(wav)) as w:
        params = w.getparams()
        frames = w.readframes(w.getnframes())
    quiet = b"\x00" * round(BLINK * params.framerate) * params.sampwidth * params.nchannels
    return wav_from(params, frames + quiet)
