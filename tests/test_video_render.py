"""Rendering: frames drawn by several tabs at once land in segments, in order. Real browser and real ffmpeg."""
import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

import pytest

from odie.browser import RENDER_ARGS, find
from odie.browser.engine import Browser
from odie.video import avatars, dialogue, encode, page, render
from tests.test_media import make_wav
from tests.tiny_glb import tiny_glb

BIN = find.installed()
SAMPLE = (Path(page.__file__).parent / "kit" / "sample.html").read_text()
needs_browser = pytest.mark.skipif(BIN is None, reason="no Chrome, Edge, Chromium or Brave here")


def test_frames_are_split_into_contiguous_ranges():
    assert render.frame_ranges(25, 2) == [(0, 13), (13, 25)]
    assert render.frame_ranges(8, 4) == [(0, 2), (2, 4), (4, 6), (6, 8)]
    assert render.frame_ranges(2, 4) == [(0, 1), (1, 2)]  # never more tabs than frames
    assert render.frame_ranges(1, 4) == [(0, 1)]


@needs_browser
async def test_frames_land_in_segments_in_order(tmp_path):
    timings = {"starts": [0.0, 1.5], "lengths": [1.0, 1.0]}
    seen = []
    b = Browser(tmp_path / "p", BIN, extra_args=RENDER_ARGS)
    try:
        segments = await render.render(b, SAMPLE, timings, tmp_path, fps=10, tabs=2,
                                       progress=lambda done, total: seen.append((done, total)))
    finally:
        await b.close()
    assert [p.name for p in segments] == ["segment-0.mp4", "segment-1.mp4"]
    assert all(p.stat().st_size > 0 for p in segments)
    assert seen[-1] == (25, 25)  # 2.5 s at 10 fps
    assert [done for done, _ in seen] == list(range(1, 26))
    total = sum([(await encode.probe(p))["seconds"] for p in segments])
    assert abs(total - 2.5) < 0.25


@needs_browser
async def test_one_failing_tab_stops_the_others_and_the_error_comes_out(tmp_path):
    broken = SAMPLE + "<script>window.__frame = function () { throw new Error('boom'); };</script>"
    b = Browser(tmp_path / "p", BIN, extra_args=RENDER_ARGS)
    try:
        with pytest.raises(Exception, match="boom"):
            await render.render(b, broken, {"starts": [0.0, 1.5], "lengths": [1.0, 1.0]}, tmp_path, fps=10, tabs=2)
    finally:
        await b.close()


class SlowFramePage:
    """A stand-in sealed page whose __frame returns a promise (as a frame with a clip does): eval only finishes once
    the frame has been drawn, a few event-loop turns later. `shot` records which frame was on the page."""

    def __init__(self):
        self.on_page = None
        self.photographed = []

    async def eval(self, expression: str):
        for _ in range(3):
            await asyncio.sleep(0)  # the seek, awaited inside the page
        self.on_page = expression
        return True

    async def shot(self, fmt: str, quality: int) -> bytes:
        self.photographed.append(self.on_page)
        return b"jpeg"


class StandInBrowser:
    def __init__(self, page):
        self.page = page

    @asynccontextmanager
    async def sealed_page(self, html, width, height):
        yield self.page


class StandInSegment:
    def __init__(self, path, fps):
        self.frames = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def add(self, jpeg: bytes) -> None:
        self.frames.append(jpeg)


async def test_render_range_waits_for_a_frame_that_returns_a_promise(tmp_path, monkeypatch):
    monkeypatch.setattr(render, "Segment", StandInSegment)
    slow = SlowFramePage()
    counter = render.Counter(3, None)
    await render.render_range(StandInBrowser(slow), "<html>", tmp_path / "s.mp4", 10, 0, 3, counter)
    # every picture is taken after its own frame finished drawing, never of the frame before
    assert slow.photographed == ["__frame(0.0)", "__frame(0.1)", "__frame(0.2)"]
    assert counter.done == 3


# ---- 3D characters: the models handed to every tab, frames called through them ----

class RecordingTab:
    """A stand-in sealed tab for render: records every expression it is told, answers __avatars.ready() as a page
    that parsed every model, and photographs nothing (a few bytes for the stand-in segment)."""

    def __init__(self):
        self.said = []

    async def eval(self, expression: str):
        self.said.append(expression)
        if expression == "__avatars.ready()":
            return {"failed": {}}
        return True

    async def shot(self, fmt: str, quality: int) -> bytes:
        return b"jpeg"


class TabsBrowser:
    """A stand-in browser whose every sealed page is a new RecordingTab; keeps the tabs and the HTML each was given."""

    def __init__(self):
        self.tabs = []
        self.html = []

    @asynccontextmanager
    async def sealed_page(self, html, width, height):
        tab = RecordingTab()
        self.tabs.append(tab)
        self.html.append(html)
        yield tab


def mira_model(tmp_path) -> avatars.Model:
    """Mira's model as a 10-byte mira.glb (its bytes go over as one piece, "eHh4eHh4eHh4eA==")."""
    path = tmp_path / "mira.glb"
    path.write_bytes(b"x" * 10)
    return avatars.Model(speaker="mira", name="Mira", path=path, size=10)


HANDED_OVER = ['__avatars.bytes("mira", 0, "eHh4eHh4eHh4eA==")', "__avatars.ready()"]
FOUR_FRAMES = {"starts": [0.0], "lengths": [0.4]}  # 4 frames at 10 fps


async def test_render_hands_every_tab_the_models_and_calls_frames_through_them(tmp_path, monkeypatch):
    monkeypatch.setattr(render, "Segment", StandInSegment)
    loads = []
    real_load = avatars.load

    def counted_load(models):
        loads.append(models)
        return real_load(models)

    monkeypatch.setattr(avatars, "load", counted_load)
    browser = TabsBrowser()
    model = mira_model(tmp_path)
    await render.render(browser, SAMPLE, FOUR_FRAMES, tmp_path, fps=10, tabs=2, models=[model])
    assert len(loads) == 1  # the file read and encoded once, shared by both tabs
    first, second = [tab.said for tab in browser.tabs]
    assert first == HANDED_OVER + ["__avatars.frame(0.0)", "__avatars.frame(0.1)"]
    assert second == HANDED_OVER + ["__avatars.frame(0.2)", "__avatars.frame(0.3)"]
    assert all("__avatars.expect" in html for html in browser.html)


async def test_render_without_models_is_as_before(tmp_path, monkeypatch):
    monkeypatch.setattr(render, "Segment", StandInSegment)
    browser = TabsBrowser()
    await render.render(browser, SAMPLE, FOUR_FRAMES, tmp_path, fps=10, tabs=2)
    first, second = [tab.said for tab in browser.tabs]
    assert first == ["__frame(0.0)", "__frame(0.1)"]
    assert second == ["__frame(0.2)", "__frame(0.3)"]
    assert browser.html[0] == page.assemble(SAMPLE, FOUR_FRAMES)
    assert "__avatars" not in browser.html[0]


# Mira speaks from 0.2 s to 0.8 s of a one-second video; her loudness isn't known (the mouth half open).
MIRA_LINES = [{"index": 0, "speaker": "mira", "text": "Still here?", "scene": 1, "t": 0.2, "dur": 0.6,
               "amplitude": []}]
DRAWS_MIRA = ('<script>Video.scenes([{setup(s) { this.a = s.avatar("mira"); }, draw(t, s) { this.a.update(t); }}]);'
              "</script>")


@needs_browser
async def test_a_real_render_of_a_tiny_3d_character(tmp_path):
    model_file = tmp_path / "mira.glb"
    model_file.write_bytes(tiny_glb())
    model = avatars.Model(speaker="mira", name="Mira", path=model_file, size=model_file.stat().st_size)
    b = Browser(tmp_path / "p", BIN, extra_args=RENDER_ARGS)
    try:
        segments = await render.render(b, DRAWS_MIRA, {"starts": [0.0], "lengths": [1.0]}, tmp_path, fps=10, tabs=2,
                                       lines_script=dialogue.lines_script(MIRA_LINES), models=[model])
    finally:
        await b.close()
    assert [p.name for p in segments] == ["segment-0.mp4", "segment-1.mp4"]
    assert all(p.stat().st_size > 0 for p in segments)
    quiet = tmp_path / "quiet.wav"
    quiet.write_bytes(make_wav(1.0, loud=0.0))
    mp4 = tmp_path / "mira.mp4"
    await encode.mux(segments, quiet, mp4)
    info = await encode.probe(mp4)
    assert (info["width"], info["height"]) == (1920, 1080)
