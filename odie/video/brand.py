"""Brand kits: a skill's own drawing code, sounds and fixed scenes for its videos, so a channel's look stays the same
whichever model writes the video. make_video(brand_kit="<skill>") names a user skill whose assets/brand/ folder holds
the kit:

- brand.json, the manifest:
  name: the kit's name, for the writer.
  api_doc: plain text, the functions under Brand the writer may call.
  sounds: the kit's own sounds by the name the writer gives Video.sounds, {"ting": "ting.wav"}; a kit sound with a
    built-in's name plays instead of it, in this video only.
  bookends: fixed scenes Odie adds at fixed lengths, outside the writer's control: "handoff" just before the timed
    segment, "ending" right after it, "card" at the very end. Each is {"seconds": 2.5}, with "says" (the var the scene
    speaks aloud, at natural speed) and "sounds" ([{"at": 0.4, "name": "ting"}]) when it has them.
  background: true when the kit draws the background under every scene.
  character: the name under Brand of a character the stage draws through the whole timed segment.
  moves: the moves the writer may cue on that character, with their seconds ({"bounce": 0.6}).
  vars: the words the writer gives the bookends, by name, with what each is ({"intro": "a short line ..."}).
- brand.js: plain JavaScript, no imports and nothing from the network, that sets window.Brand: background(ctx, t, w, h),
  bookend(name, ctx, t, w, h, vars), and the character's draw(ctx, t, w, h, info) and timer(secondsLeft) (see
  video.js's Video.brand for when the stage calls each).
- the sound files: short WAVs, 16-bit.

The kit is read only from the user's skills folder, checked, and copied into the job's folder (brand/) when the video
is asked for, so the video is made with the kit as it was then; job.data["brand_kit"] = {"name", "version", "path"},
the version a hash of the kit's files. A kit that is missing or broken is an error, never a video drawn without it."""
import hashlib
import io
import json
import logging
import re
import shutil
import wave
from dataclasses import dataclass, field
from pathlib import Path

from odie import config
from odie.browser.engine import BrowserError, BrowserTimeout
from odie.video import beats, narrate, page, sounds, timed, timeline

log = logging.getLogger("odie.video")

FOLDER = "brand"  # a kit's place in its skill (assets/brand) and in a job's folder (brand/)
MANIFEST = "brand.json"
SCRIPT = "brand.js"
BOOKENDS = ("handoff", "ending", "card")  # the scenes a kit may add, in the order they play
MAX_BOOKEND_SECONDS = 15.0
MAX_SCRIPT_BYTES = 300_000
MAX_SOUND_SECONDS = 10.0
MAX_VAR_CHARACTERS = 300
LONG_HOLD = 1.0  # a bookend held this many seconds past its animation, for a long line, is logged

SKILL_NAME = re.compile(r"^[a-z][a-z0-9]*(?:-[a-z0-9]+)*$")  # a skill's folder name, as the skill builder names them
NAME = re.compile(r"^[a-z][a-z0-9_-]*$")  # a sound's, move's or var's name
IDENTIFIER = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")  # the character's name under Brand
# Ways a script reaches the network or other code. The sealed tab refuses every request anyway; this says why first.
REACHES_OUT = re.compile(r"\b(fetch|XMLHttpRequest|WebSocket|EventSource|importScripts|sendBeacon)\b|\bimport\s*[(\s{*'\"]")
SCRIPT_CLOSE = re.compile(r"</(script)", re.IGNORECASE)


class KitProblem(Exception):
    """A brand kit that can't be used: missing, outside the skills folder, broken, or changed since the video was
    asked for. Its words are for the user."""


@dataclass(frozen=True)
class Bookend:
    """One of the kit's fixed scenes: its name, its seconds, the var it speaks ("" for a silent one) and its sounds."""
    name: str
    seconds: float
    says: str = ""
    sounds: tuple = ()  # ({"at": 0.4, "name": "ting"}, ...)


@dataclass(frozen=True)
class Kit:
    name: str
    folder: Path
    api_doc: str
    script: str
    sounds: dict[str, Path]
    bookends: dict[str, Bookend]
    background: bool
    character: str
    moves: dict[str, float]
    vars: dict[str, str]
    version: str


@dataclass(frozen=True)
class Branded:
    """A kit with the words the writer gave its bookends ({"intro": "..."}), as a page is put together with it."""
    kit: Kit
    vars: dict[str, str] = field(default_factory=dict)


# ---- Finding and reading a kit ----

def skills_folder() -> Path:
    """The user's skills folder (the skill builder's user_dir): <config>/skills."""
    return config.settings.config_dir / "skills"


def kit_folder(skill: str) -> Path:
    """Decides where a kit may be read from: only <skills folder>/<skill>/assets/brand, for a skill named as the skill
    builder names them. "my-channel" -> ~/.odie/skills/my-channel/assets/brand; "../x", "/etc", "a/b" or "My Skill"
    -> KitProblem; a folder that resolves outside the skills folder (a link out) -> KitProblem."""
    if not SKILL_NAME.match(skill) or len(skill) > 40:
        raise KitProblem(f"brand_kit is a skill's name, like my-channel (lowercase words joined by hyphens), not "
                         f"{skill!r}.")
    root = skills_folder().resolve()
    folder = (skills_folder() / skill / "assets" / FOLDER).resolve()
    if not folder.is_relative_to(root):
        raise KitProblem(f"The {skill} skill's brand kit points outside the skills folder, so it can't be used.")
    return folder


def find(skill: str) -> Kit:
    """The kit of the user skill `skill`, read and checked (read_kit); KitProblem when it isn't there or is broken."""
    folder = kit_folder(skill)
    if not (folder / MANIFEST).is_file():
        raise KitProblem(f"The {skill} skill has no brand kit: {folder / MANIFEST} isn't there.")
    return read_kit(folder)


def version_of(folder: Path, sound_files: list[str]) -> str:
    """A hash of the kit's files (brand.json, brand.js and its sound files), so a video records which kit made it:
    the same files -> the same 12 characters; one byte changed in any of them -> another."""
    digest = hashlib.sha256()
    for name in [MANIFEST, SCRIPT, *sorted(sound_files)]:
        digest.update(name.encode() + b"\0" + (folder / name).read_bytes() + b"\0")
    return digest.hexdigest()[:12]


def script_problem(script: str) -> str | None:
    """Decides whether brand.js may run in the video page: it must load nothing and reach nothing. A script that
    draws -> None; one that calls fetch(...), opens a WebSocket, imports, or names an http(s) address in a src, href
    or url() -> the reason."""
    match = REACHES_OUT.search(script)
    if match:
        return f"brand.js uses {match.group(0).strip()}, but a kit's code may not reach the network or load code."
    try:
        page.check_offline(script)
    except ValueError:
        return "brand.js names a web address to load, but a video page can't load anything."
    return None


def number(value) -> bool:
    """Decides whether a manifest value is a plain number: 2.5 -> True; "2.5", None or True -> False."""
    return sounds.is_number(value)


def wav_problem(path: Path) -> str | None:
    """Decides whether a kit sound can be mixed: a 16-bit WAV of at most MAX_SOUND_SECONDS -> None; a missing file,
    another format, 24-bit, or 30 s -> the reason."""
    if not path.is_file():
        return f"its file {path.name} isn't in the kit"
    try:
        with wave.open(str(path), "rb") as w:
            width = w.getsampwidth()
            seconds = w.getnframes() / w.getframerate()
    except (OSError, EOFError, wave.Error):
        return f"{path.name} isn't a WAV file"
    if width != 2:
        return f"{path.name} is {width * 8}-bit; kit sounds are 16-bit WAVs"
    if seconds > MAX_SOUND_SECONDS:
        return f"{path.name} lasts {seconds:.1f} s; a kit sound is at most {MAX_SOUND_SECONDS:g} s"
    return None


def read_sounds(manifest: dict, folder: Path) -> dict[str, Path]:
    """The kit's sounds by name, each file checked (wav_problem): {"ting": "ting.wav"} -> {"ting": <folder>/ting.wav}.
    A name that isn't a plain word, a file path with a folder in it, or a file that can't be mixed -> KitProblem."""
    given = manifest.get("sounds", {})
    if not isinstance(given, dict):
        raise KitProblem('brand.json: "sounds" is an object of name to file, like {"ting": "ting.wav"}.')
    found = {}
    for name, file_name in given.items():
        plain_name = NAME.match(name) is not None
        in_kit_folder = isinstance(file_name, str) and Path(file_name).name == file_name  # "ting.wav", not "../x.wav"
        if not plain_name or not in_kit_folder:
            raise KitProblem(f'brand.json: the sound {name!r} must be a plain name with a file in the kit\'s own '
                             f'folder, like "ting": "ting.wav".')
        problem = wav_problem(folder / file_name)
        if problem:
            raise KitProblem(f"brand.json: the sound {name!r}: {problem}.")
        found[name] = folder / file_name
    return found


def bookend_sound_problem(name: str, cue, kit_sounds: dict[str, Path]) -> str | None:
    """Decides whether a bookend's sound can play: {"at": 0.4, "name": "ting"} with ting a kit sound or a built-in hit
    -> None; a loop ("rain"), an unknown name or a negative at -> the reason."""
    if not isinstance(cue, dict) or not number(cue.get("at")) or cue["at"] < 0:
        return f'the {name} bookend\'s sounds are like [{{"at": 0.4, "name": "ting"}}], at 0 or more'
    sound_name = cue.get("name")
    if sound_name in kit_sounds:
        return None
    built_in = sounds.SOUNDS.get(sound_name)
    if built_in is None or built_in.kind != "hit":
        return f"the {name} bookend plays {sound_name!r}, which is neither a kit sound nor one of Odie's hits"
    return None


def read_bookends(manifest: dict, kit_vars: dict[str, str], kit_sounds: dict[str, Path]) -> dict[str, Bookend]:
    """The kit's bookends by name, checked: {"handoff": {"seconds": 2.5, "says": "intro"}} -> {"handoff":
    Bookend("handoff", 2.5, "intro")}. A name other than handoff, ending or card, seconds that aren't more than 0 and
    at most 15, a "says" naming no var, or a sound that can't play (bookend_sound_problem) -> KitProblem."""
    given = manifest.get("bookends", {})
    if not isinstance(given, dict):
        raise KitProblem('brand.json: "bookends" is an object like {"card": {"seconds": 3}}.')
    found = {}
    for name, entry in given.items():
        if name not in BOOKENDS:
            raise KitProblem(f"brand.json: there is no bookend {name!r}; they are {', '.join(BOOKENDS)}.")
        if not isinstance(entry, dict) or not number(entry.get("seconds")):
            raise KitProblem(f'brand.json: the {name} bookend needs its seconds, like {{"seconds": 2.5}}.')
        seconds = float(entry["seconds"])
        if not 0 < seconds <= MAX_BOOKEND_SECONDS:
            raise KitProblem(f"brand.json: the {name} bookend lasts {seconds:g} s; a bookend lasts more than 0 and at "
                             f"most {MAX_BOOKEND_SECONDS:g} s.")
        says = entry.get("says", "")
        if says and says not in kit_vars:
            raise KitProblem(f"brand.json: the {name} bookend says {says!r}, which isn't one of its vars.")
        cues = entry.get("sounds", [])
        if not isinstance(cues, list):
            raise KitProblem(f"brand.json: the {name} bookend's sounds are a list.")
        for cue in cues:
            problem = bookend_sound_problem(name, cue, kit_sounds)
            if problem:
                raise KitProblem(f"brand.json: {problem}.")
        found[name] = Bookend(name=name, seconds=seconds, says=says, sounds=tuple(dict(cue) for cue in cues))
    return found


def named_words(manifest: dict, key: str) -> dict[str, str]:
    """The kit's vars, {"intro": "what the line is"}, checked: names plain words, each with its words."""
    given = manifest.get(key, {})
    ok = isinstance(given, dict) and all(NAME.match(k) and isinstance(v, str) for k, v in given.items())
    if not ok:
        raise KitProblem(f'brand.json: "{key}" is an object of name to what it is, like {{"intro": "a short line"}}.')
    return dict(given)


def named_seconds(manifest: dict, key: str) -> dict[str, float]:
    """The character's moves, {"bounce": 0.6}, checked: names plain words, each lasting more than 0 seconds."""
    given = manifest.get(key, {})
    ok = isinstance(given, dict) and all(NAME.match(k) and number(v) and v > 0 for k, v in given.items())
    if not ok:
        raise KitProblem(f'brand.json: "{key}" is an object of name to seconds, like {{"bounce": 0.6}}.')
    return {name: float(seconds) for name, seconds in given.items()}


CHARACTER_NAME = 'brand.json: "character" is the name the character has under Brand, like "lantern".'


def read_kit(folder: Path) -> Kit:
    """A kit's folder, read and checked; KitProblem with the first thing wrong: brand.json missing or not JSON, no
    name or api_doc, a sound, bookend, var or move that is wrong (read_sounds, read_bookends), a character whose name
    can't be used in code, moves without a character, brand.js missing, too big, or reaching out (script_problem)."""
    try:
        manifest = json.loads((folder / MANIFEST).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise KitProblem(f"The brand kit has no {MANIFEST} in {folder}.") from None
    except (ValueError, OSError) as e:
        raise KitProblem(f"The brand kit's {MANIFEST} can't be read: {e}") from None
    if not isinstance(manifest, dict):
        raise KitProblem(f"The brand kit's {MANIFEST} is an object with name, api_doc and the rest.")
    name = manifest.get("name")
    api_doc = manifest.get("api_doc")
    if not isinstance(name, str) or not name.strip():
        raise KitProblem('brand.json needs a "name".')
    if not isinstance(api_doc, str) or not api_doc.strip():
        raise KitProblem('brand.json needs an "api_doc": the functions under Brand the writer may call, in words.')
    kit_sounds = read_sounds(manifest, folder)
    kit_vars = named_words(manifest, "vars")
    bookends = read_bookends(manifest, kit_vars, kit_sounds)
    character = manifest.get("character", "")
    if not isinstance(character, str):
        raise KitProblem(CHARACTER_NAME)
    if character and not IDENTIFIER.match(character):
        raise KitProblem(CHARACTER_NAME)
    moves = named_seconds(manifest, "moves")
    if moves and not character:
        raise KitProblem('brand.json has moves but no "character" to make them.')
    background = manifest.get("background", False)
    if not isinstance(background, bool):
        raise KitProblem('brand.json: "background" is true or false.')
    script_path = folder / SCRIPT
    if not script_path.is_file():
        raise KitProblem(f"The brand kit has no {SCRIPT} in {folder}.")
    if script_path.stat().st_size > MAX_SCRIPT_BYTES:
        raise KitProblem(f"The brand kit's {SCRIPT} is over {MAX_SCRIPT_BYTES // 1000} KB.")
    script = script_path.read_text(encoding="utf-8")
    problem = script_problem(script)
    if problem:
        raise KitProblem(f"The brand kit can't be used: {problem}")
    version = version_of(folder, [path.name for path in kit_sounds.values()])
    return Kit(name=name.strip(), folder=folder, api_doc=api_doc.strip(), script=script, sounds=kit_sounds,
               bookends=bookends, background=background, character=character, moves=moves, vars=kit_vars,
               version=version)


def snapshot(kit: Kit, job_folder: Path) -> dict:
    """Copies the kit's files into the job's folder (brand/), so the video is made with the kit as it was when it was
    asked for, and gives the record for job.data["brand_kit"]: {"name": "my-channel", "version": "3f2a…", "path":
    "/…/skills/my-channel/assets/brand"}, the name being the skill's."""
    target = job_folder / FOLDER
    target.mkdir(parents=True, exist_ok=True)
    for file_name in [MANIFEST, SCRIPT, *(path.name for path in kit.sounds.values())]:
        shutil.copy2(kit.folder / file_name, target / file_name)
    skill = kit.folder.parent.parent.name
    return {"name": skill, "version": kit.version, "path": str(kit.folder)}


def kit_of(data: dict, job_folder: Path) -> Kit | None:
    """The kit a job was asked with, read from its own copy (brand/), or None for a video without one. A copy that is
    gone or whose files changed since (another version) -> KitProblem: a branded video is never made without its kit."""
    record = data.get("brand_kit")
    if not record:
        return None
    kit = read_kit(job_folder / FOLDER)
    if kit.version != record.get("version"):
        raise KitProblem(f"The brand kit's copy in this video's folder changed (version {kit.version}, asked with "
                         f"{record.get('version')}); ask for the video again.")
    return kit


def has(kit: Kit | None, bookend: str) -> bool:
    """Decides whether a video's kit adds this bookend: a kit with a card -> has(kit, "card") True; no kit -> False."""
    return kit is not None and bookend in kit.bookends


def segment_problem(kit: Kit, timed_seconds: float | None) -> str | None:
    """Decides whether a kit can be used for this video: a handoff or ending sits around the timed segment, so a kit
    with either needs one. Handoff and no timed_segment_seconds -> what to do; a kit with only a card, or a video
    with a segment -> None."""
    around = [name for name in ("handoff", "ending") if name in kit.bookends]
    if around and not timed_seconds:
        return (f"The {kit.name} brand kit's {' and '.join(around)} sit around a timed segment, so give "
                "timed_segment_seconds too.")
    return None


# ---- The writer: what it is told, and what it may not do ----

def writer_rules(kit: Kit) -> str:
    """The writer's instruction for a video with this kit: its api_doc and the rules (Brand is fixed, no character or
    background of its own, no bookend scenes), then what applies to this kit: the background it draws, the character
    the stage draws through the segment and its moves, the words the bookends need, the kit's sounds."""
    lines = [f"## This video has a brand kit: {kit.name}", "",
             "Its code is in the page as `Brand`. What it offers:", "", kit.api_doc, "",
             "- **`Brand.*` is fixed: call it, never redraw or imitate it.** Never assign to `Brand` or anything under "
             "it, and never declare your own `Brand`.",
             "- **Do not draw your own character or background.**",
             "- **Do not write the bookend scenes.** Odie adds them at fixed lengths; your narration and "
             "`Video.scenes([...])` hold only your own scenes."]
    if kit.background:
        lines.append("- **The kit draws the background under every scene.** Leave the stage clear: no fill or picture "
                     "over the whole stage, no 3D background colour; draw only what the scene shows, and show a "
                     "picture framed, never edge to edge. This replaces any full-bleed card the guide above asks for.")
    if kit.character:
        moves = ", ".join(f"{name} ({seconds:g} s)" for name, seconds in kit.moves.items())
        lines.append(f"- **The stage draws `Brand.{kit.character}` through the whole timed segment** (its place, its "
                     "loop and its timer). Never draw or call it yourself. To make it move, cue a move: "
                     f"`Video.moves([{{scene: 3, at: 1.5, name: \"…\"}}, {{scene: 4, beat: 1, name: \"…\"}}])`, "
                     "scene from 1 and inside the timed segment, at (seconds into the scene) or beat (a phrase, "
                     f"from 0). The moves: {moves or 'none'}.")
    if kit.vars:
        wanted = ", ".join(f'"{name}": {words}' for name, words in kit.vars.items())
        lines.append(f"- **Give the bookends' words in submit_video's `brand`:** {{{wanted}}}, each one short line.")
        spoken = [bookend.says for bookend in kit.bookends.values() if bookend.says]
        for name in spoken:
            lines.append(f'  `"{name}"` is spoken aloud, so write it as speech; it isn\'t part of the narration.')
    if kit.sounds:
        names = ", ".join(kit.sounds)
        lines.append(f"- **The kit's own sounds join the list for `Video.sounds`:** {names}.")
    return "\n".join(lines) + "\n"


# Writing to Brand: `Brand = …`, `window.Brand.x = …`, `Brand["x"] += …`, a declaration of one's own, or changing it
# through Object.assign, Object.defineProperty, delete and the like.
ASSIGNS = re.compile(r"""(?<![\w$.])(?:window\s*\.\s*)?Brand(?:\s*\.\s*[\w$]+|\s*\[[^\]]*\])*\s*"""
                     r"""(?:=(?!=)|\+=|-=|\*=|/=|%=|\|\|=|&&=|\?\?=|\+\+|--)""")
DECLARES = re.compile(r"""\b(?:var|let|const|function|class)\s+Brand\b""")
CHANGES = re.compile(r"""\b(?:Object\s*\.\s*(?:assign|defineProperty|defineProperties|setPrototypeOf)\s*\(\s*"""
                     r"""(?:window\s*\.\s*)?Brand\b|delete\s+(?:window\s*\.\s*)?Brand\b)""")


def reassign_problem(body: str) -> str | None:
    """Decides whether a page tries to change the kit: `Brand.lantern = {}`, `window.Brand = …`, `const Brand = …` or
    `Object.assign(Brand, …)` -> the words to fix; `Brand.background(ctx, t, w, h)` or `if (Brand.x == 1)` -> None."""
    for pattern in (ASSIGNS, DECLARES, CHANGES):
        match = pattern.search(body)
        if match:
            return (f"The page changes the brand kit ({match.group(0).strip()}): Brand is fixed. Call its functions, "
                    "never assign to Brand or anything under it, and never declare your own Brand.")
    return None


def vars_as_given(value):
    """The bookends' words the writer meant; some models send the object as JSON text: '{"intro": "Hi."}' ->
    {"intro": "Hi."}. Anything else is passed on for vars_problem to judge."""
    if not isinstance(value, str):
        return value
    try:
        return json.loads(value)
    except ValueError:
        return value


def vars_problem(kit: Kit, given) -> str | None:
    """Decides whether the writer gave the bookends' words: every var the kit declares, each a line of words, and no
    other. A kit with vars {"intro": …}: {"intro": "Here is the short version."} -> None; {} or None -> "Give
    submit_video's brand: {"intro": …}"; {"intro": ""} -> the same; {"intro": "…", "extra": "x"} -> "there is no
    'extra'". A kit without vars -> None whatever was given."""
    if not kit.vars:
        return None
    wanted = ", ".join(f'"{name}": {words}' for name, words in kit.vars.items())
    ask = f"Give submit_video's brand, the bookends' words: {{{wanted}}}."
    if not isinstance(given, dict):
        return ask
    for name in given:
        if name not in kit.vars:
            return f"brand has {name!r}, which the kit doesn't use. {ask}"
    for name in kit.vars:
        words = given.get(name)
        if not isinstance(words, str) or not words.strip():
            return ask
        if len(words) > MAX_VAR_CHARACTERS:
            return f"brand's {name!r} is {len(words)} characters; keep it to one short line."
    return None


MOVE_KEYS = ("scene", "name", "at", "beat")


def move_problem(cues: list, kit: Kit, segment: tuple[int, int] | None, narration: list[str]) -> str | None:
    """Decides whether the moves the page cued on the kit's character (Video.moveCues()) can play: each an object with
    a scene inside the timed segment (from 1), a move the kit has, and at (seconds, 0 or more) or beat (a phrase the
    scene has). With the segment on scenes 2 to 3 and a "bounce" move: [{"scene": 2, "at": 1, "name": "bounce"}] ->
    None; {"scene": 1, …} -> "move 1 is in scene 1, outside the timed segment (scenes 2 to 3)"; "spin" -> "there is
    no move 'spin'"."""
    if not cues:
        return None
    if not kit.character:
        return "Video.moves: this kit has no character to move; remove Video.moves."
    if segment is None:
        return "Video.moves: moves play only in the timed segment, and this video has none; remove Video.moves."
    first, last = segment
    for number_, cue in enumerate(cues, start=1):
        where = f"Video.moves: move {number_}"
        if not isinstance(cue, dict) or any(key not in MOVE_KEYS for key in cue):
            return f'{where} is like {{scene: 3, at: 1.5, name: "…"}}: scene, name, and at or beat.'
        if cue.get("name") not in kit.moves:
            return f"{where}: there is no move {cue.get('name')!r}; the moves are {', '.join(kit.moves)}."
        scene = cue.get("scene")
        if not sounds.is_whole(scene) or not first + 1 <= scene <= last + 1:
            return (f"{where} is in scene {scene!r}, outside the timed segment (scenes {first + 1} to {last + 1}); "
                    "moves play only there.")
        has_at = "at" in cue
        has_beat = "beat" in cue
        if has_at == has_beat:
            return f"{where} needs one of at (seconds into the scene) or beat (a phrase, from 0)."
        if has_at and (not number(cue["at"]) or cue["at"] < 0):
            return f"{where} has at {cue['at']!r}; at is seconds into the scene, 0 or more."
        if has_beat:
            phrases = len(beats.phrases(narration[scene - 1]))
            if not sounds.is_whole(cue["beat"]) or not 0 <= cue["beat"] < phrases:
                return f"{where} has beat {cue['beat']!r}; scene {scene} has beats 0 to {phrases - 1}."
    return None


# ---- The page: the kit's script and settings, and the scenes' order with the bookends ----

def as_script_text(text: str) -> str:
    """Text inside a <script>, made unable to close it: "a</script>b" -> "a<\\/script>b" (the same to JavaScript)."""
    return SCRIPT_CLOSE.sub(r"<\\/\1", text)


def page_script(branded: Branded, timed_video: bool, later: bool = False) -> str:
    """The kit as scripts for the page, after video.js and before the writer's page: brand.js, then Video.brand with
    the kit's settings and the bookends' words (`timed_video`: whether the handoff and ending go around a timed
    segment). `later` is for the writer's page check: the scenes wait for Video.layout (Odie reads the timed marks
    first, then gives the timings with the bookends in them), and the check watches for a page painting over the kit's
    background (Video.brandReport)."""
    kit = branded.kit
    settings = {
        "background": kit.background,
        "character": kit.character,
        "moves": kit.moves,
        "bookends": {name: {"seconds": bookend.seconds} for name, bookend in kit.bookends.items()},
        "vars": branded.vars,
        "timed": timed_video,
    }
    parts = []
    if later:
        parts.append("<script>window.__layoutLater = true; window.__brandCheck = true;</script>")
    parts.append(f"<script>{as_script_text(kit.script)}</script>")
    settings_text = as_script_text(json.dumps(settings, ensure_ascii=False))
    parts.append(f"<script>Video.brand({settings_text});</script>")
    return "\n".join(parts)


def scene_order(narrated: int, closing: int, segment: tuple[int, int] | None, kit: Kit) -> list:
    """The video's scenes in the order they play, as video.js lays them out (Video.order()): the writer's scenes by
    number (from 1), the handoff just before the timed segment's first scene, the ending right after its last, then
    Odie's closing scenes (the credits card), then the card. Four scenes, the segment on scenes 2 to 3 (0-based (1,
    2)), every bookend, no credits -> [1, "handoff", 2, 3, "ending", 4, "card"]; no segment -> [1, 2, 3, 4, "card"]."""
    order = []
    for index in range(narrated):
        if segment is not None and index == segment[0] and "handoff" in kit.bookends:
            order.append("handoff")
        order.append(index + 1)
        if segment is not None and index == segment[1] and "ending" in kit.bookends:
            order.append("ending")
    order += ["closing"] * closing
    if "card" in kit.bookends:
        order.append("card")
    return order


def final_index(order: list, scene: int) -> int:
    """Where the writer's scene `scene` (from 0) plays among all the scenes: [1, "handoff", 2, 3] and scene 1 -> 2."""
    return order.index(scene + 1)


def estimated_timings(narration: list[str], order: list, branded: Branded) -> dict:
    """The page check's timings with the bookends in: the writer's scenes as page.estimated_timings guesses them, each
    bookend its seconds (the handoff longer when its line's words take longer to say), a breath between scenes."""
    writer_timings = page.estimated_timings(narration)
    lengths = []
    scene_beats = []
    for label in order:
        if isinstance(label, int):
            lengths.append(writer_timings["lengths"][label - 1])
            scene_beats.append(writer_timings["beats"][label - 1])
            continue
        bookend = branded.kit.bookends[label]
        length = bookend.seconds
        line = branded.vars.get(bookend.says, "")
        if line:
            spoken = page.estimated_timings([line])["lengths"][0]
            length = max(length, spoken)
        lengths.append(round(length, 3))
        scene_beats.append([0.0])
    starts, _total = timeline.scene_starts(lengths)
    return {"starts": starts, "lengths": lengths, "beats": scene_beats}


# ---- The made video: the bookends put into the spoken timeline ----

def wav_parts(wav: bytes) -> tuple:
    """A WAV's format and its sample bytes."""
    with wave.open(io.BytesIO(wav)) as w:
        return w.getparams(), w.readframes(w.getnframes())


def wav_bytes(params, frames: bytes) -> bytes:
    """A WAV in `params`' format holding `frames`."""
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setparams(params)
        w.writeframes(frames)
    return out.getvalue()


def bookend_length(bookend: Bookend, spoken: bytes | None) -> float:
    """How long a bookend plays: its seconds, or its spoken line's length when that is longer (the animation plays
    over its seconds and then holds). Held more than LONG_HOLD past its animation -> logged as a warning, so a line
    that is too long is noticed. A 2.5 s handoff with a 1.8 s line -> 2.5; with a 4.0 s line -> 4.0, and a warning."""
    if spoken is None:
        return bookend.seconds
    line_seconds = narrate.wav_seconds(spoken)
    length = max(bookend.seconds, line_seconds)
    hold = length - bookend.seconds
    if hold > LONG_HOLD:
        log.warning("video brand kit: the %s bookend holds its last frame %.1f s, for a %.1f s line over its %.1f s; "
                    "a shorter line keeps it moving", bookend.name, hold, line_seconds, bookend.seconds)
    return round(length, 3)


@dataclass
class Insert:
    """The time one bookend puts into the writer's timeline: at `point` (seconds into the video as narrated), `lead`
    seconds of quiet, the bookend's `length`, then `tail` seconds of quiet. `moves_at_point` says whether a moment
    exactly at the point moves later too: yes for the handoff (the segment's first scene starts right there and must
    play after it), no for the ending (the segment's last word can fall exactly at the point and stays before it)."""
    name: str
    point: float
    lead: float
    length: float
    tail: float
    moves_at_point: bool
    line: bytes = b""  # the bookend's spoken line, as sample bytes in the voice track's format

    @property
    def seconds(self) -> float:
        return self.lead + self.length + self.tail

    def moves(self, t: float) -> bool:
        """Decides whether a moment of the video as narrated plays later because of this insert: after its point ->
        True; exactly at it -> moves_at_point; before it -> False. A handoff at 6.5: 6.5 -> True, 6.4 -> False."""
        if t > self.point + EPSILON:
            return True
        return self.moves_at_point and t >= self.point - EPSILON


EPSILON = 1e-6  # seconds: moments this close are the same moment


def inserts_for(kit: Kit, starts: list[float], lengths: list[float], total: float, segment: tuple[int, int] | None,
                spoken: dict[str, bytes]) -> list[Insert]:
    """The kit's bookends as inserts into a narrated timeline (scene `starts` and `lengths`, `total` its end): the
    handoff at the segment's first scene's start (its line, then a breath), the ending at the segment's last scene's
    end (a breath first), the card at the very end (a breath first). A bookend that sits around the segment is left
    out of a video without one."""
    inserts = []
    if segment is not None and has(kit, "handoff"):
        bookend = kit.bookends["handoff"]
        line = spoken.get("handoff")
        line_frames = b""
        if line is not None:
            line_frames = wav_parts(line)[1]
        inserts.append(Insert("handoff", point=starts[segment[0]], lead=0.0, length=bookend_length(bookend, line),
                              tail=timeline.BREATH, moves_at_point=True, line=line_frames))
    if segment is not None and has(kit, "ending"):
        last = segment[1]
        length = bookend_length(kit.bookends["ending"], spoken.get("ending"))
        inserts.append(Insert("ending", point=starts[last] + lengths[last], lead=timeline.BREATH, length=length,
                              tail=0.0, moves_at_point=False))
    if has(kit, "card"):
        inserts.append(Insert("card", point=total, lead=timeline.BREATH, length=kit.bookends["card"].seconds,
                              tail=0.0, moves_at_point=False))
    return inserts


def moved(t: float, inserts: list[Insert]) -> float:
    """A moment of the video as narrated, in the video with the bookends in: later by every insert that moves it."""
    shift = sum(insert.seconds for insert in inserts if insert.moves(t))
    return round(t + shift, 3)


def bookend_start(insert: Insert, inserts: list[Insert]) -> float:
    """When a bookend starts in the video: its point, moved by the other inserts before it, plus its lead."""
    others = [other for other in inserts if other is not insert]
    return round(moved(insert.point, others) + insert.lead, 3)


def voice_with_inserts(wav: bytes, inserts: list[Insert], total: float, video_end: float) -> bytes:
    """The voice track with each insert's stretch put in at its point: its lead's quiet, its line (if it speaks)
    then quiet to its length, then its tail's quiet. Quiet is added first to the narrated end (`total`: a credits card
    after the last word is silent), and last to `video_end`, so the bookends' sounds aren't cut off in the mix. The
    inserts go in from the latest point back, so each earlier point is still where it was."""
    params, frames = wav_parts(wav)
    frame_size = params.sampwidth * params.nchannels

    def bytes_for(seconds: float) -> int:
        return round(seconds * params.framerate) * frame_size

    def quiet(seconds: float) -> bytes:
        return b"\x00" * bytes_for(seconds)

    narrated_end = bytes_for(total)
    if len(frames) < narrated_end:
        frames += b"\x00" * (narrated_end - len(frames))
    for insert in sorted(inserts, key=lambda one: one.point, reverse=True):
        line = insert.line[:bytes_for(insert.length)]
        body = line + b"\x00" * (bytes_for(insert.length) - len(line))
        stretch = quiet(insert.lead) + body + quiet(insert.tail)
        cut = bytes_for(insert.point)
        frames = frames[:cut] + stretch + frames[cut:]
    end = bytes_for(video_end)
    if len(frames) < end:
        frames += b"\x00" * (end - len(frames))
    return wav_bytes(params, frames)


@dataclass
class Laid:
    """The video's timeline with the bookends in: the voice track (the bookends' lines and quiet inserted, and quiet to
    the video's end), each scene's start, length and beats in playing order, the segment clock moved with them, and
    the order (scene_order)."""
    wav: bytes
    starts: list[float]
    lengths: list[float]
    beats: list[list[float]]
    clock: dict | None
    order: list


def lay_out(wav: bytes, lengths: list[float], scene_beats: list[list[float]], gaps: list[float], clock: dict | None,
            segment: tuple[int, int] | None, narrated: int, kit: Kit, spoken: dict[str, bytes]) -> Laid:
    """Puts the kit's bookends into a spoken video's timeline. `wav`, `lengths`, `scene_beats` and `gaps` are the video
    as narrated (and fitted): the writer's `narrated` scenes, then any silent closing scenes (the credits card);
    `segment` is the timed segment's first and last scene (0-based), and `spoken` each speaking bookend's line as a
    WAV ({"handoff": …}). Each bookend is time inserted (inserts_for); every scene from its point on plays that much
    later, the segment clock with them, and the voice track gets the same stretches (voice_with_inserts), then quiet
    to the video's end so the bookends' sounds aren't cut off.
    Scenes of 6 s and 30 s, the segment the second, and a 2.5 s handoff: the handoff starts at 6.5, the segment at
    9.5 (6.5 + 2.5 + the 0.5 breath), and the clock's start and end are 3 s later."""
    starts, total = timed.starts_with_gaps(lengths, gaps)
    order = scene_order(narrated, len(lengths) - narrated, segment, kit)
    inserts = inserts_for(kit, starts, lengths, total, segment, spoken)
    by_name = {insert.name: insert for insert in inserts}

    final_starts = []
    final_lengths = []
    final_beats = []
    closing_seen = 0
    for label in order:
        if label in by_name:
            insert = by_name[label]
            final_starts.append(bookend_start(insert, inserts))
            final_lengths.append(insert.length)
            final_beats.append([0.0])
            continue
        if label == "closing":
            index = narrated + closing_seen
            closing_seen += 1
        else:
            index = label - 1
        final_starts.append(moved(starts[index], inserts))
        final_lengths.append(lengths[index])
        final_beats.append(scene_beats[index])

    moved_clock = None
    if clock is not None:
        moved_clock = dict(clock, start=moved(clock["start"], inserts), end=moved(clock["end"], inserts))

    video_end = final_starts[-1] + final_lengths[-1]
    voice = voice_with_inserts(wav, inserts, total, video_end)
    return Laid(wav=voice, starts=final_starts, lengths=final_lengths, beats=final_beats, clock=moved_clock,
                order=order)


def cues_in_order(cues: list[dict], order: list) -> list[dict]:
    """The writer's sound cues with their scenes renumbered for the scenes as they play: with [1, "handoff", 2],
    {"scene": 2, "at": 1, "name": "ting"} -> {"scene": 3, "at": 1, "name": "ting"}. A scene not in the order is left
    as it is (the mix leaves it out, as before)."""
    renumbered = []
    for cue in cues:
        moved_cue = dict(cue)
        scene = cue.get("scene")
        if isinstance(scene, int) and scene in order:
            moved_cue["scene"] = order.index(scene) + 1
        renumbered.append(moved_cue)
    return renumbered


def bookend_sounds(kit: Kit, timings: dict, order: list) -> list[sounds.Placed]:
    """The bookends' own sounds as the mix plays them: at the bookend's start plus each sound's at, each a hit that
    rings for its file's length or to the video's end. An ending at 40.0 s with {"at": 0.2, "name": "ting"} -> the
    kit's ting at 40.2 s. The same kit always puts them at the same moments of its bookends."""
    video_end = timings["starts"][-1] + timings["lengths"][-1]
    placed = []
    for name, bookend in kit.bookends.items():
        if name not in order:
            continue
        start_of_bookend = timings["starts"][order.index(name)]
        for cue in bookend.sounds:
            found = sounds.lookup(cue["name"], kit.sounds)
            if found is None:
                continue
            _sound, sound_path = found
            file = sounds.readable_format(sound_path)
            if file is None:
                continue
            start = round(start_of_bookend + cue["at"], 3)
            file_seconds = file.frames / file.rate
            seconds = round(min(file_seconds, video_end - start), 3)
            if seconds <= 0:
                continue
            one = sounds.Placed(start=start, path=sound_path, seconds=seconds, gain=sounds.DEFAULT_GAIN["hit"],
                                kind="hit", name=cue["name"], frames=file.frames,
                                cut=seconds < round(file_seconds, 3))
            sounds.loudness_dbfs(one)  # measured now, and remembered for the mix
            placed.append(one)
    return placed


# ---- The writer's page check, for a video with a kit ----

KIT_ERROR = "brand kit:"  # how video.js marks an error in the kit's own code (kitCall, Video.brand)


def kit_error(errors: list[str]) -> str | None:
    """The first error the kit's own code raised, or None: ["SyntaxError: …", "Error: brand kit: Brand.bookend isn't
    a function"] -> the second; errors of the page's own -> None."""
    for error in errors:
        if KIT_ERROR in error:
            return error
    return None


def covered_problem(scenes: list[int]) -> str:
    """The words for scenes that painted over the kit's background: [2] -> "Scene 2 covers the whole stage …";
    [2, 4] -> "Scenes 2 and 4 cover the whole stage …"."""
    if len(scenes) == 1:
        which = f"Scene {scenes[0]} covers"
    else:
        listed = ", ".join(str(scene) for scene in scenes[:-1])
        which = f"Scenes {listed} and {scenes[-1]} cover"
    return (f"{which} the whole stage with a background of its own (a fill or a picture edge to edge, or a 3D "
            "background colour), but this video's brand kit draws the background. Leave the stage clear: draw only "
            "what the scene shows, and show a picture framed, not edge to edge.")


async def check(body: str, narration: list[str], browser, branded: Branded, assets_script: str = "",
                size: tuple[int, int] = timeline.LANDSCAPE, timed_seconds: float | None = None) -> page.CheckResult:
    """The writer's page check (as page.check_with_cues) for a video with a brand kit, the kit in the page. The page
    is loaded with its scenes waiting; the timed marks are read and judged first (timed.marks_problem), then the
    scenes are laid out with the kit's bookends in (scene_order, estimated_timings) and three moments of every scene
    are drawn, the bookends too, with the segment clock running. Then: a scene that painted over the kit's background
    (covered_problem), the character's moves (move_problem), and the sound cues, read back for the writer to judge
    with the kit's sounds. A page error is the writer's to fix, as before; an error in the kit's own code (marked by
    video.js, kit_error) is KitProblem: the kit is broken, and the writer can't fix it."""
    kit = branded.kit
    writer_timings = page.estimated_timings(narration)
    script = page_script(branded, timed_video=bool(timed_seconds), later=True)
    try:
        html = page.assemble(body, writer_timings, assets_script, size=size, brand_script=script)
    except ValueError as e:
        return page.CheckResult(problem=str(e))
    width, height = size
    async with browser.sealed_page(html, width, height) as tab:
        load_errors = list(tab.errors)
        broken = kit_error(load_errors)
        if broken:
            raise KitProblem(f"The {kit.name} brand kit didn't load: {load_errors[0]}")
        scene_count = await tab.eval("window.__sceneCount === undefined ? null : window.__sceneCount")
        problem = page.first_problem(scene_count, len(narration), load_errors, [])
        if problem:
            return page.CheckResult(problem=problem)
        segment = None
        if timed_seconds:
            marks = await tab.eval("Video.timedScenes()")
            problem = timed.marks_problem(marks["starts"], marks["ends"], timed_seconds)
            if problem:
                return page.CheckResult(problem=problem)
            segment = timed.segment_scenes(marks["starts"], marks["ends"])
        order = scene_order(len(narration), 0, segment, kit)
        timings = estimated_timings(narration, order, branded)
        try:
            await tab.eval(f"Video.layout({json.dumps(timings)})")
        except BrowserTimeout:
            raise
        except BrowserError as e:
            return page.CheckResult(problem=f"The page raised an error while loading: {e}")
        laid_out = await tab.eval("Video.order()")
        if laid_out != order:
            raise KitProblem(f"The video's scenes came out as {laid_out}, not {order}; this is Odie's mistake, not the "
                             "page's.")
        if segment is not None:
            first = final_index(order, segment[0])
            last = final_index(order, segment[1])
            clock = timed.clock_from(timings, first, last, timed_seconds)
            await tab.eval(f"window.ODIE_TIMED = {json.dumps(clock)}")
        draw_errors = []
        for probe, seconds in enumerate(page.probe_times(timings)):
            error = await page._draw_error(tab, seconds)
            if not error:
                continue
            index = probe // page.PROBES_PER_SCENE
            label = order[index]
            if KIT_ERROR in error or not isinstance(label, int):
                raise KitProblem(f"The {kit.name} brand kit failed while drawing: {error}")
            t = round(seconds - timings["starts"][index], 3)  # draw's t: seconds into the scene
            draw_errors.append((label, t, error))
            break
        problem = page.first_problem(scene_count, len(narration), load_errors, draw_errors)
        if problem:
            return page.CheckResult(problem=problem)
        report = await tab.eval("Video.brandReport()")
        if report["covered"]:
            return page.CheckResult(problem=covered_problem(report["covered"]))
        moves = await tab.eval("Video.moveCues()")
        problem = move_problem(moves, kit, segment, narration)
        if problem:
            return page.CheckResult(problem=problem)
        cues = await tab.eval("Video.soundCues()")
        return page.CheckResult(problem=None, cues=cues, segment=segment)
