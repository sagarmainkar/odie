import json

import httpx

from odie import voice
from odie.store.db import Store


def _store(tmp_path):
    s = Store(tmp_path / "a.db"); s.init_schema(); return s


def test_voice_setting_defaults_and_validates(tmp_path):
    s = _store(tmp_path)
    assert voice.get_voice(s) == "marin"
    assert voice.set_voice(s, "cedar") == "cedar"
    assert voice.set_voice(s, "nova") == "cedar"          # not usable for realtime: ignored
    assert [v["id"] for v in voice.VOICES][0] == "marin"


async def test_tts_and_stt_call_openai(tmp_path):
    seen = {}

    def handler(req: httpx.Request):
        seen[req.url.path] = req
        if req.url.path.endswith("/audio/speech"):
            body = json.loads(req.content)
            assert body["model"] == voice.TTS_MODEL and body["voice"] == "cedar"
            return httpx.Response(200, content=b"ID3mp3", headers={"content-type": "audio/mpeg"})
        return httpx.Response(200, json={"text": "remind me at six"})
    t = httpx.MockTransport(handler)
    assert await voice.tts("hello", "cedar", key="k", transport=t) == b"ID3mp3"
    assert await voice.stt(b"audio", "a.webm", "audio/webm", key="k", transport=t) == "remind me at six"
    assert seen["/v1/audio/speech"].headers["authorization"] == "Bearer k"


async def test_realtime_session_has_one_tool_and_the_persona(tmp_path):
    s = _store(tmp_path)
    from odie import persona
    persona.set_name(s, "Mira")
    captured = {}

    def handler(req):
        captured["body"] = json.loads(req.content)
        return httpx.Response(200, json={"value": "ek_x", "expires_at": 9, "session": {}})
    out = await voice.realtime_session(s, context="[context: now 18:00]", key="k", transport=httpx.MockTransport(handler))
    sess = captured["body"]["session"]
    assert out["client_secret"] == "ek_x" and out["model"] == voice.REALTIME_MODEL and out["name"] == "Mira"
    assert [t["name"] for t in sess["tools"]] == ["ask_brain"]
    assert "Mira" in sess["instructions"] and "[context: now 18:00]" in sess["instructions"]
    assert sess["audio"]["output"]["voice"] == "marin"


def test_missing_key_is_a_clear_error(tmp_path, monkeypatch):
    import pytest
    monkeypatch.setattr(voice, "load_secret", lambda name: None)
    with pytest.raises(voice.VoiceUnavailable):
        voice.api_key()


def test_engine_settings_keep_a_voice_per_engine(tmp_path, monkeypatch):
    s = _store(tmp_path)
    monkeypatch.setattr(voice, "load_secret", lambda name: "sk-test")  # with an OpenAI key, OpenAI voices can be chosen
    assert voice.get_tts(s) == ("kokoro", "af_heart")  # Kokoro is the default; OpenAI only with a key
    assert voice.set_tts(s, "kokoro") == ("kokoro", "af_heart")
    assert voice.set_tts(s, voice="hf_alpha") == ("kokoro", "hf_alpha")
    assert voice.set_tts(s, "maya1", "uk_female") == ("kokoro", "hf_alpha")   # Maya1 is hidden: ignored
    assert voice.set_tts(s, voice="not-a-voice") == ("kokoro", "hf_alpha")
    assert voice.set_tts(s, "openai") == ("openai", "marin")
    assert voice.set_tts(s, "kokoro") == ("kokoro", "hf_alpha")      # remembered per engine
    assert voice.get_voice(s) == "marin"                               # Talk voice untouched


async def test_maya_gets_a_tagged_script_then_local_tts(tmp_path, monkeypatch):
    s = _store(tmp_path)
    voice.set_tts(s, "maya1", "in_female")
    sent = {}

    def handler(req: httpx.Request):
        if req.url.path.endswith("/models"):
            return httpx.Response(200, json={"data": [{"id": "google/gemma-4-12b-qat", "state": "loaded", "type": "llm"}]})
        if req.url.path.endswith("/chat/completions"):
            sent["model"] = json.loads(req.content)["model"]
            return httpx.Response(200, json={"choices": [{"message": {"content": "Good news! <excited> Markets are up."}}]})
        sent["tts"] = json.loads(req.content)
        return httpx.Response(200, content=b"RIFFwav")
    t = httpx.MockTransport(handler)
    script = await voice.maya_script("NIFTY rose 1%.", transport=t)
    assert "<excited>" in script and sent["model"] == "google/gemma-4-12b-qat"
    audio = await voice.local_tts("maya1", script, "in_female", transport=t)
    assert audio == b"RIFFwav" and sent["tts"]["text"].startswith('<description="Realistic female voice') and "<excited>" in sent["tts"]["text"]


async def test_a_dictation_session_only_transcribes(tmp_path):
    """Live dictation (2026-10-08): a short-lived secret for a transcription-only realtime session. No model replies,
    no tools, no persona; the text streams back to the phone as the user talks."""
    captured = {}

    def handler(req):
        captured["path"], captured["auth"], captured["body"] = req.url.path, req.headers["authorization"], json.loads(req.content)
        return httpx.Response(200, json={"value": "ek_dict", "expires_at": 99, "session": {}})
    out = await voice.dictation_session(key="k", transport=httpx.MockTransport(handler))
    sess = captured["body"]["session"]
    assert out == {"client_secret": "ek_dict", "expires_at": 99}
    assert captured["path"] == "/v1/realtime/client_secrets" and captured["auth"] == "Bearer k"
    assert sess["type"] == "transcription" and "tools" not in sess and "instructions" not in sess
    assert sess["audio"]["input"]["transcription"]["model"] == voice.STT_MODEL
    assert sess["audio"]["input"]["turn_detection"]["type"] == "server_vad"  # text arrives phrase by phrase while talking
