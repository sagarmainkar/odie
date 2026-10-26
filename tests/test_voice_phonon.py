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
    assert {k: listed[0][k] for k in ("id", "label", "group", "gender")} == {"id": "zoey", "label": "Zoey", "group": "American · Female",
                                                                                "gender": "female"}
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
# --- Item 3: setup, the setup panel, podcasts and narration ---


def no_ollama():
    def down(request):
        raise httpx.ConnectError("refused")
    return httpx.MockTransport(down)


async def test_setup_offers_what_is_already_here_first(isolated_settings, tmp_path, monkeypatch):
    from odie.setup import tools
    monkeypatch.setenv("ODIE_VOICE", "on")
    monkeypatch.setattr(tools, "load_secret", lambda name: None)
    s = _store(tmp_path)
    ready = (await tools.run("voice_options", {}, s, transport=ollama(tags=("phonon:latest",))))["result"]["options"]
    assert [o["engine"] for o in ready] == ["phonon", "kokoro", "openai"]
    assert ready[0] == {"engine": "phonon", "label": "Phonon through Ollama", "note": "free, private, quick; runs in Ollama on this computer",
                        "recommended": True}
    assert ready[1]["note"] == "Odie's own voice server on this computer" and ready[2]["needs_key"] is True
    not_pulled = (await tools.run("voice_options", {}, s, transport=ollama(tags=("gemma4:e4b",))))["result"]["options"]
    assert [o["engine"] for o in not_pulled] == ["kokoro", "phonon", "openai"]  # what's here first, then what needs a step
    phonon = next(o for o in not_pulled if o["engine"] == "phonon")
    assert phonon["needs"] == "ollama pull phonon" and phonon["note"] == "run `ollama pull phonon` first (113 MB)"
    assert "recommended" not in phonon
    monkeypatch.setenv("ODIE_VOICE", "off")
    nothing = (await tools.run("voice_options", {}, s, transport=no_ollama()))["result"]["options"]
    assert [o["engine"] for o in nothing] == ["openai"]  # no Ollama, an Intel Mac: only OpenAI


async def test_setup_chooses_phonon_only_when_ollama_has_it(isolated_settings, tmp_path, monkeypatch):
    from odie.setup import state, tools
    s = _store(tmp_path)
    refused = await tools.run("set_voice", {"engine": "phonon"}, s, transport=ollama(tags=("gemma4:e4b",)))
    assert "ollama pull phonon" in refused["error"] and state.get(s)["steps"].get("voice") != "done"
    chose = await tools.run("set_voice", {"engine": "phonon"}, s, transport=ollama(tags=("phonon:latest",)))
    assert chose == {"result": {"voice": "phonon"}} and voice.get_tts(s)[0] == "phonon"
    assert state.get(s)["steps"]["voice"] == "done"
    declared = next(d["function"] for d in tools.DECLARATIONS if d["function"]["name"] == "set_voice")
    assert declared["parameters"]["properties"]["engine"]["enum"] == ["phonon", "kokoro", "openai"]


async def test_the_setup_panel_shows_the_same_order_and_the_pull_hint(isolated_settings, tmp_path, monkeypatch):
    from odie.setup import panels
    monkeypatch.setenv("ODIE_VOICE", "on")
    monkeypatch.setattr(panels, "load_secret", lambda name: None)
    s = _store(tmp_path)
    ready = await panels.panel(s, "voice", transport=ollama(tags=("phonon:latest",)))
    assert [c["id"] for c in ready["choices"]] == ["phonon", "kokoro", "openai"]
    assert ready["choices"][0]["recommended"] is True and ready["choices"][0]["label"] == "Phonon through Ollama"
    not_pulled = await panels.panel(s, "voice", transport=ollama(tags=()))
    phonon = next(c for c in not_pulled["choices"] if c["id"] == "phonon")
    assert phonon["note"] == "Run `ollama pull phonon` first (113 MB)" and phonon["needs"] is None  # a text note, no new card
    assert [c["id"] for c in not_pulled["choices"]] == ["kokoro", "phonon", "openai"]
    with pytest.raises(panels.ChoiceError) as e:
        await panels.apply(s, "voice", "phonon", transport=ollama(tags=()))
    assert "ollama pull phonon" in str(e.value)


def test_a_podcast_with_phonon_is_spoken_at_local_speed():
    from odie.skills.podcast import tools
    assert tools.speaking_speed("phonon") == tools.LOCAL_SPEED


async def test_a_podcast_with_phonon_has_two_phonon_hosts(isolated_settings, tmp_path):
    s = _store(tmp_path)
    t = ollama(voices=["zoey", "easton", "freya"])
    await voice.phonon_available(transport=t)
    await voice.phonon_voices(transport=t)
    voice.set_tts(s, "phonon", "freya")
    hosts = voice.podcast_voices(s)
    assert [h["id"] for h in hosts] == ["freya", "easton"]  # the chosen voice, and another of Phonon's
    voice.set_tts(s, "phonon", "easton")
    assert [h["id"] for h in voice.podcast_voices(s)] == ["zoey", "easton"]  # [a woman, a man], as the other engines


async def test_narration_with_phonon_asks_one_phrase_at_a_time(isolated_settings, tmp_path, monkeypatch):
    import asyncio

    from odie.video import narrate
    running = 0
    most = 0

    async def speak(store, text, engine, voice_id, transport, style=""):
        nonlocal running, most
        running += 1
        most = max(most, running)
        await asyncio.sleep(0.01)
        running -= 1
        return ollama_wav(b"\x00\x00")
    monkeypatch.setattr(narrate, "speak", speak)
    await narrate.speak_all(_store(tmp_path), ["One.", "Two.", "Three."], "phonon", "zoey", None)
    assert most == 1


# --- Item 4: groups people can find their way in, and "Another voice" ---


def test_a_voice_is_grouped_by_the_catalogue():
    from odie import voice_phonon
    assert voice_phonon.group_of("Zoey") == "American · Female"
    assert voice_phonon.group_of("ZOEY") == "American · Female"  # Ollama matches names in any case; so does the catalogue
    assert voice_phonon.group_of("Easton") == "American · Male"
    assert voice_phonon.group_of("Maeve") == "British · Female" and voice_phonon.group_of("Alfie") == "British · Male"
    assert voice_phonon.group_of("Captain Silas Blackwater") == "Characters"
    assert voice_phonon.group_of("Someone New") == "Other"
    assert len(voice_phonon.CATALOGUE) == 37


def test_a_note_is_cut_at_a_word_to_seventy_characters():
    from odie import voice_phonon
    zoey = voice_phonon.short_note("Playful, upbeat and Gen Z energy voice with a standard American accent.")
    assert zoey == "Playful, upbeat and Gen Z energy voice with a standard American…" and len(zoey) <= 70
    assert voice_phonon.short_note("Settled and kind.") == "Settled and kind."
    long = voice_phonon.short_note("Cheerful presence with real resonance under it, personable when the copy turns intimate.")
    assert long.endswith("…") and len(long) <= 70 and not long[:-1].endswith((" ", ","))


async def test_ollamas_voices_come_grouped_and_ordered():
    listed = await voice.phonon_voices(transport=ollama(voices=[
        "Someone New", "Alfie", "default", "Captain Silas Blackwater", "Easton", "Maeve", "zoey"]))
    assert [(v["id"], v["group"]) for v in listed] == [
        ("zoey", "American · Female"), ("Easton", "American · Male"), ("Maeve", "British · Female"),
        ("Alfie", "British · Male"), ("Captain Silas Blackwater", "Characters"), ("Someone New", "Other")]  # "default" hidden
    zoey = listed[0]
    assert zoey["label"] == "Zoey" and zoey["gender"] == "female" and zoey["note"].startswith("Playful, upbeat")
    assert listed[-1]["note"] == "" and listed[4]["gender"] is None


def test_a_kept_voice_names_the_model_it_speaks_through():
    assert voice.speaker_of("Noémie (phonon:fr)") == ("phonon:fr", "Noémie")
    assert voice.speaker_of("Zoey") == ("phonon", "Zoey")
    assert voice.speaker_of("Captain Silas Blackwater") == ("phonon", "Captain Silas Blackwater")
    assert voice.kept_voice_id("Noémie", "phonon:fr") == "Noémie (phonon:fr)"
    assert voice.kept_voice_id("Ziggy", "phonon") == "Ziggy"


def test_a_typed_name_is_checked_before_asking_ollama():
    assert voice.typed_name_problem("Noémie") is None
    assert voice.typed_name_problem("  ") == "Type a voice name first."
    assert voice.typed_name_problem("x" * 81) == "That name is too long: 80 characters at most."
    assert voice.typed_name_problem("x" * 80) is None


def fake_phonons(has: dict, seen: list):
    """Ollama with phonon:latest and phonon:fr; `has` maps a model to the voice names it speaks (case-insensitive)."""
    def speech(body):
        seen.append((body["model"], body["voice"]))
        if body["voice"].lower() in {n.lower() for n in has.get(body["model"], [])}:
            return httpx.Response(200, content=ollama_wav(b"\x03\x00" * 10))
        return httpx.Response(400, json={"error": {"message": f'voice "{body["voice"]}" not found; available voices: ...'}})
    return ollama(voices=["zoey", "easton"], tags=("phonon:latest", "phonon:fr", "gemma4:e4b"), speech=speech)


async def test_another_voice_is_found_in_the_first_model_that_has_it(isolated_settings, tmp_path):
    s = _store(tmp_path)
    seen = []
    t = fake_phonons({"phonon": ["zoey", "easton"], "phonon:fr": ["Noémie"]}, seen)
    await voice.phonon_voices(transport=t)
    kept = await voice.check_phonon_voice(s, "Noémie", transport=t)
    assert seen == [("phonon", "Noémie"), ("phonon:fr", "Noémie")]  # phonon first, then the other Phonon models (not :latest again)
    assert kept["id"] == "Noémie (phonon:fr)" and frames_of(kept["audio"])[0] == 10
    assert s.get_setting("voice")["phonon_extra"] == [{"name": "Noémie", "model": "phonon:fr"}]
    assert voice.get_tts(s) == ("phonon", "Noémie (phonon:fr)")  # it becomes the chosen voice
    mine = [v for v in voice.engine_voices("phonon", s) if v["group"] == "Your voices"]
    assert mine == [{"id": "Noémie (phonon:fr)", "label": "Noémie", "group": "Your voices", "note": "through phonon:fr", "gender": None,
                     "kept": True}]
    seen.clear()
    await voice.speak_wav(s, "Bonjour.", transport=t)
    assert seen == [("phonon:fr", "Noémie")]  # spoken through its own model
    voice.forget_phonon_voice(s, "Noémie (phonon:fr)")
    assert voice.get_tts(s) == ("phonon", "zoey") and s.get_setting("voice")["phonon_extra"] == []  # removed: the default voice


async def test_another_voice_no_model_has_is_said_with_the_pull_command(isolated_settings, tmp_path):
    s = _store(tmp_path)
    seen = []
    t = fake_phonons({"phonon": ["zoey"]}, seen)
    with pytest.raises(ValueError) as e:
        await voice.check_phonon_voice(s, "Noémie", transport=t)
    assert str(e.value) == ('No Phonon model here has a voice called "Noémie". French, German, Spanish and Portuguese voices need '
                            "another Phonon model, for example: ollama pull phonon:fr")
    assert seen == [("phonon", "Noémie"), ("phonon:fr", "Noémie")] and "phonon_extra" not in (s.get_setting("voice") or {})


async def test_an_empty_or_long_name_is_refused_without_asking_ollama(isolated_settings, tmp_path):
    s = _store(tmp_path)
    seen = []
    t = fake_phonons({"phonon": ["zoey"]}, seen)
    for name in ("", "   ", "y" * 81):
        with pytest.raises(ValueError):
            await voice.check_phonon_voice(s, name, transport=t)
    assert seen == []


async def test_a_voice_phonon_itself_has_keeps_its_plain_name(isolated_settings, tmp_path):
    s = _store(tmp_path)
    seen = []
    t = fake_phonons({"phonon": ["zoey", "Ziggy"]}, seen)
    kept = await voice.check_phonon_voice(s, "Ziggy", transport=t)
    assert kept["id"] == "Ziggy" and seen == [("phonon", "Ziggy")] and voice.get_tts(s)[1] == "Ziggy"


async def test_a_podcast_pairs_a_woman_and_a_man_from_the_catalogue(isolated_settings, tmp_path):
    s = _store(tmp_path)
    await voice.phonon_voices(transport=ollama(voices=["zoey", "easton", "Maeve", "Alfie"]))
    voice.set_tts(s, "phonon", "Alfie")
    assert [h["id"] for h in voice.podcast_voices(s)] == ["zoey", "Alfie"]  # [a woman, a man]: the chosen man, Zoey with him
    voice.set_tts(s, "phonon", "Maeve")
    assert [h["id"] for h in voice.podcast_voices(s)] == ["Maeve", "easton"]


async def test_the_routes_for_another_voice_and_previews_of_any_name(isolated_settings, tmp_path, monkeypatch):
    from urllib.parse import quote

    from odie.app.main import create_app
    from tests.test_api import FakeRunner
    s = _store(tmp_path)
    seen = []
    t = fake_phonons({"phonon": ["zoey", "Captain Silas Blackwater"], "phonon:fr": ["Noémie"]}, seen)
    await voice.phonon_voices(transport=ollama(voices=["zoey", "Captain Silas Blackwater"]))
    real_check = voice.check_phonon_voice
    real_tts = voice.phonon_tts

    async def check(store, name, transport=None):
        return await real_check(store, name, transport=t)

    async def tts(text, voice_id, transport=None):
        return await real_tts(text, voice_id, transport=t)
    monkeypatch.setattr(voice, "check_phonon_voice", check)
    monkeypatch.setattr(voice, "phonon_tts", tts)
    app = create_app(runner=FakeRunner(), store=s)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c, app.router.lifespan_context(app):
        r = await c.get("/api/voice/preview/phonon/" + quote("Captain Silas Blackwater"))
        assert r.status_code == 200 and r.headers["content-type"] == "audio/wav"
        assert list((isolated_settings.data_dir / "voice").glob("preview-phonon-captain-silas-blackwater-*.wav"))
        r = await c.post("/api/voice/phonon/check", json={"name": "Noémie"})
        assert r.status_code == 200 and r.json()["voice"] == "Noémie (phonon:fr)" and r.json()["engine"] == "phonon"
        assert any(v["id"] == "Noémie (phonon:fr)" for v in r.json()["voices"])
        seen.clear()
        r = await c.get("/api/voice/preview/phonon/" + quote("Noémie (phonon:fr)"))
        assert r.status_code == 200 and seen == []  # the check's own audio is the preview: Ollama isn't asked again
        r = await c.post("/api/voice/phonon/check", json={"name": "Nobody"})
        assert r.status_code == 422 and "ollama pull phonon:fr" in r.json()["detail"]
        assert (await c.post("/api/voice/phonon/check", json={"name": ""})).status_code == 422
        r = await c.delete("/api/voice/phonon/voices/" + quote("Noémie (phonon:fr)"))
        assert r.status_code == 200 and r.json()["voice"] == "zoey"
        assert (await c.get("/api/voice/preview/phonon/" + quote("Noémie (phonon:fr)"))).status_code == 404  # gone


async def test_the_model_reads_phonons_voices_under_the_same_headings():
    await voice.phonon_voices(transport=ollama(voices=["zoey", "Alfie", "The Snow Queen"]))
    text = voice.voices_text("phonon")
    assert text.startswith("American · Female: Zoey (Playful, upbeat")
    assert "; British · Male: Alfie (" in text and "; Characters: The Snow Queen (" in text


async def test_another_voice_that_is_already_listed_is_chosen_not_kept_again(isolated_settings, tmp_path):
    s = _store(tmp_path)
    seen = []
    t = fake_phonons({"phonon": ["zoey", "easton"]}, seen)
    await voice.phonon_voices(transport=t)
    for typed in ("easton", "EASTON", " Easton "):
        kept = await voice.check_phonon_voice(s, typed, transport=t)
        assert kept == {"id": "easton", "audio": None}  # the listed voice, chosen; no second Easton under "Your voices"
    assert seen == []  # Ollama isn't asked: the list already says it has the voice
    assert voice.get_tts(s) == ("phonon", "easton")
    assert "phonon_extra" not in (s.get_setting("voice") or {})


async def test_the_route_leaves_a_listed_voices_preview_alone(isolated_settings, tmp_path, monkeypatch):
    from urllib.parse import quote

    from odie.app.main import create_app
    from tests.test_api import FakeRunner
    s = _store(tmp_path)
    t = fake_phonons({"phonon": ["zoey"]}, [])
    await voice.phonon_voices(transport=t)
    real_check = voice.check_phonon_voice

    async def check(store, name, transport=None):
        return await real_check(store, name, transport=t)
    monkeypatch.setattr(voice, "check_phonon_voice", check)
    app = create_app(runner=FakeRunner(), store=s)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c, app.router.lifespan_context(app):
        folder = isolated_settings.data_dir / "voice"
        folder.mkdir(parents=True, exist_ok=True)
        r = await c.post("/api/voice/phonon/check", json={"name": "ZOEY"})
        assert r.status_code == 200 and r.json()["voice"] == "zoey"  # the id Ollama lists
        assert list(folder.glob("preview-*")) == []  # no check line written as Zoey's preview
        assert (await c.delete("/api/voice/phonon/voices/" + quote("ZOEY"))).status_code == 200


def test_previews_of_names_that_differ_only_in_case_or_script_are_separate_files(isolated_settings):
    from odie.app.routes import _preview_name
    assert _preview_name("phonon", "Zoey") != _preview_name("phonon", "ZOEY")
    assert _preview_name("phonon", "Марина (phonon:ru)") != _preview_name("phonon", "Ольга (phonon:ru)")
    assert _preview_name("phonon", "Captain Silas Blackwater").startswith("phonon-captain-silas-blackwater-")


def test_a_missing_model_names_the_model_to_pull():
    gone = json.dumps({"error": 'model "phonon:fr" not found, try pulling it first'})
    assert voice.phonon_problem(404, gone, "Noémie", "phonon:fr") == (
        "Ollama doesn't have phonon:fr: run `ollama pull phonon:fr`, then try again.")
    plain = json.dumps({"error": 'model "phonon" not found'})
    assert voice.phonon_problem(404, plain, "zoey", "phonon") == voice.PULL_PHONON


async def test_at_launch_nothing_chosen_waits_for_ollama_before_starting_kokoro(isolated_settings, tmp_path, monkeypatch):
    from odie import voice_worker
    from odie.app import main
    monkeypatch.setenv("ODIE_VOICE", "on")
    monkeypatch.setattr(voice_worker, "VoiceWorker", FakeWorker)
    s = _store(tmp_path)
    voice.forget_phonon()
    await main._launch_voice_worker(s, tmp_path)
    assert voice_worker.current.calls == []  # nothing chosen: not started before Ollama has been asked

    async def has_phonon(transport=None):
        voice._PHONON_SEEN["here"] = True
        return True

    async def no_phonon(transport=None):
        voice._PHONON_SEEN["here"] = False
        return False

    async def no_voices(transport=None):
        return []
    monkeypatch.setattr(voice, "phonon_voices", no_voices)
    monkeypatch.setattr(voice, "phonon_available", has_phonon)
    await main._learn_phonon(s)
    assert "start" not in voice_worker.current.calls  # Phonon is the default: Kokoro's server never starts
    voice_worker.current.calls.clear()
    monkeypatch.setattr(voice, "phonon_available", no_phonon)
    await main._learn_phonon(s)
    assert voice_worker.current.calls == ["start"]  # no Phonon: Kokoro is the default, so it starts now
    voice.forget_phonon()
    monkeypatch.setattr(voice_worker, "current", None)
