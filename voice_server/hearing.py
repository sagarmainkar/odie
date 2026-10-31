"""Hearing: when someone starts and stops speaking, and what they said, from a stream of 16 kHz 16-bit mono PCM.

The two models are passed in, so this file is plain turn-taking logic and the tests run it with fakes:

- `vad(chunk)` takes 512 float32 samples in -1..1 and returns the probability that they are speech (Silero VAD).
- `transcribe(audio)` takes the float32 samples of a whole utterance and returns its text (Parakeet).

`feed(pcm16)` returns the events that audio produced, in order, each a dict exactly as the WebSocket sends it:

    {"type": "speech", "on": True}                          someone started speaking
    {"type": "words", "text": "what is", "final": False}    a partial, every 400 ms while they speak
    {"type": "speech", "on": False}                         they stopped
    {"type": "words", "text": "what is the weather", "final": True}

Only numpy and the standard library here: Odie's main environment imports this file in its tests and has neither
torch nor mlx.
"""
from __future__ import annotations

from collections.abc import Callable

import numpy as np

SAMPLE_RATE = 16000
CHUNK = 512                    # Silero's chunk at 16 kHz: 32 ms
ONSET_CHUNKS = 2               # 64 ms over the floor starts speech
ONSET_FLOOR = 0.5
OFFSET_FLOOR = 0.35
OFFSET_MS = 250
PARTIAL_MS = 400
LEAD_MS = 300                  # audio kept before the onset
CAP_SECONDS = 30.0

CHUNK_MS = CHUNK * 1000 // SAMPLE_RATE            # 32
LEAD_SAMPLES = SAMPLE_RATE * LEAD_MS // 1000      # 4800
CAP_SAMPLES = int(SAMPLE_RATE * CAP_SECONDS)      # 480000


def is_loud(probability: float) -> bool:
    """Whether a chunk counts towards starting speech: over the onset floor.
    0.9 -> True; 0.5 -> False (over, not at); 0.05 -> False."""
    return probability > ONSET_FLOOR


def is_quiet(probability: float) -> bool:
    """Whether a chunk counts towards stopping speech: under the offset floor. Between the floors (0.35 to 0.5)
    is neither, so a wavering voice neither starts nor stops anything.
    0.05 -> True; 0.4 -> False; 0.9 -> False."""
    return probability < OFFSET_FLOOR


def speech_starts(loud_chunks: int) -> bool:
    """Whether speech has begun: enough loud chunks in a row (2, that is 64 ms).
    1 loud chunk -> False; 2 in a row -> True."""
    return loud_chunks >= ONSET_CHUNKS


def speech_stops(quiet_ms: int) -> bool:
    """Whether speech has ended: quiet for 250 ms in a row.
    192 ms quiet (6 chunks) -> False; 256 ms quiet (8 chunks) -> True."""
    return quiet_ms >= OFFSET_MS


def partial_due(ms_since_partial: int) -> bool:
    """Whether to send a partial: 400 ms of utterance have gone by since the last one (or since the onset).
    384 ms -> False; 416 ms -> True."""
    return ms_since_partial >= PARTIAL_MS


def utterance_full(utterance_samples: int) -> bool:
    """Whether the utterance has no room for one more chunk under the 30 s cap, so it is cut before it passes 30 s.
    479,232 samples (29.95 s) -> True, another 512 would pass 480,000; 470,000 samples -> False."""
    return utterance_samples + CHUNK > CAP_SAMPLES


class Hearing:
    """The turn-taking for one audio stream. Feed it PCM as it arrives; it says when speech starts and stops and
    what was said."""

    def __init__(self, vad: Callable[[np.ndarray], float], transcribe: Callable[[np.ndarray], str]):
        self.vad = vad
        self.transcribe = transcribe
        self.reset()

    def reset(self) -> None:
        """Forget everything: no speech, no audio kept."""
        self.remainder = np.zeros(0, np.float32)   # samples that do not yet fill a chunk; they wait for the next frame
        # The most recent audio while nobody speaks: the 300 ms lead-in plus the onset's own chunks, so an utterance
        # begins 300 ms before the first loud chunk (catches the soft start of a word the VAD is slow to hear).
        self.recent = np.zeros(0, np.float32)
        self.speaking = False
        self.utterance: list[np.ndarray] = []      # the chunks of the utterance while speech is on
        self.utterance_samples = 0
        self.loud_chunks = 0                       # loud chunks in a row, while not speaking
        self.quiet_ms = 0                          # quiet in a row, while speaking
        self.ms_since_partial = 0

    def feed(self, pcm16: bytes) -> list[dict]:
        """Take a frame of 16-bit PCM of any length; return the events it produced, in order."""
        samples = np.frombuffer(pcm16, dtype=np.int16).astype(np.float32) / 32768
        self.remainder = np.concatenate([self.remainder, samples])
        events: list[dict] = []
        while len(self.remainder) >= CHUNK:
            chunk = self.remainder[:CHUNK]
            self.remainder = self.remainder[CHUNK:]
            events += self.hear_chunk(chunk)
        return events

    def end(self) -> list[dict]:
        """The stream is over: close an open utterance (speech off, then its final) and forget everything.
        Nothing open -> no events."""
        events: list[dict] = []
        if self.speaking:
            self.add_to_utterance(self.remainder)  # the last few samples that never filled a chunk
            events.append({"type": "speech", "on": False})
            events.append(self.final())
        self.reset()
        return events

    def hear_chunk(self, chunk: np.ndarray) -> list[dict]:
        """One 512-sample chunk: ask the VAD, then follow the rule for whether speech is on or off."""
        probability = self.vad(chunk)
        if self.speaking:
            return self.while_speaking(chunk, probability)
        return self.while_silent(chunk, probability)

    def while_silent(self, chunk: np.ndarray, probability: float) -> list[dict]:
        """Nobody is speaking: keep the recent audio and count loud chunks; the second loud one in a row starts an
        utterance that begins with the 300 ms before the first."""
        self.recent = np.concatenate([self.recent, chunk])[-(LEAD_SAMPLES + ONSET_CHUNKS * CHUNK):]
        if is_loud(probability):
            self.loud_chunks += 1
        else:
            self.loud_chunks = 0
        if not speech_starts(self.loud_chunks):
            return []
        self.speaking = True
        self.loud_chunks = 0
        self.quiet_ms = 0
        self.ms_since_partial = 0
        self.utterance = []
        self.utterance_samples = 0
        self.add_to_utterance(self.recent)
        self.recent = np.zeros(0, np.float32)
        return [{"type": "speech", "on": True}]

    def while_speaking(self, chunk: np.ndarray, probability: float) -> list[dict]:
        """Someone is speaking: add the chunk to the utterance, then stop at 250 ms of quiet, or cut at the 30 s cap,
        or send a partial every 400 ms."""
        events: list[dict] = []
        if utterance_full(self.utterance_samples):
            # The cap: send what we have as a final and carry on with a fresh utterance, still speaking. The client
            # sees the usual off / final / on, so every "on" has its "off".
            events.append({"type": "speech", "on": False})
            events.append(self.final())
            events.append({"type": "speech", "on": True})
            self.utterance = []
            self.utterance_samples = 0
            self.ms_since_partial = 0
        self.add_to_utterance(chunk)
        self.ms_since_partial += CHUNK_MS
        if is_quiet(probability):
            self.quiet_ms += CHUNK_MS
        else:
            self.quiet_ms = 0
        if speech_stops(self.quiet_ms):
            events.append({"type": "speech", "on": False})
            events.append(self.final())
            self.speaking = False
            self.utterance = []
            self.utterance_samples = 0
            self.quiet_ms = 0
            return events
        if partial_due(self.ms_since_partial):
            self.ms_since_partial = 0
            events.append({"type": "words", "text": self.transcribe(self.audio()), "final": False})
        return events

    def add_to_utterance(self, samples: np.ndarray) -> None:
        self.utterance.append(samples)
        self.utterance_samples += len(samples)

    def audio(self) -> np.ndarray:
        """The utterance so far as one float32 array, for the recogniser."""
        if not self.utterance:
            return np.zeros(0, np.float32)
        return np.concatenate(self.utterance)

    def final(self) -> dict:
        return {"type": "words", "text": self.transcribe(self.audio()), "final": True}
