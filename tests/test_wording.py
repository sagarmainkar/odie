"""Model-facing text outside the main prompt speaks about "the user", with their name where it's known."""
import re

import httpx

HE = re.compile(r"\b(he|his|him|himself)\b", re.I)


def test_voice_instructions_name_the_user():
    from odie.voice import realtime_instructions
    assert "You are talking with Asha by voice, as Iris." in realtime_instructions("Iris", None, "", user="Asha")
    plain = realtime_instructions("Iris", None, "")
    assert "talking with the user by voice" in plain and not HE.search(plain)


def test_brief_system_names_the_user():
    from odie.jobs.brief import brief_system
    assert "Asha's morning brief" in brief_system("Asha") and "the user's morning brief" in brief_system("")
    assert not HE.search(brief_system("Asha"))


def test_voice_style_by_region():
    from odie.voice import transcription_prompt, tts_style
    assert "Indian English" in tts_style("IN") and "Indian" not in tts_style("DE")
    assert "Indian English" in transcription_prompt("IN") and transcription_prompt("US") == ""


async def test_profile_change_rebuilds_the_prompt(isolated_settings, tmp_path):
    from odie.app.main import create_app
    from odie.store.db import Store
    from tests.test_approvals import FakeRunner

    class Runner(FakeRunner):
        rebuilt = 0

        def invalidate_prompt(self):
            Runner.rebuilt += 1
    s = Store(tmp_path / "a.db")
    s.init_schema()
    app = create_app(runner=Runner(), store=s)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c, app.router.lifespan_context(app):
        await c.put("/api/profile", json={"user_name": "Asha"})
    assert Runner.rebuilt == 1


def test_memory_review_prompt_uses_no_male_pronoun():
    from odie.memory.review import SYSTEM
    assert not HE.search(SYSTEM)


def test_voice_topics_follow_the_install():
    from odie.voice import ask_tool, realtime_instructions
    bare = realtime_instructions("Odie", None, "", caps=frozenset())
    for word in ("mail", "calendar", "bills", "spending"):
        assert word not in bare, word
    assert "notes, reminders, memory, the news or the web" in bare
    assert "mail" not in ask_tool(frozenset())["description"] and "calendar" not in ask_tool(frozenset())["description"]
    everything = realtime_instructions("Odie", None, "")
    assert "their mail, calendar, bills, spending, notes" in everything  # unknown caps: as before
    assert "mail, calendar, notes" in ask_tool(None)["description"]
