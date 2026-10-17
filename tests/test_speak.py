"""speak: a voice memo (plain speech in the chosen voice), made into one WAV and handed to the chat as media. A podcast
is the podcast skill's make_podcast (tests/test_podcast_*.py); speak only reads memos aloud."""
import json
from pathlib import Path

import httpx
import pytest
from google.adk.tools import FunctionTool

from odie import media, voice
from odie.agent.tools import media as mtools
from odie.store.db import Store
from tests.test_media import make_wav


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    return s


def kokoro(seen, seconds=0.5):
    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, content=make_wav(seconds))
    return httpx.MockTransport(handler)


def _speak(store, transport):
    [tool] = mtools.make_media_tools(store, transport=transport)
    return tool


def test_join_wavs():
    out, starts = media.join_wavs([make_wav(1.0), make_wav(0.5)], gap_ms=300)
    assert media.wav_info(out)["duration"] == 1.8 and starts == [0.0, 1.3]
    with pytest.raises(ValueError):
        media.join_wavs([make_wav(1.0), make_wav(1.0, rate=16000)])  # parts must match
    with pytest.raises(ValueError):
        media.join_wavs([])


async def test_a_memo(store):
    seen = []
    out = await _speak(store, kokoro(seen, 1.2)).func(script="Good morning! Here's your day.", title="Morning")
    m = media.get(out["media"]["id"])[1]  # the full description; the model's result is short
    assert m["kind"] == "memo" and m["duration"] == 1.2 and len(m["peaks"]) == 48 and m["title"] == "Morning"
    assert m["transcript"] == "Good morning! Here's your day." and m["voice"] == "Heart"
    assert seen == [{"engine": "kokoro", "text": "Good morning! Here's your day.", "voice": "af_heart", "lang": "a"}]
    path, saved = media.get(m["id"])
    assert path.read_bytes()[:4] == b"RIFF" and saved["mime"] == "audio/wav" and "under your reply" in out["result"]
    untitled = await _speak(store, kokoro([], 0.5)).func(script="Remember to call the bank about the card.")
    assert untitled["media"]["title"] == "Remember to call the bank about the card."


async def test_openai_is_asked_for_pcm(store):
    from odie.secrets import save_secret
    save_secret("OPENAI_API_KEY", "sk-test-not-real-0123456789")  # the test's own settings folder
    voice.set_tts(store, engine="openai", voice="cedar")
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, content=b"\x00\x01" * 24000)  # one second of 24 kHz 16-bit mono
    out = await _speak(store, httpx.MockTransport(handler)).func(script="Hello there.")
    assert seen[0]["response_format"] == "pcm" and seen[0]["voice"] == "cedar" and seen[0]["input"] == "Hello there."
    assert out["media"]["duration"] == 1.0 and media.get(out["media"]["id"])[1]["voice"] == "Cedar"


async def test_memo_text_is_plain_speech(store):
    seen = []
    script = "## Plan\n- **Call** the [bank](https://x.example/a)\n- `code` here\n\nDone."
    await _speak(store, kokoro(seen)).func(script=script)
    assert seen[0]["text"] == "Plan. Call the bank. code here. Done."
    assert mtools.plain_speech("See https://x.example/page for *more*.") == "See for more."
    assert len(mtools.plain_speech("word " * 2000)) <= 4000


def test_podcast_voices_follow_the_accent(store):
    ids = lambda: [v["id"] for v in voice.podcast_voices(store)]  # noqa: E731
    assert ids() == ["af_heart", "am_michael"]
    voice.set_tts(store, engine="kokoro", voice="hm_omega")
    assert ids() == ["hf_alpha", "hm_omega"]
    voice.set_tts(store, engine="kokoro", voice="bf_emma")
    assert ids() == ["bf_emma", "bm_george"]
    voice.set_tts(store, engine="kokoro", voice="hf_beta")
    assert ids() == ["hf_beta", "hm_omega"]


async def test_speak_errors_are_plain(store):
    def down(request):
        raise httpx.ConnectError("refused")
    tool = _speak(store, httpx.MockTransport(down))
    out = await tool.func(script="Hello.")
    assert "media" not in out and "voice" in out["error"].lower() and "refused" not in out["error"].lower()
    assert "error" in await tool.func(script="   ")


def test_the_tool_says_when_to_use_it_and_sends_podcasts_to_make_podcast(store):
    tool = _speak(store, None)
    assert tool.name == "speak" and "voice memo" in tool.description
    assert "make_podcast" in tool.description and 'style="podcast"' not in tool.description


def test_speak_has_no_style_any_more(store):
    declaration = FunctionTool(mtools.make_media_tools(store)[0].func)._get_declaration()
    assert sorted(declaration.parameters_json_schema["properties"]) == ["script", "title", "voice_name"]


async def test_the_model_sees_a_short_result(store):
    from odie.app.runner import event_to_sse, events_to_history
    from tests.test_media import _call, _response, _text
    out = await _speak(store, kokoro([], 1.0)).func(script="Good morning!", title="Morning")
    assert set(out["media"]) == {"id", "kind", "title", "duration"}  # no peaks or transcript sent back to the model
    full = media.get(out["media"]["id"])[1]
    assert len(full["peaks"]) == 48 and full["transcript"] == "Good morning!"
    ev = _response("speak", out)
    assert event_to_sse(ev)[1] == {"type": "media", "media": full}  # the chat gets it all, from the sidecar
    events = [_text("user", "memo please"), _call("speak"), ev, _text("odie", "Here.")]
    [reply] = [i for i in events_to_history(events) if i["role"] == "odie"]
    assert reply["media"] == [full]


async def test_the_result_gives_the_audio_files_path(store):
    # A video skill hands the narration to ffmpeg: the path comes back, so the model never guesses where it is.
    memo = await _speak(store, kokoro([], 0.5)).func(script="Hello there.")
    assert memo["path"] == str(media.media_dir() / f"{memo['media']['id']}.wav")
    assert Path(memo["path"]).read_bytes()[:4] == b"RIFF"


async def test_a_memo_in_another_voice_of_the_chosen_engine(store):
    # Kokoro is chosen (Heart); "a man's voice for this one" -> Michael, by label in any case or by id. Settings stay.
    seen = []
    out = await _speak(store, kokoro(seen, 0.5)).func(script="Attention, explained.", voice_name="michael")
    assert seen[0]["voice"] == "am_michael" and media.get(out["media"]["id"])[1]["voice"] == "Michael"
    await _speak(store, kokoro(seen, 0.5)).func(script="Again.", voice_name="bm_george")
    assert seen[1]["voice"] == "bm_george" and seen[1]["lang"] == "b"
    assert voice.get_tts(store) == ("kokoro", "af_heart")


async def test_a_voice_from_another_engine_is_refused_with_the_ones_it_can_use(store):
    # Kokoro is chosen; "cedar" is OpenAI's: switching engines would send the text to the cloud, so it's an error.
    seen = []
    out = await _speak(store, kokoro(seen, 0.5)).func(script="Hello.", voice_name="cedar")
    assert seen == [] and "media" not in out
    error = out["error"]
    assert "Kokoro" in error and "Michael" in error and "Heart" in error and "Settings" in error


def test_the_tool_explains_the_voice_choice(store):
    tool = _speak(store, None)
    assert "voice_name" in tool.description and "same engine" in tool.description and "path" in tool.description


async def test_a_two_host_script_is_refused_with_a_pointer_to_make_podcast(store):
    """speak once took style="podcast"; ADK now drops that argument silently, so an old-habit call would read
    "Host A:" aloud in one voice. A script with two hosts is refused, and nothing is spoken."""
    seen = []
    script = "Host A: Today we're looking at tides.\nHost B: Why twice a day?\nHost A: Two bulges."
    out = await _speak(store, kokoro(seen)).func(script=script)
    assert "make_podcast" in out["error"] and "two hosts" in out["error"]
    assert seen == []


@pytest.mark.parametrize("script", ["Remember to buy milk.", "Note: buy milk.", "Note: buy milk.\nAt 10:30 call Asha.",
                                    "Monday: gym.\nTuesday: swim.\nWednesday: rest."])
async def test_a_memo_with_one_label_or_a_list_of_labels_is_spoken(store, script):
    seen = []
    out = await _speak(store, kokoro(seen)).func(script=script)
    assert "error" not in out and len(seen) == 1


def test_two_hosts_are_two_names_taking_every_labelled_line():
    assert mtools.has_two_hosts("Host A: hi\nHost B: hello")
    assert mtools.has_two_hosts("**Asha:** Hi.\n**Rohan:** Hello.\nAsha: Bye.")
    assert not mtools.has_two_hosts("Remember to buy milk")
    assert not mtools.has_two_hosts("Note: buy milk")  # one label isn't two hosts
    assert not mtools.has_two_hosts("Host A: Hi. Host B: Hello.")  # one line: one speaker
    assert not mtools.has_two_hosts("Monday: gym\nTuesday: swim\nWednesday: rest")  # a list, not two hosts
