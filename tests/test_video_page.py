"""Putting a video page together: the kit (KaTeX with its fonts, three.js, video.js) and the timings are inlined ahead
of the model's page, and a page that reaches for the network is refused with the reason."""
import pytest

from odie.video import page


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
