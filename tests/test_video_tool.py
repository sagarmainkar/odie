"""make_video, the explainer-video skill's chat tool: the chat only briefs the video. What it refuses (in the order the
spec gives), the job it queues (a topic, a length and a brief; the writer writes the page later, in the job), a folder
of its own for every video, and the reply that says how long."""
import importlib.util
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from google.adk.tools import FunctionTool

from odie import browser as odie_browser
from odie import voice
from odie.browser import RENDER_ARGS, find
from odie.store.db import Store
from odie.video import jobs, page

SKILL = Path(page.__file__).parent.parent / "skills" / "explainer-video"
GOLDEN = Path(__file__).parent / "golden" / "tool_declarations.json"


def load_tools():
    spec = importlib.util.spec_from_file_location("explainer_video_tools", SKILL / "tools.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


tools = load_tools()


@pytest.fixture
def world(isolated_settings, tmp_path, monkeypatch):
    """A browser said to be present, a store for the voice, and jobs.submit replaced by a recorder. Everything on disk
    is under tmp_path."""
    assert str(isolated_settings.data_dir).startswith(str(tmp_path))
    store = Store(tmp_path / "assistant.db")
    store.init_schema()
    monkeypatch.setitem(jobs.hooks, "store", store)
    monkeypatch.setattr(find, "browser_binary", lambda: "/Applications/Some Browser")
    submitted = []

    def record(job):
        submitted.append(job)
        return len(submitted)

    monkeypatch.setattr(jobs, "submit", record)
    return store, submitted


# The refusals, in order: each one comes back before anything is queued.

async def test_no_browser_is_said_first_even_with_other_problems(world, monkeypatch):
    monkeypatch.setattr(find, "browser_binary", lambda: None)
    out = await tools.make_video("", minutes=9, brief="x" * 7000, voice_name="nobody")
    assert "needs Chrome, Edge, Brave or Chromium" in out["error"] and world[1] == []


async def test_an_empty_topic_is_refused(world):
    out = await tools.make_video("   ", minutes=9)
    assert "topic" in out["error"] and world[1] == []


@pytest.mark.parametrize("minutes", [0, 7, -1])
async def test_minutes_outside_one_to_six_are_refused_with_the_range(world, minutes):
    out = await tools.make_video("Attention", minutes=minutes)
    assert "from 1 to 6" in out["error"] and str(minutes) in out["error"] and world[1] == []


async def test_minutes_that_arent_a_whole_number_are_refused(world):
    out = await tools.make_video("Attention", minutes=2.5)
    assert "from 1 to 6" in out["error"] and world[1] == []


async def call_as_adk_does(**args) -> dict:
    """make_video called the way ADK calls it: through its FunctionTool, with the model's arguments as they came."""
    chat = SimpleNamespace(session=SimpleNamespace(id="chat-7"))
    return await FunctionTool(tools.make_video).run_async(args=args, tool_context=chat)


@pytest.mark.parametrize("minutes", [2.0, "2", " 2 "])
async def test_minutes_as_a_whole_float_or_text_are_read_as_the_number(world, minutes):
    out = await call_as_adk_does(topic="Attention", minutes=minutes)
    assert "result" in out, out
    assert world[1][0].minutes == 2 and type(world[1][0].minutes) is int


@pytest.mark.parametrize("minutes", ["two", "2.5", "²"])  # "²" is a digit to Python, but no number
async def test_minutes_as_text_that_isnt_a_whole_number_are_refused_naming_the_text(world, minutes):
    out = await call_as_adk_does(topic="Attention", minutes=minutes)
    assert "from 1 to 6" in out["error"] and f"got the text '{minutes}'" in out["error"] and world[1] == []


async def test_text_minutes_outside_the_range_are_refused_with_the_number(world):
    out = await call_as_adk_does(topic="Attention", minutes="9")
    assert "from 1 to 6" in out["error"] and "not 9" in out["error"] and world[1] == []


async def test_null_brief_voice_and_minutes_are_read_as_not_given(world):
    out = await call_as_adk_does(topic="Attention", minutes=None, brief=None, voice_name=None)
    assert "result" in out, out
    job = world[1][0]
    assert (job.minutes, job.brief, job.voice_name) == (2, "", "")


async def test_a_null_topic_is_the_topic_refusal(world):
    out = await call_as_adk_does(topic=None)
    assert out["error"] == tools.NO_TOPIC and world[1] == []


async def test_a_brief_over_6000_characters_is_refused(world):
    out = await tools.make_video("Attention", brief="x" * 6001, voice_name="nobody")
    assert "6,001" in out["error"] and "6,000" in out["error"] and world[1] == []
    assert "result" in await tools.make_video("Attention", brief="x" * 6000)


async def test_a_voice_from_the_other_engine_is_refused_and_nothing_is_queued(world):
    store, submitted = world
    voice.set_tts(store, engine="kokoro", voice="af_heart")
    out = await tools.make_video("Attention", voice_name="cedar")
    assert "cedar" in out["error"] and "Settings" in out["error"] and submitted == []


async def test_a_voice_of_the_chosen_engine_goes_to_the_job_by_its_id(world):
    store, submitted = world
    voice.set_tts(store, engine="kokoro", voice="af_heart")
    out = await tools.make_video("Attention", voice_name="Michael")
    assert "result" in out and submitted[0].voice_name == "am_michael"


# A good call: the job carries what the writer needs, and no page.

async def test_a_good_call_queues_a_job_with_the_topic_minutes_and_brief(world, tmp_path):
    _store, submitted = world
    chat = SimpleNamespace(session=SimpleNamespace(id="chat-7"))
    brief = "For Asha, a beginner. 1. Words become vectors. 2. Each word asks every other word how much to listen."
    out = await tools.make_video(" How attention works ", minutes=3, brief=brief, tool_context=chat)
    assert "result" in out, out
    job = submitted[0]
    assert (job.topic, job.title, job.minutes, job.brief) == ("How attention works", "How attention works", 3, brief)
    assert job.narration == [] and job.body == "" and job.voice_name == ""
    assert job.slug == "how-attention-works" and job.session_id == "chat-7"
    assert job.folder.is_dir() and str(job.folder).startswith(str(tmp_path))
    assert jobs.needs_writing(job)


async def test_the_length_defaults_to_two_minutes(world):
    await tools.make_video("Attention")
    assert world[1][0].minutes == 2


async def test_the_same_topic_twice_gets_two_folders(world):
    _store, submitted = world
    await tools.make_video("How Attention Works!")
    await tools.make_video("How Attention Works!")
    first, second = submitted
    assert first.folder.name == "how-attention-works" and second.folder.name == "how-attention-works-2"
    assert first.folder.parent == second.folder.parent and first.folder.parent.name == "videos"
    assert second.slug == "how-attention-works-2"


def test_the_slug_is_plain_lower_case_with_hyphens():
    assert tools.slug_of("Speculative decoding") == "speculative-decoding"
    assert tools.slug_of("TCP/IP, explained") == "tcp-ip-explained"
    assert tools.slug_of("¿Qué?") == "qu"
    assert tools.slug_of("!!!") == "video"


# The estimate and the reply.

def test_the_making_counts_narrating_rendering_and_joining_in_seconds():
    # the first live run: 6 scenes, 96.25 s of speech, a 98.75 s video of 2,963 frames, made in well under a minute
    assert round(tools.making_seconds(96.25, 2963), 1) == 62.0  # 9.6 narrating + 42.3 drawing + 10 joining


def test_the_estimate_adds_two_minutes_of_writing_to_the_making():
    # 2 minutes: 120 s of speech in 6 scenes, 122.5 s of video, 3,675 frames -> 12 + 52.5 + 10 = 74.5 s -> 1, + 2
    assert tools.minutes_to_make(2) == 3
    assert tools.minutes_to_make(1) == 3  # 42.1 s of making -> at least 1, + 2
    assert tools.minutes_to_make(6) == 5  # 203.9 s -> 3, + 2


async def test_the_reply_says_how_long_and_that_the_chat_stays_free(world, monkeypatch):
    out = await tools.make_video("Attention", minutes=2)
    assert out["result"].startswith("Making it now: about 3–5 minutes (writing the script and the animation, then "
                                    "drawing it). It'll appear in this chat, with a ping on the phone")
    assert "keep chatting" in out["result"]

    monkeypatch.setattr(jobs, "submit", lambda job: 2)
    queued = await tools.make_video("Attention", minutes=2)
    assert queued["result"].startswith("It's number 2 in line, about 3–5 minutes after the one before. It'll appear")
    assert re.search(r"about \d+–\d+ minutes", queued["result"]) and "keep chatting" in queued["result"]


# What the chat model is offered.

def test_the_skill_offers_only_make_video_without_an_approval_card(isolated_settings, tmp_path):
    from odie.skills.registry import discover
    store = Store(tmp_path / "skills.db")
    store.init_schema()
    entry = {e.name: e for e in discover(store, user_dir=tmp_path / "none")}["explainer-video"]
    assert entry.status == "ok" and entry.tools == ["make_video"]
    assert entry.skill.frontmatter.metadata["title"] == "Explainer videos"
    assert not any(tool._require_confirmation for tool in entry.tool_objs)


def test_the_declaration_has_exactly_topic_minutes_brief_and_voice_name():
    declaration = FunctionTool(tools.make_video)._get_declaration()
    properties = declaration.parameters_json_schema["properties"]
    assert sorted(properties) == ["brief", "minutes", "topic", "voice_name"]
    assert declaration.parameters_json_schema["required"] == ["topic"]

    golden = {d["name"]: d for d in json.loads(GOLDEN.read_text())}
    assert sorted(golden["make_video"]["parameters_json_schema"]["properties"]) == sorted(properties)
    assert "save_video_page" not in golden and "submit_video" not in golden  # the writer's tools, never the chat's


def test_the_skill_says_how_to_write_the_brief():
    text = (SKILL / "SKILL.md").read_text()
    assert "brief" in text and "can't see" in text and "6,000" in text
    assert "no emojis" in text and "save_video_page" not in text
    assert len(text.split("---", 2)[2].split()) < 500  # the body is short: the writer has the page contract


def test_videos_are_drawn_in_a_browser_cut_off_from_the_network(isolated_settings, monkeypatch):
    monkeypatch.setattr(odie_browser, "_render", None)
    browser = odie_browser.render_browser()  # made, not started
    assert browser.extra_args == RENDER_ARGS
    assert "--proxy-server=socks5://127.0.0.1:9" in browser.extra_args
    assert str(browser.profile).startswith(str(isolated_settings.data_dir))
