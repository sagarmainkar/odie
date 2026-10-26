"""The audio-story skill's guided start: which accents each voice engine offers, and the cast-ready voice options
(story_voices) the chat model puts straight into its form, each with a ▶ preview. No real voice engine is asked."""
import asyncio
from pathlib import Path

import httpx
import pytest

from odie import voice
from odie.skills.registry import _load_tools, discover
from odie.store.db import Store

SKILL = Path(voice.__file__).parent / "skills" / "audio-story"


def tools() -> dict:
    return {t.name: t for t in _load_tools(SKILL, "audio-story")}


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    from odie.making import jobs
    jobs.hooks["store"] = s
    return s


def phonon_listing(voices):
    def handler(request):
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"voices": voices})
        return httpx.Response(200, json={"models": [{"name": "phonon:latest"}]})
    return httpx.MockTransport(handler)


def choose(store, engine, monkeypatch):
    store.set_setting("voice", {"engine": engine})
    monkeypatch.setenv("ODIE_VOICE", "on")
    monkeypatch.setattr(voice, "load_secret", lambda name: "sk-test")  # OpenAI chosen: its key is there


def test_each_engine_offers_its_accents():
    mod = tools()["story_voices"].func.__globals__
    assert mod["accents_for"]("phonon") == ["American", "British"]
    assert mod["accents_for"]("kokoro") == ["American", "British", "Indian"]
    assert mod["accents_for"]("openai") == ["American", "British", "Indian"]


def test_phonon_voices_for_an_accent_with_characters_and_previews(store, monkeypatch):
    choose(store, "phonon", monkeypatch)
    asyncio.run(voice.phonon_voices(transport=phonon_listing(["Zoey", "Easton", "Maeve", "Alfie", "Captain Silas Blackwater", "Old Mortlake"])))
    asyncio.run(voice.phonon_available(transport=phonon_listing([])))
    got = asyncio.run(tools()["story_voices"].func(accent="British"))
    assert set(got) == {"engine", "accent", "options", "notes"}  # one list, pasted as it is into every voice select
    assert got["engine"] == "phonon" and got["accent"] == "British"
    options = got["options"]
    assert [o["value"] for o in options] == ["Maeve", "Alfie", "Captain Silas Blackwater", "Old Mortlake"]
    assert options[0]["note"].startswith("woman · ") and options[1]["note"].startswith("man · ")
    assert options[2]["note"].startswith("man · character voice")  # the Characters come after the accent's voices
    assert all(len(o["note"]) <= 80 for o in options) and all(o["preview"] for o in options)
    captain = options[2]
    assert captain["preview"] == "/api/voice/preview/phonon/Captain%20Silas%20Blackwater"  # spaces encoded for the ▶
    assert captain["label"] == "Captain Silas Blackwater"


def test_the_phonon_list_is_asked_of_ollama_first(store, monkeypatch):
    choose(store, "phonon", monkeypatch)
    asked = []

    async def fake_voices(transport=None):
        asked.append(True)
        voice._PHONON_VOICES[voice.PHONON_MODEL] = [voice.phonon_voice("Zoey")]
        return voice.engine_voices("phonon")
    monkeypatch.setattr(voice, "phonon_voices", fake_voices)
    monkeypatch.setattr(voice, "phonon_here", lambda: True)
    got = asyncio.run(tools()["story_voices"].func(accent="American"))
    assert asked and [o["value"] for o in got["options"]] == ["Zoey"]


def test_kokoro_has_indian_voices_and_no_characters(store, monkeypatch):
    choose(store, "kokoro", monkeypatch)
    got = asyncio.run(tools()["story_voices"].func(accent="Indian"))
    assert got["engine"] == "kokoro" and [o["value"] for o in got["options"]] == ["hf_alpha", "hf_beta", "hm_omega", "hm_psi"]
    assert got["options"][0] == {"value": "hf_alpha", "label": "Alpha", "note": "woman", "gender": "female",
                                 "preview": "/api/voice/preview/kokoro/hf_alpha"}


def test_openai_takes_any_voice_and_adds_the_accent_in_the_story(store, monkeypatch):
    choose(store, "openai", monkeypatch)
    got = asyncio.run(tools()["story_voices"].func(accent="Indian"))
    assert got["engine"] == "openai"
    assert {o["value"] for o in got["options"]} == {v["id"] for v in voice.VOICES}
    marin = next(o for o in got["options"] if o["value"] == "marin")
    assert marin["note"] == "woman · accent added in the story" and marin["preview"] == "/api/voice/preview/openai/marin"


def test_no_accent_yet_lists_the_accents_and_a_wrong_one_is_said_plainly(store, monkeypatch):
    choose(store, "kokoro", monkeypatch)
    assert asyncio.run(tools()["story_voices"].func()) == {"engine": "kokoro", "accents": ["American", "British", "Indian"],
                                                         "default": "American"}
    choose(store, "phonon", monkeypatch)
    monkeypatch.setattr(voice, "phonon_here", lambda: True)
    bad = asyncio.run(tools()["story_voices"].func(accent="Indian"))
    assert bad == {"error": "Phonon's voices here are American or British: choose one of those."}


def test_the_skill_loads_and_answers_to_audio_story_requests(store):
    skills = {e.name: e for e in discover(store)}
    skill = skills["audio-story"]
    for words in ("audio story", "radio play", "audio drama", "story to listen to", "bedtime story"):
        assert words in skill.description, words
    text = (SKILL / "SKILL.md").read_text()
    assert "never use `speak`" in text.lower() and "make_audio_story" in text and "story_voices" in text
    assert "shell" in text  # never stitched together in the shell


# make_audio_story: what it refuses, and the job it queues.

@pytest.fixture
def queued(store, monkeypatch, tmp_path):
    """jobs.submit replaced by a recorder; Kokoro chosen in Settings; no iMovie (its folder is a temp one, never
    /Applications)."""
    from odie.making import jobs, sound_library
    choose(store, "kokoro", monkeypatch)
    monkeypatch.setattr(sound_library, "LIBRARY_ROOT", tmp_path / "no-imovie")
    submitted = []

    def record(job):
        submitted.append(job)
        return len(submitted)

    monkeypatch.setattr(jobs, "submit", record)
    return submitted


CAST = [{"id": "narrator", "name": "Narrator", "voice": "bf_emma", "about": "an outside storyteller", "gender": "any"},
        {"id": "keeper", "name": "The keeper", "voice": "bm_george", "about": "the old lighthouse keeper",
         "gender": "male"}]


async def make(**changes) -> dict:
    from types import SimpleNamespace

    from google.adk.tools import FunctionTool
    args = {"title": "The Lighthouse at Rook Point", "genre": "mystery",
            "premise": "A keeper hears a ship that isn't there.", "cast": CAST, "narrator": "narrator",
            "accent": "British", "minutes": 5, "sound_level": 25, "brief": "Slow and eerie."}
    args.update(changes)
    chat = SimpleNamespace(session=SimpleNamespace(id="chat-7"))
    func = tools()["make_audio_story"].func
    return await FunctionTool(func).run_async(args=args, tool_context=chat)


async def test_a_good_story_is_queued_with_its_cast_and_level(queued):
    from odie.agent.tools.files import workspace
    from odie.making import story, story_writer
    out = await make()
    assert out["result"].startswith("Making it now: about a minute (")  # 5 minutes on a local voice
    [job] = queued
    assert job.kind == "story" and job.title == "The Lighthouse at Rook Point" and job.minutes == 5
    assert job.session_id == "chat-7"
    assert job.folder == workspace() / story.FOLDER / "the-lighthouse-at-rook-point" and job.folder.is_dir()
    request = job.data["request"]
    assert request == story_writer.Request(genre="mystery", premise="A keeper hears a ship that isn't there.",
                                           cast=[{**member, "age": "", "pace": 145} for member in CAST],
                                           narrator="narrator",
                                           accent="British", minutes=5, brief="Slow and eerie.", engine="kokoro")
    assert job.data["sound_level"] == 25
    assert "The keeper" in job.brief and "bm_george" in job.brief  # brief.md keeps what was asked


async def test_a_voice_of_another_engine_is_refused_with_where_to_look(queued):
    cast = [CAST[0], {**CAST[1], "voice": "marin"}]
    out = await make(cast=cast)
    assert out["error"].startswith("The keeper's voice: 'marin' isn't one of")
    assert "story_voices" in out["error"]
    assert queued == []


async def test_too_many_characters_the_length_and_the_sound_level_are_refused(queued):
    crowd = [{"id": f"c{n}", "name": f"Person {n}", "voice": "bf_emma", "gender": "female"} for n in range(8)]
    out = await make(cast=[CAST[0], *crowd])
    assert out["error"] == ("A story has at most 8 speakers, the narrator included; this cast has 9. Let minor "
                            "characters share a voice, or leave them to the narrator.")
    assert (await make(minutes=1))["error"].startswith("minutes is the story's length in whole minutes, from 2 to 15")
    assert "not 20" in (await make(minutes=20))["error"]
    assert (await make(sound_level=50))["error"] == (
        "sound_level is how loud the ambience is when no one speaks, from 10 to 40 (25 unless the user chose), not 50.")
    assert queued == []


async def test_the_narrator_must_be_in_the_cast_and_the_accent_offered(queued):
    assert (await make(narrator="captain"))["error"] == (
        'narrator is the cast id of who tells the story ("narrator" for an outside storyteller, in the cast too); '
        '"captain" isn\'t in the cast: narrator, keeper.')
    phonon_only = await make(accent="Irish")
    assert phonon_only["error"].startswith("Kokoro's voices here are American, British or Indian")
    assert (await make(premise="  "))["error"].startswith("premise is the story's idea")
    assert queued == []


async def test_cast_ids_are_made_plain_and_kept_unique(queued):
    cast = [{"name": "Narrator", "voice": "bf_emma", "gender": "any"},
            {"id": "The Keeper", "name": "The keeper", "voice": "bm_george", "gender": "male"}]
    out = await make(cast=cast, narrator="narrator")
    assert "result" in out
    assert [m["id"] for m in queued[0].data["request"].cast] == ["narrator", "the-keeper"]
    twice = [CAST[0], {**CAST[1], "id": "narrator"}]
    assert (await make(cast=twice))["error"] == 'Two cast members have the id "narrator": give each their own.'


def test_the_skill_asks_the_accent_before_the_cast_and_pastes_the_voice_options():
    """The voices come for one accent, so the accent is asked with the story, before story_voices(accent) and the cast
    form; the cast form's selects take story_voices' options as they are, previews and all."""
    text = (SKILL / "SKILL.md").read_text()
    story_step = text.index("2. **The story")
    cast_step = text.index("3. **Cast")
    assert story_step < text.index("**accent:**", story_step) < cast_step  # asked in step 2
    assert cast_step < text.index("story_voices(accent)")
    assert "exactly as `story_voices` gives them" in text and "`preview`" in text


def test_the_skill_offers_make_audio_story_and_never_speak():
    text = (SKILL / "SKILL.md").read_text()
    assert "adk_additional_tools: [story_voices, make_audio_story]" in text


async def test_without_imovie_the_reply_says_once_where_richer_sound_comes_from(queued, monkeypatch, tmp_path):
    from odie.making import sound_library
    without = await make()
    assert without["result"].endswith("For richer sound, install iMovie (free in the App Store); Odie uses its sound "
                                      "library.\"")
    imovie = tmp_path / "Resources"
    (imovie / sound_library.ILIFE_EFFECTS_FOLDER).mkdir(parents=True)
    monkeypatch.setattr(sound_library, "LIBRARY_ROOT", imovie)
    with_imovie = await make(title="Another")
    assert "iMovie" not in with_imovie["result"]


def test_the_wait_told_is_about_what_real_stories_take():
    """Real 3-minute stories took 39–49 s to write and seconds to speak and mix on Phonon."""
    wait = tools()["make_audio_story"].func.__globals__["wait_words"]
    assert wait(3, "phonon") == "about a minute"
    assert wait(15, "phonon") == "about 3–4 minutes"
    assert wait(10, "openai") == "about 12–13 minutes"  # OpenAI speaks about as fast as the story plays


def test_the_note_on_sounds_says_where_they_come_from(tmp_path):
    from odie.making import sound_library
    note = tools()["make_audio_story"].func.__globals__["library_note"]
    own = sound_library.Library(sound_library.OWN_CATEGORY, tmp_path, sound_library.OWN_CATEGORY)
    imovie = sound_library.Library(sound_library.ILIFE_EFFECTS_FOLDER, tmp_path, "Effects")
    assert "Odie's own small sound kit, with no music" in note([])
    only_own = note([own])
    assert "the user's own sounds folder" in only_own and "kit" not in only_own
    assert "install iMovie" in only_own
    assert note([imovie, own]) == ""


async def test_with_only_your_own_sounds_the_reply_names_your_folder(queued):
    from odie.making import sound_library
    folder = sound_library.own_sounds_folder()
    assert not str(folder).startswith(str(Path.home() / ".odie"))  # the isolated test home, never the real one
    (folder / "Rain").mkdir(parents=True)
    out = await make()
    assert "the user's own sounds folder" in out["result"] and "sound kit" not in out["result"]


# Casting by gender: a "she" is never cast on a man's voice, or on a creature's.

def test_phonon_voices_say_who_they_can_play(store, monkeypatch):
    choose(store, "phonon", monkeypatch)
    asyncio.run(voice.phonon_voices(transport=phonon_listing(
        ["Harper", "Miles", "The Snow Queen", "The Thing Under the Stairs", "Fennick the Young Elf"])))
    monkeypatch.setattr(voice, "phonon_here", lambda: True)
    got = asyncio.run(tools()["story_voices"].func(accent="American"))
    genders = {o["value"]: o["gender"] for o in got["options"]}
    assert genders == {"Harper": "female", "Miles": "male", "The Snow Queen": "female",
                       "The Thing Under the Stairs": "creature", "Fennick the Young Elf": "male"}
    queen = next(o for o in got["options"] if o["value"] == "The Snow Queen")
    assert queen["note"].startswith("woman · character voice · ") and len(queen["note"]) <= 80
    thing = next(o for o in got["options"] if o["value"] == "The Thing Under the Stairs")
    assert thing["note"].startswith("creature · character voice")
    for name in ("The Snow Queen", "Morwenna of the Deep", "Fairy Godmother"):
        assert name in got["notes"]  # the owner's rule for eerie women
    assert "ghost" in got["notes"] and "gender" in got["notes"]


def test_every_phonon_character_voice_has_a_gender():
    from odie import voice_phonon
    genders = tools()["story_voices"].func.__globals__["CHARACTER_GENDERS"]
    characters = {v["name"] for v in voice_phonon.CATALOGUE if v["locale"] == "characters"}
    assert set(genders) == characters
    assert {name for name, gender in genders.items() if gender == "female"} == {
        "The Snow Queen", "Morwenna of the Deep", "Fairy Godmother"}
    assert genders["Fennick the Young Elf"] == "male" and genders["The Thing Under the Stairs"] == "creature"


def test_a_voice_plays_a_character_of_its_gender():
    problem = tools()["make_audio_story"].func.__globals__["casting_problem"]
    ghost = {"name": "The ghost girl", "gender": "female"}
    captain = {"name": "The captain", "gender": "male"}
    dragon = {"name": "The dragon", "gender": "any"}
    assert problem(ghost, "Morwenna of the Deep", "female") is None
    assert problem(captain, "Miles", "male") is None
    assert problem(dragon, "Vyrmathrax the Ancient", "creature") is None  # a creature voice plays a creature
    assert problem(dragon, "Miles", "male") is None  # "any" can be anyone
    assert problem(ghost, "Alloy", "any") is None  # a voice with no gender to go by can play anyone
    she_on_him = problem(ghost, "Miles", "male")
    assert she_on_him == "The ghost girl is female, but Miles is a man's voice: choose a woman's voice."
    he_on_her = problem(captain, "Harper", "female")
    assert he_on_her == "The captain is male, but Harper is a woman's voice: choose a man's voice."
    she_on_it = problem(ghost, "The Thing Under the Stairs", "creature")
    assert she_on_it == ("The ghost girl is female, but The Thing Under the Stairs is a creature's voice, with no "
                         "gender: choose a woman's voice.")


def test_gender_words_are_read_kindly():
    word = tools()["make_audio_story"].func.__globals__["gender_word"]
    assert [word(w) for w in ("female", " She", "woman", "girl")] == ["female"] * 4
    assert [word(w) for w in ("male", "he", "Man", "boy")] == ["male"] * 4
    assert [word(w) for w in ("any", "creature", "it", "none")] == ["any"] * 4
    assert word("") == "" and word(None) == "" and word("tall") == ""


async def test_a_cast_member_without_a_gender_is_asked_for_one(queued):
    cast = [CAST[0], {k: v for k, v in CAST[1].items() if k != "gender"}]
    out = await make(cast=cast)
    assert out["error"] == ('The keeper needs a gender: "female" (she), "male" (he) or "any" (a creature, a thing, '
                            "or a storyteller who is no one in the story).")
    assert queued == []


async def test_a_woman_on_a_mans_voice_is_refused_in_words(queued):
    cast = [CAST[0], {**CAST[1], "name": "The keeper's widow", "gender": "female"}]
    out = await make(cast=cast)
    assert out["error"] == "The keeper's widow is female, but George is a man's voice: choose a woman's voice."
    assert queued == []


async def test_the_cast_keeps_its_gender_and_age(queued):
    cast = [CAST[0], {**CAST[1], "gender": "He", "age": "old"}]
    out = await make(cast=cast)
    assert "result" in out
    keeper = queued[0].data["request"].cast[1]
    assert keeper["gender"] == "male" and keeper["age"] == "old"


async def test_phonon_a_ghost_girl_on_the_thing_under_the_stairs_is_refused(store, monkeypatch, tmp_path):
    from odie.making import jobs, sound_library
    choose(store, "phonon", monkeypatch)
    await voice.phonon_voices(transport=phonon_listing(["Hadley", "The Thing Under the Stairs", "Morwenna of the Deep"]))
    monkeypatch.setattr(voice, "phonon_here", lambda: True)
    monkeypatch.setattr(sound_library, "LIBRARY_ROOT", tmp_path / "no-imovie")
    monkeypatch.setattr(jobs, "submit", lambda job: 1)
    narrator = {"id": "narrator", "name": "Narrator", "voice": "Hadley", "gender": "any"}
    ghost = {"id": "ghost", "name": "The ghost", "voice": "The Thing Under the Stairs", "gender": "female",
             "about": "a drowned girl"}
    out = await make(cast=[narrator, ghost], accent="American")
    assert out["error"].startswith("The ghost is female, but The Thing Under the Stairs is a creature's voice")
    assert "For an eerie woman (a ghost, a witch, a sinister woman), choose The Snow Queen, Morwenna of the Deep or " \
           "Fairy Godmother." in out["error"]  # on Phonon, the owner's three voices for her
    out = await make(cast=[narrator, {**ghost, "voice": "Morwenna of the Deep"}], accent="American")
    assert "result" in out


def test_the_skill_casts_eerie_women_from_the_three_voices():
    text = (SKILL / "SKILL.md").read_text()
    assert "**The Snow Queen**, **Morwenna of the Deep** or the **Fairy Godmother**" in text
    assert '"gender"' in text  # every cast member carries one in the call


# American first: the owner prefers it for stories; British stays on offer.

def test_the_accent_question_starts_on_american(store, monkeypatch):
    choose(store, "phonon", monkeypatch)
    monkeypatch.setattr(voice, "phonon_here", lambda: True)
    got = asyncio.run(tools()["story_voices"].func())
    assert got["accents"] == ["American", "British"] and got["default"] == "American"


async def test_no_accent_given_is_american(queued):
    out = await make(accent="")
    assert "result" in out
    assert queued[0].data["request"].accent == "American"


def test_the_skill_prefills_american():
    text = (SKILL / "SKILL.md").read_text()
    assert "prefilled with **American**" in text
    assert 'accent="American"' in text and 'accent="British"' not in text
