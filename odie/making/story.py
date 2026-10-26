"""The audio story as one kind of thing Odie makes in the background (odie.making.jobs). Its writing step is the
story writer (odie.making.story_writer), the only model call: it writes the script and chooses the sound. Its making
step is plain code, the same every time:

1. speak every line in its speaker's voice (grouped by voice, the quiet before and after each line trimmed);
2. lay the story out in time (lay_out): scene by scene, the lines with their pauses, each scene's bed and music,
   the hits, and the transitions;
3. mix it with one ffmpeg graph (mix_plan): every bed and music file matched to the speech's loudness, then set to
   the slider's level below it, ducked under speech by one smooth envelope (envelope), the hits at fixed peaks;
4. master it: 48 kHz stereo, loudnorm to about -16 LUFS with a true peak near -1.5 dBTP, then measure how far the
   speech sits above the beds (the gap the slider promises) and keep it in the job's levels.json;
5. save one file, AAC in .m4a, as the chat's story player. Nothing else is posted.

Importing this module registers the kind as "story", with its jobs under <workspace>/stories/<slug>/ (job.json,
brief.md and levels.json; the audio is kept with Odie's media, like every player in the chat).

job.data carries "request" (story_writer.Request) and "sound_level" (10–40) from the chat, and "scenes" and
"catalogue" from the writing step to the making step."""
import dataclasses
import itertools
import json
import logging
import math
import re
import sys
import tempfile
import wave
from array import array
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

import httpx

from odie import media, voice
from odie.making import jobs, sound_library, story_writer
from odie.store.db import Store
from odie.video import encode
from odie.video.narrate import lead_cut, speak_all, tail_cut, wav_seconds
from odie.video.sounds import seconds_text

log = logging.getLogger("odie.making.story")

FOLDER = "stories"

# The format every story is mastered to: the voices are 24 kHz mono, so they are upsampled.
RATE = 48000

# The sound level slider, in percent, and the dB below the speech it puts the ambience at: 25 % -> 12 dB below.
# Between these points the dB is a straight line; outside them it holds at the ends. The range stops at 40 %: beds
# louder than 8 dB under the speech drown it.
SLIDER_POINTS = ((10, -20.0), (25, -12.0), (40, -8.0))
LOWEST_SOUND_LEVEL = 10
HIGHEST_SOUND_LEVEL = 40
DEFAULT_SOUND_LEVEL = 25

BED_LEVEL_DB = {"low": -3.0, "normal": 0.0, "up front": 2.0}  # the writer's word for a bed, on top of the slider
MUSIC_BELOW_AMBIENCE_DB = 4.0  # a music bed sits this far under the ambience
RISE_DB = 6.0  # beds rise by up to this much between lines and in the prelude…
CEILING_DB = -4.0  # …but never above this, against the speech
MATCH_LIMIT_DB = 30.0  # the most a file is raised or lowered to match the speech (a near-silent file isn't blown up)

ENVELOPE_RATE = 1000  # values a second in the duck envelope (it is upsampled in the mix)
DUCK_PAD = 0.15  # the beds are fully down this long before a line's first word and after its last
DUCK_RAMP = 0.4  # seconds the beds take to go down or come back up: slow enough never to pump
MIN_RISE_GAP = 1.5  # a gap between lines shorter than this (after the pads) keeps the beds down

BED_FADE_IN = 1.5  # a scene's bed and music fade in over this long
BED_FADE_OUT = 1.5  # …and out over this long at a stinger or a silence (a crossfade takes its own seconds)
STORY_TAIL = 3.0  # after the last line, the beds play on this long, fading out

HIT_PEAK = {"low": 0.3, "normal": 0.5, "up front": 0.8}  # a hit's peak, as a share of full scale, by the writer's word
HIT_ATTACK = 0.3  # a hit's first 0.3 s is its loud part: it never covers a line's first word
HIT_MAX_SECONDS = 8.0  # a hit plays at most this long…
HIT_FADE = 0.3  # …and a longer one fades out over its last 0.3 s

TARGET_LUFS = -16.0  # the whole story's loudness, as podcasts are
TRUE_PEAK = -1.5  # dBTP
LOUDNESS_RANGE = 11.0  # LU, loudnorm's target range
MEASURE_SECONDS = 60  # how much of a sound file is measured for its loudness
MEASURE_FRAME = 256  # samples a frame when measuring only where people speak
AAC_BITRATE = "160k"
PEAKS_RATE = 4000  # the waveform is drawn from a small mono copy

MEAN = re.compile(r"mean_volume: (-?[\d.]+) dB")
MAX = re.compile(r"max_volume: (-?[\d.]+) dB")
CHANNELS = re.compile(r"Audio: [^\n]*?, \d+ Hz, ([^,\n]+)")


@dataclass(frozen=True)
class Spoken:
    """A line in the story's time: who says it (a cast id), what, and when."""
    speaker: str
    text: str
    start: float
    seconds: float


@dataclass(frozen=True)
class Placed:
    """A sound in the story's time. role: "bed" (ambience, looped), "music" (looped) or "hit" (once). level: the
    writer's word. A bed fades in and out; a hit plays from its start."""
    role: str
    sound: str
    level: str
    start: float
    seconds: float = 0.0
    fade_in: float = 0.0
    fade_out: float = 0.0


@dataclass
class Laid:
    """The whole story in time: its lines, its sounds (beds first, then hits) and its length in seconds."""
    speech: list[Spoken]
    sounds: list[Placed]
    length: float


@dataclass(frozen=True)
class Source:
    """A sound file as the mix uses it: where it is, how loud it is (its mean and its peak, in dBFS), its channels,
    and its length (0 when unknown)."""
    path: str
    mean_db: float
    max_db: float
    channels: int = 1
    seconds: float = 0.0


@dataclass
class MixPlan:
    """The mix as ffmpeg takes it: the sound inputs (after the speech and the envelope), the filter graph, and
    whether there are beds (an envelope input, and a beds-only output for measuring the gap)."""
    inputs: list[str]
    graph: str
    has_beds: bool


@dataclass
class Made:
    """A finished story: the player's media, the measured gap (dB the speech sits above the beds; None without beds),
    the mastered loudness, and the sounds left out."""
    media: dict
    gap_db: float | None
    loudness_lufs: float | None
    skipped: list[str] = field(default_factory=list)


# 1. Speaking.

def accent_style(engine: str, accent: str) -> str:
    """Decides how a voice is told the story's accent: an OpenAI voice has none of its own, so the accent goes in its
    style line; Kokoro's and Phonon's voices carry their accent already and are never steered. ("openai", "Indian")
    -> "Speak with a natural Indian English accent, as a storyteller in an audio drama: …"; ("kokoro", "Indian") ->
    ""."""
    if engine != "openai":
        return ""
    return (f"Speak with a natural {accent} English accent, as a storyteller in an audio drama: expressive, with the "
            f"feeling each line carries.")


def voice_for(store: Store, member: dict) -> tuple[str, dict]:
    """A cast member's engine and voice: the engine chosen in Settings, and their voice in it. One engine a story
    today; a story that mixes engines would give each member their own engine here (and resample in speech_track).
    A voice the engine doesn't have is a VoiceUnavailable naming the member: "Narrator's voice: 'marin' isn't one
    of …"."""
    engine, _read_aloud = voice.get_tts(store)
    try:
        chosen = voice.voice_in_chosen_engine(store, member["voice"])
    except ValueError as e:
        raise voice.VoiceUnavailable(f"{member['name']}'s voice: {e}") from e
    return engine, chosen


def spoken_lines(scenes: list[story_writer.Scene]) -> list[story_writer.Speech]:
    """Every spoken line of the story, in order."""
    lines = []
    for scene in scenes:
        for line in scene.lines:
            if isinstance(line, story_writer.Speech):
                lines.append(line)
    return lines


async def speak_lines(store: Store, scenes: list[story_writer.Scene], cast: list[dict], accent: str,
                      transport: httpx.AsyncBaseTransport | None) -> tuple[list[bytes], dict[str, dict]]:
    """Every spoken line as a WAV, in order, the quiet before and after each trimmed; and each cast id's voice. The
    lines are asked for voice by voice (speak_all), so a local voice loads each voice once."""
    engine, _read_aloud = voice.get_tts(store)
    if engine == "phonon":
        await voice.phonon_voices()  # Phonon's voices are known once Ollama has been asked
    voices = {}
    engines = {}
    for member in cast:
        member_engine, chosen = voice_for(store, member)
        voices[member["id"]] = chosen
        engines[member["id"]] = member_engine
    style = accent_style(engine, accent)

    lines = spoken_lines(scenes)
    groups: dict[tuple[str, str], list[int]] = {}
    for position, line in enumerate(lines):
        key = (engines[line.speaker], voices[line.speaker]["id"])
        groups.setdefault(key, []).append(position)
    spoken: list[bytes] = [b""] * len(lines)
    for (group_engine, voice_id), positions in groups.items():
        texts = [lines[p].text for p in positions]
        wavs = await speak_all(store, texts, group_engine, voice_id, transport, style)
        for position, wav in zip(positions, wavs, strict=True):
            spoken[position] = tail_cut(lead_cut(wav))
    return spoken, voices


# 2. The timeline.

def hit_start(start: float, word_starts: list[float]) -> float:
    """Decides where a hit plays so its loud first HIT_ATTACK seconds never cover a line's first word: a hit within
    HIT_ATTACK of a line's start moves into the gap just before the line. A door at 10.0 with a line at 10.1 -> 9.8;
    at 10.2 -> 9.8; at 8.0 -> 8.0 (stays); at 0.1 with a line at 0.2 -> 0.0 (never before the story starts)."""
    for word in word_starts:
        if word - HIT_ATTACK < start < word + HIT_ATTACK:
            return max(0.0, word - HIT_ATTACK)
    return start


def scene_end_and_next(end: float, transition: story_writer.Transition | None) -> tuple[float, float, float, float]:
    """How a scene hands over, from where its last line ends: (its beds' end, their fade out, the next scene's start,
    the next scene's beds' start). A crossfade of 2.5 at 7.3 -> (9.8, 2.5, 9.8, 7.3): the beds overlap for 2.5 s; a
    silence of 1.0 -> (8.3, 1.0, 8.3, 8.3); a stinger -> (8.8, 1.5, 9.3, 9.3); the last scene -> (end + STORY_TAIL,
    STORY_TAIL, end + STORY_TAIL, …)."""
    if transition is None:
        tail_end = end + STORY_TAIL
        return tail_end, STORY_TAIL, tail_end, tail_end
    seconds = transition.seconds
    if transition.kind == "crossfade":
        return end + seconds, seconds, end + seconds, end
    fade = min(seconds, BED_FADE_OUT)
    return end + fade, fade, end + seconds, end + seconds


def lay_out(scenes: list[story_writer.Scene], line_seconds: list[float]) -> Laid:
    """The story in time, from its scenes and how long each spoken line came out. Lines follow each other with
    their pauses; a cue plays where it stands and the next line waits its lead; a sound_after plays as its line ends.
    Each scene's bed and music play under the whole scene, fading in (BED_FADE_IN, or over a crossfade) and out into
    the transition; a stinger plays as its scene ends. Hits are then moved off the lines' first words (hit_start)."""
    seconds_left = iter(line_seconds)
    speech = []
    beds = []
    hits = []
    scene_start = 0.0
    beds_start = 0.0
    fade_in = BED_FADE_IN
    length = 0.0
    for scene in scenes:
        cursor = scene_start
        for line in scene.lines:
            if isinstance(line, story_writer.Cue):
                hits.append(Placed("hit", line.sound, line.level, cursor))
                cursor += line.lead
                continue
            seconds = next(seconds_left)
            speech.append(Spoken(line.speaker, line.text, round(cursor, 3), seconds))
            if line.sound_after:
                hits.append(Placed("hit", line.sound_after, "normal", cursor + seconds))
            cursor += seconds + line.pause_after
        end = round(cursor, 3)
        if scene.transition is not None and scene.transition.kind == "stinger":
            hits.append(Placed("hit", scene.transition.sound, "normal", end))
        beds_end, fade_out, next_start, next_beds_start = scene_end_and_next(end, scene.transition)
        for role, sound in (("bed", scene.bed), ("music", scene.music)):
            if sound is not None:
                beds.append(Placed(role, sound.sound, sound.level, round(beds_start, 3),
                                   round(beds_end - beds_start, 3), fade_in, fade_out))
        length = next_start
        fade_in = BED_FADE_IN
        if scene.transition is not None and scene.transition.kind == "crossfade":
            fade_in = scene.transition.seconds
        scene_start = round(next_start, 3)
        beds_start = next_beds_start

    word_starts = [line.start for line in speech]
    moved = []
    for hit in hits:
        moved.append(dataclasses.replace(hit, start=round(hit_start(hit.start, word_starts), 3)))
    return Laid(speech=speech, sounds=beds + moved, length=round(length, 3))


# 3. Levels and the mix.

def slider_db(percent: float) -> float:
    """The dB below the speech the sound level slider puts the ambience at, along SLIDER_POINTS and held to 10–40:
    10 -> -20; 25 -> -12; 40 -> -8; 30 -> -10.67 (a straight line between 25 and 40); 5 -> -20; 55 -> -8."""
    held = min(max(percent, LOWEST_SOUND_LEVEL), HIGHEST_SOUND_LEVEL)
    for (low_percent, low_db), (high_percent, high_db) in itertools.pairwise(SLIDER_POINTS):
        if held <= high_percent:
            share = (held - low_percent) / (high_percent - low_percent)
            return low_db + share * (high_db - low_db)
    return SLIDER_POINTS[-1][1]


def rise_db(under_db: float) -> float:
    """Decides how far the beds rise between lines, from where they sit under the speech: RISE_DB, but never above
    CEILING_DB. -12 -> 6 (up to -6); -8 -> 4 (up to -4); -2 -> 0."""
    return max(0.0, min(RISE_DB, CEILING_DB - under_db))


def bed_under_db(level: str, slider: float) -> float:
    """Where a bed sits under the speech: the slider's dB plus the writer's word for it, held so its rise between
    lines stops at CEILING_DB. ("normal", -12) -> -12; ("low", -12) -> -15; ("up front", -8) -> -8 (-6 would rise to
    -2)."""
    under = slider + BED_LEVEL_DB.get(level, 0.0)
    return min(under, CEILING_DB - rise_db(slider))


def music_under_db(level: str, slider: float) -> float:
    """A music bed sits MUSIC_BELOW_AMBIENCE_DB under where a bed with the same word would: ("normal", -12) -> -16."""
    return bed_under_db(level, slider) - MUSIC_BELOW_AMBIENCE_DB


def matched_db(speech_db: float, source: Source) -> float:
    """The gain that brings a bed or music file to the speech's loudness, held to ±MATCH_LIMIT_DB: speech at -20,
    a file at -30 -> +10."""
    gain = speech_db - source.mean_db
    return max(-MATCH_LIMIT_DB, min(MATCH_LIMIT_DB, gain))


def hit_db(level: str, source: Source) -> float:
    """The gain that puts a hit's peak at its word's share of full scale: "low" (0.3) on a file peaking at -6 dB ->
    20·log10(0.3) + 6 = -4.46."""
    return 20 * math.log10(HIT_PEAK.get(level, HIT_PEAK["normal"])) - source.max_db


def db_text(gain: float) -> str:
    """A gain for ffmpeg's volume filter: 4 -> "4.00dB"; -0.0 -> "0.00dB"."""
    return f"{round(gain, 2) + 0.0:.2f}dB"


def to_story_format(channels: int) -> str:
    """The filters that bring a source to the story's 48 kHz stereo, at the same loudness: a mono file is copied to
    both sides (a plain upmix would lower it by 3 dB), anything else is mixed to stereo. 1 ->
    "aresample=48000,pan=stereo|c0=c0|c1=c0,aformat=sample_fmts=fltp"."""
    if channels == 1:
        layout = "pan=stereo|c0=c0|c1=c0"
    else:
        layout = "aformat=channel_layouts=stereo"
    return f"aresample={RATE},{layout},aformat=sample_fmts=fltp"


def bed_filter(k: int, placed: Placed, source: Source, gain: float, envelope_label: str, out: str) -> str:
    """One bed or music bed, input k (read round and round): cut to its time, faded in and out, set to its gain,
    delayed to its start, then multiplied by the duck envelope, and split for the story and the beds-only bus."""
    fade_out_start = max(0.0, placed.seconds - placed.fade_out)
    return (f"[{k}:a]{to_story_format(source.channels)},atrim=duration={seconds_text(placed.seconds)},"
            f"asetpts=PTS-STARTPTS,afade=t=in:d={seconds_text(placed.fade_in)},"
            f"afade=t=out:st={seconds_text(fade_out_start)}:d={seconds_text(placed.fade_out)},volume={db_text(gain)},"
            f"adelay={round(placed.start * 1000)}:all=1[pre{out}];[pre{out}][{envelope_label}]amultiply,"
            f"asplit=2[m{out}][q{out}]")


def hit_filter(k: int, placed: Placed, source: Source, gain: float, out: str) -> str:
    """One hit, input k: played once (at most HIT_MAX_SECONDS, a longer one faded out), set to its gain and delayed
    to its start."""
    fade = ""
    if source.seconds > HIT_MAX_SECONDS:
        fade = f"afade=t=out:st={seconds_text(HIT_MAX_SECONDS - HIT_FADE)}:d={seconds_text(HIT_FADE)},"
    return (f"[{k}:a]{to_story_format(source.channels)},atrim=duration={seconds_text(HIT_MAX_SECONDS)},"
            f"asetpts=PTS-STARTPTS,{fade}volume={db_text(gain)},adelay={round(placed.start * 1000)}:all=1[{out}]")


def mix_plan(laid: Laid, sources: dict[str, Source], speech_db: float, sound_level: float) -> MixPlan:
    """The one ffmpeg graph for the whole story. Input 0 is the speech track; input 1 the duck envelope (when there
    are beds); then each sound. Beds and music are matched to the speech (matched_db), set to the slider's level
    under it and raised by the rise (the envelope takes them back down under speech); hits are set by their peak.
    The outputs: [story], the speech with everything under it, and [beds], the beds alone, for the measured gap."""
    slider = slider_db(sound_level)
    rise = rise_db(slider)
    beds = [p for p in laid.sounds if p.role != "hit"]
    hits = [p for p in laid.sounds if p.role == "hit"]
    has_beds = bool(beds)

    parts = [f"[0:a]{to_story_format(1)}[speech]"]
    inputs: list[str] = []
    k = 1
    if has_beds:
        labels = "".join(f"[e{n}]" for n in range(len(beds)))
        parts.append(f"[1:a]{to_story_format(1)},asplit={len(beds)}{labels}")
        k = 2
    story_labels = "[speech]"
    bed_labels = ""
    for n, placed in enumerate(beds):
        source = sources[placed.sound]
        if placed.role == "music":
            under = music_under_db(placed.level, slider)
        else:
            under = bed_under_db(placed.level, slider)
        gain = matched_db(speech_db, source) + under + rise
        parts.append(bed_filter(k, placed, source, gain, f"e{n}", f"b{n}"))
        inputs += ["-stream_loop", "-1", "-i", source.path]
        story_labels += f"[mb{n}]"
        bed_labels += f"[qb{n}]"
        k += 1
    for n, placed in enumerate(hits):
        source = sources[placed.sound]
        parts.append(hit_filter(k, placed, source, hit_db(placed.level, source), f"h{n}"))
        inputs += ["-i", source.path]
        story_labels += f"[h{n}]"
        k += 1
    story_count = 1 + len(beds) + len(hits)
    parts.append(f"{story_labels}amix=inputs={story_count}:normalize=0:duration=longest[story]")
    if has_beds:
        parts.append(f"{bed_labels}amix=inputs={len(beds)}:normalize=0:duration=longest[beds]")
    return MixPlan(inputs=inputs, graph=";".join(parts), has_beds=has_beds)


def ducked_spans(speech_spans: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Where the beds are fully down: each line padded by DUCK_PAD, with spans closer than MIN_RISE_GAP joined (a
    short gap stays down, so the beds never pump). Lines at 2–3 and 3.5–4.5 -> one span, 1.85–4.65."""
    joined: list[list[float]] = []
    for start, end in sorted(speech_spans):
        padded_start = start - DUCK_PAD
        padded_end = end + DUCK_PAD
        if joined and padded_start - joined[-1][1] < MIN_RISE_GAP:
            joined[-1][1] = max(joined[-1][1], padded_end)
        else:
            joined.append([padded_start, padded_end])
    return [(start, end) for start, end in joined]


def envelope(speech_spans: list[tuple[float, float]], length: float, rise: float) -> array:
    """The duck envelope, ENVELOPE_RATE values a second over the whole story: 1.0 where the beds are up (between
    lines and in the prelude), 10^(-rise/20) where they are down (ducked_spans), and a straight line in dB over
    DUCK_RAMP between the two. Lines at 2–3 and 8–9 with a rise of 6: 0.5 s -> 1.0; 2.5 s -> 0.5 (-6 dB); 5.0 s ->
    1.0."""
    count = round(length * ENVELOPE_RATE)
    values = array("f", [1.0]) * count
    down = 10 ** (-rise / 20)
    ramp_samples = round(DUCK_RAMP * ENVELOPE_RATE)
    for start, end in ducked_spans(speech_spans):
        first = max(0, round(start * ENVELOPE_RATE))
        last = min(count, round(end * ENVELOPE_RATE) + 1)
        for i in range(first, last):
            values[i] = down
        for step in range(1, ramp_samples):
            gain = 10 ** (-rise * (1 - step / ramp_samples) / 20)
            for i in (first - step, last - 1 + step):
                if 0 <= i < count and gain < values[i]:
                    values[i] = gain
    return values


def envelope_bytes(values: array) -> bytes:
    """The envelope as raw little-endian 32-bit floats, as ffmpeg's f32le input reads them."""
    copy = array("f", values)
    if sys.byteorder == "big":
        copy.byteswap()
    return copy.tobytes()


def speech_track(wavs: list[bytes], starts: list[float], length: float) -> bytes:
    """All the lines in one WAV in the voice's own format (24 kHz mono), each at its start, quiet between, `length`
    seconds long. Every line is in one engine's format (one engine a story)."""
    with wave.open(BytesIO(wavs[0])) as first:
        params = first.getparams()
    frame_bytes = params.nchannels * params.sampwidth
    track = bytearray(round(length * params.framerate) * frame_bytes)
    for wav, start in zip(wavs, starts, strict=True):
        with wave.open(BytesIO(wav)) as w:
            frames = w.readframes(w.getnframes())
        at = round(start * params.framerate) * frame_bytes
        piece = frames[: max(0, len(track) - at)]
        track[at: at + len(piece)] = piece
    out = BytesIO()
    with wave.open(out, "wb") as w:
        w.setparams(params)
        w.writeframes(bytes(track))
    return out.getvalue()


# Measuring, with ffmpeg.

def number_after(pattern: re.Pattern, text: str) -> float | None:
    """The number a pattern finds in ffmpeg's report, or None: "mean_volume: -23.4 dB" -> -23.4."""
    found = pattern.search(text)
    if found is None:
        return None
    return float(found.group(1))


async def measure_source(path: Path, seconds: float = 0.0) -> Source | None:
    """How loud a sound file is (its first MEASURE_SECONDS) and how many channels it has; None when ffmpeg can't read
    it."""
    command = [encode.ffmpeg(), "-hide_banner", "-nostats", "-t", str(MEASURE_SECONDS), "-i", str(path),
               "-af", "volumedetect", "-f", "null", "-"]
    _code, stderr = await encode.run(command)
    text = stderr.decode("utf-8", errors="replace")
    mean_db = number_after(MEAN, text)
    max_db = number_after(MAX, text)
    if mean_db is None or max_db is None:
        return None
    channels = 2
    layout = CHANNELS.search(text)
    if layout and layout.group(1).strip() == "mono":
        channels = 1
    return Source(path=str(path), mean_db=mean_db, max_db=max_db, channels=channels, seconds=seconds)


async def measure_db(path: Path, spans: list[tuple[float, float]]) -> float | None:
    """How loud a file is only where people speak (its mean in dBFS over those spans, measured in small frames), so
    the quiet between lines doesn't count: a 0.5-amplitude tone at 0–0.5 and 1–1.5 in 2 s -> about -9 dB."""
    select = "+".join(f"between(t,{seconds_text(start)},{seconds_text(end)})" for start, end in spans)
    command = [encode.ffmpeg(), "-hide_banner", "-nostats", "-i", str(path),
               "-af", f"asetnsamples=n={MEASURE_FRAME}:p=0,aselect='{select}',volumedetect", "-f", "null", "-"]
    _code, stderr = await encode.run(command)
    return number_after(MEAN, stderr.decode("utf-8", errors="replace"))


def source_path(entry: dict, role: str) -> str:
    """The file a sound plays from: for a bed or music, its longest cut (a jingle's Long), else the file itself."""
    variants = entry.get("variants") or []
    if role == "hit" or not variants:
        return entry["path"]
    longest = max(variants, key=lambda variant: variant.get("seconds", 0))
    return longest["path"]


async def find_sources(sounds: list[Placed], catalogue: list[dict]) -> tuple[dict[str, Source], list[str]]:
    """Every sound the story plays, measured, by id; and the ids left out (missing or unreadable), each with a log
    line. The story is made without them."""
    by_id = {entry["id"]: entry for entry in catalogue}
    sources: dict[str, Source] = {}
    skipped: list[str] = []
    for placed in sounds:
        if placed.sound in sources or placed.sound in skipped:
            continue
        entry = by_id.get(placed.sound)
        path = None
        if entry is not None:
            path = Path(source_path(entry, placed.role))
        if path is None or not path.is_file():
            log.info("audio story sound %s left out: its file is missing (%s)", placed.sound, path)
            skipped.append(placed.sound)
            continue
        source = await measure_source(path, float(entry.get("seconds") or 0.0))
        if source is None:
            log.info("audio story sound %s left out: ffmpeg couldn't read %s", placed.sound, path)
            skipped.append(placed.sound)
            continue
        sources[placed.sound] = source
    return sources, skipped


# 4. Mastering.

async def run_ffmpeg(command: list[str]) -> str:
    """Run ffmpeg; its report (stderr) as text. A failure is an EncodeError with the end of what it said."""
    code, stderr = await encode.run(command)
    if code != 0:
        raise encode.EncodeError(encode.tail(stderr) or f"ffmpeg exited with {code}")
    return stderr.decode("utf-8", errors="replace")


def loudnorm_report(text: str) -> dict:
    """The JSON loudnorm prints at the end of its report: {"input_i": "-23.1", …}; {} when there is none."""
    start = text.rfind("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        return {}
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return {}


def is_measured(report: dict) -> bool:
    """Decides whether loudnorm's first pass measured something usable for its second: numbers for every value ->
    True; a silent mix ("-inf") or no report -> False (the second pass then measures on its own)."""
    for key in ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset"):
        try:
            value = float(report[key])
        except (KeyError, TypeError, ValueError):
            return False
        if not math.isfinite(value):
            return False
    return True


def loudnorm_filter(report: dict) -> str:
    """The second pass's loudnorm: the targets, and the first pass's measurements when it has them (linear, so the
    whole story moves by one gain and the gap between speech and beds stays as mixed)."""
    targets = f"loudnorm=I={TARGET_LUFS}:TP={TRUE_PEAK}:LRA={LOUDNESS_RANGE}"
    if not is_measured(report):
        return f"{targets}:print_format=json"
    return (f"{targets}:measured_I={report['input_i']}:measured_TP={report['input_tp']}:"
            f"measured_LRA={report['input_lra']}:measured_thresh={report['input_thresh']}:"
            f"offset={report['target_offset']}:linear=true:print_format=json")


async def master(mix: Path, out: Path) -> float | None:
    """The mix normalised to TARGET_LUFS with a true peak near TRUE_PEAK, in two passes, as 48 kHz stereo 16-bit;
    returns the loudness it came out at."""
    first = await run_ffmpeg([encode.ffmpeg(), "-hide_banner", "-nostats", "-i", str(mix), "-af",
                              f"loudnorm=I={TARGET_LUFS}:TP={TRUE_PEAK}:LRA={LOUDNESS_RANGE}:print_format=json",
                              "-f", "null", "-"])
    second = await run_ffmpeg([encode.ffmpeg(), "-hide_banner", "-nostats", "-y", "-i", str(mix),
                               "-af", loudnorm_filter(loudnorm_report(first)), "-ar", str(RATE), "-ac", "2",
                               "-c:a", "pcm_s16le", str(out)])
    output = loudnorm_report(second).get("output_i")
    try:
        return float(output)
    except (TypeError, ValueError):
        return None


# 5. The whole making step.

def transcript_and_hosts(laid: Laid, cast: list[dict], voices: dict[str, dict]) -> tuple[list[dict], list[dict]]:
    """The player's transcript [{host, text, start}] (host: the speaker's display name) and its hosts, the cast as
    they first speak [{name, voice, group}]."""
    names = {member["id"]: member["name"] for member in cast}
    transcript = []
    hosts = []
    seen = set()
    for line in laid.speech:
        transcript.append({"host": names[line.speaker], "text": line.text, "start": line.start})
        if line.speaker not in seen:
            seen.add(line.speaker)
            chosen = voices[line.speaker]
            group = chosen.get("gender") or chosen.get("group", "")
            hosts.append({"name": names[line.speaker], "voice": chosen["label"], "group": group})
    return transcript, hosts


async def render(store: Store, title: str, scenes: list[story_writer.Scene], cast: list[dict], accent: str,
                 sound_level: float, catalogue: list[dict], workdir: Path,
                 transport: httpx.AsyncBaseTransport | None = None) -> Made:
    """Make the story's one file: speak, lay out, mix, master, save. The working files live in a folder inside
    `workdir` that is removed at the end, so only the saved player remains. A voice that can't be reached is a
    VoiceUnavailable in one line; a missing or unreadable sound is left out with a log line."""
    wavs, voices = await speak_lines(store, scenes, cast, accent, transport)
    laid = lay_out(scenes, [wav_seconds(wav) for wav in wavs])
    sources, skipped = await find_sources(laid.sounds, catalogue)
    kept = [placed for placed in laid.sounds if placed.sound in sources]
    laid = dataclasses.replace(laid, sounds=kept)
    spans = [(line.start, line.start + line.seconds) for line in laid.speech]

    workdir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=workdir) as scratch:
        folder = Path(scratch)
        speech = folder / "speech.wav"
        speech.write_bytes(speech_track(wavs, [line.start for line in laid.speech], laid.length))
        speech_db = await measure_db(speech, spans)
        if speech_db is None:
            speech_db = -20.0
        plan = mix_plan(laid, sources, speech_db, sound_level)

        command = [encode.ffmpeg(), "-y", "-loglevel", "error", "-i", str(speech)]
        if plan.has_beds:
            envelope_file = folder / "envelope.f32"
            rise = rise_db(slider_db(sound_level))
            envelope_file.write_bytes(envelope_bytes(envelope(spans, laid.length, rise)))
            command += ["-f", "f32le", "-ar", str(ENVELOPE_RATE), "-ac", "1", "-i", str(envelope_file)]
        mix = folder / "mix.wav"
        beds = folder / "beds.wav"
        length = seconds_text(laid.length)
        command += [*plan.inputs, "-filter_complex", plan.graph,
                    "-map", "[story]", "-t", length, "-c:a", "pcm_f32le", str(mix)]
        if plan.has_beds:
            command += ["-map", "[beds]", "-t", length, "-c:a", "pcm_s16le", str(beds)]
        await run_ffmpeg(command)

        gap = None
        if plan.has_beds:
            beds_db = await measure_db(beds, spans)
            if beds_db is not None:
                gap = round(speech_db - beds_db, 1)

        mastered = folder / "master.wav"
        loudness = await master(mix, mastered)
        peaks = folder / "peaks.wav"
        await run_ffmpeg([encode.ffmpeg(), "-y", "-loglevel", "error", "-i", str(mastered), "-ac", "1",
                          "-ar", str(PEAKS_RATE), "-c:a", "pcm_s16le", str(peaks)])
        encoded = folder / "story.m4a"
        await run_ffmpeg([encode.ffmpeg(), "-y", "-loglevel", "error", "-i", str(mastered), "-c:a", "aac",
                          "-b:a", AAC_BITRATE, "-movflags", "+faststart", str(encoded)])

        transcript, hosts = transcript_and_hosts(laid, cast, voices)
        meta = {**media.wav_info(peaks.read_bytes()), "format": "story", "hosts": hosts, "transcript": transcript}
        saved = media.save(encoded.read_bytes(), "podcast", "m4a", "audio/mp4", title, meta)

    log.info("audio story %r: speech %s dB above the beds (the slider promises %.1f), %s LUFS",
             title, gap, -slider_db(sound_level), loudness)
    return Made(media=saved, gap_db=gap, loudness_lufs=loudness, skipped=skipped)


async def write(job: jobs.Job, turn, browser) -> None:
    """The writing step: the story writer's focused turn with the sound listing from the user's library, then the
    title and the scenes onto the job. A story never uses the browser."""
    request = job.data["request"]
    catalogue = await sound_library.catalogue()
    listing = sound_library.writer_listing(catalogue)
    written = await story_writer.write(request, catalogue, listing, turn)
    job.title = jobs.title_after_writing(written.title, job)
    job.data["scenes"] = written.scenes
    job.data["catalogue"] = catalogue
    job.data["note"] = written.note
    if written.note:
        log.info("audio story %s: %s", job.slug, written.note)


async def make(job: jobs.Job, browser, transport) -> dict:
    """The making step: the story rendered to one file; its levels kept in the job's levels.json. Returns the story
    player's media for the message."""
    request = job.data["request"]
    sound_level = job.data.get("sound_level", DEFAULT_SOUND_LEVEL)
    made = await render(jobs.hooks["store"], job.title, job.data["scenes"], request.cast, request.accent, sound_level,
                        job.data["catalogue"], job.folder, transport=transport)
    levels = {"sound_level": sound_level, "promised_gap_db": -slider_db(sound_level), "measured_gap_db": made.gap_db,
              "loudness_lufs": made.loudness_lufs, "sounds_left_out": made.skipped, "note": job.data.get("note", "")}
    (job.folder / "levels.json").write_text(json.dumps(levels, indent=1), encoding="utf-8")
    return made.media


# Errors whose words are written for the user: the voice isn't running, or didn't answer, or a cast voice isn't there.
KNOWN_ERRORS = (voice.VoiceUnavailable,)
KIND = jobs.Kind(word="audio story", folder=FOLDER, write=write, make=make, known_errors=KNOWN_ERRORS)
jobs.KINDS["story"] = KIND
