"""Sound effects for explainer videos: the small set of sounds the writer may place under the narration, each a WAV
in the kit's sounds folder (odie/video/kit/sounds/, mono 44.1 kHz 16-bit), named for the writer. A hit plays once,
its own length (a whoosh on a cut, a ting when a number lands); a loop is ambience that repeats seamlessly for as
long as a cue asks (rain under a monsoon shot, footsteps under an army). The files are made by
scripts/sounds/build_sounds.py; the folder's README says how to replace one with a recording.

The writer places sounds in its page with Video.sounds([{scene: 2, at: 0, name: "footsteps", seconds: 6}, ...]); the
submit check reads them back (odie.video.page.check_with_cues) and cue_problem judges them against the narration.
Once the narration is spoken, resolve turns the cues into seconds from the video's start and mix lays the sounds under
the narration with one ffmpeg command; the mixed WAV replaces the narration in the MP4."""
import array
import logging
import math
import shutil
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from odie.video import beats, encode, page

log = logging.getLogger("odie.video")

FOLDER = Path(__file__).parent / "kit" / "sounds"


@dataclass(frozen=True)
class Sound:
    name: str
    kind: Literal["hit", "loop"]  # a hit plays once at its own length; a loop repeats for as long as asked
    seconds: float  # the file's length
    words: str  # what it sounds like and where it helps, for the writer choosing one


# Hits first, then loops, in the order the writer's list shows them.
SOUNDS: dict[str, Sound] = {sound.name: sound for sound in [
    Sound("whoosh", "hit", 0.8, "a fast air sweep, for a cut or a move"),
    Sound("click", "hit", 0.1, "a small soft click, for a choice, a switch or a button"),
    Sound("tick", "hit", 0.15, "one dry clock tick, for a moment, a count or time passing"),
    Sound("ting", "hit", 1.5, "a bright little ting, for a number or a fact that lands"),
    Sound("bell", "hit", 2.5, "a struck bell ringing out, for an hour, a temple or a school"),
    Sound("chime", "hit", 2.0, "three rising notes, for a discovery or a happy turn"),
    Sound("thud", "hit", 0.6, "a heavy low thud, for something falling or a hard fact"),
    Sound("drum", "hit", 0.8, "one deep drum hit, for a reveal or a battle's start"),
    Sound("riser", "hit", 2.5, "a rising swell of suspense, ending on the reveal"),
    Sound("stamp", "hit", 0.5, "a stamp coming down on paper, for a decree, a treaty or an approval"),
    Sound("page", "hit", 0.7, "a paper page turning, for a new chapter, a book or a document"),
    Sound("key", "hit", 0.15, "one keyboard key press, for typing a word or a search"),
    Sound("whistle", "hit", 2.0, "a steam engine's whistle, for a train leaving or arriving"),
    Sound("applause-short", "hit", 1.5, "a short burst of applause, for a win or a famous moment"),
    Sound("rain", "loop", 4.0, "steady rain, for a monsoon, a storm or a grey day"),
    Sound("wind", "loop", 6.0, "wind in gusts, for a mountain pass, a desert or a cold open place"),
    Sound("sea", "loop", 8.0, "waves on a shore in a slow swell, for a beach, a coast or a voyage"),
    Sound("crowd", "loop", 5.0, "a crowd's low murmur, for a market, a court or a gathering"),
    Sound("footsteps", "loop", 4.0, "several feet marching in step, for an army, a march or a long walk"),
    Sound("heartbeat", "loop", 4.0, "a slow heartbeat, for tension, fear or a life in the balance"),
    Sound("train", "loop", 4.0, "a steam train chugging with a hiss, for railways and journeys"),
    Sound("engine", "loop", 4.0, "a low engine hum, for a factory, a ship or a machine at work"),
    Sound("typewriter", "loop", 5.0, "a typewriter's keys, for a writer, a newsroom or a letter being written"),
    Sound("applause", "loop", 5.0, "ongoing applause in a hall, for a speech, a stage or a crowd's approval"),
    Sound("night", "loop", 5.0, "crickets at night, for a village, a camp or a quiet dark scene"),
    Sound("forest", "loop", 6.0, "faint leaves and birds, for woods, a garden or an early morning"),
]}


def path(name: str) -> Path:
    """Where the named sound's WAV is: "whoosh" -> odie/video/kit/sounds/whoosh.wav. It does not check the name
    (is_known does) or that the file is there."""
    return FOLDER / f"{name}.wav"


def is_known(name: str) -> bool:
    """Decides whether the writer named a sound in the set, exactly as listed: "whoosh" -> True; "applause-short" ->
    True; "Whoosh" (capitalised), "explosion" (not in the set) or "" -> False."""
    return name in SOUNDS


def lookup(name: str, kit_sounds: dict[str, Path] | None = None) -> tuple[Sound, Path] | None:
    """The sound a cue's name plays in this video, and its file: a brand kit's own sound first (a kit sound with a
    built-in's name plays instead of it, in this video only; a kit sound is a hit), else Odie's. "whoosh" -> Odie's
    whoosh and kit/sounds/whoosh.wav; "ting" with a kit {"ting": <kit>/ting.wav} -> the kit's ting; "explosion" ->
    None."""
    if kit_sounds and name in kit_sounds:
        return Sound(name, "hit", 0.0, "the brand kit's own sound"), kit_sounds[name]
    sound = SOUNDS.get(name)
    if sound is None:
        return None
    return sound, path(name)


def describe(sound: Sound) -> str:
    """The sound's line in the writer's list: its name, its words and its kind, with a hit's length:
    whoosh -> "whoosh — a fast air sweep, for a cut or a move (hit, 0.8 s)"; whistle -> "... (hit, 2 s)";
    rain -> "rain — steady rain, for a monsoon, a storm or a grey day (loop)"."""
    if sound.kind == "loop":
        return f"{sound.name} — {sound.words} (loop)"
    return f"{sound.name} — {sound.words} (hit, {sound.seconds:g} s)"


def listing() -> str:
    """The writer's list of sounds, one line each, hits first and then loops."""
    lines = [describe(sound) for sound in SOUNDS.values()]
    return "\n".join(lines)


# ---- Cues: where the writer's page places sounds, checked against the narration before the video is accepted ----

MAX_CUES_PER_SCENE = 6
MAX_CUES = 40
CUE_KEYS = ("scene", "name", "at", "beat", "seconds", "gain")  # a cue's keys, as Video.sounds takes them


def is_number(value) -> bool:
    """Decides whether a cue's value is a plain number: 1.5 -> True; 0 -> True; "1.5", None or True -> False (JSON's
    true is no number, though Python counts it as 1)."""
    if isinstance(value, bool):
        return False
    return isinstance(value, int | float)


def is_whole(value) -> bool:
    """Decides whether a cue's value is a whole number, as a scene or a beat must be: 2 -> True; 1.5, "2" or True ->
    False."""
    if isinstance(value, bool):
        return False
    return isinstance(value, int)


def shape_problem(number: int, cue) -> str | None:
    """Decides whether cue `number` has the shape Video.sounds takes (the kit keeps every item as given, so this is
    the one place a cue's shape is judged): the first thing wrong, or None.
    {"scene": 2, "beat": 1, "name": "whoosh"} -> None; {"scene": 1, "name": "ting"} -> "cue 1 has neither at nor
    beat …"; {"scene": 1, "at": 0, "name": "ting", "gain": 2} -> "cue 1 has gain 2; …"."""
    where = f"Video.sounds: cue {number}"
    if not isinstance(cue, dict):
        return f'{where} isn\'t an object like {{scene: 2, at: 1.5, name: "whoosh"}}.'
    for key in cue:
        if key not in CUE_KEYS:
            return f'{where} has a key "{key}"; the keys are scene, name, at or beat, seconds and gain.'
    scene = cue.get("scene")
    if not is_whole(scene) or scene < 1:
        return f"{where} has scene {scene!r}; a scene is a whole number from 1 (the first)."
    name = cue.get("name")
    if not isinstance(name, str):
        return f'{where} has name {name!r}; a name is a sound\'s name as text, like "whoosh".'
    if "at" in cue and "beat" in cue:
        return f"{where} has both at and beat; give one: at (seconds into the scene) or beat (a phrase, from 0)."
    if "at" not in cue and "beat" not in cue:
        return f"{where} has neither at nor beat; give one: at (seconds into the scene) or beat (a phrase, from 0)."
    if "at" in cue:
        at = cue["at"]
        if not is_number(at) or at < 0:
            return f"{where} has at {at!r}; at is seconds into the scene, 0 or more."
    if "beat" in cue:
        beat = cue["beat"]
        if not is_whole(beat) or beat < 0:
            return f"{where} has beat {beat!r}; a beat is a whole number from 0 (the scene's first phrase)."
    if "seconds" in cue:
        seconds = cue["seconds"]
        if not is_number(seconds) or seconds <= 0:
            return f"{where} has seconds {seconds!r}; seconds (how long a loop plays) is more than 0."
    if "gain" in cue:
        gain = cue["gain"]
        if not is_number(gain) or not 0 <= gain <= 1:
            return f"{where} has gain {gain!r}; a gain is from 0 (silent) to 1 (full)."
    return None


def name_problem(number: int, cue: dict, kit_names: tuple[str, ...] = ()) -> str | None:
    """Decides whether cue `number` names a sound in the set, or one of a brand kit's own (`kit_names`): "whoosh" ->
    None; "wooosh" -> "Video.sounds: cue 2: there is no sound called 'wooosh'; the sounds are: whoosh, click, …"
    (every name, the kit's too, not the whole listing)."""
    name = cue["name"]
    if is_known(name) or name in kit_names:
        return None
    names = ", ".join([*SOUNDS, *(kit_name for kit_name in kit_names if kit_name not in SOUNDS)])
    return f"Video.sounds: cue {number}: there is no sound called '{name}'; the sounds are: {names}."


def scenes_in_words(count: int) -> str:
    """A scene count as said: 1 -> "1 scene"; 7 -> "7 scenes"."""
    if count == 1:
        return "1 scene"
    return f"{count} scenes"


def scene_problem(number: int, cue: dict, scene_count: int) -> str | None:
    """Decides whether cue `number`'s scene is one the video has (one scene per narration part): scene 7 of 7 ->
    None; scene 9 of 7 -> "Video.sounds: cue 2 names scene 9; this video has 7 scenes …"."""
    scene = cue["scene"]
    if scene <= scene_count:
        return None
    return (f"Video.sounds: cue {number} names scene {scene}; this video has {scenes_in_words(scene_count)} (one per "
            "narration part).")


def beat_problem(number: int, cue: dict, narration: list[str]) -> str | None:
    """Decides whether a cue on a beat names a phrase its scene has ("|" in a scene's narration splits it into
    phrases, beats 0, 1, …): beat 1 of "A | B" -> None; beat 1 of a scene with no marks -> "Video.sounds: cue 1:
    scene 3 has 1 phrase (beats 0..0), so beat 1 isn't there. …"; a cue placed with at -> None."""
    if "beat" not in cue:
        return None
    beat = cue["beat"]
    scene = cue["scene"]
    count = len(beats.phrases(narration[scene - 1]))
    if beat < count:
        return None
    phrase_word = "phrases"
    if count == 1:
        phrase_word = "phrase"
    return (f"Video.sounds: cue {number}: scene {scene} has {count} {phrase_word} (beats 0..{count - 1}), so beat "
            f"{beat} isn't there. Use one of those beats, or at (seconds into the scene).")


def at_problem(number: int, cue: dict, lengths: list[float]) -> str | None:
    """Decides whether a cue placed with at starts inside its scene, as long as the scene is estimated from its words
    (odie.video.page.estimated_timings): at 6.4 in a 6.43 s scene -> None (it is cut at the scene's end); at 8.5 in
    that scene -> "Video.sounds: cue 4 is at 8.5 s but scene 2 is about 6.4 s long. …"; a cue on a beat -> None."""
    if "at" not in cue:
        return None
    at = cue["at"]
    scene = cue["scene"]
    length = lengths[scene - 1]
    if at <= length:
        return None
    about = round(length, 1)
    return (f"Video.sounds: cue {number} is at {at:g} s but scene {scene} is about {about:g} s long. Place it "
            "earlier in the scene, or on a beat.")


def crowded_scene_problem(cues: list[dict]) -> str | None:
    """Decides whether any scene has more than MAX_CUES_PER_SCENE cues: six in scene 2 -> None; seven in scene 2 ->
    "Video.sounds: scene 2 has 7 cues; at most 6. …" (the first such scene, in scene order)."""
    per_scene = {}
    for cue in cues:
        scene = cue["scene"]
        per_scene[scene] = per_scene.get(scene, 0) + 1
    for scene in sorted(per_scene):
        count = per_scene[scene]
        if count > MAX_CUES_PER_SCENE:
            return (f"Video.sounds: scene {scene} has {count} cues; at most {MAX_CUES_PER_SCENE}. Keep the two or "
                    "three where the picture turns.")
    return None


def too_many_problem(cues: list[dict]) -> str | None:
    """Decides whether the video has more than MAX_CUES cues in all: 40 -> None; 41 -> "Video.sounds: there are 41
    cues; at most 40 in all. …"."""
    count = len(cues)
    if count <= MAX_CUES:
        return None
    return (f"Video.sounds: there are {count} cues; at most {MAX_CUES} in all. Keep the ones where the picture "
            "turns; silence is a choice too.")


def cue_problem(cues: list[dict], narration: list[str], kit_names: tuple[str, ...] = ()) -> str | None:
    """Decides whether the page's sound cues (Video.soundCues(), as the check read them) fit the video: the first
    problem as words the writer can act on, or None. Cue by cue, in list order: its shape, then a name not in the
    set, a scene the video doesn't have, a beat its scene doesn't have, an at past its scene's estimated length; then
    more than MAX_CUES_PER_SCENE in one scene, then more than MAX_CUES in all. A loop asked to play longer than its
    scene is fine (it is cut at the scene's end). [] -> None; [{"scene": 3, "beat": 1, "name": "whoosh"}] where
    scene 3 is one phrase -> "Video.sounds: cue 1: scene 3 has 1 phrase (beats 0..0), so beat 1 isn't there. …".
    A brand kit's own sounds (`kit_names`) count as names in the set."""
    lengths = page.estimated_timings(narration)["lengths"]
    for number, cue in enumerate(cues, start=1):
        problem = own_problem(number, cue, narration, lengths, kit_names)
        if problem:
            return problem
    problem = crowded_scene_problem(cues)
    if problem:
        return problem
    return too_many_problem(cues)


def own_problem(number: int, cue, narration: list[str], lengths: list[float],
                kit_names: tuple[str, ...] = ()) -> str | None:
    """Decides whether cue `number` is right on its own, whatever the other cues are: its shape, then its name, its
    scene, its beat and its at, the first thing wrong as words (`lengths` are the scenes' estimated lengths).
    {"scene": 1, "at": 0, "name": "rain"} -> None; {"scene": 1, "at": 0, "name": "wooosh"} -> "Video.sounds: cue 1:
    there is no sound called 'wooosh'; …"."""
    problem = shape_problem(number, cue)
    if problem:
        return problem
    problem = name_problem(number, cue, kit_names)
    if problem:
        return problem
    problem = scene_problem(number, cue, len(narration))
    if problem:
        return problem
    problem = beat_problem(number, cue, narration)
    if problem:
        return problem
    return at_problem(number, cue, lengths)


def good_cues(cues: list, narration: list[str], kit_names: tuple[str, ...] = ()) -> list[dict]:
    """The cues that pass cue_problem's rules, in the writer's order, for when the writer has already been told once
    and the video goes on without the rest: a cue with a problem of its own is left out, and so is any cue past the
    first MAX_CUES_PER_SCENE of its scene or past the first MAX_CUES in all.
    [{"scene": 1, "at": 0, "name": "rain"}, {"scene": 1, "at": 1, "name": "wooosh"}] -> [{"scene": 1, "at": 0,
    "name": "rain"}]; seven good cues in scene 2 -> its first six."""
    lengths = page.estimated_timings(narration)["lengths"]
    kept = []
    per_scene = {}
    for number, cue in enumerate(cues, start=1):
        if own_problem(number, cue, narration, lengths, kit_names):
            continue
        scene = cue["scene"]
        in_scene = per_scene.get(scene, 0)
        if in_scene >= MAX_CUES_PER_SCENE:
            continue
        if len(kept) >= MAX_CUES:
            break
        per_scene[scene] = in_scene + 1
        kept.append(cue)
    return kept


# ---- The mix: the cues as seconds from the video's start, laid under the narration with one ffmpeg command ----

DEFAULT_GAIN = {"loop": 0.35, "hit": 0.6}  # a cue's gain when the writer gave none
# How loud each kind plays at gain 1, as RMS in dBFS, whatever its file's own loudness (see level_db). A narration is
# typically -20 to -25 dBFS RMS: a loop sits about 8 dB under a quiet voice, and a hit about level with it. Set by
# ear: change these, not the files.
LOOP_RMS_DBFS = -30.0  # measured over the loop's whole file
HIT_RMS_DBFS = -22.0  # measured over the hit's loudest HIT_WINDOW_SECONDS
HIT_WINDOW_SECONDS = 0.1  # the stretch of a hit its loudness is measured over: its attack, which is what is heard
SILENT_DBFS = -96.0  # what a silent file measures (16-bit's floor), so the maths never takes the log of 0
LIMIT = 0.891    # the limiter's ceiling (-1 dB), so the sum never clips
FADE_SECONDS = 0.3  # a sound stopped short fades out over this long (at most a quarter of what it plays)
LOOP_FADE_IN_SECONDS = 0.05  # a loop fades in over this long, so one starting mid-scene doesn't pop
CODECS = {1: "pcm_u8", 2: "pcm_s16le", 3: "pcm_s24le", 4: "pcm_s32le"}  # a WAV's bytes a sample -> ffmpeg's codec


@dataclass(frozen=True)
class Placed:
    """One sound as the mix plays it: from `start` seconds into the video, for `seconds`, at `gain`."""
    start: float  # seconds from the video's start
    path: Path  # the sound's WAV
    seconds: float  # how long it plays: a hit its own length, cut at its scene's spoken end; a loop as long as
    # asked, or to its scene's end without seconds, cut at the next scene's start (or the narration's end)
    gain: float  # more than 0, at most 1: the cue's, or its kind's default
    kind: Literal["hit", "loop"]
    name: str
    frames: int  # the file's length in samples: the stretch a loop repeats
    cut: bool = False  # a hit stopped before its file's end (at its scene's spoken end); a loop always fades out


@dataclass(frozen=True)
class WavFormat:
    channels: int
    width: int  # bytes a sample
    rate: int  # samples a second
    frames: int  # the file's length in samples


def wav_format(path: Path) -> WavFormat:
    """A WAV's format and length: rain.wav -> WavFormat(channels=1, width=2, rate=44100, frames=176400)."""
    with wave.open(str(path), "rb") as file:
        return WavFormat(channels=file.getnchannels(), width=file.getsampwidth(), rate=file.getframerate(),
                         frames=file.getnframes())


def readable_format(path: Path) -> WavFormat | None:
    """A sound file's format, or None when the file is missing or isn't a WAV: rain.wav -> WavFormat(1, 2, 44100,
    176400); a deleted file, or a text file saved as rain.wav -> None."""
    try:
        return wav_format(path)
    except (OSError, EOFError, wave.Error):
        return None


def where_problem(cue: dict, timings: dict, narrated_scenes: int) -> str | None:
    """Decides whether a cue's scene and beat are among the spoken video's narrated scenes (the check made sure of it
    against the narration, so this only catches a job whose narration changed since): scene 2 of three -> None;
    scene 4 of three, even with Odie's credits card as a fourth scene in the timings -> "scene 4 isn't in the
    video"; beat 2 of a scene with beats [0.0, 1.5] -> "scene 3 has no beat 2"."""
    scene = cue["scene"]
    if scene > narrated_scenes:
        return f"scene {scene} isn't in the video"
    if "beat" not in cue:
        return None
    beat = cue["beat"]
    scene_beats = timings["beats"][scene - 1]
    if beat >= len(scene_beats):
        return f"scene {scene} has no beat {beat}"
    return None


def offset_in_scene(cue: dict, timings: dict) -> float:
    """Seconds into its scene where a cue starts: {"at": 1.5} -> 1.5; {"scene": 1, "beat": 2} with scene 1's beats
    [0.0, 2.0, 4.1] -> 4.1."""
    if "at" in cue:
        return cue["at"]
    scene_beats = timings["beats"][cue["scene"] - 1]
    return scene_beats[cue["beat"]]


def cue_gain(cue: dict, kind: str) -> float:
    """The cue's gain, or its kind's default when the writer gave none: {"gain": 0.5} -> 0.5; a loop without one ->
    0.35; a hit without one -> 0.6."""
    if "gain" in cue:
        return cue["gain"]
    return DEFAULT_GAIN[kind]


def loop_end(scene: int, timings: dict, narrated_scenes: int) -> float:
    """Decides where a loop in `scene` stops, in seconds from the video's start: at the next scene's start, so it runs
    through the breath between the scenes; in the last narrated scene, at the narration's end (Odie's credits card,
    if it follows, stays silent). Starts [0.0, 6.5, 13.0] and lengths [6.0, 6.0, 4.0]: scene 1 -> 6.5; scene 3 ->
    17.0; scene 3 with a credits card starting at 17.5 after it -> 17.0."""
    starts = timings["starts"]
    if scene < narrated_scenes:
        return starts[scene]
    last = narrated_scenes - 1
    return starts[last] + timings["lengths"][last]


def play_seconds(cue: dict, kind: str, file_seconds: float, room: float) -> float:
    """Decides how long a placed sound plays, given its `room` (for a hit, what is left of its scene's spoken length
    after it starts; for a loop, the seconds to loop_end). A hit plays its file's own length (a cue's seconds mean
    nothing to it), cut to the room; a loop plays the cue's seconds cut to the room, or the whole room without them.
    A 0.8 s whoosh with 6 s of room -> 0.8; a 1.5 s ting 5.9 s into a 6 s scene (0.1 s of room) -> 0.1; footsteps
    asked for 20 s with 6.5 s of room -> 6.5; sea asked for 2 s with 2.5 s of room -> 2.0; rain with no seconds and
    6.5 s of room -> 6.5."""
    if kind == "hit":
        return round(min(file_seconds, room), 3)
    if "seconds" in cue:
        return round(min(cue["seconds"], room), 3)
    return round(room, 3)


def place(number: int, cue: dict, timings: dict, narrated_scenes: int,
          kit_sounds: dict[str, Path] | None = None) -> Placed | None:
    """Cue `number` as the mix plays it, or None (with a log line) when it can't be played: a name not in the set, a
    scene or beat not among the narrated scenes, no room left (a hit at or past its scene's spoken end, a loop at or
    past loop_end; the check only estimated the lengths), a gain of 0, or a file that is missing, isn't a WAV or
    can't be measured (loudness_dbfs: a 16-bit WAV only). A hit stopped before its file's end is marked cut.
    With scene 2 at 6.5 s, 6.0 s long, and scene 3 at 13.0 s: {"scene": 2, "at": 5.9, "name": "ting"} ->
    Placed(start=12.4, seconds=0.1, kind="hit", cut=True, …); {"scene": 2, "at": 1, "name": "crowd"} ->
    Placed(start=7.5, seconds=5.5, kind="loop", …), through the breath to scene 3's start. A brand kit's sounds
    (`kit_sounds`) are found first (lookup)."""
    name = cue["name"]
    found = lookup(name, kit_sounds)
    if found is None:
        log.info("video sound cue %d left out: there is no sound called %r", number, name)
        return None
    sound, sound_path = found
    problem = where_problem(cue, timings, narrated_scenes)
    if problem:
        log.info("video sound cue %d (%s) left out: %s", number, name, problem)
        return None
    scene = cue["scene"]
    offset = offset_in_scene(cue, timings)
    start = round(timings["starts"][scene - 1] + offset, 3)
    room = round(timings["lengths"][scene - 1] - offset, 3)
    if sound.kind == "loop":
        room = round(loop_end(scene, timings, narrated_scenes) - start, 3)
    if room <= 0:
        log.info("video sound cue %d (%s) left out: it starts %.3g s into scene %d, with nothing of the scene left to "
                 "play it in", number, name, offset, scene)
        return None
    gain = cue_gain(cue, sound.kind)
    if gain <= 0:
        log.info("video sound cue %d (%s) left out: its gain is 0", number, name)
        return None
    file = readable_format(sound_path)
    if file is None:
        log.info("video sound cue %d (%s) left out: %s is missing or isn't a WAV", number, name, sound_path)
        return None
    file_seconds = file.frames / file.rate
    seconds = play_seconds(cue, sound.kind, file_seconds, room)
    cut = seconds < round(file_seconds, 3)
    placed = Placed(start=start, path=sound_path, seconds=seconds, gain=gain, kind=sound.kind, name=name,
                    frames=file.frames, cut=cut)
    try:
        loudness_dbfs(placed)  # measured now, and remembered for the mix
    except (OSError, EOFError, wave.Error) as e:
        log.info("video sound cue %d (%s) left out: its loudness can't be measured: %s", number, name, e)
        return None
    return placed


def resolve(cues: list[dict], timings: dict, narrated_scenes: int | None = None,
            kit_sounds: dict[str, Path] | None = None) -> list[Placed]:
    """The page's sound cues as the mix plays them, in the writer's order, from the spoken video's timings
    ({"starts": [...], "lengths": [...], "beats": [[...], ...]}, seconds; each scene's beats start at 0.0).
    `narrated_scenes` is how many of the timings' scenes the narration speaks: fewer than the timings hold when Odie's
    silent credits card follows them; None means all of them. A cue that can't be played is left out with a log line
    (see place), never an error. [] -> []; with scene 1 starting at 0.0 and its beats [0.0, 2.0, 4.1]:
    [{"scene": 1, "beat": 2, "name": "whoosh"}] -> [Placed(start=4.1, seconds=0.8, gain=0.6, kind="hit",
    name="whoosh", …)]. A brand kit's sounds (`kit_sounds`, {"ting": <kit>/ting.wav}) play instead of Odie's of the
    same name, and add their own names."""
    if narrated_scenes is None:
        narrated_scenes = len(timings["starts"])
    placed = []
    for number, cue in enumerate(cues, start=1):
        one = place(number, cue, timings, narrated_scenes, kit_sounds)
        if one is not None:
            placed.append(one)
    return placed


def wav_rms_dbfs(path: Path, window_seconds: float | None = None) -> float:
    """How loud a 16-bit WAV is, as its RMS in dBFS (a full-scale square wave is 0): over the whole file, or, given
    window_seconds, over its loudest stretch that long (the whole file when it is shorter). A silent file ->
    SILENT_DBFS. rain.wav -> -14.3; footsteps.wav -> -26.1; ting.wav -> -17.4, and with 0.1 s -> -9.9."""
    with wave.open(str(path), "rb") as file:
        if file.getsampwidth() != 2:
            raise wave.Error(f"{path.name} isn't 16-bit")
        samples_a_second = file.getframerate() * file.getnchannels()
        frames = file.readframes(file.getnframes())
    samples = array.array("h")
    samples.frombytes(frames)
    squares = [sample * sample for sample in samples]
    count = len(squares)
    loudest = sum(squares)
    if window_seconds is not None:
        count = min(count, round(window_seconds * samples_a_second))
        loudest = loudest_window_sum(squares, count)
    if loudest == 0:
        return SILENT_DBFS
    rms = math.sqrt(loudest / count)
    return 20 * math.log10(rms / 32768)


def loudest_window_sum(squares: list[int], count: int) -> int:
    """The largest sum of `count` squares in a row, slid one sample at a time: [1, 9, 4, 0] with 2 -> 13 (9 + 4)."""
    running = sum(squares[:count])
    loudest = running
    for i in range(count, len(squares)):
        running += squares[i] - squares[i - count]
        if running > loudest:
            loudest = running
    return loudest


measured: dict[tuple[Path, str], float] = {}  # (file, kind) -> its loudness in dBFS; the files don't change at run time


def loudness_dbfs(placed: Placed) -> float:
    """How loud a placed sound's file is, measured as its kind is heard, and remembered in `measured`. Decides the
    measure by kind: a loop plays round and round, so the ear hears its average, the RMS of its whole file (footsteps
    -> -26.1, rain -> -14.3); a hit is heard as its attack, so the RMS of its loudest HIT_WINDOW_SECONDS, which leaves
    out the silent tail a whole-file measure would count against a long hit (ting -> -9.9, not its whole file's
    -17.4)."""
    key = (placed.path, placed.kind)
    if key not in measured:
        window = None
        if placed.kind == "hit":
            window = HIT_WINDOW_SECONDS
        measured[key] = wav_rms_dbfs(placed.path, window)
    return measured[key]


def level_db(placed: Placed) -> float:
    """How much a placed sound's file is raised or lowered in the mix (the narration stays at 0 dB): to its kind's
    loudness at gain 1 (LOOP_RMS_DBFS or HIT_RMS_DBFS), from what its file measures (loudness_dbfs), then lowered by
    the gain (20·log10). So sounds of a kind play equally loud at the same gain, a sparse file as loud as a dense
    one. Footsteps (-26.1) at gain 1 -> -30 + 26.1 = -3.9; rain (-14.3) at gain 1 -> -15.7, at its default 0.35 ->
    -15.7 - 9.12 = -24.9; a ting (-9.9) at gain 1 -> -12.1; a whoosh (-13.6) at its default 0.6 -> -22 + 13.6 -
    4.44 = -12.8."""
    target = HIT_RMS_DBFS
    if placed.kind == "loop":
        target = LOOP_RMS_DBFS
    lowered = 20 * math.log10(placed.gain)
    return target - loudness_dbfs(placed) + lowered


def seconds_text(seconds: float) -> str:
    """Seconds as ffmpeg is given them, to the millisecond: 2 -> "2.0"; 0.1 -> "0.1"; 1.23456 -> "1.235"."""
    return str(round(float(seconds), 3))


def placing_filters(placed: Placed, voice: WavFormat) -> str:
    """The filters every sound ends with: brought to the narration's rate and channels (so the narration itself is
    never resampled and stays sample for sample as it was), delayed to its start, and set to its level (level_db). A
    whoosh at 1.0 s, gain 0.6, under a 24 kHz mono narration -> "aformat=sample_rates=24000:channel_layouts=1c,
    adelay=1000:all=1,volume=-12.82dB"."""
    delay_ms = round(placed.start * 1000)
    return (f"aformat=sample_rates={voice.rate}:channel_layouts={voice.channels}c,adelay={delay_ms}:all=1,"
            f"volume={level_db(placed):.2f}dB")


def fade_out_seconds(seconds: float) -> float:
    """How long a sound stopped short fades out, given how long it plays: FADE_SECONDS, or a quarter of what it plays
    when that is shorter. 6.5 -> 0.3; 0.4 -> 0.1; a hit cut to 0.1 -> 0.025."""
    quarter = seconds / 4
    return round(min(FADE_SECONDS, quarter), 3)


def fade_filters(placed: Placed) -> str:
    """Decides which fades a placed sound gets, as filters to put after its trim (each ending in a comma), so nothing
    stops in one sample with a click: a loop always fades in over LOOP_FADE_IN_SECONDS (it may start mid-scene) and
    out over its last fade_out_seconds (it is always cut, at its seconds, the next scene's start or the narration's
    end); a hit fades out only when it was cut at its scene's spoken end; a hit that plays whole gets none (it ends as
    it was made). Rain for 6.5 s -> "afade=t=in:d=0.05,afade=t=out:st=6.2:d=0.3,"; a ting cut to 0.5 s ->
    "afade=t=out:st=0.375:d=0.125,"; a whoosh played whole -> ""."""
    if placed.kind == "hit" and not placed.cut:
        return ""
    fade = fade_out_seconds(placed.seconds)
    fade_start = round(placed.seconds - fade, 3)
    fade_out = f"afade=t=out:st={seconds_text(fade_start)}:d={seconds_text(fade)},"
    if placed.kind == "hit":
        return fade_out
    fade_in = f"afade=t=in:d={seconds_text(LOOP_FADE_IN_SECONDS)},"
    return fade_in + fade_out


def loop_filter(placed: Placed, k: int, voice: WavFormat) -> str:
    """Ffmpeg's filters for a loop, input k: its whole file repeated for ever, cut to its seconds, faded in and out
    (fade_filters), then placed. Rain (176,400 samples) as input 2, from 2.0 s for 2 s at gain 0.35 ->
    "[2:a]aloop=loop=-1:size=176400,atrim=duration=2.0,afade=t=in:d=0.05,afade=t=out:st=1.7:d=0.3,aformat=…,
    adelay=2000:all=1,volume=-24.86dB[a2]"."""
    duration = seconds_text(placed.seconds)
    return (f"[{k}:a]aloop=loop=-1:size={placed.frames},atrim=duration={duration},{fade_filters(placed)}"
            f"{placing_filters(placed, voice)}[a{k}]")


def hit_filter(placed: Placed, k: int, voice: WavFormat) -> str:
    """Ffmpeg's filters for a hit, input k: played once, cut to its seconds (its own length, or less at its scene's
    end, then faded out: fade_filters), then placed. A whoosh as input 1 at 1.0 s, gain 0.6 ->
    "[1:a]atrim=duration=0.8,aformat=…,adelay=1000:all=1,volume=-12.82dB[a1]"; a ting cut to 0.5 s ->
    "[1:a]atrim=duration=0.5,afade=t=out:st=0.375:d=0.125,aformat=…"."""
    duration = seconds_text(placed.seconds)
    return f"[{k}:a]atrim=duration={duration},{fade_filters(placed)}{placing_filters(placed, voice)}[a{k}]"


def sound_filter(placed: Placed, k: int, voice: WavFormat) -> str:
    """Decides which filters a placed sound gets by its kind: a loop (rain) -> loop_filter, repeated to its seconds;
    a hit (whoosh) -> hit_filter, played once."""
    if placed.kind == "loop":
        return loop_filter(placed, k, voice)
    return hit_filter(placed, k, voice)


def mix_graph(placed: list[Placed], voice: WavFormat) -> str:
    """The whole filter graph: each sound's filters (inputs 1, 2, …), then all of them summed with the narration
    (input 0) at 0 dB, the mix as long as the narration, and a limiter at -1 dB that neither raises the level nor
    shifts the sound in time. A whoosh and a rain loop -> "[1:a]…[a1];[2:a]…[a2];[0:a][a1][a2]amix=inputs=3:
    normalize=0:duration=first,alimiter=limit=0.891:level=0:latency=1[out]"."""
    parts = []
    labels = "[0:a]"
    for k, one in enumerate(placed, start=1):
        parts.append(sound_filter(one, k, voice))
        labels += f"[a{k}]"
    inputs = len(placed) + 1
    parts.append(f"{labels}amix=inputs={inputs}:normalize=0:duration=first,"
                 f"alimiter=limit={LIMIT}:level=0:latency=1[out]")
    return ";".join(parts)


def mix_command(narration_wav: Path, placed: list[Placed], voice: WavFormat, out: Path) -> list[str]:
    """The one ffmpeg command for the mix: the narration and each sound as inputs, the graph (mix_graph), and out
    written as a WAV in the narration's own format. Bit-exact, so the same inputs give the same bytes."""
    command = [encode.ffmpeg(), "-y", "-loglevel", "error", "-i", str(narration_wav)]
    for one in placed:
        command += ["-i", str(one.path)]
    command += [
        "-filter_complex", mix_graph(placed, voice), "-map", "[out]",
        "-ar", str(voice.rate), "-ac", str(voice.channels), "-c:a", CODECS[voice.width],
        "-fflags", "+bitexact", "-flags:a", "+bitexact",
        str(out),
    ]
    return command


def files_present(placed: list[Placed]) -> list[Placed]:
    """The placed sounds whose files are still there, in order; one gone since resolve is left out with a log line:
    [whoosh, rain] with rain.wav deleted since -> [whoosh]."""
    present = []
    for one in placed:
        if one.path.is_file():
            present.append(one)
        else:
            log.info("video sound %r left out of the mix: %s is missing", one.name, one.path)
    return present


async def mix(narration_wav: Path, placed: list[Placed], out: Path) -> None:
    """Write out: the narration with the placed sounds under it, in the narration's format and to its exact length
    (one ffmpeg command, mix_command). With every file gone, out is a copy of the narration. ffmpeg failing is an
    EncodeError with the end of what it said."""
    present = files_present(placed)
    if not present:
        shutil.copyfile(narration_wav, out)
        return
    voice = wav_format(narration_wav)
    command = mix_command(narration_wav, present, voice, out)
    code, stderr = await encode.run(command)
    if code != 0:
        raise encode.EncodeError(encode.tail(stderr) or f"ffmpeg exited with {code}")
