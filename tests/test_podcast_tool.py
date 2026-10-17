"""make_podcast, the podcast skill's chat tool: the chat only briefs the podcast. What it refuses, the job it queues
(a topic, a length and a brief; the writer writes the script later, in the job), a folder of its own for every
podcast, and the reply that says how long, from the voice engine chosen in Settings."""
import importlib.util
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from google.adk.tools import FunctionTool

from odie import voice
from odie.agent import turn
from odie.agent.tools.files import workspace
from odie.making import chat as making_chat
from odie.making import jobs, podcast
from odie.signin import state
from odie.store.db import Store

SKILL = Path(podcast.__file__).parent.parent / "skills" / "podcast"
GOLDEN = Path(__file__).parent / "golden" / "tool_declarations.json"


def load_tools():
    spec = importlib.util.spec_from_file_location("podcast_tools", SKILL / "tools.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tools = load_tools()


@pytest.fixture
def world(isolated_settings, tmp_path, monkeypatch):
    """A store for the voice and jobs.submit replaced by a recorder. Everything on disk is under tmp_path."""
    assert str(isolated_settings.data_dir).startswith(str(tmp_path))
    store = Store(tmp_path / "assistant.db")
    store.init_schema()
    monkeypatch.setitem(jobs.hooks, "store", store)
    submitted = []

    def record(job):
        submitted.append(job)
        return len(submitted)

    monkeypatch.setattr(jobs, "submit", record)
    return store, submitted


async def call_as_adk_does(**args) -> dict:
    """make_podcast called the way ADK calls it: through its FunctionTool, with the model's arguments as they came."""
    chat = SimpleNamespace(session=SimpleNamespace(id="chat-7"))
    return await FunctionTool(tools.make_podcast).run_async(args=args, tool_context=chat)


# The refusals: each one comes back before anything is queued.

async def test_an_empty_topic_is_refused(world):
    out = await tools.make_podcast("   ", minutes=4)
    assert out["error"] == tools.NO_TOPIC and world[1] == []


async def test_a_null_topic_is_the_topic_refusal(world):
    out = await call_as_adk_does(topic=None)
    assert out["error"] == tools.NO_TOPIC and world[1] == []


@pytest.mark.parametrize("minutes", [0, 11, -1, 2.5])
async def test_minutes_outside_one_to_ten_are_refused_with_the_range(world, minutes):
    out = await tools.make_podcast("Tides", minutes=minutes)
    assert out["error"] == (f"minutes is the podcast's length in whole minutes, from 1 to 10 (the user's length, "
                            f"else 4), not {minutes}.")
    assert world[1] == []


@pytest.mark.parametrize("minutes", ["4", " 4 ", 4.0])
async def test_minutes_as_text_or_a_whole_float_are_read_as_the_number(world, minutes):
    out = await call_as_adk_does(topic="Tides", minutes=minutes)
    assert "result" in out, out
    assert world[1][0].minutes == 4 and type(world[1][0].minutes) is int


async def test_minutes_as_text_that_isnt_a_number_are_refused_naming_the_text(world):
    out = await call_as_adk_does(topic="Tides", minutes="four")
    assert "from 1 to 10" in out["error"] and "got the text 'four'" in out["error"] and world[1] == []


async def test_null_brief_and_minutes_are_read_as_not_given(world):
    out = await call_as_adk_does(topic="Tides", minutes=None, brief=None)
    assert "result" in out, out
    job = world[1][0]
    assert (job.minutes, job.brief) == (4, "")


async def test_a_brief_over_6000_characters_is_refused(world):
    out = await tools.make_podcast("Tides", brief="x" * 6001)
    assert "6,001" in out["error"] and "at most 6,000" in out["error"] and "what the podcast needs" in out["error"]
    assert world[1] == []
    assert "result" in await tools.make_podcast("Tides", brief="x" * 6000)


@pytest.fixture
def private_chat(world):
    """Signed-in browsing on, and a chat that read amazon.in this turn: a private chat, as the guard sees it."""
    store, _submitted = world
    state.turn_on(store, accepted=True, version=state.VERSION, now=datetime(2026, 10, 17, 9, 0, tzinfo=UTC))
    token = turn.PRIVATE.set({"amazon.in"})
    yield
    turn.PRIVATE.reset(token)


async def test_a_private_chat_with_a_cloud_voice_is_refused_before_anything_is_made(world, private_chat, monkeypatch):
    monkeypatch.setattr(voice, "get_tts", lambda store: ("openai", "cedar"))
    out = await tools.make_podcast("My orders this month", brief="Asha's three orders: a kettle, …")
    assert out["error"] == tools.PRIVATE_CLOUD_VOICE and "Settings → Voice" in out["error"]
    assert world[1] == []
    from odie.agent.tools.files import workspace
    assert not (workspace() / podcast.FOLDER).exists()  # no folder made


async def test_a_private_chat_with_odies_own_voice_is_queued(world, private_chat, monkeypatch):
    monkeypatch.setattr(voice, "get_tts", lambda store: ("kokoro", "af_heart"))
    out = await tools.make_podcast("My orders this month", brief="Asha's three orders.")
    assert "result" in out and len(world[1]) == 1


async def test_a_chat_that_isnt_private_is_queued_with_a_cloud_voice(world, monkeypatch):
    monkeypatch.setattr(voice, "get_tts", lambda store: ("openai", "cedar"))
    out = await tools.make_podcast("Tides")
    assert "result" in out and len(world[1]) == 1


# A good call: the job carries what the writer needs, and no script.

async def test_a_good_call_queues_a_podcast_job_with_the_topic_minutes_and_brief(world, tmp_path):
    _store, submitted = world
    chat = SimpleNamespace(session=SimpleNamespace(id="chat-7"))
    brief = "For Asha, who sails. 1. The moon pulls the sea. 2. Two bulges, two tides a day."
    out = await tools.make_podcast(" How tides work ", minutes=3, brief=brief, tool_context=chat)
    assert "result" in out, out
    job = submitted[0]
    assert (job.topic, job.title, job.minutes, job.brief) == ("How tides work", "How tides work", 3, brief)
    assert job.kind == "podcast" and job.data == {} and job.voice_name == ""
    assert job.slug == "how-tides-work" and job.session_id == "chat-7"
    assert job.folder.is_dir() and job.folder.parent.name == "podcasts"
    assert str(job.folder).startswith(str(tmp_path))


async def test_the_length_defaults_to_four_minutes(world):
    await tools.make_podcast("Tides")
    assert world[1][0].minutes == 4


async def test_the_same_topic_twice_gets_two_folders(world):
    _store, submitted = world
    await tools.make_podcast("How Tides Work!")
    await tools.make_podcast("How Tides Work!")
    first, second = submitted
    assert first.folder.name == "how-tides-work" and second.folder.name == "how-tides-work-2"
    assert second.slug == "how-tides-work-2"


# The estimate and the reply.

def test_the_voice_speaks_ten_times_real_time_on_this_computer_and_about_real_time_with_openai():
    assert tools.speaking_speed("kokoro") == 10
    assert tools.speaking_speed("maya1") == 10  # a podcast with Maya1 chosen is spoken by Kokoro (podcast_voices)
    assert tools.speaking_speed("openai") == 1


def test_speaking_takes_whole_minutes_rounded_up():
    assert [tools.speaking_minutes(m, "kokoro") for m in (1, 4, 10)] == [1, 1, 1]
    assert [tools.speaking_minutes(m, "openai") for m in (1, 4, 10)] == [1, 4, 10]


def test_the_estimate_is_the_writing_plus_the_speaking():
    assert tools.minutes_to_make(4, "kokoro") == (2, 3)  # 1–2 writing + 1 speaking
    assert tools.minutes_to_make(4, "openai") == (5, 6)  # 1–2 writing + 4 speaking
    assert tools.minutes_to_make(10, "openai") == (11, 12)


async def test_the_reply_says_how_long_from_the_chosen_engine_and_that_the_chat_stays_free(world, monkeypatch):
    out = await tools.make_podcast("Tides", minutes=4)
    assert out["result"].startswith("Making it now: about 2–3 minutes (writing the script, then speaking it in two "
                                    "voices). It'll appear in this chat, with a ping on the phone")
    assert "keep chatting" in out["result"]

    monkeypatch.setattr(voice, "get_tts", lambda store: ("openai", "cedar"))
    monkeypatch.setattr(jobs, "submit", lambda job: 1)
    cloud = await tools.make_podcast("Tides", minutes=4)
    assert cloud["result"].startswith("Making it now: about 5–6 minutes")

    monkeypatch.setattr(jobs, "submit", lambda job: 2)
    queued = await tools.make_podcast("Tides", minutes=4)
    assert queued["result"].startswith("It's number 2 in line, about 5–6 minutes after the one before.")
    assert re.search(r"about \d+–\d+ minutes", queued["result"])


# What the chat model is offered.

def test_the_skill_offers_only_make_podcast_without_an_approval_card(isolated_settings, tmp_path):
    from odie.skills.registry import discover
    store = Store(tmp_path / "skills.db")
    store.init_schema()
    entry = {e.name: e for e in discover(store, user_dir=tmp_path / "none")}["podcast"]
    assert entry.status == "ok" and entry.tools == ["make_podcast"]
    assert "podcast" in entry.description.lower()
    assert not any(tool._require_confirmation for tool in entry.tool_objs)


def test_the_declaration_has_exactly_topic_minutes_brief_and_sources():
    declaration = FunctionTool(tools.make_podcast)._get_declaration()
    properties = declaration.parameters_json_schema["properties"]
    assert sorted(properties) == ["brief", "minutes", "sources", "topic"]
    assert declaration.parameters_json_schema["required"] == ["topic"]

    golden = {d["name"]: d for d in json.loads(GOLDEN.read_text())}
    assert sorted(golden["make_podcast"]["parameters_json_schema"]["properties"]) == sorted(properties)
    assert "submit_podcast" not in golden  # the writer's tool, never the chat's
    assert "style" not in golden["speak"]["parameters_json_schema"]["properties"]


def test_the_skill_says_how_to_write_the_brief():
    text = (SKILL / "SKILL.md").read_text()
    assert "make_podcast(" in text and "brief" in text and "can't see" in text and "6,000" in text
    assert "our session" in text.lower() and "decisions" in text  # a podcast of this chat: the brief carries it
    assert "no emojis" in text
    assert 'style="podcast"' not in text and "speak(" not in text and "Host A:" not in text  # the writer's business
    assert len(text.split("---", 2)[2].split()) < 450  # the body is short: the writer has the podcast rules


# Sources: what the user gave, read by Odie's code and put after the brief, word for word.

TIDES = "Asha's notes on tides.\n\n| place | high tide |\n|---|---|\n| Goa | 2.1 m |"


async def test_my_message_goes_into_the_jobs_brief_after_the_plan(world):
    _store, submitted = world
    chat = SimpleNamespace(session=SimpleNamespace(id="chat-7"))
    token = turn.USER_TEXT.set(TIDES)  # the runner sets the user's words for the turn's tools
    try:
        out = await tools.make_podcast("How tides work", brief="For a ten-year-old. Show the table.",
                                      sources=["my message"], tool_context=chat)
    finally:
        turn.USER_TEXT.reset(token)
    assert "result" in out, out
    brief = submitted[0].brief
    assert brief.startswith("For a ten-year-old. Show the table.")
    assert "## Source material" in brief and TIDES in brief and "[context:" not in brief


async def test_a_workspace_file_is_quoted_word_for_word_into_the_jobs_brief(world):
    _store, submitted = world
    (workspace() / "tides.md").write_text(TIDES, encoding="utf-8")
    out = await tools.make_podcast("How tides work", brief="For Asha.", sources=["tides.md"])
    assert "result" in out, out
    brief = submitted[0].brief
    assert brief.startswith("For Asha.") and "### File: tides.md" in brief and TIDES in brief


async def test_the_sources_text_reaches_brief_md_when_the_job_is_written(world):
    _store, submitted = world
    (workspace() / "tides.md").write_text(TIDES, encoding="utf-8")
    await tools.make_podcast("How tides work", brief="For Asha.", sources=["tides.md"])
    job = submitted[0]
    jobs.write_brief(job)
    assert TIDES in (job.folder / "brief.md").read_text(encoding="utf-8")


async def test_a_source_that_cant_be_read_is_an_error_and_nothing_is_queued(world):
    out = await tools.make_podcast("How tides work", brief="For Asha.", sources=["../../outside.txt"])
    assert "workspace" in out["error"] and world[1] == []
    out = await tools.make_podcast("How tides work", sources=["a.txt"] * 6)
    assert "at most 5" in out["error"] and world[1] == []
    assert not (workspace() / "podcasts").exists()  # no folder made for a refused podcast


@pytest.mark.parametrize("given", [None, []])
async def test_no_sources_leaves_the_brief_as_it_is(world, given):
    out = await call_as_adk_does(topic="Tides", brief="For Asha.", sources=given)
    assert "result" in out, out
    assert world[1][0].brief == "For Asha."


async def test_sources_sent_as_json_text_are_read_as_the_list(world):
    out = await call_as_adk_does(topic="How tides work", brief="For Asha.", sources='["my message"]')
    assert "error" in out and "user's message" in out["error"]  # read as the list: no user turn here, so refused


async def test_sources_that_arent_a_list_are_an_error(world):
    out = await call_as_adk_does(topic="How tides work", sources={"note": "Tides"})
    assert "list" in out["error"] and world[1] == []


async def test_a_brief_over_the_limit_is_told_to_use_sources(world):
    out = await tools.make_podcast("Tides", brief="x" * 6001)
    assert out["error"].endswith(making_chat.USE_SOURCES) and world[1] == []
    assert making_chat.USE_SOURCES == "Pass what the user gave in sources instead of copying it."


def test_the_declaration_offers_sources_last_as_a_list_of_texts_or_nothing():
    declaration = FunctionTool(tools.make_podcast)._get_declaration()
    properties = declaration.parameters_json_schema["properties"]
    assert list(properties)[-1] == "sources"
    assert properties["sources"]["anyOf"][0] == {"items": {"type": "string"}, "type": "array"}
    golden = {d["name"]: d for d in json.loads(GOLDEN.read_text())}
    assert golden["make_podcast"]["parameters_json_schema"]["properties"]["sources"] == properties["sources"]


def test_the_skill_says_to_pass_what_the_user_gave_in_sources():
    text = (SKILL / "SKILL.md").read_text()
    assert "`sources`" in text and "my message" in text and "instead of" in text
