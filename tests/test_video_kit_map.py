"""map.js draws the offline map in a real browser: the projection matches Web Mercator, places come from the shipped
gazetteer, routes and vehicles follow their points, a state fills inside its borders, and a frame never leans on the
projection of the frame before."""
import hashlib
import io
import json
import math
from pathlib import Path

import pytest
from PIL import Image

from odie.browser import RENDER_ARGS, find
from odie.browser.engine import Browser, BrowserError
from odie.video import page

BIN = find.installed()
needs_browser = pytest.mark.skipif(BIN is None, reason="no Chrome, Edge, Chromium or Brave here")
TIMINGS = {"starts": [0.0], "lengths": [2.0]}
PLACES = json.loads((Path(page.__file__).parent / "kit" / "geo" / "places.json").read_text())
DARK_SEA = (14, 17, 23)     # #0e1117
DARK_LAND = (29, 36, 48)    # #1d2430
PAPER_SEA = (232, 228, 216)  # #e8e4d8
PAPER_LAND = (246, 243, 234)  # #f6f3ea
RED = (255, 0, 0)

# One scene whose drawing is whatever window.__draw is when the frame is drawn; what it returns is kept in
# window.__out, so a test can draw and read the helpers' answers in the same frame.
SCENE = """<script>
Video.scenes([
  {draw(t, s) {
    window.__out = null;
    if (window.__draw) {
      window.__out = window.__draw(t, s);
    }
  }},
]);
</script>"""


def mercator_pixel(lat: float, lon: float, center: tuple[float, float], width: float) -> tuple[float, float]:
    """Web Mercator by hand: `center` in the middle of the 1920x1080 stage, `width` degrees of longitude across it.
    The equator's height is 0 and a latitude's height is ln(tan(45 degrees + lat / 2)), in degrees."""
    scale = 1920 / width

    def height(latitude: float) -> float:
        return math.degrees(math.log(math.tan(math.pi / 4 + math.radians(latitude) / 2)))

    x = 960 + (lon - center[1]) * scale
    y = 540 - (height(lat) - height(center[0])) * scale
    return x, y


def pixel(png: bytes, x: float, y: float) -> tuple[int, int, int]:
    return Image.open(io.BytesIO(png)).convert("RGB").getpixel((round(x), round(y)))


def near(colour: tuple[int, int, int], expected: tuple[int, int, int], slack: int = 12) -> bool:
    return all(abs(a - b) <= slack for a, b in zip(colour, expected))


def reddish(colour: tuple[int, int, int]) -> bool:
    return colour[0] > 120 and colour[0] > colour[1] + 60 and colour[0] > colour[2] + 60


async def drawn(p, draw_js: str, at: float = 0.5):
    """Sets the scene's drawing to `draw_js`, draws the frame at `at`; what the drawing returned and a picture of it."""
    await p.eval(f"window.__draw = {draw_js}; true")
    await p.eval(f"__frame({at})")
    out = await p.eval("window.__out")
    return out, await p.shot("png")


def open_page(tmp_path):
    browser = Browser(tmp_path / "p", BIN, extra_args=RENDER_ARGS)
    return browser, browser.sealed_page(page.assemble(SCENE, TIMINGS), 1920, 1080)


@needs_browser
async def test_the_projection_puts_the_centre_in_the_middle_and_matches_mercator(tmp_path):
    browser, sealed = open_page(tmp_path)
    try:
        async with sealed as p:
            gangtok, _ = await drawn(p, '(t, s) => { s.map({center: "Gangtok", width: 6}); '
                                        'return s.project("Gangtok"); }')
            pune, _ = await drawn(p, '(t, s) => { s.map({center: "Delhi", width: 30}); '
                                     'return s.project(s.place("Pune")); }')
            assert p.errors == []
    finally:
        await browser.close()
    assert abs(gangtok[0] - 960) < 0.5 and abs(gangtok[1] - 540) < 0.5
    delhi = PLACES["Delhi"]
    expected = mercator_pixel(PLACES["Pune"][0], PLACES["Pune"][1], (delhi[0], delhi[1]), 30)
    assert abs(pune[0] - expected[0]) < 2 and abs(pune[1] - expected[1]) < 2
    assert expected[1] > 540 + 300  # Pune is well south of Delhi: the test isn't comparing two centres


@needs_browser
async def test_places_come_from_the_gazetteer_or_are_null(tmp_path):
    browser, sealed = open_page(tmp_path)
    try:
        async with sealed as p:
            answers, _ = await drawn(p, """(t, s) => [s.place("Gangtok"), s.place("Lachung"), s.place("pune, India"),
                                                    s.place("Pune, Nepal"), s.place("Hyderabad"),
                                                    s.place("Hyderabad, Pakistan"), s.place(" PUNE ")]""")
            assert p.errors == []
    finally:
        await browser.close()
    gangtok, lachung, pune_india, pune_nepal, hyderabad, hyderabad_pakistan, pune_shouted = answers
    assert gangtok == pytest.approx([27.33, 88.62], abs=0.01)
    assert lachung is None
    assert pune_india == PLACES["Pune"][:2] and pune_shouted == PLACES["Pune"][:2]
    assert pune_nepal is None
    assert hyderabad == pytest.approx([17.4, 78.48], abs=0.01)  # the bigger Hyderabad has the plain name
    assert hyderabad_pakistan == pytest.approx([25.38, 68.37], abs=0.01)


@needs_browser
async def test_a_road_at_half_ends_at_its_midpoint_and_a_flight_is_lifted(tmp_path):
    # From 70E to 90E along 20N, centred on 80E: the stage's middle is the route's midpoint.
    route = "[[20, 70], [20, 90]]"
    browser, sealed = open_page(tmp_path)
    try:
        async with sealed as p:
            tip, road = await drawn(p, f"""(t, s) => {{ s.map({{center: [20, 80], width: 30}});
                return s.route({route}, 0.5, {{color: "#ff0000", width: 10}}); }}""")
            _, flight = await drawn(p, f"""(t, s) => {{ s.map({{center: [20, 80], width: 30}});
                s.route({route}, 1, {{kind: "flight", color: "#ff0000", width: 10}}); }}""")
            assert p.errors == []
    finally:
        await browser.close()
    assert abs(tip[0] - 960) < 2 and abs(tip[1] - 540) < 2
    assert reddish(pixel(road, 960 - 200, 540)) and not reddish(pixel(road, 960 + 200, 540))
    # the flight's middle is lifted at least 8 % of the 1280 px between its ends above the straight line
    column = [y for y in range(0, 540) if reddish(pixel(flight, 960, y))]
    assert column and max(column) < 540 - 0.08 * 1280 + 5
    assert not reddish(pixel(flight, 960, 540))


@needs_browser
async def test_sikkim_fills_inside_its_borders_and_not_bhutan(tmp_path):
    browser, sealed = open_page(tmp_path)
    try:
        async with sealed as p:
            _, plain = await drawn(p, '(t, s) => { s.map({center: "Gangtok", width: 6}); }')
            points, filled = await drawn(p, """(t, s) => { s.map({center: "Gangtok", width: 6});
                s.region("Sikkim", {color: "#ff0000"});
                return [s.project([27.6, 88.45]), s.project([27.47, 89.64])]; }""")
            with pytest.raises(BrowserError, match="no country or Indian state called Atlantis"):
                await p.eval('window.__draw = (t, s) => { s.map({center: "Gangtok", width: 6}); '
                             's.region("Atlantis"); }; __frame(0.5)')
    finally:
        await browser.close()
    inside, bhutan = points
    assert near(pixel(plain, *inside), DARK_LAND) and near(pixel(plain, *bhutan), DARK_LAND)
    assert reddish(pixel(filled, *inside))
    assert near(pixel(filled, *bhutan), DARK_LAND)


@needs_browser
async def test_a_vehicle_at_half_sits_on_the_route_and_points_along_it(tmp_path):
    browser, sealed = open_page(tmp_path)
    try:
        async with sealed as p:
            north, car = await drawn(p, """(t, s) => { s.map({center: [20, 78], width: 30});
                return s.vehicle("car", [[10, 78], [30, 78]], 0.5, {size: 80, color: "#ff0000"}); }""")
            east, _ = await drawn(p, """(t, s) => { s.map({center: [20, 78], width: 30});
                return s.vehicle("train", [[20, 70], [20, 86]], 0.5); }""")
            slant, _ = await drawn(p, """(t, s) => { s.map({center: [20, 78], width: 30});
                return [s.vehicle("plane", ["Pune", "Delhi"], 0.5, {kind: "road"}), s.project("Pune"),
                        s.project("Delhi")]; }""")
            for kind in ("plane", "walker"):
                await drawn(p, f"""(t, s) => {{ s.map({{center: [20, 78], width: 30}});
                    s.vehicle("{kind}", [[10, 78], [30, 78]], 0.5); }}""")
            with pytest.raises(BrowserError, match="isn't one of plane, car, train, walker"):
                await p.eval('window.__draw = (t, s) => { s.map({}); s.vehicle("boat", [[0, 0], [1, 1]], 0.5); }; '
                             '__frame(0.5)')
    finally:
        await browser.close()
    # half way by length on the map, which Mercator stretches northwards: between the ends' pixels, not at 20N
    south_end = mercator_pixel(10, 78, (20, 78), 30)
    north_end = mercator_pixel(30, 78, (20, 78), 30)
    assert abs(north["x"] - 960) < 1 and abs(north["y"] - (south_end[1] + north_end[1]) / 2) < 1
    assert abs(north["angle"] - -90) < 1  # degrees clockwise from east: straight up the screen
    assert abs(east["angle"]) < 1
    vehicle, pune, delhi = slant
    expected = math.degrees(math.atan2(delhi[1] - pune[1], delhi[0] - pune[0]))
    assert abs(vehicle["angle"] - expected) < 1
    # the car is long along its heading: red 32 px ahead (up), the land 32 px to its side
    assert reddish(pixel(car, north["x"], north["y"] - 32))
    assert not reddish(pixel(car, north["x"] + 32, north["y"]))


@needs_browser
async def test_following_a_flight_keeps_the_vehicle_in_the_middle(tmp_path):
    # The camera-follow shot: s.map centred on s.along(...) puts the plane at the stage's centre at any zoom.
    browser, sealed = open_page(tmp_path)
    try:
        async with sealed as p:
            answers, _ = await drawn(p, """(t, s) => { const o = {kind: "flight"};
                const here = s.along(["Pune", "Siliguri"], 0.4, o);
                s.map({center: here, width: 12});
                const plane = s.vehicle("plane", ["Pune", "Siliguri"], 0.4, o);
                s.route(["Pune", "Siliguri"], 0.4, o);
                return [plane, here]; }""")
            assert p.errors == []
    finally:
        await browser.close()
    plane, here = answers
    assert abs(plane["x"] - 960) < 1 and abs(plane["y"] - 540) < 1
    assert 18 < here[0] < 27 and 73 < here[1] < 89


@needs_browser
async def test_helpers_need_this_frames_map(tmp_path):
    browser, sealed = open_page(tmp_path)
    try:
        async with sealed as p:
            with pytest.raises(BrowserError, match="call s.map first"):
                await p.eval('window.__draw = (t, s) => { s.pin([0, 0]); }; __frame(0.5)')
            await drawn(p, "(t, s) => { s.map({}); s.pin([0, 0]); }")
            # the projection of the frame before doesn't carry over
            with pytest.raises(BrowserError, match="call s.map first"):
                await p.eval('window.__draw = (t, s) => { s.project([0, 0]); }; __frame(0.6)')
            with pytest.raises(BrowserError, match='no place called "Lachung"'):
                await p.eval('window.__draw = (t, s) => { s.map({center: "Lachung"}); }; __frame(0.5)')
    finally:
        await browser.close()


@needs_browser
async def test_a_map_frame_is_the_same_whatever_was_drawn_before_and_styles_have_their_colours(tmp_path):
    full = """(t, s) => { s.map({center: [24, 82], width: %s, style: "%s", labels: true});
        s.region("Bhutan", {color: s.colors.green});
        s.glow(["Delhi", "Agra", "Jaipur"], {radius: 60});
        s.route(["Pune", "Delhi", "Gangtok"], 0.7, {kind: "flight", dash: true});
        s.pin("Pune", {label: "Pune"});
        s.vehicle("plane", ["Pune", "Delhi", "Gangtok"], 0.7, {kind: "flight"});
        return [s.project([18, 68]), s.project([23, 79])]; }"""  # a point in the Arabian Sea, one in central India
    browser, sealed = open_page(tmp_path)
    try:
        async with sealed as p:
            points, first = await drawn(p, full % (30, "dark"))
            paper_points, paper = await drawn(p, full % (30, "paper"))
            _, zoomed = await drawn(p, full % (8, "dark"))
            _, again = await drawn(p, full % (30, "dark"))
            assert p.errors == []
    finally:
        await browser.close()
    assert hashlib.sha1(first).hexdigest() == hashlib.sha1(again).hexdigest()
    assert hashlib.sha1(first).hexdigest() != hashlib.sha1(zoomed).hexdigest()
    sea, land = points
    assert near(pixel(first, *sea), DARK_SEA) and near(pixel(first, *land), DARK_LAND)
    sea, land = paper_points
    assert near(pixel(paper, *sea), PAPER_SEA) and near(pixel(paper, *land), PAPER_LAND)


@needs_browser
async def test_a_glow_brightens_around_its_places_and_fades_away_from_them(tmp_path):
    browser, sealed = open_page(tmp_path)
    try:
        async with sealed as p:
            points, glow = await drawn(p, """(t, s) => { s.map({center: [26, 78], width: 20});
                s.glow(["Delhi", "Agra"], {color: "#ff0000", radius: 80, opacity: 1});
                return [s.project("Delhi"), s.project("Agra"), s.project([22, 86])]; }""")
            assert p.errors == []
    finally:
        await browser.close()
    delhi, agra, far = points
    between = ((delhi[0] + agra[0]) / 2, (delhi[1] + agra[1]) / 2)
    assert reddish(pixel(glow, *delhi)) and reddish(pixel(glow, *between))
    assert not reddish(pixel(glow, *far))


@needs_browser
async def test_the_page_check_passes_a_map_page_and_tells_a_missing_map(tmp_path):
    good = """<script>Video.scenes([{draw(t, s) {
        const p = s.at(t, 0, s.length);
        s.map({center: s.along(["Pune", "Siliguri"], p, {kind: "flight"}), width: s.lerp(30, 6, p)});
        s.route(["Pune", "Siliguri"], p, {kind: "flight"});
        s.vehicle("plane", ["Pune", "Siliguri"], p);
        s.pin("Gangtok", {label: "Gangtok", opacity: s.fade(t, 1)});
    }}]);</script>"""
    forgot = """<script>Video.scenes([{draw(t, s) { s.pin("Gangtok"); }}]);</script>"""
    browser = Browser(tmp_path / "p", BIN, extra_args=RENDER_ARGS)
    try:
        passed = await page.check(good, ["word " * 10], browser)
        told = await page.check(forgot, ["word " * 10], browser)
    finally:
        await browser.close()
    assert passed is None
    assert "scene 1" in told and "call s.map first" in told
