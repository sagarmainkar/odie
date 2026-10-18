"""The explainer video's sound set (odie.video.sounds): every named sound has its WAV in the kit (mono, 44.1 kHz,
16-bit), hits are short and loops 4-8 s and seamless, the folder stays small, and the writer's list names them all."""
import array
import logging
import math
import shutil
import wave

import pytest

from odie.video import sounds
from tests.test_media import make_wav

MAX_TOTAL_BYTES = 8_000_000
WINDOW = 2_000  # samples, about 45 ms


def read_samples(name: str) -> array.array:
    """The file's samples as 16-bit integers."""
    with wave.open(str(sounds.path(name)), "rb") as file:
        frames = file.readframes(file.getnframes())
    samples = array.array("h")
    samples.frombytes(frames)
    return samples


def rms(samples) -> float:
    """The root-mean-square level of the samples, in 16-bit units."""
    total = sum(sample * sample for sample in samples)
    return math.sqrt(total / len(samples))


# The index.

def test_the_set_holds_the_specs_names_hits_first_then_loops():
    hits = ["whoosh", "click", "tick", "ting", "bell", "chime", "thud", "drum", "riser", "stamp", "page", "key",
            "whistle", "applause-short"]
    loops = ["rain", "wind", "sea", "crowd", "footsteps", "heartbeat", "train", "engine", "typewriter", "applause",
             "night", "forest"]
    assert list(sounds.SOUNDS) == hits + loops
    assert [sounds.SOUNDS[name].kind for name in hits] == ["hit"] * len(hits)
    assert [sounds.SOUNDS[name].kind for name in loops] == ["loop"] * len(loops)
    for name, sound in sounds.SOUNDS.items():
        assert sound.name == name
        assert sound.words.strip() == sound.words and sound.words


def test_the_declared_lengths_keep_to_the_kinds_limits():
    for sound in sounds.SOUNDS.values():
        if sound.kind == "hit":
            assert 0 < sound.seconds <= 3.0, sound.name
        else:
            assert 4.0 <= sound.seconds <= 8.0, sound.name
    assert sounds.SOUNDS["riser"].seconds == 2.5
    assert sounds.SOUNDS["whistle"].seconds == 2.0
    assert sounds.SOUNDS["applause-short"].seconds == 1.5


def test_is_known_takes_exact_names_only():
    assert sounds.is_known("whoosh")
    assert sounds.is_known("applause-short")
    assert not sounds.is_known("Whoosh")
    assert not sounds.is_known("explosion")
    assert not sounds.is_known("")


def test_a_path_is_the_named_wav_in_the_kits_sounds_folder():
    where = sounds.path("whoosh")
    assert where.name == "whoosh.wav"
    assert where.parent.name == "sounds"
    assert where.parent.parent.name == "kit"


def test_the_listing_gives_one_line_per_sound_with_its_words_and_kind():
    lines = sounds.listing().splitlines()
    assert len(lines) == len(sounds.SOUNDS)
    for line, sound in zip(lines, sounds.SOUNDS.values()):
        assert line.startswith(f"{sound.name} — {sound.words} (")
    assert lines[0] == f"whoosh — {sounds.SOUNDS['whoosh'].words} (hit, 0.8 s)"
    assert sounds.describe(sounds.SOUNDS["riser"]).endswith("(hit, 2.5 s)")
    assert sounds.describe(sounds.SOUNDS["whistle"]).endswith("(hit, 2 s)")
    assert sounds.describe(sounds.SOUNDS["rain"]) == f"rain — {sounds.SOUNDS['rain'].words} (loop)"


# The files.

def test_every_named_sound_has_its_file_and_the_folder_holds_no_others():
    folder = sounds.path("whoosh").parent
    on_disk = sorted(file.stem for file in folder.glob("*.wav"))
    assert on_disk == sorted(sounds.SOUNDS)


@pytest.mark.parametrize("name", list(sounds.SOUNDS))
def test_each_file_is_mono_44k_16_bit_at_its_declared_length(name):
    with wave.open(str(sounds.path(name)), "rb") as file:
        assert file.getnchannels() == 1
        assert file.getframerate() == 44_100
        assert file.getsampwidth() == 2
        seconds = file.getnframes() / file.getframerate()
    assert seconds == pytest.approx(sounds.SOUNDS[name].seconds, abs=0.001)


@pytest.mark.parametrize("name", list(sounds.SOUNDS))
def test_each_file_peaks_near_minus_3_dbfs_and_never_clips(name):
    samples = read_samples(name)
    peak = max(abs(sample) for sample in samples) / 32767
    peak_db = 20 * math.log10(peak)
    assert -3.5 <= peak_db <= -2.5


def test_the_folder_stays_under_8_mb():
    folder = sounds.path("whoosh").parent
    total = sum(file.stat().st_size for file in folder.glob("*.wav"))
    assert total < MAX_TOTAL_BYTES


@pytest.mark.parametrize("name", [sound.name for sound in sounds.SOUNDS.values() if sound.kind == "loop"])
def test_a_loop_joins_its_end_to_its_start_without_a_jump(name):
    # Played twice, the loop's last 2,000 samples lead into its first 2,000. Their levels must differ no more than
    # any two neighbouring 2,000-sample windows inside the file do (no swell cut off into a lull), and the one-sample
    # step across the join must be no bigger than the biggest step among those 4,000 samples around it (no click).
    # Cut without its crossfade, the sea (in a quiet lull, all low rumble), the wind and the engine's hum each click
    # at the join and fail; with it, every loop passes.
    samples = read_samples(name)
    levels = [rms(samples[start:start + WINDOW]) for start in range(0, len(samples) - WINDOW + 1, WINDOW)]
    inner_jumps = [abs(after - before) for before, after in zip(levels, levels[1:])]
    seam_jump = abs(rms(samples[:WINDOW]) - rms(samples[-WINDOW:]))
    assert seam_jump <= max(inner_jumps)

    around = list(samples[-WINDOW:]) + list(samples[:WINDOW])
    steps_around = [abs(around[index + 1] - around[index]) for index in range(len(around) - 1) if index != WINDOW - 1]
    seam_step = abs(samples[0] - samples[-1])
    assert seam_step <= max(steps_around)


# ---- Cues: the writer's Video.sounds([...]) list, checked against the narration before the video is accepted ----

# Seven scenes. At 140 words a minute, 14 words are 6.0 s and 15 words 6.43 s; scene 3 is one phrase, scene 4 two.
SEVEN = ["word " * 14, "word " * 15, "word " * 14, "word " * 7 + "| " + "word " * 7, "word " * 14, "word " * 14,
         "word " * 14]


def test_good_cues_have_no_problem():
    cues = [
        {"scene": 2, "at": 0, "name": "footsteps", "seconds": 20, "gain": 0.4},  # a loop longer than its scene is cut
        {"scene": 4, "beat": 1, "name": "whoosh"},
        {"scene": 2, "at": 6.4, "name": "ting", "gain": 0.6},  # just inside the 6.43 s scene
        {"scene": 7, "beat": 0, "name": "applause-short"},
    ]
    assert sounds.cue_problem(cues, SEVEN) is None
    assert sounds.cue_problem([], SEVEN) is None


def test_an_unknown_name_is_told_with_the_names_of_the_set():
    cues = [{"scene": 1, "at": 0, "name": "rain"}, {"scene": 2, "at": 1, "name": "wooosh"}]
    problem = sounds.cue_problem(cues, SEVEN)
    names = ", ".join(sounds.SOUNDS)
    assert problem == f"Video.sounds: cue 2: there is no sound called 'wooosh'; the sounds are: {names}."
    assert "fast air sweep" not in problem  # the names, not the whole listing


def test_a_scene_the_video_doesnt_have_is_told_with_the_count():
    cues = [{"scene": 1, "at": 0, "name": "rain"}, {"scene": 9, "at": 1, "name": "ting"}]
    problem = sounds.cue_problem(cues, SEVEN)
    assert problem.startswith("Video.sounds: cue 2 names scene 9; this video has 7 scenes"), problem
    one = sounds.cue_problem([{"scene": 2, "at": 0, "name": "ting"}], ["word " * 14])
    assert "cue 1 names scene 2; this video has 1 scene" in one and "1 scenes" not in one


def test_a_beat_the_scene_doesnt_have_is_told_with_its_phrases():
    # Review Focus 1: scene 3 is one phrase, so only beat 0 is there
    problem = sounds.cue_problem([{"scene": 3, "beat": 1, "name": "whoosh"}], SEVEN)
    assert problem.startswith("Video.sounds: cue 1: scene 3 has 1 phrase (beats 0..0), so beat 1 isn't there"), problem
    two = sounds.cue_problem([{"scene": 4, "beat": 2, "name": "whoosh"}], SEVEN)
    assert "scene 4 has 2 phrases (beats 0..1), so beat 2 isn't there" in two


def test_at_beyond_the_scenes_estimated_length_is_told():
    cues = [{"scene": 1, "at": 0, "name": "rain"}, {"scene": 1, "at": 1, "name": "ting"},
            {"scene": 1, "at": 2, "name": "tick"}, {"scene": 2, "at": 8.5, "name": "ting"}]
    problem = sounds.cue_problem(cues, SEVEN)
    assert problem.startswith("Video.sounds: cue 4 is at 8.5 s but scene 2 is about 6.4 s long"), problem


def test_more_than_six_cues_in_a_scene_is_told_naming_the_scene():
    # Review Focus 4: seven in one scene
    cues = [{"scene": 2, "at": n * 0.5, "name": "tick"} for n in range(7)]
    problem = sounds.cue_problem(cues, SEVEN)
    assert problem.startswith("Video.sounds: scene 2 has 7 cues; at most 6"), problem
    assert sounds.cue_problem(cues[:6], SEVEN) is None


def test_more_than_forty_cues_in_all_is_told_with_the_limit():
    # Review Focus 4: forty-one cues, six or fewer in every scene
    cues = [{"scene": 1 + n % 7, "at": 0.1 * (n // 7), "name": "tick"} for n in range(41)]
    problem = sounds.cue_problem(cues, SEVEN)
    assert problem.startswith("Video.sounds: there are 41 cues; at most 40"), problem
    assert sounds.cue_problem(cues[:40], SEVEN) is None


def test_problems_come_in_order_name_scene_beat_at_then_the_counts():
    unknown = {"scene": 9, "at": 99, "name": "wooosh"}  # wrong in every way: the name is told first
    assert "no sound called 'wooosh'" in sounds.cue_problem([unknown], SEVEN)
    no_scene = {"scene": 9, "beat": 5, "name": "ting"}
    assert "names scene 9" in sounds.cue_problem([no_scene], SEVEN)
    crowded = [{"scene": 2, "at": 0, "name": "tick"}] * 7 + [{"scene": 3, "at": 50, "name": "tick"}]
    assert "is at 50 s" in sounds.cue_problem(crowded, SEVEN)  # a cue's own problem before the counts


def test_a_cue_of_the_wrong_shape_is_told_too():
    # the kit refuses these in the page; Odie checks the shape again, as the list comes back from the page
    told = {
        "not a dict": sounds.cue_problem(["whoosh"], SEVEN),
        "no at or beat": sounds.cue_problem([{"scene": 1, "name": "ting"}], SEVEN),
        "both": sounds.cue_problem([{"scene": 1, "at": 0, "beat": 0, "name": "ting"}], SEVEN),
        "scene 0": sounds.cue_problem([{"scene": 0, "at": 0, "name": "ting"}], SEVEN),
        "beat 1.5": sounds.cue_problem([{"scene": 1, "beat": 1.5, "name": "ting"}], SEVEN),
        "gain 2": sounds.cue_problem([{"scene": 1, "at": 0, "name": "ting", "gain": 2}], SEVEN),
        "seconds 0": sounds.cue_problem([{"scene": 1, "at": 0, "name": "rain", "seconds": 0}], SEVEN),
        "name 5": sounds.cue_problem([{"scene": 1, "at": 0, "name": 5}], SEVEN),
        "a true scene": sounds.cue_problem([{"scene": True, "at": 0, "name": "ting"}], SEVEN),
        "volume": sounds.cue_problem([{"scene": 1, "at": 0, "name": "ting", "volume": 0.5}], SEVEN),
    }
    for case, problem in told.items():
        assert problem is not None and problem.startswith("Video.sounds: cue 1 "), (case, problem)
    assert "neither at nor beat" in told["no at or beat"] and "both at and beat" in told["both"]
    assert "gain" in told["gain 2"] and "volume" in told["volume"]


def test_good_cues_keep_the_ones_that_pass_in_order():
    rain = {"scene": 1, "at": 0, "name": "rain"}
    cues = [rain, {"scene": 1, "at": 1, "name": "wooosh"}, {"scene": 9, "at": 0, "name": "ting"},
            {"scene": 3, "beat": 1, "name": "whoosh"}, {"scene": 2, "at": 8.5, "name": "ting"}, "whoosh",
            {"scene": 4, "beat": 1, "name": "whoosh"}]
    assert sounds.good_cues(cues, SEVEN) == [rain, {"scene": 4, "beat": 1, "name": "whoosh"}]
    assert sounds.good_cues([], SEVEN) == []


def test_good_cues_keep_the_first_six_of_a_scene_and_the_first_forty_in_all():
    crowded = [{"scene": 2, "at": n * 0.5, "name": "tick"} for n in range(8)]
    assert sounds.good_cues(crowded, SEVEN) == crowded[:6]
    many = [{"scene": 1 + n % 7, "at": 0.1 * (n // 7), "name": "tick"} for n in range(42)]
    assert sounds.good_cues(many, SEVEN) == many[:40]
    assert sounds.cue_problem(sounds.good_cues(crowded + many, SEVEN), SEVEN) is None


# ---- The mix: cues resolved to seconds, then mixed under the narration with ffmpeg ----

# Three scenes: 6 s, 6 s and 4 s long with a 0.5 s breath between; scene 1 has three phrases, scene 3 two.
TIMINGS = {"starts": [0.0, 6.5, 13.0], "lengths": [6.0, 6.0, 4.0], "beats": [[0.0, 2.0, 4.1], [0.0], [0.0, 1.5]]}


def summary(placed: sounds.Placed) -> tuple:
    return placed.name, placed.kind, placed.start, placed.seconds, placed.gain


def test_resolve_turns_scenes_and_beats_into_seconds_from_the_start():
    table = [
        # cue -> (name, kind, start, seconds, gain)
        ({"scene": 1, "at": 0, "name": "rain"}, ("rain", "loop", 0.0, 6.5, 0.35)),  # no seconds: to scene 2's start
        ({"scene": 1, "at": 3, "name": "wind"}, ("wind", "loop", 3.0, 3.5, 0.35)),  # through the breath too
        ({"scene": 1, "beat": 2, "name": "whoosh"}, ("whoosh", "hit", 4.1, 0.8, 0.6)),
        ({"scene": 2, "beat": 0, "name": "bell", "seconds": 1, "gain": 0.9}, ("bell", "hit", 6.5, 2.5, 0.9)),
        ({"scene": 3, "beat": 1, "name": "sea", "seconds": 2, "gain": 0.5}, ("sea", "loop", 14.5, 2.0, 0.5)),
        ({"scene": 3, "at": 1.5, "name": "heartbeat", "seconds": 1.25}, ("heartbeat", "loop", 14.5, 1.25, 0.35)),
    ]
    cues = [cue for cue, _ in table]
    placed = sounds.resolve(cues, TIMINGS)
    assert [summary(one) for one in placed] == [want for _, want in table]
    assert placed[0].path == sounds.path("rain") and placed[0].frames == 4 * 44100


def test_a_loop_longer_than_its_scene_is_cut_at_the_scenes_end():  # Review Focus 2
    [placed] = sounds.resolve([{"scene": 1, "at": 0, "name": "footsteps", "seconds": 20}], TIMINGS)
    assert (placed.start, placed.seconds) == (0.0, 6.5)  # scene 1's 6 s and the breath, to scene 2's start


def test_a_loop_without_seconds_fills_its_scene_to_the_next_ones_start():
    [placed] = sounds.resolve([{"scene": 2, "at": 1, "name": "crowd"}], TIMINGS)
    assert (placed.start, placed.seconds) == (7.5, 5.5)  # scene 3 starts at 13.0


def test_a_loop_in_the_last_scene_stops_at_the_narrations_end():
    cues = [{"scene": 3, "at": 0, "name": "sea", "seconds": 20}, {"scene": 3, "beat": 1, "name": "rain"}]
    placed = sounds.resolve(cues, TIMINGS)
    assert [(one.start, one.seconds) for one in placed] == [(13.0, 4.0), (14.5, 2.5)]  # the narration ends at 17.0


def test_the_credits_card_stays_silent():
    with_credits = {"starts": [*TIMINGS["starts"], 17.5], "lengths": [*TIMINGS["lengths"], 3.0],
                    "beats": [*TIMINGS["beats"], [0.0]]}
    cues = [{"scene": 3, "at": 0, "name": "sea", "seconds": 20}, {"scene": 3, "beat": 1, "name": "rain"},
            {"scene": 4, "at": 0, "name": "ting"}]
    placed = sounds.resolve(cues, with_credits, narrated_scenes=3)
    assert [(one.name, one.start, one.seconds) for one in placed] == [("sea", 13.0, 4.0), ("rain", 14.5, 2.5)]


def test_a_hit_is_still_cut_at_its_scenes_spoken_end():
    [placed] = sounds.resolve([{"scene": 1, "at": 5.5, "name": "bell"}], TIMINGS)
    assert (placed.start, placed.seconds) == (5.5, 0.5)  # not through the breath


def test_a_hit_near_its_scenes_end_plays_and_is_cut_there():  # Review Focus 3
    [placed] = sounds.resolve([{"scene": 2, "at": 5.9, "name": "ting"}], TIMINGS)
    assert (placed.start, placed.seconds) == (12.4, 0.1)


def test_cues_that_no_longer_fit_are_left_out_with_a_log_line(caplog):
    cues = [
        {"scene": 1, "at": 0, "name": "wooosh"},       # no such sound
        {"scene": 4, "at": 0, "name": "ting"},         # no such scene
        {"scene": 3, "beat": 2, "name": "ting"},       # scene 3 has beats 0 and 1
        {"scene": 1, "at": 6.5, "name": "ting"},       # past the scene's real end
        {"scene": 1, "at": 6, "name": "ting"},         # a hit at the very end: nothing left to play
        {"scene": 1, "at": 6.5, "name": "rain"},       # a loop at the next scene's start: nothing left either
        {"scene": 2, "at": 0, "name": "ting", "gain": 0},  # silent
    ]
    with caplog.at_level(logging.INFO, logger="odie.video"):
        assert sounds.resolve(cues, TIMINGS) == []
    lines = [record.getMessage() for record in caplog.records]
    assert len(lines) == len(cues)
    assert "wooosh" in lines[0] and "scene 4" in lines[1] and "beat 2" in lines[2]


def test_a_sound_whose_file_is_missing_or_broken_is_left_out(tmp_path, monkeypatch, caplog):
    shutil.copy(sounds.path("rain"), tmp_path / "rain.wav")
    (tmp_path / "ting.wav").write_bytes(b"not a wav")
    monkeypatch.setattr(sounds, "FOLDER", tmp_path)
    cues = [{"scene": 1, "at": 0, "name": "whoosh"}, {"scene": 1, "at": 0, "name": "rain"},
            {"scene": 1, "at": 1, "name": "ting"}]
    with caplog.at_level(logging.INFO, logger="odie.video"):
        placed = sounds.resolve(cues, TIMINGS)
    assert [one.name for one in placed] == ["rain"]
    lines = [record.getMessage() for record in caplog.records]
    assert len(lines) == 2 and "whoosh" in lines[0] and "ting" in lines[1]


def test_no_cues_place_nothing():
    assert sounds.resolve([], TIMINGS) == []


def test_a_files_loudness_is_its_rms_in_dbfs():
    # Loops over the whole file; hits over their loudest 100 ms (their attack, not their silent tail).
    assert round(sounds.wav_rms_dbfs(sounds.path("rain")), 1) == -14.3
    assert round(sounds.wav_rms_dbfs(sounds.path("footsteps")), 1) == -26.1
    assert round(sounds.wav_rms_dbfs(sounds.path("ting"), sounds.HIT_WINDOW_SECONDS), 1) == -9.9
    assert round(sounds.wav_rms_dbfs(sounds.path("ting")), 1) == -17.4  # the whole ting, tail and all


def test_a_silent_file_measures_at_the_floor(tmp_path):
    silent = tmp_path / "silent.wav"
    write_silence(silent, seconds=0.5)
    assert sounds.wav_rms_dbfs(silent) == sounds.SILENT_DBFS
    assert sounds.wav_rms_dbfs(silent, sounds.HIT_WINDOW_SECONDS) == sounds.SILENT_DBFS


def test_levels_bring_each_file_to_its_kinds_loudness_then_follow_the_gain():
    def placed(name, kind, gain):
        return sounds.Placed(start=0.0, path=sounds.path(name), seconds=1.0, gain=gain, kind=kind, name=name,
                             frames=176400)

    footsteps = sounds.level_db(placed("footsteps", "loop", 1.0))
    rain = sounds.level_db(placed("rain", "loop", 1.0))
    assert round(footsteps, 1) == -3.9  # -30 - (-26.1): the quiet file is raised
    assert round(rain, 1) == -15.7  # -30 - (-14.3): the loud one lowered
    assert round(sounds.level_db(placed("rain", "loop", 0.35)) - rain, 2) == -9.12  # the gain, 20·log10(0.35)
    assert round(sounds.level_db(placed("ting", "hit", 1.0)), 1) == -12.1  # -22 - (-9.9), its loudest 100 ms
    assert round(sounds.level_db(placed("whoosh", "hit", 0.6)), 1) == -12.8  # -22 - (-13.6) - 4.44


def write_silence(path, seconds=4.0, rate=24000, channels=1):
    frames = int(seconds * rate)
    with wave.open(str(path), "wb") as file:
        file.setnchannels(channels)
        file.setsampwidth(2)
        file.setframerate(rate)
        file.writeframes(b"\x00\x00" * frames * channels)


def read_wav(path) -> tuple[tuple, array.array]:
    """(channels, width, rate, frames) and the samples."""
    with wave.open(str(path), "rb") as file:
        shape = (file.getnchannels(), file.getsampwidth(), file.getframerate(), file.getnframes())
        frames = file.readframes(file.getnframes())
    samples = array.array("h")
    samples.frombytes(frames)
    return shape, samples


def window_rms(samples, rate, start, end) -> float:
    return rms(samples[int(start * rate):int(end * rate)])


# A 4 s narration: a hit (whoosh, 0.8 s) at 1 s and a loop (rain) from 2 s for 2 s.
ONE_SCENE = {"starts": [0.0], "lengths": [4.0], "beats": [[0.0]]}
HIT_AND_LOOP = [{"scene": 1, "at": 1, "name": "whoosh"}, {"scene": 1, "at": 2, "name": "rain", "seconds": 2}]


def test_the_mix_command_is_one_ffmpeg_graph(tmp_path):
    narration = tmp_path / "narration.wav"
    write_silence(narration)
    placed = sounds.resolve(HIT_AND_LOOP, ONE_SCENE)
    voice = sounds.wav_format(narration)
    assert voice == sounds.WavFormat(channels=1, width=2, rate=24000, frames=96000)
    command = sounds.mix_command(narration, placed, voice, tmp_path / "mix.wav")
    graph = command[command.index("-filter_complex") + 1]
    assert graph == (
        "[1:a]atrim=duration=0.8,aformat=sample_rates=24000:channel_layouts=1c,adelay=1000:all=1,volume=-12.82dB[a1];"
        "[2:a]aloop=loop=-1:size=176400,atrim=duration=2.0,afade=t=in:d=0.05,afade=t=out:st=1.7:d=0.3,"
        "aformat=sample_rates=24000:channel_layouts=1c,adelay=2000:all=1,volume=-24.86dB[a2];"
        "[0:a][a1][a2]amix=inputs=3:normalize=0:duration=first,alimiter=limit=0.891:level=0:latency=1[out]")
    inputs = [command[i + 1] for i, word in enumerate(command) if word == "-i"]
    assert inputs == [str(narration), str(sounds.path("whoosh")), str(sounds.path("rain"))]
    assert command[-1] == str(tmp_path / "mix.wav")
    assert sounds.mix_command(narration, placed, voice, tmp_path / "mix.wav") == command


def test_fades_go_on_every_loop_and_on_a_hit_only_when_it_is_cut():
    def placed(kind, seconds, cut=False):
        return sounds.Placed(start=0.0, path=sounds.path("ting"), seconds=seconds, gain=1.0, kind=kind, name="ting",
                             frames=66150, cut=cut)

    assert sounds.fade_filters(placed("loop", 6.5)) == "afade=t=in:d=0.05,afade=t=out:st=6.2:d=0.3,"
    assert sounds.fade_filters(placed("loop", 0.4)) == "afade=t=in:d=0.05,afade=t=out:st=0.3:d=0.1,"  # a quarter
    assert sounds.fade_filters(placed("hit", 0.5, cut=True)) == "afade=t=out:st=0.375:d=0.125,"
    assert sounds.fade_filters(placed("hit", 1.5)) == ""  # a hit that plays whole ends as it was made


def test_a_hit_cut_at_its_scenes_end_is_marked_cut_and_a_whole_one_isnt():
    ting_near_the_end, whoosh = sounds.resolve([{"scene": 1, "at": 3.5, "name": "ting"},
                                                {"scene": 1, "at": 1, "name": "whoosh"}], ONE_SCENE)
    assert (ting_near_the_end.seconds, ting_near_the_end.cut) == (0.5, True)
    assert (whoosh.seconds, whoosh.cut) == (0.8, False)


async def test_a_cut_loop_and_a_cut_hit_fade_out_instead_of_stopping_dead(tmp_path):
    narration = tmp_path / "narration.wav"
    write_silence(narration)
    out = tmp_path / "mix.wav"
    cues = [{"scene": 1, "at": 1, "name": "rain", "gain": 1}]  # rain to the narration's end at 4.0 s
    await sounds.mix(narration, sounds.resolve(cues, ONE_SCENE), out)
    _shape, samples = read_wav(out)
    assert window_rms(samples, 24000, 3.95, 4.0) < 0.2 * window_rms(samples, 24000, 3.65, 3.7)

    cues = [{"scene": 1, "at": 2.5, "name": "bell", "gain": 1}]  # a 2.5 s bell cut to 1.5 s at the scene's end
    await sounds.mix(narration, sounds.resolve(cues, ONE_SCENE), out)
    _shape, samples = read_wav(out)
    assert window_rms(samples, 24000, 3.95, 4.0) < 0.2 * window_rms(samples, 24000, 3.65, 3.7)


async def test_a_hit_that_plays_whole_is_mixed_as_its_file_is(tmp_path):
    narration = tmp_path / "narration.wav"
    write_silence(narration, rate=44100)  # the files' own rate, so nothing is resampled
    out = tmp_path / "mix.wav"
    [whoosh] = sounds.resolve([{"scene": 1, "at": 1, "name": "whoosh"}], ONE_SCENE)
    await sounds.mix(narration, [whoosh], out)
    _shape, mixed = read_wav(out)
    file = read_samples("whoosh")
    factor = 10 ** (round(sounds.level_db(whoosh), 2) / 20)
    start = 44100
    for i in range(len(file) - 2205, len(file)):  # its last 50 ms, where a fade would show
        assert abs(mixed[start + i] - file[i] * factor) <= 2, i


async def test_footsteps_and_rain_come_out_equally_loud_at_the_same_gain(tmp_path):
    narration = tmp_path / "narration.wav"
    write_silence(narration, seconds=6.0, rate=44100)
    timings = {"starts": [0.0], "lengths": [6.0], "beats": [[0.0]]}
    loudness = {}
    for name in ("footsteps", "rain"):
        out = tmp_path / f"{name}.wav"
        await sounds.mix(narration, sounds.resolve([{"scene": 1, "at": 0, "name": name}], timings), out)
        _shape, samples = read_wav(out)
        loudness[name] = 20 * math.log10(window_rms(samples, 44100, 0.5, 4.5) / 32768)  # one whole 4 s loop
    assert abs(loudness["footsteps"] - loudness["rain"]) < 2, loudness


async def test_the_mix_lays_the_sounds_where_the_cues_put_them(tmp_path):
    narration = tmp_path / "narration.wav"
    write_silence(narration)
    out = tmp_path / "mix.wav"
    await sounds.mix(narration, sounds.resolve(HIT_AND_LOOP, ONE_SCENE), out)
    shape, samples = read_wav(out)
    assert shape == (1, 2, 24000, 96000)  # the narration's format and its exact length
    assert window_rms(samples, 24000, 0.0, 1.0) < 2  # near silence before the hit
    assert window_rms(samples, 24000, 1.0, 1.3) > 300  # the hit
    assert window_rms(samples, 24000, 1.85, 2.0) < 2  # the hit is over and the loop not yet begun
    for start in (2.0, 2.5, 3.0, 3.5):  # the loop is there to the end
        assert window_rms(samples, 24000, start, start + 0.5) > 50


async def test_the_same_cues_and_narration_give_the_same_mix(tmp_path):
    narration = tmp_path / "narration.wav"
    write_silence(narration)
    placed = sounds.resolve(HIT_AND_LOOP, ONE_SCENE)
    await sounds.mix(narration, placed, tmp_path / "one.wav")
    await sounds.mix(narration, placed, tmp_path / "two.wav")
    assert (tmp_path / "one.wav").read_bytes() == (tmp_path / "two.wav").read_bytes()


async def test_the_narration_is_untouched_where_no_sound_plays(tmp_path):
    narration = tmp_path / "narration.wav"
    narration.write_bytes(make_wav(4.0, rate=24000, loud=0.5))
    out = tmp_path / "mix.wav"
    await sounds.mix(narration, sounds.resolve([{"scene": 1, "at": 3, "name": "whoosh"}], ONE_SCENE), out)
    _shape, mixed = read_wav(out)
    _shape, voice = read_wav(narration)
    before_the_hit = 3 * 24000 - 200  # the limiter looks 5 ms ahead
    assert mixed[:before_the_hit] == voice[:before_the_hit]


async def test_a_loud_mix_is_held_under_the_limit(tmp_path):
    narration = tmp_path / "narration.wav"
    narration.write_bytes(make_wav(3.0, rate=24000, loud=0.88))
    out = tmp_path / "mix.wav"
    cues = [{"scene": 1, "at": 0.5, "name": "drum", "gain": 1}, {"scene": 1, "at": 0, "name": "rain", "gain": 1,
                                                                   "seconds": 3}]
    await sounds.mix(narration, sounds.resolve(cues, {"starts": [0.0], "lengths": [3.0], "beats": [[0.0]]}), out)
    _shape, samples = read_wav(out)
    assert max(abs(sample) for sample in samples) <= 0.891 * 32768 + 2


async def test_a_stereo_narration_keeps_its_format(tmp_path):
    narration = tmp_path / "narration.wav"
    write_silence(narration, seconds=2.0, rate=22050, channels=2)
    out = tmp_path / "mix.wav"
    await sounds.mix(narration, sounds.resolve([{"scene": 1, "at": 0.5, "name": "ting"}], ONE_SCENE), out)
    shape, samples = read_wav(out)
    assert shape == (2, 2, 22050, 44100)
    assert rms(samples) > 50


async def test_a_file_gone_by_mix_time_is_left_out(tmp_path, caplog):
    narration = tmp_path / "narration.wav"
    write_silence(narration)
    placed = sounds.resolve(HIT_AND_LOOP, ONE_SCENE)
    gone = sounds.Placed(start=0.5, path=tmp_path / "gone.wav", seconds=0.5, gain=0.6, kind="hit", name="gone",
                         frames=22050)
    out = tmp_path / "mix.wav"
    with caplog.at_level(logging.INFO, logger="odie.video"):
        await sounds.mix(narration, [gone, *placed], out)
    shape, samples = read_wav(out)
    assert shape == (1, 2, 24000, 96000) and window_rms(samples, 24000, 1.0, 1.3) > 300
    assert any("gone" in record.getMessage() for record in caplog.records)


async def test_a_mix_with_every_file_gone_is_the_narration(tmp_path):
    narration = tmp_path / "narration.wav"
    narration.write_bytes(make_wav(1.0))
    gone = sounds.Placed(start=0.5, path=tmp_path / "gone.wav", seconds=0.5, gain=0.6, kind="hit", name="gone",
                         frames=22050)
    out = tmp_path / "mix.wav"
    await sounds.mix(narration, [gone], out)
    assert out.read_bytes() == narration.read_bytes()
