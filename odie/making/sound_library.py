"""The sounds an audio story can use: the ones installed with iMovie on the user's Mac, and a folder of the user's
own, read into one catalogue of loops (beds that run under a scene), hits (played once) and music.

Odie uses these sounds where they already are, on the user's own Mac. It never copies them into the repo and never
uploads them anywhere; a finished story is the user's own file, and sharing it is their choice.

Without iMovie or a sounds folder, the video kit's own synthesized sounds (odie/video/kit/sounds, CC0) stand in, and
there is no music. The catalogue is built the first time a story needs it (never at Odie's start) and cached as JSON
in Odie's data folder, built again when a library's files change.

Music carries mood and style words (music_moods.json, next to this file), so a writer that can't hear can choose it by
feel; a moods.json in the user's sounds folder wins over them (with_moods)."""
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

# Mood words for music. A model that listens (LAION CLAP) put three mood words and two style words on each of iMovie's
# 113 tracks: it scored three 10-second windows of a track against 26 mood and 16 style phrases, and ranked each word
# against its own average over the whole library, so a track gets the words it fits better than the other tracks do.
# They are our own words (no audio), keyed by the track's folder and file ("Jingles/Borealis.caf"), the same on every
# Mac. A moods.json in the user's sounds folder, in the same shape, wins over them, and can tag the user's own sounds.
SHIPPED_MOODS = Path(__file__).with_name("music_moods.json")
OWN_MOODS_FILE = "moods.json"

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

LISTING_TOKENS = 4000  # the writer's listing stays under this many tokens…
CHARS_PER_TOKEN = 2.85  # …counted at the rate of its ids, full of hyphens: the real listing with music's mood words is
# 10,774 characters and 3,640 tokens (tiktoken cl100k), 2.96 a token; its ids alone are about 2.85
KIND_LABELS = {"loop": "loops", "hit": "hits", "music": "music"}
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


def words_list(given) -> bool:
    """Whether a tag file's value is a list of words: ["eerie", "dark"] -> True; [] -> True; "eerie" -> False."""
    return isinstance(given, list) and all(isinstance(word, str) for word in given)


def read_tags(path: Path) -> dict[str, dict]:
    """The tags in a moods file, {"<folder>/<file>" or "<file>": {"moods": [...], "styles": [...]}}. A missing or broken
    file -> {} (a log line for a broken one); an entry whose moods aren't a list of words is left out; styles are
    optional; any other key (the shipped file's "_about") is skipped. {"_about": "…", "Jingles/Borealis.caf":
    {"moods": ["eerie"]}} -> {"Jingles/Borealis.caf": {"moods": ["eerie"], "styles": []}}."""
    try:
        given = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        log.info("sound library: %s can't be read as tags; left out", path)
        return {}
    if not isinstance(given, dict):
        return {}
    tags = {}
    for key, value in given.items():
        if not isinstance(value, dict) or not words_list(value.get("moods")):
            continue
        styles = value.get("styles", [])
        if not words_list(styles):
            styles = []
        tags[key] = {"moods": list(value["moods"]), "styles": list(styles)}
    return tags


def track_keys(entry: dict) -> list[str]:
    """The keys a sound's tags can be under, for each of its files (a jingle's every cut): its folder and file, then
    the file alone. "…/Jingles/Borealis Long.caf" with a Short cut -> ["Jingles/Borealis Long.caf", "Borealis Long.caf",
    "Jingles/Borealis Short.caf", "Borealis Short.caf"]."""
    files = [entry["path"]] + [variant["path"] for variant in entry.get("variants", [])]
    keys = []
    for file in files:
        path = Path(file)
        for key in (f"{path.parent.name}/{path.name}", path.name):
            if key not in keys:
                keys.append(key)
    return keys


def tags_for(entry: dict, tags: dict[str, dict]) -> dict | None:
    """Decides which tags in one moods file are a sound's: the first of its track_keys the file has, else None.
    Borealis (Long and Short cuts) with {"Borealis Short.caf": …} -> those tags; with only "Jingles/Other.caf" ->
    None."""
    for key in track_keys(entry):
        if key in tags:
            return tags[key]
    return None


def mood_files() -> list[Path]:
    """The moods files, the one that wins last: Odie's own words for iMovie's music, then the user's moods.json."""
    return [SHIPPED_MOODS, own_sounds_folder() / OWN_MOODS_FILE]


def with_moods(entries: list[dict], files: list[Path]) -> list[dict]:
    """The catalogue with each tagged sound's "moods" and "styles" added, from the moods files; a sound in more than one
    takes the last file's (the user's own tags win over the shipped ones, track by track). An untagged sound is left as
    it is. Borealis, shipped as eerie and the user's as calm -> calm."""
    every_file = [read_tags(file) for file in files]
    tagged = []
    for entry in entries:
        found = None
        for tags in reversed(every_file):
            found = tags_for(entry, tags)
            if found:
                break
        if found:
            entry = {**entry, "moods": found["moods"], "styles": found["styles"]}
        tagged.append(entry)
    return tagged


async def catalogue(libraries: list[Library] | None = None, cache_file: Path | None = None) -> list[dict]:
    """The sounds a story can use, music with its mood words (with_moods, read each time so a change to the user's
    moods.json counts at once). Read from the cache while the libraries hold the same files; built (and cached) again
    when they change. No library, or nothing readable in them -> the video kit's sounds."""
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
        return with_moods(cached["entries"], mood_files())
    entries = await build(found)
    if not entries:
        return kit_catalogue()
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps({"signature": now, "entries": entries}))
    return with_moods(entries, mood_files())


def listing_seconds(seconds: float) -> str:
    """A length as the listing shows it, in whole seconds and never 0: 62.5 -> "62"; 9.6 -> "10"; 0.3 -> "1"."""
    return str(max(1, round(seconds)))


def prefix_and_name(sound_id: str) -> tuple[str, str]:
    """A sound id split where the listing splits it: "ambience/ocean-surf" -> ("ambience/", "ocean-surf")."""
    prefix, _slash, name = sound_id.partition("/")
    return f"{prefix}/", name


def style_of(entry: dict) -> str:
    """A sound's first style word, the one its music is grouped under in the listing, written as one word: ["synth
    pads", "ambient drone"] -> "synth-pads"; no styles -> ""."""
    styles = entry.get("styles") or []
    if not styles:
        return ""
    return styles[0].replace(" ", "-")


def music_words(entry: dict) -> str:
    """A piece of music as the listing gives it: its name and its moods. Borealis, eerie, melancholy and dreamy ->
    "borealis eerie/melancholy/dreamy"; untagged -> "borealis"."""
    _prefix, name = prefix_and_name(entry["id"])
    moods = entry.get("moods") or []
    if not moods:
        return name
    return f"{name} {'/'.join(moods)}"


def is_recent(entry: dict, recent: set[str]) -> bool:
    """Decides whether the listing marks a sound as used in the user's recent stories: its id among their beds and
    music. Borealis with {"jingles/borealis"} -> True; Dewdrops -> False."""
    return entry["id"] in recent


def sound_words(entry: dict, recent: set[str]) -> str:
    """One sound as its line lists it: a loop or a hit with its seconds ("ocean-surf 62"), music with its moods
    (music_words), the moods of a tagged loop or hit after its seconds ("low-hum 9 eerie/dark"), and RECENT_MARK after
    one used in a recent story ("ocean-surf 62 *")."""
    _prefix, name = prefix_and_name(entry["id"])
    if entry["kind"] == "music":
        words = music_words(entry)
    else:
        words = f"{name} {listing_seconds(entry['seconds'])}"
        moods = entry.get("moods") or []
        if moods:
            words += f" {'/'.join(moods)}"
    if is_recent(entry, recent):
        words += f" {RECENT_MARK}"
    return words


def kind_groups(entries: list[dict]) -> list[tuple[str, list[dict]]]:
    """A category's sounds in the groups its line lists, each with its label: the loops, the hits, then the music, by
    style: untagged music as "music", tagged music under "music, <style>", the styles in order of their names.
    [ocean-surf (loop), borealis (synth pads), daydream (piano)] -> [("loops", [ocean-surf]), ("music, piano",
    [daydream]), ("music, synth-pads", [borealis])]."""
    groups = []
    for kind in ("loop", "hit"):
        of_kind = [e for e in entries if e["kind"] == kind]
        if of_kind:
            groups.append((KIND_LABELS[kind], of_kind))
    music = [e for e in entries if e["kind"] == "music"]
    styles = sorted({style_of(e) for e in music})
    for style in styles:
        label = KIND_LABELS["music"]
        if style:
            label = f"{label}, {style}"
        groups.append((label, [e for e in music if style_of(e) == style]))
    return groups


def category_line(entries: list[dict], recent: set[str] = frozenset()) -> str:
    """One category in one line: its id prefix, then its loops and hits, each name with its seconds, and its music by
    style, each name with its moods (music has no seconds: it loops under a scene). "ambience/ loops: ocean-surf 62,
    night-camp 28; hits: thunder-clap 13"; "jingles/ music, piano: daydream calm/dreamy/peaceful; music, synth-pads:
    borealis eerie/melancholy/dreamy". A sound in `recent` is marked (sound_words)."""
    prefix, _name = prefix_and_name(entries[0]["id"])
    groups = []
    for label, grouped in kind_groups(entries):
        groups.append(f"{label}: {', '.join(sound_words(e, recent) for e in grouped)}")
    return f"{prefix} " + "; ".join(groups)


def category_rank(category: str) -> int:
    """Where a category comes in the writer's listing: the user's own folders first (-1), then CATEGORY_ORDER, then
    anything else. "Your sounds" or a folder of theirs -> -1; "Ambience" -> 0; "Effects" -> 14."""
    if category in CATEGORY_ORDER:
        return CATEGORY_ORDER.index(category)
    return -1


def summary_line(entries: list[dict]) -> str:
    """A category too big to list in full, in one line with three ids to show the shape: "effects/ 95 sounds (64
    hits, 31 loops), not listed in full; for example effects/alarm, effects/bark, effects/owl." """
    prefix, _name = prefix_and_name(entries[0]["id"])
    counts: dict[str, int] = {}
    for e in entries:
        counts[e["kind"]] = counts.get(e["kind"], 0) + 1
    kinds = ", ".join(f"{n} {KIND_LABELS[kind]}" for kind, n in sorted(counts.items()))
    examples = ", ".join(e["id"] for e in entries[:3])
    return f"{prefix} {len(entries)} sounds ({kinds}), not listed in full; for example {examples}."


LISTING_INTRO = ("Sounds you can use, one category a line: its id prefix, then its loops (beds that run under a scene) "
                 "and hits (played once), each with its seconds, then its music by style, each with its moods. A "
                 'sound\'s id is the prefix and the name: "ambience/" and "ocean-surf" -> "ambience/ocean-surf". Use '
                 "the ids exactly.")
NO_MUSIC = "There is no music here (no iMovie on this Mac): don't add music beds."
RECENT_MARK = "*"
RECENT_LEGEND = f"{RECENT_MARK} used in your recent stories, prefer others"


def writer_listing(entries: list[dict], recent: set[str] = frozenset()) -> str:
    """The sounds as the writer reads them, one line a category (category_line). The most useful categories come
    first and in full; once the next one in full wouldn't leave room under LISTING_TOKENS (at CHARS_PER_TOKEN), the
    rest are summed up in a line each. Without music (the kit), it says so. `recent` is the beds and music of the
    user's last stories: each is marked, with RECENT_LEGEND to say what the mark means."""
    by_category: dict[str, list[dict]] = {}
    for e in entries:
        by_category.setdefault(e["category"], []).append(e)
    order = sorted(by_category, key=category_rank)
    head = [LISTING_INTRO]
    if not any(e["kind"] == "music" for e in entries):
        head.append(NO_MUSIC)
    if any(is_recent(e, recent) for e in entries):
        head.append(RECENT_LEGEND)
    budget = LISTING_TOKENS * CHARS_PER_TOKEN
    used = sum(len(line) + 1 for line in head)
    summaries = {c: summary_line(by_category[c]) for c in order}
    parts: list[str] = []
    for i, category in enumerate(order):
        full = category_line(by_category[category], recent)
        rest = sum(len(summaries[c]) + 1 for c in order[i + 1:])
        fits = used + len(full) + 1 + rest <= budget
        chosen = full if fits else summaries[category]
        parts.append(chosen)
        used += len(chosen) + 1
    return "\n".join(head + parts)
