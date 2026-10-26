"""The story writer, the audio story's creative director: one focused model turn, in the background, that writes a
story's script and chooses its sound.

It runs on the shared writer harness (odie.making.writer). It sees only story_writer.md, a message with the chat's
brief (the genre, the story, the cast, the accent, the length) and the sound listing from the user's library
(odie.making.sound_library), and one tool, submit_story, which takes the whole script as JSON. check_script decides
whether Odie's code can render it: a problem goes back to the writer to fix, up to three times. The length is the
one exception: a script outside ±10% of the asked minutes is refused once, then accepted with a note for the job
(LengthOnce), because a story a little long or short is still a story.

The script, as the writer sends it:
{"title": "...", "scenes": [{"title": "Prelude", "bed": {"sound": id, "level": word}, "music": {...},
  "lines": [{"sound": id, "level": word, "lead": seconds} | {"speaker": id, "text": "...", "pause_after": seconds,
  "sound_after": id}], "transition": {"kind": "crossfade" | "stinger" | "silence", "seconds": s, "sound": id}}]}
The cast comes from the chat, so the script names speakers by their cast id and never chooses voices."""
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from odie.agent.tools.media import plain_speech
from odie.making import writer as harness
from odie.making.chat import text_or_empty

INSTRUCTION = Path(__file__).with_name("story_writer.md").read_text(encoding="utf-8")

# How a script's lines become time. The making step (odie.making.story) lays the story out with the same numbers, so
# the length checked here is the length made.
WORDS_PER_MINUTE = 145  # a storyteller's pace: 140–150 words a minute
LENGTH_SPREAD = 0.10  # a story within 10% of its minutes is the right length
LINE_GAP = 0.4  # seconds after a line that gives no pause_after
MAX_PAUSE = 4.0  # the longest pause_after, in seconds
MAX_LEAD = 8.0  # the longest a sound cue may play before the next line
PRELUDE_LEAD = (2.0, 6.0)  # the story's opening sound plays this long before the narrator speaks
CROSSFADE_SECONDS = (2.0, 3.0)
SILENCE_SECONDS = (0.5, 3.0)
STINGER_SECONDS = 2.0  # the time a stinger transition takes, counted for the length
DEFAULT_TRANSITION_SECONDS = 2.5  # a crossfade, when a scene gives no transition
LEVELS = ("low", "normal", "up front")  # the only levels the writer chooses; the dB numbers are in odie.making.story
TRANSITIONS = ("crossfade", "stinger", "silence")
NARRATOR_ID = "narrator"  # the outside storyteller's id in the cast; a narrator in the story has their own id

LINES = harness.Lines(
    nudge=("You haven't called submit_story yet. Stop planning: write the whole script now and call submit_story "
           "with it as one JSON object."),
    nudge_after_problem=("submit_story hasn't accepted the script yet. Its last answer was: {problem} Fix exactly "
                         "that and call submit_story again with the whole fixed script."),
    never_submitted="I couldn't write the story's script (the writer stopped without one).",
    not_passed="I couldn't write a story script that passed its check: {problem}",
)
SUBMIT_DOC = ("Submit the whole audio story at once: script is one JSON object with its title and scenes, as the "
              "instructions show. It checks that every speaker is in the cast, every sound is in the list, the levels, "
              "beds, pauses and transitions, and the length.\n"
              '{"error": …}: fix exactly that and call submit_story again with the whole fixed script.\n'
              '{"result": "Accepted."}: the story is done.')
SUBMIT_FIELDS = {"script": str}
FIX_ALL = "Fix these and call submit_story again with the whole script."


@dataclass(frozen=True)
class Sound:
    """A scene's bed or music: the sound's id in the library and its level word."""
    sound: str
    level: str


@dataclass(frozen=True)
class Cue:
    """A sound played once in the flow of lines; the next line starts `lead` seconds after it starts."""
    sound: str
    level: str
    lead: float


@dataclass(frozen=True)
class Speech:
    """A spoken line: who says it (a cast id), the plain speech, the pause after it, and a sound right after it."""
    speaker: str
    text: str
    pause_after: float
    sound_after: str | None = None


@dataclass(frozen=True)
class Transition:
    """How a scene hands over to the next: a crossfade, a stinger (a sound), or a short silence."""
    kind: str
    seconds: float
    sound: str | None = None


@dataclass
class Scene:
    title: str
    bed: Sound | None
    music: Sound | None
    lines: list = field(default_factory=list)  # Cue and Speech, in order
    transition: Transition | None = None  # None for the last scene


@dataclass
class Story:
    """A checked script, ready to render."""
    title: str
    scenes: list[Scene]


@dataclass
class Written:
    """The accepted story: its title, its scenes, and a note for the job when its length was let through."""
    title: str
    scenes: list[Scene]
    note: str = ""


@dataclass
class Request:
    """What the chat asked for (make_audio_story): the genre, the story's idea, the cast [{id, name, voice, about}],
    who narrates (NARRATOR_ID for an outside storyteller, else a character's id), the accent, the minutes, and the
    brief."""
    genre: str
    premise: str
    cast: list[dict]
    narrator: str
    accent: str
    minutes: int
    brief: str = ""


# Small readers.

def level_word(given) -> str:
    """A level as one of LEVELS, forgiving the spelling: None -> "normal"; "Up-front" or "upfront" -> "up front";
    "loud" -> "loud" (left for the check to refuse)."""
    if given is None:
        return "normal"
    word = " ".join(str(given).lower().replace("-", " ").split())
    if word == "upfront":
        return "up front"
    return word


def number_text(value: float) -> str:
    """A number as the writer wrote it: 12.0 -> "12"; 2.5 -> "2.5"."""
    if float(value) == int(value):
        return str(int(value))
    return str(value)


def clock(seconds: float) -> str:
    """Seconds as minutes and seconds: 67.5 -> "1:08"; 132 -> "2:12"."""
    whole = round(seconds)
    return f"{whole // 60}:{whole % 60:02d}"


def minutes_word(minutes: int) -> str:
    """1 -> "minute"; 2 -> "minutes"."""
    if minutes == 1:
        return "minute"
    return "minutes"


def seconds_of(given, default: float) -> float | None:
    """A number of seconds as the writer sent it: None -> the default; 3 or "3" -> 3.0; "soon" -> None (refused)."""
    if given is None:
        return default
    try:
        return float(given)
    except (TypeError, ValueError):
        return None


def where(number: int, scene: dict) -> str:
    """How a problem names its scene: 1, {"title": "Prelude"} -> 'Scene 1 ("Prelude")'."""
    title = text_or_empty(scene.get("title")).strip()
    if not title:
        return f"Scene {number}"
    return f'Scene {number} ("{title}")'


def no_sound(sound_id) -> str:
    """The problem for a sound id that isn't in the library, in words the writer can act on: "animals/owl" -> 'there
    is no sound "animals/owl" in the library. Use an id from the sound list.'."""
    return f'there is no sound "{sound_id}" in the library. Use an id from the sound list.'


KIND_WORDS = {"hit": "a hit, played once", "loop": "a loop", "music": "music"}
ONCE = "a hit (or a loop, which plays once for up to 8 seconds)"  # what a cue, a sound_after or a stinger may be


def once_problem(sound_id: str, kinds: dict[str, str], what: str) -> str | None:
    """Decides whether a sound can play once in the flow (a cue, a sound_after, a stinger): a known hit or loop ->
    None (a loop plays its first 8 seconds, like seagulls crying as the prelude opens); unknown -> no_sound; music ->
    '"jingles/borealis" is music; a stinger is a hit (or a loop, …).'. `what` names it: "a sound in the lines"."""
    if sound_id not in kinds:
        return no_sound(sound_id)
    if kinds[sound_id] == "music":
        return f'"{sound_id}" is music; {what} is {ONCE}.'
    return None


def sound_given(given) -> dict | None:
    """A bed or music as the writer wrote it, as {"sound", "level"}: the object as it is; plain text as its id
    ("ambience/forest" -> {"sound": "ambience/forest"}); anything else (a number, a list) -> None, for the check to
    refuse."""
    if isinstance(given, dict):
        return given
    if isinstance(given, str):
        return {"sound": given}
    return None


def transition_given(given) -> dict | None:
    """A transition as the writer wrote it: the object as it is; plain text as its kind ("crossfade" -> {"kind":
    "crossfade"}); anything else -> None, for the check to refuse."""
    if isinstance(given, dict):
        return given
    if isinstance(given, str):
        return {"kind": given}
    return None


# The checks.

def sound_problem(given, kinds: dict[str, str], part: str) -> str | None:
    """Decides whether a scene's bed or music can be played. `part` is "bed" or "music"; `kinds` the library's id ->
    kind. A known id of the right kind (a bed is a loop, the music is music) and a known level -> None. Otherwise the
    problem: an unknown id -> 'there is no sound "…" in the library. …'; a hit as the bed -> '"foley/door-creak" is a
    hit, played once; a bed is a loop from the list.'; "loud" -> 'the level "loud" isn't one of low, normal, up
    front.'; 42 -> 'write it as {"sound": id, "level": word}, not 42.'."""
    sound = sound_given(given)
    if sound is None:
        return f'write it as {{"sound": id, "level": word}}, not {given}.'
    sound_id = sound.get("sound")
    if sound_id not in kinds:
        return no_sound(sound_id)
    kind = kinds[sound_id]
    if part == "bed" and kind != "loop":
        return f'"{sound_id}" is {KIND_WORDS[kind]}; a bed is a loop from the list.'
    if part == "music" and kind != "music":
        return f'"{sound_id}" is {KIND_WORDS[kind]}; music is a sound marked music in the list.'
    return level_problem(sound)


def level_problem(sound: dict) -> str | None:
    """Decides whether a sound's level is one of LEVELS (forgiving the spelling): "Up-front" -> None; "loud" -> 'the
    level "loud" isn't one of low, normal, up front.'."""
    level = level_word(sound.get("level"))
    if level not in LEVELS:
        return f'the level "{sound.get("level")}" isn\'t one of {", ".join(LEVELS)}.'
    return None


def line_problem(line: dict, kinds: dict[str, str], speakers: list[str], opening: bool) -> str | None:
    """Decides whether one line can be rendered. A sound cue: a known hit or loop (once_problem), a known level, and a
    lead from 0 to 8 seconds (from 2 to 6 for the story's opening sound). A spoken line: a speaker in the cast,
    something to say, a pause_after from 0 to 4, and a sound_after that can play once. {"speaker": "keeper", "text": "Another storm."} -> None; {"speaker":
    "captain", …} -> '"captain" isn't in the cast. …'; {"sound": "animals/seagulls", "lead": 12} as the opening -> "the
    lead is 12 seconds; it can be from 2 to 6 for the prelude's opening sound."."""
    if "speaker" in line:
        if line["speaker"] not in speakers:
            return f'"{line["speaker"]}" isn\'t in the cast. The speakers are: {", ".join(speakers)}.'
        if not plain_speech(text_or_empty(line.get("text"))):
            return "the line has nothing to say."
        pause = seconds_of(line.get("pause_after"), LINE_GAP)
        if pause is None or not 0 <= pause <= MAX_PAUSE:
            given = number_text_or_raw(line.get("pause_after"))
            return f"pause_after is {given} seconds; it can be from 0 to {number_text(MAX_PAUSE)}."
        sound_after = line.get("sound_after")
        if sound_after is not None:
            return once_problem(sound_after, kinds, "a sound in the lines")
        return None
    if "sound" in line:
        problem = once_problem(line["sound"], kinds, "a sound in the lines") or level_problem(line)
        if problem:
            return problem
        lowest, highest = 0.0, MAX_LEAD
        for_what = ""
        if opening:
            lowest, highest = PRELUDE_LEAD
            for_what = " for the prelude's opening sound"
        lead = seconds_of(line.get("lead"), 0.0)
        if lead is None or not lowest <= lead <= highest:
            return (f"the lead is {number_text_or_raw(line.get('lead'))} seconds; it can be from "
                    f"{number_text(lowest)} to {number_text(highest)}{for_what}.")
        return None
    return 'a line is either a sound ({"sound": …}) or a speaker and their text ({"speaker": …, "text": …}).'


def number_text_or_raw(given) -> str:
    """A number for a problem's words: 12 -> "12"; "soon" -> "soon"."""
    value = seconds_of(given, 0.0)
    if value is None:
        return str(given)
    return number_text(value)


def transition_problem(given, kinds: dict[str, str]) -> str | None:
    """Decides whether a transition can be made: a crossfade of 2 to 3 seconds, a stinger with a sound that plays once
    (a hit, or a loop), or a silence of 0.5 to 3 seconds. {"kind": "crossfade", "seconds": 2.5} -> None; "crossfade"
    -> None (plain text is its kind); {"kind": "crossfade", "seconds": 6} -> "a crossfade is 2 to 3 seconds, not 6.";
    {"kind": "wipe"} -> '"wipe" isn't one of crossfade, stinger, silence.'; a stinger of music -> '"jingles/…" is
    music; a stinger is a hit …'."""
    transition = transition_given(given)
    if transition is None:
        return f'write it as {{"kind": "crossfade", "seconds": 2.5}}, not {given}.'
    kind = transition.get("kind")
    if kind not in TRANSITIONS:
        return f'"{kind}" isn\'t one of {", ".join(TRANSITIONS)}.'
    if kind == "stinger":
        return once_problem(transition.get("sound"), kinds, "a stinger")
    limits = CROSSFADE_SECONDS
    if kind == "silence":
        limits = SILENCE_SECONDS
    seconds = seconds_of(transition.get("seconds"), DEFAULT_TRANSITION_SECONDS)
    if seconds is None or not limits[0] <= seconds <= limits[1]:
        return (f"a {kind} is {number_text(limits[0])} to {number_text(limits[1])} seconds, not "
                f"{number_text_or_raw(transition.get('seconds'))}.")
    return None


def prelude_problem(scene: dict, narrator: str) -> str | None:
    """Decides whether the story opens as an audio story should: on sound (a cue with a lead of 2 to 6 seconds), then
    the narrator setting the place, time and mood. Seagulls for 3 s, then the narrator -> None; the narrator first ->
    "the story opens on sound. …"; seagulls, then the keeper -> 'the narrator speaks first, …; here "keeper" does.'.
    The lead itself is line_problem's to check."""
    lines = scene.get("lines") or []
    if not lines or "sound" not in lines[0]:
        return ("the story opens on sound. Make its first line a sound with a lead of 2 to 6 seconds, then the "
                "narrator sets the scene.")
    for line in lines:
        if "speaker" in line:
            if line["speaker"] == narrator:
                return None
            return f'the narrator speaks first, setting the place, time and mood; here "{line["speaker"]}" does.'
    return None


def bed_count_problem(scene: dict) -> str | None:
    """Decides whether a scene stacks beds: "bed" one sound or none -> None; "bed" a list of two, or "beds" given ->
    'one bed at a time. …'. Music is its own one bed."""
    bed = scene.get("bed")
    music = scene.get("music")
    if isinstance(bed, list) or isinstance(music, list) or "beds" in scene:
        return 'one bed at a time. Give "bed" one sound (and "music" one more at most).'
    return None


def scene_problems(number: int, scene: dict, kinds: dict[str, str], speakers: list[str], narrator: str,
                   last: bool) -> list[str]:
    """Every problem in one scene, each named with where it is: 'Scene 2 ("The storm"), line 3: …'."""
    place = where(number, scene)
    found = []
    stacked = bed_count_problem(scene)
    if stacked:
        return [f"{place}: {stacked}"]
    for part in ("bed", "music"):
        if scene.get(part) is not None:
            problem = sound_problem(scene[part], kinds, part)
            if problem:
                label = "the bed"
                if part == "music":
                    label = "the music"
                found.append(f"{place}, {label}: {problem}")
    if number == 1:
        problem = prelude_problem(scene, narrator)
        if problem:
            found.append(f"{place}: {problem}")
    for index, line in enumerate(scene.get("lines") or [], start=1):
        opening = number == 1 and index == 1
        problem = line_problem(line, kinds, speakers, opening)
        if problem:
            found.append(f"{place}, line {index}: {problem}")
    transition = scene.get("transition")
    if transition is not None and not last:
        problem = transition_problem(transition, kinds)
        if problem:
            found.append(f"{place}, the transition: {problem}")
    return found


def script_problems(script, catalogue: list[dict], cast: list[dict], narrator: str = NARRATOR_ID) -> list[str]:
    """Every reason the script can't be rendered, in words the writer can fix (empty when it can): the shape, then
    each scene's beds, prelude, lines and transition. An unknown sound in the prelude -> ['Scene 1 ("Prelude"), line
    1: there is no sound "animals/owl" in the library. …']."""
    if not isinstance(script, dict) or not isinstance(script.get("scenes"), list) or not script["scenes"]:
        return ['The script needs "scenes": a list of scenes, each with its "lines".']
    kinds = {entry["id"]: entry["kind"] for entry in catalogue}
    speakers = [member["id"] for member in cast]
    scenes = script["scenes"]
    found = []
    for number, scene in enumerate(scenes, start=1):
        if not isinstance(scene, dict):
            found.append(f"Scene {number}: a scene is an object with its title, bed and lines.")
            continue
        found.extend(scene_problems(number, scene, kinds, speakers, narrator, number == len(scenes)))
    return found


def script_problems_in(text: str, catalogue: list[dict], cast: list[dict], narrator: str = NARRATOR_ID) -> list[str]:
    """script_problems for the script as the writer sent it, JSON text (a ```json fence around it is fine): not JSON
    -> ["The script isn't JSON: … Send it as one JSON object."]."""
    try:
        script = json.loads(unfenced(text))
    except json.JSONDecodeError as e:
        return [f"The script isn't JSON: {e}. Send it as one JSON object."]
    return script_problems(script, catalogue, cast, narrator)


def unfenced(text: str) -> str:
    """The JSON inside a ``` fence, or the text as it is: '```json\\n{…}\\n```' -> '{…}'."""
    stripped = text_or_empty(text).strip()
    match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", stripped, flags=re.DOTALL)
    if match:
        return match.group(1)
    return stripped


# From a checked script to a Story.

def sound_of(given) -> Sound | None:
    """A checked bed or music as a Sound, its level word made plain: None -> None (the scene has none); {"sound":
    "ambience/ocean-surf", "level": "Up-front"} -> Sound("ambience/ocean-surf", "up front"); "ambience/forest" ->
    Sound("ambience/forest", "normal")."""
    sound = sound_given(given)
    if sound is None:
        return None
    return Sound(sound["sound"], level_word(sound.get("level")))


def line_of(given: dict):
    """One checked line as a Speech or a Cue, with the defaults filled in (a pause of LINE_GAP, a lead of 0)."""
    if "speaker" in given:
        return Speech(speaker=given["speaker"], text=plain_speech(given["text"]),
                      pause_after=seconds_of(given.get("pause_after"), LINE_GAP), sound_after=given.get("sound_after"))
    return Cue(sound=given["sound"], level=level_word(given.get("level")), lead=seconds_of(given.get("lead"), 0.0))


def transition_of(given: dict | None, last: bool) -> Transition | None:
    """A scene's transition: none on the last scene; a crossfade of 2.5 s when a scene gives none; a stinger takes
    STINGER_SECONDS."""
    if last:
        return None
    transition = transition_given(given)
    if transition is None:
        return Transition("crossfade", DEFAULT_TRANSITION_SECONDS, None)
    kind = transition["kind"]
    if kind == "stinger":
        return Transition("stinger", STINGER_SECONDS, transition["sound"])
    return Transition(kind, seconds_of(transition.get("seconds"), DEFAULT_TRANSITION_SECONDS), None)


def parse_script(script: dict) -> Story:
    """A script that check_script passed, as a Story for the making step."""
    scenes = []
    count = len(script["scenes"])
    for number, given in enumerate(script["scenes"], start=1):
        lines = [line_of(line) for line in given.get("lines") or []]
        scenes.append(Scene(title=text_or_empty(given.get("title")), bed=sound_of(given.get("bed")),
                            music=sound_of(given.get("music")), lines=lines,
                            transition=transition_of(given.get("transition"), number == count)))
    return Story(title=text_or_empty(script.get("title")).strip(), scenes=scenes)


# The length.

def line_seconds(line) -> float:
    """The time a line takes in the story: a spoken line, its words at 145 a minute plus its pause (29 words -> 12 s
    + 0.4); a cue, its lead."""
    if isinstance(line, Speech):
        return len(line.text.split()) * 60 / WORDS_PER_MINUTE + line.pause_after
    return line.lead


def estimated_seconds(story: Story) -> float:
    """How long the story plays: every line's time and every transition's."""
    total = 0.0
    for scene in story.scenes:
        total += sum(line_seconds(line) for line in scene.lines)
        if scene.transition is not None:
            total += scene.transition.seconds
    return total


def length_problem(story: Story, minutes: int) -> str | None:
    """Decides whether the story is about as long as asked, within 10%: 2 minutes -> 1:48 to 2:12 fine. 117 s -> None;
    67.5 s -> "The story is too short: about 1:08 for 2 minutes; anything from 1:48 to 2:12 is fine (…). Add a beat or
    a line of dialogue to a scene."; 179 s -> "… too long … Cut a beat or shorten the lines."."""
    target = minutes * 60
    lowest = target * (1 - LENGTH_SPREAD)
    highest = target * (1 + LENGTH_SPREAD)
    seconds = estimated_seconds(story)
    if lowest <= seconds <= highest:
        return None
    said = (f"about {clock(seconds)} for {minutes} {minutes_word(minutes)}; anything from {clock(lowest)} to "
            f"{clock(highest)} is fine (about {WORDS_PER_MINUTE} words a minute, plus the pauses, leads and "
            f"transitions).")
    if seconds < lowest:
        return f"The story is too short: {said} Add a beat or a line of dialogue to a scene."
    return f"The story is too long: {said} Cut a beat or shorten the lines."


def check_script(script, catalogue: list[dict], cast: list[dict], minutes: int,
                 narrator: str = NARRATOR_ID) -> list[str]:
    """Decides whether Odie can render the script, as the problems to fix (empty: it can): every speaker in the cast,
    every sound in the library, known levels, at most one bed and one music bed in a scene, pauses and leads within
    limits, the prelude opening on sound and then the narrator; and once all that holds, the length. The lighthouse
    script of 117 s for 2 minutes -> []; with "animals/owl", not in the library -> ['Scene 1 ("Prelude"), line 1:
    there is no sound "animals/owl" in the library. …']; with only one line after the prelude -> ["The story is too
    short: about 1:08 for 2 minutes; …"]."""
    found = script_problems(script, catalogue, cast, narrator)
    if found:
        return found
    problem = length_problem(parse_script(script), minutes)
    if problem:
        return [problem]
    return []


@dataclass
class LengthOnce:
    """The story writer's one exception to the harness's three refusals: the length is refused once, and after that
    let through with a note for the job."""
    refused: bool = False
    note: str = ""

    def problem_to_send(self, problem: str | None, story: Story, minutes: int) -> str | None:
        """Decides whether a length problem goes back to the writer: none -> None; the first -> the problem (the
        writer fixes it); any after that -> None, the script is accepted, and the note says how long it came out:
        "The story came out at about 1:08 for 2 minutes (asked once to fix its length).". """
        if problem is None:
            return None
        if not self.refused:
            self.refused = True
            return problem
        self.note = (f"The story came out at about {clock(estimated_seconds(story))} for {minutes} "
                     f"{minutes_word(minutes)} (asked once to fix its length).")
        return None


# The writer's turn.

def cast_lines(cast: list[dict]) -> str:
    """The cast as the writer reads it: "- keeper: The keeper (the old lighthouse keeper)"."""
    lines = []
    for member in cast:
        about = text_or_empty(member.get("about")).strip()
        line = f"- {member['id']}: {member.get('name', member['id'])}"
        if about:
            line += f" ({about})"
        lines.append(line)
    return "\n".join(lines)


def narrator_line(narrator: str) -> str:
    """Who tells the story: "narrator" -> an outside storyteller; "keeper" -> the keeper, in the first person."""
    if narrator == NARRATOR_ID:
        return "The narrator is an outside storyteller (speaker id narrator), a voice telling the tale."
    return (f"The narrator is {narrator}, in the story: they tell it in the first person, as themselves, in their own "
            f"voice.")


def prompt_for(request: Request, listing: str) -> str:
    """The writer's whole message: the genre, the story, the cast and narrator, the accent, the length in minutes and
    words (2 minutes -> about 290 spoken words), the chat's brief, and the sound list."""
    brief = request.brief.strip()
    if not brief:
        brief = "(none)"
    words = request.minutes * WORDS_PER_MINUTE
    return (f"Genre: {request.genre}\n"
            f"The story: {request.premise}\n"
            f"Accent: {request.accent} (the voices carry it; write the dialogue to suit)\n"
            f"Length: {request.minutes} {minutes_word(request.minutes)}, about {words} spoken words ("
            f"{WORDS_PER_MINUTE} a minute; the pauses, leads and transitions add to it).\n\n"
            f"Cast (speaker ids):\n{cast_lines(request.cast)}\n"
            f"{narrator_line(request.narrator)}\n\n"
            f"Brief from the chat:\n{brief}\n\n"
            f"Sounds (use these ids exactly):\n{listing}\n\n"
            f"Plan in a few lines, then call submit_story with the whole script.")


def tools_for(desk: harness.Desk, request: Request, catalogue: list[dict]) -> list:
    """The writer's one tool, submit_story (script), built by the shared harness on `desk`. Its check refuses what
    can't be rendered (up to the harness's three times) and the length once (LengthOnce); accepting makes the Written
    story, the title falling back to the desk's topic."""
    length = LengthOnce()

    async def check(fields: dict) -> str | None:
        text = text_or_empty(fields["script"])
        found = script_problems_in(text, catalogue, request.cast, request.narrator)
        if found:
            return " ".join(found) + " " + FIX_ALL
        story = parse_script(json.loads(unfenced(text)))
        return length.problem_to_send(length_problem(story, request.minutes), story, request.minutes)

    def accept(fields: dict) -> Written:
        story = parse_script(json.loads(unfenced(text_or_empty(fields["script"]))))
        title = harness.title_given(story.title, desk.topic)
        return Written(title=title, scenes=story.scenes, note=length.note)

    return [harness.submit_tool(desk, "submit_story", SUBMIT_DOC, SUBMIT_FIELDS, check, accept)]


async def write(request: Request, catalogue: list[dict], listing: str, turn) -> Written:
    """Writes the story in one focused turn: `turn(prompt, instruction, tools, timeout, follow_up=…)` is
    runner.focused_turn in Odie. Returns the accepted script; raises WriterFailed when there's none (see
    odie.making.writer.write)."""
    desk = harness.Desk(topic=request.premise[:80])
    [tool] = tools_for(desk, request, catalogue)
    return await harness.write(desk, prompt_for(request, listing), INSTRUCTION, tool, LINES, turn)
