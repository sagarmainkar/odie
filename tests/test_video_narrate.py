"""Narration: each scene spoken in the voice chosen in Settings, measured from its own WAV, joined with a breath."""
import io
import json
import wave

import httpx
import pytest

from odie import voice
from odie.store.db import Store
from odie.video import narrate
from tests.test_media import make_wav
from tests.test_speak import kokoro  # a stand-in for Odie's local voice server


@pytest.fixture
def store(isolated_settings, tmp_path):
    """A fresh store in isolated settings, as tests/test_speak.py makes it."""
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    return s


def wave_seconds(wav: bytes) -> float:
    with wave.open(io.BytesIO(wav)) as w:
        return w.getnframes() / w.getframerate()


async def test_each_scene_is_spoken_in_the_settings_voice_and_measured(store):
    spoken = []
    wav, lengths, beats = await narrate.narrate(store, ["First scene.", "Second scene."],
                                                transport=kokoro(spoken, 1.25))
    assert lengths == [1.25, 1.25]
    assert beats == [[0.0], [0.0]]  # a scene without marks is one beat
    assert [call["voice"] for call in spoken] == ["af_heart", "af_heart"]  # the Settings default in a fresh store
    assert [call["text"] for call in spoken] == ["First scene.", "Second scene."]
    assert wave_seconds(wav) == 1.25 + 0.5 + 1.25


async def test_another_engines_voice_is_refused_before_speaking(store):
    spoken = []
    with pytest.raises(ValueError, match="Settings"):
        await narrate.narrate(store, ["Hi."], voice_name="cedar", transport=kokoro(spoken, 1.0))
    assert spoken == []  # a bad voice costs no speech


async def test_a_voice_of_the_chosen_engine_is_used_for_every_scene(store):
    spoken = []
    await narrate.narrate(store, ["One.", "Two."], voice_name="Michael", transport=kokoro(spoken, 0.5))
    assert [call["voice"] for call in spoken] == ["am_michael", "am_michael"]


async def test_a_voice_that_doesnt_answer_is_told_plainly(store):
    def refused(request):
        raise httpx.ConnectError("Connection refused", request=request)

    with pytest.raises(voice.VoiceUnavailable) as caught:
        await narrate.narrate(store, ["Hi."], transport=httpx.MockTransport(refused))
    assert str(caught.value) == "Odie's voice didn't answer (Settings → Voice): Connection refused"


async def test_a_voice_that_says_no_is_told_with_its_status(store):
    def unauthorised(request):
        return httpx.Response(401, json={"error": "bad key"})

    with pytest.raises(voice.VoiceUnavailable) as caught:
        await narrate.narrate(store, ["Hi."], transport=httpx.MockTransport(unauthorised))
    message = str(caught.value)
    assert message.startswith("Odie's voice didn't answer (Settings → Voice): ") and "401" in message
    assert "\n" not in message  # one line, without httpx's "for more information" link


# A stand-in voice whose WAV for each text has a known length and its own tone, so pieces can be told apart.
PHRASES = {"Babur came from Fergana": (1.0, 440.0), "and won at Panipat.": (2.0, 660.0), "Then Akbar.": (0.5, 880.0)}


def voice_by_text(seen):
    def handler(request):
        text = json.loads(request.content)["text"]
        seen.append(text)
        seconds, tone = PHRASES[text]
        return httpx.Response(200, content=make_wav(seconds, freq=tone))
    return httpx.MockTransport(handler)


def frames_of(wav: bytes) -> bytes:
    with wave.open(io.BytesIO(wav)) as w:
        return w.readframes(w.getnframes())


async def test_each_phrase_is_spoken_on_its_own_and_its_start_is_a_beat(store):
    seen = []
    wav, lengths, beats = await narrate.narrate(store, ["Babur came from Fergana | and won at Panipat."],
                                                transport=voice_by_text(seen))
    assert seen == ["Babur came from Fergana", "and won at Panipat."]  # the marks are never spoken
    assert lengths == [3.0]
    assert beats == [[0.0, 1.0]]


async def test_a_scenes_pieces_are_joined_in_order_with_no_gap(store):
    wav, _lengths, _beats = await narrate.narrate(store, ["Babur came from Fergana | and won at Panipat."],
                                                  transport=voice_by_text([]))
    first = make_wav(1.0, freq=440.0)
    second = make_wav(2.0, freq=660.0)
    assert frames_of(wav) == frames_of(first) + frames_of(second)
    assert wave_seconds(wav) == 3.0


async def test_the_breath_between_scenes_is_unchanged(store):
    wav, lengths, beats = await narrate.narrate(store, ["Babur came from Fergana | and won at Panipat.",
                                                        "Then Akbar."], transport=voice_by_text([]))
    assert lengths == [3.0, 0.5]
    assert beats == [[0.0, 1.0], [0.0]]
    assert wave_seconds(wav) == 3.0 + 0.5 + 0.5  # the 0.5 s breath between scenes, none inside a scene
