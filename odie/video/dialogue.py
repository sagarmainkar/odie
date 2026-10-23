"""A dialogue video (23 Oct 2026, an experiment): the user's own script of scenes and speakers' lines, read from their
note or file, staged by the video writer word for word. Each line is spoken in its speaker's voice, on its own; its
loudness every 20 ms is what a character's mouth follows (s.mouth), and every line's place on the timeline goes to
the page (Video.lines) and to a timeline.json next to the video.

Without a script nothing here runs: make_video takes the explainer's path exactly as before.

The script, as the user writes it:

    ## Scene: A workshop at night
    NARRATOR: The lamp had been burning for hours.
    ANNA: You're still here? [pause 1.2]
    BEN: Someone has to finish it.

"## Act: <label>" marks the act the scenes after it are in (for the cast's ages); "## Scene: <where>" starts a
scene; "SPEAKER: text" is a line (the speaker's case doesn't matter); "[pause N]" at a
line's end is the quiet after it in seconds. Anything else (front matter, a title, notes) is ignored."""
from __future__ import annotations

import array
import io
import json
import math
import re
import wave
from dataclasses import dataclass, field

from odie.video import beats, limits, timeline

NARRATOR = "narrator"  # the one speaker who may go without a voice of their own: the video voice speaks for them
DEFAULT_PAUSE = 0.35  # seconds of quiet after a line that names none (none after a scene's last: the breath comes)
MAX_PAUSE = 10.0  # the longest pause a line may ask for, in seconds
LOUDNESS_STEP = 0.02  # seconds per loudness value: what the mouths follow
RELEASE = 0.7  # how much of the last step's loudness a mouth keeps as it closes: shut after about 0.1 s of quiet
SCENE = re.compile(r"^#{2,}\s*Scene\s*:\s*(.*)$", re.IGNORECASE)
ACT = re.compile(r"^#{1,}\s*Act\b\s*:?\s*(.*)$", re.IGNORECASE)  # "## Act: One", "## Act 2": the scenes after
MARKER = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+|>\s*)")  # a bullet, a number or a quote before the name
LINE = re.compile(r"^([^\W\d_][\w .'-]{0,40}?)\s*(?:\([^)]*\))?\s*:\s*(.+)$")  # NAME (direction): text
PAUSE = re.compile(r"\s*\[pause(?:\s+(\d+(?:\.\d+)?)\s*s?)?\s*\]\s*$", re.IGNORECASE)
FRONT_MATTER = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)


class ScriptProblem(ValueError):
    """The script or the voices can't be staged, in words for the user."""


@dataclass
class Line:
    speaker: str  # lower case, as the voices are keyed
    text: str
    pause: float | None = None  # the quiet after it the script asked for; None: pause_after decides

    def pause_after(self, is_last_in_scene: bool) -> float:
        """The quiet after this line: the script's own when it gave one (after a scene's last line too, a beat before
        the cut); else DEFAULT_PAUSE between lines and none after a scene's last (the usual breath comes)."""
        if self.pause is not None:
            return self.pause
        if is_last_in_scene:
            return 0.0
        return DEFAULT_PAUSE


@dataclass
class Scene:
    where: str  # the heading's words: where the scene is, for the writer
    lines: list[Line] = field(default_factory=list)
    act: str = ""  # the act it is in ("## Act: Chapter one" before it), for the cast's ages; "" when none was given


@dataclass
class Script:
    scenes: list[Scene]

    def speakers(self) -> list[str]:
        """Everyone who speaks, sorted: ["anna", "ben", "narrator"]."""
        return sorted({line.speaker for scene in self.scenes for line in scene.lines})

    def as_data(self) -> list[dict]:
        """The script as the job keeps it: [{"where", "lines": [{"speaker", "text", "pause"}]}]."""
        return [{"where": scene.where, "act": scene.act, "lines": [line.__dict__.copy() for line in scene.lines]}
                for scene in self.scenes]


def from_data(data: list[dict]) -> Script:
    """A script the job kept (Script.as_data) read back."""
    return Script([Scene(s["where"], [Line(**line) for line in s["lines"]], s.get("act", "")) for s in data])


def line_of(text: str) -> Line | None:
    """One script line, or None for anything else. Written as people and LLMs write scripts: "ANNA: You're still
    here? [pause 1.2]" -> anna, "You're still here?", pause 1.2; "- **Anna:** Hi." or "1. Anna (whispering): Hi." ->
    anna, "Hi." (the bullet, the bold and the direction go); "[pause]" -> the default pause; "Some notes." (no
    speaker) -> None. A note written as "Note: check this" reads as a speaker called note, who then has no voice:
    make_video names them. Raises ScriptProblem for a pause over MAX_PAUSE or a "|" in the words (it marks lines for
    the writer), quoting the line."""
    plain = MARKER.sub("", text.strip()).replace("**", "").replace("__", "")
    match = LINE.match(plain)
    if match is None:
        return None
    speaker, said = match.groups()
    pause = None
    paused = PAUSE.search(said)
    if paused:
        if paused.group(1):
            pause = float(paused.group(1))
        said = said[:paused.start()]
    said = said.strip()
    if not said:
        return None
    if pause is not None and pause > MAX_PAUSE:
        raise ScriptProblem(f'"{text.strip()}": a pause can be at most {MAX_PAUSE:.0f} seconds.')
    if "|" in said:
        raise ScriptProblem(f'"{text.strip()}": a line can\'t contain "|"; write it another way.')
    return Line(speaker=speaker.strip().lower(), text=said, pause=pause)


def parse(text: str) -> Script:
    """The scenes and lines of a script (see the module's words for the format); lines before the first scene
    heading are a first scene with no heading. Raises ScriptProblem for a script with no lines, or a scene heading
    with none under it (naming the scene)."""
    body = FRONT_MATTER.sub("", text.replace("\r\n", "\n"), count=1)
    scenes: list[Scene] = []
    current: Scene | None = None
    act = ""
    for raw in body.split("\n"):
        act_heading = ACT.match(raw.strip())
        if act_heading:
            act = act_heading.group(1).strip()
            continue
        heading = SCENE.match(raw.strip())
        if heading:
            current = Scene(where=heading.group(1).strip(), act=act)
            scenes.append(current)
            continue
        if raw.lstrip().startswith("#"):
            continue  # a title or any other heading
        line = line_of(raw)
        if line is None:
            continue
        if current is None:
            current = Scene(where="", act=act)
            scenes.append(current)
        current.lines.append(line)
    if not any(scene.lines for scene in scenes):
        raise ScriptProblem("The script has no lines: write each as SPEAKER: what they say, under ## Scene: "
                            "headings.")
    for scene in scenes:
        if not scene.lines:
            raise ScriptProblem(f'The scene "{scene.where}" has no lines: add them as SPEAKER: what they say, or '
                                "remove its heading.")
    return Script(scenes)


def script_problem(script: Script) -> str | None:
    """Decides whether the script fits in one video, before anything is queued: the first problem in the user's
    terms, or None. A scene of 13 lines -> "Scene 1 (The roof) has 13 lines; …at most 12…"; 41 scenes; a scene over
    4,000 characters; over 6 minutes of speech and pauses -> how much and the limit. SCRIPT -> None."""
    if len(script.scenes) > limits.MAX_SCENES:
        return (f"The script has {len(script.scenes)} scenes; a video can have at most {limits.MAX_SCENES}. Make "
                "it two videos.")
    for number, scene in enumerate(script.scenes, start=1):
        name = f"Scene {number}"
        if scene.where:
            name = f"Scene {number} ({scene.where})"
        if len(scene.lines) > beats.MAX_BEATS:
            return (f"{name} has {len(scene.lines)} lines; a scene can have at most {beats.MAX_BEATS}. Split it with "
                    "another ## Scene: heading.")
        characters = sum(len(line.text) for line in scene.lines)
        if characters > limits.SCENE_CHARACTERS:
            return (f"{name} has {characters:,} characters of lines; a scene can have at most "
                    f"{limits.SCENE_CHARACTERS:,}. Split it with another ## Scene: heading.")
    words = sum(len(line.text.split()) for scene in script.scenes for line in scene.lines)
    pauses = sum(line.pause or 0.0 for scene in script.scenes for line in scene.lines)
    minutes = words / timeline.WORDS_PER_MINUTE + pauses / 60
    if minutes > timeline.MAX_MINUTES:
        return (f"The script is about {minutes:.1f} minutes of speech and pauses; a video can be at most "
                f"{timeline.MAX_MINUTES} minutes. Make it two videos.")
    return None


def voices_by_speaker(voices: list[dict] | None) -> dict[str, str]:
    """make_video's voices as a lookup by speaker: [{"id": "Anna", "name": "af_heart"}] -> {"anna": "af_heart"}.
    An entry without both an id and a name raises ScriptProblem."""
    out = {}
    for entry in voices or []:
        if not isinstance(entry, dict) or not entry.get("id") or not entry.get("name"):
            raise ScriptProblem('Each voice needs an id and a name: {"id": "anna", "name": "af_heart"}.')
        out[str(entry["id"]).strip().lower()] = str(entry["name"]).strip()
    return out


def missing_voices(script: Script, voices: dict[str, str]) -> list[str]:
    """The speakers with no voice, sorted; the narrator never needs one (the video voice speaks for them). Anna and
    Ben speak, only Anna has a voice -> ["ben"]."""
    given = {speaker.lower() for speaker in voices}
    return [s for s in script.speakers() if s != NARRATOR and s not in given]


def narration_of(script: Script) -> list[str]:
    """One narration string per scene, its lines as phrases ("A | B"), so the page check times them as beats and the
    writer's s.beatAt(t) is the line being spoken."""
    return [" | ".join(line.text for line in scene.lines) for scene in script.scenes]


def writer_listing(script: Script, characters: list | None = None, look: str = "") -> str:
    """The script as the writer reads it: each scene with where it is (and, with a cast, its act and the ages of
    who speaks in it) and its lines, numbered across the video, with who speaks. With a cast (odie.video.cast
    characters), the sheets of those who speak in this script come first, each description word for word; with a
    look, it comes before the script. No cast and no look -> the script alone, as phase 1 gave it."""
    out = []
    speakers = set(script.speakers())
    characters = [character for character in characters or [] if character.id in speakers]  # this script's cast
    if characters:
        out.append("Cast (draw each exactly as described here, in every scene and every video; never change or add "
                   "to how they look):")
        for character in characters:
            description = character.canonical
            if not description:
                description = "(no description given: choose one look and keep it)"
            entry = f"  {character.id} ({character.display_name}): {description}"
            if character.notes:
                entry += f"\n    Notes: {character.notes}"
            out.append(entry)
        out.append("")
    if look.strip():
        out.append("Look (for every video of this work; follow it):")
        out.append(look.strip())
        out.append("")
    out.append("Script (stage it; never change, add or drop a word):")
    index = 0
    for number, scene in enumerate(script.scenes, start=1):
        where = scene.where or "(no heading)"
        out.append(f"Scene {number}{scene_note(scene, characters)}: {where}")
        for line in scene.lines:
            out.append(f"  line {index} · {line.speaker}: {line.text}")
            index += 1
    return "\n".join(out)


def scene_note(scene: Scene, characters: list | None) -> str:
    """What the writer is told about a scene beside its number: its act and the ages of those who speak in it, when
    the cast gives them. Act "Chapter one", Mira 34 there -> " (Chapter one; mira is 34)"; no act, or no cast (a
    phase-1 listing stays as it was) -> ""; an act but no ages -> " (Chapter one)"."""
    if not scene.act or not characters:
        return ""
    ages = []
    speakers = {line.speaker for line in scene.lines}
    for character in characters or []:
        age = character.age_in(scene.act)
        if character.id in speakers and age is not None:
            ages.append(f"{character.id} is {age}")
    if not ages:
        return f" ({scene.act})"
    return f" ({scene.act}; {', '.join(ages)})"


def loudness(wav: bytes, step: float = LOUDNESS_STEP) -> list[float]:
    """A spoken line's loudness every `step` seconds, 0..1 with two decimals, as a mouth should follow it: the RMS of
    each step, scaled to the line's usual peaks (its 95th percentile is 1.0, louder is held at 1.0, so one click can't
    leave the voice near 0), then opening at once and closing gently (each step keeps at least RELEASE of the one
    before), so a mouth doesn't snap shut between syllables. A tone for 0.1 s then quiet -> 1.0 five times, then 0.7,
    0.49, 0.34 … (under 0.15, closed, after about 0.1 s). All quiet -> all 0.0."""
    with wave.open(io.BytesIO(wav)) as w:
        rate = w.getframerate()
        channels = w.getnchannels()
        width = w.getsampwidth()
        frames = w.readframes(w.getnframes())
    if width != 2:
        return []  # not 16-bit: no loudness known, so a mouth is half open while the line plays
    samples = array.array("h", frames)
    if channels > 1:
        samples = array.array("h", samples[::channels])
    per_step = max(1, int(rate * step))
    levels = []
    for start in range(0, len(samples), per_step):
        chunk = samples[start:start + per_step]
        levels.append(math.sqrt(sum(v * v for v in chunk) / len(chunk)))
    scale = usual_peak(levels)
    if scale == 0:
        return [0.0 for _ in levels]
    out = []
    held = 0.0
    for level in levels:
        held = max(min(1.0, level / scale), held * RELEASE)
        out.append(round(held, 2))
    return out


def usual_peak(levels: list[float]) -> float:
    """The level a line's loud moments usually reach: its 95th percentile. [0, 0, …, 1, 1, 1, 9] -> about 1 (the 9
    is one click); all 0 -> 0."""
    if not levels:
        return 0.0
    ranked = sorted(levels)
    return ranked[min(len(ranked) - 1, int(len(ranked) * 0.95))]


def lines_script(lines: list[dict]) -> str:
    """The page's line timeline: `<script>Video.lines([...])</script>`, each {index, speaker, text, scene, t, dur,
    amplitude} with t in seconds into the video."""
    data = json.dumps(lines).replace("</", "<\\/")  # a line saying "</script>" can't end the script early
    return f"<script>Video.lines({data})</script>"


def estimated_lines(script: Script, timings: dict) -> list[dict]:
    """The line timeline guessed from the page check's estimated timings (each line starts at its scene's beat), with
    no loudness: what the check draws the page with before anything is spoken."""
    out = []
    index = 0
    for number, scene in enumerate(script.scenes):
        start = timings["starts"][number]
        length = timings["lengths"][number]
        beats = timings.get("beats", [[0.0]] * len(script.scenes))[number]
        for i, line in enumerate(scene.lines):
            begin = beats[i] if i < len(beats) else 0.0
            end = beats[i + 1] if i + 1 < len(beats) else length
            out.append({"index": index, "speaker": line.speaker, "text": line.text, "scene": number + 1,
                        "t": round(start + begin, 3), "dur": round(max(0.0, end - begin), 3), "amplitude": []})
            index += 1
    return out


@dataclass
class Staging:
    """What the video writer needs to stage a script: the script as it reads it (writer_listing), the narration the
    page is checked against (narration_of: one string a scene, a phrase a line), and the line timeline for the
    check's estimated timings (estimated_lines, as the page script)."""
    listing: str
    narration: list[str]
    script: Script

    def lines_for(self, timings: dict) -> str:
        return lines_script(estimated_lines(self.script, timings))


def staging(script: Script, characters: list | None = None, look: str = "") -> Staging:
    """The writer's staging of `script` (see Staging), with the cast's sheets and the work's look when there are."""
    return Staging(listing=writer_listing(script, characters, look), narration=narration_of(script), script=script)
