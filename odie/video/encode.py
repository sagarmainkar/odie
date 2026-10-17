"""ffmpeg for the explainer video: JPEG frames become one segment per scene, the segments are joined with the
narration into the final MP4, and probe reads back what a file holds. The ffmpeg binary comes from imageio-ffmpeg
(a separate program, not part of Odie's code). Every call is an async subprocess, so the event loop never waits."""
import asyncio
import re
from pathlib import Path

import imageio_ffmpeg

STDERR_TAIL = 2000      # characters of ffmpeg's complaint kept in an error

# The colours players expect of an HD video: limited ("tv") range and the BT.709 matrix, written into the stream too.
# The JPEG frames arrive full range with the old SD matrix, which players show washed out or with shifted colours.
TO_HD_COLOURS = ("scale=out_range=tv:out_color_matrix=bt709,format=yuv420p,"
                 "setparams=range=tv:colorspace=bt709:color_primaries=bt709:color_trc=bt709")


class EncodeError(Exception):
    """ffmpeg failed; the message is the tail of what it said on stderr."""


def ffmpeg() -> str:
    """Path to the ffmpeg binary that imageio-ffmpeg ships for this platform."""
    return imageio_ffmpeg.get_ffmpeg_exe()


def tail(text: bytes) -> str:
    """The last 2000 characters of ffmpeg's stderr: a long complaint keeps its end, where the cause usually is."""
    return text.decode("utf-8", errors="replace").strip()[-STDERR_TAIL:]


class Segment:
    """One scene's picture: `async with Segment(path, fps) as seg: await seg.add(jpeg_bytes)` for each frame.
    Leaving the block normally closes ffmpeg's input, waits for it to finish and raises EncodeError if it failed.
    Leaving it with an error ends ffmpeg at once and lets the original error go on."""

    def __init__(self, path: Path, fps: int):
        self.path = path
        self.fps = fps
        self.process: asyncio.subprocess.Process | None = None
        self.stderr_task: asyncio.Task | None = None

    async def __aenter__(self) -> "Segment":
        command = [
            ffmpeg(), "-y", "-loglevel", "error",
            "-f", "image2pipe", "-c:v", "mjpeg", "-framerate", str(self.fps), "-i", "-",
            "-vf", TO_HD_COLOURS, "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p",
            str(self.path),
        ]
        self.process = await asyncio.create_subprocess_exec(
            *command,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        # Read stderr while frames go in, so a chatty ffmpeg can never fill its pipe and stall.
        self.stderr_task = asyncio.create_task(self.process.stderr.read())
        return self

    async def add(self, jpeg: bytes) -> None:
        """Send one frame. If ffmpeg has already stopped (a bad frame), the pipe is closed on us: ignore that here,
        because leaving the block reports what ffmpeg said."""
        stdin = self.process.stdin
        try:
            stdin.write(jpeg)
            await stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass

    async def __aexit__(self, exc_type, exc, traceback) -> bool:
        if exc_type is not None:
            await self.stop()
            return False
        await self.close_input()
        code = await self.process.wait()
        stderr = await self.stderr_task
        if code != 0:
            raise EncodeError(tail(stderr) or f"ffmpeg exited with {code}")
        return False

    async def close_input(self) -> None:
        stdin = self.process.stdin
        try:
            stdin.close()
            await stdin.wait_closed()
        except (BrokenPipeError, ConnectionResetError):
            pass

    async def stop(self) -> None:
        """End ffmpeg now (the block failed): no orphan process, no half-read pipe."""
        if self.process.returncode is None:
            self.process.kill()
        await self.process.wait()
        await self.stderr_task


def concat_line(path: Path) -> str:
    """One line of ffmpeg's concat list, the path in single quotes with any single quote written as '\\'':
    /jobs/seg0.mp4 -> file '/jobs/seg0.mp4';  /jobs/Asha's seg.mp4 -> file '/jobs/Asha'\\''s seg.mp4'."""
    quoted = str(path).replace("'", "'\\''")
    return f"file '{quoted}'"


async def run(command: list[str]) -> tuple[int, bytes]:
    """Run a command to the end; give back its exit code and stderr."""
    process = await asyncio.create_subprocess_exec(
        *command,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await process.communicate()
    return process.returncode, stderr


async def mux(segments: list[Path], narration_wav: Path, out: Path) -> None:
    """Join the scene segments in order, lay the narration under them and write the final MP4. The picture is copied
    (already encoded), the voice becomes AAC, and the shorter of the two sets the length."""
    list_file = out.parent / f"{out.stem}-segments.txt"
    lines = [concat_line(segment) for segment in segments]
    list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")
    command = [
        ffmpeg(), "-y", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", str(list_file),
        "-i", str(narration_wav),
        "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart",
        str(out),
    ]
    code, stderr = await run(command)
    if code != 0:
        raise EncodeError(tail(stderr) or f"ffmpeg exited with {code}")


DURATION = re.compile(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)")
# A video stream's pixel format, after its codec: "Video: h264 (High) (avc1 / 0x31637661), yuv420p(tv, bt709, …), …"
PIXELS = re.compile(r" Video: [^,]+, (\w+\([^)]*\)|\w+)")
# A video stream's size, after a comma: "…, yuv420p(tv, progressive), 1280x720, SAR 1:1 …" -> 1280, 720.
SIZE = re.compile(r" Video: .*?, (\d{2,5})x(\d{2,5})\b")


async def probe(path: Path) -> dict:
    """What a media file holds: {"seconds": 3.0, "video": True, "audio": False, "pixels": "yuv420p(tv, bt709,
    progressive)", "width": 1280, "height": 720} ("pixels" is the video's pixel format and colours, "" without video;
    width and height are 0 without video). Read from `ffmpeg -i PATH`,
    which prints the facts on stderr and then exits non-zero because there is no output file: that exit is expected."""
    _, stderr = await run([ffmpeg(), "-hide_banner", "-i", str(path)])
    text = stderr.decode("utf-8", errors="replace")
    found = DURATION.search(text)
    seconds = 0.0
    if found:
        hours, minutes, secs = found.groups()
        seconds = int(hours) * 3600 + int(minutes) * 60 + float(secs)
    pixels = ""
    found_pixels = PIXELS.search(text)
    if found_pixels:
        pixels = found_pixels.group(1)
    width = 0
    height = 0
    found_size = SIZE.search(text)
    if found_size:
        width = int(found_size.group(1))
        height = int(found_size.group(2))
    return {"seconds": seconds, "video": " Video:" in text, "audio": " Audio:" in text, "pixels": pixels,
            "width": width, "height": height}
