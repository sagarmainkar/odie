"""Putting a video page together: the kit (KaTeX with its fonts, three.js, video.js) and the timings are inlined ahead
of the model's page, and a page that reaches for the network is refused with the reason."""
import pytest

from odie.browser import RENDER_ARGS, find
from odie.browser.engine import Browser
from odie.video import page

BIN = find.installed()
needs_browser = pytest.mark.skipif(BIN is None, reason="no Chrome, Edge, Chromium or Brave here")


def test_assembly_inlines_the_kit_and_the_timings():
    body = "<script>Video.scenes([{draw(){}}])</script>"
    html = page.assemble(body, {"starts": [0], "lengths": [2.0]})
    assert html.startswith("<!doctype html>")
    assert "data:font/woff2;base64," in html and "url(fonts/" not in html
    # where each piece is defined or written, not where a comment first names it
    three = html.index("THREE")
    video = html.index("window.Video = {")
    timings = html.index("<script>window.__timings = ")
    assert three < video < timings < html.index(body)
    assert '"lengths": [2.0]' in html


def test_assembly_refuses_a_page_that_loads_from_the_network():
    with pytest.raises(ValueError, match="ships with the kit"):
        page.assemble('<script src="https://cdn.example/three.js"></script>', {"starts": [0], "lengths": [1.0]})


def test_assembly_refuses_protocol_relative_links_and_css_urls():
    for body in ('<link rel="stylesheet" href="//cdn.example/a.css">',
                 "<div style=\"background: url('http://example.com/a.png')\"></div>"):
        with pytest.raises(ValueError, match="ships with the kit"):
            page.assemble(body, {"starts": [0], "lengths": [1.0]})


def test_a_web_address_in_words_is_fine():
    html = page.assemble('<script>s.text("src", "arxiv.org/abs/1706.03762, https://arxiv.org")</script>',
                         {"starts": [0], "lengths": [1.0]})
    assert "https://arxiv.org" in html


def test_fonts_are_inlined_and_their_other_formats_dropped(tmp_path):
    (tmp_path / "A.woff2").write_bytes(b"woff2!")
    css = ('@font-face{font-family:A;src:url(fonts/A.woff2) format("woff2"),url(fonts/A.woff) format("woff"),'
           'url(fonts/A.ttf) format("truetype")}')
    inlined = '@font-face{font-family:A;src:url(data:font/woff2;base64,d29mZjIh) format("woff2")}'
    assert page.inline_fonts(css, tmp_path) == inlined


def test_probe_times_cover_every_scene():
    assert page.probe_times({"starts": [0.0, 4.5], "lengths": [4.0, 2.0]}) == [0.05, 2.0, 4.0, 4.55, 5.5, 6.5]


def test_estimated_timings_from_words():
    timings = page.estimated_timings(["one two three", "word " * 70])
    assert timings["lengths"][0] == 2.0  # short scenes still get 2 s
    assert timings["lengths"][1] == 30.0  # 70 words at 140 a minute
    assert timings["starts"] == [0.0, 2.5]  # the second scene starts after the first and a breath
    assert timings["beats"] == [[0.0], [0.0]]  # no marks: one beat a scene


def test_estimated_beats_share_the_scene_by_words_and_marks_are_not_words():
    # 7 words then 21 words, 28 words in all (12 s at 140 a minute): the second phrase starts a quarter in, at 3 s
    timings = page.estimated_timings(["word " * 7 + "| " + "word " * 21])
    assert timings["lengths"] == [12.0]
    assert timings["beats"] == [[0.0, 3.0]]


def test_the_first_problem_is_the_one_told():
    assert page.first_problem(None, 2, [], []) == (
        "The page never called Video.scenes(...): put all scenes in one Video.scenes([...]) call.")
    assert page.first_problem(None, 2, ["SyntaxError: bad"], []).endswith("SyntaxError: bad")
    assert page.first_problem(2, 1, [], []) == (
        "The page has 2 scenes but there are 1 narration parts: one narration per scene.")
    assert "boom in setup" in page.first_problem(2, 2, ["Error: boom in setup"], [])
    # two draw errors: only the earlier one is told
    problem = page.first_problem(2, 2, [], [(1, 0.05, "first"), (2, 1.95, "second")])
    assert "scene 1" in problem and "first" in problem and "second" not in problem
    assert page.first_problem(2, 2, [], []) is None


def test_the_stapled_assets_go_after_the_kit_and_before_the_page():
    staple = '<script>Video.assets({"img1": {"kind": "image"}})</script>'
    html = page.assemble("<div id=page></div>", {"starts": [0], "lengths": [1.0]}, staple)
    assert html.index("<script>window.__timings = ") < html.index(staple) < html.index("<div id=page></div>")
    plain = page.assemble("<div id=page></div>", {"starts": [0], "lengths": [1.0]})
    assert plain == page.assemble("<div id=page></div>", {"starts": [0], "lengths": [1.0]}, "")
    assert "Video.assets({" not in plain.split("<script>window.__timings = ")[1]


def test_the_map_and_its_data_go_after_video_js_and_before_the_timings():
    html = page.assemble("<div id=page></div>", {"starts": [0], "lengths": [1.0]})
    video = html.index("window.Video = {")
    geo = html.index("<script>window.__geo = {")
    map_kit = html.index("// map.js: the explainer-video kit")
    timings = html.index("<script>window.__timings = ")
    assert video < geo < map_kit < timings


def test_the_map_data_is_inlined_whole_and_under_3_mb():
    geo = page._kit()["geo"]
    assert geo.startswith("window.__geo = {") and geo.endswith("};")
    assert len(geo.encode("utf-8")) < 3_000_000
    for key in ('"land": {', '"countries": {', '"states": {', '"places": {'):
        assert key in geo
    assert "</" not in geo  # nothing in the data can close the <script> it sits in


def test_the_credits_card_is_odies_closing_scene_with_one_line_a_credit():
    script = page.credits_scene(["Photo by A on Unsplash", "Video by B on Pexels"])
    assert script.startswith("<script>Video.closing({") and script.endswith("</script>")
    assert '"Pictures"' in script
    assert '["Photo by A on Unsplash", "Video by B on Pexels"]' in script
    assert page.credits_scene([]) == ""


def test_a_credit_can_never_close_the_script_it_sits_in():
    script = page.credits_scene(["Photo by </script><script>alert(1)</script> on Unsplash"])
    assert script.count("</script>") == 1 and "<\\/script>" in script


def test_the_credits_go_after_the_pictures_and_before_the_page_so_the_page_ends_with_them():
    staple = '<script>Video.assets({"img1": {"kind": "image"}})</script>'
    credits = page.credits_scene(["Photo by A on Unsplash"])
    timings = {"starts": [0, 1.5], "lengths": [1.0, 3.0]}
    html = page.assemble("<div id=page></div>", timings, staple, credits)
    assert html.index(staple) < html.index(credits) < html.index("<div id=page></div>")
    assert page.assemble("<div id=page></div>", timings, staple) == page.assemble("<div id=page></div>", timings,
                                                                                  staple, "")


# ---- The check reads back the sound cues the page placed with Video.sounds ----

async def checked_with_cues(body, narration, tmp_path) -> page.CheckResult:
    b = Browser(tmp_path / "p", BIN, extra_args=RENDER_ARGS)
    try:
        return await page.check_with_cues(body, narration, b)
    finally:
        await b.close()


@needs_browser
async def test_the_check_returns_the_cues_the_page_placed(tmp_path):
    body = ('<script>Video.scenes([{draw(t, s) {}}, {draw(t, s) {}}]);\n'
            'Video.sounds([{scene: 1, at: 0, name: "rain", seconds: 4}, {scene: 2, beat: 0, name: "whoosh", '
            'gain: 0.5}]);</script>')
    result = await checked_with_cues(body, ["word " * 10, "word " * 10], tmp_path)
    assert result == page.CheckResult(problem=None, cues=[{"scene": 1, "at": 0, "name": "rain", "seconds": 4},
                                                          {"scene": 2, "beat": 0, "name": "whoosh", "gain": 0.5}])


@needs_browser
async def test_a_page_without_cues_checks_with_none(tmp_path):
    # Review Focus 5: no Video.sounds call -> no cues
    body = "<script>Video.scenes([{draw(t, s) {}}]);</script>"
    assert await checked_with_cues(body, ["word " * 10], tmp_path) == page.CheckResult(problem=None, cues=[])


@needs_browser
async def test_a_page_whose_video_sounds_throws_is_told_the_kits_words(tmp_path):
    bad = '{scene: 1, at: 0, name: "rain"}, {scene: 1, at: 1, name: "ting"}, {scene: 1, name: "tick"}'
    after_scenes = f"<script>Video.scenes([{{draw(t, s) {{}}}}]); Video.sounds([{bad}]);</script>"
    before_scenes = f"<script>Video.sounds([{bad}]); Video.scenes([{{draw(t, s) {{}}}}]);</script>"
    for body in (after_scenes, before_scenes):
        result = await checked_with_cues(body, ["word " * 10], tmp_path)
        assert result.problem is not None and "Video.sounds: item 3 has neither at nor beat" in result.problem, (
            result.problem)
        assert result.cues == []


@needs_browser
async def test_check_still_gives_just_the_problem(tmp_path):
    body = '<script>Video.scenes([{draw(t, s) {}}]); Video.sounds([{scene: 1, at: 0, name: "rain"}]);</script>'
    b = Browser(tmp_path / "p", BIN, extra_args=RENDER_ARGS)
    try:
        assert await page.check(body, ["word " * 10], b) is None
        assert "2 scenes" in await page.check(body.replace("{draw(t, s) {}}", "{draw(){}}, {draw(){}}"),
                                              ["word " * 10], b)
    finally:
        await b.close()
