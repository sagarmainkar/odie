"""The sound library audio stories choose from (odie.making.sound_library): iMovie's sounds on the user's Mac and a
folder of their own, read into one catalogue of loops, hits and music, cached, and listed for the writer. Every test
builds a fake library in a temp folder with tiny generated sounds; none reads /Applications."""
import asyncio
import math
import struct
import subprocess
import wave
from pathlib import Path

import pytest

from odie.making import sound_library as lib
from odie.video.encode import ffmpeg


def tone(path: Path, seconds: float, rate: int = 8000) -> Path:
    """A tiny mono WAV of a quiet tone, `seconds` long."""
    path.parent.mkdir(parents=True, exist_ok=True)
    frames = int(seconds * rate)
    samples = b"".join(struct.pack("<h", int(800 * math.sin(i / 8))) for i in range(frames))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples)
    return path


def as_caf(wav: Path, caf: Path) -> Path:
    """The WAV converted to Core Audio Format, as iMovie ships its effects (the bundled ffmpeg writes and reads it)."""
    caf.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run([ffmpeg(), "-v", "error", "-y", "-i", str(wav), "-c:a", "pcm_s16le", str(caf)], check=True)
    return caf


@pytest.fixture
def imovie(tmp_path) -> Path:
    """A fake iMovie Resources folder: a few categories of .caf/.wav effects, Jingles in three cuts, one .mp3-folder
    effect (a WAV standing in) and one theme."""
    root = tmp_path / "Resources"
    effects = root / lib.ILIFE_EFFECTS_FOLDER
    scratch = tmp_path / "scratch"
    as_caf(tone(scratch / "surf.wav", 12.0), effects / "Ambience" / "Ocean Surf.caf")
    tone(effects / "Ambience" / "Night Camp.wav", 9.0)
    tone(effects / "Animals" / "Bark.wav", 1.0)
    tone(effects / "Animals" / "Jungle Birds.wav", 10.0)
    tone(effects / "Stingers" / "Suspense Hit.wav", 3.0)
    tone(effects / "Foley" / "Door Creak.wav", 1.5)
    for cut, seconds in (("Long", 6.0), ("Medium", 3.0), ("Short", 1.0)):
        tone(effects / "Jingles" / f"Acoustic Sunrise {cut}.wav", seconds)
    tone(root / lib.IMOVIE_EFFECTS_FOLDER / "Thunder Clap.wav", 2.0)
    tone(root / lib.THEME_MUSIC_FOLDER / "Bulletin.wav", 5.0)
    return root


def run(coro):
    return asyncio.run(coro)


def test_the_libraries_found_in_order(imovie, tmp_path):
    own = tmp_path / "own"
    tone(own / "Rain" / "Tin Roof.wav", 8.0)
    found = lib.find_libraries(imovie, own)
    assert [f.name for f in found] == ["iLife Sound Effects", "iMovie Sound Effects", "iMovie Theme Music", "Your sounds"]
    assert lib.find_libraries(tmp_path / "no-imovie", tmp_path / "no-own") == []


def test_a_sound_is_a_loop_a_hit_or_music_by_category_then_length_and_name():
    assert lib.kind_of("Ambience", "Ocean Surf", 60) == "loop"
    assert lib.kind_of("Stingers", "Suspense Hit", 3) == "hit"
    assert lib.kind_of("Foley", "Door Creak", 1.5) == "hit"
    assert lib.kind_of("Jingles", "Acoustic Sunrise", 60) == "music"
    assert lib.kind_of("Theme Music", "Bulletin", 30) == "music"
    assert lib.kind_of("Animals", "Night Camp", 60) == "loop"  # long: runs under a scene
    assert lib.kind_of("Animals", "Bark", 2) == "hit"
    assert lib.kind_of("People", "Crowd Murmur", 5) == "loop"  # a crowd is a bed even when short
    assert lib.kind_of("Effects", "Thunder Clap", 2) == "hit"
    assert lib.kind_of("Effects", "Rain Heavy", 30) == "loop"


def test_kinds_the_real_library_needs():
    """iMovie's own names and lengths, as found on a real Mac: Textures are mostly short accents, a few long Foley
    sounds run under a scene, and a ring, a bell, a clap or a strike plays once however long it is."""
    assert lib.kind_of("Textures", "Suspense Accents 01", 1.2) == "hit"
    assert lib.kind_of("Textures", "Mystery Accents 03", 6.6) == "hit"  # "accent" in a name: a hit
    assert lib.kind_of("Textures", "Super Stager", 35.4) == "loop"  # Textures go by length and name now
    assert lib.kind_of("Ambience", "Thunder Clap", 12.8) == "hit"
    assert lib.kind_of("Effects", "Bell Tower", 9.7) == "hit"
    assert lib.kind_of("Foley", "Antique Clock Strike", 49.8) == "hit"
    assert lib.kind_of("Work - Home", "Cell Phone Ringing", 17.2) == "hit"
    assert lib.kind_of("Work - Home", "Old Telephone Ring", 12.0) == "hit"
    assert lib.kind_of("Foley", "Footsteps", 12.6) == "loop"  # long Foley runs under a scene
    assert lib.kind_of("Foley", "Clock Wind Up", 32.7) == "loop"
    assert lib.kind_of("Foley", "Scuba Breathing", 54.4) == "loop"
    assert lib.kind_of("Foley", "Door Wood Squeak", 2.1) == "hit"
    assert lib.kind_of("Transportation", "Jet Fly By", 8.7) == "hit"  # a pass-by is an event: as a bed it repeats
    assert lib.kind_of("Effects", "Train Pass FX 2", 18.4) == "hit"
    assert lib.kind_of("Transportation", "Police Car Siren Passing", 13.7) == "hit"
    assert lib.kind_of("Work - Home", "Telephone Number Change", 8.6) == "hit"
    for name, seconds in (("Chicken", 30.5), ("Basketball Bounce", 13.6), ("Bottle Pour", 10.1)):
        assert lib.kind_of("Effects", name, seconds) == "hit"  # the overrides: events, not beds


def test_the_catalogue_reads_every_sound_once(isolated_settings, imovie, tmp_path):
    entries = run(lib.build(lib.find_libraries(imovie, tmp_path / "own")))
    by_id = {e["id"]: e for e in entries}
    assert set(by_id) == {"ambience/ocean-surf", "ambience/night-camp", "animals/bark", "animals/jungle-birds",
                          "stingers/suspense-hit", "foley/door-creak", "jingles/acoustic-sunrise", "effects/thunder-clap",
                          "theme-music/bulletin"}
    surf = by_id["ambience/ocean-surf"]
    assert surf["name"] == "Ocean Surf" and surf["category"] == "Ambience" and surf["kind"] == "loop"
    assert abs(surf["seconds"] - 12.0) < 0.1 and surf["path"].endswith("Ocean Surf.caf")  # a .caf is read too
    assert by_id["animals/bark"]["kind"] == "hit" and by_id["animals/jungle-birds"]["kind"] == "loop"
    assert by_id["theme-music/bulletin"]["kind"] == "music"


def test_a_jingles_three_cuts_are_one_sound_with_variants(isolated_settings, imovie, tmp_path):
    entries = run(lib.build(lib.find_libraries(imovie, tmp_path / "own")))
    jingle = next(e for e in entries if e["id"] == "jingles/acoustic-sunrise")
    assert jingle["kind"] == "music" and jingle["name"] == "Acoustic Sunrise"
    assert [v["cut"] for v in jingle["variants"]] == ["long", "medium", "short"]
    assert jingle["path"].endswith("Acoustic Sunrise Long.wav") and abs(jingle["seconds"] - 6.0) < 0.1  # the long cut leads
    assert lib.cut_of("Acoustic Sunrise Medium") == ("Acoustic Sunrise", "medium")
    assert lib.cut_of("Acoustic Sunrise (Short)") == ("Acoustic Sunrise", "short")
    assert lib.cut_of("Ocean Surf") == ("Ocean Surf", None)


def test_your_own_sounds_folder(isolated_settings, tmp_path):
    own = tmp_path / "own"
    tone(own / "Rain" / "Tin Roof.wav", 8.0)
    tone(own / "Gong.wav", 2.0)
    entries = run(lib.build(lib.find_libraries(tmp_path / "no-imovie", own)))
    assert {e["id"]: e["kind"] for e in entries} == {"rain/tin-roof": "loop", "your-sounds/gong": "hit"}


def test_your_own_folder_sits_in_odies_home_or_its_data_folder(isolated_settings, monkeypatch, tmp_path):
    import dataclasses

    from odie import config
    with_home = dataclasses.replace(config.settings, home=tmp_path / "home", data_dir=tmp_path / "home" / "data")
    monkeypatch.setattr(config, "settings", with_home)
    assert lib.own_sounds_folder() == tmp_path / "home" / "sounds"
    folders_only = dataclasses.replace(config.settings, home=None, data_dir=tmp_path / "data")  # ODIE_DATA_DIR without ODIE_HOME
    monkeypatch.setattr(config, "settings", folders_only)
    assert lib.own_sounds_folder() == tmp_path / "data" / "sounds"


def test_the_catalogue_is_cached_and_built_again_when_a_library_changes(isolated_settings, imovie, tmp_path, monkeypatch):
    cache = tmp_path / "cache.json"
    libraries = lib.find_libraries(imovie, tmp_path / "own")
    first = run(lib.catalogue(libraries, cache))
    assert cache.exists()
    probed = []
    real_probe = lib.probe

    async def counting(path):
        probed.append(path)
        return await real_probe(path)
    monkeypatch.setattr(lib, "probe", counting)
    assert run(lib.catalogue(libraries, cache)) == first and probed == []  # nothing changed: read from the cache
    tone(imovie / lib.ILIFE_EFFECTS_FOLDER / "Animals" / "Owl Hoot.wav", 2.0)
    again = run(lib.catalogue(libraries, cache))
    assert "animals/owl-hoot" in {e["id"] for e in again} and probed  # a new file: built again


def test_without_a_library_the_video_kit_stands_in_and_says_there_is_no_music(isolated_settings, tmp_path):
    entries = run(lib.catalogue([], tmp_path / "cache.json"))
    kinds = {e["id"]: e["kind"] for e in entries}
    assert kinds["kit/rain"] == "loop" and kinds["kit/whoosh"] == "hit"
    assert not any(e["kind"] == "music" for e in entries)
    assert all(Path(e["path"]).exists() for e in entries)
    listing = lib.writer_listing(entries)
    assert "no music" in listing.lower()
    kit_line = next(line for line in listing.splitlines() if line.startswith("kit/ "))
    assert "loops: " in kit_line and "rain 4" in kit_line


def test_the_writers_listing_is_one_line_a_category_grouped_by_kind(isolated_settings, imovie, tmp_path):
    entries = run(lib.build(lib.find_libraries(imovie, tmp_path / "own")))
    listing = lib.writer_listing(entries)
    lines = listing.splitlines()
    ambience = next(line for line in lines if line.startswith("ambience/ "))
    assert ambience == "ambience/ loops: night-camp 9, ocean-surf 12"
    animals = next(line for line in lines if line.startswith("animals/ "))
    assert animals == "animals/ loops: jungle-birds 10; hits: bark 1"
    assert "jingles/ music: acoustic-sunrise" in listing  # music has no seconds: it loops under a scene
    assert listing.index("ambience/ ") < listing.index("stingers/ ")  # the most useful categories first
    assert '"ambience/" and "ocean-surf" -> "ambience/ocean-surf"' in listing  # how an id is made from a line


def test_listing_seconds_are_whole_and_at_least_one():
    assert [lib.listing_seconds(s) for s in (62.5, 9.6, 0.3, 1.4)] == ["62", "10", "1", "1"]


def full_library() -> list[dict]:
    """A library shaped like iMovie's real one: 426 entries in 15 categories, names as long as its own (about 14
    characters, "coin-drop-on-wood")."""
    entries = []
    sizes = {"Ambience": 14, "Textures": 13, "Animals": 13, "Foley": 27, "People": 24, "Transportation": 17,
             "Machines": 13, "Stingers": 53, "Booms": 7, "Sci-Fi": 17, "Sports": 8, "Work - Home": 12, "Jingles": 106,
             "Effects": 95, "Theme Music": 7}
    for category, count in sizes.items():
        prefix = category.lower().replace(" - ", "-").replace(" ", "-")
        for i in range(count):
            name = f"Door Squeak {i:02d}"
            seconds = 5.0 + i % 40
            entry = {"id": f"{prefix}/door-squeak-{i:02d}", "name": name, "category": category,
                     "kind": lib.kind_of(category, name, seconds), "seconds": seconds, "path": "/x", "variants": []}
            if entry["kind"] == "music":  # every track tagged, as the shipped words tag iMovie's
                entry["moods"] = MOODS[i % len(MOODS):][:3] or MOODS[:3]
                entry["styles"] = [STYLES[i % len(STYLES)], STYLES[(i + 1) % len(STYLES)]]
            entries.append(entry)
    return entries


# Words as long as the shipped ones: CLAP's 26 moods and 16 styles.
MOODS = ["eerie", "spooky", "tense", "suspenseful", "dark", "sad", "melancholy", "solemn", "calm", "peaceful", "dreamy",
         "mysterious", "romantic", "warm", "happy", "cheerful", "playful", "upbeat", "energetic", "triumphant", "epic",
         "heroic", "adventurous", "funny", "relaxed", "nostalgic"]
STYLES = ["piano", "strings", "orchestra", "acoustic guitar", "electric guitar", "synth pads", "electronic beat", "jazz",
          "blues", "rock", "folk", "lounge", "hip hop", "ambient drone", "brass", "drums"]


def test_the_writers_listing_lists_a_whole_imovie_sized_library_within_its_budget():
    """The budget counts CHARS_PER_TOKEN characters a token, a little cautious: a real tokenizer gives about 2.95 on
    the real listing, its music with its mood words."""
    listing = lib.writer_listing(full_library())
    assert len(listing) / lib.CHARS_PER_TOKEN <= lib.LISTING_TOKENS
    assert "not listed in full" not in listing  # every sound is there
    assert "music, piano: " in listing  # the music with its moods
    assert "effects/ " in listing and "door-squeak-94 " in listing


def test_a_library_too_big_for_the_budget_sums_up_its_least_useful_categories():
    entries = full_library()
    for copy in range(3):  # a big folder of the user's own, three times over
        entries += [{**e, "id": f"{e['id']}-{copy}"} for e in full_library() if e["category"] == "Effects"]
    listing = lib.writer_listing(entries)
    assert len(listing) / lib.CHARS_PER_TOKEN <= lib.LISTING_TOKENS
    assert "ambience/ loops: " in listing  # a top category in full
    assert "effects/ 380 sounds" in listing and "not listed in full" in listing  # the least useful one summed up


# Mood words for music: tags a listening model put on iMovie's tracks, shipped with Odie, and the user's own.

def tags_file(path: Path, tags: dict) -> Path:
    """A moods file in the shipped shape: {"<folder>/<file>": {"moods": [...], "styles": [...]}}."""
    import json
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"_about": "test tags", **tags}))
    return path


def test_music_takes_its_mood_words_by_the_file_it_comes_from(isolated_settings, imovie, tmp_path):
    entries = run(lib.build(lib.find_libraries(imovie, tmp_path / "own")))
    shipped = tags_file(tmp_path / "shipped.json", {
        "Jingles/Acoustic Sunrise Long.wav": {"moods": ["solemn", "dreamy", "relaxed"], "styles": ["acoustic guitar"]},
        "iMovie Theme Music/Bulletin.wav": {"moods": ["epic", "dark", "tense"], "styles": ["orchestra", "drums"]},
    })
    tagged = {e["id"]: e for e in lib.with_moods(entries, [shipped])}
    assert tagged["jingles/acoustic-sunrise"]["moods"] == ["solemn", "dreamy", "relaxed"]
    assert tagged["jingles/acoustic-sunrise"]["styles"] == ["acoustic guitar"]
    assert tagged["theme-music/bulletin"]["moods"] == ["epic", "dark", "tense"]
    assert "moods" not in tagged["ambience/ocean-surf"]  # no tags for it: nothing added


def test_a_jingle_and_a_theme_of_one_name_keep_their_own_words(tmp_path):
    """iMovie has a jingle "Travel" and a theme "TRAVEL": keyed by name, one overwrote the other."""
    jingle = {"id": "jingles/travel", "kind": "music", "path": "/R/iLife Sound Effects/Jingles/Travel.caf",
              "variants": []}
    theme = {"id": "theme-music/travel", "kind": "music", "path": "/R/iMovie Theme Music/TRAVEL.m4a", "variants": []}
    shipped = tags_file(tmp_path / "shipped.json", {
        "Jingles/Travel.caf": {"moods": ["funny"], "styles": ["brass"]},
        "iMovie Theme Music/TRAVEL.m4a": {"moods": ["happy"], "styles": ["electric guitar"]},
    })
    tagged = {e["id"]: e for e in lib.with_moods([jingle, theme], [shipped])}
    assert tagged["jingles/travel"]["moods"] == ["funny"] and tagged["theme-music/travel"]["moods"] == ["happy"]


def test_a_tag_on_any_cut_of_a_jingle_finds_it():
    entry = {"path": "/R/Jingles/Borealis Long.caf",
             "variants": [{"path": "/R/Jingles/Borealis Long.caf"}, {"path": "/R/Jingles/Borealis Short.caf"}]}
    assert lib.track_keys(entry) == ["Jingles/Borealis Long.caf", "Borealis Long.caf", "Jingles/Borealis Short.caf",
                                     "Borealis Short.caf"]
    assert lib.tags_for(entry, {"Borealis Short.caf": {"moods": ["eerie"], "styles": []}}) == {"moods": ["eerie"],
                                                                                              "styles": []}
    assert lib.tags_for(entry, {"Jingles/Other.caf": {"moods": ["calm"], "styles": []}}) is None


def test_the_users_own_tags_win_and_tag_their_own_sounds(isolated_settings, imovie, tmp_path):
    own = tmp_path / "own"
    tone(own / "Drones" / "Low Hum.wav", 9.0)
    entries = run(lib.build(lib.find_libraries(imovie, own)))
    shipped = tags_file(tmp_path / "shipped.json", {
        "Jingles/Acoustic Sunrise Long.wav": {"moods": ["solemn", "dreamy", "relaxed"], "styles": ["acoustic guitar"]},
    })
    theirs = tags_file(own / lib.OWN_MOODS_FILE, {
        "Acoustic Sunrise Long.wav": {"moods": ["warm", "happy"], "styles": ["folk"]},  # a bare file name works too
        "Drones/Low Hum.wav": {"moods": ["eerie", "dark"], "styles": ["ambient drone"]},
    })
    tagged = {e["id"]: e for e in lib.with_moods(entries, [shipped, theirs])}
    assert tagged["jingles/acoustic-sunrise"]["moods"] == ["warm", "happy"]  # theirs, not the shipped words
    assert tagged["drones/low-hum"]["moods"] == ["eerie", "dark"]


def test_a_broken_or_missing_moods_file_is_no_tags(tmp_path):
    broken = tmp_path / "moods.json"
    broken.write_text("{not json")
    assert lib.read_tags(broken) == {}
    assert lib.read_tags(tmp_path / "none.json") == {}
    odd = tags_file(tmp_path / "odd.json", {"A.caf": {"moods": "eerie"}, "B.caf": {"moods": ["calm"]}})
    assert lib.read_tags(odd) == {"B.caf": {"moods": ["calm"], "styles": []}}  # moods must be a list; styles optional


def test_the_catalogue_carries_the_shipped_words_and_the_users(isolated_settings, imovie, tmp_path, monkeypatch):
    shipped = tags_file(tmp_path / "shipped.json", {
        "Jingles/Acoustic Sunrise Long.wav": {"moods": ["solemn"], "styles": ["acoustic guitar"]},
    })
    monkeypatch.setattr(lib, "SHIPPED_MOODS", shipped)
    own = lib.own_sounds_folder()
    assert not str(own).startswith(str(Path.home() / ".odie"))  # the isolated test home
    libraries = lib.find_libraries(imovie, own)
    first = {e["id"]: e for e in run(lib.catalogue(libraries, tmp_path / "cache.json"))}
    assert first["jingles/acoustic-sunrise"]["moods"] == ["solemn"]
    tags_file(own / lib.OWN_MOODS_FILE, {"Acoustic Sunrise Long.wav": {"moods": ["warm"], "styles": []}})
    again = {e["id"]: e for e in run(lib.catalogue(libraries, tmp_path / "cache.json"))}
    assert again["jingles/acoustic-sunrise"]["moods"] == ["warm"]  # read each time: a change is seen at once


def test_the_shipped_words_cover_every_imovie_track_by_its_file():
    import json
    shipped = json.loads(lib.SHIPPED_MOODS.read_text())
    tracks = {key: tags for key, tags in shipped.items() if key != "_about"}
    assert len(tracks) == 113  # 106 jingles and 7 themes
    assert "Jingles/Travel.caf" in tracks and "iMovie Theme Music/TRAVEL.m4a" in tracks  # both, no longer one
    assert all(len(t["moods"]) == 3 and len(t["styles"]) == 2 for t in tracks.values())
    assert "CLAP" in shipped["_about"] and "moods.json" in shipped["_about"]


def test_the_listing_gives_music_its_mood_words_grouped_by_style(isolated_settings, imovie, tmp_path):
    entries = run(lib.build(lib.find_libraries(imovie, tmp_path / "own")))
    shipped = tags_file(tmp_path / "shipped.json", {
        "Jingles/Acoustic Sunrise Long.wav": {"moods": ["solemn", "dreamy", "relaxed"],
                                               "styles": ["acoustic guitar", "electric guitar"]},
    })
    listing = lib.writer_listing(lib.with_moods(entries, [shipped]))
    jingles = next(line for line in listing.splitlines() if line.startswith("jingles/ "))
    assert jingles == "jingles/ music, acoustic-guitar: acoustic-sunrise solemn/dreamy/relaxed"
    themes = next(line for line in listing.splitlines() if line.startswith("theme-music/ "))
    assert themes == "theme-music/ music: bulletin"  # untagged music: its name alone
    assert "moods" in listing.splitlines()[0]  # the intro says how to read them


def test_music_words_are_the_moods_then_one_style_group():
    borealis = {"id": "jingles/borealis", "kind": "music", "moods": ["eerie", "melancholy", "dreamy"],
                "styles": ["synth pads", "ambient drone"]}
    assert lib.music_words(borealis) == "borealis eerie/melancholy/dreamy"
    assert lib.style_of(borealis) == "synth-pads"
    assert lib.style_of({"id": "jingles/x", "kind": "music"}) == ""
