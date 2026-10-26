"""Frames drawn by several browser tabs at once: each tab renders its own run of frames into its own ffmpeg segment,
and the segments, in order, are the whole picture."""
import asyncio
from collections.abc import Callable
from pathlib import Path

from odie.browser.engine import Browser
from odie.video import avatars, timeline
from odie.video.encode import Segment
from odie.video.page import assemble

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
                       counter: Counter, size: tuple[int, int] = timeline.LANDSCAPE,
                       loaded: list[avatars.Loaded] | None = None) -> Path:
    """One tab of the video's size: its own sealed page, frames first..end-1 drawn in order into one segment (the
    segment takes the frames' size as it is). A frame that draws a clip returns a promise (the clip is seeked first);
    `page.eval` awaits it, so each picture is of the finished frame. With 3D characters (`loaded`, read once by
    render), the tab is handed their models as soon as it opens, and each frame is asked for through them
    (avatars.frame_call); without, frames are asked for as always."""
    width, height = size
    with_avatars = bool(loaded)  # None or [] -> no 3D characters on this page
    async with browser.sealed_page(html, width, height) as page, Segment(path, fps) as segment:
        if with_avatars:
            await avatars.hand_over(page, loaded)
        for k in range(first, end):
            await page.eval(avatars.frame_call(k / fps, with_avatars))
            jpeg = await page.shot("jpeg", JPEG_QUALITY)
            await segment.add(jpeg)
            counter.one_more()
    return path


async def render(browser: Browser, body: str, timings: dict, folder: Path, fps: int, tabs: int,
                 progress: Callable[[int, int], None] | None = None, assets_script: str = "",
                 credits_script: str = "", size: tuple[int, int] = timeline.LANDSCAPE,
                 brand_script: str = "", lines_script: str = "",
                 models: list[avatars.Model] | None = None) -> list[Path]:
    """Draws every frame of the video at `size` (timeline.LANDSCAPE, or VERTICAL for a reel) and returns the segment
    files (`segment-0.mp4`, ...) in order; every tab's page carries the pictures and clips (`assets_script`) and Odie's
    credits card (`credits_script`, whose scene the timings include), and a brand kit's script (`brand_script`, its
    bookends in the timings too) and a dialogue video's line timeline (`lines_script`), see page.assemble. A dialogue
    video's 3D characters (`models`, odie.video.avatars) put the 3D kit in the page; each file is read once here and
    handed to every tab as it opens. Without models the page and the frames are exactly as before. If any tab
    fails, the others are stopped and the error comes out: no half-written segment is handed back."""
    avatar_script = ""
    loaded = None
    if models:
        avatar_script = avatars.page_script(models)
        loaded = avatars.load(models)  # once, shared by every tab
    html = assemble(body, timings, assets_script, credits_script, size=size, brand_script=brand_script,
                    lines_script=lines_script, avatar_script=avatar_script)
    total_seconds = timings["starts"][-1] + timings["lengths"][-1]
    frames = timeline.frame_count(total_seconds, fps)
    counter = Counter(frames, progress)

    jobs = []
    for i, (first, end) in enumerate(frame_ranges(frames, tabs)):
        path = folder / f"segment-{i}.mp4"
        drawn = render_range(browser, html, path, fps, first, end, counter, size=size, loaded=loaded)
        jobs.append(asyncio.create_task(drawn))

    try:
        return list(await asyncio.gather(*jobs))
    except BaseException:
        for job in jobs:
            job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)
        raise
