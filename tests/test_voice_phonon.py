"""Phonon through Ollama as a read-aloud engine (odie.voice): the voices Ollama lists, the speech request, long text
split and joined into one WAV, plain reasons when Ollama can't help, and when Phonon is the default engine. Every
call to Ollama goes through httpx.MockTransport; no test reaches a real Ollama."""
import io
import json
import struct
import wave

import httpx
import pytest

from odie import voice
from odie.store.db import Store
from odie.voice import (
    ollama_root as real_ollama_root,  # before the autouse fixture points the voice side elsewhere
)


def _store(tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


def ollama_wav(pcm: bytes, rate: int = 24000) -> bytes:
    """A WAV as Ollama streams it: 16-bit mono, and size fields that say nothing (it doesn't know the length yet)."""
    fmt = struct.pack("<HHIIHH", 1, 1, rate, rate * 2, 2, 16)
    return b"RIFF" + b"\xff\xff\xff\xff" + b"WAVE" + b"fmt " + struct.pack("<I", 16) + fmt + b"data" + b"\xff\xff\xff\xff" + pcm


def frames_of(wav_bytes: bytes) -> tuple[int, int, int]:
    """(frames, rate, channels) of a WAV, read with the standard library: it trusts the header, so a wrong one shows."""
    with wave.open(io.BytesIO(wav_bytes)) as w:
        return w.getnframes(), w.getframerate(), w.getnchannels()


def ollama(voices=None, tags=("phonon:latest",), speech=None, seen=None):
    """A fake Ollama: /api/show lists `voices`, /api/tags lists `tags`, /v1/audio/speech answers `speech(body)`."""
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request)
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"voices": list(voices or [])})
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": t} for t in tags]})
        if request.url.path == "/v1/audio/speech":
            body = json.loads(request.content)
            if speech is not None:
                return speech(body)
            return httpx.Response(200, content=ollama_wav(b"\x01\x00" * 100), headers={"content-type": "audio/wav"})
        return httpx.Response(404, json={"error": "not here"})
    return httpx.MockTransport(handler)


def test_phonon_is_an_engine_that_is_never_hidden():
    assert voice.ENGINES["phonon"] == {"label": "Phonon (Ollama)", "note": "On this computer through Ollama. Quick, streams, no expressions.",
                                       "local": True}
    assert "phonon" not in voice._HIDDEN


def test_ollamas_address_is_the_chat_sides(monkeypatch):
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.setattr("odie.models.load_secret", lambda name: None)
    assert real_ollama_root() == "http://localhost:11434"
    monkeypatch.setattr("odie.models.load_secret", lambda name: "http://studio.local:11434/v1/" if name == "OLLAMA_BASE_URL" else None)
    assert real_ollama_root() == "http://studio.local:11434"


async def test_the_speech_request_and_its_answer():
    seen = []
    wav = await voice.phonon_tts("Hello there.", "zoey", transport=ollama(seen=seen))
    [request] = seen
    assert request.method == "POST" and request.url.path == "/v1/audio/speech"
    assert json.loads(request.content) == {"model": "phonon", "input": "Hello there.", "voice": "zoey", "response_format": "wav"}
    assert frames_of(wav) == (100, 24000, 1)  # a header that tells the truth about the PCM


async def test_the_voices_come_from_ollama_and_are_kept_for_the_process():
    seen = []
    listed = await voice.phonon_voices(transport=ollama(voices=["zoey", "easton", "freya"], seen=seen))
    assert [v["id"] for v in listed] == ["zoey", "easton", "freya"]
    assert listed[0] == {"id": "zoey", "label": "Zoey", "group": ""}
    assert seen[0].url.path == "/api/show" and json.loads(seen[0].content) == {"model": "phonon"}
    again = await voice.phonon_voices(transport=ollama(voices=["other"], seen=seen))
    assert again == listed and len(seen) == 1  # Settings opening again doesn't ask Ollama again
    assert voice.engine_voices("phonon") == listed


async def test_before_ollama_answers_there_is_one_default_voice():
    assert voice.engine_voices("phonon") == [{"id": "default", "label": "Default", "group": ""}]  # nothing fetched yet
    assert await voice.phonon_voices(transport=ollama(voices=[])) == [{"id": "default", "label": "Default", "group": ""}]

    def down(request):
        raise httpx.ConnectError("refused")
    assert await voice.phonon_voices(transport=httpx.MockTransport(down)) == [{"id": "default", "label": "Default", "group": ""}]
    assert (await voice.phonon_voices(transport=ollama(voices=["zoey"])))[0]["id"] == "zoey"  # a failure wasn't kept: asked again


def test_the_default_phonon_voice():
    assert voice.default_phonon_voice([{"id": "freya"}, {"id": "ZOEY"}]) == "ZOEY"  # Zoey in any case
    assert voice.default_phonon_voice([{"id": "freya"}, {"id": "easton"}]) == "freya"  # else the first listed
    assert voice.default_phonon_voice([]) == "default"


async def test_long_text_is_split_at_sentences_and_joined_into_one_wav():
    sentence = "This sentence is exactly fifty characters long ok. "
    assert len(sentence) == 51
    text = (sentence * 177).strip()  # about 9,000 characters
    assert 8900 < len(text) < 9100
    asked = []

    def speech(body):
        asked.append(body["input"])
        return httpx.Response(200, content=ollama_wav(b"\x02\x00" * 1000))
    wav = await voice.phonon_tts(text, "zoey", transport=ollama(speech=speech))
    assert len(asked) == 3 and all(len(part) <= voice.PHONON_MAX_CHARS for part in asked)
    assert all(part.endswith(".") for part in asked)  # cut at sentence ends, never mid-sentence
    assert " ".join(asked) == text  # nothing lost, nothing repeated
    assert frames_of(wav) == (3000, 24000, 1)  # one WAV: the three pieces' PCM, one correct header


def test_a_sentence_longer_than_a_request_is_cut_at_a_space():
    words = "word " * 1000  # one 5,000-character sentence with no full stop
    parts = voice.split_for_phonon(words.strip())
    assert len(parts) == 2 and all(len(p) <= voice.PHONON_MAX_CHARS for p in parts) and " ".join(parts) == words.strip()
    assert voice.split_for_phonon("Short. Two.") == ["Short. Two."]


async def test_ollama_without_phonon_says_to_pull_it():
    def missing(body):
        return httpx.Response(404, json={"error": "model \"phonon\" not found, try pulling it first"})
    with pytest.raises(voice.VoiceUnavailable) as e:
        await voice.phonon_tts("Hi.", "zoey", transport=ollama(speech=missing))
    assert "ollama pull phonon" in str(e.value) and "Ollama doesn't have phonon" in str(e.value)


async def test_a_voice_phonon_lacks_is_said_plainly():
    def no_voice(body):
        return httpx.Response(400, json={"error": {"message": "voice \"Nobody\" not found; available voices: zoey, easton"}})
    with pytest.raises(voice.VoiceUnavailable) as e:
        await voice.phonon_tts("Hi.", "Nobody", transport=ollama(speech=no_voice))
    assert "Nobody" in str(e.value) and "Settings" in str(e.value)


async def test_an_unreachable_ollama_is_said_plainly():
    def down(request):
        raise httpx.ConnectError("refused")
    with pytest.raises(voice.VoiceUnavailable) as e:
        await voice.phonon_tts("Hi.", "zoey", transport=httpx.MockTransport(down))
    assert "Ollama isn't answering" in str(e.value)


async def test_phonon_is_available_when_ollama_has_a_phonon_model():
    assert await voice.phonon_available(transport=ollama(tags=("phonon:latest", "gemma4:e4b"))) is True
    assert await voice.phonon_available(transport=ollama(tags=("phonon:fr",))) is True
    assert await voice.phonon_available(transport=ollama(tags=("gemma4:e4b",))) is False

    def down(request):
        raise httpx.ConnectError("refused")
    assert await voice.phonon_available(transport=httpx.MockTransport(down)) is False


async def test_the_default_engine_prefers_phonon_then_kokoro_then_openai(monkeypatch):
    monkeypatch.setenv("ODIE_VOICE", "on")
    assert voice.default_engine() == "kokoro"  # Ollama not asked yet: what Odie knew before
    await voice.phonon_available(transport=ollama(tags=("phonon:latest",)))
    assert voice.default_engine() == "phonon"
    monkeypatch.setenv("ODIE_VOICE", "off")
    assert voice.default_engine() == "phonon"  # an Intel Mac runs Phonon too: it is Ollama's, not Odie's own server
    await voice.phonon_available(transport=ollama(tags=()))
    assert voice.default_engine() == "openai"
    monkeypatch.setenv("ODIE_VOICE", "on")
    assert voice.default_engine() == "kokoro"


async def test_choosing_and_speaking_with_phonon(isolated_settings, tmp_path, monkeypatch):
    monkeypatch.setenv("ODIE_VOICE", "off")  # an Intel Mac: Phonon is offered where Kokoro isn't
    s = _store(tmp_path)
    t = ollama(voices=["zoey", "easton"])
    await voice.phonon_available(transport=t)
    await voice.phonon_voices(transport=t)
    assert voice.get_tts(s) == ("phonon", "zoey")  # nothing chosen: Phonon, Zoey
    assert voice.set_tts(s, "phonon", "easton") == ("phonon", "easton")
    assert voice.set_tts(s, voice="nobody") == ("phonon", "easton")  # not a voice Ollama listed: ignored
    seen = []
    wav = await voice.speak_wav(s, "Hello.", transport=ollama(seen=seen))
    assert json.loads(seen[0].content)["voice"] == "easton" and frames_of(wav)[0] == 100


async def test_a_saved_phonon_voice_stands_before_ollama_is_asked(isolated_settings, tmp_path):
    s = _store(tmp_path)
    s.set_setting("voice", {"engine": "phonon", "phonon_voice": "easton"})
    assert voice.get_tts(s) == ("phonon", "easton")  # a restart: the voice list isn't read yet, the choice still holds


async def test_settings_lists_phonon_with_its_voices(isolated_settings, tmp_path, monkeypatch):
    from odie.app.main import create_app
    from tests.test_api import FakeRunner
    monkeypatch.setenv("ODIE_VOICE", "off")
    monkeypatch.setattr(voice, "load_secret", lambda name: None)
    s = _store(tmp_path)
    app = create_app(runner=FakeRunner(), store=s)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c, app.router.lifespan_context(app):
        j = (await c.get("/api/voice")).json()
        phonon = next(e for e in j["engines"] if e["id"] == "phonon")
        assert phonon["available"] is False and phonon["voices"] == [voice.PHONON_DEFAULT]  # no Ollama: listed, not available

        async def has_phonon(transport=None):
            return ["phonon:latest"]
        monkeypatch.setattr(voice, "phonon_models", has_phonon)
        await voice.phonon_voices(transport=ollama(voices=["zoey", "easton"]))
        j = (await c.get("/api/voice")).json()
        phonon = next(e for e in j["engines"] if e["id"] == "phonon")
        assert phonon["available"] is True and [v["id"] for v in phonon["voices"]] == ["zoey", "easton"]
        assert j["engine"] == "phonon" and j["voice"] == "zoey"  # nothing chosen, no key, an Intel Mac: Phonon is the default
        assert (await c.put("/api/voice", json={"engine": "phonon", "voice": "easton"})).json()["voice"] == "easton"


# --- Item 2: Odie's own voice server runs only when read-aloud uses it ---


class FakeWorker:
    """Records what is asked of Odie's voice worker; it never starts a process."""
    def __init__(self, log=None, installed=True):
        self.calls: list[str] = []
        self.problem = "fake worker: not a real server"
        self.proc = None
        self.installed = installed

    async def start(self):
        self.calls.append("start")

    async def ensure(self, timeout: float = 30):
        self.calls.append("ensure")
        return False  # the fake never answers: speaking then says why, which is enough to see it was asked

    async def stop(self):
        self.calls.append("stop")

    async def healthy(self):
        return False


def test_the_worker_is_wanted_only_for_its_own_engines(isolated_settings, tmp_path, monkeypatch):
    monkeypatch.setenv("ODIE_VOICE", "on")
    s = _store(tmp_path)
    s.set_setting("voice", {"engine": "kokoro"})
    assert voice.worker_wanted(s) is True
    s.set_setting("voice", {"engine": "phonon"})
    assert voice.worker_wanted(s) is False
    monkeypatch.setattr(voice, "load_secret", lambda name: "sk-test")
    s.set_setting("voice", {"engine": "openai"})
    assert voice.worker_wanted(s) is False


async def test_at_launch_the_worker_starts_only_for_kokoro(isolated_settings, tmp_path, monkeypatch):
    from odie import voice_worker
    from odie.app import main
    monkeypatch.setenv("ODIE_VOICE", "on")
    monkeypatch.setattr(voice_worker, "VoiceWorker", FakeWorker)
    s = _store(tmp_path)
    s.set_setting("voice", {"engine": "phonon"})
    await main._launch_voice_worker(s, tmp_path)
    assert isinstance(voice_worker.current, FakeWorker) and voice_worker.current.calls == []  # made, not started
    s.set_setting("voice", {"engine": "kokoro"})
    await main._launch_voice_worker(s, tmp_path)
    assert voice_worker.current.calls == ["start"]
    monkeypatch.setattr(voice_worker, "current", None)


async def test_choosing_kokoro_later_starts_it_and_leaving_kokoro_stops_it(isolated_settings, tmp_path, monkeypatch):
    from odie import voice_worker
    monkeypatch.setenv("ODIE_VOICE", "on")
    worker = FakeWorker()
    monkeypatch.setattr(voice_worker, "current", worker)
    s = _store(tmp_path)
    voice.set_tts(s, "phonon")
    voice.set_tts(s, "kokoro")
    with pytest.raises(voice.VoiceUnavailable):
        await voice.speak(s, "Hello.")  # the kokoro path asks the worker to be up first (here: it says why it can't)
    assert worker.calls == ["ensure"]
    voice.set_tts(s, "phonon")
    await voice.settle_worker(s)
    assert worker.calls == ["ensure", "stop"]  # away from Kokoro: the server goes
    voice.set_tts(s, "kokoro")
    await voice.settle_worker(s)
    assert worker.calls == ["ensure", "stop"]  # back on Kokoro: nothing now; the next speech starts it on demand


async def test_the_settings_route_stops_the_worker_when_kokoro_is_left(isolated_settings, tmp_path, monkeypatch):
    from odie import voice_worker
    from odie.app.main import create_app
    from tests.test_api import FakeRunner
    monkeypatch.setenv("ODIE_VOICE", "on")
    worker = FakeWorker()
    s = _store(tmp_path)
    app = create_app(runner=FakeRunner(), store=s)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c, app.router.lifespan_context(app):
        monkeypatch.setattr(voice_worker, "current", worker)
        await c.put("/api/voice", json={"engine": "kokoro"})
        assert worker.calls == []
        await c.put("/api/voice", json={"engine": "phonon"})
        assert worker.calls == ["stop"]


async def test_kokoro_stays_choosable_while_its_server_is_stopped(isolated_settings, tmp_path, monkeypatch):
    """With Phonon chosen, Odie's own voice server isn't running; Settings must still let Kokoro be chosen (it starts on
    demand). Only a server that isn't set up at all makes Kokoro unavailable."""
    from odie import voice_worker
    from odie.app.main import create_app
    from tests.test_api import FakeRunner
    monkeypatch.setenv("ODIE_VOICE", "on")
    s = _store(tmp_path)
    app = create_app(runner=FakeRunner(), store=s)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c, app.router.lifespan_context(app):
        monkeypatch.setattr(voice_worker, "current", FakeWorker())  # set up, not running
        kokoro = next(e for e in (await c.get("/api/voice")).json()["engines"] if e["id"] == "kokoro")
        assert kokoro["available"] is True
        monkeypatch.setattr(voice_worker, "current", FakeWorker(installed=False))  # never `uv sync`ed
        kokoro = next(e for e in (await c.get("/api/voice")).json()["engines"] if e["id"] == "kokoro")
        assert kokoro["available"] is False
