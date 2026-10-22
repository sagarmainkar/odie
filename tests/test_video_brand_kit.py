"""Brand kits for make_video (odie.video.brand): a skill supplies fixed drawing code, sounds and fixed opening and
ending scenes; the page loads them, the writer must use them and can't change them, and the branded parts of two
videos come out the same whatever writes the middle. The kit used here is made up (tests/brand_kit.py)."""
import array
import io
import json
import logging
import wave

import pytest
from PIL import Image

from odie.browser import RENDER_ARGS, find
from odie.browser.engine import Browser
from odie.making import jobs
from odie.video import brand, encode, kind, page, sounds, timeline, writer
from tests import brand_kit
from tests.test_media import make_wav
from tests.test_video_jobs import make_job
from tests.test_video_tool import load_tools
from tests.test_video_vertical import joined_wavs, near, store  # noqa: F401 (store is a fixture)

tools = load_tools()
BIN = find.installed()
needs_browser = pytest.mark.skipif(BIN is None, reason="no Chrome, Edge, Chromium or Brave here")

# A three-scene reel: a question card, the timed segment (scene 2), a closing line. The page draws only text and a
# small framed box, so the kit's background shows around them.
PAGE = """<script>
Video.scenes([
  {draw(t, s) { s.text("q", "Why do magnets stick?", {size: 72}); }},
  {timed_start: true, timed_end: true, draw(t, s) {
    s.ctx.fillStyle = "#F6E05E"; s.ctx.fillRect(140, 400, 300, 300); s.text("a", "Lined up", {size: 72}); }},
  {draw(t, s) { s.text("b", "So it sticks", {size: 72}); }},
]);
Video.moves([{scene: 2, at: 0.5, name: "bounce"}]);
</script>"""
NARRATION = ["Why do magnets stick?", "Inside a magnet, tiny regions line up and point the same way, and their pulls add up.",
             "So it sticks."]
VARS = {"intro": "Here is the short version."}


@pytest.fixture
def kit_home(store, tmp_path):  # noqa: F811 (store is a fixture)
    """The test kit in this test's own skills folder (never the real one)."""
    skills = brand.skills_folder()
    assert str(skills).startswith(str(tmp_path))
    return brand_kit.make_kit(skills)


@pytest.fixture
def kit(kit_home) -> brand.Kit:
    return brand.find("test-channel")


# ── 1. Finding and reading a kit: only the user's skills folder; a broken kit is an error ──

@pytest.mark.parametrize("name", ["../other", "/etc", "a/b", "My Skill", "x" * 41])
def test_a_kit_is_named_by_its_skill_only(kit_home, name):
    with pytest.raises(brand.KitProblem, match="a skill's name"):
        brand.find(name)


def test_a_kit_folder_that_leads_outside_the_skills_folder_is_refused(kit_home, tmp_path):
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    skill = brand.skills_folder() / "linked" / "assets"
    skill.mkdir(parents=True)
    (skill / "brand").symlink_to(outside)
    with pytest.raises(brand.KitProblem, match="outside the skills folder"):
        brand.find("linked")


def test_a_skill_without_a_kit_says_where_it_looked(kit_home):
    with pytest.raises(brand.KitProblem, match=r"no brand kit: .*no-kit/assets/brand/brand.json"):
        brand.find("no-kit")


def test_the_kit_reads_with_everything_it_declares(kit):
    assert kit.name == "Test channel"
    assert set(kit.bookends) == {"handoff", "ending", "card"}
    assert kit.bookends["handoff"].says == "intro" and kit.bookends["ending"].sounds == ({"at": 0.2, "name": "ting"},)
    assert kit.character == "lantern" and kit.moves == {"bounce": 0.6} and kit.background is True
    assert kit.sounds["ting"].name == "ting.wav" and len(kit.version) == 12


@pytest.mark.parametrize("change, said", [
    (lambda m: m["bookends"].update(intro={"seconds": 2}), "there is no bookend 'intro'"),
    (lambda m: m["bookends"]["card"].update(seconds=0), "lasts 0 s"),
    (lambda m: m["bookends"]["handoff"].update(says="outro"), "isn't one of its vars"),
    (lambda m: m["bookends"]["ending"].update(sounds=[{"at": 0, "name": "rain"}]), "neither a kit sound"),
    (lambda m: m["sounds"].update(pop="pop.wav"), "pop.wav isn't in the kit"),
    (lambda m: m["sounds"].update(pop="../ting.wav"), "plain name with a file in the kit's own folder"),
    (lambda m: m.update(character=""), 'moves but no "character"'),
    (lambda m: m.update(character="my lantern"), '"character" is the name'),
    (lambda m: m.pop("api_doc"), "api_doc"),
])
def test_a_broken_manifest_is_an_error_naming_what_is_wrong(store, change, said):  # noqa: F811
    manifest = json.loads(json.dumps(brand_kit.MANIFEST))
    change(manifest)
    brand_kit.make_kit(brand.skills_folder(), manifest=manifest)
    with pytest.raises(brand.KitProblem, match=said):
        brand.find("test-channel")


@pytest.mark.parametrize("line", ['fetch("https://example.com/x.json");', "const s = new WebSocket(u);",
                                  'import x from "./x.js";', 'const u = "url(https://example.com/f.woff)";'])
def test_a_kit_script_that_reaches_out_is_refused(store, line):  # noqa: F811
    brand_kit.make_kit(brand.skills_folder(), script=brand_kit.SCRIPT + "\n" + line + "\n")
    with pytest.raises(brand.KitProblem, match="brand.js"):
        brand.find("test-channel")


def test_a_kit_sound_must_be_a_16_bit_wav(kit_home):
    with wave.open(str(kit_home / "ting.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(3)
        w.setframerate(48000)
        w.writeframes(b"\x00\x00\x00" * 4800)
    with pytest.raises(brand.KitProblem, match="24-bit"):
        brand.find("test-channel")


def test_the_version_follows_the_files(kit_home, tmp_path):
    first = brand.find("test-channel").version
    assert brand.find("test-channel").version == first
    record = brand.snapshot(brand.find("test-channel"), tmp_path / "job")
    assert brand.read_kit(tmp_path / "job" / "brand").version == first == record["version"]
    (kit_home / "brand.js").write_text(brand_kit.SCRIPT + "\n// changed\n")
    assert brand.find("test-channel").version != first


def test_the_neutral_chime_is_a_short_mono_48k_16_bit_wav(tmp_path):
    path = brand_kit.chime_wav(tmp_path / "ting.wav")
    with wave.open(str(path)) as w:
        assert (w.getnchannels(), w.getsampwidth(), w.getframerate()) == (1, 2, 48000)
        assert w.getnframes() == 48000
    assert brand.wav_problem(path) is None
    assert path.read_bytes() == brand_kit.chime_wav(tmp_path / "again.wav").read_bytes()  # the same every time


# ── 2. make_video: the kit goes on the job, copied; a missing or misused kit is an error ──

@pytest.fixture
def queued(store, monkeypatch):  # noqa: F811
    monkeypatch.setitem(jobs.hooks, "store", store)
    monkeypatch.setattr(find, "browser_binary", lambda: "/Applications/Some Browser")
    jobs_queued = []
    monkeypatch.setattr(jobs, "submit", lambda job: jobs_queued.append(job) or len(jobs_queued))
    return jobs_queued


async def test_a_video_with_a_kit_records_it_and_keeps_a_copy(queued, kit):
    said = await tools.make_video("How magnets work", minutes=2, aspect="vertical", timed_segment_seconds=60,
                                  brand_kit="test-channel")
    assert "result" in said
    [job] = queued
    assert job.data["brand_kit"] == {"name": "test-channel", "version": kit.version, "path": str(kit.folder)}
    assert sorted(p.name for p in (job.folder / "brand").iterdir()) == ["brand.js", "brand.json", "ting.wav"]


async def test_a_kit_that_sits_around_a_segment_needs_one(queued, kit):
    said = await tools.make_video("How magnets work", minutes=2, brand_kit="test-channel")
    assert "timed_segment_seconds" in said["error"] and queued == []


async def test_a_missing_kit_is_an_error_and_no_video(queued):
    said = await tools.make_video("How magnets work", minutes=2, timed_segment_seconds=60, brand_kit="no-such-skill")
    assert "no brand kit" in said["error"] and queued == []


async def test_a_video_without_a_kit_is_asked_for_as_before(queued):
    await tools.make_video("How magnets work", minutes=2)
    assert "brand_kit" not in queued[0].data


def test_a_jobs_copy_that_changed_is_an_error(kit, tmp_path):
    record = brand.snapshot(kit, tmp_path)
    assert brand.kit_of({"brand_kit": record}, tmp_path).version == kit.version
    assert brand.kit_of({}, tmp_path) is None
    (tmp_path / "brand" / "brand.js").write_text("// another kit\n")
    with pytest.raises(brand.KitProblem, match="changed"):
        brand.kit_of({"brand_kit": record}, tmp_path)


# ── 3. The writer: the kit's functions and rules, and what it may not do ──

def test_the_writer_is_given_the_kit_and_its_rules_last(kit):
    plain = writer.instruction_for("vertical", timed_seconds=60)
    with_kit = writer.instruction_for("vertical", timed_seconds=60, kit=kit)
    assert with_kit.startswith(plain.rstrip())
    rules = with_kit[len(plain.rstrip()):]
    for words in ("Brand.palette", "`Brand.*` is fixed: call it, never redraw or imitate it.",
                  "Do not draw your own character or background.", "Do not write the bookend scenes.",
                  "The kit draws the background under every scene", "The stage draws `Brand.lantern` through the whole "
                  "timed segment", "bounce (0.6 s)", '"intro": one short spoken line', "is spoken aloud", "ting"):
        assert words in rules
    assert writer.instruction_for("vertical", timed_seconds=60) == plain


def test_the_submit_tool_asks_for_the_bookends_words_only_with_a_kit_that_has_some(kit):
    assert "brand" not in writer.submit_fields(None)
    assert writer.submit_fields(kit)["brand"] == dict[str, str]
    assert "brand:" in writer.submit_doc(kit) and "brand:" not in writer.submit_doc(None)


@pytest.mark.parametrize("body", ["Brand.lantern = {};", "window.Brand = {draw() {}};", "const Brand = {};",
                                  "Brand.palette.background += 'x';", "Object.assign(Brand, {x: 1});",
                                  'Brand["palette"] = null;', "delete Brand.palette;"])
def test_a_page_that_changes_the_kit_is_refused(body):
    assert "Brand is fixed" in brand.reassign_problem(f"<script>{body}</script>")


@pytest.mark.parametrize("body", ["s.ctx.fillStyle = Brand.palette.lantern;", "if (Brand.palette == null) {}",
                                  "const brandColour = 1;", "myBrand = 2;"])
def test_a_page_that_reads_the_kit_is_fine(body):
    assert brand.reassign_problem(f"<script>{body}</script>") is None


@pytest.mark.parametrize("given, said", [
    ({"intro": "Here is the short version."}, None),
    ('{"intro": "Here is the short version."}', None),  # as JSON text, as some models send it
    (None, "Give submit_video's brand"),
    ({"intro": "  "}, "Give submit_video's brand"),
    ({"intro": "Hi.", "outro": "Bye."}, "'outro', which the kit doesn't use"),
    ({"intro": "x" * 301}, "one short line"),
])
def test_the_bookends_words(kit, given, said):
    problem = brand.vars_problem(kit, brand.vars_as_given(given))
    if said is None:
        assert problem is None
    else:
        assert said in problem


@pytest.mark.parametrize("cues, said", [
    ([{"scene": 2, "at": 0.5, "name": "bounce"}, {"scene": 2, "beat": 1, "name": "bounce"}], None),
    ([{"scene": 1, "at": 0, "name": "bounce"}], "outside the timed segment (scenes 2 to 2)"),
    ([{"scene": 2, "at": 0, "name": "spin"}], "there is no move 'spin'"),
    ([{"scene": 2, "name": "bounce"}], "needs one of at"),
    ([{"scene": 2, "beat": 3, "name": "bounce"}], "beats 0 to 1"),
    ([{"scene": 2, "at": 0, "name": "bounce", "speed": 2}], "is like"),
])
def test_the_characters_moves(kit, cues, said):
    narration = ["Why?", "The field. | It pulls.", "So."]
    problem = brand.move_problem(cues, kit, (1, 1), narration)
    if said is None:
        assert problem is None
    else:
        assert said in problem


@pytest.mark.parametrize("segment, expected", [
    ((1, 1), [1, "handoff", 2, "ending", 3, "card"]),
    ((0, 2), ["handoff", 1, 2, 3, "ending", "card"]),
    (None, [1, 2, 3, "card"]),
])
def test_the_scenes_order_with_the_bookends(kit, segment, expected):
    assert brand.scene_order(3, 0, segment, kit) == expected
    with_credits = brand.scene_order(3, 1, segment, kit)
    assert with_credits[-2:] == ["closing", "card"]  # the kit's card after Odie's credits card


# ── 4. The made video's timeline: the bookends inserted, the clock moved, the voice track with them ──

def wav_of(seconds: float, rate: int = 24000) -> bytes:
    return make_wav(seconds, rate=rate, loud=0.5)


def level_at(wav: bytes, start: float, end: float) -> float:
    """The loudest sample between two moments, as a share of full scale."""
    with wave.open(io.BytesIO(wav)) as w:
        rate = w.getframerate()
        w.setpos(round(start * rate))
        frames = w.readframes(round((end - start) * rate))
    samples = array.array("h", frames)
    if not samples:
        return 0.0
    return max(abs(x) for x in samples) / 32767


def seconds_of(wav: bytes) -> float:
    with wave.open(io.BytesIO(wav)) as w:
        return w.getnframes() / w.getframerate()


def test_the_bookends_go_into_the_timeline_and_the_voice_track(kit):
    lengths = [6.0, 30.0, 2.0]
    wav, _starts = joined_wavs([wav_of(length) for length in lengths], gap=timeline.BREATH)
    clock = {"start": 6.5, "seconds": 30, "end": 36.5}
    laid = brand.lay_out(wav, lengths, [[0.0]] * 3, [timeline.BREATH] * 2, clock, (1, 1), 3, kit,
                         {"handoff": wav_of(1.0)})
    assert laid.order == [1, "handoff", 2, "ending", 3, "card"]
    assert laid.starts == [0.0, 6.5, 8.5, 39.0, 40.5, 43.0]
    assert laid.lengths == [6.0, 1.5, 30.0, 1.0, 2.0, 1.5]
    assert laid.clock == {"start": 8.5, "seconds": 30, "end": 38.5}  # moved by the handoff, not by the ending
    assert seconds_of(laid.wav) == pytest.approx(44.5, abs=0.001)  # quiet to the end, for the card's ting
    assert level_at(laid.wav, 6.6, 7.4) > 0.3  # the handoff's line
    assert level_at(laid.wav, 7.6, 8.4) == 0  # then quiet to its 1.5 s and the breath
    assert level_at(laid.wav, 8.6, 38.4) > 0.3  # the segment, after it
    assert level_at(laid.wav, 38.6, 40.4) == 0  # the ending's breath and quiet
    assert level_at(laid.wav, 40.6, 42.4) > 0.3  # the last scene
    assert level_at(laid.wav, 42.6, 44.5) == 0  # the card


def test_a_long_line_holds_the_handoff_and_is_logged(kit, caplog):
    lengths = [3.0, 10.0]
    wav, _starts = joined_wavs([wav_of(length) for length in lengths], gap=timeline.BREATH)
    with caplog.at_level(logging.WARNING, logger="odie.video"):
        laid = brand.lay_out(wav, lengths, [[0.0]] * 2, [timeline.BREATH], None, (1, 1), 2, kit,
                             {"handoff": wav_of(2.0)})
    assert laid.lengths[1] == 2.0 and not caplog.records  # held 0.5 s: no warning
    with caplog.at_level(logging.WARNING, logger="odie.video"):
        laid = brand.lay_out(wav, lengths, [[0.0]] * 2, [timeline.BREATH], None, (1, 1), 2, kit,
                             {"handoff": wav_of(3.0)})
    assert laid.lengths[1] == 3.0
    assert "holds its last frame 1.5 s" in caplog.text


def test_the_writers_cues_move_to_their_scenes_places():
    order = [1, "handoff", 2, "ending", 3, "card"]
    cues = [{"scene": 2, "at": 1, "name": "whoosh"}, {"scene": 3, "beat": 0, "name": "ting"}]
    assert brand.cues_in_order(cues, order) == [{"scene": 3, "at": 1, "name": "whoosh"},
                                                 {"scene": 5, "beat": 0, "name": "ting"}]


def test_the_bookends_sounds_play_at_their_moments(kit):
    timings = {"starts": [0.0, 6.5, 8.5, 39.0, 40.5, 43.0], "lengths": [6.0, 1.5, 30.0, 1.0, 2.0, 1.5],
               "beats": [[0.0]] * 6}
    placed = brand.bookend_sounds(kit, timings, [1, "handoff", 2, "ending", 3, "card"])
    assert [(one.name, one.start) for one in placed] == [("ting", 39.2), ("ting", 43.1)]
    assert all(one.path == kit.sounds["ting"] for one in placed)
    assert placed[1].seconds == pytest.approx(1.0) and not placed[1].cut  # the whole ting, before the video ends


def test_a_kit_sound_plays_instead_of_odies_and_adds_its_own_names(kit, tmp_path):
    timings = {"starts": [0.0], "lengths": [3.0], "beats": [[0.0]]}
    [ting] = sounds.resolve([{"scene": 1, "at": 0, "name": "ting"}], timings, kit_sounds=kit.sounds)
    assert ting.path == kit.sounds["ting"]
    [odies] = sounds.resolve([{"scene": 1, "at": 0, "name": "ting"}], timings)
    assert odies.path == sounds.path("ting")  # another video, without the kit: Odie's own
    bloop = brand_kit.chime_wav(tmp_path / "bloop.wav")
    assert sounds.cue_problem([{"scene": 1, "at": 0, "name": "bloop"}], ["Hi."], ("bloop",)) is None
    assert "no sound called 'bloop'" in sounds.cue_problem([{"scene": 1, "at": 0, "name": "bloop"}], ["Hi."])
    [own] = sounds.resolve([{"scene": 1, "at": 0, "name": "bloop"}], timings, kit_sounds={"bloop": bloop})
    assert own.path == bloop


# ── 5. The page: the kit loaded, frozen, drawn; the check ──

def page_with_kit(kit, body=PAGE, timed_video=True) -> tuple[str, dict, list]:
    """The finished page for the test reel: three scenes of 3, 6 and 2 s, the segment the second, with every
    bookend in, and its clock running from the segment's first word to its last."""
    order = brand.scene_order(3, 0, (1, 1), kit)
    starts = [0.0, 3.5, 5.5, 12.0, 13.5, 16.0]
    lengths = [3.0, 1.5, 6.0, 1.0, 2.0, 1.5]
    timings = {"starts": starts, "lengths": lengths, "beats": [[0.0]] * 6,
               "timed": {"start": 5.5, "seconds": 6, "end": 11.5}}
    script = brand.page_script(brand.Branded(kit, VARS), timed_video=timed_video)
    html = page.assemble(body, timings, size=timeline.VERTICAL, brand_script=script)
    return html, timings, order


async def frame_png(tab, seconds: float) -> Image.Image:
    await tab.eval(f"__frame({seconds})")
    return Image.open(io.BytesIO(await tab.shot("png"))).convert("RGB")


@needs_browser
async def test_the_page_draws_the_kit_around_the_writers_scenes(kit, tmp_path):
    html, _timings, order = page_with_kit(kit)
    browser = Browser(tmp_path / "p", BIN, extra_args=RENDER_ARGS)
    try:
        async with browser.sealed_page(html, 1080, 1920) as tab:
            assert tab.errors == []
            assert await tab.eval("Video.order()") == order
            question = await frame_png(tab, 1.0)
            handoff = await frame_png(tab, 4.0)
            segment = await frame_png(tab, 8.0)
            ending = await frame_png(tab, 12.5)
            card = await frame_png(tab, 16.5)
            seen = await tab.eval("Brand.seen()")
    finally:
        await browser.close()
    corner = (60, 60)
    lantern = (1080 - 200, 1920 - 340 - 140)
    assert near(question.getpixel(corner), brand_kit.BACKGROUND)  # the kit's background, under the writer's scene
    assert near(question.getpixel(lantern), brand_kit.BACKGROUND)  # no lantern before the segment
    assert near(segment.getpixel(lantern), brand_kit.LANTERN)  # drawn by the stage through the segment
    assert near(segment.getpixel((290, 550)), "#F6E05E")  # the writer's own box, over the background
    assert near(handoff.getpixel((300, 960)), brand_kit.HANDOFF)
    assert near(ending.getpixel((300, 960)), brand_kit.ENDING)
    assert near(card.getpixel((300, 960)), brand_kit.CARD)
    assert near(ending.getpixel(lantern), brand_kit.BACKGROUND)  # the lantern only in the segment
    assert seen[-1]["left"] == pytest.approx(6 * (11.5 - 8.0) / 6, abs=0.01)  # its timer fed by the segment clock
    assert seen[-1]["t"] == pytest.approx(8.0 - 5.5, abs=0.001)  # seconds into the segment


@needs_browser
async def test_the_kit_cant_be_changed_from_the_page(kit, tmp_path):
    attempt = """<script>
    try { window.Brand = {}; } catch (e) {}
    try { Brand.palette.background = "#000000"; } catch (e) {}
    try { Brand.lantern.draw = function () {}; } catch (e) {}
    Video.scenes([{draw(t, s) {}}, {timed_start: true, timed_end: true, draw(t, s) {}}, {draw(t, s) {}}]);
    </script>"""
    html, _timings, _order = page_with_kit(kit, body=attempt)
    browser = Browser(tmp_path / "p", BIN, extra_args=RENDER_ARGS)
    try:
        async with browser.sealed_page(html, 1080, 1920) as tab:
            assert await tab.eval("Brand.palette.background") == brand_kit.BACKGROUND
            assert await tab.eval("typeof Brand.lantern.draw === 'function' && Object.isFrozen(Brand.lantern)")
            assert await tab.eval("Object.isFrozen(Brand) && typeof Brand.bookend === 'function'")
    finally:
        await browser.close()


@needs_browser
async def test_the_check_accepts_a_page_that_draws_around_the_kit(kit, tmp_path):
    browser = Browser(tmp_path / "p", BIN, extra_args=RENDER_ARGS)
    try:
        good = await brand.check(PAGE, NARRATION, browser, brand.Branded(kit, VARS), size=timeline.VERTICAL,
                                 timed_seconds=6)
        painted = await brand.check(PAGE.replace('s.text("q"', 's.ctx.fillStyle = "#000"; '
                                                 's.ctx.fillRect(0, 0, s.W, s.H); s.text("q"'),
                                    NARRATION, browser, brand.Branded(kit, VARS), size=timeline.VERTICAL,
                                    timed_seconds=6)
        three_bg = await brand.check(PAGE.replace('s.text("b"', 's.three.scene.background = new THREE.Color(0); '
                                                  's.text("b"'),
                                     NARRATION, browser, brand.Branded(kit, VARS), size=timeline.VERTICAL,
                                     timed_seconds=6)
        moved_out = await brand.check(PAGE.replace("{scene: 2, at: 0.5", "{scene: 1, at: 0.5"), NARRATION, browser,
                                      brand.Branded(kit, VARS), size=timeline.VERTICAL, timed_seconds=6)
        unmarked = await brand.check(PAGE.replace("timed_start: true, timed_end: true, ", ""), NARRATION, browser,
                                     brand.Branded(kit, VARS), size=timeline.VERTICAL, timed_seconds=6)
    finally:
        await browser.close()
    assert good.problem is None and good.segment == (1, 1)
    assert painted.problem.startswith("Scene 1 covers the whole stage")
    assert three_bg.problem.startswith("Scene 3 covers the whole stage")
    assert "outside the timed segment" in moved_out.problem
    assert "Mark the 6-second segment" in unmarked.problem


@needs_browser
async def test_a_kit_that_breaks_while_drawing_is_the_kits_problem_not_the_writers(store, tmp_path):  # noqa: F811
    broken = brand_kit.SCRIPT.replace("ctx.fillStyle = colours[name];", "throw new Error('no such scene');")
    brand_kit.make_kit(brand.skills_folder(), script=broken)
    kit = brand.find("test-channel")
    browser = Browser(tmp_path / "p", BIN, extra_args=RENDER_ARGS)
    try:
        with pytest.raises(brand.KitProblem, match="brand kit: no such scene"):
            await brand.check(PAGE, NARRATION, browser, brand.Branded(kit, VARS), size=timeline.VERTICAL,
                              timed_seconds=6)
    finally:
        await browser.close()


@needs_browser
async def test_a_kit_missing_a_function_it_needs_doesnt_load(store, tmp_path):  # noqa: F811
    brand_kit.make_kit(brand.skills_folder(), script=brand_kit.SCRIPT.replace("bookend: function", "bookends: function"))
    kit = brand.find("test-channel")
    browser = Browser(tmp_path / "p", BIN, extra_args=RENDER_ARGS)
    try:
        with pytest.raises(brand.KitProblem, match="Brand.bookend isn't a function"):
            await brand.check(PAGE, NARRATION, browser, brand.Branded(kit, VARS), size=timeline.VERTICAL,
                              timed_seconds=6)
    finally:
        await browser.close()


async def test_the_writer_is_refused_a_page_that_changes_the_kit_before_anything_is_drawn(kit):
    judged = await writer.checked_submission(NARRATION, PAGE.replace("<script>", "<script>Brand.x = 1;"), object(),
                                             kit=kit, kit_vars=VARS)
    assert "Brand is fixed" in judged.problem
    judged = await writer.checked_submission(NARRATION, PAGE, object(), kit=kit, kit_vars={})
    assert "Give submit_video's brand" in judged.problem


# ── 6. Acceptance: two videos with the same kit; only the middle differs ──

@pytest.fixture
def making(store, monkeypatch, kit):  # noqa: F811
    """kind.make_video with a stand-in voice (each text spoken for the seconds the test gives it), the real fit,
    render, mix, mux and probe, and a low frame rate."""
    monkeypatch.setitem(jobs.hooks, "store", store)
    monkeypatch.setattr(kind.timeline, "FPS", 2)
    spoken = {}

    async def stand_in_narrate(store, narration, voice_name="", transport=None, style=""):
        lengths = [spoken[text] for text in narration]
        wav, _starts = joined_wavs([wav_of(length) for length in lengths], gap=timeline.BREATH)
        return wav, lengths, [[0.0] for _ in lengths]

    monkeypatch.setattr(kind, "narrate", stand_in_narrate)
    return spoken


def episode(kit, slug: str, narration: list[str], body: str, intro: str):
    job = make_job(slug=slug)
    job.data.update({"narration": narration, "body": body, "aspect": "vertical", "timed_scenes": [1, 1],
                     "timed_segment": {"seconds": 6, "tolerance": 0.1}, "cues": [],
                     "brand_vars": {"intro": intro}})
    job.data["brand_kit"] = brand.snapshot(kit, job.folder)
    return job


def card_audio(job) -> bytes:
    """The mixed sound of the video's last 1.5 s: the kit's card, its ting and nothing else."""
    mixed = (job.folder / "mix.wav").read_bytes()
    with wave.open(io.BytesIO(mixed)) as w:
        rate = w.getframerate()
        total = w.getnframes()
        w.setpos(total - round(1.5 * rate))
        return w.readframes(round(1.5 * rate))


async def drawn(page_html: str, moments: list[float], tmp_path, name: str) -> list[Image.Image]:
    browser = Browser(tmp_path / name, BIN, extra_args=RENDER_ARGS)
    try:
        async with browser.sealed_page(page_html, 1080, 1920) as tab:
            return [await frame_png(tab, seconds) for seconds in moments]
    finally:
        await browser.close()


def timings_of(page_html: str) -> dict:
    return json.loads(page_html.split("<script>window.__timings = ", 1)[1].split(";</script>", 1)[0])


@needs_browser
async def test_two_videos_with_one_kit_share_every_branded_frame_and_sound(making, kit, tmp_path):
    other_page = """<script>
    Video.scenes([
      {draw(t, s) { s.ctx.fillStyle = "#E53E3E"; s.ctx.fillRect(200, 600, 400, 200); }},
      {timed_start: true, timed_end: true, draw(t, s) { s.text("w", "Waves", {size: 96, y: 500}); }},
      {draw(t, s) { s.ctx.strokeStyle = "#FFFFFF"; s.ctx.strokeRect(300, 300, 480, 480); }},
    ]);
    </script>"""
    first_words = ["Why do magnets stick?", "The domains line up.", "So it sticks."]
    second_words = ["Why do waves break?", "The sea floor rises.", "On every shore."]
    making.update({first_words[0]: 3.0, first_words[1]: 6.3, first_words[2]: 2.0, "Here is the short version.": 1.2,
                   second_words[0]: 4.0, second_words[1]: 6.3, second_words[2]: 2.0, "Now, the quick answer.": 1.0})
    first = episode(kit, "magnets", first_words, PAGE, "Here is the short version.")
    second = episode(kit, "waves", second_words, other_page, "Now, the quick answer.")
    browser = Browser(tmp_path / "make", BIN, extra_args=RENDER_ARGS)
    try:
        first_mp4 = await kind.make_video(first, browser, transport=None)
        second_mp4 = await kind.make_video(second, browser, transport=None)
    finally:
        await browser.close()
    for mp4 in (first_mp4, second_mp4):
        info = await encode.probe(mp4)
        assert (info["width"], info["height"]) == (1080, 1920)

    first_html = (first.folder / "page.html").read_text(encoding="utf-8")
    second_html = (second.folder / "page.html").read_text(encoding="utf-8")
    first_timings = timings_of(first_html)
    second_timings = timings_of(second_html)
    assert first_timings["lengths"][1] == second_timings["lengths"][1] == 1.5  # the handoff, both lines shorter
    assert first_timings["lengths"][3:] == second_timings["lengths"][3:]  # the ending, the last scene, the card

    def moments(timings: dict) -> list[float]:
        starts = timings["starts"]
        return [starts[1] + 0.2, starts[1] + 1.2, starts[2] + 0.1, starts[3] + 0.5, starts[5] + 0.3, starts[5] + 1.4]

    first_frames = await drawn(first_html, moments(first_timings), tmp_path, "a")
    second_frames = await drawn(second_html, moments(second_timings), tmp_path, "b")
    for name, one, two in zip(["handoff", "handoff held", "segment", "ending", "card", "card held"], first_frames,
                              second_frames):
        if name == "segment":  # the writers' middles differ; the lantern on it doesn't
            box = (1080 - 320, 1920 - 340 - 260, 1080 - 80, 1920 - 340 - 20)
            assert one.crop(box).tobytes() == two.crop(box).tobytes(), name
            continue
        assert one.tobytes() == two.tobytes(), name  # pixel for pixel
    assert first_frames[2].tobytes() != second_frames[2].tobytes()  # only the middle story changes
    lantern = (1080 - 200, 1920 - 340 - 140)
    assert near(first_frames[2].getpixel(lantern), brand_kit.LANTERN)  # and the lantern is there in both
    assert near(first_frames[3].getpixel((300, 960)), brand_kit.ENDING)

    first_card = card_audio(first)
    assert max(abs(x) for x in array.array("h", first_card)) > 1000  # the ting rings in it, not silence
    assert first_card == card_audio(second)  # the card's ting, sample for sample
    assert first.data["brand_kit"]["version"] == second.data["brand_kit"]["version"] == kit.version
