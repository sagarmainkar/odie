"""The audio story's making step (odie.making.story): every line spoken in its speaker's voice, laid out scene by
scene with the sound, mixed under the speech at the slider's level, mastered to about -16 LUFS, and saved as one
file in the story player. Nothing else is posted.

The voice is a MockTransport (a tone a line); the sounds are a fake library of tiny generated WAVs in tmp_path."""
import dataclasses
import io
import json
import logging
import math
import wave

import httpx
import pytest

from odie import media, voice
from odie.agent.tools.files import workspace
from odie.making import jobs, story
from odie.making import story_writer as writer
from odie.store.db import Store
from odie.video import encode
from tests.test_media import make_wav

# The timeline, as plain arithmetic.

def scene(title, lines, bed="ambience/surf", music=None, transition=None):
    music_sound = None
    if music:
        music_sound = writer.Sound(music, "normal")
    bed_sound = None
    if bed:
        bed_sound = writer.Sound(bed, "normal")
    return writer.Scene(title=title, bed=bed_sound, music=music_sound, lines=lines, transition=transition)


def say(speaker, pause=0.4, after=None):
    return writer.Speech(speaker=speaker, text="Hello there.", pause_after=pause, sound_after=after)


def two_scenes(transition):
    return [
        scene("Prelude", [writer.Cue("animals/gulls", "low", 3.0), say("narrator"), say("keeper", after="foley/door")],
              music="jingles/theme", transition=transition),
        scene("The storm", [say("keeper", pause=0.0)], bed="ambience/wind"),
    ]


def test_lines_are_laid_end_to_end_after_the_preludes_sound():
    laid = story.lay_out(two_scenes(writer.Transition("crossfade", 2.5)), [2.0, 1.5, 3.0])
    assert [(s.speaker, s.start, s.seconds) for s in laid.speech] == [
        ("narrator", 3.0, 2.0), ("keeper", 5.4, 1.5), ("keeper", 9.8, 3.0)]
    # the scene ends at 7.3 (after the keeper's pause); the crossfade takes 2.5 s; the next scene starts at 9.8
    hits = [(h.sound, h.start, h.level) for h in laid.sounds if h.role == "hit"]
    assert hits == [("animals/gulls", 0.0, "low"), ("foley/door", 6.9, "normal")]
    assert laid.length == pytest.approx(9.8 + 3.0 + story.STORY_TAIL)


def test_beds_fade_in_and_cross_into_the_next_scene():
    laid = story.lay_out(two_scenes(writer.Transition("crossfade", 2.5)), [2.0, 1.5, 3.0])
    beds = [(b.role, b.sound, b.start, round(b.seconds, 3), b.fade_in, b.fade_out) for b in laid.sounds
            if b.role != "hit"]
    assert beds == [
        ("bed", "ambience/surf", 0.0, 9.8, story.BED_FADE_IN, 2.5),
        ("music", "jingles/theme", 0.0, 9.8, story.BED_FADE_IN, 2.5),
        ("bed", "ambience/wind", 7.3, round(12.8 + story.STORY_TAIL - 7.3, 3), 2.5, story.STORY_TAIL),
    ]


def test_a_stinger_plays_at_the_scenes_end_and_a_silence_lets_the_beds_go():
    stung = story.lay_out(two_scenes(writer.Transition("stinger", 2.0, "stingers/hit")), [2.0, 1.5, 3.0])
    assert ("stingers/hit", 7.3, "normal") in [(h.sound, h.start, h.level) for h in stung.sounds if h.role == "hit"]
    assert stung.speech[2].start == pytest.approx(9.3)
    quiet = story.lay_out(two_scenes(writer.Transition("silence", 1.0)), [2.0, 1.5, 3.0])
    first_bed = quiet.sounds[0]
    assert (first_bed.start + first_bed.seconds, first_bed.fade_out) == (pytest.approx(8.3), 1.0)
    second_bed = next(b for b in quiet.sounds if b.sound == "ambience/wind")
    assert (second_bed.start, second_bed.fade_in) == (pytest.approx(8.3), story.BED_FADE_IN)


def test_at_most_one_bed_and_one_music_play_at_once_outside_a_crossfade():
    laid = story.lay_out(two_scenes(writer.Transition("silence", 1.0)), [2.0, 1.5, 3.0])
    for moment in (1.0, 5.0, 9.0, 11.0):
        playing = [b.role for b in laid.sounds if b.role != "hit" and b.start <= moment < b.start + b.seconds]
        assert playing.count("bed") <= 1 and playing.count("music") <= 1


def test_a_hit_on_a_words_start_moves_into_the_gap_before_it():
    assert story.hit_start(10.0, [10.1]) == pytest.approx(9.8)
    assert story.hit_start(10.2, [10.1]) == pytest.approx(9.8)
    assert story.hit_start(8.0, [10.1]) == 8.0
    assert story.hit_start(0.1, [0.2]) == 0.0  # never before the story starts
    cue_then_line = story.lay_out([scene("Prelude", [writer.Cue("animals/gulls", "low", 3.0),
                                                     writer.Cue("foley/door", "normal", 0.0), say("narrator")])],
                                  [2.0])
    door = next(h for h in cue_then_line.sounds if h.sound == "foley/door")
    assert door.start == pytest.approx(3.0 - story.HIT_ATTACK)


# Levels, all code.

def test_the_slider_maps_to_decibels_below_the_speech():
    assert [story.slider_db(p) for p in (10, 25, 40)] == [-20.0, -12.0, -8.0]
    assert story.slider_db(30) == pytest.approx(-12 + 4 * 5 / 15)
    assert story.slider_db(5) == -20.0 and story.slider_db(55) == -8.0  # held to 10–40


def test_beds_rise_between_lines_but_never_above_minus_four():
    assert story.rise_db(-12.0) == 6.0
    assert story.rise_db(-8.0) == 4.0
    assert story.bed_under_db("normal", -12.0) == -12.0
    assert story.bed_under_db("up front", -8.0) == -8.0  # -6 would rise to -2: held so the rise stops at -4
    assert story.bed_under_db("low", -12.0) == -15.0
    assert story.music_under_db("normal", -12.0) == -16.0


def test_the_envelope_ducks_under_speech_and_rises_in_long_gaps_only():
    rate = story.ENVELOPE_RATE
    env = story.envelope([(2.0, 3.0), (3.5, 4.5), (8.0, 9.0)], 10.0, 6.0)
    assert len(env) == 10 * rate
    down = 10 ** (-6 / 20)
    assert env[int(0.5 * rate)] == pytest.approx(1.0)  # the prelude, before anyone speaks: raised
    assert env[int(2.5 * rate)] == pytest.approx(down)  # under speech
    assert env[int(3.25 * rate)] == pytest.approx(down)  # a 0.5 s gap: stays down, no pumping
    assert env[int(6.25 * rate)] == pytest.approx(1.0)  # a 3.5 s gap: up
    ramp = [env[int(t * rate)] for t in (4.65, 4.85, 5.05, 5.25)]
    assert ramp == sorted(ramp) and down < ramp[1] < 1.0  # it rises smoothly, over DUCK_RAMP
    assert env[int(7.9 * rate)] == pytest.approx(down)  # down again before the next line's first word


def test_the_mix_graph_has_its_pieces():
    laid = story.lay_out(two_scenes(writer.Transition("crossfade", 2.5)), [2.0, 1.5, 3.0])
    sources = {s.sound: story.Source(path=f"/sounds/{s.sound}.wav", mean_db=-30.0, max_db=-6.0) for s in laid.sounds}
    loops = {sound: dataclasses.replace(source, path=f"/loops/{sound}.wav") for sound, source in sources.items()}
    plan = story.mix_plan(laid, sources, loops, speech_db=-20.0, sound_level=25, speech_peak_db=-3.0)
    graph = plan.graph
    assert graph.count("amultiply") == 3  # the three beds, each under the duck envelope
    assert "afade=t=in:d=1.5" in graph and "afade=t=in:d=2.5" in graph
    assert "adelay=7300:all=1" in graph  # the second bed comes in under the crossfade
    # a bed matched to the speech (-20 - -30 = +10), at 25 % (-12), raised by 6 between lines: +4 dB
    assert "volume=4.00dB" in graph
    assert "volume=0.00dB" in graph  # the music, 4 dB below
    # a hit at "low" peaks 10 dB under the speech's peak: -3 - 10 - -6 = -7
    assert "volume=-7.00dB" in graph
    # every bed's peaks are held 3 dB under the speech's: -3 - 3 = -6 dBFS (a campfire's crackle can't jump out)
    assert graph.count("alimiter=limit=0.5012") == 3
    assert graph.count("amix=") == 2  # the story, and the beds alone (for the measured gap)
    looped = [plan.inputs[i + 3] for i, arg in enumerate(plan.inputs) if arg == "-stream_loop"]
    assert looped == ["/loops/ambience/surf.wav", "/loops/jingles/theme.wav", "/loops/ambience/wind.wav"]  # the units
    assert "/sounds/foley/door.wav" in plan.inputs  # a hit plays from its own file


# Beds that loop without a hole at the seam.

def test_a_beds_steady_part_starts_after_its_fade_in_and_ends_before_its_fade_out():
    """iMovie's Ocean Surf fades in over its first 1.3 s and out over its last 0.9 s (100 ms levels against its
    usual level): the loop is cut from where it is steady."""
    levels = [-74, -63, -53, -42, -32, -24, -17, -13, -12, -12, -13, -12, -10, -8, -5, -4, -3, -1] + [0] * 80 \
        + [-1, -6, -9, -12, -13, -15, -16, -17, -20]
    head, tail = story.body_span([level - 22 for level in levels])
    assert head == pytest.approx(1.7)  # the first of five steady windows in a row, within 3 dB
    assert tail == pytest.approx(9.9)  # 1.0 s from the end of 10.7
    assert story.body_span([-20.0] * 50) == (0.0, pytest.approx(5.0))  # steady throughout: nothing to cut


def test_a_beds_trim_never_takes_more_than_a_quarter_of_either_end():
    levels = [-60.0] * 40 + [-20.0] * 20 + [-60.0] * 40  # mostly quiet: the median is the quiet
    assert story.body_span(levels) == (0.0, pytest.approx(10.0))
    fading = [-60.0] * 40 + [-20.0] * 60
    head, tail = story.body_span(fading)
    assert head == pytest.approx(2.5) and tail == pytest.approx(10.0)  # held at a quarter of 10 s


def noise_bed(path, seconds=8.0, fade_in=1.3, fade_out=0.9):
    """Pink noise with fades at both ends, as iMovie's ambiences have: a stand-in for surf or rain."""
    encode_cmd = [encode.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i",
                  f"anoisesrc=d={seconds}:c=pink:a=0.3:r=48000:s=7",
                  "-af", f"afade=t=in:d={fade_in},afade=t=out:st={seconds - fade_out}:d={fade_out}", str(path)]
    import subprocess
    subprocess.run(encode_cmd, check=True)
    return path


def smoothed(levels, n=5):
    """Levels averaged over n windows (in power), as the ear hears a dip of half a second."""
    powers = [10 ** (level / 10) for level in levels]
    return [10 * math.log10(sum(powers[i:i + n]) / n) for i in range(len(powers) - n + 1)]


async def test_a_bed_loops_without_a_dip_at_its_seam(tmp_path):
    import statistics
    import subprocess
    bed = noise_bed(tmp_path / "surf.wav")
    source = await story.measure_source(bed, 8.0)
    unit = await story.seamless_loop(source, tmp_path)
    assert unit.path != source.path and unit.channels == 2
    # the fades are straight lines in amplitude, within 3 dB of the usual level from 71 % of the way: about 1.0 s in
    # and 0.6 s before the end; the unit is that steady part less the crossfade
    assert unit.seconds == pytest.approx(8.0 - 1.0 - 0.6 - story.LOOP_CROSSFADE, abs=0.3)
    looped = tmp_path / "looped.wav"
    subprocess.run([encode.ffmpeg(), "-v", "error", "-y", "-stream_loop", "-1", "-i", unit.path,
                    "-t", str(unit.seconds * 3), str(looped)], check=True)
    levels = smoothed(await story.window_levels(looped))
    usual = statistics.median(levels)
    for seam in (unit.seconds, unit.seconds * 2):
        near = levels[int((seam - 1.0) / story.LEVEL_WINDOW): int((seam + 1.0) / story.LEVEL_WINDOW)]
        assert min(near) > usual - 2.0  # the file as it is dips more than 10 dB here


async def test_a_bed_too_short_to_crossfade_loops_as_it_is(tmp_path):
    bed = noise_bed(tmp_path / "short.wav", seconds=2.0, fade_in=0.1, fade_out=0.1)
    source = await story.measure_source(bed, 2.0)
    assert await story.seamless_loop(source, tmp_path) == source


def test_hits_are_set_against_the_speechs_peak():
    """A "low" owl sits well under the loudest word, "normal" a little under, "up front" about level with it, however
    hot or quiet the voice is."""
    owl = story.Source(path="/owl.wav", mean_db=-30.0, max_db=-6.0)
    assert story.hit_db("low", owl, speech_peak_db=-3.0) == pytest.approx(-7.0)  # its peak at -13: 10 under -3
    assert story.hit_db("normal", owl, speech_peak_db=-3.0) == pytest.approx(-1.0)  # at -7: 4 under
    assert story.hit_db("up front", owl, speech_peak_db=-3.0) == pytest.approx(3.0)  # at -3: level
    assert story.hit_db("up front", owl, speech_peak_db=-12.0) == pytest.approx(-6.0)  # a quiet voice: quieter hits


def test_the_master_is_one_gain_then_a_true_peak_limiter():
    master = story.master_filter(gain_db=4.2, ceiling_db=-2.0)
    assert master.startswith("volume=4.20dB,")  # one gain for the whole story: the gap stays as mixed
    assert "aresample=192000,alimiter=limit=0.7943" in master  # oversampled 4×, so it holds the true peak
    assert "level=false" in master  # never its own make-up gain
    assert master.endswith("aresample=48000")


def test_where_only_the_beds_play_fully_up():
    """The spans the gap is measured on in the finished file: no one speaks (with the ducking's ramps), no hit
    plays, the beds are past their fade-in and before their fade-out, and one scene's bed plays."""
    laid = story.Laid(
        speech=[story.Spoken("narrator", "Hello.", 6.0, 2.0), story.Spoken("keeper", "Hi.", 12.0, 1.0)],
        sounds=[story.Placed("bed", "ambience/surf", "normal", 0.0, 16.0, 1.5, 3.0),
                story.Placed("hit", "foley/door", "normal", 0.0)],
        length=16.0)
    spans = story.beds_alone_spans(laid, {"foley/door": 0.8})
    # up from 1.5 (the fade-in) to 6.0 - 0.55; then 8.0 + 0.55 to 12.0 - 0.55; after 13.55 the fade-out from 13.0
    assert spans == [(pytest.approx(1.5), pytest.approx(5.45)), (pytest.approx(8.55), pytest.approx(11.45))]


def test_the_speech_alone_is_the_speech_with_its_bed_less_the_bed():
    assert story.speech_alone_db(-18.0, -30.0) == pytest.approx(-18.28, abs=0.01)
    assert story.speech_alone_db(-18.0, -18.0) is None  # nothing but the bed: no speech to measure


# A whole story, rendered.

@pytest.fixture
def world(isolated_settings, tmp_path, monkeypatch):
    store = Store(tmp_path / "assistant.db")
    store.init_schema()
    monkeypatch.setitem(jobs.hooks, "store", store)
    library = tmp_path / "library"
    (library / "Ambience").mkdir(parents=True)
    (library / "Foley").mkdir()
    (library / "Ambience" / "surf.wav").write_bytes(make_wav(6.0, freq=220, loud=0.3))
    (library / "Foley" / "door.wav").write_bytes(make_wav(0.8, freq=660, loud=0.6))
    catalogue = [
        {"id": "ambience/surf", "name": "Surf", "category": "Ambience", "kind": "loop", "seconds": 6.0,
         "path": str(library / "Ambience" / "surf.wav"), "variants": []},
        {"id": "foley/door", "name": "Door", "category": "Foley", "kind": "hit", "seconds": 0.8,
         "path": str(library / "Foley" / "door.wav"), "variants": []},
    ]
    return store, catalogue


def voices(seen, seconds=1.0):
    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, content=make_wav(seconds, freq=330, loud=0.5))
    return httpx.MockTransport(handler)


CAST = [{"id": "narrator", "name": "Narrator", "voice": "af_heart"},
        {"id": "keeper", "name": "The keeper", "voice": "am_michael"}]


def short_story():
    return [scene("Prelude", [writer.Cue("foley/door", "normal", 2.0), say("narrator"), say("keeper", pause=2.0),
                              say("narrator")])]


def saves(monkeypatch):
    saved = []
    real = media.save

    def counting(*args, **kwargs):
        saved.append(args)
        return real(*args, **kwargs)

    monkeypatch.setattr(media, "save", counting)
    return saved


async def test_a_story_is_one_file_in_the_story_player(world, tmp_path, monkeypatch):
    store, catalogue = world
    saved = saves(monkeypatch)
    seen = []
    made = await story.render(store, "The Lighthouse", short_story(), CAST, "British", 25, catalogue, tmp_path / "job",
                              transport=voices(seen))
    assert len(saved) == 1  # one media.save, nothing else
    m = made.media
    assert m["kind"] == "podcast" and m["format"] == "story" and m["mime"] == "audio/mp4" and m["ext"] == "m4a"
    assert [b["voice"] for b in seen] == ["af_heart", "af_heart", "am_michael"]  # grouped by voice
    assert [(t["host"], t["start"]) for t in m["transcript"]] == [
        ("Narrator", 2.0), ("The keeper", 3.4), ("Narrator", 6.4)]
    assert m["hosts"] == [{"name": "Narrator", "voice": "Heart", "group": "female"},
                          {"name": "The keeper", "voice": "Michael", "group": "male"}]
    path, _meta = media.get(m["id"])
    info = await encode.probe(path)
    assert info["audio"] and info["seconds"] == pytest.approx(7.8 + story.STORY_TAIL, abs=0.15)
    assert m["duration"] == pytest.approx(7.8 + story.STORY_TAIL, abs=0.15)
    assert not list((tmp_path / "job").glob("*.wav"))  # the working files are gone


def roomy_story():
    """A story with time for its bed alone: a 6 s prelude sound, then lines with 4 s pauses."""
    return [scene("Prelude", [writer.Cue("foley/door", "normal", 6.0), say("narrator", pause=4.0),
                              say("keeper", pause=4.0), say("narrator")])]


@pytest.mark.parametrize("level", [10, 25, 40])
async def test_the_encoded_file_keeps_the_gap_the_slider_promises(world, tmp_path, level):
    """Measured on the finished .m4a: its loudness and true peak, and the speech above the bed."""
    store, catalogue = world
    made = await story.render(store, "Gap", roomy_story(), CAST, "British", level, catalogue, tmp_path / f"job{level}",
                              transport=voices([]))
    promised = -story.slider_db(level)
    assert made.gap_db == pytest.approx(promised, abs=2.0)
    assert made.gap_measured_on == "the encoded file"
    assert made.loudness_lufs == pytest.approx(story.TARGET_LUFS, abs=1.0)
    assert made.true_peak_db <= story.MOST_TRUE_PEAK


async def test_a_missing_sound_is_skipped_with_a_log_line(world, tmp_path, caplog):
    store, catalogue = world
    lines = [writer.Cue("foley/door", "normal", 2.0), say("narrator"), writer.Cue("foley/gone", "normal", 0.0),
             say("keeper")]
    catalogue = catalogue + [{"id": "foley/gone", "name": "Gone", "category": "Foley", "kind": "hit", "seconds": 1.0,
                              "path": str(tmp_path / "nowhere.wav"), "variants": []}]
    with caplog.at_level(logging.INFO, logger="odie.making.story"):
        made = await story.render(store, "Gone", [scene("Prelude", lines)], CAST, "British", 25, catalogue,
                                  tmp_path / "job", transport=voices([]))
    assert made.media["kind"] == "podcast"
    assert "foley/gone" in caplog.text and "left out" in caplog.text


async def test_a_voice_that_doesnt_answer_is_said_in_one_line(world, tmp_path):
    store, catalogue = world

    def handler(request):
        raise httpx.ConnectError("Connection refused")

    with pytest.raises(voice.VoiceUnavailable) as e:
        await story.render(store, "Down", short_story(), CAST, "British", 25, catalogue, tmp_path / "job",
                           transport=httpx.MockTransport(handler))
    assert str(e.value) == "Odie's voice didn't answer (Settings → Voice): Connection refused"


async def test_a_cast_voice_from_another_engine_is_said_by_name(world, tmp_path):
    store, catalogue = world
    cast = [{"id": "narrator", "name": "Narrator", "voice": "marin"}, CAST[1]]
    with pytest.raises(voice.VoiceUnavailable) as e:
        await story.render(store, "X", short_story(), cast, "British", 25, catalogue, tmp_path / "job",
                           transport=voices([]))
    assert str(e.value).startswith("Narrator's voice: 'marin' isn't one of")


def test_openai_voices_get_the_accent_as_a_style_line():
    assert story.accent_style("openai", "Indian") == (
        "Speak with a natural Indian English accent, as a storyteller in an audio drama: expressive, with the "
        "feeling each line carries.")
    assert story.accent_style("kokoro", "Indian") == ""  # Kokoro and Phonon voices carry their own accent


async def test_the_speech_track_puts_each_line_at_its_start_and_is_measured_where_it_speaks(tmp_path):
    line = make_wav(0.5)
    track = story.speech_track([line, line], [0.0, 1.0], 2.0)
    with wave.open(io.BytesIO(track)) as w:
        assert w.getnframes() == 48000  # 2 s at the voice's 24 kHz
    path = tmp_path / "speech.wav"
    path.write_bytes(track)
    spoken = await story.measure_db(path, [(0.0, 0.5), (1.0, 1.5)])
    assert spoken == pytest.approx(20 * math.log10(0.5 / math.sqrt(2)), abs=0.5)  # the quiet between is left out


# Through the queue.

async def test_the_job_writes_then_makes_and_posts_one_player(world, tmp_path, monkeypatch):
    _store, catalogue = world
    posts = []

    class Chat:
        async def post_message(self, text, session_id=None, media=None, kind="system"):
            posts.append((text, media))

    monkeypatch.setitem(jobs.hooks, "runner", Chat())
    monkeypatch.setattr(jobs, "send_to_all", lambda *a, **k: 1)

    async def no_library(libraries=None, cache_file=None):
        return catalogue

    monkeypatch.setattr(story.sound_library, "catalogue", no_library)
    script = {"title": "Rook Point", "scenes": [{"title": "Prelude", "bed": {"sound": "ambience/surf"}, "lines": [
        {"sound": "foley/door", "lead": 2},
        *[{"speaker": "narrator", "text": " ".join(["tide"] * 29) + "."} for _ in range(9)]]}]}

    async def submits(prompt, instruction, tools, timeout, follow_up=None, max_llm_calls=None):
        from types import SimpleNamespace

        from google.adk.events.event_actions import EventActions
        [submit] = tools
        await submit(json.dumps(script), tool_context=SimpleNamespace(actions=EventActions()))

    folder = workspace() / story.FOLDER / "rook-point"
    folder.mkdir(parents=True)
    request = writer.Request(genre="mystery", premise="A keeper hears a ship.", cast=CAST, narrator="narrator",
                             accent="British", minutes=2)
    job = jobs.Job(kind="story", slug="rook-point", title="A keeper hears a ship.", topic="A keeper hears a ship.",
                   minutes=2, session_id="chat-1", folder=folder, data={"request": request, "sound_level": 25})

    def kokoro_tone(request):
        return httpx.Response(200, content=make_wav(1.0, freq=330))

    await jobs.run(job, browser=object(), transport=httpx.MockTransport(kokoro_tone), turn=submits)
    [(text, posted)] = posts
    assert text == "The audio story about Rook Point is ready."
    assert len(posted) == 1 and posted[0]["format"] == "story"
    levels = json.loads((folder / "levels.json").read_text())
    assert levels["sound_level"] == 25 and levels["promised_gap_db"] == 12.0 and "measured_gap_db" in levels
    assert json.loads((folder / "script.json").read_text()) == script  # the accepted script, as videos keep theirs
    timeline = json.loads((folder / "timeline.json").read_text())
    assert timeline["length"] > 0 and len(timeline["speech"]) == 9
    assert timeline["speech"][0] == {"speaker": "narrator", "text": " ".join(["tide"] * 29) + ".", "start": 2.0,
                                     "seconds": pytest.approx(1.0, abs=0.05)}
    bed, door = timeline["sounds"]
    assert bed["role"] == "bed" and bed["sound"] == "ambience/surf" and "gain_db" in bed and "fade_in" in bed
    assert door["role"] == "hit" and door["sound"] == "foley/door" and door["start"] == 0.0
    assert set(timeline["levels"]) == {"speech_db", "speech_peak_db", "master_gain_db", "limit_ceiling_db"}
    assert json.loads((folder / "job.json").read_text())["status"] == "done"
