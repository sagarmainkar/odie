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
    assert first[0].pause is None  # none given: DEFAULT_PAUSE between lines (Line.pause_after)
    assert first[0].pause_after(is_last_in_scene=False) == dialogue.DEFAULT_PAUSE
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
    assert levels[2] > 0.9 and levels[-1] < 0.05  # loud while the tone plays, quiet after


def test_a_mouth_opens_at_once_and_closes_over_a_tenth_of_a_second():
    """Speech dips between syllables for a frame or two; a mouth that shut on every dip would flicker. The loudness
    rises at once but falls off gently: 1.0 then quiet -> 0.7, 0.49, … (closed, under 0.15, after about 0.1 s)."""
    levels = dialogue.loudness(tone_then_quiet(0.1, 0.2))
    assert levels[5] == 0.7 and levels[6] == 0.49
    assert levels[10] < 0.15 <= levels[9]  # closed 0.12 s after the voice stops


def test_loudness_is_scaled_to_the_lines_usual_peaks_not_one_spike():
    """One click far louder than the voice would leave every other moment near 0 (a shut mouth all line long): the
    scale is the line's 95th percentile, and anything over it is 1.0."""
    import io as io_lib
    rate = 24000
    frames = [int(3000 * math.sin(2 * math.pi * 220 * i / rate)) for i in range(int(rate * 0.5))]
    frames[100:200] = [30000] * 100  # a click
    buffer = io_lib.BytesIO()
    with wave.open(buffer, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(struct.pack(f"<{len(frames)}h", *frames))
    levels = dialogue.loudness(buffer.getvalue())
    assert levels[15] > 0.5  # the voice itself still opens the mouth


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


def test_the_writer_stages_a_script_with_its_own_guide_and_no_narration():
    from odie.video import writer
    instruction = writer.instruction_for("landscape", dialogue=True)
    assert instruction.startswith(writer.INSTRUCTION.rstrip())
    assert "never change, add or drop a word" in instruction and "s.mouth(" in instruction
    assert writer.instruction_for("landscape") == writer.INSTRUCTION  # no script: as before
    assert sorted(writer.submit_fields(None, dialogue=True)) == ["page", "title"]
    staged = dialogue.staging(dialogue.parse(SCRIPT))
    prompt = writer.prompt_for_dialogue("The night shift", "A quiet, warm look.", staged.listing)
    assert "line 1 · anna: You're still here?" in prompt and "A quiet, warm look." in prompt
    assert "narration" not in writer.prompt_for_dialogue("T", "", staged.listing).lower().replace("no narration", "")


def test_the_page_check_draws_with_estimated_lines():
    staged = dialogue.staging(dialogue.parse(SCRIPT))
    timings = {"starts": [0.0, 8.0], "lengths": [7.5, 2.0], "beats": [[0.0, 2.5, 4.0], [0.0]]}
    script = staged.lines_for(timings)
    assert script.startswith("<script>Video.lines(")
    assert '"speaker": "anna"' in script and '"t": 2.5' in script and '"text": "Look."' in script


async def test_a_dialogue_job_times_its_page_from_the_lines_and_keeps_a_timeline(isolated_settings, tmp_path,
                                                                                   monkeypatch):
    """The making step of a dialogue video: its lines spoken (narrate_dialogue), their timeline in the page
    (Video.lines, t in seconds into the video), and timeline.json next to the video with every line's text, voice,
    start and length."""
    import json as json_lib

    from odie.making import jobs
    from odie.store.db import Store
    from odie.video import kind
    from tests.test_media import make_wav
    from tests.test_video_jobs import make_job, stand_in_render

    store = Store(tmp_path / "assistant.db")
    store.init_schema()
    monkeypatch.setitem(jobs.hooks, "store", store)
    script = dialogue.parse("## Scene: A\nANNA: Hi. [pause 0.5]\nBEN: Hello.\n## Scene: B\nANNA: Bye.")
    job = make_job(slug="night", title="Night")
    job.data = {"narration": dialogue.narration_of(script), "body": "<div></div>",
                "dialogue": {"script": script.as_data(), "voices": {"anna": "af_bella", "ben": "am_michael"}}}

    async def stand_in_dialogue(store, script, voices, transport=None, style="", narrator_voice=""):
        lines = [{"index": 0, "speaker": "anna", "text": "Hi.", "voice": "af_bella", "scene": 1, "at": 0.0,
                  "dur": 1.0, "amplitude": [1.0]},
                 {"index": 1, "speaker": "ben", "text": "Hello.", "voice": "am_michael", "scene": 1, "at": 1.5,
                  "dur": 1.0, "amplitude": [0.5]},
                 {"index": 2, "speaker": "anna", "text": "Bye.", "voice": "af_bella", "scene": 2, "at": 0.0,
                  "dur": 1.0, "amplitude": []}]
        return make_wav(4.0), [2.5, 1.0], [[0.0, 1.5], [0.0]], lines

    seen = {}

    async def watching_render(browser, body, timings, folder, fps, tabs, progress=None, assets_script="",
                              credits_script="", size=None, brand_script="", lines_script=""):
        seen["timings"] = timings
        seen["lines_script"] = lines_script
        return await stand_in_render(browser, body, timings, folder, fps, tabs)

    def unused_narrate(*args, **kwargs):
        raise AssertionError("a dialogue video never takes the narrator's path")

    monkeypatch.setattr(kind, "narrate_dialogue", stand_in_dialogue)
    monkeypatch.setattr(kind, "narrate", unused_narrate)
    monkeypatch.setattr(kind, "render", watching_render)
    await kind.make_video(job, browser=object(), transport=None)

    assert seen["timings"] == {"starts": [0.0, 3.0], "lengths": [2.5, 1.0], "beats": [[0.0, 1.5], [0.0]]}
    placed = json_lib.loads(seen["lines_script"].removeprefix("<script>Video.lines(").removesuffix(")</script>"))
    assert [(line["speaker"], line["t"]) for line in placed] == [("anna", 0.0), ("ben", 1.5), ("anna", 3.0)]
    assert "<script>Video.lines(" in (job.folder / "page.html").read_text()
    kept = json_lib.loads((job.folder / "timeline.json").read_text())
    assert [(line["speaker"], line["voice"], line["text"], line["start"], line["dur"]) for line in kept["lines"]] == [
        ("anna", "af_bella", "Hi.", 0.0, 1.0), ("ben", "am_michael", "Hello.", 1.5, 1.0),
        ("anna", "af_bella", "Bye.", 3.0, 1.0)]
    assert [(scene["where"], scene["start"], scene["length"]) for scene in kept["scenes"]] == [
        ("A", 0.0, 2.5), ("B", 3.0, 1.0)]
    assert "timeline.json" in kind.ready_text(job)


def test_a_lines_quiet_after_its_last_word_is_cut_to_a_short_tail():
    """A voice leaves up to a second of quiet after a line; in a dialogue that would keep the caption up and the
    speaker 'talking' with a shut mouth. The pause after the line is the script's to give."""
    from odie.video import narrate
    wav = tone_then_quiet(1.0, 0.9)
    cut = narrate.tail_cut(wav)
    with wave.open(io.BytesIO(cut)) as w:
        assert round(w.getnframes() / w.getframerate(), 2) == 1.0 + narrate.MAX_TAIL
    short = tone_then_quiet(1.0, 0.05)
    assert narrate.tail_cut(short) == short  # already short: the same bytes


# The review's fixes: scripts as people (and LLMs) really write them, and limits said before anything is queued.

@pytest.mark.parametrize("written", ["- ANNA: Hi.", "* ANNA: Hi.", "1. ANNA: Hi.", "> ANNA: Hi.", "**ANNA:** Hi.",
                                     "**ANNA**: Hi.", "__ANNA__: Hi.", "ANNA (whispering): Hi."])
def test_markdown_bullets_bold_names_and_directions_still_read_as_lines(written):
    [line] = dialogue.parse(written).scenes[0].lines
    assert (line.speaker, line.text) == ("anna", "Hi.")


def test_a_name_may_start_with_any_letter():
    [line] = dialogue.parse("ÉLODIE: Salut.").scenes[0].lines
    assert line.speaker == "élodie"


@pytest.mark.parametrize("written, pause", [("ANNA: Hi. [pause]", None), ("ANNA: Hi. [pause 1.5s]", 1.5),
                                            ("ANNA: Hi. [Pause 2]", 2.0)])
def test_pause_marks_are_read_never_spoken(written, pause):
    [line] = dialogue.parse(written).scenes[0].lines
    assert line.text == "Hi." and line.pause == pause


def test_a_pause_over_ten_seconds_is_refused_naming_the_line():
    with pytest.raises(dialogue.ScriptProblem, match="at most 10"):
        dialogue.parse("ANNA: Wait. [pause 300]")


def test_a_bar_in_a_line_is_refused_since_it_marks_lines_for_the_writer():
    with pytest.raises(dialogue.ScriptProblem, match="Either this"):
        dialogue.parse("ANNA: Either this | or that.")


def test_a_script_too_big_for_a_video_is_said_in_its_own_words():
    many = "## Scene: One\n" + "\n".join(f"ANNA: Line {n}." for n in range(13))
    assert "13 lines" in dialogue.script_problem(dialogue.parse(many))
    long = "\n".join(f"## Scene: {n}\nANNA: " + "word " * 150 for n in range(7))
    assert "minutes" in dialogue.script_problem(dialogue.parse(long))
    assert dialogue.script_problem(dialogue.parse(SCRIPT)) is None


def test_a_pause_on_a_scenes_last_line_is_kept_when_the_script_gives_one():
    script = dialogue.parse("## Scene: A\nANNA: Hi. [pause 2]\n## Scene: B\nBEN: Yo.")
    assert script.scenes[0].lines[0].pause == 2.0
    assert dialogue.parse("ANNA: Hi.").scenes[0].lines[0].pause is None  # none given: the default between lines


def test_a_line_that_closes_a_script_tag_cant_break_the_page():
    assert "</script>" not in dialogue.lines_script([{"text": "Look </script> here"}]).removesuffix("</script>")


async def test_a_characters_voice_is_checked_again_when_spoken_and_the_narrator_takes_the_asked_voice(store,
                                                                                                      monkeypatch):
    from odie import voice
    from odie.video import narrate
    from tests.test_speak import kokoro
    spoken = []
    script = dialogue.parse("NARRATOR: Night fell.\nANNA: Hi.")
    await narrate.narrate_dialogue(store, script, {"anna": "af_bella"}, transport=kokoro(spoken, 0.5),
                                   narrator_voice="am_michael")
    assert {call["text"]: call["voice"] for call in spoken} == {"Night fell.": "am_michael", "Hi.": "af_bella"}
    monkeypatch.setattr(voice, "load_secret", lambda name: "sk-test")  # OpenAI's voices need a key to be chosen
    voice.set_tts(store, engine="openai", voice="shimmer")  # Settings changed after the video was asked for
    with pytest.raises(voice.VoiceUnavailable, match="af_bella"):
        await narrate.narrate_dialogue(store, script, {"anna": "af_bella"}, transport=kokoro([], 0.5))
