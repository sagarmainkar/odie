"""video.js in a real browser: frames are deterministic, scenes switch on the timings, text and formulas draw."""
import hashlib
import re
from pathlib import Path

import pytest

from odie.browser import RENDER_ARGS, find
from odie.browser.engine import Browser
from odie.video import page

KIT = Path(page.__file__).parent / "kit"
SAMPLE = (KIT / "sample.html").read_text()
BIN = find.installed()
TIMINGS = {"starts": [0.0, 3.5], "lengths": [3.0, 3.0]}
needs_browser = pytest.mark.skipif(BIN is None, reason="no Chrome, Edge, Chromium or Brave here")


async def shots_at(times, tmp_path):
    b = Browser(tmp_path / "p", BIN, extra_args=RENDER_ARGS)
    out = []
    try:
        async with b.sealed_page(page.assemble(SAMPLE, TIMINGS), 1920, 1080) as p:
            assert await p.eval("window.__sceneCount") == 2
            for t in times:
                assert await p.eval(f"__frame({t})") is True
                out.append(hashlib.sha1(await p.shot("png")).hexdigest())
            assert p.errors == []
    finally:
        await b.close()
    return out


@needs_browser
async def test_the_same_time_draws_the_same_picture(tmp_path):
    a, b, a_again = await shots_at([1.0, 2.0, 1.0], tmp_path)
    assert a == a_again and a != b


@needs_browser
async def test_the_second_scene_starts_at_its_timing(tmp_path):
    end_of_first, start_of_second = await shots_at([3.4, 3.6], tmp_path)
    assert end_of_first != start_of_second


@needs_browser
async def test_fonts_load_first_formulas_draw_and_the_first_scene_text_is_hidden(tmp_path):
    b = Browser(tmp_path / "p", BIN, extra_args=RENDER_ARGS)
    try:
        async with b.sealed_page(page.assemble(SAMPLE, TIMINGS), 1920, 1080) as p:
            # every KaTeX font is in before the first frame, so a formula first drawn mid-video has its font
            fonts_in = await p.eval("[...document.fonts].filter(f => f.family.startsWith('KaTeX'))"
                                    ".every(f => f.status === 'loaded')")
            await p.eval("__frame(1.5)")
            title_shown = await p.eval("getComputedStyle(document.getElementById('v-title')).visibility")
            await p.eval("__frame(6.0)")
            title_later = await p.eval("getComputedStyle(document.getElementById('v-title')).visibility")
            formula = await p.eval("document.getElementById('v-formula').querySelector('.katex') !== null")
            assert p.errors == []
    finally:
        await b.close()
    assert title_shown == "visible" and title_later == "hidden"
    assert fonts_in and formula


def test_the_kit_and_the_sample_use_no_clock_and_no_unseeded_randomness():
    for name in ("video.js", "sample.html"):
        code = (KIT / name).read_text()
        code = re.sub(r"//[^\n]*", "", code)  # comments may name what the kit avoids
        for banned in ("requestAnimationFrame", "Date", "performance.now", "Math.random", "setTimeout", "setInterval"):
            assert banned not in code, f"{name} uses {banned}"


@needs_browser
async def test_a_page_whose_scenes_dont_match_the_narration_says_so(tmp_path):
    b = Browser(tmp_path / "p", BIN, extra_args=RENDER_ARGS)
    try:
        three_scenes = {"starts": [0.0, 3.5, 7.0], "lengths": [3.0, 3.0, 3.0]}
        async with b.sealed_page(page.assemble(SAMPLE, three_scenes), 1920, 1080) as p:
            count = await p.eval("window.__sceneCount")
            errors = list(p.errors)
    finally:
        await b.close()
    assert count == 2
    assert "The page has 2 scenes but the narration has 3" in errors[0]


# Scene 1 zooms the camera, changes the clear colour and the exposure; scene 2 draws a cube with the defaults.
MESSY = """<script>
Video.scenes([
  {draw(t, s) {
    s.three.camera.zoom = 3;
    s.three.camera.near = 5;
    s.three.camera.setViewOffset(1920, 1080, 200, 100, 1920, 1080);
    s.three.renderer.setClearColor("#ff0000", 1);
    s.three.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    s.three.renderer.toneMappingExposure = 3;
  }},
  {setup(s) {
    this.cube = new THREE.Mesh(new THREE.BoxGeometry(2, 2, 2), new THREE.MeshStandardMaterial({color: s.colors.blue}));
    s.three.scene.add(this.cube);
  },
  draw(t, s) {
    this.cube.rotation.set(0.4, t, 0);
  }},
]);
</script>"""


@needs_browser
async def test_a_frame_draws_the_same_whatever_the_tab_drew_before(tmp_path):
    html = page.assemble(MESSY, {"starts": [0.0, 1.5], "lengths": [1.0, 1.0]})
    b = Browser(tmp_path / "p", BIN, extra_args=RENDER_ARGS)
    try:
        async with b.sealed_page(html, 1920, 1080) as p:
            await p.eval("__frame(0.5)")
            await p.eval("__frame(2.0)")
            after_scene_one = hashlib.sha1(await p.shot("png")).hexdigest()
            assert p.errors == []
        async with b.sealed_page(html, 1920, 1080) as p:
            await p.eval("__frame(2.0)")
            first_in_a_fresh_tab = hashlib.sha1(await p.shot("png")).hexdigest()
    finally:
        await b.close()
    assert after_scene_one == first_in_a_fresh_tab


async def checked(body, narration, tmp_path):
    b = Browser(tmp_path / "p", BIN, extra_args=RENDER_ARGS)
    try:
        return await page.check(body, narration, b)
    finally:
        await b.close()


@needs_browser
async def test_a_scene_count_mismatch_is_named(tmp_path):
    problem = await checked(SAMPLE, ["only one scene of narration"], tmp_path)
    assert "2 scenes" in problem and "1 narration" in problem


@needs_browser
async def test_an_error_in_a_later_scene_is_caught(tmp_path):
    body = "<script>Video.scenes([{draw(){}}, {draw(t){ if (t > 1) null.boom; }}])</script>"
    problem = await checked(body, ["word " * 10, "word " * 10], tmp_path)
    assert "scene 2" in problem and "boom" in problem
    # scene 2 starts at 4.786 s and lasts 4.286 s; its middle is told in the scene's own seconds, as draw's t is
    assert "at t = 2.143 s" in problem, problem


@needs_browser
async def test_an_error_only_at_the_very_end_of_a_scene_is_caught(tmp_path):
    # the held end state (and every breath frame) draws at t = length, where p = 1 indexes one past the end
    body = ("<script>Video.scenes([{draw(t, s){ const items = [1, 2]; const p = t / s.length; "
            "items[Math.floor(p * items.length)].toFixed(); }}])</script>")
    problem = await checked(body, ["word " * 10], tmp_path)
    assert problem is not None and "scene 1 at t = 4.286 s" in problem, problem


@needs_browser
async def test_an_error_in_setup_is_caught(tmp_path):
    body = "<script>Video.scenes([{setup(){ null.kaboom; }, draw(){}}])</script>"
    problem = await checked(body, ["word " * 10], tmp_path)
    assert "kaboom" in problem


@needs_browser
async def test_a_page_that_never_calls_video_scenes_is_named(tmp_path):
    problem = await checked("<p>hello</p>", ["word " * 10], tmp_path)
    assert "never called Video.scenes" in problem


@needs_browser
async def test_a_page_that_loads_from_the_network_is_refused_with_the_reason(tmp_path):
    problem = await checked('<script src="https://cdn.example/x.js"></script>', ["word"], tmp_path)
    assert "ships with the kit" in problem


@needs_browser
async def test_a_good_page_passes(tmp_path):
    assert await checked(SAMPLE, ["word " * 10, "word " * 10], tmp_path) is None


# A one-scene page that keeps its helpers where the test can call them.
KEEPS_S = "<script>Video.scenes([{setup(s) { window.__s = s; }, draw(t, s) {}}]);</script>"


async def evaluated(timings, expressions, tmp_path):
    b = Browser(tmp_path / "p", BIN, extra_args=RENDER_ARGS)
    try:
        async with b.sealed_page(page.assemble(KEEPS_S, timings), 1920, 1080) as p:
            values = [await p.eval(expression) for expression in expressions]
            assert p.errors == []
    finally:
        await b.close()
    return values


@needs_browser
async def test_a_scene_has_its_beats_and_eased_progress_across_each(tmp_path):
    timings = {"starts": [0.0], "lengths": [5.0], "beats": [[0.0, 1.0, 3.0]]}
    values = await evaluated(timings, [
        "__s.beats",
        "__s.beat(0.5, 1)", "__s.beat(2.0, 1)", "__s.beat(3.5, 1)",  # beat 1 runs from 1 s to 3 s
        "__s.beat(4.0, 2)", "__s.beat(5.0, 2)",                       # the last beat runs to the scene's end, 5 s
        "__s.beatAt(0.5)", "__s.beatAt(1.0)", "__s.beatAt(2.9)", "__s.beatAt(4.0)",
    ], tmp_path)
    assert values == [[0, 1, 3], 0, 0.5, 1, 0.5, 1, 0, 1, 1, 2]


@needs_browser
async def test_timings_without_beats_give_each_scene_one_beat(tmp_path):
    values = await evaluated({"starts": [0.0], "lengths": [4.0]},
                             ["__s.beats", "__s.beat(2.0, 0)", "__s.beatAt(3.0)"], tmp_path)
    assert values == [[0], 0.5, 0]


BEAT_ONE = "<script>Video.scenes([{draw(t, s) { s.text('x', 'hi', {opacity: s.beat(t, 1)}); }}]);</script>"


@needs_browser
async def test_a_beat_the_narration_doesnt_mark_is_a_told_problem(tmp_path):
    problem = await checked(BEAT_ONE, ["word " * 10], tmp_path)
    assert problem is not None and "s.beat(t, 1)" in problem and "1 beat" in problem, problem


@needs_browser
async def test_a_beat_the_narration_marks_passes_the_check(tmp_path):
    assert await checked(BEAT_ONE, ["word " * 5 + "| " + "word " * 5], tmp_path) is None


def one_picture_staple() -> str:
    """The staple for one 40×30 red picture called img1, as odie.video.assets.staple makes it."""
    import base64
    import io
    import json

    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (40, 30), (255, 0, 0)).save(out, "JPEG")
    src = "data:image/jpeg;base64," + base64.b64encode(out.getvalue()).decode()
    registry = {"img1": {"kind": "image", "src": src, "width": 40, "height": 30}}
    return f"<script>Video.assets({json.dumps(registry)})</script>"


PHOTO_PAGE = '<script>Video.scenes([{draw(t, s) { s.photo("img1", {zoom: 1.1}); }}]);</script>'


@needs_browser
async def test_a_page_that_draws_a_picture_passes_the_check_with_its_staple(tmp_path):
    b = Browser(tmp_path / "p", BIN, extra_args=RENDER_ARGS)
    try:
        with_staple = await page.check(PHOTO_PAGE, ["The Red Fort at dusk."], b, one_picture_staple())
        without = await page.check(PHOTO_PAGE, ["The Red Fort at dusk."], b)
    finally:
        await b.close()
    assert with_staple is None
    assert "no picture called img1; this video has no pictures" in without
