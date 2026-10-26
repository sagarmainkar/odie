"""The audio story as one kind of thing Odie makes in the background (odie.making.jobs). Its writing step is the
story writer (odie.making.story_writer), the only model call: it writes the script and chooses the sound. Its making
step is plain code, the same every time:

1. speak every line in its speaker's voice (grouped by voice, the quiet before and after each line trimmed);
2. lay the story out in time (lay_out): scene by scene, the lines with their pauses, each scene's bed and music,
   the hits, and the transitions;
3. mix it with one ffmpeg graph (mix_plan): every bed and music file cut to its steady part and made a loop unit
   that repeats with a crossfade, never a hole, at its seam (seamless_loop), matched to the speech's loudness, then set
   to the slider's level below it, ducked under speech by one smooth envelope (envelope), the hits at fixed peaks;
4. master it: 48 kHz stereo, one gain to about -16 LUFS and a true-peak limiter at -2 dBTP, encoded as AAC; then
   measure the encoded file: its loudness, its true peak, and how far the speech sits above the beds (the gap the
   slider promises), kept in the job's levels.json;
5. save one file, AAC in .m4a, as the chat's story player. Nothing else is posted.

Importing this module registers the kind as "story", with its jobs under <workspace>/stories/<slug>/ (job.json,
brief.md, script.json, timeline.json and levels.json; the audio is kept with Odie's media, like every player in the
chat).

job.data carries "request" (story_writer.Request) and "sound_level" (10–40) from the chat, and "scenes" and
"catalogue" from the writing step to the making step."""
import dataclasses
import itertools
import json
import logging
import math
import re
import statistics
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
SCRIPT_FILE = "script.json"  # the script as the writer sent it and the check accepted it
TIMELINE_FILE = "timeline.json"  # the story laid out in time: every line and sound, with its gain
LEVELS_FILE = "levels.json"  # what was measured on the finished file

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
# A bed's peaks are held this far under the speech's loudest word: a sparse bed matched by its average (a campfire's
# crackle, quiet between pops) would otherwise peak far over full scale. Its loudness, and so the gap, stays as matched.
BED_PEAK_UNDER_SPEECH_PEAK_DB = 3.0
LOWEST_LIMIT = 0.0625  # alimiter's lowest limit (-24 dBFS)

ENVELOPE_RATE = 1000  # values a second in the duck envelope (it is upsampled in the mix)
DUCK_PAD = 0.15  # the beds are fully down this long before a line's first word and after its last
DUCK_RAMP = 0.4  # seconds the beds take to go down or come back up: slow enough never to pump
MIN_RISE_GAP = 1.5  # a gap between lines shorter than this (after the pads) keeps the beds down

LOOP_CROSSFADE = 1.0  # each time a bed or music repeats, its end crossfades into its start over this long
QUIET_DB = 3.0  # a bed's start or end this far under its usual level is its own fade, cut before it loops
# (6 dB left Night Camp's seam 2.3 dB down; 3 dB, 0.9 dB, as its own ups and downs are)
STEADY_RUN = 5  # windows in a row at the usual level that mark where a bed is steady (half a second)
LEVEL_WINDOW = 0.1  # seconds a window when reading a sound's level over time
MOST_TRIMMED = 0.25  # the most of a bed's length cut from either end

BED_FADE_IN = 1.5  # a scene's bed and music fade in over this long
BED_FADE_OUT = 1.5  # …and out over this long at a stinger or a silence (a crossfade takes its own seconds)
STORY_TAIL = 3.0  # after the last line, the beds play on this long, fading out

# A hit's peak against the loudest word, by the writer's word: a low owl well under the speech, an up-front door slam
# about as loud as the loudest line. Set against the speech, not full scale, so a hot voice and a quiet one get the
# same balance.
HIT_UNDER_SPEECH_PEAK_DB = {"low": -10.0, "normal": -4.0, "up front": 0.0}
HIT_ATTACK = 0.3  # a hit's first 0.3 s is its loud part: it never covers a line's first word
HIT_MAX_SECONDS = 8.0  # a hit plays at most this long…
HIT_FADE = 0.3  # …and a longer one fades out over its last 0.3 s

TARGET_LUFS = -16.0  # the whole story's loudness, as podcasts are: one gain takes the mix there…
LIMIT_CEILING = -2.0  # …and a limiter holds its true peak here (dBTP), before the AAC encoding…
MOST_TRUE_PEAK = -1.5  # …so the encoded file's true peak stays at or under this; over it, the limiter goes lower once
OVERSAMPLE = 4  # the limiter runs at 4 × 48 kHz, so it catches the peaks between samples (the true peak)
LIMITER_ATTACK_MS = 1.0
LIMITER_RELEASE_MS = 60.0
SILENT_LUFS = -70.0  # a mix this quiet or quieter has nothing to bring up: its gain stays 0
MIN_ALONE = 0.5  # seconds: a span shorter than this, where only the beds play, isn't measured
MEASURE_SECONDS = 60  # how much of a sound file is measured for its loudness
MEASURE_FRAME = 256  # samples a frame when measuring only where people speak
AAC_BITRATE = "160k"
PEAKS_RATE = 4000  # the waveform is drawn from a small mono copy

MEAN = re.compile(r"mean_volume: (-?[\d.]+) dB")
WINDOW_RMS = re.compile(r"lavfi\.astats\.Overall\.RMS_level=(\S+)")
MAX = re.compile(r"max_volume: (-?[\d.]+) dB")
INTEGRATED = re.compile(r"I:\s+(-?[\d.]+) LUFS")
PEAK = re.compile(r"Peak:\s+(-?[\d.]+|-inf) dBFS")
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
    """The mix as ffmpeg takes it: the sound inputs (after the speech and the envelope), the filter graph, whether
    there are beds (an envelope input, and a beds-only output for measuring the gap), and each sound with the gain it
    plays at (for the job's timeline.json)."""
    inputs: list[str]
    graph: str
    has_beds: bool
    gains: list[tuple[Placed, float]] = field(default_factory=list)


@dataclass
class Made:
    """A finished story: the player's media; the gap (dB the speech sits above the beds; None without beds) and
    where it was measured ("the encoded file", or "the mix" when the beds never play alone); the encoded file's
    loudness and true peak; the sounds left out; and the story laid out in time with its levels (timeline_of)."""
    media: dict
    gap_db: float | None
    loudness_lufs: float | None
    true_peak_db: float | None = None
    gap_measured_on: str = ""
    skipped: list[str] = field(default_factory=list)
    timeline: dict = field(default_factory=dict)


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


def hit_db(level: str, source: Source, speech_peak_db: float) -> float:
    """The gain that puts a hit's peak where its word says, against the speech's loudest peak
    (HIT_UNDER_SPEECH_PEAK_DB): "low" on a file peaking at -6 dB, the speech peaking at -3 -> -3 - 10 - -6 = -7;
    "up front" -> +3 (level with the speech's peak)."""
    under = HIT_UNDER_SPEECH_PEAK_DB.get(level, HIT_UNDER_SPEECH_PEAK_DB["normal"])
    return speech_peak_db + under - source.max_db


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


def bed_limit(speech_peak_db: float) -> float:
    """The limiter's level for a bed's peaks, as a share of full scale: BED_PEAK_UNDER_SPEECH_PEAK_DB under the
    speech's peak, never under alimiter's lowest. Speech peaking at -3 dBFS -> 0.5012 (-6 dBFS); at -30 -> 0.0625."""
    return max(LOWEST_LIMIT, 10 ** ((speech_peak_db - BED_PEAK_UNDER_SPEECH_PEAK_DB) / 20))


def bed_filter(k: int, placed: Placed, source: Source, gain: float, limit: float, envelope_label: str,
               out: str) -> str:
    """One bed or music bed, input k (read round and round): cut to its time, faded in and out, set to its gain, its
    peaks held at `limit` (bed_limit), delayed to its start, then multiplied by the duck envelope, and split for the
    story and the beds-only bus."""
    fade_out_start = max(0.0, placed.seconds - placed.fade_out)
    return (f"[{k}:a]{to_story_format(source.channels)},atrim=duration={seconds_text(placed.seconds)},"
            f"asetpts=PTS-STARTPTS,afade=t=in:d={seconds_text(placed.fade_in)},"
            f"afade=t=out:st={seconds_text(fade_out_start)}:d={seconds_text(placed.fade_out)},volume={db_text(gain)},"
            f"alimiter=limit={limit:.4f}:attack={LIMITER_ATTACK_MS}:release={LIMITER_RELEASE_MS}:level=false,"
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


def mix_plan(laid: Laid, sources: dict[str, Source], loops: dict[str, Source], speech_db: float,
             sound_level: float, speech_peak_db: float) -> MixPlan:
    """The one ffmpeg graph for the whole story. Input 0 is the speech track; input 1 the duck envelope (when there
    are beds); then each sound. Beds and music play from their loop units (`loops`, read round and round), matched to
    the speech (matched_db), set to the slider's level under it and raised by the rise (the envelope takes them back
    down under speech); hits play from `sources`, set by their peak against the speech's (hit_db).
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
    gains = []
    for n, placed in enumerate(beds):
        source = loops[placed.sound]
        if placed.role == "music":
            under = music_under_db(placed.level, slider)
        else:
            under = bed_under_db(placed.level, slider)
        gain = matched_db(speech_db, source) + under + rise
        gains.append((placed, gain))
        parts.append(bed_filter(k, placed, source, gain, bed_limit(speech_peak_db), f"e{n}", f"b{n}"))
        inputs += ["-stream_loop", "-1", "-i", source.path]
        story_labels += f"[mb{n}]"
        bed_labels += f"[qb{n}]"
        k += 1
    for n, placed in enumerate(hits):
        source = sources[placed.sound]
        gain = hit_db(placed.level, source, speech_peak_db)
        gains.append((placed, gain))
        parts.append(hit_filter(k, placed, source, gain, f"h{n}"))
        inputs += ["-i", source.path]
        story_labels += f"[h{n}]"
        k += 1
    story_count = 1 + len(beds) + len(hits)
    parts.append(f"{story_labels}amix=inputs={story_count}:normalize=0:duration=longest[story]")
    if has_beds:
        parts.append(f"{bed_labels}amix=inputs={len(beds)}:normalize=0:duration=longest[beds]")
    return MixPlan(inputs=inputs, graph=";".join(parts), has_beds=has_beds, gains=gains)


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


# Beds that loop without a hole at the seam.

async def window_levels(path: Path) -> list[float]:
    """A sound's level over time, in dBFS, one value every LEVEL_WINDOW seconds (silence as -120): a steady tone ->
    the same value throughout; iMovie's Ocean Surf -> about -96 at the start, rising to about -22 by 1.7 s."""
    samples = round(RATE * LEVEL_WINDOW)
    windows = (f"aresample={RATE},asetnsamples=n={samples}:p=0,astats=metadata=1:reset=1,"
               f"ametadata=print:key=lavfi.astats.Overall.RMS_level")
    command = [encode.ffmpeg(), "-hide_banner", "-nostats", "-i", str(path), "-af", windows, "-f", "null", "-"]
    _code, stderr = await encode.run(command)
    levels = []
    for value in WINDOW_RMS.findall(stderr.decode("utf-8", errors="replace")):
        try:
            level = float(value)
        except ValueError:
            level = -120.0
        if not math.isfinite(level):
            level = -120.0
        levels.append(level)
    return levels


def body_span(levels: list[float]) -> tuple[float, float]:
    """Decides where a bed is steady, in seconds: from the first STEADY_RUN windows in a row above its usual level
    (the median) less QUIET_DB, to the last such run; the fade-in before and the fade-out after are cut, but never more
    than MOST_TRIMMED of the length at either end. Ocean Surf's 100 ms levels, fading in over 1.3 s and out over 0.9 s
    of 10.7 -> (1.7, 9.9); a steady 5 s -> (0.0, 5.0); a 10 s file quiet for its first 4 s -> (2.5, 10.0)."""
    length = len(levels) * LEVEL_WINDOW
    if not levels:
        return 0.0, 0.0
    usual = statistics.median(levels)
    steady = [level > usual - QUIET_DB for level in levels]
    runs = [i for i in range(len(levels) - STEADY_RUN + 1) if all(steady[i:i + STEADY_RUN])]
    if not runs:
        return 0.0, length
    head = runs[0] * LEVEL_WINDOW
    tail = (runs[-1] + STEADY_RUN) * LEVEL_WINDOW
    most = length * MOST_TRIMMED
    return round(min(head, most), 3), round(max(tail, length - most), 3)


def can_crossfade(head: float, tail: float) -> bool:
    """Decides whether a bed's steady part is long enough to loop with a crossfade: at least three crossfades long,
    so the crossfade is a small part of each repeat. (1.7, 9.9) -> True; (0.1, 1.9) -> False (it loops as it is)."""
    return tail - head >= 3 * LOOP_CROSSFADE


def loop_unit_graph(channels: int, head: float, tail: float) -> str:
    """The ffmpeg graph that makes a bed's loop unit from its steady part (head to tail): the part less its first
    LOOP_CROSSFADE seconds (input 0), with its end crossfaded, at equal power, into those first seconds (input 1, the
    same file again: one input split in two starves acrossfade). The unit ends where it starts, so played round and
    round it has no seam: a steady part of 1.7–9.9 s -> a unit of 7.2 s."""
    opening_end = seconds_text(head + LOOP_CROSSFADE)
    story_format = to_story_format(channels)
    return (f"[0:a]{story_format},atrim=start={opening_end}:end={seconds_text(tail)},asetpts=PTS-STARTPTS[rest];"
            f"[1:a]{story_format},atrim=start={seconds_text(head)}:end={opening_end},asetpts=PTS-STARTPTS[opening];"
            f"[rest][opening]acrossfade=d={seconds_text(LOOP_CROSSFADE)}:c1=qsin:c2=qsin[unit]")


async def seamless_loop(source: Source, folder: Path) -> Source:
    """A bed or music file as a loop unit that repeats with no dip at the seam (loop_unit_graph), written in `folder`
    as 48 kHz stereo and measured again; the file as it is when its steady part is too short to crossfade."""
    head, tail = body_span(await window_levels(Path(source.path)))
    if not can_crossfade(head, tail):
        return source
    unit = folder / f"loop-{Path(source.path).stem}-{len(list(folder.glob('loop-*')))}.wav"
    await run_ffmpeg([encode.ffmpeg(), "-y", "-loglevel", "error", "-i", source.path, "-i", source.path,
                      "-filter_complex", loop_unit_graph(source.channels, head, tail), "-map", "[unit]",
                      "-c:a", "pcm_f32le", str(unit)])
    measured = await measure_source(unit, tail - head - LOOP_CROSSFADE)
    if measured is None:
        return source
    return measured


async def seamless_loops(sounds: list[Placed], sources: dict[str, Source], folder: Path) -> dict[str, Source]:
    """Every bed and music the story plays, as its loop unit (seamless_loop), by id; made once a sound."""
    loops: dict[str, Source] = {}
    for placed in sounds:
        if placed.role == "hit" or placed.sound in loops:
            continue
        loops[placed.sound] = await seamless_loop(sources[placed.sound], folder)
    return loops


async def measure_peak(path: Path) -> float | None:
    """A file's loudest sample, in dBFS (the speech's loudest word, for the hits); None when ffmpeg can't read it."""
    command = [encode.ffmpeg(), "-hide_banner", "-nostats", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"]
    _code, stderr = await encode.run(command)
    return number_after(MAX, stderr.decode("utf-8", errors="replace"))


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


@dataclass(frozen=True)
class Loudness:
    """How loud a file is over its whole length (EBU R 128): its integrated loudness and its true peak."""
    lufs: float
    true_peak_db: float


async def loudness_of(path: Path) -> Loudness | None:
    """A file's integrated loudness (LUFS) and true peak (dBTP), from ffmpeg's ebur128 summary; None when there is
    none (an unreadable file)."""
    report = await run_ffmpeg([encode.ffmpeg(), "-hide_banner", "-nostats", "-i", str(path), "-af",
                               "ebur128=peak=true", "-f", "null", "-"])
    summary = report[report.rfind("Summary:"):]
    lufs = number_after(INTEGRATED, summary)
    found = PEAK.search(summary)
    if lufs is None or found is None:
        return None
    peak_text = found.group(1)
    true_peak = -120.0
    if peak_text != "-inf":
        true_peak = float(peak_text)
    return Loudness(lufs=lufs, true_peak_db=true_peak)


def master_gain_db(mix: Loudness | None) -> float:
    """The one gain that takes the mix to TARGET_LUFS: a mix at -21.4 LUFS -> +5.4; a silent or unmeasured mix -> 0."""
    if mix is None or mix.lufs <= SILENT_LUFS:
        return 0.0
    return TARGET_LUFS - mix.lufs


def master_filter(gain_db: float, ceiling_db: float) -> str:
    """The master as ffmpeg filters: one gain for the whole story (so the speech-to-bed gap stays as mixed), then a
    limiter at the ceiling, run oversampled so it holds the true peak, never adding gain of its own. (4.2, -2.0) ->
    "volume=4.20dB,aresample=192000,alimiter=limit=0.7943:…:level=false:…,aresample=48000"."""
    limit = 10 ** (ceiling_db / 20)
    return (f"volume={db_text(gain_db)},aresample={RATE * OVERSAMPLE},alimiter=limit={limit:.4f}:"
            f"attack={LIMITER_ATTACK_MS}:release={LIMITER_RELEASE_MS}:level=false:latency=true,aresample={RATE}")


def lower_ceiling(ceiling_db: float, true_peak_db: float) -> float | None:
    """Decides whether the master is made again with a lower limiter, from the encoded file's true peak (the AAC
    encoding can push it up a little): at or under MOST_TRUE_PEAK -> None (it stands); over -> the ceiling lowered by
    the overshoot and 0.3 dB more. (-2.0, -1.8) -> None; (-2.0, -1.2) -> -2.6."""
    if true_peak_db <= MOST_TRUE_PEAK:
        return None
    return round(ceiling_db - (true_peak_db - MOST_TRUE_PEAK) - 0.3, 2)


@dataclass(frozen=True)
class Mastered:
    """The encoded story (AAC in .m4a), its waveform's small copy, and how loud it came out."""
    encoded: Path
    peaks: Path
    loudness: Loudness | None
    gain_db: float
    ceiling_db: float


async def master(mix: Path, folder: Path) -> Mastered:
    """The mix brought to TARGET_LUFS by one gain, its true peak held by the limiter at LIMIT_CEILING, encoded as AAC
    and measured; made once more with a lower ceiling when the encoded file's true peak is over MOST_TRUE_PEAK."""
    gain = master_gain_db(await loudness_of(mix))
    ceiling = LIMIT_CEILING
    mastered = folder / "master.wav"
    encoded = folder / "story.m4a"
    for _attempt in range(2):
        await run_ffmpeg([encode.ffmpeg(), "-y", "-loglevel", "error", "-i", str(mix), "-af",
                          master_filter(gain, ceiling), "-ar", str(RATE), "-ac", "2", "-c:a", "pcm_f32le",
                          str(mastered)])
        await run_ffmpeg([encode.ffmpeg(), "-y", "-loglevel", "error", "-i", str(mastered), "-c:a", "aac",
                          "-b:a", AAC_BITRATE, "-movflags", "+faststart", str(encoded)])
        loudness = await loudness_of(encoded)
        if loudness is None:
            break
        lower = lower_ceiling(ceiling, loudness.true_peak_db)
        if lower is None:
            break
        log.info("audio story master: true peak %.1f dBTP after AAC; limiting at %.1f instead", loudness.true_peak_db,
                 lower)
        ceiling = lower
    peaks = folder / "peaks.wav"
    await run_ffmpeg([encode.ffmpeg(), "-y", "-loglevel", "error", "-i", str(mastered), "-ac", "1",
                      "-ar", str(PEAKS_RATE), "-c:a", "pcm_s16le", str(peaks)])
    return Mastered(encoded=encoded, peaks=peaks, loudness=loudness, gain_db=gain, ceiling_db=ceiling)


# Measuring the gap in the finished file.

def without(spans: list[tuple[float, float]], cuts: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """The spans with the cuts taken out: [(0, 10)] less [(2, 3), (5, 6)] -> [(0, 2), (3, 5), (6, 10)]."""
    left = list(spans)
    for cut_start, cut_end in cuts:
        kept = []
        for start, end in left:
            if cut_end <= start or cut_start >= end:
                kept.append((start, end))
                continue
            if start < cut_start:
                kept.append((start, cut_start))
            if cut_end < end:
                kept.append((cut_end, end))
        left = kept
    return left


def beds_alone_spans(laid: Laid, hit_seconds: dict[str, float]) -> list[tuple[float, float]]:
    """Decides where the finished story has its beds alone and fully up, to measure them there: inside a bed's (or a
    music bed's) steady part, past its fade-in and before its fade-out (so never in a crossfade); outside every
    ducked span and its DUCK_RAMP; away from every hit while it plays (hit_seconds by id, else HIT_MAX_SECONDS); at
    least MIN_ALONE long. A bed 0–16 s (fades 1.5 and 3) under lines at 6–8 and 12–13, a 0.8 s door at 0 ->
    [(1.5, 5.45), (8.55, 11.45)]."""
    steady = []
    for placed in laid.sounds:
        if placed.role != "hit":
            steady.append((placed.start + placed.fade_in, placed.start + placed.seconds - placed.fade_out))
    cuts = []
    for start, end in ducked_spans([(line.start, line.start + line.seconds) for line in laid.speech]):
        cuts.append((start - DUCK_RAMP, end + DUCK_RAMP))
    for placed in laid.sounds:
        if placed.role == "hit":
            seconds = min(hit_seconds.get(placed.sound, HIT_MAX_SECONDS), HIT_MAX_SECONDS)
            cuts.append((placed.start, placed.start + seconds))
    alone = without(merged(steady), cuts)
    return [(round(start, 3), round(end, 3)) for start, end in alone if end - start >= MIN_ALONE]


def merged(spans: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Overlapping spans as one: [(0, 5), (4, 9), (12, 14)] -> [(0, 9), (12, 14)]."""
    joined: list[list[float]] = []
    for start, end in sorted(spans):
        if end <= start:
            continue
        if joined and start <= joined[-1][1]:
            joined[-1][1] = max(joined[-1][1], end)
        else:
            joined.append([start, end])
    return [(start, end) for start, end in joined]


def speech_alone_db(with_beds_db: float, beds_db: float) -> float | None:
    """The speech's own level from the level where it speaks (the speech and the ducked beds under it) and the beds'
    level there, taking the beds' power out: (-18.0, -30.0) -> -18.28; the beds as loud as everything -> None."""
    speech_power = 10 ** (with_beds_db / 10) - 10 ** (beds_db / 10)
    if speech_power <= 0:
        return None
    return 10 * math.log10(speech_power)


async def gap_in_file(path: Path, beds: Path, laid: Laid, hit_seconds: dict[str, float]) -> float | None:
    """How far the speech sits above the beds in the finished file `path`. Where the beds play alone, fully up
    (beds_alone_spans), the file holds the beds alone; the mix's beds-only output (`beds`) says how much quieter they
    are under the lines than there (the rise, and the bed's own ups and downs between those moments). So the beds'
    level under the speech in the file is their level alone in the file less that difference; the speech is measured
    in the file where it speaks, the beds' power taken out. None when the beds never play alone."""
    alone = beds_alone_spans(laid, hit_seconds)
    spoken = [(line.start, line.start + line.seconds) for line in laid.speech]
    if not alone or not spoken:
        return None
    measured = [await measure_db(path, alone), await measure_db(path, spoken), await measure_db(beds, alone),
                await measure_db(beds, spoken)]
    if any(level is None for level in measured):
        return None
    file_alone, file_spoken, stem_alone, stem_spoken = measured
    beds_under = file_alone - (stem_alone - stem_spoken)
    speech = speech_alone_db(file_spoken, beds_under)
    if speech is None:
        return None
    return round(speech - beds_under, 1)


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


def timeline_of(laid: Laid, plan: MixPlan, speech_db: float, speech_peak_db: float, mastered: Mastered) -> dict:
    """What the job's timeline.json keeps, so a story can be checked or remixed elsewhere: its length, every line
    (who, what, when, how long), every sound (its role, id, level word, start, length, fades and the gain it plays
    at, in dB, beds before the rise is taken off under the lines) and the levels the mix and master used."""
    speech = [{"speaker": line.speaker, "text": line.text, "start": line.start, "seconds": round(line.seconds, 3)}
              for line in laid.speech]
    sounds = []
    for placed, gain in plan.gains:
        sounds.append({**dataclasses.asdict(placed), "gain_db": round(gain, 2)})
    levels = {"speech_db": round(speech_db, 2), "speech_peak_db": round(speech_peak_db, 2),
              "master_gain_db": round(mastered.gain_db, 2), "limit_ceiling_db": mastered.ceiling_db}
    return {"length": laid.length, "speech": speech, "sounds": sounds, "levels": levels}


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
        speech_peak_db = await measure_peak(speech)
        if speech_peak_db is None:
            speech_peak_db = -3.0
        loops = await seamless_loops(laid.sounds, sources, folder)
        plan = mix_plan(laid, sources, loops, speech_db, sound_level, speech_peak_db)

        command = [encode.ffmpeg(), "-y", "-loglevel", "error", "-i", str(speech)]
        rise = rise_db(slider_db(sound_level))
        if plan.has_beds:
            envelope_file = folder / "envelope.f32"
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

        mastered = await master(mix, folder)
        gap = None
        measured_on = ""
        if plan.has_beds:
            hit_seconds = {sound: source.seconds for sound, source in sources.items() if source.seconds > 0}
            gap = await gap_in_file(mastered.encoded, beds, laid, hit_seconds)
            measured_on = "the encoded file"
        if plan.has_beds and gap is None:
            gap = await mix_gap(beds, spans, speech_db)  # the beds never play alone: the gap as mixed
            measured_on = "the mix"

        timeline = timeline_of(laid, plan, speech_db, speech_peak_db, mastered)
        transcript, hosts = transcript_and_hosts(laid, cast, voices)
        meta = {**media.wav_info(mastered.peaks.read_bytes()), "format": "story", "hosts": hosts,
                "transcript": transcript}
        saved = media.save(mastered.encoded.read_bytes(), "podcast", "m4a", "audio/mp4", title, meta)

    loudness = mastered.loudness
    lufs = None
    true_peak = None
    if loudness is not None:
        lufs = loudness.lufs
        true_peak = loudness.true_peak_db
    log.info("audio story %r: speech %s dB above the beds on %s (the slider promises %.1f); %s LUFS, true peak %s "
             "dBTP (gain %.1f dB, limited at %.1f)", title, gap, measured_on, -slider_db(sound_level), lufs, true_peak,
             mastered.gain_db, mastered.ceiling_db)
    return Made(media=saved, gap_db=gap, loudness_lufs=lufs, true_peak_db=true_peak, gap_measured_on=measured_on,
                skipped=skipped, timeline=timeline)


async def mix_gap(beds: Path, spans: list[tuple[float, float]], speech_db: float) -> float | None:
    """The gap as mixed, before mastering: the speech's level over its lines less the beds-only output's there."""
    beds_db = await measure_db(beds, spans)
    if beds_db is None:
        return None
    return round(speech_db - beds_db, 1)


async def write(job: jobs.Job, turn, browser) -> None:
    """The writing step: the story writer's focused turn with the sound listing from the user's library, then the
    title and the scenes onto the job, and the accepted script into its script.json. A story never uses the
    browser."""
    request = job.data["request"]
    catalogue = await sound_library.catalogue()
    listing = sound_library.writer_listing(catalogue)
    written = await story_writer.write(request, catalogue, listing, turn)
    job.title = jobs.title_after_writing(written.title, job)
    job.data["scenes"] = written.scenes
    job.data["catalogue"] = catalogue
    job.data["note"] = written.note
    (job.folder / SCRIPT_FILE).write_text(json.dumps(written.script, indent=1, ensure_ascii=False), encoding="utf-8")
    if written.note:
        log.info("audio story %s: %s", job.slug, written.note)


async def make(job: jobs.Job, browser, transport) -> dict:
    """The making step: the story rendered to one file; its timeline kept in the job's timeline.json and what was
    measured in its levels.json. Returns the story player's media for the message."""
    request = job.data["request"]
    sound_level = job.data.get("sound_level", DEFAULT_SOUND_LEVEL)
    made = await render(jobs.hooks["store"], job.title, job.data["scenes"], request.cast, request.accent, sound_level,
                        job.data["catalogue"], job.folder, transport=transport)
    levels = {"sound_level": sound_level, "promised_gap_db": -slider_db(sound_level), "measured_gap_db": made.gap_db,
              "gap_measured_on": made.gap_measured_on, "loudness_lufs": made.loudness_lufs,
              "true_peak_db": made.true_peak_db, "asked_seconds": request.minutes * 60,
              "made_seconds": round(made.timeline.get("length", 0.0), 1), "sounds_left_out": made.skipped,
              "note": job.data.get("note", "")}
    (job.folder / LEVELS_FILE).write_text(json.dumps(levels, indent=1), encoding="utf-8")
    (job.folder / TIMELINE_FILE).write_text(json.dumps(made.timeline, indent=1, ensure_ascii=False), encoding="utf-8")
    return made.media


# Errors whose words are written for the user: the voice isn't running, or didn't answer, or a cast voice isn't there.
KNOWN_ERRORS = (voice.VoiceUnavailable,)
KIND = jobs.Kind(word="audio story", folder=FOLDER, write=write, make=make, known_errors=KNOWN_ERRORS)
jobs.KINDS["story"] = KIND
