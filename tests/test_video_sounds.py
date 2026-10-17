"""The explainer video's sound set (odie.video.sounds): every named sound has its WAV in the kit (mono, 44.1 kHz,
16-bit), hits are short and loops 4-8 s and seamless, the folder stays small, and the writer's list names them all."""
import array
import math
import wave

import pytest

from odie.video import sounds

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
