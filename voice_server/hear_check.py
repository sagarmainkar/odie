"""A by-hand check of /stt/stream against the real models. Starts nothing: start the voice server first, then

    say -o /tmp/dubai.wav --data-format=LEI16@16000 "what is the weather like tomorrow in Dubai"
    uv run python hear_check.py /tmp/dubai.wav --url ws://127.0.0.1:8771/stt/stream

It streams the WAV (16 kHz 16-bit mono) in 32 ms frames at real-time pace, then silence, as a live microphone would,
and prints every event with the milliseconds since the clip's last sample was sent (negative: still sending). It
exits on the first final after the clip has ended, or 15 s after "ready" (the first load, with Parakeet's 2.5 GB
download, may take minutes: up to 10 are allowed for it).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
import wave
from pathlib import Path

import numpy as np
import websockets

FRAME = 512                      # 32 ms at 16 kHz
FRAME_SECONDS = FRAME / 16000
QUIET = 300                      # a sample under this (of 32,768) counts as silence, for the clip's tail


def read_clip(path: Path) -> bytes:
    """The WAV's PCM, after checking it is what the hearing takes: 16 kHz, 16-bit, mono."""
    with wave.open(str(path), "rb") as w:
        if (w.getframerate(), w.getsampwidth(), w.getnchannels()) != (16000, 2, 1):
            sys.exit(f"{path}: need 16 kHz 16-bit mono, got {w.getframerate()} Hz, {8 * w.getsampwidth()}-bit, "
                     f"{w.getnchannels()} channel(s)")
        return w.readframes(w.getnframes())


def silent_tail_ms(pcm: bytes) -> int:
    """How much silence ends the clip, in ms: a clip whose last loud sample is 0.1 s before its end -> 100."""
    samples = np.abs(np.frombuffer(pcm, dtype="<i2").astype(np.int32))
    loud = np.nonzero(samples > QUIET)[0]
    if len(loud) == 0:
        return len(samples) * 1000 // 16000
    return (len(samples) - 1 - loud[-1]) * 1000 // 16000


async def check(path: Path, url: str) -> None:
    pcm = read_clip(path)
    print(f"clip: {len(pcm) // 2 / 16000:.2f} s, of which the last {silent_tail_ms(pcm)} ms are silence")
    started = time.monotonic()
    clip_ended: list[float] = []  # set once the clip's last frame is sent
    async with websockets.connect(url, max_size=None) as ws:

        async def send() -> None:
            # Real-time pace against the clock, so a slow send does not drift: frame n goes at start + n * 32 ms.
            frames = [pcm[i:i + 2 * FRAME] for i in range(0, len(pcm), 2 * FRAME)]
            silence = bytes(2 * FRAME)
            begun = time.monotonic()
            n = 0
            while True:
                await asyncio.sleep(max(0.0, begun + n * FRAME_SECONDS - time.monotonic()))
                if n < len(frames):
                    await ws.send(frames[n])
                    if n == len(frames) - 1:
                        clip_ended.append(time.monotonic())
                else:
                    await ws.send(silence)
                n += 1

        def since_end() -> str:
            if not clip_ended:
                return "(clip still going)"
            return f"{(time.monotonic() - clip_ended[0]) * 1000:+6.0f} ms"

        sender = None
        try:
            async with asyncio.timeout(600) as limit:
                async for text in ws:
                    event = json.loads(text)
                    if event["type"] == "ready":
                        print(f"ready after {(time.monotonic() - started) * 1000:.0f} ms (model load)")
                        limit.reschedule(asyncio.get_running_loop().time() + 15)
                        sender = asyncio.create_task(send())
                        continue
                    print(f"{since_end():>20}  {text}")
                    if event["type"] == "error":
                        return
                    if event["type"] == "words" and event["final"] and clip_ended:
                        await ws.send(json.dumps({"type": "end"}))
                        return
        except TimeoutError:
            print("no final in time (10 min for the load, 15 s after ready)")
        finally:
            if sender is not None:
                sender.cancel()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("wav", type=Path)
    parser.add_argument("--url", default="ws://127.0.0.1:8771/stt/stream")
    args = parser.parse_args()
    asyncio.run(check(args.wav, args.url))


if __name__ == "__main__":
    main()
