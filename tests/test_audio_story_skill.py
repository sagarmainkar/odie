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
    assert got["engine"] == "phonon" and got["accent"] == "British"
    assert [o["value"] for o in got["voices"]] == ["Maeve", "Alfie"]
    assert got["voices"][0]["note"].startswith("woman · ") and got["voices"][1]["note"].startswith("man · ")
    assert all(len(o["note"]) <= 80 for o in got["voices"] + got["characters"])
    captain = next(o for o in got["characters"] if o["value"] == "Captain Silas Blackwater")
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
    assert asked and [o["value"] for o in got["voices"]] == ["Zoey"]


def test_kokoro_has_indian_voices_and_no_characters(store, monkeypatch):
    choose(store, "kokoro", monkeypatch)
    got = asyncio.run(tools()["story_voices"].func(accent="Indian"))
    assert got["engine"] == "kokoro" and [o["value"] for o in got["voices"]] == ["hf_alpha", "hf_beta", "hm_omega", "hm_psi"]
    assert got["characters"] == []
    assert got["voices"][0] == {"value": "hf_alpha", "label": "Alpha", "note": "woman", "preview": "/api/voice/preview/kokoro/hf_alpha"}


def test_openai_takes_any_voice_and_adds_the_accent_in_the_story(store, monkeypatch):
    choose(store, "openai", monkeypatch)
    got = asyncio.run(tools()["story_voices"].func(accent="Indian"))
    assert got["engine"] == "openai" and got["characters"] == []
    assert {o["value"] for o in got["voices"]} == {v["id"] for v in voice.VOICES}
    marin = next(o for o in got["voices"] if o["value"] == "marin")
    assert marin["note"] == "woman · accent added in the story" and marin["preview"] == "/api/voice/preview/openai/marin"


def test_no_accent_yet_lists_the_accents_and_a_wrong_one_is_said_plainly(store, monkeypatch):
    choose(store, "kokoro", monkeypatch)
    assert asyncio.run(tools()["story_voices"].func()) == {"engine": "kokoro", "accents": ["American", "British", "Indian"]}
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
