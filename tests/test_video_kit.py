"""video.js in a real browser: frames are deterministic, scenes switch on the timings, text and formulas draw."""
import hashlib
import re
from pathlib import Path

import pytest

from odie.browser import RENDER_ARGS, find
from odie.browser.engine import Browser, BrowserError
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
    for name in ("video.js", "map.js", "sample.html"):
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


# The sample's two scenes, then Odie's credits card: the timings have three scenes, the writer's page two.
WITH_CREDITS = {"starts": [0.0, 3.5, 7.0], "lengths": [3.0, 3.0, 3.0], "beats": [[0.0], [0.0], [0.0]]}


@needs_browser
async def test_the_credits_card_is_a_scene_after_the_writers_last(tmp_path):
    credits = page.credits_scene(["Photo by A on Unsplash", "Video by B on Pexels"])
    html = page.assemble(SAMPLE, WITH_CREDITS, "", credits)
    shown = "id => getComputedStyle(document.getElementById(id)).visibility"
    b = Browser(tmp_path / "p", BIN, extra_args=RENDER_ARGS)
    try:
        async with b.sealed_page(html, 1920, 1080) as p:
            count = await p.eval("window.__sceneCount")
            await p.eval("__frame(5.0)")
            title_in_scene_2 = await p.eval(f"document.getElementById('v-odie-credits-title') === null || "
                                            f"({shown})('v-odie-credits-title')")
            await p.eval("__frame(9.5)")
            title = await p.eval(f"({shown})('v-odie-credits-title')")
            words = await p.eval("[0, 1].map(i => document.getElementById('v-odie-credits-' + i).textContent)")
            colour = await p.eval("getComputedStyle(document.getElementById('v-odie-credits-0')).color")
            heading = await p.eval("document.getElementById('v-odie-credits-title').textContent")
            assert p.errors == []
    finally:
        await b.close()
    assert count == 2  # the writer's scenes: Odie's card isn't one of the page's
    assert title_in_scene_2 in (True, "hidden")
    assert title == "visible" and heading == "Pictures"
    assert words == ["Photo by A on Unsplash", "Video by B on Pexels"]
    assert colour == "rgb(236, 236, 236)"  # the kit's text colour, #ECECEC


@needs_browser
async def test_a_credits_card_without_its_scene_in_the_timings_is_still_a_mismatch(tmp_path):
    credits = page.credits_scene(["Photo by A on Unsplash"])
    html = page.assemble(SAMPLE, TIMINGS, "", credits)
    b = Browser(tmp_path / "p", BIN, extra_args=RENDER_ARGS)
    try:
        async with b.sealed_page(html, 1920, 1080) as p:
            errors = list(p.errors)
    finally:
        await b.close()
    assert any("The page has 2 scenes but the narration has 1" in error for error in errors), errors


# ---- Sound cues: Video.sounds keeps the writer's list (after a shape check); Video.soundCues gives it back ----

async def cues_of(body, expressions, tmp_path):
    """Loads `body` in a sealed tab with one 3 s scene's timings; the value of each expression and the page's errors."""
    b = Browser(tmp_path / "p", BIN, extra_args=RENDER_ARGS)
    try:
        async with b.sealed_page(page.assemble(body, {"starts": [0.0], "lengths": [3.0]}), 1920, 1080) as p:
            values = [await p.eval(expression) for expression in expressions]
            errors = list(p.errors)
    finally:
        await b.close()
    return values, errors


ONE_SCENE = "Video.scenes([{draw(t, s) {}}]);"


@needs_browser
async def test_video_sounds_keeps_the_cues_and_sound_cues_gives_a_copy(tmp_path):
    body = ("<script>" + ONE_SCENE + 'Video.sounds([{scene: 1, at: 0, name: "rain", seconds: 6, gain: 0.4}, '
            '{scene: 1, beat: 0, name: "whoosh"}]);</script>')
    values, errors = await cues_of(body, [
        "Video.soundCues()",
        "(() => { const c = Video.soundCues(); c[0].name = 'changed'; c.push({}); return Video.soundCues(); })()",
    ], tmp_path)
    expected = [{"scene": 1, "at": 0, "name": "rain", "seconds": 6, "gain": 0.4}, {"scene": 1, "beat": 0,
                                                                                    "name": "whoosh"}]
    assert errors == []
    assert values == [expected, expected]  # changing the copy changes nothing kept


@needs_browser
async def test_sound_cues_are_empty_when_the_page_places_none(tmp_path):
    values, errors = await cues_of("<script>" + ONE_SCENE + "</script>", ["Video.soundCues()"], tmp_path)
    assert values == [[]] and errors == []


@needs_browser
async def test_a_second_video_sounds_call_adds_to_the_first(tmp_path):
    body = ("<script>" + ONE_SCENE + 'Video.sounds([{scene: 1, at: 0, name: "rain"}]); '
            'Video.sounds([{scene: 1, at: 1.5, name: "ting"}]);</script>')
    values, _errors = await cues_of(body, ["Video.soundCues().map(c => c.name)"], tmp_path)
    assert values == [["rain", "ting"]]


@needs_browser
async def test_a_bad_cue_throws_naming_its_item_and_keeps_none_of_the_list(tmp_path):
    expressions = [
        'Video.sounds([{scene: 1, at: 0, name: "rain"}, {scene: 1, at: 1, name: "ting"}, '
        '{scene: 0, at: 1, name: "x"}])',
        'Video.sounds([{scene: 1, name: "ting"}])',
        'Video.sounds([{scene: 1, at: 0, beat: 0, name: "ting"}])',
        'Video.sounds([{scene: 1, at: -1, name: "ting"}])',
        'Video.sounds([{scene: 1, beat: 1.5, name: "ting"}])',
        'Video.sounds([{scene: 1, at: 0, name: "rain", seconds: 0}])',
        'Video.sounds([{scene: 1, at: 0, name: "ting", gain: 2}])',
        'Video.sounds([{scene: 1, at: 0, name: 5}])',
        'Video.sounds([{scene: 1, at: 0, name: "ting", volume: 0.5}])',
        'Video.sounds(["ting"])',
        'Video.sounds({scene: 1, at: 0, name: "ting"})',
    ]
    told = []
    b = Browser(tmp_path / "p", BIN, extra_args=RENDER_ARGS)
    try:
        html = page.assemble("<script>" + ONE_SCENE + "</script>", {"starts": [0.0], "lengths": [3.0]})
        async with b.sealed_page(html, 1920, 1080) as p:
            for expression in expressions:
                with pytest.raises(BrowserError) as raised:
                    await p.eval(expression)
                told.append(str(raised.value))
            kept = await p.eval("Video.soundCues()")
    finally:
        await b.close()
    assert "Error: Video.sounds: item 3 has scene 0; a scene is a whole number from 1" in told[0], told[0]
    assert kept == []  # a list with a bad item is refused whole
    assert "item 1 has neither at nor beat" in told[1]
    assert "item 1 has both at and beat" in told[2]
    assert "item 1 has at -1" in told[3]
    assert "item 1 has beat 1.5" in told[4]
    assert "item 1 has seconds 0" in told[5]
    assert "item 1 has gain 2" in told[6]
    assert "item 1 has name 5" in told[7]
    assert 'item 1 has a key "volume"' in told[8]
    assert "item 1 isn't an object" in told[9]
    assert "Video.sounds takes a list" in told[10]
