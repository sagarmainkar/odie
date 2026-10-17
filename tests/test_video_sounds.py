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
