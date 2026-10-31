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


def test_the_final_covers_the_lead_in_before_the_onset():
    lengths: list[int] = []
    h = Hearing(vad=loud_is_speech, transcribe=lambda audio: lengths.append(len(audio)) or "x")
    h.feed(pcm(0.5, False))                                      # half a second of room noise first
    h.feed(pcm(0.5, True))
    h.feed(pcm(0.3, False))
    assert lengths[-1] >= int(16000 * (0.3 + 0.5)) - CHUNK       # 300 ms before the onset, and the speech


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


def test_end_closes_an_open_utterance():
    h = Hearing(vad=loud_is_speech, transcribe=lambda a: "bye")
    h.feed(pcm(0.5, True))
    assert h.end()[-1] == {"type": "words", "text": "bye", "final": True}
    assert h.end() == []
