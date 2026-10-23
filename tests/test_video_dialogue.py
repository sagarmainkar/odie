"""A dialogue video: a script of scenes and speakers' lines, read from the user's own file, each line spoken in its
speaker's voice, with the loudness the characters' mouths follow and the timeline the page and the user get."""
import io
import math
import struct
import wave

import pytest

from odie.video import dialogue

SCRIPT = """---
title: ignored front matter
---
# The night shift

Some notes for the writers, ignored.

## Scene: A workshop at night
NARRATOR: The lamp had been burning for hours.
anna: You're still here? [pause 1.2]
BEN: Someone has to finish it.

## Scene: The roof at dawn
Ben: Look.
"""


def test_a_script_reads_as_scenes_of_speakers_lines_with_pauses():
    script = dialogue.parse(SCRIPT)
    assert [scene.where for scene in script.scenes] == ["A workshop at night", "The roof at dawn"]
    first = script.scenes[0].lines
    assert [(line.speaker, line.text) for line in first] == [
        ("narrator", "The lamp had been burning for hours."),
        ("anna", "You're still here?"),
        ("ben", "Someone has to finish it."),
    ]
    assert first[1].pause == 1.2
    assert first[0].pause == dialogue.DEFAULT_PAUSE
    assert script.speakers() == ["anna", "ben", "narrator"]


def test_lines_before_any_scene_heading_are_the_first_scene():
    script = dialogue.parse("ANNA: Hello.\nBEN: Hi.")
    assert len(script.scenes) == 1 and script.scenes[0].where == ""


def test_a_script_without_lines_is_refused_in_words():
    with pytest.raises(dialogue.ScriptProblem, match="no lines"):
        dialogue.parse("## Scene: Empty\nJust some notes.")


def test_a_scene_without_lines_is_refused_naming_it():
    with pytest.raises(dialogue.ScriptProblem, match="The hallway"):
        dialogue.parse("## Scene: The hallway\n\n## Scene: The roof\nANNA: Hi.")


def test_every_speaker_but_the_narrator_needs_a_voice():
    script = dialogue.parse(SCRIPT)
    assert dialogue.missing_voices(script, {"anna": "af_heart"}) == ["ben"]
    assert dialogue.missing_voices(script, {"anna": "af_heart", "BEN": "am_michael"}) == []


def test_voices_are_read_by_speaker_whatever_the_case():
    assert dialogue.voices_by_speaker([{"id": "Anna", "name": "af_heart"}, {"id": "ben", "name": "am_michael"}]) == {
        "anna": "af_heart", "ben": "am_michael"}
    with pytest.raises(dialogue.ScriptProblem, match="id and a name"):
        dialogue.voices_by_speaker([{"id": "anna"}])


def test_the_writer_gets_each_scene_as_its_lines_one_phrase_each():
    script = dialogue.parse(SCRIPT)
    narration = dialogue.narration_of(script)
    assert narration[0] == ("The lamp had been burning for hours. | You're still here? | Someone has to finish it.")
    assert narration[1] == "Look."


def tone_then_quiet(seconds_loud: float, seconds_quiet: float, rate: int = 24000) -> bytes:
    frames = []
    for i in range(int(rate * seconds_loud)):
        frames.append(int(12000 * math.sin(2 * math.pi * 220 * i / rate)))
    frames += [0] * int(rate * seconds_quiet)
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack(f"<{len(frames)}h", *frames))
    return buffer.getvalue()


def test_loudness_comes_every_20_ms_from_0_to_1():
    levels = dialogue.loudness(tone_then_quiet(0.2, 0.2))
    assert len(levels) == 20  # 0.4 s in 20 ms steps
    assert max(levels) == 1.0
    assert levels[2] > 0.9 and levels[-1] == 0.0  # loud while the tone plays, silent after


def test_silence_is_all_zeros_not_an_error():
    assert set(dialogue.loudness(tone_then_quiet(0, 0.1))) == {0.0}


@pytest.fixture
def store(isolated_settings, tmp_path):
    from odie.store.db import Store
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    return s


async def test_each_line_is_spoken_in_its_speakers_voice_and_laid_with_its_pause(store):
    from odie.video import narrate
    from tests.test_speak import kokoro
    spoken = []
    script = dialogue.parse(SCRIPT)
    voices = {"anna": "af_bella", "ben": "am_michael"}
    wav, lengths, beats, lines = await narrate.narrate_dialogue(store, script, voices, transport=kokoro(spoken, 1.0))
    said = {call["text"]: call["voice"] for call in spoken}
    assert said["You're still here?"] == "af_bella" and said["Someone has to finish it."] == "am_michael"
    assert said["The lamp had been burning for hours."] == "af_heart"  # the narrator: the video voice
    # scene 1: three 1 s lines, 0.35 s after the first, 1.2 s after the second -> 3 + 0.35 + 1.2 = 4.55 s
    assert lengths == [4.55, 1.0]
    assert beats == [[0.0, 1.35, 3.55], [0.0]]
    assert [(line["index"], line["speaker"], line["scene"], line["at"], line["dur"]) for line in lines] == [
        (0, "narrator", 1, 0.0, 1.0), (1, "anna", 1, 1.35, 1.0), (2, "ben", 1, 3.55, 1.0), (3, "ben", 2, 0.0, 1.0)]
    assert len(lines[0]["amplitude"]) == 50 and max(lines[0]["amplitude"]) == 1.0
    total = 4.55 + 0.5 + 1.0  # the scenes joined with the usual breath
    with wave.open(io.BytesIO(wav)) as w:
        assert round(w.getnframes() / w.getframerate(), 2) == total
