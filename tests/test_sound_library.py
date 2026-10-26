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
            name = f"Door Squeak Mid {i:02d}"
            seconds = 5.0 + i % 40
            entries.append({"id": f"{prefix}/door-squeak-mid-{i:02d}", "name": name, "category": category,
                            "kind": lib.kind_of(category, name, seconds), "seconds": seconds, "path": "/x",
                            "variants": []})
    return entries


def test_the_writers_listing_lists_a_whole_imovie_sized_library_within_its_budget():
    """The budget counts CHARS_PER_TOKEN characters a token, a cautious count for ids full of hyphens (a real
    tokenizer gives about 2.8 on this listing)."""
    listing = lib.writer_listing(full_library())
    assert len(listing) / lib.CHARS_PER_TOKEN <= lib.LISTING_TOKENS
    assert "not listed in full" not in listing  # every sound is there
    assert "effects/ " in listing and "door-squeak-mid-94 " in listing


def test_a_library_too_big_for_the_budget_sums_up_its_least_useful_categories():
    entries = full_library()
    for copy in range(3):  # a big folder of the user's own, three times over
        entries += [{**e, "id": f"{e['id']}-{copy}"} for e in full_library() if e["category"] == "Effects"]
    listing = lib.writer_listing(entries)
    assert len(listing) / lib.CHARS_PER_TOKEN <= lib.LISTING_TOKENS
    assert "ambience/ loops: " in listing  # a top category in full
    assert "effects/ 380 sounds" in listing and "not listed in full" in listing  # the least useful one summed up
