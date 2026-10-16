"""Rendering: frames drawn by several tabs at once land in segments, in order. Real browser and real ffmpeg."""
from pathlib import Path

import pytest

from odie.browser import RENDER_ARGS, find
from odie.browser.engine import Browser
from odie.video import encode, page, render

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
