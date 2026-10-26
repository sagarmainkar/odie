"""The audio-story skill's tools. story_voices gives the chat model the voices for the story's cast form, already shaped
as form options (value, label, note, and a ▶ preview), for the engine chosen in Settings and the accent the user picked,
so the model never builds forty options by hand or guesses a voice id. Plain trusted code of a built-in skill: no
shell, no approval card."""
from urllib.parse import quote

from google.adk.tools import FunctionTool

from odie import voice
from odie.making import jobs

ACCENTS = {"phonon": ["American", "British"], "kokoro": ["American", "British", "Indian"],
           "openai": ["American", "British", "Indian"]}
NOTE_LIMIT = 80  # a form option's note is cut at 80 characters
WHO = {"female": "woman", "male": "man", "neutral": "neutral"}
CHARACTERS = "Characters"  # Phonon's group of character voices (a pirate captain, a witch, an old keeper)
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


def phonon_options(voices: list[dict], accent: str) -> tuple[list[dict], list[dict]]:
    """Phonon's voices for one accent ("British · Female", "British · Male"), each noted with who it is and how it
    sounds, and its Characters group on its own, for the roles a character voice lifts."""
    accent_voices = []
    characters = []
    for v in voices:
        group = v.get("group", "")
        if group.startswith(f"{accent} · "):
            who = WHO.get(v.get("gender") or "", "voice")
            accent_voices.append(option("phonon", v["id"], v["label"], f"{who} · {v.get('note', '')}".rstrip(" ·")))
        elif group == CHARACTERS:
            characters.append(option("phonon", v["id"], v["label"], v.get("note", "")))
    return accent_voices, characters


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


async def story_voices(accent: str = "") -> dict:
    """The voices for an audio story's cast form, for the voice engine chosen in Settings. Call it before the cast
    form; put the options straight into its selects.
    accent: "American", "British" or "Indian" (what the user chose). Without one, it returns the accents this engine
    offers, for the accent question.
    Returns {"engine", "accent", "voices": form options for that accent, "characters": Phonon's character voices (a
    pirate captain, a witch, an old keeper; [] on other engines)}. Each option is {value, label, note, preview}: use
    `value` as the voice in make_audio_story. {"error": …}: choose as it says."""
    store = jobs.hooks["store"]
    engine, _chosen = voice.get_tts(store)
    if engine == "phonon":
        await voice.phonon_voices()  # Phonon's voices are known only once Ollama has been asked
    picked = (accent or "").strip().capitalize()
    if not picked:
        return {"engine": engine, "accents": accents_for(engine)}
    problem = accent_problem(engine, picked)
    if problem:
        return {"error": problem}
    characters: list[dict] = []
    if engine == "phonon":
        voices, characters = phonon_options(voice.engine_voices("phonon"), picked)
    elif engine == "kokoro":
        voices = kokoro_options(picked)
    else:
        voices = openai_options()
    return {"engine": engine, "accent": picked, "voices": voices, "characters": characters}


TOOLS = [FunctionTool(story_voices)]
