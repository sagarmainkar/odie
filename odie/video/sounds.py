"""Sound effects for explainer videos: the small set of sounds the writer may place under the narration, each a WAV
in the kit's sounds folder (odie/video/kit/sounds/, mono 44.1 kHz 16-bit), named for the writer. A hit plays once,
its own length (a whoosh on a cut, a ting when a number lands); a loop is ambience that repeats seamlessly for as
long as a cue asks (rain under a monsoon shot, footsteps under an army). The files are made by
scripts/sounds/build_sounds.py; the folder's README says how to replace one with a recording."""
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

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
