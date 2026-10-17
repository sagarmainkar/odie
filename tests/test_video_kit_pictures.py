"""video.js draws pictures and clips in a real browser: fit, zoom and focus, wipes, scrims, textures, an unknown name,
and a clip that gives the same frame at the same t in two tabs."""
import base64
import hashlib
import io
import json
import subprocess

import pytest
from PIL import Image

from odie.browser import RENDER_ARGS, find
from odie.browser.engine import Browser, BrowserError
from odie.video import page
from odie.video.encode import ffmpeg

BIN = find.installed()
needs_browser = pytest.mark.skipif(BIN is None, reason="no Chrome, Edge, Chromium or Brave here")
TIMINGS = {"starts": [0.0], "lengths": [2.0]}
RED = (255, 0, 0)
BLUE = (0, 0, 255)


def png_data_uri(picture: Image.Image) -> str:
    buffer = io.BytesIO()
    picture.save(buffer, "PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def red_left_blue_right() -> Image.Image:
    """400x300: the left half red, the right half blue."""
    picture = Image.new("RGB", (400, 300), BLUE)
    picture.paste(RED, (0, 0, 200, 300))
    return picture


def portrait_red_top_quarter() -> Image.Image:
    """300x600: the top 150 rows red, the rest blue."""
    picture = Image.new("RGB", (300, 600), BLUE)
    picture.paste(RED, (0, 0, 300, 150))
    return picture


def horizontal_bands() -> Image.Image:
    """400x300 in six 50-row bands of different colours, so any shift up or down changes the picture."""
    picture = Image.new("RGB", (400, 300))
    colours = [(255, 0, 0), (255, 160, 0), (255, 255, 0), (0, 200, 0), (0, 0, 255), (160, 0, 200)]
    for i, colour in enumerate(colours):
        picture.paste(colour, (0, i * 50, 400, (i + 1) * 50))
    return picture


def picture_assets() -> dict:
    """img1 the landscape test picture, img2 the portrait one, img3 the banded landscape, img4..img8 copies of img1 so
    the names run img1..img8."""
    landscape = png_data_uri(red_left_blue_right())
    assets = {
        "img1": {"kind": "image", "src": landscape, "width": 400, "height": 300},
        "img2": {"kind": "image", "src": png_data_uri(portrait_red_top_quarter()), "width": 300, "height": 600},
        "img3": {"kind": "image", "src": png_data_uri(horizontal_bands()), "width": 400, "height": 300},
    }
    for n in range(4, 9):
        assets[f"img{n}"] = {"kind": "image", "src": landscape, "width": 400, "height": 300}
    return assets


# One scene whose drawing is whatever window.__draw is when the frame is drawn, so each test sets its own. Its setup
# puts a plane carrying img1's texture in the 3D scene, shown only when window.__showPlane is set.
SCENE = """<script>
Video.assets(%s);
Video.scenes([
  {setup(s) {
    const material = new THREE.MeshBasicMaterial({map: s.texture("img1")});
    this.plane = new THREE.Mesh(new THREE.PlaneGeometry(8, 6), material);
    s.three.scene.add(this.plane);
    window.__sameTexture = s.texture("img1") === s.texture("img1") && s.texture("img1").isTexture === true;
  },
  draw(t, s) {
    this.plane.visible = window.__showPlane === true;
    if (window.__draw) {
      window.__draw(t, s);
    }
  }},
]);
</script>"""


def body_with(assets: dict) -> str:
    return SCENE % json.dumps(assets)


def pixel(png: bytes, x: int, y: int) -> tuple[int, int, int]:
    return Image.open(io.BytesIO(png)).convert("RGB").getpixel((x, y))


def near(colour: tuple[int, int, int], expected: tuple[int, int, int], slack: int = 12) -> bool:
    return all(abs(a - b) <= slack for a, b in zip(colour, expected))


async def drawn(p, draw_js: str, at: float = 0.5) -> bytes:
    """Sets the scene's drawing to `draw_js` (a function of t and s), draws the frame at `at` and photographs it."""
    await p.eval(f"window.__draw = {draw_js}; true")
    await p.eval(f"__frame({at})")
    return await p.shot("png")


@needs_browser
async def test_photos_fit_zoom_and_focus_where_the_options_say(tmp_path):
    b = Browser(tmp_path / "p", BIN, extra_args=RENDER_ARGS)
    try:
        async with b.sealed_page(page.assemble(body_with(picture_assets()), TIMINGS), 1920, 1080) as p:
            # contain: 400x300 scaled to 1440x1080, centred: bars on the left and right show the stage behind
            contain = await drawn(p, '(t, s) => s.photo("img1", {fit: "contain"})')
            # cover pushed in 1.5x looking at the top-left corner: the middle of the stage is the picture's left (red)
            top_left = await drawn(p, '(t, s) => s.photo("img1", {zoom: 1.5, focus: {x: 0, y: 0}})')
            top_right = await drawn(p, '(t, s) => s.photo("img1", {zoom: 1.5, focus: {x: 1, y: 0}})')
            # a portrait picture with cover crops from the upper third by default; an explicit focus overrides it
            portrait = await drawn(p, '(t, s) => s.photo("img2")')
            portrait_centred = await drawn(p, '(t, s) => s.photo("img2", {focus: {x: 0.5, y: 0.5}})')
            # a box: the picture only inside it
            boxed = await drawn(p, '(t, s) => s.photo("img1", {x: 100, y: 100, w: 400, h: 300, radius: 20})')
            same_texture = await p.eval("window.__sameTexture")
            assert p.errors == []
    finally:
        await b.close()
    stage = (14, 17, 23)  # the kit's background, #0e1117
    assert near(pixel(contain, 100, 540), stage) and near(pixel(contain, 1820, 540), stage)
    assert near(pixel(contain, 600, 540), RED) and near(pixel(contain, 1500, 540), BLUE)
    assert near(pixel(top_left, 960, 540), RED)
    assert near(pixel(top_right, 960, 540), BLUE)
    assert near(pixel(portrait, 960, 10), RED)
    assert near(pixel(portrait_centred, 960, 10), BLUE)
    assert near(pixel(boxed, 200, 250), RED) and near(pixel(boxed, 400, 250), BLUE)
    assert near(pixel(boxed, 700, 250), stage) and near(pixel(boxed, 101, 101), stage)  # outside; a rounded corner
    assert same_texture is True


@needs_browser
async def test_a_landscape_picture_less_wide_than_the_stage_is_centred_by_default(tmp_path):
    # 4:3 is taller in shape than the 16:9 stage, so cover crops it top and bottom; it is not a portrait, so it keeps
    # its centre (only portraits keep their upper third)
    b = Browser(tmp_path / "p", BIN, extra_args=RENDER_ARGS)
    try:
        async with b.sealed_page(page.assemble(body_with(picture_assets()), TIMINGS), 1920, 1080) as p:
            default = await drawn(p, '(t, s) => s.photo("img3")')
            centred = await drawn(p, '(t, s) => s.photo("img3", {focus: {x: 0.5, y: 0.5}})')
            upper_third = await drawn(p, '(t, s) => s.photo("img3", {focus: {x: 0.5, y: 0.33}})')
            assert p.errors == []
    finally:
        await b.close()
    assert hashlib.sha1(default).hexdigest() == hashlib.sha1(centred).hexdigest()
    assert hashlib.sha1(default).hexdigest() != hashlib.sha1(upper_third).hexdigest()


@needs_browser
async def test_a_wipe_shows_a_on_one_side_and_b_on_the_other_and_a_scrim_darkens_its_edge(tmp_path):
    fill_then_wipe = """(t, s) => {
      s.ctx.fillStyle = "#ff0000"; s.ctx.fillRect(0, 0, s.W, s.H);
      s.wipe(0.5, {dir: "%s"});
      s.ctx.fillStyle = "#0000ff"; s.ctx.fillRect(0, 0, s.W, s.H);
    }"""
    b = Browser(tmp_path / "p", BIN, extra_args=RENDER_ARGS)
    try:
        async with b.sealed_page(page.assemble(body_with(picture_assets()), TIMINGS), 1920, 1080) as p:
            right = await drawn(p, fill_then_wipe % "right")
            left = await drawn(p, fill_then_wipe % "left")
            down = await drawn(p, fill_then_wipe % "down")
            circle = await drawn(p, fill_then_wipe % "circle")
            scrim = await drawn(p, """(t, s) => {
              s.ctx.fillStyle = "#ffffff"; s.ctx.fillRect(0, 0, s.W, s.H);
              s.scrim();
            }""")
            # the wipe ends with the frame: the next frame draws without it
            after = await drawn(p, '(t, s) => { s.ctx.fillStyle = "#0000ff"; s.ctx.fillRect(0, 0, s.W, s.H); }')
            assert p.errors == []
    finally:
        await b.close()
    # "right": the edge moves right, so B comes in from the left
    assert near(pixel(right, 480, 540), BLUE) and near(pixel(right, 1440, 540), RED)
    assert near(pixel(left, 480, 540), RED) and near(pixel(left, 1440, 540), BLUE)
    assert near(pixel(down, 960, 270), BLUE) and near(pixel(down, 960, 810), RED)
    assert near(pixel(circle, 960, 540), BLUE) and near(pixel(circle, 10, 10), RED)
    top, bottom = pixel(scrim, 960, 200), pixel(scrim, 960, 1075)
    assert near(top, (255, 255, 255)) and sum(bottom) < sum(top) / 2
    assert near(pixel(after, 1440, 540), BLUE)


@needs_browser
async def test_a_photo_as_a_texture_in_3d(tmp_path):
    b = Browser(tmp_path / "p", BIN, extra_args=RENDER_ARGS)
    try:
        async with b.sealed_page(page.assemble(body_with(picture_assets()), TIMINGS), 1920, 1080) as p:
            await p.eval("window.__showPlane = true; true")
            shot = await drawn(p, "(t, s) => {}")
            assert p.errors == []
    finally:
        await b.close()
    # the 8x6 plane at the origin spans about x 440..1480 on the stage: red on its left, blue on its right
    assert near(pixel(shot, 700, 540), RED, slack=30) and near(pixel(shot, 1220, 540), BLUE, slack=30)


@needs_browser
async def test_an_unknown_picture_is_named_with_the_ones_there_are(tmp_path):
    b = Browser(tmp_path / "p", BIN, extra_args=RENDER_ARGS)
    try:
        async with b.sealed_page(page.assemble(body_with(picture_assets()), TIMINGS), 1920, 1080) as p:
            await p.eval('window.__draw = (t, s) => s.photo("img9"); true')
            with pytest.raises(BrowserError) as raised:
                await p.eval("__frame(0.5)")
    finally:
        await b.close()
    assert "no picture called img9; the pictures are img1…img8" in str(raised.value)


def ramp_webm(tmp_path) -> str:
    """A 1-second 320x240 VP9 WebM (the format clips ship in; every Chrome-family browser plays it) whose every frame
    differs (ffmpeg's test pattern with a frame counter), as a data URI."""
    path = tmp_path / "ramp.webm"
    pattern = "testsrc=size=320x240:rate=25:duration=1"
    subprocess.run([ffmpeg(), "-y", "-loglevel", "error", "-f", "lavfi", "-i", pattern,
                    "-c:v", "libvpx-vp9", "-pix_fmt", "yuv420p", "-an", str(path)], check=True)
    return "data:video/webm;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def clip_body(src: str) -> str:
    assets = {"clip1": {"kind": "clip", "src": src, "width": 320, "height": 240, "seconds": 1.0}}
    return body_with({**picture_assets(), **assets})


async def clip_shots(b: Browser, html: str, times: list[float]) -> list[str]:
    """In a fresh sealed tab: clip1 drawn at each of `times` in turn, each frame's PNG hash."""
    hashes = []
    async with b.sealed_page(html, 1920, 1080) as p:
        await p.eval('window.__draw = (t, s) => s.clip("clip1", window.__clipAt, {fit: "contain"}); true')
        for at in times:
            assert await p.eval(f"window.__clipAt = {at}; __frame(0.5)") is True
            hashes.append(hashlib.sha1(await p.shot("png")).hexdigest())
        assert p.errors == []
    return hashes


@needs_browser
async def test_a_clip_at_the_same_t_gives_the_same_frame_in_two_tabs(tmp_path):
    html = page.assemble(clip_body(ramp_webm(tmp_path)), TIMINGS)
    b = Browser(tmp_path / "p", BIN, extra_args=RENDER_ARGS)
    try:
        first_tab = await clip_shots(b, html, [0.5, 0.1, 1.5])
        second_tab = await clip_shots(b, html, [0.9, 0.5])  # reaches 0.5 from somewhere else
    finally:
        await b.close()
    at_half, at_tenth, past_the_end = first_tab
    assert at_half == second_tab[1]
    assert at_half != at_tenth  # the clip really moves with t
    assert past_the_end == at_half  # it loops: 1.5 s into a 1-second clip is 0.5 s


@needs_browser
async def test_a_frame_with_a_clip_returns_a_promise_and_one_without_returns_true(tmp_path):
    html = page.assemble(clip_body(ramp_webm(tmp_path)), TIMINGS)
    b = Browser(tmp_path / "p", BIN, extra_args=RENDER_ARGS)
    try:
        async with b.sealed_page(html, 1920, 1080) as p:
            await p.eval("__frame(0.5)")  # the first frame waits for the pictures; after that, nothing to wait for
            await p.eval('window.__draw = (t, s) => s.photo("img1"); true')
            plain = await p.eval("__frame(0.5) === true")
            await p.eval('window.__draw = (t, s) => s.clip("clip1", t); true')
            promised = await p.eval("__frame(0.5) instanceof Promise")
            await p.eval('window.__draw = (t, s) => { s.clip("clip1", 0.2); s.clip("clip1", 0.4); }; true')
            twice = await p.eval("(() => { try { return Promise.resolve(__frame(0.5)).then(() => 'drawn', "
                                 "e => e.message); } catch (e) { return e.message; } })()")
            assert p.errors == []
    finally:
        await b.close()
    assert plain is True and promised is True
    assert "clip1" in twice and "one moment" in twice
