"""speak: a voice memo (plain speech in the chosen voice) or a podcast (two hosts, a woman first, then a man), made into
one WAV and handed to the chat as media. The podcast skill tells the model how to write the script."""
import json
from pathlib import Path

import httpx
import pytest

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
    await _speak(store, kokoro(seen)).func(script="## Plan\n- **Call** the [bank](https://x.example/a)\n- `code` here\n\nDone.")
    assert seen[0]["text"] == "Plan. Call the bank. code here. Done."
    assert mtools.plain_speech("See https://x.example/page for *more*.") == "See for more."
    assert len(mtools.plain_speech("word " * 2000)) <= 4000


async def test_a_podcast_gives_the_first_host_a_womans_voice(store):
    seen = []
    script = ("Asha: Welcome back! I'm Asha.\n**Rohan:** And I'm Rohan. Today, our session.\nAsha: So where do we start?\n"
              "it continues here.\n\nRohan: With the basics.")
    out = await _speak(store, kokoro(seen, 0.5)).func(script=script, title="Our session", style="podcast")
    m = media.get(out["media"]["id"])[1]
    assert m["kind"] == "podcast" and m["title"] == "Our session"
    assert m["hosts"] == [{"name": "Asha", "voice": "Heart", "group": "female"}, {"name": "Rohan", "voice": "Michael", "group": "male"}]
    assert [b["voice"] for b in seen] == ["af_heart", "am_michael", "af_heart", "am_michael"]
    assert seen[2]["text"] == "So where do we start? it continues here."
    assert [(t["host"], t["start"]) for t in m["transcript"]] == [("Asha", 0.0), ("Rohan", 0.8), ("Asha", 1.6), ("Rohan", 2.4)]
    assert m["duration"] == 2.9  # four half-second turns and three 300 ms gaps


def test_podcast_voices_follow_the_accent(store):
    ids = lambda: [v["id"] for v in voice.podcast_voices(store)]  # noqa: E731
    assert ids() == ["af_heart", "am_michael"]
    voice.set_tts(store, engine="kokoro", voice="hm_omega")
    assert ids() == ["hf_alpha", "hm_omega"]
    voice.set_tts(store, engine="kokoro", voice="bf_emma")
    assert ids() == ["bf_emma", "bm_george"]
    voice.set_tts(store, engine="kokoro", voice="hf_beta")
    assert ids() == ["hf_beta", "hm_omega"]


@pytest.mark.parametrize("script, why", [
    ("Ana: hi\nBen: hello\nCal: hey\nCal: again", "two hosts"), ("Ana: just me talking.", "two hosts"), ("no names at all here", "Host A:"),
    ("\n".join(f"{'Ana' if i % 2 else 'Ben'}: line {i}" for i in range(61)), "60"),
])
def test_scripts_are_checked(script, why):
    with pytest.raises(ValueError) as e:
        mtools.parse_script(script)
    assert why in str(e.value)


async def test_speak_errors_are_plain(store):
    def down(request):
        raise httpx.ConnectError("refused")
    tool = _speak(store, httpx.MockTransport(down))
    out = await tool.func(script="Hello.")
    assert "media" not in out and "voice" in out["error"].lower() and "refused" not in out["error"].lower()
    assert "error" in await tool.func(script="   ")
    assert "two hosts" in (await tool.func(script="A: hi", style="podcast"))["error"]
    assert "memo or podcast" in (await tool.func(script="Hi", style="song"))["error"]


def test_the_podcast_skill_is_built_in(store):
    from odie.skills import registry
    [e] = [e for e in registry.discover(store) if e.name == "podcast"]
    text = (registry.BUILTIN / "podcast" / "SKILL.md").read_text()
    assert "podcast" in e.description.lower() and e.status != "error"
    assert 'style="podcast"' in text and "woman" in text and "Host A:" in text and "140 words" in text


def test_the_podcast_skill_keeps_the_hosts_unnamed():
    """The owner wants "just a man and a woman": Gemma's episode opened "Asha: Welcome back! I'm Asha." (11 Oct 2026)."""
    from odie.skills import registry
    text = (registry.BUILTIN / "podcast" / "SKILL.md").read_text()
    assert "never say their own names or each other's" in text and "Host A (a woman) and Host B (a man)" in text
    assert "Asha" not in text and "Rohan" not in text and "first names" not in text and "say their names" not in text


async def test_a_podcast_with_neutral_labels_gets_both_voices_and_a_title_without_them(store):
    seen = []
    script = ("Host A: Today we're looking at how a home loan shrinks if you pay it off early.\n"
              "Host B: And it's a bigger saving than most people think.\nHost A: Let's start with the EMI.")
    out = await _speak(store, kokoro(seen, 0.5)).func(script=script, style="podcast")
    m = media.get(out["media"]["id"])[1]
    assert [h["name"] for h in m["hosts"]] == ["Host A", "Host B"]
    assert [b["voice"] for b in seen] == ["af_heart", "am_michael", "af_heart"]
    assert m["title"] == "Today we're looking at how a home loan shrinks if you pay…"
    assert "Host" not in m["title"]


def test_the_tool_says_when_to_use_it(store):
    tool = _speak(store, None)
    assert tool.name == "speak" and "voice memo" in tool.description and "podcast skill" in tool.description


async def test_the_model_sees_a_short_result(store):
    from odie.app.runner import event_to_sse, events_to_history
    from tests.test_media import _call, _response, _text
    out = await _speak(store, kokoro([], 1.0)).func(script="Good morning!", title="Morning")
    assert set(out["media"]) == {"id", "kind", "title", "duration"}  # no peaks or transcript sent back to the model
    full = media.get(out["media"]["id"])[1]
    assert len(full["peaks"]) == 48 and full["transcript"] == "Good morning!"
    ev = _response("speak", out)
    assert event_to_sse(ev)[1] == {"type": "media", "media": full}  # the chat gets it all, from the sidecar
    [reply] = [i for i in events_to_history([_text("user", "memo please"), _call("speak"), ev, _text("odie", "Here.")]) if i["role"] == "odie"]
    assert reply["media"] == [full]


def test_lines_with_colons_continue_the_turn():
    turns = mtools.parse_script("Asha: Hi there.\nRohan: Let's start.\nAt 10:30 we met the team.\nNote: this matters.\n"
                                "https://example.com/page was the link.\nAsha: Right.")
    assert [n for n, _ in turns] == ["Asha", "Rohan", "Asha"]
    assert turns[1][1] == "Let's start. At 10:30 we met the team. Note: this matters. was the link."


def test_a_recurring_third_speaker_is_refused():
    with pytest.raises(ValueError) as e:
        mtools.parse_script("Asha: Hi.\nRohan: Hello.\nMeera: Hey.\nAsha: So.\nMeera: Me again.")
    assert "two hosts" in str(e.value)


def test_names_in_any_script():
    turns = mtools.parse_script("Élodie: Bonjour à tous.\nआशा: नमस्ते।\nÉlodie: On commence.")
    assert [n for n, _ in turns] == ["Élodie", "आशा", "Élodie"]


async def test_a_host_with_only_links_is_a_plain_error(store):
    out = await _speak(store, kokoro([])).func(script="Asha: Hi there.\nRohan: https://example.com", style="podcast")
    assert "two hosts" in out["error"]


async def test_the_result_gives_the_audio_files_path(store):
    # A video skill hands the narration to ffmpeg: the path comes back, so the model never guesses where it is.
    memo = await _speak(store, kokoro([], 0.5)).func(script="Hello there.")
    assert memo["path"] == str(media.media_dir() / f"{memo['media']['id']}.wav")
    assert Path(memo["path"]).read_bytes()[:4] == b"RIFF"
    pod = await _speak(store, kokoro([], 0.5)).func(script="Host A: Hi.\nHost B: Hello.", style="podcast")
    assert pod["path"] == str(media.media_dir() / f"{pod['media']['id']}.wav")


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
    assert "Kokoro" in out["error"] and "Michael" in out["error"] and "Heart" in out["error"] and "Settings" in out["error"]


def test_the_tool_explains_the_voice_choice(store):
    tool = _speak(store, None)
    assert "voice_name" in tool.description and "same engine" in tool.description and "path" in tool.description
