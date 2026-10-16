"""make_video, the explainer-video skill's tool: what it refuses before anything is drawn (in the order the spec
gives), the page checked in a real browser, a folder of its own for every video, and the reply that says how long."""
import importlib.util
import re
from pathlib import Path

import pytest

from odie import browser as odie_browser
from odie import voice
from odie.browser import RENDER_ARGS, find
from odie.browser.engine import Browser, BrowserError, BrowserTimeout
from odie.store.db import Store
from odie.video import jobs, page

SKILL = Path(page.__file__).parent.parent / "skills" / "explainer-video"
SAMPLE = (Path(page.__file__).parent / "kit" / "sample.html").read_text()
BIN = find.installed()
needs_browser = pytest.mark.skipif(BIN is None, reason="no Chrome, Edge, Chromium or Brave here")


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


@pytest.fixture
def no_page_check(monkeypatch):
    """page.check stands in as "the page is fine", and records that it ran."""
    calls = []

    async def fine(body, narration, browser):
        calls.append(body)  # None: no problem

    monkeypatch.setattr(page, "check", fine)
    monkeypatch.setattr(odie_browser, "_render", object())  # never start a real browser for these
    return calls


async def test_no_browser_is_said_first(world, monkeypatch):
    monkeypatch.setattr(find, "browser_binary", lambda: None)
    out = await tools.make_video("T", ["Hi."], "<script></script>")
    assert "needs Chrome, Edge, Brave or Chromium" in out["error"]


async def test_too_long_is_refused(world):
    out = await tools.make_video("T", ["word " * 140] * 7, "<script></script>")
    assert "6 minutes" in out["error"]


async def test_a_scene_over_the_speech_limit_is_named(world):
    out = await tools.make_video("T", ["ok.", "x" * 4001], "<script></script>")
    assert "scene 2" in out["error"]


async def test_no_narration_and_a_silent_scene_are_refused(world):
    assert "narration" in (await tools.make_video("T", [], "<script></script>"))["error"]
    assert "scene 2" in (await tools.make_video("T", ["Hi.", "  "], "<script></script>"))["error"]


async def test_more_than_40_scenes_are_refused_with_the_limit(world, no_page_check):
    out = await tools.make_video("T", ["Hi."] * 41, "<script></script>")
    assert "41 scenes" in out["error"] and "at most 40" in out["error"] and no_page_check == []
    assert "result" in await tools.make_video("T", ["Hi."] * 40, "<script></script>")


async def test_a_page_over_300_kb_is_refused_with_the_limit(world, no_page_check):
    out = await tools.make_video("T", ["Hi."], "<script>" + "x" * 300_000 + "</script>")
    assert "300 KB" in out["error"] and no_page_check == [] and world[1] == []
    assert "result" in await tools.make_video("T", ["Hi."], "x" * 300_000)


async def test_a_voice_from_the_other_engine_is_refused_before_the_page_is_checked(world, no_page_check):
    store, submitted = world
    voice.set_tts(store, engine="kokoro", voice="af_heart")
    out = await tools.make_video("T", ["Hi."], "<script></script>", voice_name="cedar")
    assert "cedar" in out["error"] and "Settings" in out["error"]
    assert no_page_check == [] and submitted == []


async def test_a_voice_of_the_chosen_engine_goes_to_the_job_by_its_id(world, no_page_check):
    store, submitted = world
    voice.set_tts(store, engine="kokoro", voice="af_heart")
    out = await tools.make_video("T", ["Hi."], "<script></script>", voice_name="Michael")
    assert "result" in out and submitted[0].voice_name == "am_michael"


async def test_a_page_that_never_finishes_drawing_is_told_as_a_hang(world, monkeypatch):
    async def hangs(body, narration, browser):
        raise BrowserTimeout("The page didn't answer within 120 s.")

    monkeypatch.setattr(page, "check", hangs)
    monkeypatch.setattr(odie_browser, "_render", object())
    out = await tools.make_video("T", ["Hi."], "<script>while (true) {}</script>")
    assert out["error"].startswith("The page didn't finish drawing in time (a loop that never ends?): ")


async def test_a_browser_that_fails_otherwise_is_told_in_its_own_words(world, monkeypatch):
    async def no_start(body, narration, browser):
        raise BrowserError("The browser didn't start (another copy of Odie's browser may still be running).")

    monkeypatch.setattr(page, "check", no_start)
    monkeypatch.setattr(odie_browser, "_render", object())
    out = await tools.make_video("T", ["Hi."], "<script></script>")
    assert out["error"] == "The browser didn't start (another copy of Odie's browser may still be running)."


async def test_a_page_problem_comes_back_to_fix(world, monkeypatch):
    async def mismatch(body, narration, browser):
        return "The page has 2 scenes but there are 1 narration parts: one narration per scene."

    monkeypatch.setattr(page, "check", mismatch)
    monkeypatch.setattr(odie_browser, "_render", object())
    out = await tools.make_video("T", ["Hi."], SAMPLE)
    assert "2 scenes" in out["error"] and world[1] == []


async def test_the_same_title_twice_gets_two_folders(world, no_page_check):
    _store, submitted = world
    await tools.make_video("How Attention Works!", ["Hi."], "<script></script>")
    await tools.make_video("How Attention Works!", ["Hi."], "<script></script>")
    first, second = submitted
    assert first.folder.name == "how-attention-works" and second.folder.name == "how-attention-works-2"
    assert first.folder.parent == second.folder.parent and first.folder.parent.name == "videos"
    assert second.slug == "how-attention-works-2"


def test_the_slug_is_plain_lower_case_with_hyphens():
    assert tools.slug_of("Speculative decoding") == "speculative-decoding"
    assert tools.slug_of("TCP/IP, explained") == "tcp-ip-explained"
    assert tools.slug_of("¿Qué?") == "qu"
    assert tools.slug_of("!!!") == "video"


def test_the_estimate_counts_narrating_rendering_and_joining_in_seconds():
    # the first live run: 6 scenes, 96.25 s of speech, a 98.75 s video of 2,963 frames, made in well under a minute
    assert round(tools.making_seconds(96.25, 2963), 1) == 62.0  # 9.6 narrating + 42.3 drawing + 10 joining
    three_minutes = ["word " * 60] * 7  # 420 words: 180 s of speech, 183 s of video with the breaths, 5,490 frames
    assert tools.minutes_to_make(three_minutes) == 2  # 18 + 78.4 + 10 = 106.4 s
    assert tools.minutes_to_make(["Hi."]) == 1  # never less than a minute


async def test_the_reply_says_how_long_and_that_the_chat_stays_free(world, no_page_check, monkeypatch):
    out = await tools.make_video("T", ["word " * 60] * 7, "<script></script>")
    assert out["result"].startswith("Making it now: about 2–3 minutes.")
    assert "keep chatting" in out["result"] and "don't repeat the script" in out["result"]

    monkeypatch.setattr(jobs, "submit", lambda job: 2)
    queued = await tools.make_video("T", ["word " * 60] * 7, "<script></script>")
    assert "number 2 in line, about 2–3 minutes after the one before" in queued["result"]
    assert re.search(r"about \d+–\d+ minutes", queued["result"])


def test_the_skill_offers_the_tool_without_an_approval_card(isolated_settings, tmp_path):
    from odie.skills.registry import discover
    store = Store(tmp_path / "skills.db")
    store.init_schema()
    entry = {e.name: e for e in discover(store, user_dir=tmp_path / "none")}["explainer-video"]
    assert entry.status == "ok" and entry.tools == ["make_video"]
    assert entry.skill.frontmatter.metadata["title"] == "Explainer videos"
    assert not entry.tool_objs[0]._require_confirmation


def test_videos_are_drawn_in_a_browser_cut_off_from_the_network(isolated_settings, monkeypatch):
    monkeypatch.setattr(odie_browser, "_render", None)
    browser = odie_browser.render_browser()  # made, not started
    assert browser.extra_args == RENDER_ARGS
    assert "--proxy-server=socks5://127.0.0.1:9" in browser.extra_args
    assert str(browser.profile).startswith(str(isolated_settings.data_dir))


def test_the_skill_states_the_texts_defaults_and_a_reply_without_emojis():
    skill = (SKILL / "SKILL.md").read_text()
    kit = (Path(page.__file__).parent / "kit" / "video.js").read_text()
    assert "x: W / 2, y: H / 2, size: 48, color: colors.text" in kit  # what the kit really does
    assert "`x` (960), `y` (540), `size` (48), `color` (`s.colors.text`)" in skill
    assert "y defaults to 540" in skill and "with no emojis" in skill


def test_the_skill_carries_the_sample_page_verbatim():
    assert SAMPLE.strip() in (SKILL / "SKILL.md").read_text()


@needs_browser
async def test_a_good_request_starts_the_job_and_says_how_long(world, tmp_path, monkeypatch):
    _store, submitted = world
    real = Browser(tmp_path / "render", BIN, extra_args=RENDER_ARGS)
    monkeypatch.setattr(odie_browser, "_render", real)
    try:
        out = await tools.make_video("Attention", ["word " * 20, "word " * 20], SAMPLE)
    finally:
        await real.close()
    assert out["result"].startswith("Making it now: about "), out
    job = submitted[0]
    assert job.title == "Attention" and job.slug == "attention" and job.body == SAMPLE
    assert job.narration == ["word " * 20, "word " * 20] and job.voice_name == "" and job.session_id is None
    assert job.folder.is_dir() and str(job.folder).startswith(str(tmp_path))
