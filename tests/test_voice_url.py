"""The voice-server client (odie/voice_url.py): any server with the OpenAI audio API, and voiced's model descriptions."""
from __future__ import annotations

import asyncio
import json
import shutil
import subprocess

import httpx
import pytest

from odie import voice_url

LISTING = {"data": [
    {"id": "kokoro", "kind": "tts", "usage": {"voices": [
        {"name": "af_heart", "gender": "female", "accent": "American"},
        {"name": "bm_george", "gender": "male", "accent": "British"}]}},
    {"id": "libra-tts", "kind": "tts", "usage": {"voices": [{"name": "nina", "gender": "female"}],
                                                  "styles": ["warm", "cheerful"]}},
    {"id": "parakeet", "kind": "stt", "usage": {}},
]}


def serving(handler):
    return httpx.MockTransport(handler)


def test_base_strips_v1_and_slash():
    assert voice_url.base(" http://h:12000/v1/ ") == "http://h:12000"
    assert voice_url.base("http://h:12000/") == "http://h:12000"
    assert voice_url.base("http://h:12000") == "http://h:12000"


def test_url_problem_names_the_voice_server():
    assert voice_url.url_problem("http://127.0.0.1:12000") is None
    assert "voice server" in voice_url.url_problem("")
    assert "http://" in voice_url.url_problem("studio.local:12000")


def test_models_reads_voices_and_styles():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/models"
        return httpx.Response(200, json=LISTING)
    found = asyncio.run(voice_url.models("http://v:12000/v1", transport=serving(handler)))
    names = [m.name for m in found]
    assert names == ["kokoro", "libra-tts", "parakeet"]
    kokoro, libra, parakeet = found
    assert kokoro.kind == "tts" and parakeet.kind == "stt"
    assert kokoro.voices[1] == {"id": "bm_george", "label": "Bm_george", "group": "male", "note": "British"}
    assert libra.styles == ["warm", "cheerful"] and kokoro.styles == []


def test_models_without_usage():
    """A server that only speaks OpenAI's shape (no kind, no usage): a speaking model with nothing listed."""
    found = asyncio.run(voice_url.models("http://v", transport=serving(lambda r: httpx.Response(200, json={"data": [{"id": "x"}]}))))
    assert found == [voice_url.Model("x", "tts", [], [])]


def test_plain_string_voices_are_read():
    listing = {"data": [{"id": "m", "kind": "tts", "usage": {"voices": ["zoey"]}}]}
    found = asyncio.run(voice_url.models("http://v", transport=serving(lambda r: httpx.Response(200, json=listing))))
    assert found[0].voices == [{"id": "zoey", "label": "Zoey", "group": "", "note": ""}]


def test_available_is_false_when_nothing_answers():
    def refuse(request):
        raise httpx.ConnectError("nobody home")
    assert asyncio.run(voice_url.available("http://v", transport=serving(refuse))) is False
    assert asyncio.run(voice_url.available("http://v", transport=serving(lambda r: httpx.Response(200, json={"ok": True})))) is True


def test_speak_sends_style_and_returns_wav():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=b"RIFF....WAVE")
    wav = asyncio.run(voice_url.speak("http://v/", "libra-tts", "nina", "Hi <laugh>", style="wry", extra={"trim": True},
                                      transport=serving(handler)))
    assert wav == b"RIFF....WAVE" and seen["path"] == "/v1/audio/speech"
    assert seen["body"] == {"model": "libra-tts", "input": "Hi <laugh>", "voice": "nina", "response_format": "wav",
                            "style": "wry", "trim": True}


def test_speak_without_style_sends_none():
    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, content=b"RIFF")
    asyncio.run(voice_url.speak("http://v", "kokoro", "af_heart", "Hello", transport=serving(handler)))
    assert "style" not in seen["body"]


def test_speak_refusal_is_value_error():
    refused = serving(lambda r: httpx.Response(400, json={"error": {"message": "no voice called bob"}}))
    with pytest.raises(ValueError, match="no voice called bob"):
        asyncio.run(voice_url.speak("http://v", "kokoro", "bob", "Hi", transport=refused))


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_transcribe_converts_to_wav(tmp_path):
    """A phone's recording (webm here) reaches the server as 16 kHz mono WAV: voiced's models decode WAV only."""
    webm = tmp_path / "speech.webm"
    subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=0.5",
                    "-c:a", "libopus", str(webm)], check=True)
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["body"] = request.content
        return httpx.Response(200, json={"text": "pay the bill"})
    text = asyncio.run(voice_url.transcribe("http://v", "parakeet", webm.read_bytes(), "speech.webm", "audio/webm",
                                            transport=serving(handler)))
    assert text == "pay the bill" and seen["path"] == "/v1/audio/transcriptions"
    assert b"RIFF" in seen["body"] and b"WAVE" in seen["body"] and b'name="model"' in seen["body"]
    assert b"parakeet" in seen["body"]
