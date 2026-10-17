"""Builds the explainer video's sound set, odie/video/kit/sounds/*.wav, by synthesis: no recordings, so no licence
to carry, and the same files on every run (each sound draws its noise from its own fixed seed).

Run it from the repository root: uv run python scripts/sounds/build_sounds.py [name ...]
With no names it writes every sound in odie.video.sounds.SOUNDS; with names, only those (so a sound replaced by a
recording is left alone). It prints each file's length and size, and the folder's total.

Each sound is one function returning samples in -1..1 at 44.1 kHz; write() scales it so its loudest sample is at
-3 dBFS and stores it as mono 16-bit WAV. The aim is clean and simple, not realistic: filtered noise for air, rain,
steam and hands; sines that die away for anything struck; short noise bursts in a rhythm for feet and keys.

A loop is made 0.3 s longer than its file, and seamless() fades that extra tail out over the file's first 0.3 s
while the start fades in, so the file's last sample leads into its first as if the sound went on. A rhythm in a loop
(feet, heartbeats, chirps) repeats a whole number of times in it, and slow wobbles in level fit it a whole number of
times too, so the second time round sounds like the first."""
import argparse
import array
import math
import random
import sys
import wave

from odie.video import sounds

RATE = 44_100
PEAK = 10 ** (-3 / 20)  # -3 dBFS: the loudest sample of every file
CROSSFADE = 0.3  # seconds of a loop's extra tail faded into its start


# Building blocks: signals are plain lists of floats, one per sample.

def count(seconds: float) -> int:
    """How many samples last `seconds`: 0.5 -> 22050."""
    return round(seconds * RATE)


def noise(length: int, seed: int) -> list[float]:
    """White noise, `length` samples in -1..1, the same on every run for the same seed: noise(3, seed=1) twice ->
    the same three numbers both times."""
    rng = random.Random(seed)
    return [rng.uniform(-1.0, 1.0) for _ in range(length)]


def silence(length: int) -> list[float]:
    """`length` samples of nothing to mix sounds into: silence(3) -> [0.0, 0.0, 0.0]."""
    return [0.0] * length


def lowpass(samples: list[float], cutoff: float) -> list[float]:
    """A gentle one-pole low-pass: what lies above `cutoff` Hz fades at 6 dB an octave. lowpass(noise, 300) -> white
    noise dulled to a rumble; a steady 50 Hz hum through it comes out almost unchanged."""
    smoothing = 1 - math.exp(-2 * math.pi * cutoff / RATE)
    out = []
    level = 0.0
    for sample in samples:
        level += smoothing * (sample - level)
        out.append(level)
    return out


def highpass(samples: list[float], cutoff: float) -> list[float]:
    """What lowpass() takes away: the part above `cutoff` Hz. highpass(noise, 3000) -> white noise thinned to a
    hiss; a 50 Hz hum through it nearly vanishes."""
    under = lowpass(samples, cutoff)
    return [sample - low for sample, low in zip(samples, under)]


def band(samples: list[float], low: float, high: float) -> list[float]:
    """The part between `low` and `high` Hz: band(noise, 250, 2200) -> the breathy middle of a steam chuff."""
    below_high = lowpass(samples, high)
    return highpass(below_high, low)


def resonant(samples: list[float], centres: list[float], damping: float) -> tuple[list[float], list[float]]:
    """A state-variable filter whose centre may move, one centre in Hz per sample; returns its (low-pass, band-pass)
    outputs. A small damping (0.3) rings around the centre like air in a pipe; 1.0 or more is broad and smooth.
    Noise with centres rising from 300 Hz to 2.5 kHz through the band-pass -> a whoosh."""
    low = 0.0
    middle = 0.0
    lows = []
    middles = []
    for sample, centre in zip(samples, centres):
        tune = 2 * math.sin(math.pi * centre / RATE)
        low += tune * middle
        high = sample - low - damping * middle
        middle += tune * high
        lows.append(low)
        middles.append(middle)
    return lows, middles


def sine(frequencies: list[float]) -> list[float]:
    """A sine whose pitch follows `frequencies`, one value in Hz per sample: [440] * 44100 -> one second of A4;
    pitch_drop(150, 70, ...) -> a drum's falling note."""
    out = []
    phase = 0.0
    for frequency in frequencies:
        out.append(math.sin(phase))
        phase += 2 * math.pi * frequency / RATE
    return out


def tone(frequency: float, length: int) -> list[float]:
    """A steady sine at `frequency` Hz: tone(50, count(4.0)) -> 4 s of hum, exactly 200 cycles."""
    return sine([frequency] * length)


def pitch_drop(start: float, end: float, length: int, fall: float) -> list[float]:
    """Frequencies falling from `start` towards `end` Hz, two thirds of the way within `fall` seconds:
    pitch_drop(150, 70, n, fall=0.04) -> 150 Hz at the start, about 99 Hz after 40 ms, near 70 Hz by 0.2 s."""
    return [end + (start - end) * math.exp(-index / (fall * RATE)) for index in range(length)]


def pitch_rise(start: float, end: float, length: int) -> list[float]:
    """Frequencies rising evenly in pitch (the same number of octaves each second) from `start` to `end` Hz:
    pitch_rise(220, 880, n) -> 220 Hz at the start, 440 Hz halfway, nearly 880 Hz at the end."""
    return [start * (end / start) ** (index / length) for index in range(length)]


def decay(length: int, fall: float) -> list[float]:
    """An envelope that rises in 1 ms (so the start doesn't click) and then dies away, falling to 37 % every `fall`
    seconds: a struck or plucked thing. decay(n, 0.1) -> 1.0 at 1 ms, 0.37 at 0.1 s, 0.14 at 0.2 s."""
    rise = count(0.001)
    out = []
    for index in range(length):
        level = math.exp(-index / (fall * RATE))
        if index < rise:
            level *= index / rise
        out.append(level)
    return out


def swell(length: int, peak: float) -> list[float]:
    """An envelope that rises smoothly from 0 to 1 at fraction `peak` of its length and falls smoothly back to 0:
    swell(n, peak=0.25) on 1 s -> 0 at the start, 1 at 0.25 s, 0.5 at about 0.6 s, 0 at the end."""
    top = max(1, round(length * peak))
    out = []
    for index in range(length):
        if index < top:
            level = math.sin(math.pi / 2 * index / top) ** 2
        else:
            level = math.cos(math.pi / 2 * (index - top) / (length - top)) ** 2
        out.append(level)
    return out


def attack_release(length: int, attack: float, release: float) -> list[float]:
    """An envelope that rises smoothly over `attack` seconds, holds at 1 and falls smoothly over the last `release`:
    on 2 s with attack 0.25 and release 0.35 -> 0 at the start, 1 from 0.25 s to 1.65 s, 0 at the end."""
    rise = count(attack)
    fall = count(release)
    out = []
    for index in range(length):
        level = 1.0
        if index < rise:
            level = math.sin(math.pi / 2 * index / rise) ** 2
        left = length - index
        if left < fall:
            level *= math.sin(math.pi / 2 * left / fall) ** 2
        out.append(level)
    return out


def wobble(length: int, waves: list[tuple[float, float, float]]) -> list[float]:
    """A slow level change around 1: 1 plus a sine for each (hertz, depth, phase) wave. In a loop, each wave's hertz
    times the loop's seconds is a whole number, so the wobble comes round to where it started.
    [(0.5, 0.15, 0.0)] -> a level swaying between 0.85 and 1.15 once every 2 s."""
    out = []
    for index in range(length):
        seconds = index / RATE
        level = 1.0
        for hertz, depth, phase in waves:
            level += depth * math.sin(2 * math.pi * hertz * seconds + phase)
        out.append(level)
    return out


def times(signal: list[float], envelope: list[float]) -> list[float]:
    """The signal shaped by the envelope, sample by sample: [0.5, -0.5] times [1.0, 0.5] -> [0.5, -0.25]."""
    return [sample * level for sample, level in zip(signal, envelope)]


def scaled(samples: list[float], gain: float) -> list[float]:
    """Every sample times `gain`: [0.5, -0.2] scaled by 2 -> [1.0, -0.4]."""
    return [sample * gain for sample in samples]


def mix(*signals: list[float]) -> list[float]:
    """Signals of the same length added together: [0.1, 0.2] and [0.3, -0.2] -> [0.4, 0.0]."""
    return [sum(values) for values in zip(*signals)]


def add(into: list[float], sound: list[float], at: int, gain: float = 1.0) -> None:
    """Mixes `sound` into `into` from sample `at` on, cutting whatever runs past the end: [1, 1] added into
    [0, 0, 0] at 2 -> [0, 0, 1]."""
    stop = min(len(into), at + len(sound))
    for index in range(at, stop):
        into[index] += gain * sound[index - at]


def fade_out(samples: list[float], seconds: float) -> list[float]:
    """The last `seconds` faded smoothly to silence, so a hit ends without a click: a bell still ringing at 2.5 s
    with fade_out(bell, 0.3) -> unchanged up to 2.2 s, silent by its last sample."""
    fall = count(seconds)
    out = list(samples)
    for left in range(1, fall + 1):
        out[-left] *= math.sin(math.pi / 2 * left / fall) ** 2
    return out


def scatter(length: int, per_second: float, seed: int, make) -> list[float]:
    """Many short sounds at random moments (seeded), `per_second` of them on average, each made by `make(rng)`:
    scatter(count(1.0), 100, seed, clap) -> a second of applause, 100 claps landing anywhere in it."""
    rng = random.Random(seed)
    out = silence(length)
    how_many = round(per_second * length / RATE)
    for _ in range(how_many):
        at = rng.randrange(length)
        add(out, make(rng), at)
    return out


def crossfade_weights(progress: float, periodic: bool) -> tuple[float, float]:
    """The weights (start fading in, tail fading out) at `progress` 0..1 through a loop's crossfade. A periodic
    sound's tail is the same sound as its start, so straight lines keep its level: 0.5 -> (0.5, 0.5). Different
    stretches of noise add by power, so a quarter sine and cosine keep theirs: 0.5 -> (0.707, 0.707)."""
    if periodic:
        return progress, 1 - progress
    angle = math.pi / 2 * progress
    return math.sin(angle), math.cos(angle)


def seamless(samples: list[float], seconds: float, periodic: bool = False) -> list[float]:
    """A loop `seconds` long from `samples`, which run 0.3 s longer: the extra tail is faded out over the loop's
    first 0.3 s while the loop's own start fades in. The file's first sample is then the tail's first, the one that
    followed the file's last, so played round and round there is no join. `periodic` is for a hum whose tones fit the
    loop a whole number of times (see crossfade_weights)."""
    length = count(seconds)
    overlap = count(CROSSFADE)
    loop = samples[:length]
    for index in range(overlap):
        fade_in, fade_out = crossfade_weights(index / overlap, periodic)
        loop[index] = samples[index] * fade_in + samples[length + index] * fade_out
    return loop


def loop_length(seconds: float) -> int:
    """The samples a loop is made of before seamless(): its own length plus the tail that is faded into its start:
    loop_length(4.0) -> 189630, 4.3 s."""
    return count(seconds + CROSSFADE)


def struck(frequency: float, length: int, partials: list[tuple[float, float, float]]) -> list[float]:
    """A struck metal tone: for each (ratio, gain, fall) partial a sine at frequency x ratio that dies away in `fall`
    seconds. Bells ring with partials that aren't whole multiples, which is what makes them sound like metal:
    struck(1760, n, [(1.0, 1.0, 0.45), (2.76, 0.35, 0.16)]) -> a 1760 Hz note with a quieter 4858 Hz partial that
    dies sooner (the ting)."""
    out = silence(length)
    for ratio, gain, fall in partials:
        partial = times(tone(frequency * ratio, length), decay(length, fall))
        add(out, partial, 0, gain)
    return out


# Hits.

def whoosh() -> list[float]:
    # Noise through a band-pass whose centre sweeps up from 300 Hz to 2.5 kHz, under a swell that peaks at 0.3 s and
    # dies away: air rushing past.
    length = count(0.8)
    centres = pitch_rise(300, 2500, length)
    _, air = resonant(noise(length, seed=1), centres, damping=0.6)
    return times(air, swell(length, peak=0.38))


def click() -> list[float]:
    # A 2 kHz sine that dies in 4 ms with a snap of high noise that dies in 1.5 ms: a small, soft click.
    length = count(0.1)
    ping = times(tone(2000, length), decay(length, 0.004))
    snap = times(highpass(noise(length, seed=2), 3000), decay(length, 0.0015))
    return fade_out(mix(ping, scaled(snap, 0.8)), 0.02)


def tick() -> list[float]:
    # A clock tick: a 3.2 kHz sine dying in 6 ms on a 900 Hz knock dying in 12 ms, with a 2 ms snap of high noise.
    length = count(0.15)
    bright = times(tone(3200, length), decay(length, 0.006))
    knock = times(tone(900, length), decay(length, 0.012))
    snap = times(highpass(noise(length, seed=3), 4000), decay(length, 0.002))
    return fade_out(mix(bright, scaled(knock, 0.6), scaled(snap, 0.6)), 0.02)


def ting() -> list[float]:
    # A small struck bar at 1760 Hz (A6) with two higher, quieter partials (2.76 and 5.4 times, as a glockenspiel
    # bar rings) that die sooner than the note.
    length = count(1.5)
    note = struck(1760, length, [(1.0, 1.0, 0.45), (2.76, 0.35, 0.16), (5.40, 0.15, 0.07)])
    return fade_out(note, 0.1)


def bell() -> list[float]:
    # A bell at 330 Hz: the partials a cast bell rings with (a hum an octave down, the note, a minor third, a fifth,
    # the octave and two above), each dying at its own pace, a second partial 1 Hz off the note so it shimmers, and
    # a 5 ms knock of noise where the clapper strikes.
    length = count(2.5)
    partials = [(0.5, 0.5, 1.2), (1.0, 0.8, 0.9), (1.003, 0.4, 0.9), (1.2, 0.5, 0.6), (1.5, 0.35, 0.5),
                (2.0, 0.6, 0.45), (2.5, 0.2, 0.25), (3.0, 0.15, 0.2)]
    ring = struck(330, length, partials)
    strike = times(band(noise(length, seed=4), 1000, 5000), decay(length, 0.005))
    return fade_out(mix(ring, scaled(strike, 0.6)), 0.3)


def chime() -> list[float]:
    # Three struck bars rising through a major chord (E6, G#6, B6), 0.15 s apart, each like the ting.
    length = count(2.0)
    out = silence(length)
    for number, frequency in enumerate([1318.5, 1661.2, 1975.5]):
        start = count(0.15 * number)
        note = struck(frequency, length - start, [(1.0, 1.0, 0.5), (2.76, 0.25, 0.12), (5.40, 0.1, 0.05)])
        add(out, note, start, gain=0.8)
    return fade_out(out, 0.2)


def thud() -> list[float]:
    # A sine falling from 100 Hz to 45 Hz that dies in 0.12 s, on a 30 ms burst of noise dulled below 300 Hz: a
    # heavy thing landing.
    length = count(0.6)
    body = times(sine(pitch_drop(100, 45, length, fall=0.05)), decay(length, 0.12))
    dull = lowpass(lowpass(noise(length, seed=5), 300), 300)
    impact = times(dull, decay(length, 0.03))
    return fade_out(mix(body, scaled(impact, 12.0)), 0.05)


def drum() -> list[float]:
    # A drum: a sine falling from 150 Hz to 70 Hz that dies in 0.25 s, an overtone 1.6 times higher that dies sooner,
    # and a 15 ms burst of mid noise for the stick on the skin.
    length = count(0.8)
    body = times(sine(pitch_drop(150, 70, length, fall=0.04)), decay(length, 0.25))
    overtone = times(sine(pitch_drop(240, 112, length, fall=0.04)), decay(length, 0.08))
    skin = times(band(noise(length, seed=6), 200, 2500), decay(length, 0.015))
    return fade_out(mix(body, scaled(overtone, 0.4), scaled(skin, 1.5)), 0.1)


def riser() -> list[float]:
    # Noise through a ringing band-pass whose centre climbs from 200 Hz to 5 kHz, with a quiet sine climbing two
    # octaves (220 to 880 Hz) under it, both growing louder to the end: suspense building to a reveal.
    length = count(2.5)
    centres = pitch_rise(200, 5000, length)
    _, air = resonant(noise(length, seed=7), centres, damping=0.5)
    climb = sine(pitch_rise(220, 880, length))
    growing = [(index / length) ** 2 for index in range(length)]
    rising = mix(air, scaled(climb, 0.25))
    return fade_out(times(rising, growing), 0.02)


def stamp() -> list[float]:
    # A rubber stamp on paper on a desk: a short knock (a sine falling from 180 Hz to 110 Hz, dying in 40 ms), a
    # 25 ms burst of noise below 1.2 kHz for the thump, and a 6 ms slap of high noise for the paper.
    length = count(0.5)
    knock = times(sine(pitch_drop(180, 110, length, fall=0.02)), decay(length, 0.04))
    thump = times(lowpass(noise(length, seed=8), 1200), decay(length, 0.025))
    slap = times(highpass(noise(length, seed=9), 2500), decay(length, 0.006))
    return fade_out(mix(knock, scaled(thump, 3.0), scaled(slap, 0.6)), 0.05)


def page() -> list[float]:
    # A page turning: noise between 1.5 and 7 kHz that swells and fades over half a second, fluttering at random
    # every 10 ms like paper bending, then a short snap of high noise as the page lands.
    length = count(0.7)
    paper = band(noise(length, seed=10), 1500, 7000)
    rng = random.Random(11)
    steps = []
    while len(steps) < length:
        steps.extend([rng.uniform(0.3, 1.0)] * count(0.01))
    flutter = lowpass(steps[:length], 40)
    rustle = times(times(paper, flutter), swell(length, peak=0.45))
    out = list(rustle)
    snap = times(highpass(noise(count(0.1), seed=12), 2000), decay(count(0.1), 0.01))
    add(out, snap, count(0.5), gain=0.5)
    return fade_out(out, 0.05)


def key() -> list[float]:
    # One key pressed and let go: a click of noise between 2 and 6 kHz dying in 4 ms on a 220 Hz thock as it goes
    # down, and a quieter click as it comes back up 70 ms later.
    length = count(0.15)
    part = count(0.06)
    press = mix(times(band(noise(part, seed=13), 2000, 6000), decay(part, 0.004)),
                scaled(times(tone(220, part), decay(part, 0.008)), 0.5))
    release = times(band(noise(part, seed=14), 2000, 6000), decay(part, 0.003))
    out = silence(length)
    add(out, press, count(0.003))
    add(out, release, count(0.07), gain=0.45)
    return fade_out(out, 0.02)


def whistle() -> list[float]:
    # A steam whistle: two sines a fifth apart (587 and 881 Hz) with a little vibrato and a touch of the octave, a
    # slow 0.25 s attack and a 0.35 s release, over breath noise between 1 and 4 kHz that puffs at the start.
    length = count(2.0)
    vibrato = [1 + 0.004 * math.sin(2 * math.pi * 5.5 * index / RATE) for index in range(length)]
    low = sine([587.33 * shake for shake in vibrato])
    fifth = sine([587.33 * 1.5 * shake for shake in vibrato])
    octave = sine([587.33 * 2 * shake for shake in vibrato])
    voice = mix(low, scaled(fifth, 0.8), scaled(octave, 0.15))
    puff = [0.35 + level for level in decay(length, 0.3)]
    breath = times(band(noise(length, seed=15), 1000, 4000), puff)
    steam = mix(voice, scaled(breath, 1.2))
    return times(steam, attack_release(length, attack=0.25, release=0.35))


def clap(rng: random.Random) -> list[float]:
    """One hand clap: noise in a band around 0.9-2.2 kHz (each clap a little different) dying in 6-14 ms."""
    length = count(0.06)
    centre = rng.uniform(900, 2200)
    hands = band(noise(length, seed=rng.randrange(1_000_000)), centre * 0.6, centre * 1.6)
    fall = rng.uniform(0.006, 0.014)
    return scaled(times(hands, decay(length, fall)), rng.uniform(0.4, 1.0))


def applause_short() -> list[float]:
    # A short burst of applause: about 100 claps a second at random moments, coming in over 80 ms, holding to 0.45 s
    # and dying away over the second after.
    length = count(1.5)
    claps = scatter(length, per_second=100, seed=16, make=clap)
    hold = count(0.45)
    envelope = []
    for index in range(length):
        level = min(1.0, index / count(0.08))
        if index > hold:
            level = math.exp(-(index - hold) / count(0.35))
        envelope.append(level)
    return fade_out(times(claps, envelope), 0.1)


# Loops: each is made loop_length() long and made seamless at the end.

def drop(rng: random.Random) -> list[float]:
    """One raindrop: a 2-5 ms tick of high noise with a tiny pitched plip, at a random loudness."""
    length = count(0.02)
    hiss = highpass(noise(length, seed=rng.randrange(1_000_000)), 2500)
    fall = rng.uniform(0.002, 0.005)
    splash = times(hiss, decay(length, fall))
    plip = times(tone(rng.uniform(2000, 4500), length), decay(length, 0.003))
    loudness = rng.uniform(0.2, 0.7)
    return scaled(mix(splash, scaled(plip, 0.4)), loudness)


def rain() -> list[float]:
    # Steady rain: a bed of noise between 600 Hz and 7 kHz (the hiss of many drops) whose level wobbles slowly, with
    # about 70 single drops a second on top.
    length = loop_length(4.0)
    hiss = band(noise(length, seed=20), 600, 7000)
    bed = times(hiss, wobble(length, [(0.5, 0.15, 0.0), (0.25, 0.1, 1.0)]))
    drops = scatter(length, per_second=70, seed=21, make=drop)
    return seamless(mix(scaled(bed, 2.0), drops), 4.0)


def wind() -> list[float]:
    # Wind in gusts: noise through a ringing band-pass whose centre drifts between about 130 and 870 Hz, rising and
    # falling in level once and three times a loop, over a rumble of noise dulled below 150 Hz.
    length = loop_length(6.0)
    centres = []
    for index in range(length):
        seconds = index / RATE
        drift = 250 * math.sin(2 * math.pi * seconds / 6) + 120 * math.sin(2 * math.pi * 2 * seconds / 6 + 0.7)
        centres.append(500 + drift)
    _, gusts = resonant(noise(length, seed=22), centres, damping=0.35)
    gusting = times(gusts, wobble(length, [(1 / 6, 0.35, -math.pi / 2), (3 / 6, 0.15, 0.0)]))
    rumble = lowpass(lowpass(noise(length, seed=23), 150), 150)
    return seamless(mix(gusting, scaled(rumble, 8.0)), 6.0)


def sea() -> list[float]:
    # Waves on a shore: one swell every 8 s (0.125 Hz). Noise through a low-pass that opens from 300 Hz to 1.7 kHz as
    # the wave rises and grows louder, a hiss of foam just after the crest, and a constant distant surf below 200 Hz.
    # The loop starts and ends in the lull between waves.
    length = loop_length(8.0)
    swell_levels = []
    foam_levels = []
    for index in range(length):
        seconds = index / RATE
        rising = 0.5 - 0.5 * math.cos(2 * math.pi * seconds / 8)
        breaking = 0.5 - 0.5 * math.cos(2 * math.pi * (seconds - 0.7) / 8)
        swell_levels.append(rising)
        foam_levels.append(breaking ** 4)
    cutoffs = [300 + 1400 * level ** 2 for level in swell_levels]
    surge, _ = resonant(noise(length, seed=24), cutoffs, damping=1.2)
    surging = times(surge, [0.2 + 0.8 * level ** 1.5 for level in swell_levels])
    foam = times(highpass(noise(length, seed=25), 2500), foam_levels)
    distant = lowpass(lowpass(noise(length, seed=26), 200), 200)
    return seamless(mix(surging, scaled(foam, 0.5), scaled(distant, 3.0)), 8.0)


def crowd() -> list[float]:
    # A crowd's murmur: eight voices, each noise in a band around its own pitch (250-900 Hz) switched on and off in
    # random syllables of 0.1-0.25 s, smoothed, over a low room bed of noise between 200 Hz and 2 kHz.
    length = loop_length(5.0)
    out = scaled(band(noise(length, seed=30), 200, 2000), 0.3)
    for voice in range(8):
        rng = random.Random(31 + voice)
        centre = rng.uniform(250, 900)
        talk = band(noise(length, seed=40 + voice), centre * 0.7, centre * 1.5)
        steps = []
        while len(steps) < length:
            level = rng.uniform(0.2, 1.0)
            if rng.random() < 0.2:
                level = 0.05  # a pause between words
            steps.extend([level] * count(rng.uniform(0.1, 0.25)))
        syllables = lowpass(steps[:length], 8)
        add(out, times(talk, syllables), 0)
    return seamless(out, 5.0)


def step(rng: random.Random, cutoff: float) -> list[float]:
    """One boot on the ground: a 35 ms burst of noise dulled below `cutoff` Hz, a 110-to-60 Hz thump and a faint
    scuff of high noise."""
    length = count(0.2)
    heel = times(lowpass(noise(length, seed=rng.randrange(1_000_000)), cutoff), decay(length, 0.035))
    thump = times(sine(pitch_drop(110, 60, length, fall=0.02)), decay(length, 0.03))
    scuff = times(band(noise(length, seed=rng.randrange(1_000_000)), 1500, 5000), decay(length, 0.012))
    return mix(scaled(heel, 4.0), scaled(thump, 0.5), scaled(scuff, 0.3))


def footsteps() -> list[float]:
    # Four people marching in step at two steps a second (8 in the loop): each step a short low-passed burst, the
    # left foot a little louder and brighter than the right, each marcher up to 15 ms off the beat. Steps fall at
    # 0.4 s, 0.9 s ... 3.9 s, so the loop's join lands between two steps.
    length = loop_length(4.0)
    out = silence(length)
    for marcher in range(4):
        rng = random.Random(50 + marcher)
        loudness = rng.uniform(0.6, 1.0)
        for number in range(8):
            left_foot = number % 2 == 0
            cutoff = 700 if left_foot else 500
            gain = loudness if left_foot else loudness * 0.8
            at = 0.4 + 0.5 * number + rng.uniform(-0.015, 0.015)
            add(out, step(rng, cutoff), count(at), gain)
    return seamless(out, 4.0)


def heart_thump(top: float, seed: int) -> list[float]:
    """One thump of a heart, 0.45 s: a sine falling from `top` Hz to 0.6 of it, dying in 70 ms, with a dull 20 ms
    knock of noise below 250 Hz. heart_thump(65, ...) is the "lub", heart_thump(75, ...) the "dub"."""
    part = count(0.45)
    body = times(sine(pitch_drop(top, top * 0.6, part, fall=0.03)), decay(part, 0.07))
    knock = times(lowpass(lowpass(noise(part, seed=seed), 250), 250), decay(part, 0.02))
    return mix(body, scaled(knock, 6.0))


def heartbeat() -> list[float]:
    # A heart at 60 beats a minute: each beat two low thumps 0.27 s apart, "lub" (a sine falling from 65 to 40 Hz,
    # dying in 70 ms, with a dull 20 ms knock) and a quieter "dub" a little higher. Beats at 0.35 s, 1.35 s ...
    length = loop_length(4.0)
    out = silence(length)
    for beat in range(4):
        at = 0.35 + beat
        add(out, heart_thump(65, seed=60 + beat), count(at))
        add(out, heart_thump(75, seed=70 + beat), count(at + 0.27), gain=0.65)
    return seamless(out, 4.0)


def train() -> list[float]:
    # A steam train: four chuffs a second (bursts of noise between 250 Hz and 2.2 kHz dying in 60 ms, accented
    # strong-weak-medium-weak), a steady hiss of steam above 3 kHz, and the rails' clack-clack once a second.
    length = loop_length(4.0)
    out = silence(length)
    accents = [1.0, 0.55, 0.8, 0.55]
    part = count(0.2)
    number = 0
    while count(0.05 + 0.25 * number) < length:
        chuff = times(band(noise(part, seed=80 + number), 250, 2200), decay(part, 0.06))
        add(out, chuff, count(0.05 + 0.25 * number), accents[number % 4])
        number += 1
    hiss = times(highpass(noise(length, seed=79), 3000), wobble(length, [(2.0, 0.2, 0.0)]))
    add(out, hiss, 0, gain=0.25)
    clack_part = count(0.03)
    for second in range(4):
        for offset, seed in [(0.6, 120 + second), (0.72, 130 + second)]:
            clack = times(band(noise(clack_part, seed=seed), 1500, 5000), decay(clack_part, 0.006))
            add(out, clack, count(second + offset), gain=0.6)
    return seamless(out, 4.0)


def engine() -> list[float]:
    # A low engine hum: 50 Hz with its harmonics (100, 150, 200, 300 Hz), throbbing gently twice a second, over a
    # rumble of noise dulled below 250 Hz. Every tone fits the 4 s loop a whole number of times, so the hum is
    # periodic and the join uses a straight crossfade.
    length = loop_length(4.0)
    hum = silence(length)
    for frequency, gain in [(50, 1.0), (100, 0.6), (150, 0.35), (200, 0.2), (300, 0.1)]:
        add(hum, tone(frequency, length), 0, gain)
    throbbing = times(hum, wobble(length, [(2.0, 0.06, 0.0)]))
    rumble = lowpass(lowpass(noise(length, seed=90), 250), 250)
    return seamless(mix(throbbing, scaled(rumble, 6.0)), 4.0, periodic=True)


def typewriter() -> list[float]:
    # Typing at a typewriter: keys at irregular moments 70-200 ms apart with the odd pause of a quarter to half a
    # second, each key a clack of noise between 1.5 and 5 kHz dying in 5 ms on the dull thunk of the typebar. The
    # keys start 0.3 s into the loop, so the join is a pause.
    length = loop_length(5.0)
    out = silence(length)
    rng = random.Random(100)
    part = count(0.08)
    at = 0.3
    while at < 4.95:
        clack = times(band(noise(part, seed=rng.randrange(1_000_000)), 1500, 5000), decay(part, 0.005))
        thunk = times(lowpass(noise(part, seed=rng.randrange(1_000_000)), 500), decay(part, 0.015))
        add(out, mix(clack, scaled(thunk, 3.0)), count(at), rng.uniform(0.6, 1.0))
        at += rng.uniform(0.07, 0.2)
        if rng.random() < 0.08:
            at += rng.uniform(0.25, 0.5)
    return seamless(out, 5.0)


def applause() -> list[float]:
    # Ongoing applause: about 120 claps a second at random moments, the level breathing slowly (once and twice a loop).
    length = loop_length(5.0)
    claps = scatter(length, per_second=120, seed=110, make=clap)
    return seamless(times(claps, wobble(length, [(0.2, 0.1, 0.0), (0.4, 0.05, 1.0)])), 5.0)


def chirp(pitch: float) -> list[float]:
    """One cricket chirp: three 18 ms pulses of a sine at `pitch` Hz, 30 ms apart."""
    pulse_length = count(0.018)
    pulse = times(tone(pitch, pulse_length), swell(pulse_length, peak=0.5))
    out = silence(count(0.09))
    for number in range(3):
        add(out, pulse, count(0.03 * number))
    return out


def night() -> list[float]:
    # Crickets at night: three crickets (4.6, 3.9 and 5.2 kHz) chirping every 0.5, 0.625 and 1.25 s (each fits the
    # 5 s loop a whole number of times), each chirp a little louder or softer, over faint air below 400 Hz.
    length = loop_length(5.0)
    out = scaled(lowpass(lowpass(noise(length, seed=140), 400), 400), 3.0)
    rng = random.Random(141)
    for pitch, every, first, gain in [(4600, 0.5, 0.32, 1.0), (3900, 0.625, 0.45, 0.7), (5200, 1.25, 0.7, 0.45)]:
        sound = chirp(pitch)
        at = first
        while at < 5.0:
            add(out, sound, count(at), gain * rng.uniform(0.8, 1.0))
            at += every
    return seamless(out, 5.0)


def bird_call(rng: random.Random) -> list[float]:
    """One bird's call: two to four short notes, each a sine sliding from 2.5-4.5 kHz up or down a little over
    50-100 ms, with short gaps."""
    out = []
    for _ in range(rng.randint(2, 4)):
        note_length = count(rng.uniform(0.05, 0.1))
        start = rng.uniform(2500, 4500)
        end = start * rng.uniform(0.8, 1.3)
        frequencies = [start + (end - start) * index / note_length for index in range(note_length)]
        out.extend(times(sine(frequencies), swell(note_length, peak=0.3)))
        out.extend(silence(count(rng.uniform(0.04, 0.08))))
    return out


def forest() -> list[float]:
    # A forest, faintly: leaves rustling (noise between 1.5 and 6 kHz whose level drifts once, twice and three times
    # a loop) and four short bird calls at seeded moments between 0.5 and 5.4 s.
    length = loop_length(6.0)
    leaves = band(noise(length, seed=150), 1500, 6000)
    rustling = times(leaves, wobble(length, [(1 / 6, 0.4, 0.0), (2 / 6, 0.2, 1.0), (3 / 6, 0.1, 2.0)]))
    out = scaled(rustling, 0.5)
    rng = random.Random(151)
    for moment in [0.5, 1.9, 3.3, 4.6]:
        at = moment + rng.uniform(0.0, 0.3)
        add(out, bird_call(rng), count(at), rng.uniform(0.5, 1.0))
    return seamless(out, 6.0)


MAKERS = {
    "whoosh": whoosh, "click": click, "tick": tick, "ting": ting, "bell": bell, "chime": chime, "thud": thud,
    "drum": drum, "riser": riser, "stamp": stamp, "page": page, "key": key, "whistle": whistle,
    "applause-short": applause_short,
    "rain": rain, "wind": wind, "sea": sea, "crowd": crowd, "footsteps": footsteps, "heartbeat": heartbeat,
    "train": train, "engine": engine, "typewriter": typewriter, "applause": applause, "night": night,
    "forest": forest,
}


def write(name: str, samples: list[float]) -> int:
    """Scales the samples so the loudest is at -3 dBFS and writes them as the kit's mono 44.1 kHz 16-bit WAV for
    `name`; returns the file's size in bytes. A sound peaking at 2.4 is scaled down by 3.4 times, one
    peaking at 0.1 is raised: every file peaks at the same level."""
    loudest = max(abs(sample) for sample in samples)
    gain = PEAK / loudest
    pcm = array.array("h", [round(sample * gain * 32767) for sample in samples])
    if sys.byteorder == "big":
        pcm.byteswap()  # WAV is little-endian
    where = sounds.path(name)
    with wave.open(str(where), "wb") as file:
        file.setnchannels(1)
        file.setsampwidth(2)
        file.setframerate(RATE)
        file.writeframes(pcm.tobytes())
    return where.stat().st_size


def main() -> None:
    parser = argparse.ArgumentParser(description="Synthesizes the explainer video's sounds into odie/video/kit/sounds.")
    parser.add_argument("names", nargs="*", help="only these sounds (default: every sound in the index)")
    args = parser.parse_args()
    names = list(sounds.SOUNDS)
    if args.names:
        names = args.names
    unknown = [name for name in names if not sounds.is_known(name)]
    if unknown:
        parser.error(f"not in odie.video.sounds.SOUNDS: {', '.join(unknown)}")
    if set(MAKERS) != set(sounds.SOUNDS):
        raise SystemExit("MAKERS and odie.video.sounds.SOUNDS name different sounds: keep them in step.")

    sounds.FOLDER.mkdir(parents=True, exist_ok=True)
    for name in names:
        samples = MAKERS[name]()
        declared = count(sounds.SOUNDS[name].seconds)
        if len(samples) != declared:
            raise SystemExit(f"{name}: made {len(samples)} samples, the index says {declared}.")
        size = write(name, samples)
        print(f"{name:<15} {len(samples) / RATE:5.2f} s  {size / 1024:6.1f} KB")
    total = sum(file.stat().st_size for file in sounds.FOLDER.glob("*.wav"))
    print(f"{'total':<15} {total / 1_000_000:.2f} MB in the folder (the limit is 8 MB)")


if __name__ == "__main__":
    main()
