"""The sounds an audio story can use: the ones installed with iMovie on the user's Mac, and a folder of the user's
own, read into one catalogue of loops (beds that run under a scene), hits (played once) and music.

Odie uses these sounds where they already are, on the user's own Mac. It never copies them into the repo and never
uploads them anywhere; a finished story is the user's own file, and sharing it is their choice.

Without iMovie or a sounds folder, the video kit's own synthesized sounds (odie/video/kit/sounds, CC0) stand in, and
there is no music. The catalogue is built the first time a story needs it (never at Odie's start) and cached as JSON
in Odie's data folder, built again when a library's files change."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
from dataclasses import dataclass
from pathlib import Path

from odie.making.chat import slug_of
from odie.video.encode import probe

log = logging.getLogger("odie.making.sound_library")

# Where iMovie keeps its sounds. Another Mac layout is a change to these lines only.
LIBRARY_ROOT = Path("/Applications/iMovie.app/Contents/Resources")
ILIFE_EFFECTS_FOLDER = "iLife Sound Effects"  # <Category>/*.caf: Ambience, Animals, Jingles, Stingers, …
IMOVIE_EFFECTS_FOLDER = "iMovie Sound Effects"  # *.mp3, one folder
THEME_MUSIC_FOLDER = "iMovie Theme Music"  # *.m4a, one folder
OWN_FOLDER = "sounds"  # <ODIE_HOME>/sounds/, any subfolders as categories
OWN_CATEGORY = "Your sounds"  # a sound right inside the user's folder, in no subfolder
AUDIO_SUFFIXES = (".caf", ".mp3", ".m4a", ".wav", ".aif", ".aiff")
CACHE_FILE = "sound-library.json"
RULES_VERSION = 2  # raised when kind_of or build changes, so a cached catalogue is built again with the new rules
PROBES_AT_ONCE = 8  # ffmpeg reads of durations run side by side, at most this many

MUSIC_CATEGORIES = {"Jingles", "Theme Music"}
LOOP_CATEGORIES = {"Ambience"}  # beds, unless the name says it plays once (a thunder clap)
HIT_CATEGORIES = {"Stingers", "Booms"}  # played once, however long
LOOP_SECONDS = 8.0  # in any other category, a sound this long or longer can run under a scene
BED_WORD_SECONDS = 4.0  # a sound whose name says it's a bed (a crowd, rain) is one from this long
BED_WORDS = ("crowd", "ambience", "ambient", "room tone", "traffic", "rain", "wind", "rumble", "hum", "drone", "forest",
             "jungle", "ocean", "surf", "stream", "river", "fire", "night", "engine", "idle")
# Whole words in a name that make a sound an event, played once however long the file is: a bell tower tolls, a phone
# rings, an accent is a short musical sting, a jet flies by (looped under a scene, a pass-by would repeat).
HIT_WORDS = {"accent", "accents", "clap", "strike", "ring", "ringing", "bell", "knock", "slam", "fly", "pass",
             "passing", "sweep"}
# Sounds the rules above get wrong, found on a real iMovie library: (category, name in lower case) -> kind.
OVERRIDES: dict[tuple[str, str], str] = {
    ("Transportation", "car horn"): "hit",
    ("People", "crowd cheer"): "hit",
    ("Effects", "chicken"): "hit",  # 30 s of one hen: a moment, not a farmyard
    ("Effects", "basketball bounce"): "hit",
    ("Effects", "bottle pour"): "hit",
    ("Work - Home", "telephone number change"): "hit",  # a recorded message
}

LISTING_TOKENS = 4000  # the writer's listing stays under this many tokens (4 characters a token)
# The categories the writer reads first, most useful for a story's atmosphere first; a category not named here (the
# user's own folders) comes before all of them.
CATEGORY_ORDER = ["Ambience", "Textures", "Animals", "Foley", "People", "Transportation", "Machines", "Stingers",
                  "Jingles", "Theme Music", "Booms", "Sci-Fi", "Sports", "Work - Home", "Effects", "Kit"]
CUTS = ("long", "medium", "short")
CUT_NAME = re.compile(r"^(.*?)[\s_-]*\(?\b(long|medium|short)\)?$", re.IGNORECASE)


@dataclass(frozen=True)
class Library:
    """One folder of sounds. Each subfolder is a category; a sound right inside the folder is in `category`."""
    name: str
    folder: Path
    category: str


def own_sounds_folder() -> Path:
    """The user's own sounds folder: <ODIE_HOME>/sounds, or <data folder>/sounds when the folders are set directly
    with no home around them (ODIE_DATA_DIR without ODIE_HOME). ~/.odie -> ~/.odie/sounds; ODIE_DATA_DIR=/x/data
    alone -> /x/data/sounds."""
    from odie import config
    if config.settings.home is not None:
        return config.settings.home / OWN_FOLDER
    return config.settings.data_dir / OWN_FOLDER


def find_libraries(root: Path = LIBRARY_ROOT, own: Path | None = None) -> list[Library]:
    """The sound folders on this Mac, in order: iMovie's effects, its sound effects and its theme music, then the
    user's own folder; only the ones that exist. A Mac without iMovie and no sounds folder -> []."""
    own_folder = own if own is not None else own_sounds_folder()
    candidates = [
        Library(ILIFE_EFFECTS_FOLDER, root / ILIFE_EFFECTS_FOLDER, "Effects"),
        Library(IMOVIE_EFFECTS_FOLDER, root / IMOVIE_EFFECTS_FOLDER, "Effects"),
        Library(THEME_MUSIC_FOLDER, root / THEME_MUSIC_FOLDER, "Theme Music"),
        Library(OWN_CATEGORY, own_folder, OWN_CATEGORY),
    ]
    return [library for library in candidates if library.folder.is_dir()]


def has_imovie(libraries: list[Library]) -> bool:
    """Decides whether iMovie's sounds are among the libraries found: any of its folders -> True; only the user's own
    sounds folder, or nothing -> False (the story falls back to Odie's kit, with no music)."""
    return any(library.name != OWN_CATEGORY for library in libraries)


def kind_of(category: str, name: str, seconds: float) -> str:
    """Decides how a sound can be used: "loop" (a bed that runs under a scene), "hit" (played once) or "music". The
    small OVERRIDES table first; then the category: Jingles and Theme Music are music, Stingers and Booms hits; then a
    name with a HIT_WORDS word is a hit (a bell, a ring, a clap, an accent), whatever its length; then Ambience is a
    loop; anything else goes by name and length: a name that says it's a bed (a crowd, rain, wind) is a loop from 4
    seconds, any other sound from 8.
    ("Ambience", "Ocean Surf", 60) -> "loop"; ("Ambience", "Thunder Clap", 12.8) -> "hit"; ("Jingles", …) -> "music";
    ("Textures", "Suspense Accents 01", 1.2) -> "hit"; ("Foley", "Footsteps", 12.6) -> "loop"; ("Foley", "Door Wood
    Squeak", 2.1) -> "hit"; ("Effects", "Bell Tower", 9.7) -> "hit"; ("Animals", "Bark", 2) -> "hit"; ("People",
    "Crowd Murmur", 5) -> "loop"."""
    lowered = name.lower()
    overridden = OVERRIDES.get((category, lowered))
    if overridden:
        return overridden
    if category in MUSIC_CATEGORIES:
        return "music"
    if category in HIT_CATEGORIES:
        return "hit"
    name_words = set(re.findall(r"[a-z]+", lowered))
    if name_words & HIT_WORDS:
        return "hit"
    if category in LOOP_CATEGORIES:
        return "loop"
    sounds_like_a_bed = any(word in lowered for word in BED_WORDS)
    if sounds_like_a_bed and seconds >= BED_WORD_SECONDS:
        return "loop"
    if seconds >= LOOP_SECONDS:
        return "loop"
    return "hit"


def cut_of(name: str) -> tuple[str, str | None]:
    """A sound's name without its cut, and the cut (iMovie's jingles come Long, Medium and Short): "Acoustic Sunrise
    Medium" -> ("Acoustic Sunrise", "medium"); "Acoustic Sunrise (Short)" -> ("Acoustic Sunrise", "short"); "Ocean
    Surf" -> ("Ocean Surf", None)."""
    found = CUT_NAME.match(name.strip())
    if found is None or not found.group(1).strip():
        return name.strip(), None
    return found.group(1).strip(), found.group(2).lower()


def sound_files(library: Library) -> list[tuple[str, Path]]:
    """Every sound in a library with its category: (subfolder name or the library's own category, the file)."""
    found = []
    for path in sorted(library.folder.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in AUDIO_SUFFIXES:
            continue
        relative = path.relative_to(library.folder)
        category = relative.parts[0] if len(relative.parts) > 1 else library.category
        found.append((category, path))
    return found


def signature(libraries: list[Library]) -> str:
    """What the libraries hold, as one short text that changes when a file is added, removed or changed, or when the
    rules that read them (RULES_VERSION) change."""
    digest = hashlib.sha1(f"rules {RULES_VERSION}\n".encode())
    for library in libraries:
        for _category, path in sound_files(library):
            stat = path.stat()
            digest.update(f"{path}|{stat.st_mtime_ns}|{stat.st_size}\n".encode())
    return digest.hexdigest()


async def durations(paths: list[Path]) -> dict[Path, float]:
    """Each file's length in seconds, read with ffmpeg (there is no ffprobe), a few at a time."""
    gate = asyncio.Semaphore(PROBES_AT_ONCE)

    async def one(path: Path) -> tuple[Path, float]:
        async with gate:
            facts = await probe(path)
        return path, float(facts["seconds"])
    return dict(await asyncio.gather(*(one(p) for p in paths)))


async def build(libraries: list[Library]) -> list[dict]:
    """One entry per sound, {id, name, category, kind, seconds, path, variants}: a jingle's Long, Medium and Short cuts
    are one entry (the longest cut leads, the cuts in `variants`). A file ffmpeg can't read (no length) is left out."""
    files = [(category, path) for library in libraries for category, path in sound_files(library)]
    seconds = await durations([path for _category, path in files])
    grouped: dict[tuple[str, str], list[dict]] = {}
    for category, path in files:
        if seconds[path] <= 0:
            log.info("sound library: %s can't be read; left out", path)
            continue
        name, cut = cut_of(path.stem)
        grouped.setdefault((category, name), []).append({"cut": cut, "seconds": round(seconds[path], 2), "path": str(path)})

    entries = []
    taken: set[str] = set()
    for (category, name), cuts in grouped.items():
        cuts.sort(key=lambda c: CUTS.index(c["cut"]) if c["cut"] in CUTS else -1)
        lead = cuts[0]
        variants = [c for c in cuts if c["cut"]]
        entry_id = unique_id(f"{slug_of(category, 'sounds')}/{slug_of(name, 'sound')}", taken)
        entries.append({"id": entry_id, "name": name, "category": category, "kind": kind_of(category, name, lead["seconds"]),
                        "seconds": lead["seconds"], "path": lead["path"], "variants": variants})
    return entries


def unique_id(wanted: str, taken: set[str]) -> str:
    """The id, or with -2, -3… when another sound already has it."""
    candidate = wanted
    number = 2
    while candidate in taken:
        candidate = f"{wanted}-{number}"
        number += 1
    taken.add(candidate)
    return candidate


def kit_catalogue() -> list[dict]:
    """The video kit's sounds as a catalogue, for a Mac with no sound library: loops and hits, no music."""
    from odie.video import sounds
    entries = []
    for sound in sounds.SOUNDS.values():
        entries.append({"id": f"kit/{sound.name}", "name": sound.name, "category": "Kit", "kind": sound.kind,
                        "seconds": sound.seconds, "path": str(sounds.path(sound.name)), "variants": []})
    return entries


async def catalogue(libraries: list[Library] | None = None, cache_file: Path | None = None) -> list[dict]:
    """The sounds a story can use. Read from the cache while the libraries hold the same files; built (and cached)
    again when they change. No library, or nothing readable in them -> the video kit's sounds."""
    from odie import config
    found = find_libraries() if libraries is None else libraries
    if not found:
        return kit_catalogue()
    cache = cache_file or (config.settings.data_dir / CACHE_FILE)
    now = signature(found)
    try:
        cached = json.loads(cache.read_text())
    except (OSError, ValueError):
        cached = {}
    if cached.get("signature") == now and cached.get("entries"):
        return cached["entries"]
    entries = await build(found)
    if not entries:
        return kit_catalogue()
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"signature": now, "entries": entries}))
    return entries


def seconds_text(seconds: float) -> str:
    """A length as the listing shows it: 12.03 -> "12s"; 6.0 -> "6s"; 0.8 -> "0.8s"."""
    if seconds >= 10:
        return f"{round(seconds)}s"
    shown = f"{seconds:.1f}".removesuffix(".0")
    return f"{shown}s"


def category_rank(category: str) -> int:
    """Where a category comes in the writer's listing: the user's own folders first (-1), then CATEGORY_ORDER, then
    anything else. "Your sounds" or a folder of theirs -> -1; "Ambience" -> 0; "Effects" -> 14."""
    if category in CATEGORY_ORDER:
        return CATEGORY_ORDER.index(category)
    return -1


def summary_line(category: str, entries: list[dict]) -> str:
    """A category too big to list in full, in one line with three ids to show the shape: "Effects: 95 sounds (40 loops,
    55 hits), not listed in full; for example effects/a, effects/b, effects/c." """
    counts: dict[str, int] = {}
    for e in entries:
        counts[e["kind"]] = counts.get(e["kind"], 0) + 1
    kinds = ", ".join(f"{n} {kind}s" for kind, n in sorted(counts.items()))
    examples = ", ".join(e["id"] for e in entries[:3])
    return f"{category}: {len(entries)} sounds ({kinds}), not listed in full; for example {examples}."


def writer_listing(entries: list[dict]) -> str:
    """The sounds as the writer reads them, grouped by category, one short line each ("ambience/ocean-surf · 60s ·
    loop"). The most useful categories come first and in full; once the next one in full wouldn't leave room under
    LISTING_TOKENS, the rest are summed up in a line each. Without music (the kit), it says so."""
    by_category: dict[str, list[dict]] = {}
    for e in entries:
        by_category.setdefault(e["category"], []).append(e)
    order = sorted(by_category, key=category_rank)
    intro = ("Sounds you can use, by category: id · seconds · loop (a bed under a scene), hit (once) or music. Use the ids "
             "exactly as written.")
    head = [intro]
    if not any(e["kind"] == "music" for e in entries):
        head.append("There is no music here (no iMovie on this Mac): don't add music beds.")
    budget = LISTING_TOKENS * 4
    used = sum(len(line) + 1 for line in head)
    summaries = {c: summary_line(c, by_category[c]) for c in order}
    parts: list[str] = []
    for i, category in enumerate(order):
        full = "\n".join([f"{category}:"] + [f"{e['id']} · {seconds_text(e['seconds'])} · {e['kind']}" for e in by_category[category]])
        rest = sum(len(summaries[c]) + 1 for c in order[i + 1:])
        fits = used + len(full) + 1 + rest <= budget
        chosen = full if fits else summaries[category]
        parts.append(chosen)
        used += len(chosen) + 1
    return "\n".join(head + parts)
