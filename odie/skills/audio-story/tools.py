"""The audio-story skill's tools. story_voices gives the chat model the voices for the story's cast form, already shaped
as form options (value, label, note, and a ▶ preview), for the engine chosen in Settings and the accent the user picked,
so the model never builds forty options by hand or guesses a voice id. (Should it still rewrite them, the web fills
in the ▶ of any option that names a voice: web/src/blocks/voicePreviews.ts.) make_audio_story checks the story the user chose
within the chat turn and puts it in Odie's background queue (odie.making.jobs, kind "story" from odie.making.story):
the writer writes the script and chooses the sound, and Odie's code speaks, mixes and posts one file. Plain trusted code
of a built-in skill: no shell, no approval card."""
from urllib.parse import quote

from google.adk.tools import FunctionTool, ToolContext

from odie import voice
from odie.agent.context import session_id_of
from odie.agent.tools.files import workspace
from odie.making import chat, jobs, sound_library, story, story_writer

ACCENTS = {"phonon": ["American", "British"], "kokoro": ["American", "British", "Indian"],
           "openai": ["American", "British", "Indian"]}
DEFAULT_ACCENT = "American"  # the owner prefers American English for stories; British stays on offer
NOTE_LIMIT = 80  # a form option's note is cut at 80 characters
WHO = {"female": "woman", "male": "man", "neutral": "neutral", "creature": "creature", "any": "voice"}
CHARACTERS = "Characters"  # Phonon's group of character voices (a pirate captain, a witch, an old keeper)
CHARACTER_NOTE = "character voice"
OPENAI_ACCENT = "accent added in the story"  # OpenAI voices have no fixed accent: the story asks for it in words

# Who each of Phonon's character voices can play: its catalogue gives them no gender, so they are here, from how each
# sounds and its description. A creature (a demon, a dragon, the thing under the stairs) has none: it plays a creature
# or a thing, never a "she" or a "he".
CHARACTER_GENDERS = {
    "Captain Silas Blackwater": "male", "Morwenna of the Deep": "female", "Old Mortlake": "male",
    "Azgorath": "creature", "Fennick the Young Elf": "male", "The Thing Under the Stairs": "creature",
    "Vyrmathrax the Ancient": "creature", "Grub the Ogre": "male", "Master Aldric": "male",
    "The Snow Queen": "female", "Sir Bramwell": "male", "Fairy Godmother": "female",
}
# A cast member's gender as the model may write it, made one of "female", "male" or "any" (a creature, a thing, or a
# storyteller who is no one in the story).
GENDER_WORDS = {"female": "female", "she": "female", "her": "female", "woman": "female", "girl": "female",
                "male": "male", "he": "male", "him": "male", "man": "male", "boy": "male",
                "any": "any", "creature": "any", "thing": "any", "it": "any", "they": "any", "none": "any",
                "neutral": "any"}
VOICE_IS = {"female": "a woman's voice", "male": "a man's voice", "creature": "a creature's voice, with no gender"}
CHOOSE = {"female": "a woman's voice", "male": "a man's voice"}
# The owner's rule, from listening, for a ghost, a witch or a sinister woman: one of Phonon's three women's character
# voices (a deep creature's growl for a girl's ghost was the story that showed it).
CASTING_NOTE = ("Each option's gender is who its voice can play. Give every cast member a gender in make_audio_story: "
                '"female" (she) on a woman\'s voice, "male" (he) on a man\'s, "any" (a creature, a thing, or an outside '
                "storyteller) on any voice; a creature's voice plays only a creature.")
EERIE_NOTE = ("For an eerie woman (a ghost, a witch, a sinister woman), choose The Snow Queen, Morwenna of the Deep or "
              "Fairy Godmother.")


def accents_for(engine: str) -> list[str]:
    """The accents a story can be cast in with this engine's voices: Phonon's English voices are American or British;
    Kokoro has Indian voices too; OpenAI's voices take any of the three as a style line. "phonon" -> ["American",
    "British"]; "kokoro" -> ["American", "British", "Indian"]; an engine with no list -> ["American"]."""
    return ACCENTS.get(engine, ["American"])


def preview_path(engine: str, voice_id: str) -> str:
    """The ▶ preview for a voice, a path the form plays: ("phonon", "Captain Silas Blackwater") ->
    "/api/voice/preview/phonon/Captain%20Silas%20Blackwater"."""
    return f"/api/voice/preview/{engine}/{quote(voice_id, safe='')}"


def option(engine: str, voice_id: str, label: str, note: str, gender: str) -> dict:
    """One voice as a form option, its note cut to the form's 80 characters, with who it can play (voice_gender; the
    form shows no gender, so it is for the model's casting)."""
    return {"value": voice_id, "label": label, "note": note[:NOTE_LIMIT], "gender": gender,
            "preview": preview_path(engine, voice_id)}


def character_gender(voice_id: str) -> str:
    """A Phonon character voice's gender from CHARACTER_GENDERS, by its name in any case: "the snow queen" -> "female";
    "Azgorath" -> "creature"; a voice not in the table (one the user found themselves) -> "any"."""
    for name, gender in CHARACTER_GENDERS.items():
        if name.lower() == voice_id.strip().lower():
            return gender
    return "any"


def voice_gender(engine: str, chosen: dict) -> str:
    """Decides who a voice can play: "female", "male", "creature" (a character voice with no gender), or "any" (a voice
    with nothing to go by: OpenAI's neutral Alloy, a Phonon voice the user found themselves). ("phonon", Harper) ->
    "female"; ("phonon", The Thing Under the Stairs) -> "creature"; ("phonon", Fennick the Young Elf) -> "male";
    ("kokoro", George) -> "male"; ("openai", Alloy) -> "any"."""
    if engine == "phonon":
        gender = chosen.get("gender")
        if gender in ("female", "male"):
            return gender
        return character_gender(chosen["id"])
    group = chosen.get("group", "")
    if group in ("female", "male"):
        return group
    return "any"


def noted(*parts: str) -> str:
    """A note from its parts, the empty ones left out: ("woman", "warm and low") -> "woman · warm and low";
    ("man", "") -> "man"."""
    return " · ".join(part for part in parts if part)


def phonon_options(voices: list[dict], accent: str) -> list[dict]:
    """Phonon's voices for one accent ("British · Female", "British · Male"), each noted with who it is and how it
    sounds, then its Characters group, noted as character voices, for the roles a character voice lifts; each with who
    it can play (voice_gender): "woman · character voice · A regal, cold-hearted queen of ice."."""
    accent_voices = []
    characters = []
    for v in voices:
        group = v.get("group", "")
        note = v.get("note", "")
        gender = voice_gender("phonon", v)
        who = WHO[gender]
        if group.startswith(f"{accent} · "):
            accent_voices.append(option("phonon", v["id"], v["label"], noted(who, note), gender))
        elif group == CHARACTERS:
            characters.append(option("phonon", v["id"], v["label"], noted(who, CHARACTER_NOTE, note), gender))
    return accent_voices + characters


def kokoro_options(accent: str) -> list[dict]:
    """Kokoro's voices with this accent, noted woman or man: "Indian" -> Alpha, Beta (women), Omega, Psi (men)."""
    return [option("kokoro", v["id"], v["label"], WHO[v["group"]], voice_gender("kokoro", v))
            for v in voice.KOKORO_VOICES if v["note"] == accent]


def openai_options() -> list[dict]:
    """Every OpenAI voice: they have no fixed accent, so the story asks for it, and a ▶ plays it without one."""
    return [option("openai", v["id"], v["label"], f"{WHO[v['group']]} · {OPENAI_ACCENT}", voice_gender("openai", v))
            for v in voice.VOICES]


def accent_problem(engine: str, accent: str) -> str | None:
    """Whether an accent can be cast with this engine, as words to fix: ("phonon", "Indian") -> "Phonon's voices here
    are American or British: choose one of those."; ("kokoro", "Indian") -> None."""
    offered = accents_for(engine)
    if accent in offered:
        return None
    return f"{engine_name(engine)}'s voices here are {spoken_list(offered)}: choose one of those."


def engine_name(engine: str) -> str:
    """An engine's name as a sentence says it, without the note in brackets: "phonon" ("Phonon (Ollama)") ->
    "Phonon"; "kokoro" -> "Kokoro"; an engine Odie doesn't list -> its id."""
    engine_info = voice.ENGINES.get(engine, {})
    full_label = engine_info.get("label", engine)
    return full_label.split(" (")[0]


def spoken_list(items: list[str]) -> str:
    """Items as a sentence lists them: ["American"] -> "American"; ["American", "British"] -> "American or British";
    ["American", "British", "Indian"] -> "American, British or Indian"."""
    if len(items) <= 1:
        return "".join(items)
    return f"{', '.join(items[:-1])} or {items[-1]}"


def accent_word(given) -> str:
    """The accent as the user chose it, in its usual spelling: " british" -> "British"; None -> ""."""
    text = chat.text_or_empty(given)
    return text.strip().capitalize()


async def story_voices(accent: str = "") -> dict:
    """The voices for an audio story's cast form, for the voice engine chosen in Settings.
    accent: "American", "British" or "Indian", as the user chose it with the story. Without one, it returns the
    accents this engine offers, for that question, and the one to prefill it with ("default": American).
    Returns {"engine", "accent", "options", "notes"}: options is the voices for that accent (and, on Phonon, its
    character voices: a pirate captain, a witch, an old keeper), each {value, label, note, gender, preview}. Paste
    options exactly as given as the options of every voice select in the cast form, previews and all; use a `value` as
    the voice in make_audio_story. Cast each character on a voice of their gender, as notes says. {"error": …}: choose
    as it says."""
    store = jobs.hooks["store"]
    engine, _chosen = voice.get_tts(store)
    if engine == "phonon":
        await voice.phonon_voices()  # Phonon's voices are known only once Ollama has been asked
    picked = accent_word(accent)
    if not picked:
        return {"engine": engine, "accents": accents_for(engine), "default": DEFAULT_ACCENT}
    problem = accent_problem(engine, picked)
    if problem:
        return {"error": problem}
    if engine == "phonon":
        options = phonon_options(voice.engine_voices("phonon"), picked)
    elif engine == "kokoro":
        options = kokoro_options(picked)
    else:
        options = openai_options()
    notes = CASTING_NOTE
    if engine == "phonon":
        notes = f"{notes} {EERIE_NOTE}"
    return {"engine": engine, "accent": picked, "options": options, "notes": notes}


MIN_MINUTES = 2
MAX_MINUTES = 15
DEFAULT_MINUTES = 5
MAX_SPEAKERS = 8  # the player gives up to eight speakers a tone of their own
WORD = "story"
# The wait told to the user, from real stories on Phonon: the writer took 39–49 s for a 3-minute script, and speaking,
# mixing and mastering a minute of story took a few seconds.
WRITING_SECONDS = 30  # the writer's turn…
WRITING_SECONDS_PER_MINUTE = 5  # …and a little more for each minute of story
LOCAL_SECONDS_PER_MINUTE = 6  # a local voice speaks, and Odie mixes and masters, a minute of story in about this long
OPENAI_SECONDS_PER_MINUTE = 66  # OpenAI speaks about as fast as the story plays, then the mix
ABOUT_A_MINUTE = 90  # a wait up to this many seconds is "about a minute"
DOING = "writing the script and choosing the sound, then speaking every line and mixing it"

NO_GENRE = "genre is the story's genre, as the user chose it (horror, mystery, a bedtime story…)."
NO_PREMISE = "premise is the story's idea: the pitch the user chose, or their own idea, in a sentence or two."
NO_CAST = ('cast is a list of {id, name, voice, gender, age, about}: the narrator and each character, with a voice '
           "from story_voices.")
NO_GENDER = ('{name} needs a gender: "female" (she), "male" (he) or "any" (a creature, a thing, or a storyteller who is '
             "no one in the story).")
VOICES_FROM = "Call story_voices for the voices to choose from."
RICHER_SOUND = '"For richer sound, install iMovie (free in the App Store); Odie uses its sound library."'
NO_SOUNDS = ("There is no iMovie on this Mac, so the story uses Odie's own small sound kit, with no music. Tell the "
             f"user once: {RICHER_SOUND}")
OWN_SOUNDS_ONLY = ("There is no iMovie on this Mac, so the story uses the sounds in the user's own sounds folder. Tell "
                   f"the user once: {RICHER_SOUND}")


def seconds_to_make(minutes: int, engine: str) -> int:
    """About how long a story takes, in seconds: the writing (WRITING_SECONDS and a little a minute), then speaking,
    mixing and mastering (a few seconds a minute on a local voice; about real time on OpenAI). 3 minutes on Phonon ->
    63; 15 on Phonon -> 195; 10 on OpenAI -> 740."""
    writing = WRITING_SECONDS + WRITING_SECONDS_PER_MINUTE * minutes
    making = LOCAL_SECONDS_PER_MINUTE * minutes
    if engine == "openai":
        making = OPENAI_SECONDS_PER_MINUTE * minutes
    return writing + making


def wait_words(minutes: int, engine: str) -> str:
    """The wait as the user is told it (seconds_to_make): up to ABOUT_A_MINUTE -> "about a minute"; longer -> the
    whole minutes around it. 3 minutes on Phonon -> "about a minute"; 15 -> "about 3–4 minutes"; 10 on OpenAI ->
    "about 12–13 minutes"."""
    seconds = seconds_to_make(minutes, engine)
    if seconds <= ABOUT_A_MINUTE:
        return "about a minute"
    low = seconds // 60
    return f"about {low}–{low + 1} minutes"


def library_note(libraries: list[sound_library.Library]) -> str:
    """Decides what the reply adds about where the sound comes from: iMovie's library found -> nothing; only the
    user's own sounds folder -> that it is used, and the iMovie line to say once; nothing at all -> Odie's small kit,
    no music, and the iMovie line. [iLife Sound Effects, Your sounds] -> ""; [Your sounds] -> OWN_SOUNDS_ONLY; [] ->
    NO_SOUNDS."""
    if sound_library.has_imovie(libraries):
        return ""
    if libraries:
        return OWN_SOUNDS_ONLY
    return NO_SOUNDS


def gender_word(given) -> str:
    """A cast member's gender as one of "female", "male" or "any", forgiving the word: "female", " She", "woman",
    "girl" -> "female"; "he", "boy" -> "male"; "creature", "it" -> "any"; "", None or "tall" -> "" (asked for)."""
    word = chat.text_or_empty(given).strip().lower()
    return GENDER_WORDS.get(word, "")


def casting_problem(member: dict, voice_label: str, gender_of_voice: str) -> str | None:
    """Decides whether a voice can play a cast member, by gender: a member of any gender, or a voice with nothing to
    go by ("any"), always fits; otherwise the voice is the member's gender. The ghost girl (female) on Morwenna of
    the Deep -> None; a dragon (any) on Vyrmathrax the Ancient (creature) -> None; the ghost girl on Miles -> "The ghost
    girl is female, but Miles is a man's voice: choose a woman's voice."; on The Thing Under the Stairs -> "… is a
    creature's voice, with no gender: …"; the captain (male) on Harper -> "… Harper is a woman's voice: choose a man's
    voice."."""
    wanted = member["gender"]
    if wanted == "any" or gender_of_voice == "any" or wanted == gender_of_voice:
        return None
    return (f"{member['name']} is {wanted}, but {voice_label} is {VOICE_IS[gender_of_voice]}: choose "
            f"{CHOOSE[wanted]}.")


def plain_cast(cast) -> list[dict] | str:
    """The cast as the model sent it, made plain: each member {id, name, voice, about, gender, age}, the id a plain
    word made from the id or the name ("The Keeper" -> "the-keeper"), the gender one of female, male or any
    (gender_word), the age a word if given ("old", "a girl"). The problem in words instead when it can't be: not a
    list, a member without a name, a voice or a gender, too many speakers, or two with one id."""
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
        gender = gender_word(given.get("gender"))
        if not gender:
            return NO_GENDER.format(name=name)
        about = chat.text_or_empty(given.get("about")).strip()
        age = chat.text_or_empty(given.get("age")).strip()
        members.append({"id": member_id, "name": name, "voice": chosen_voice, "about": about, "gender": gender,
                        "age": age})
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
    return (f"sound_level is how loud the ambience is when no one speaks, from {story.LOWEST_SOUND_LEVEL} to "
            f"{story.HIGHEST_SOUND_LEVEL} ({story.DEFAULT_SOUND_LEVEL} unless the user chose), not {level}.")


def checked_voices(store, engine: str, cast: list[dict]) -> list[dict] | str:
    """Each member's voice checked in the engine chosen in Settings, by id or label, and kept as its id, with how fast
    that voice reads (Phonon's character voices are slower); the problem in words for the first that isn't there:
    "The keeper's voice: 'marin' isn't one of Kokoro's voices… Call story_voices for the voices to choose from.", or
    that can't play the member (casting_problem), with the owner's three voices for a woman on Phonon (EERIE_NOTE)."""
    checked = []
    for member in cast:
        try:
            chosen = voice.voice_in_chosen_engine(store, member["voice"])
        except ValueError as e:
            return f"{member['name']}'s voice: {e} {VOICES_FROM}"
        problem = casting_problem(member, chosen["label"], voice_gender(engine, chosen))
        if problem and engine == "phonon" and member["gender"] == "female":
            problem = f"{problem} {EERIE_NOTE}"
        if problem:
            return problem
        pace = story_writer.words_per_minute(engine, chosen.get("group", ""))
        checked.append({**member, "voice": chosen["id"], "pace": pace})
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


async def make_audio_story(title: str, genre: str, premise: str, cast: list[dict], narrator: str,
                           accent: str = DEFAULT_ACCENT, minutes: int = 5, sound_level: int = 25, brief: str = "",
                           tool_context: ToolContext | None = None) -> dict:
    """Make the audio story the user chose in the guided start: a narrator, character voices, ambience, effects and
    music, posted to this chat as one file. Call it once, after the cast form. A separate writer writes the script and
    chooses the sound in the background; it sees only what you pass here.
    title: the story's title (short). genre: as the user chose it ("horror"). premise: the pitch or idea they chose,
    a sentence or two.
    cast: [{id, name, voice, gender, age, about}] for the narrator and each character: id a short plain word
    ("keeper"), name as the listener knows them ("The keeper"), voice a value from story_voices of their gender,
    gender "female" (she), "male" (he) or "any" (a creature, a thing, an outside storyteller), age a word if it
    matters ("old", "a girl"), about one line on who they are.
    narrator: the id of who tells it: "narrator" for an outside storyteller (then in the cast as id "narrator"), or a
    character's id to tell it in the first person.
    accent: as chosen ("American", unless the user chose British or Indian). minutes: 2 to 15 (the user's length, else 5). sound_level: 10 to 40, how loud the
    ambience is when no one speaks; it drops lower under the voices (the slider's value, else 25). brief: anything else the user asked for (tone, an
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
    if not picked_accent:
        picked_accent = DEFAULT_ACCENT
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
    result = chat.reply_in_words(place, wait_words(minutes, engine), DOING)
    note = library_note(sound_library.find_libraries(sound_library.LIBRARY_ROOT))
    if note:
        result = f"{result} {note}"
    return {"result": result}


TOOLS = [FunctionTool(story_voices), FunctionTool(make_audio_story)]
