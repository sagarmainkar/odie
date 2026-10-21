"""Patience with OpenAI's voice (21 Oct 2026: gpt-4o-mini-tts took 40-50 s on its own servers for a 2-second clip on
about half the requests, so a reel's ~25 phrases, one after another with 60 s each and no retry, always failed).
OpenAI's phrases are now spoken several at a time, each request waits longer and a timeout or a busy answer is tried
again; the local voice still speaks one phrase at a time."""
import asyncio
import json

import httpx
import pytest

from odie import voice
from odie.secrets import save_secret
from odie.store.db import Store
from odie.video import narrate
from tests.test_media import make_wav

LOUD = b"\x00\x40"  # one sample of 16-bit PCM, well above the quiet that lead_cut trims


@pytest.fixture
def store(isolated_settings, tmp_path, monkeypatch):
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    monkeypatch.setattr(voice, "RETRY_PAUSES", (0.0, 0.0))
    return s


def openai_chosen(store):
    save_secret("OPENAI_API_KEY", "sk-test-not-real-0123456789")  # the test's own settings folder
    voice.set_tts(store, engine="openai", voice="cedar")


def counting(answer):
    """A transport that answers with `answer(text)` after a short wait, and records how many requests were open at
    once at most, and the order phrases were asked in."""
    state = {"open": 0, "most": 0, "asked": []}

    async def handler(request):
        text = json.loads(request.content).get("input") or json.loads(request.content).get("text")
        state["asked"].append(text)
        state["open"] += 1
        state["most"] = max(state["most"], state["open"])
        await asyncio.sleep(0.02)
        state["open"] -= 1
        return answer(text)
    return httpx.MockTransport(handler), state


async def test_openai_phrases_are_spoken_several_at_a_time_and_kept_in_order(store):
    openai_chosen(store)
    seconds = {"One.": 0.5, "Two.": 1.0, "Three.": 0.25, "Four.": 0.75, "Five.": 1.5, "Six.": 0.5, "Seven.": 1.0, "Eight.": 0.25}
    transport, state = counting(lambda text: httpx.Response(200, content=LOUD * int(24000 * seconds[text])))
    _wav, lengths, beats = await narrate.narrate(store, ["One. | Two.", "Three. | Four. | Five.", "Six.", "Seven. | Eight."],
                                                 transport=transport)
    assert 1 < state["most"] <= narrate.OPENAI_AT_ONCE
    assert lengths == [1.5, 2.5, 0.5, 1.25]  # each scene its own phrases, in order
    assert beats == [[0.0, 0.5], [0.0, 0.25, 1.0], [0.0], [0.0, 1.0]]


async def test_the_local_voice_still_speaks_one_phrase_at_a_time(store):
    transport, state = counting(lambda text: httpx.Response(200, content=make_wav(0.5)))
    await narrate.narrate(store, ["One. | Two.", "Three. | Four."], transport=transport)
    assert state["most"] == 1 and state["asked"] == ["One.", "Two.", "Three.", "Four."]


async def test_a_timeout_or_a_busy_answer_is_tried_again(store):
    answers = [httpx.ReadTimeout("slow"), httpx.Response(429, json={"error": "busy"}), httpx.Response(200, content=b"ID3")]
    tries = []

    def handler(request):
        tries.append(1)
        got = answers[len(tries) - 1]
        if isinstance(got, Exception):
            raise got
        return got
    assert await voice.tts("Hi.", "cedar", key="k", transport=httpx.MockTransport(handler)) == b"ID3"
    assert len(tries) == 3


async def test_openai_that_keeps_timing_out_gives_up_after_two_retries(store):
    tries = []

    def handler(request):
        tries.append(1)
        raise httpx.ReadTimeout("slow")
    with pytest.raises(httpx.ReadTimeout):
        await voice.tts("Hi.", "cedar", key="k", transport=httpx.MockTransport(handler))
    assert len(tries) == 3


async def test_a_wrong_key_is_not_tried_again(store):
    tries = []

    def handler(request):
        tries.append(1)
        return httpx.Response(401, json={"error": "bad key"})
    with pytest.raises(httpx.HTTPStatusError):
        await voice.tts("Hi.", "cedar", key="k", transport=httpx.MockTransport(handler))
    assert len(tries) == 1


def test_which_failures_are_worth_another_try():
    request = httpx.Request("POST", "https://api.openai.com/v1/audio/speech")

    def status(code):
        return httpx.HTTPStatusError("x", request=request, response=httpx.Response(code, request=request))
    assert voice.try_again(httpx.ReadTimeout("slow"))
    assert voice.try_again(httpx.ConnectError("refused"))
    assert voice.try_again(status(429)) and voice.try_again(status(503))
    assert not voice.try_again(status(401)) and not voice.try_again(status(400))
