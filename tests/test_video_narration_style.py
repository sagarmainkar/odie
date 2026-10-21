"""A video's own narration style for OpenAI's voice, OpenAI's voice models read from settings, and the video voice
pinned apart from the read-aloud voice.

The first four tests are the patch's rules: a style steers OpenAI and no style keeps today's instructions (same model);
Kokoro never sees a style; make_video keeps the style on the job, cut at 300 characters; a job's style reaches every
phrase OpenAI speaks for that video, and a job without one speaks as before."""
import importlib
import json

import httpx
import pytest

from odie import config, voice
from odie.making import jobs
from odie.secrets import save_secret
from odie.store.db import Store
from odie.video import kind, narrate
from tests.test_speak import kokoro
from tests.test_video_jobs import Chat, make_job, stand_in_render
from tests.test_video_tool import load_tools

tools = load_tools()

SCIENCE = "Curious science narrator. Calm, but lift slightly at the payoff. Slow down on numbers."
ONE_SECOND_OF_PCM = b"\x00\x01" * 24000  # what OpenAI's speech sends as "pcm": 24 kHz, 16-bit, mono


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    return s


def settings_from_env(monkeypatch, **values: str) -> None:
    """Sets ODIE_<NAME>=value for each one and reads the settings again, as Odie does when it starts.
    isolated_settings puts everything back after the test."""
    for name, value in values.items():
        monkeypatch.setenv(f"ODIE_{name}", value)
    importlib.reload(config)


def openai_recorder(sent: list) -> httpx.MockTransport:
    """OpenAI's speech endpoint: keeps each request's JSON body and answers with a second of PCM."""
    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, content=ONE_SECOND_OF_PCM)
    return httpx.MockTransport(handler)


def openai_chosen(store) -> None:
    save_secret("OPENAI_API_KEY", "sk-test-not-real-0123456789")  # the test's own settings folder
    voice.set_tts(store, engine="openai", voice="cedar")


# ── The patch's four tests ──

async def test_a_style_steers_openai_and_no_style_keeps_todays_instructions(store):
    sent = []
    await voice.tts("Hi.", "cedar", key="k", transport=openai_recorder(sent), style=SCIENCE)
    await voice.tts("Hi.", "cedar", key="k", transport=openai_recorder(sent))
    styled, plain = sent
    assert styled["instructions"] == SCIENCE
    assert plain["instructions"] == voice.tts_style(config.settings.country)
    assert styled["model"] == plain["model"] == "gpt-4o-mini-tts"  # the model stays: tts-1 ignores instructions


async def test_kokoro_never_sees_a_style(store):
    plain, styled = [], []
    await narrate.narrate(store, ["One.", "Two | three."], transport=kokoro(plain, 0.5))
    await narrate.narrate(store, ["One.", "Two | three."], transport=kokoro(styled, 0.5), style=SCIENCE)
    assert styled == plain  # the same requests, word for word
    assert all(set(call) == {"engine", "text", "voice", "lang"} for call in styled)  # no instructions of any kind


@pytest.fixture
def queue(store, monkeypatch, tmp_path):
    """make_video with a browser said to be present and jobs.submit replaced by a recorder; returns the jobs."""
    from odie.browser import find
    monkeypatch.setitem(jobs.hooks, "store", store)
    monkeypatch.setattr(find, "browser_binary", lambda: "/Applications/Some Browser")
    submitted = []

    def record(job):
        submitted.append(job)
        return len(submitted)

    monkeypatch.setattr(jobs, "submit", record)
    return submitted


async def test_make_video_keeps_the_style_on_the_job_cut_at_300_characters(queue):
    assert "result" in await tools.make_video("How tides work", style=SCIENCE)
    assert "result" in await tools.make_video("How tides work", style="Slow. " * 80)
    assert "result" in await tools.make_video("How tides work")
    given, long, none = queue
    assert given.data["style"] == SCIENCE
    assert len(long.data["style"]) == 300 and long.data["style"].startswith("Slow. Slow.")
    assert none.data["style"] == ""


async def test_a_jobs_style_reaches_every_phrase_openai_speaks_and_no_style_speaks_as_before(store, monkeypatch):
    openai_chosen(store)
    monkeypatch.setitem(jobs.hooks, "store", store)
    monkeypatch.setitem(jobs.hooks, "runner", Chat())
    monkeypatch.setattr(jobs, "send_to_all", lambda *args, **kwargs: 1)
    monkeypatch.setattr(kind, "render", stand_in_render)

    sent = []
    styled = make_job(slug="tides")
    styled.data["narration"] = ["Tides rise | and fall.", "Twice a day."]
    styled.data["style"] = SCIENCE
    await jobs.run(styled, browser=object(), transport=openai_recorder(sent))
    assert [call["input"] for call in sent] == ["Tides rise", "and fall.", "Twice a day."]
    assert {call["instructions"] for call in sent} == {SCIENCE}

    sent.clear()
    before_styles = make_job(slug="attention")  # data without "style", as every video made until now
    await jobs.run(before_styles, browser=object(), transport=openai_recorder(sent))
    assert {call["instructions"] for call in sent} == {voice.tts_style(config.settings.country)}
    assert {call["voice"] for call in sent} == {"cedar"}


# ── OpenAI's voice models are settings, so a retired model is a settings change ──

async def test_the_voice_models_default_to_todays_and_follow_their_settings(store, monkeypatch):
    assert voice.tts_model() == voice.TTS_MODEL == "gpt-4o-mini-tts"
    assert voice.stt_model() == voice.STT_MODEL == "gpt-4o-mini-transcribe"

    settings_from_env(monkeypatch, TTS_MODEL="gpt-next-tts", STT_MODEL="gpt-transcribe")
    sent = []
    await voice.tts("Hi.", "cedar", key="k", transport=openai_recorder(sent))
    assert sent[0]["model"] == "gpt-next-tts"
    assert voice.stt_model() == "gpt-transcribe"


async def test_dictation_and_live_talk_transcribe_with_the_stt_setting(store, monkeypatch):
    settings_from_env(monkeypatch, STT_MODEL="gpt-transcribe")
    seen = {}

    def handler(request):
        if request.url.path.endswith("/audio/transcriptions"):
            seen["dictation"] = b'name="model"\r\n\r\ngpt-transcribe' in request.content
            return httpx.Response(200, json={"text": "remind me at six"})
        seen["talk"] = json.loads(request.content)["session"]["audio"]["input"]["transcription"]["model"]
        return httpx.Response(200, json={"value": "ek_x", "expires_at": 9, "session": {}})
    t = httpx.MockTransport(handler)
    assert await voice.stt(b"audio", "a.webm", "audio/webm", key="k", transport=t) == "remind me at six"
    await voice.realtime_session(store, context="", key="k", transport=t)
    assert seen == {"dictation": True, "talk": "gpt-transcribe"}


# ── The video voice: pinned apart from read-aloud ──

def test_without_a_video_voice_videos_speak_in_the_read_aloud_voice(store):
    voice.set_tts(store, engine="kokoro", voice="am_michael")
    assert voice.video_tts(store) == ("kokoro", "am_michael")
    voice.set_tts(store, voice="bf_emma")
    assert voice.video_tts(store) == ("kokoro", "bf_emma")  # unset: it follows, as before


def test_a_pinned_video_voice_stays_when_the_read_aloud_voice_changes(store, monkeypatch):
    voice.set_tts(store, engine="kokoro", voice="af_heart")
    settings_from_env(monkeypatch, VIDEO_VOICE="am_michael")
    assert voice.video_tts(store) == ("kokoro", "am_michael")
    voice.set_tts(store, voice="bf_emma")
    assert voice.video_tts(store) == ("kokoro", "am_michael")


def test_a_pinned_video_voice_may_be_another_engines_and_is_found_by_its_name(store, monkeypatch):
    voice.set_tts(store, engine="kokoro", voice="af_heart")
    settings_from_env(monkeypatch, VIDEO_VOICE="Cedar")
    assert voice.video_tts(store) == ("openai", "cedar")


def test_a_video_voice_that_isnt_one_falls_back_to_read_aloud_and_says_so(store, monkeypatch, caplog):
    voice.set_tts(store, engine="kokoro", voice="af_heart")
    settings_from_env(monkeypatch, VIDEO_VOICE="nobody")
    assert voice.video_tts(store) == ("kokoro", "af_heart")
    assert "nobody" in caplog.text


async def test_a_video_is_narrated_in_the_pinned_voice_unless_the_user_asked_for_one(store, monkeypatch):
    voice.set_tts(store, engine="kokoro", voice="af_heart")
    settings_from_env(monkeypatch, VIDEO_VOICE="am_michael")
    pinned, asked = [], []
    await narrate.narrate(store, ["One."], transport=kokoro(pinned, 0.5))
    await narrate.narrate(store, ["One."], voice_name="Emma", transport=kokoro(asked, 0.5))
    assert pinned[0]["voice"] == "am_michael"
    assert asked[0]["voice"] == "bf_emma"


async def test_a_pinned_openai_voice_narrates_through_openai_with_the_style(store, monkeypatch):
    save_secret("OPENAI_API_KEY", "sk-test-not-real-0123456789")
    voice.set_tts(store, engine="kokoro", voice="af_heart")
    settings_from_env(monkeypatch, VIDEO_VOICE="cedar")
    sent = []
    await narrate.narrate(store, ["One."], transport=openai_recorder(sent), style=SCIENCE)
    assert (sent[0]["voice"], sent[0]["instructions"], sent[0]["response_format"]) == ("cedar", SCIENCE, "pcm")

