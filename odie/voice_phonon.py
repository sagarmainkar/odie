"""Phonon's English voices (phonon:latest), as the catalogue describes them (gradium/phonon-voices on Hugging Face,
Apache 2.0): each voice's name, its accent (en-us, en-gb) or "characters", its gender, and a sentence about how it
sounds. It only labels and groups the voices: what Ollama lists stays the truth for what can be chosen (odie.voice).

Groups, in the order the picker shows them: American and British voices by gender, the characters, then any voice
Ollama lists that the catalogue doesn't know ("Other"), then the voices the user found with "Another voice".
"""
from __future__ import annotations

GROUPS = ["American · Female", "American · Male", "British · Female", "British · Male", "Characters", "Other", "Your voices"]
OTHER = "Other"
YOURS = "Your voices"
NOTE_LIMIT = 70
_ACCENTS = {"en-us": "American", "en-gb": "British"}

CATALOGUE: list[dict] = [
    {"name": "Zoey", "locale": "en-us", "gender": "female", "note": "Playful, upbeat and Gen Z energy voice with a standard American accent."},
    {"name": "Juniper", "locale": "en-us", "gender": "female", "note": "Cheerful presence with real resonance under it, personable when the copy turns intimate and decisive on the final line."},
    {"name": "Everly", "locale": "en-us", "gender": "female", "note": "Rounded, soft-edged tone with gentle lift at the end of phrases and an easy, relaxed delivery."},
    {"name": "Harper", "locale": "en-us", "gender": "female", "note": "Modern, confident and friendly voice with a standard American accent."},
    {"name": "Hadley", "locale": "en-us", "gender": "female", "note": "Settled, even-toned and genuinely kind, with crisp consonants that hold up over a handset."},
    {"name": "Delia", "locale": "en-us", "gender": "female", "note": "Low, grounded and quick to the point, with a sincerity that keeps an apology honest."},
    {"name": "Easton", "locale": "en-us", "gender": "male", "note": "Punchy and close in, with crisp consonant attack that cuts through a music bed and pitch that lifts across each line."},
    {"name": "Micah", "locale": "en-us", "gender": "male", "note": "Buoyant and high in energy, with a playful lift at the ends of phrases and clean attack that survives a loud mix."},
    {"name": "Trevor", "locale": "en-us", "gender": "male", "note": "Buoyant energy over a resonant mid-low core, phrases landing softly and consonants cutting through a handset."},
    {"name": "Russell", "locale": "en-us", "gender": "male", "note": "A high-energy American adult voice that pushes and encourages with the intensity of someone who genuinely believes in you."},
    {"name": "Preston", "locale": "en-us", "gender": "male", "note": "Trim, focused delivery with clean edges on every consonant and a steady, low-set core that carries through phone bandwidth."},
    {"name": "Miles", "locale": "en-us", "gender": "male", "note": "Resonant and decisive, with genuine dynamic range, dropping right down for one clause then driving back up."},
    {"name": "Maeve", "locale": "en-gb", "gender": "female", "note": "A sparky, attentive British English adult voice that gets to the point with a smile."},
    {"name": "Freya", "locale": "en-gb", "gender": "female", "note": "A young British voice, glossy and confident with fast, girly chatter and bubbly sparkle, perfect for a friendly receptionist or assistant."},
    {"name": "Pippa", "locale": "en-gb", "gender": "female", "note": "A confident, upbeat British English adult voice with infectious energy."},
    {"name": "Elodie-Rose", "locale": "en-gb", "gender": "female", "note": "A young British voice with sharp, enthusiastic energy and crisp articulation, sparky and to the point for customer support and care."},
    {"name": "Imogen", "locale": "en-gb", "gender": "female", "note": "A bubbly, friendly British English adult voice that puts callers instantly at ease."},
    {"name": "Lottie", "locale": "en-gb", "gender": "female", "note": "Sparky and to the point, high forward energy with clean edges on the consonants and the range to drop low for one line then climb back."},
    {"name": "Alfie", "locale": "en-gb", "gender": "male", "note": "Punchy and forward, with crisp consonant attack and a pitch that lifts across a line, sitting high over a music bed."},
    {"name": "Hugh", "locale": "en-gb", "gender": "male", "note": "Soft and close, airy in texture, with lively pitch movement and an attentive, sincere delivery."},
    {"name": "Edwin", "locale": "en-gb", "gender": "male", "note": "Efficient and firm, sincere in attention, with tidy articulation that holds up at phone bandwidth."},
    {"name": "Spencer", "locale": "en-gb", "gender": "male", "note": "Light and airy, sitting a touch higher, with crisp consonants and a slow, patient delivery."},
    {"name": "Toby", "locale": "en-gb", "gender": "male", "note": "A sparky, attentive British English adult voice that gets to the point with a smile."},
    {"name": "Teddy", "locale": "en-gb", "gender": "male", "note": "Sparky and close in, quick off the mark, with firm consonants and the range to drop right down for a clause then come back up."},
    {"name": "Bryony", "locale": "en-gb", "gender": "female", "note": "Full, rich mid-range tones, softly relaxed and spoken close to the mic, moving briskly with light pitch play."},
    {"name": "Captain Silas Blackwater", "locale": "characters", "gender": None, "note": "An old British pirate captain from the West Country, around sixty."},
    {"name": "Morwenna of the Deep", "locale": "characters", "gender": None, "note": "A sultry, seductive woman in her thirties."},
    {"name": "Old Mortlake", "locale": "characters", "gender": None, "note": "An elderly gravedigger in a Victorian churchyard."},
    {"name": "Azgorath", "locale": "characters", "gender": None, "note": "An enormous ancient demon."},
    {"name": "Fennick the Young Elf", "locale": "characters", "gender": None, "note": "A curious, kind-hearted elf boy of about ten."},
    {"name": "The Thing Under the Stairs", "locale": "characters", "gender": None, "note": "A monstrous creature lurking in the dark."},
    {"name": "Vyrmathrax the Ancient", "locale": "characters", "gender": None, "note": "An ancient dragon, thousands of years old."},
    {"name": "Grub the Ogre", "locale": "characters", "gender": None, "note": "A big, good-natured ogre who lives under a bridge."},
    {"name": "Master Aldric", "locale": "characters", "gender": None, "note": "A wise old British wizard, around eighty."},
    {"name": "The Snow Queen", "locale": "characters", "gender": None, "note": "A regal, cold-hearted queen of ice."},
    {"name": "Sir Bramwell", "locale": "characters", "gender": None, "note": "A brave but pompous English knight, middle-aged."},
    {"name": "Fairy Godmother", "locale": "characters", "gender": None, "note": "A kind fairy godmother, an older woman in her sixties."},
]
_BY_NAME = {v["name"].lower(): v for v in CATALOGUE}


def entry(name: str) -> dict | None:
    """The catalogue's entry for a voice name, in any case (Ollama matches names that way): "zoey" -> Zoey's entry;
    "Someone New" -> None."""
    return _BY_NAME.get(name.strip().lower())


def group_of(name: str) -> str:
    """Which heading a voice goes under. An American or British voice by its accent and gender, a character voice under
    "Characters", a name the catalogue doesn't know under "Other". "Zoey" -> "American · Female"; "Alfie" -> "British
    · Male"; "Captain Silas Blackwater" -> "Characters"; "Someone New" -> "Other"."""
    known = entry(name)
    if known is None:
        return OTHER
    if known["locale"] == "characters":
        return "Characters"
    accent = _ACCENTS.get(known["locale"])
    if accent is None or not known["gender"]:
        return OTHER
    return f"{accent} · {known['gender'].capitalize()}"


def short_note(note: str, limit: int = NOTE_LIMIT) -> str:
    """A catalogue sentence short enough for the picker: as it is when it fits in `limit` characters, else cut at the
    last whole word that fits with "…" after it. Zoey's 71-character sentence -> "Playful, upbeat and Gen Z energy voice
    with a standard American…"; "Settled and kind." -> as it is."""
    if len(note) <= limit:
        return note
    room = note[: limit - 1]  # one character for the "…"
    cut = room.rfind(" ")
    if cut > 0:
        room = room[:cut]
    return room.rstrip(" ,;:.—-") + "…"


def describe(name: str) -> dict:
    """What the picker shows about a voice Ollama lists: its group, a short note and its gender (None for a character or
    a voice the catalogue doesn't know). "Zoey" -> {"group": "American · Female", "note": "Playful, upbeat…",
    "gender": "female"}."""
    known = entry(name)
    note = short_note(known["note"]) if known else ""
    gender = known["gender"] if known else None
    return {"group": group_of(name), "note": note, "gender": gender}


def ordered(voices: list[dict]) -> list[dict]:
    """Voices in the picker's order: by GROUPS, and within a group in the order Ollama listed them."""
    rank = {group: i for i, group in enumerate(GROUPS)}
    return sorted(voices, key=lambda v: rank.get(v["group"], len(GROUPS)))
