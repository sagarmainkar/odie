import numpy as np

from voice_server.hearing import CHUNK, Hearing


def pcm(seconds: float, loud: bool) -> bytes:
    """16 kHz 16-bit PCM: a 440 Hz tone at half scale, or silence."""
    n = int(16000 * seconds)
    t = np.arange(n) / 16000
    wave = (np.sin(2 * np.pi * 440 * t) * 16000).astype(np.int16) if loud else np.zeros(n, np.int16)
    return wave.tobytes()


def loud_is_speech(chunk: np.ndarray) -> float:
    return 0.9 if np.abs(chunk).max() > 0.1 else 0.05


def test_speech_starts_after_two_loud_chunks_and_stops_after_the_quiet():
    h = Hearing(vad=loud_is_speech, transcribe=lambda audio: "hello")
    events = h.feed(pcm(0.032, True))            # one chunk: not yet
    assert events == []
    events = h.feed(pcm(0.032, True))            # the second: speech on
    assert events == [{"type": "speech", "on": True}]
    events = h.feed(pcm(0.2, False))             # 200 ms quiet: not yet off
    assert all(e["type"] != "speech" for e in events)
    events = h.feed(pcm(0.1, False))             # 300 ms quiet: off, with the final
    assert {"type": "speech", "on": False} in events
    assert events[-1] == {"type": "words", "text": "hello", "final": True}


def test_partials_come_every_400_ms_over_the_utterance_so_far():
    seen: list[int] = []

    def transcribe(audio: np.ndarray) -> str:
        seen.append(len(audio))
        return f"{len(seen)}"

    h = Hearing(vad=loud_is_speech, transcribe=transcribe)
    events = h.feed(pcm(1.0, True))
    partials = [e for e in events if e["type"] == "words" and not e["final"]]
    assert [e["text"] for e in partials] == ["1", "2"]          # at 0.4 s and 0.8 s of speech
    assert seen[1] > seen[0]                                     # each over more audio than the last
    assert seen[0] >= int(16000 * 0.4)                           # the utterance so far, not one chunk
    # Exactly: the 2 onset chunks (no audio came before them), then 13 chunks (416 ms) per partial.
    # 1,024 + 13 x 512 = 7,680; then 7,680 + 13 x 512 = 14,336. A dropped chunk shows here.
    assert seen == [7680, 14336]


def test_the_final_covers_the_lead_in_before_the_onset():
    heard: list[np.ndarray] = []
    lengths: list[int] = []

    def transcribe(audio: np.ndarray) -> str:
        heard.append(audio)
        lengths.append(len(audio))
        return "x"

    h = Hearing(vad=loud_is_speech, transcribe=transcribe)
    h.feed(pcm(0.5, False))                                      # half a second of room noise first
    h.feed(pcm(0.5, True))
    h.feed(pcm(0.3, False))
    assert lengths[-1] >= int(16000 * (0.3 + 0.5)) - CHUNK       # 300 ms before the onset, and the speech
    final = heard[-1]
    # The 8,000 quiet samples fill 15 chunks and leave 320, so chunk 15 is 320 silent samples then the tone: the first
    # loud chunk. 300 ms (4,800 samples) of silence come before it, and the tone starts 320 samples into it.
    first_sound = int(np.flatnonzero(final)[0])
    assert 4800 <= first_sound < 4800 + CHUNK
    # 4,800 lead-in + 2 onset chunks (1,024) + 14 loud chunks (7,168) + 9 tail chunks (4,608: one with the tone's last
    # 128 samples, so still loud, then the 8 quiet ones that make 256 ms) = 17,600.
    assert len(final) == 17600


def test_frames_of_any_size_lose_no_samples():
    fed: list[int] = []
    h = Hearing(vad=lambda c: fed.append(len(c)) or 0.0, transcribe=lambda a: "")
    for _ in range(10):
        h.feed(pcm(0.02, False))                                 # 320-sample frames
    assert all(n == CHUNK for n in fed)
    assert sum(fed) == 3072                                      # 3200 samples fed, 6 chunks, 128 kept for the next


def test_speech_that_never_stops_is_cut_at_the_cap():
    h = Hearing(vad=loud_is_speech, transcribe=lambda a: "long")
    events = []
    for _ in range(32):
        events += h.feed(pcm(1.0, True))
    finals = [e for e in events if e["type"] == "words" and e["final"]]
    assert len(finals) >= 1
    assert {"type": "speech", "on": True} in events[events.index(finals[0]) + 1:]   # speech starts again after the cut


def test_a_pause_that_begins_just_before_the_cap_ends_the_speech_there():
    lengths: list[int] = []
    h = Hearing(vad=loud_is_speech, transcribe=lambda a: lengths.append(len(a)) or "long")
    events = h.feed(pcm(29.9, True))                             # the tone ends 3 chunks before the cap
    events += h.feed(pcm(0.6, False))
    finals = [e for e in events if e["type"] == "words" and e["final"]]
    assert len(finals) == 1                                      # no 32 ms leftover utterance after the cut
    assert lengths[-1] == 479744                                 # the final came at the cap: 1,024 + 935 x 512
    assert events[-2:] == [{"type": "speech", "on": False}, {"type": "words", "text": "long", "final": True}]


def test_frames_split_mid_sample_lose_no_samples():
    heard: list[np.ndarray] = []
    h = Hearing(vad=lambda c: heard.append(c) or 0.0, transcribe=lambda a: "")
    samples = np.arange(1, CHUNK + 1, dtype="<i2")               # 1, 2, ... 512: one chunk
    data = samples.tobytes()
    h.feed(data[:3])                                             # a sample and a half: nothing raised
    h.feed(data[3:1023])
    h.feed(data[1023:])
    assert len(heard) == 1
    assert np.array_equal(heard[0], samples.astype(np.float32) / 32768)


def test_end_closes_an_open_utterance():
    h = Hearing(vad=loud_is_speech, transcribe=lambda a: "bye")
    h.feed(pcm(0.5, True))
    assert h.end()[-1] == {"type": "words", "text": "bye", "final": True}
    assert h.end() == []
