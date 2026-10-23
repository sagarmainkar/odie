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

"## Scene: <where>" starts a scene; "SPEAKER: text" is a line (the speaker's case doesn't matter); "[pause N]" at a
line's end is the quiet after it in seconds. Anything else (front matter, a title, notes) is ignored."""
from __future__ import annotations

import array
import io
import json
import math
import re
import wave
from dataclasses import dataclass, field

NARRATOR = "narrator"  # the one speaker who may go without a voice of their own: the video voice speaks for them
DEFAULT_PAUSE = 0.35  # seconds of quiet after a line that names none
LOUDNESS_STEP = 0.02  # seconds per loudness value: what the mouths follow
SCENE = re.compile(r"^#{2,}\s*Scene\s*:\s*(.*)$", re.IGNORECASE)
LINE = re.compile(r"^([A-Za-z][\w .'-]{0,40}?)\s*:\s*(.+)$")
PAUSE = re.compile(r"\s*\[pause\s+(\d+(?:\.\d+)?)\s*\]\s*$", re.IGNORECASE)
FRONT_MATTER = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)


class ScriptProblem(ValueError):
    """The script or the voices can't be staged, in words for the user."""


@dataclass
class Line:
    speaker: str  # lower case, as the voices are keyed
    text: str
    pause: float = DEFAULT_PAUSE


@dataclass
class Scene:
    where: str  # the heading's words: where the scene is, for the writer
    lines: list[Line] = field(default_factory=list)


@dataclass
class Script:
    scenes: list[Scene]

    def speakers(self) -> list[str]:
        """Everyone who speaks, sorted: ["anna", "ben", "narrator"]."""
        return sorted({line.speaker for scene in self.scenes for line in scene.lines})

    def as_data(self) -> list[dict]:
        """The script as the job keeps it: [{"where", "lines": [{"speaker", "text", "pause"}]}]."""
        return [{"where": scene.where, "lines": [line.__dict__.copy() for line in scene.lines]}
                for scene in self.scenes]


def from_data(data: list[dict]) -> Script:
    """A script the job kept (Script.as_data) read back."""
    return Script([Scene(s["where"], [Line(**line) for line in s["lines"]]) for s in data])


def line_of(text: str) -> Line | None:
    """One script line, or None for anything else: "ANNA: You're still here? [pause 1.2]" -> anna, "You're still
    here?", pause 1.2; "BEN: Hi." -> ben, "Hi.", the default pause; "Some notes." (no speaker) -> None. A note
    written as "Note: check this" reads as a speaker called note, who then has no voice: make_video names them."""
    match = LINE.match(text.strip())
    if match is None:
        return None
    speaker, said = match.groups()
    pause = DEFAULT_PAUSE
    paused = PAUSE.search(said)
    if paused:
        pause = float(paused.group(1))
        said = said[:paused.start()]
    said = said.strip()
    if not said:
        return None
    return Line(speaker=speaker.strip().lower(), text=said, pause=pause)


def parse(text: str) -> Script:
    """The scenes and lines of a script (see the module's words for the format); lines before the first scene
    heading are a first scene with no heading. Raises ScriptProblem for a script with no lines, or a scene heading
    with none under it (naming the scene)."""
    body = FRONT_MATTER.sub("", text.replace("\r\n", "\n"), count=1)
    scenes: list[Scene] = []
    current: Scene | None = None
    for raw in body.split("\n"):
        heading = SCENE.match(raw.strip())
        if heading:
            current = Scene(where=heading.group(1).strip())
            scenes.append(current)
            continue
        if raw.lstrip().startswith("#"):
            continue  # a title or any other heading
        line = line_of(raw)
        if line is None:
            continue
        if current is None:
            current = Scene(where="")
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


def writer_listing(script: Script) -> str:
    """The script as the writer reads it: each scene with where it is and its lines, numbered across the video, with
    who speaks."""
    out = ["Script (stage it; never change, add or drop a word):"]
    index = 0
    for number, scene in enumerate(script.scenes, start=1):
        where = scene.where or "(no heading)"
        out.append(f"Scene {number}: {where}")
        for line in scene.lines:
            out.append(f"  line {index} · {line.speaker}: {line.text}")
            index += 1
    return "\n".join(out)


def loudness(wav: bytes, step: float = LOUDNESS_STEP) -> list[float]:
    """A spoken line's loudness every `step` seconds (RMS), scaled so its loudest moment is 1.0, two decimals: a tone
    for 0.2 s then 0.2 s of quiet -> 20 values, about 1.0 for the first ten and 0.0 after. All quiet -> all 0.0."""
    with wave.open(io.BytesIO(wav)) as w:
        rate = w.getframerate()
        channels = w.getnchannels()
        frames = w.readframes(w.getnframes())
    samples = array.array("h", frames)
    if channels > 1:
        samples = array.array("h", samples[::channels])
    per_step = max(1, int(rate * step))
    levels = []
    for start in range(0, len(samples), per_step):
        chunk = samples[start:start + per_step]
        levels.append(math.sqrt(sum(v * v for v in chunk) / len(chunk)))
    loudest = max(levels, default=0.0)
    if loudest == 0:
        return [0.0 for _ in levels]
    return [round(level / loudest, 2) for level in levels]


def lines_script(lines: list[dict]) -> str:
    """The page's line timeline: `<script>Video.lines([...])</script>`, each {index, speaker, scene, t, dur,
    amplitude} with t in seconds into the video."""
    return f"<script>Video.lines({json.dumps(lines)})</script>"


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
            out.append({"index": index, "speaker": line.speaker, "scene": number + 1, "t": round(start + begin, 3),
                        "dur": round(max(0.0, end - begin), 3), "amplitude": []})
            index += 1
    return out
