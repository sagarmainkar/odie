"""Sound effects for explainer videos: the small set of sounds the writer may place under the narration, each a WAV
in the kit's sounds folder (odie/video/kit/sounds/, mono 44.1 kHz 16-bit), named for the writer. A hit plays once,
its own length (a whoosh on a cut, a ting when a number lands); a loop is ambience that repeats seamlessly for as
long as a cue asks (rain under a monsoon shot, footsteps under an army). The files are made by
scripts/sounds/build_sounds.py; the folder's README says how to replace one with a recording.

The writer places sounds in its page with Video.sounds([{scene: 2, at: 0, name: "footsteps", seconds: 6}, ...]); the
submit check reads them back (odie.video.page.check_with_cues) and cue_problem judges them against the narration."""
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from odie.video import beats, page

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
    """Decides whether cue `number` has the shape Video.sounds takes, as the kit checks it in the page (the list comes
    back from the page, so it is checked again here): the first thing wrong, or None.
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


def name_problem(number: int, cue: dict) -> str | None:
    """Decides whether cue `number` names a sound in the set: "whoosh" -> None; "wooosh" -> "Video.sounds: cue 2:
    there is no sound called 'wooosh'; the sounds are: whoosh, click, …" (every name, not the whole listing)."""
    name = cue["name"]
    if is_known(name):
        return None
    names = ", ".join(SOUNDS)
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


def cue_problem(cues: list[dict], narration: list[str]) -> str | None:
    """Decides whether the page's sound cues (Video.soundCues(), as the check read them) fit the video: the first
    problem as words the writer can act on, or None. Cue by cue, in list order: its shape, then a name not in the
    set, a scene the video doesn't have, a beat its scene doesn't have, an at past its scene's estimated length; then
    more than MAX_CUES_PER_SCENE in one scene, then more than MAX_CUES in all. A loop asked to play longer than its
    scene is fine (it is cut at the scene's end). [] -> None; [{"scene": 3, "beat": 1, "name": "whoosh"}] where
    scene 3 is one phrase -> "Video.sounds: cue 1: scene 3 has 1 phrase (beats 0..0), so beat 1 isn't there. …"."""
    lengths = page.estimated_timings(narration)["lengths"]
    for number, cue in enumerate(cues, start=1):
        problem = shape_problem(number, cue)
        if problem:
            return problem
        problem = name_problem(number, cue)
        if problem:
            return problem
        problem = scene_problem(number, cue, len(narration))
        if problem:
            return problem
        problem = beat_problem(number, cue, narration)
        if problem:
            return problem
        problem = at_problem(number, cue, lengths)
        if problem:
            return problem
    problem = crowded_scene_problem(cues)
    if problem:
        return problem
    return too_many_problem(cues)
