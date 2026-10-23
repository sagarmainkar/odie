"""video.js in a real browser, for a dialogue video: Video.lines gives the page who speaks when, s.speaking() says
which line plays in this frame and s.mouth(id) how open that speaker's mouth is, from the line's loudness."""
from odie.browser import RENDER_ARGS
from odie.browser.engine import Browser
from odie.video import dialogue, page
from tests.test_video_kit import BIN, needs_browser

KEEPS_S = '<script>Video.scenes([{draw(t, s) { window.__s = s; }}]);</script>'
LINES = [
    {"index": 0, "speaker": "anna", "scene": 1, "t": 0.5, "dur": 1.0, "amplitude": [0.0, 0.1, 0.4, 1.0, 0.8]},
    {"index": 1, "speaker": "ben", "scene": 1, "t": 2.0, "dur": 1.0, "amplitude": []},
]


async def evaluated(expressions, tmp_path, lines=LINES):
    html = page.assemble(KEEPS_S, {"starts": [0.0], "lengths": [4.0]}, lines_script=dialogue.lines_script(lines))
    b = Browser(tmp_path / "p", BIN, extra_args=RENDER_ARGS)
    try:
        async with b.sealed_page(html, 1920, 1080) as p:
            values = []
            for expression in expressions:
                values.append(await p.eval(expression))
            assert p.errors == []
    finally:
        await b.close()
    return values


@needs_browser
async def test_speaking_names_the_line_playing_in_this_frame(tmp_path):
    values = await evaluated([
        "__frame(0.2) && __s.speaking()",
        "__frame(1.0) && __s.speaking()",
        "__frame(1.6) && __s.speaking()",
        "__frame(2.5) && __s.speaking().speaker",
    ], tmp_path)
    assert values[0] is None
    assert values[1] == {"speaker": "anna", "index": 0, "progress": 0.5}
    assert values[2] is None  # between the lines
    assert values[3] == "ben"


@needs_browser
async def test_a_mouth_opens_with_its_speakers_loudness_and_stays_shut_otherwise(tmp_path):
    values = await evaluated([
        "__frame(0.51) && __s.mouth('anna')",  # 0.0 loud
        "__frame(0.55) && __s.mouth('anna')",  # 0.4: half open
        "__frame(0.57) && __s.mouth('anna')",  # 1.0: open
        "__frame(0.57) && __s.mouth('ben')",   # not ben's line
        "__frame(2.5) && __s.mouth('ben')",    # no loudness known (the page check): half open while speaking
        "__frame(3.5) && __s.mouth('ben')",    # after the line
        "__frame(2.5) && __s.mouth('Ben')",    # the speaker's case doesn't matter
    ], tmp_path)
    assert values == [0, 1, 2, 0, 1, 0, 1]
