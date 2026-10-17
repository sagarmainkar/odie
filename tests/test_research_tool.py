"""make_research, the research skill's chat tool: the chat only briefs the research. What it refuses (an empty topic,
a brief over 6,000 characters, sources that can't be read, and any request in a private chat), the job it queues (a
topic and a brief; the writer searches, reads and writes later, in the job), a folder of its own for every report,
and the reply that says it takes about 5–15 minutes."""
import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from google.adk.tools import FunctionTool

from odie.agent import turn
from odie.agent.tools.files import workspace
from odie.making import chat as making_chat
from odie.making import jobs, research
from odie.signin import state
from odie.store.db import Store

SKILL = Path(research.__file__).parent.parent / "skills" / "research"
GOLDEN = Path(__file__).parent / "golden" / "tool_declarations.json"


def load_tools():
    spec = importlib.util.spec_from_file_location("research_tools", SKILL / "tools.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tools = load_tools()


@pytest.fixture
def world(isolated_settings, tmp_path, monkeypatch):
    """A store for the guard and jobs.submit replaced by a recorder. Everything on disk is under tmp_path."""
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
    """make_research called the way ADK calls it: through its FunctionTool, with the model's arguments as they came."""
    chat = SimpleNamespace(session=SimpleNamespace(id="chat-7"))
    return await FunctionTool(tools.make_research).run_async(args=args, tool_context=chat)


# The refusals: each one comes back before anything is queued.

async def test_an_empty_topic_is_refused(world):
    out = await tools.make_research("   ")
    assert out["error"] == tools.NO_TOPIC and world[1] == []


async def test_a_null_topic_and_brief_are_read_as_not_given(world):
    out = await call_as_adk_does(topic=None, brief=None)
    assert out["error"] == tools.NO_TOPIC and world[1] == []
    out = await call_as_adk_does(topic="Kettles", brief=None)
    assert "result" in out and world[1][0].brief == ""


async def test_a_brief_over_6000_characters_is_refused_and_told_to_use_sources(world):
    out = await tools.make_research("Kettles", brief="x" * 6001)
    assert "6,001" in out["error"] and "at most 6,000" in out["error"] and "what the research needs" in out["error"]
    assert out["error"].endswith(making_chat.USE_SOURCES)
    assert world[1] == []
    assert "result" in await tools.make_research("Kettles", brief="x" * 6000)


@pytest.fixture
def private_chat(world):
    """Signed-in browsing on, and a chat that read amazon.in this turn: a private chat, as the guard sees it."""
    store, _submitted = world
    state.turn_on(store, accepted=True, version=state.VERSION, now=datetime(2026, 10, 17, 9, 0, tzinfo=UTC))
    token = turn.PRIVATE.set({"amazon.in"})
    yield
    turn.PRIVATE.reset(token)


async def test_a_private_chat_is_refused_before_anything_is_made(world, private_chat):
    out = await tools.make_research("Kettle reviews", brief="Asha's last order was a glass kettle.")
    assert out["error"] == tools.PRIVATE_CHAT and "outside" in out["error"] and "private" in out["error"]
    assert world[1] == []
    assert not (workspace() / research.FOLDER).exists()  # no folder made


async def test_a_chat_that_isnt_private_is_queued(world):
    store, submitted = world
    state.turn_on(store, accepted=True, version=state.VERSION, now=datetime(2026, 10, 17, 9, 0, tzinfo=UTC))
    out = await tools.make_research("Kettle reviews")  # signed-in browsing on, but this chat read no signed-in page
    assert "result" in out and len(submitted) == 1


# A good call: the job carries what the writer needs.

async def test_a_good_call_queues_a_research_job_with_the_topic_and_brief(world, tmp_path):
    _store, submitted = world
    chat = SimpleNamespace(session=SimpleNamespace(id="chat-7"))
    brief = "For Asha: a kettle for a family of four, under ₹3,000. Steel or glass? Skip cordless travel kettles."
    out = await tools.make_research(" Which kettle to buy ", brief=brief, tool_context=chat)
    assert "result" in out, out
    job = submitted[0]
    assert (job.topic, job.title, job.brief) == ("Which kettle to buy", "Which kettle to buy", brief)
    assert job.kind == "research" and job.data == {}
    assert job.slug == "which-kettle-to-buy" and job.session_id == "chat-7"
    assert job.folder.is_dir() and job.folder.parent.name == "research"
    assert str(job.folder).startswith(str(tmp_path))


async def test_the_same_topic_twice_gets_two_folders(world):
    _store, submitted = world
    await tools.make_research("Kettles!")
    await tools.make_research("Kettles!")
    first, second = submitted
    assert first.folder.name == "kettles" and second.folder.name == "kettles-2"


# The reply.

async def test_the_reply_says_five_to_fifteen_minutes_and_that_the_chat_stays_free(world, monkeypatch):
    out = await tools.make_research("Kettles")
    assert out["result"].startswith("Making it now: about 5–15 minutes (searching and reading, then writing). "
                                    "It'll appear in this chat, with a ping on the phone")
    assert "keep chatting" in out["result"]

    monkeypatch.setattr(jobs, "submit", lambda job: 2)
    queued = await tools.make_research("Kettles")
    assert queued["result"].startswith("It's number 2 in line, about 5–15 minutes after the one before.")


# Sources: what the user gave, read by Odie's code and put after the brief, word for word.

NOTES = "Asha's kettle notes.\n\n| model | litres |\n|---|---|\n| Prestige | 1.7 |"


async def test_my_message_goes_into_the_jobs_brief_after_the_plan(world):
    _store, submitted = world
    token = turn.USER_TEXT.set(NOTES)  # the runner sets the user's words for the turn's tools
    try:
        out = await tools.make_research("Kettles", brief="Compare these.", sources=["my message"])
    finally:
        turn.USER_TEXT.reset(token)
    assert "result" in out, out
    brief = submitted[0].brief
    assert brief.startswith("Compare these.") and "## Source material" in brief and NOTES in brief


async def test_a_workspace_file_is_quoted_word_for_word_into_the_jobs_brief(world):
    _store, submitted = world
    (workspace() / "kettles.md").write_text(NOTES, encoding="utf-8")
    out = await tools.make_research("Kettles", brief="For Asha.", sources=["kettles.md"])
    assert "result" in out, out
    assert "### File: kettles.md" in submitted[0].brief and NOTES in submitted[0].brief


async def test_a_source_that_cant_be_read_is_an_error_and_nothing_is_queued(world):
    out = await tools.make_research("Kettles", sources=["../../outside.txt"])
    assert "workspace" in out["error"] and world[1] == []
    out = await call_as_adk_does(topic="Kettles", sources={"note": "Kettles"})
    assert "list" in out["error"] and world[1] == []
    assert not (workspace() / research.FOLDER).exists()  # no folder made for refused research


# What the chat model is offered.

def test_the_skill_offers_only_make_research_without_an_approval_card(isolated_settings, tmp_path):
    from odie.skills.registry import discover
    store = Store(tmp_path / "skills.db")
    store.init_schema()
    entry = {e.name: e for e in discover(store, user_dir=tmp_path / "none")}["research"]
    assert entry.status == "ok" and entry.tools == ["make_research"]
    assert "research" in entry.description.lower()
    assert not any(tool._require_confirmation for tool in entry.tool_objs)


def test_the_declaration_has_exactly_topic_brief_and_sources():
    declaration = FunctionTool(tools.make_research)._get_declaration()
    properties = declaration.parameters_json_schema["properties"]
    assert list(properties) == ["topic", "brief", "sources"]
    assert declaration.parameters_json_schema["required"] == ["topic"]

    golden = {d["name"]: d for d in json.loads(GOLDEN.read_text())}
    assert golden["make_research"]["parameters_json_schema"]["properties"] == properties
    assert "submit_research" not in golden  # the writer's tool, never the chat's


def test_the_skill_says_when_to_use_it_and_how_to_brief():
    text = (SKILL / "SKILL.md").read_text()
    assert "make_research(" in text and "brief" in text and "can't see" in text and "6,000" in text
    assert "compare" in text and "look into" in text and "find out" in text
    assert "`sources`" in text and "my message" in text and "instead of" in text
    assert "private" in text and "no emojis" in text
    assert len(text.split("---", 2)[2].split()) < 450  # the body is short: the writer has the research rules
