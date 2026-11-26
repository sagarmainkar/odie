"""Libra: the user's own voice server, and the voice markup the chat model writes when Libra reads replies aloud.
Every call to a Libra server goes through httpx.MockTransport; no test reaches a real one."""
import json

import httpx
import pytest

from odie import capabilities, voice, voice_libra
from odie.agent import prompt
from odie.cli_chat import Turn, show_event
from odie.store.db import Store


def _store(tmp_path, **settings):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    if settings:
        s.set_setting("voice", settings)
    return s


def libra(seen: list | None = None, status: int = 200, body: bytes = b"RIFFwav"):
    """A fake Libra server: notes each speech request's JSON, answers with `body` (or an OpenAI-style 400)."""
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/health":
            return httpx.Response(200, json={"ok": True})
        if seen is not None:
            seen.append({"url": str(request.url), **json.loads(request.content)})
        if status == 400:
            return httpx.Response(400, json={"error": {"message": "unknown voice 'zoe'; one of nina, sofia"}})
        return httpx.Response(status, content=body)
    return httpx.MockTransport(handler)


# ── the markup ──

def test_people_never_see_the_markup():
    assert voice_libra.hidden("<tone:wry>You paid twice? <laugh> No harm.") == "You paid twice? No harm."
    assert voice_libra.hidden("Oh <laugh>, fine.") == "Oh, fine."
    assert voice_libra.hidden("<TONE:Calm>Breathe <Sigh>.") == "Breathe."


def test_other_angle_brackets_stay():
    text = "a <b>bold</b> move, x < 5 and <tone:grumpy> stays"
    assert voice_libra.hidden(text) == text


def test_libra_hears_the_tags_but_not_the_tone():
    assert voice_libra.for_libra("<tone:wry>You paid twice? <Laugh> No harm.") == "You paid twice? <laugh> No harm."


def test_the_tone_a_reply_asks_for():
    assert voice_libra.tone_of("<tone:wry>You paid twice?") == "wry"
    assert voice_libra.tone_of("<TONE:Calm>Breathe.") == "calm"
    assert voice_libra.tone_of("Plain answer.") is None
    assert voice_libra.tone_of("<tone:grumpy>Hi") is None


def test_which_tone_libra_speaks_in():
    calm = {"libra_style": "calm"}
    assert voice_libra.tone_to_use("wry", "<tone:sad>x", calm) == "wry"  # the Mac passes the reply's tone
    assert voice_libra.tone_to_use(None, "<tone:sad>x", calm) == "sad"
    assert voice_libra.tone_to_use(None, "x", calm) == "calm"
    assert voice_libra.tone_to_use("grumpy", "x", {}) is None


def test_the_read_aloud_cleaner_keeps_markers_whole():
    from odie.app.routes import _speakable
    assert _speakable("**Hi** <laugh> `x`, <long pause> <throat-clearing> ok") == "Hi <laugh> x, <long pause> <throat-clearing> ok"
    assert _speakable("<tone:wry>> quoted _under_") == "<tone:wry> quoted under"


def test_streamed_words_hide_a_marker_split_across_pieces():
    hider = voice_libra.StreamHider()
    assert hider.feed("<to") == ""
    assert hider.feed("ne:wry>Hi <la") == "Hi"
    assert hider.feed("ugh> ok") == " ok"
    assert hider.feed(" x < 5 ") == " x < 5"
    assert hider.flush() == " "


def test_the_terminal_prints_no_markup():
    import io
    out, err = io.StringIO(), io.StringIO()
    turn = Turn()
    for piece in ["<tone:", "cheerful>Paid", "! <chu", "ckle> Done."]:
        show_event({"type": "token", "text": piece}, turn, out, err)
    show_event({"type": "text", "text": "<tone:cheerful>Paid! <chuckle> Done."}, turn, out, err)
    assert out.getvalue() == "Paid! Done.\n"


def test_a_notification_never_carries_the_markup(tmp_path, monkeypatch):
    from odie.push import send
    s = _store(tmp_path)
    s.add_subscription("https://push.example/1", "key", "auth", None)
    sent = []
    monkeypatch.setattr(send, "webpush", lambda subscription_info, data, **_: sent.append(json.loads(data)))
    monkeypatch.setattr(send, "load_or_create_vapid", lambda path: {"subject": "mailto:x@example.com", "private": "k"})
    monkeypatch.setattr(send, "_private_key_file", lambda vapid: "key.pem")
    send.send_to_all(s, "Odie", "<tone:warm>All done. <sigh> Finally.")
    assert sent[0]["body"] == "All done. Finally."


# ── settings ──

def test_the_server_address():
    assert voice_libra.server_url({}) == voice_libra.DEFAULT_URL
    assert voice_libra.server_url({"libra_url": "http://studio.local:8794/v1/"}) == "http://studio.local:8794"
    assert voice_libra.url_problem("http://127.0.0.1:8794") is None
    assert voice_libra.url_problem("http://studio.local:8794/") is None
    assert "http://" in voice_libra.url_problem("studio.local:8794")
    assert voice_libra.url_problem("  ") == "Type the Libra server's address first."


def test_libra_is_an_engine_but_never_the_default(tmp_path):
    s = _store(tmp_path)
    assert "libra" in voice.ENGINES and "libra" not in voice.disabled()
    assert voice.get_tts(s)[0] != "libra"
    assert voice.set_tts(s, "libra") == ("libra", "nina")
    assert voice.set_tts(s, "libra", "omar") == ("libra", "omar")
    assert voice.set_tts(s, "libra", "nobody") == ("libra", "omar")


def test_the_model_is_told_about_the_markup_only_while_libra_reads(tmp_path):
    s = _store(tmp_path)
    assert "libra_voice" not in capabilities.detect((), s)
    voice.set_tts(s, "libra")
    caps = capabilities.detect((), s)
    assert "libra_voice" in caps
    rules = [r.id for r in prompt.placed(prompt.RULES, [], caps)]
    assert "libra-voice" in rules
    assert "<tone:NAME>" in prompt.LIBRA_RULE and "<laugh>" in prompt.LIBRA_RULE
    assert "libra-voice" not in [r.id for r in prompt.placed(prompt.RULES, [], frozenset())]


def test_podcast_hosts_with_libra():
    assert [v["id"] for v in voice.libra_hosts("sofia")] == ["sofia", "omar"]
    assert [v["id"] for v in voice.libra_hosts("jon")] == ["nina", "jon"]
    assert [v["id"] for v in voice.libra_hosts("gone")] == ["nina", "omar"]


# ── speaking ──

async def test_libra_gets_the_tone_as_style_and_keeps_the_tags(tmp_path):
    s = _store(tmp_path, engine="libra", libra_voice="bob", libra_url="http://studio.local:8794")
    seen = []
    audio = await voice.libra_tts(s, "<tone:wry>You paid twice? <laugh> No harm.", "bob", transport=libra(seen))
    assert audio == b"RIFFwav"
    assert seen == [{"url": "http://studio.local:8794/v1/audio/speech", "input": "You paid twice? <laugh> No harm.",
                     "voice": "bob", "response_format": "wav", "trim": True, "style": "wry"}]


async def test_a_sentence_sent_alone_carries_its_replys_tone(tmp_path):
    s = _store(tmp_path, engine="libra", libra_style="calm")
    seen = []
    await voice.libra_tts(s, "Then it rang. <gasp>", "nina", tone="frightened", transport=libra(seen))
    assert seen[0]["style"] == "frightened"
    await voice.libra_tts(s, "No tone here.", "nina", transport=libra(seen))
    assert seen[1]["style"] == "calm"


async def test_no_tone_anywhere_sends_no_style(tmp_path):
    s = _store(tmp_path, engine="libra")
    seen = []
    await voice.libra_tts(s, "Plain.", "nina", transport=libra(seen))
    assert "style" not in seen[0]


async def test_a_server_that_isnt_there_says_how_to_start_it(tmp_path):
    s = _store(tmp_path, engine="libra")

    def down(request):
        raise httpx.ConnectError("refused")
    with pytest.raises(voice.VoiceUnavailable, match="./libra start"):
        await voice.libra_tts(s, "Hi.", "nina", transport=httpx.MockTransport(down))


async def test_a_refusal_says_the_servers_words(tmp_path):
    s = _store(tmp_path, engine="libra")
    with pytest.raises(voice.VoiceUnavailable, match="unknown voice 'zoe'"):
        await voice.libra_tts(s, "Hi.", "zoe", transport=libra(status=400))


async def test_read_aloud_falls_back_when_libra_is_off(tmp_path, monkeypatch):
    s = _store(tmp_path, engine="libra")
    heard = []

    async def libra_off(store, text, voice_id, tone=None, transport=None):
        raise voice.VoiceUnavailable("The Libra voice server isn't answering.")

    async def kokoro(engine, text, voice_id, transport=None):
        heard.append((engine, text))
        return b"wav"
    monkeypatch.setattr(voice, "libra_tts", libra_off)
    monkeypatch.setattr(voice, "local_tts", kokoro)
    monkeypatch.setattr(voice, "default_engine", lambda: "kokoro")
    audio, media = await voice.speak(s, "<tone:wry>Paid twice? <laugh> No harm.")
    assert (audio, media) == (b"wav", "audio/wav")
    assert heard == [("kokoro", "Paid twice? No harm.")]  # another voice never hears the markup


async def test_other_engines_never_hear_the_markup(tmp_path, monkeypatch):
    s = _store(tmp_path, engine="kokoro")
    heard = []

    async def kokoro(engine, text, voice_id, transport=None):
        heard.append(text)
        return b"wav"
    monkeypatch.setattr(voice, "local_tts", kokoro)
    await voice.speak(s, "<tone:wry>Paid twice? <laugh> No harm.")
    assert heard == ["Paid twice? No harm."]


# ── how quickly it talks ──

def _a_second_of_tone() -> bytes:
    """One second of a 440 Hz tone as a 24 kHz WAV, as Libra answers."""
    import io
    import math
    import struct
    import wave
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(24000)
        w.writeframes(b"".join(struct.pack("<h", int(8000 * math.sin(2 * math.pi * 440 * i / 24000))) for i in range(24000)))
    return out.getvalue()


def _seconds(wav: bytes) -> float:
    import io
    import wave
    with wave.open(io.BytesIO(wav)) as w:
        return w.getnframes() / w.getframerate()


def test_the_speed_in_settings():
    assert voice_libra.settings_speed({}) == "brisk"
    assert voice_libra.settings_speed({"libra_speed": "quick"}) == "quick"
    assert voice_libra.settings_speed({"libra_speed": "zoom"}) == "brisk"


async def test_brisk_is_a_tenth_quicker_and_a_readable_wav():
    import shutil
    if shutil.which("ffmpeg") is None:
        pytest.skip("no ffmpeg here")
    wav = _a_second_of_tone()
    quicker = await voice_libra.quicken(wav, "brisk")
    assert _seconds(quicker) == pytest.approx(1 / 1.1, abs=0.02)  # the header's lengths are right: wave reads it
    assert await voice_libra.quicken(wav, "normal") == wav


async def test_a_wav_ffmpeg_cant_read_is_given_back_as_it_was():
    assert await voice_libra.quicken(b"RIFFwav", "quick") == b"RIFFwav"


async def test_read_aloud_plays_at_the_settings_speed(tmp_path):
    import shutil
    if shutil.which("ffmpeg") is None:
        pytest.skip("no ffmpeg here")
    s = _store(tmp_path, engine="libra", libra_speed="quick")
    audio = await voice.libra_tts(s, "Okay.", "nina", transport=libra(body=_a_second_of_tone()))
    assert _seconds(audio) == pytest.approx(1 / 1.2, abs=0.02)


async def test_a_sentence_with_nothing_to_say_never_reaches_libra(tmp_path):
    s = _store(tmp_path, engine="libra")
    seen = []
    with pytest.raises(voice.VoiceUnavailable):
        await voice.libra_tts(s, "—", "nina", transport=libra(seen))
    assert seen == []
    assert voice_libra.has_words("<laugh>")


def test_the_model_is_told_to_sound_like_a_friend(tmp_path):
    rules = " ".join(r.text for r in prompt.RULES if r.id == "libra-voice")
    assert "not narrating" in rules and "warm, cheerful or excited" in rules
