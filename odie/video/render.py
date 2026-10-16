"""Frames drawn by several browser tabs at once: each tab renders its own run of frames into its own ffmpeg segment,
and the segments, in order, are the whole picture."""
import asyncio
from collections.abc import Callable
from pathlib import Path

from odie.browser.engine import Browser
from odie.video import timeline
from odie.video.encode import Segment
from odie.video.page import assemble

WIDTH = 1920
HEIGHT = 1080
JPEG_QUALITY = 92


def frame_ranges(frames: int, tabs: int) -> list[tuple[int, int]]:
    """Which frames each tab draws, as (first, one past the last): contiguous, in order, as even as possible, the
    first tabs taking the extra frame, and never more tabs than frames.
    25 frames, 2 tabs -> [(0, 13), (13, 25)]; 8 frames, 4 tabs -> [(0, 2), (2, 4), (4, 6), (6, 8)];
    2 frames, 4 tabs -> [(0, 1), (1, 2)]."""
    tabs = min(tabs, frames)
    if tabs <= 0:
        return []
    each, extra = divmod(frames, tabs)
    ranges = []
    first = 0
    for i in range(tabs):
        size = each + 1 if i < extra else each
        ranges.append((first, first + size))
        first += size
    return ranges


class Counter:
    """Frames drawn so far by all tabs together; tells `progress` after each one."""

    def __init__(self, total: int, progress: Callable[[int, int], None] | None):
        self.total = total
        self.done = 0
        self.progress = progress

    def one_more(self) -> None:
        self.done += 1
        if self.progress:
            self.progress(self.done, self.total)


async def render_range(browser: Browser, html: str, path: Path, fps: int, first: int, end: int,
                       counter: Counter) -> Path:
    """One tab: its own sealed page, frames first..end-1 drawn in order into one segment."""
    async with browser.sealed_page(html, WIDTH, HEIGHT) as page, Segment(path, fps) as segment:
        for k in range(first, end):
            await page.eval(f"__frame({k / fps})")
            jpeg = await page.shot("jpeg", JPEG_QUALITY)
            await segment.add(jpeg)
            counter.one_more()
    return path


async def render(browser: Browser, body: str, timings: dict, folder: Path, fps: int, tabs: int,
                 progress: Callable[[int, int], None] | None = None) -> list[Path]:
    """Draws every frame of the video and returns the segment files (`segment-0.mp4`, ...) in order. If any tab
    fails, the others are stopped and the error comes out: no half-written segment is handed back."""
    html = assemble(body, timings)
    total_seconds = timings["starts"][-1] + timings["lengths"][-1]
    frames = timeline.frame_count(total_seconds, fps)
    counter = Counter(frames, progress)

    jobs = []
    for i, (first, end) in enumerate(frame_ranges(frames, tabs)):
        path = folder / f"segment-{i}.mp4"
        jobs.append(asyncio.create_task(render_range(browser, html, path, fps, first, end, counter)))

    try:
        return list(await asyncio.gather(*jobs))
    except BaseException:
        for job in jobs:
            job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)
        raise
