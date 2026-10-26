"""The audio-story skill's tools. story_voices gives the chat model the voices for the story's cast form, already shaped
as form options (value, label, note, and a ▶ preview), for the engine chosen in Settings and the accent the user picked,
so the model never builds forty options by hand or guesses a voice id. (Should it still rewrite them, the web fills
in the ▶ of any option that names a voice: web/src/blocks/voicePreviews.ts.) make_audio_story checks the story the user chose
within the chat turn and puts it in Odie's background queue (odie.making.jobs, kind "story" from odie.making.story):
the writer writes the script and chooses the sound, and Odie's code speaks, mixes and posts one file. Plain trusted code
of a built-in skill: no shell, no approval card."""
import math
from urllib.parse import quote

from google.adk.tools import FunctionTool, ToolContext

from odie import voice
from odie.agent.context import session_id_of
from odie.agent.tools.files import workspace
from odie.making import chat, jobs, sound_library, story, story_writer

ACCENTS = {"phonon": ["American", "British"], "kokoro": ["American", "British", "Indian"],
           "openai": ["American", "British", "Indian"]}
NOTE_LIMIT = 80  # a form option's note is cut at 80 characters
WHO = {"female": "woman", "male": "man", "neutral": "neutral"}
CHARACTERS = "Characters"  # Phonon's group of character voices (a pirate captain, a witch, an old keeper)
CHARACTER_NOTE = "character voice"
OPENAI_ACCENT = "accent added in the story"  # OpenAI voices have no fixed accent: the story asks for it in words


def accents_for(engine: str) -> list[str]:
    """The accents a story can be cast in with this engine's voices: Phonon's English voices are American or British;
    Kokoro has Indian voices too; OpenAI's voices take any of the three as a style line. "phonon" -> ["American",
    "British"]; "kokoro" -> ["American", "British", "Indian"]; an engine with no list -> ["American"]."""
    return ACCENTS.get(engine, ["American"])


def preview_path(engine: str, voice_id: str) -> str:
    """The ▶ preview for a voice, a path the form plays: ("phonon", "Captain Silas Blackwater") ->
    "/api/voice/preview/phonon/Captain%20Silas%20Blackwater"."""
    return f"/api/voice/preview/{engine}/{quote(voice_id, safe='')}"


def option(engine: str, voice_id: str, label: str, note: str) -> dict:
    """One voice as a form option, its note cut to the form's 80 characters."""
    return {"value": voice_id, "label": label, "note": note[:NOTE_LIMIT], "preview": preview_path(engine, voice_id)}


def noted(*parts: str) -> str:
    """A note from its parts, the empty ones left out: ("woman", "warm and low") -> "woman · warm and low";
    ("man", "") -> "man"."""
    return " · ".join(part for part in parts if part)


def phonon_options(voices: list[dict], accent: str) -> list[dict]:
    """Phonon's voices for one accent ("British · Female", "British · Male"), each noted with who it is and how it
    sounds, then its Characters group, noted as character voices, for the roles a character voice lifts."""
    accent_voices = []
    characters = []
    for v in voices:
        group = v.get("group", "")
        note = v.get("note", "")
        if group.startswith(f"{accent} · "):
            gender = v.get("gender") or ""
            who = WHO.get(gender, "voice")
            accent_voices.append(option("phonon", v["id"], v["label"], noted(who, note)))
        elif group == CHARACTERS:
            characters.append(option("phonon", v["id"], v["label"], noted(CHARACTER_NOTE, note)))
    return accent_voices + characters


def kokoro_options(accent: str) -> list[dict]:
    """Kokoro's voices with this accent, noted woman or man: "Indian" -> Alpha, Beta (women), Omega, Psi (men)."""
    return [option("kokoro", v["id"], v["label"], WHO[v["group"]]) for v in voice.KOKORO_VOICES if v["note"] == accent]


def openai_options() -> list[dict]:
    """Every OpenAI voice: they have no fixed accent, so the story asks for it, and a ▶ plays it without one."""
    return [option("openai", v["id"], v["label"], f"{WHO[v['group']]} · {OPENAI_ACCENT}") for v in voice.VOICES]


def accent_problem(engine: str, accent: str) -> str | None:
    """Whether an accent can be cast with this engine, as words to fix: ("phonon", "Indian") -> "Phonon's voices here
    are American or British: choose one of those."; ("kokoro", "Indian") -> None."""
    offered = accents_for(engine)
    if accent in offered:
        return None
    label = voice.ENGINES.get(engine, {}).get("label", engine).split(" (")[0]
    listed = " or ".join(offered) if len(offered) == 2 else ", ".join(offered[:-1]) + " or " + offered[-1]
    return f"{label}'s voices here are {listed}: choose one of those."


def accent_word(given) -> str:
    """The accent as the user chose it, in its usual spelling: " british" -> "British"; None -> ""."""
    text = chat.text_or_empty(given)
    return text.strip().capitalize()


async def story_voices(accent: str = "") -> dict:
    """The voices for an audio story's cast form, for the voice engine chosen in Settings.
    accent: "American", "British" or "Indian", as the user chose it with the story. Without one, it returns the
    accents this engine offers, for that question.
    Returns {"engine", "accent", "options"}: options is the voices for that accent (and, on Phonon, its character
    voices: a pirate captain, a witch, an old keeper), each {value, label, note, preview}. Paste options exactly as
    given as the options of every voice select in the cast form, previews and all; use a `value` as the voice in
    make_audio_story. {"error": …}: choose as it says."""
    store = jobs.hooks["store"]
    engine, _chosen = voice.get_tts(store)
    if engine == "phonon":
        await voice.phonon_voices()  # Phonon's voices are known only once Ollama has been asked
    picked = accent_word(accent)
    if not picked:
        return {"engine": engine, "accents": accents_for(engine)}
    problem = accent_problem(engine, picked)
    if problem:
        return {"error": problem}
    if engine == "phonon":
        options = phonon_options(voice.engine_voices("phonon"), picked)
    elif engine == "kokoro":
        options = kokoro_options(picked)
    else:
        options = openai_options()
    return {"engine": engine, "accent": picked, "options": options}


MIN_MINUTES = 2
MAX_MINUTES = 15
DEFAULT_MINUTES = 5
MAX_SPEAKERS = 8  # the player gives up to eight speakers a tone of their own
WORD = "story"
WRITING_MINUTES = (2, 4)  # the writer's turn: a script with its sound takes a few minutes
MIXING_MINUTES = 1  # the mix and the master
LOCAL_SPEED = 10  # minutes of speech a local voice speaks in a minute
DOING = "writing the script and choosing the sound, then speaking every line and mixing it"

NO_GENRE = "genre is the story's genre, as the user chose it (horror, mystery, a bedtime story…)."
NO_PREMISE = "premise is the story's idea: the pitch the user chose, or their own idea, in a sentence or two."
NO_CAST = ('cast is a list of {id, name, voice, about}: the narrator and each character, with a voice from '
           "story_voices.")
VOICES_FROM = "Call story_voices for the voices to choose from."
NO_IMOVIE = ('There is no iMovie on this Mac, so the story uses Odie\'s own small sound kit, with no music. Tell the '
             'user once: "For richer sound, install iMovie (free in the App Store); Odie uses its sound library."')


def minutes_to_make(minutes: int, engine: str) -> tuple[int, int]:
    """The estimate told to the user, as (low, high) whole minutes: the writing (2 to 4), the speaking (a local voice
    speaks ten minutes of story in one; OpenAI about as fast as it plays) and the mix (1). 10 minutes on Kokoro -> (4,
    6); on OpenAI -> (13, 15)."""
    speaking = minutes
    if engine != "openai":
        speaking = math.ceil(minutes / LOCAL_SPEED)
    low_writing, high_writing = WRITING_MINUTES
    return low_writing + speaking + MIXING_MINUTES, high_writing + speaking + MIXING_MINUTES


def plain_cast(cast) -> list[dict] | str:
    """The cast as the model sent it, made plain: each member {id, name, voice, about}, the id a plain word made from
    the id or the name ("The Keeper" -> "the-keeper"). The problem in words instead when it can't be: not a list, a
    member without a name or a voice, too many speakers, or two with one id."""
    if not isinstance(cast, list) or not cast:
        return NO_CAST
    if len(cast) > MAX_SPEAKERS:
        return (f"A story has at most {MAX_SPEAKERS} speakers, the narrator included; this cast has {len(cast)}. Let "
                f"minor characters share a voice, or leave them to the narrator.")
    members = []
    for given in cast:
        if not isinstance(given, dict):
            return NO_CAST
        name = chat.text_or_empty(given.get("name")).strip()
        chosen_voice = chat.text_or_empty(given.get("voice")).strip()
        if not name or not chosen_voice:
            return NO_CAST
        id_or_name = chat.text_or_empty(given.get("id")).strip()
        if not id_or_name:
            id_or_name = name
        member_id = chat.slug_of(id_or_name, "speaker")
        if any(member["id"] == member_id for member in members):
            return f'Two cast members have the id "{member_id}": give each their own.'
        about = chat.text_or_empty(given.get("about")).strip()
        members.append({"id": member_id, "name": name, "voice": chosen_voice, "about": about})
    return members


def narrator_problem(narrator: str, cast: list[dict]) -> str | None:
    """Decides whether the narrator is someone in the cast: "narrator" with a Narrator in the cast -> None; "keeper"
    (a narrator in the story) -> None; "captain", in no one's id -> 'narrator is the cast id of who tells the story
    (…); "captain" isn't in the cast: narrator, keeper.'."""
    ids = [member["id"] for member in cast]
    if narrator in ids:
        return None
    return (f'narrator is the cast id of who tells the story ("{story_writer.NARRATOR_ID}" for an outside '
            f'storyteller, in the cast too); "{narrator}" isn\'t in the cast: {", ".join(ids)}.')


def sound_level_problem(level) -> str | None:
    """Decides whether the sound level can be used: a whole number from 10 to 40 -> None; 50, 5 or "loud" -> the
    range, as words to act on."""
    is_whole = isinstance(level, int) and not isinstance(level, bool)
    if is_whole and story.LOWEST_SOUND_LEVEL <= level <= story.HIGHEST_SOUND_LEVEL:
        return None
    return (f"sound_level is how loud the sound sits under the voices, from {story.LOWEST_SOUND_LEVEL} to "
            f"{story.HIGHEST_SOUND_LEVEL} ({story.DEFAULT_SOUND_LEVEL} unless the user chose), not {level}.")


def checked_voices(store, engine: str, cast: list[dict]) -> list[dict] | str:
    """Each member's voice checked in the engine chosen in Settings, by id or label, and kept as its id; the problem
    in words for the first that isn't there: "The keeper's voice: 'marin' isn't one of Kokoro's voices… Call
    story_voices for the voices to choose from."."""
    checked = []
    for member in cast:
        try:
            chosen = voice.voice_in_chosen_engine(store, member["voice"])
        except ValueError as e:
            return f"{member['name']}'s voice: {e} {VOICES_FROM}"
        checked.append({**member, "voice": chosen["id"]})
    return checked


def brief_record(request: story_writer.Request, sound_level: int, brief: str) -> str:
    """What the job's brief.md keeps: what the user chose, in plain lines."""
    cast_lines = []
    for member in request.cast:
        line = f"- {member['name']} ({member['id']}), voice {member['voice']}"
        if member["about"]:
            line += f": {member['about']}"
        cast_lines.append(line)
    chosen = (f"Genre: {request.genre}\nThe story: {request.premise}\nAccent: {request.accent}\n"
              f"Narrator: {request.narrator}\nLength: {request.minutes} minutes\nSound level: {sound_level} %")
    cast_text = "\n".join(cast_lines)
    return f"{chosen}\n\nCast:\n{cast_text}\n\nBrief:\n{brief}"


async def make_audio_story(title: str, genre: str, premise: str, cast: list[dict], narrator: str, accent: str,
                           minutes: int = 5, sound_level: int = 25, brief: str = "",
                           tool_context: ToolContext | None = None) -> dict:
    """Make the audio story the user chose in the guided start: a narrator, character voices, ambience, effects and
    music, posted to this chat as one file. Call it once, after the cast form. A separate writer writes the script and
    chooses the sound in the background; it sees only what you pass here.
    title: the story's title (short). genre: as the user chose it ("horror"). premise: the pitch or idea they chose,
    a sentence or two.
    cast: [{id, name, voice, about}] for the narrator and each character: id a short plain word ("keeper"), name as
    the listener knows them ("The keeper"), voice a value from story_voices, about one line on who they are.
    narrator: the id of who tells it: "narrator" for an outside storyteller (then in the cast as id "narrator"), or a
    character's id to tell it in the first person.
    accent: as chosen ("British"). minutes: 2 to 15 (the user's length, else 5). sound_level: 10 to 40, how loud the
    sound sits under the voices (the slider's value, else 25). brief: anything else the user asked for (tone, an
    ending, who it's for).
    It returns at once. {"error": …}: fix exactly that and call again. {"result": …}: reply in one or two lines as it
    says."""
    store = jobs.hooks["store"]
    genre = chat.text_or_empty(genre).strip()
    premise = chat.text_or_empty(premise).strip()
    brief = chat.text_or_empty(brief)
    if not genre:
        return {"error": NO_GENRE}
    if not premise:
        return {"error": NO_PREMISE}

    members = plain_cast(cast)
    if isinstance(members, str):
        return {"error": members}
    narrator_id = chat.slug_of(chat.text_or_empty(narrator), story_writer.NARRATOR_ID)
    problem = narrator_problem(narrator_id, members)
    if problem:
        return {"error": problem}

    minutes = chat.minutes_as_given(minutes, DEFAULT_MINUTES)
    problem = chat.minutes_problem(minutes, MIN_MINUTES, MAX_MINUTES, WORD, DEFAULT_MINUTES)
    if problem:
        return {"error": problem}
    sound_level = chat.minutes_as_given(sound_level, story.DEFAULT_SOUND_LEVEL)
    problem = sound_level_problem(sound_level)
    if problem:
        return {"error": problem}

    engine, _read_aloud = voice.get_tts(store)
    picked_accent = accent_word(accent)
    problem = accent_problem(engine, picked_accent)
    if problem:
        return {"error": problem}
    if engine == "phonon":
        await voice.phonon_voices()
    members = checked_voices(store, engine, members)
    if isinstance(members, str):
        return {"error": members}
    problem = chat.brief_problem(brief, WORD)
    if problem:
        return {"error": problem}

    name = chat.text_or_empty(title).strip()
    if not name:
        name = premise[:80]
    request = story_writer.Request(genre=genre, premise=premise, cast=members, narrator=narrator_id,
                                   accent=picked_accent, minutes=minutes, brief=brief, engine=engine)
    folder = chat.free_folder(workspace() / story.FOLDER, chat.slug_of(name, WORD))
    folder.mkdir(parents=True)
    job = jobs.Job(kind="story", slug=folder.name, title=name, topic=name, minutes=minutes,
                   brief=brief_record(request, sound_level, brief), session_id=session_id_of(tool_context),
                   folder=folder, data={"request": request, "sound_level": sound_level})
    place = jobs.submit(job)
    low, high = minutes_to_make(minutes, engine)
    result = chat.reply(place, low, high, DOING)
    libraries = sound_library.find_libraries(sound_library.LIBRARY_ROOT)
    if not sound_library.has_imovie(libraries):
        result = f"{result} {NO_IMOVIE}"
    return {"result": result}


TOOLS = [FunctionTool(story_voices), FunctionTool(make_audio_story)]
