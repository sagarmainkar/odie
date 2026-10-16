"""Narration: each scene spoken in the voice chosen in Settings, measured from its own WAV, joined with a breath."""
import io
import wave

import httpx
import pytest

from odie import voice
from odie.video import narrate
# The `store` fixture and the `kokoro` stand-in for Odie's local voice server come from tests/test_speak.py.
from tests.test_speak import kokoro, store  # noqa: F401


def wave_seconds(wav: bytes) -> float:
    with wave.open(io.BytesIO(wav)) as w:
        return w.getnframes() / w.getframerate()


async def test_each_scene_is_spoken_in_the_settings_voice_and_measured(store):
    spoken = []
    wav, lengths = await narrate.narrate(store, ["First scene.", "Second scene."], transport=kokoro(spoken, 1.25))
    assert lengths == [1.25, 1.25]
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
