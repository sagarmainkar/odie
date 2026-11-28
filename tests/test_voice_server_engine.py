"""Read-aloud through the voice server (voiced): each speaking model it lists is an engine, old Libra and Kokoro
settings carry over, and a server that is down falls back instead of going silent."""
from __future__ import annotations

import json
import logging

import httpx
import pytest

from odie import voice, voice_url
from odie.store.db import Store
from tests.test_media import make_wav


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    return s


@pytest.fixture(autouse=True)
def known_models(monkeypatch):
    """Every test starts from the models Odie knows before asking the server."""
    voice.forget_server_models()
    yield
    voice.forget_server_models()


def server(seen, seconds=0.5):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append({"path": request.url.path, **json.loads(request.content)})
        return httpx.Response(200, content=make_wav(seconds))
    return httpx.MockTransport(handler)


def test_old_libra_settings_move_to_the_voice_server(store):
    store.set_setting("voice", {"engine": "libra", "libra_voice": "sofia", "libra_style": "wry", "libra_speed": "quick",
                                "libra_url": "http://127.0.0.1:8794"})
    assert voice.get_tts(store) == ("libra-tts", "sofia")
    moved = voice.migrated(store.get_setting("voice"))
    assert moved["server_style"] == "wry" and moved["server_speed"] == "quick"
    assert voice.server_url(store) == voice_url.DEFAULT_URL  # the retired :8794 is dropped


def test_a_libra_address_on_another_machine_is_kept(store):
    store.set_setting("voice", {"engine": "libra", "libra_url": "http://studio.local:12000"})
    assert voice.server_url(store) == "http://studio.local:12000"


def test_maya1_becomes_kokoro(store):
    store.set_setting("voice", {"engine": "maya1", "maya1_voice": "uk_female"})
    assert voice.get_tts(store) == ("kokoro", "af_heart")


def test_migrated_settings_come_back_unchanged():
    already = {"engine": "libra-tts", "libra-tts_voice": "nina", "server_style": "calm"}
    assert voice.migrated(already) == already


async def test_kokoro_speaks_through_the_voice_server(store):
    seen = []
    voice.set_tts(store, engine="kokoro", voice="bf_emma")
    wav = await voice.speak_wav(store, "Hello there.", transport=server(seen))
    assert wav.startswith(b"RIFF")
    assert seen == [{"path": "/v1/audio/speech", "model": "kokoro", "input": "Hello there.", "voice": "bf_emma",
                     "response_format": "wav"}]


async def test_a_styled_model_hears_the_tone_and_tags(store):
    seen = []
    voice.set_tts(store, engine="libra-tts", voice="nina")
    voice.set_server(store, speed="normal")
    await voice.speak_wav(store, "<tone:wry>You paid twice? <laugh> No harm.", transport=server(seen))
    assert seen[0]["model"] == "libra-tts" and seen[0]["style"] == "wry" and seen[0]["trim"] is True
    assert seen[0]["input"] == "You paid twice? <laugh> No harm."


async def test_a_plain_model_never_sees_the_markup(store):
    seen = []
    voice.set_tts(store, engine="kokoro", voice="af_heart")
    await voice.speak_wav(store, "<tone:wry>You paid twice? <laugh> No harm.", transport=server(seen))
    assert seen[0]["input"] == "You paid twice? No harm." and "style" not in seen[0]


async def test_server_down_falls_back_to_phonon(store, monkeypatch, caplog):
    voice.set_tts(store, engine="kokoro", voice="af_heart")
    monkeypatch.setattr(voice, "phonon_here", lambda: True)
    spoken = {}

    async def phonon(text, voice_id, transport=None):
        spoken["text"] = text
        return make_wav(0.5)
    monkeypatch.setattr(voice, "phonon_tts", phonon)

    def refuse(request):
        raise httpx.ConnectError("nobody home")
    with caplog.at_level(logging.WARNING):
        wav = await voice.speak_wav(store, "Hello.", transport=httpx.MockTransport(refuse))
    assert wav.startswith(b"RIFF") and spoken["text"] == "Hello."
    assert "voice server" in caplog.text


def test_the_markup_rule_follows_styles(store):
    voice.set_tts(store, engine="libra-tts", voice="nina")
    assert voice.styles_on(store) is True
    voice.set_tts(store, engine="kokoro", voice="af_heart")
    assert voice.styles_on(store) is False


def test_the_servers_models_become_engines(store):
    voice.learn_server_models([
        voice_url.Model("kokoro", "tts", [{"id": "af_heart", "label": "Af_heart", "group": "female", "note": "American"}]),
        voice_url.Model("orpheus", "tts", [{"id": "tara", "label": "Tara", "group": "female", "note": ""}]),
        voice_url.Model("parakeet", "stt"),
    ])
    assert "orpheus" in voice.ENGINES and "parakeet" not in voice.ENGINES
    assert "libra-tts" not in voice.ENGINES  # not listed by the server any more
    assert voice.set_tts(store, engine="orpheus", voice="tara") == ("orpheus", "tara")
    assert voice.styles_on(store) is False


def test_podcast_hosts_on_a_styled_model(store):
    voice.set_tts(store, engine="libra-tts", voice="sofia")
    assert [v["id"] for v in voice.podcast_voices(store)] == ["sofia", "omar"]
