"""Vertical (9:16) explainer videos for reels, and no lead-in.

A job's aspect ("landscape", the default, or "vertical") sets the stage: 1920 x 1080 or 1080 x 1920, from the
timeline's size table, through the page check, the render tabs, the kit and the finished file. A vertical page gets
Instagram's safe area as CSS variables (and s.safe), and the writer gets the vertical composition rules. In both
aspects the video opens on its first card at t = 0 and the narration starts at once: a scene's quiet before its first
word is cut to at most 0.2 s. A landscape job draws the same frames, at the same size, through the same encoder as
before."""
import io
import json
import subprocess
import wave

import httpx
import pytest
from PIL import Image

from odie.browser import RENDER_ARGS, find
from odie.browser.engine import Browser
from odie.making import jobs
from odie.store.db import Store
from odie.video import encode, kind, narrate, page, render, timeline, writer
from tests.test_media import make_wav
from tests.test_video_jobs import make_job
from tests.test_video_tool import load_tools

tools = load_tools()
BIN = find.installed()
needs_browser = pytest.mark.skipif(BIN is None, reason="no Chrome, Edge, Chromium or Brave here")

# Today's page style, word for word: a landscape page must keep it.
LANDSCAPE_STYLE = "html, body { margin: 0; background: #000; overflow: hidden; width: 1920px; height: 1080px; }"

# A two-scene page: scene 1 is the question card (an amber panel filling the stage, the question on it), scene 2
# anything else (a slate stage with one line).
QUESTION_PAGE = """<script>
Video.scenes([
  {draw(t, s) {
    s.ctx.fillStyle = "#FFB020"; s.ctx.fillRect(0, 0, s.W, s.H);
    s.text("q", "Why is ice slippery?", {size: 72, weight: 700, color: "#12161C"});
  }},
  {draw(t, s) {
    s.ctx.fillStyle = "#12161C"; s.ctx.fillRect(0, 0, s.W, s.H);
    s.text("a", "A thin wet skin.", {size: 72});
  }},
]);
</script>"""


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    return s


# ── 1. The aspect, from the words the chat used ──

@pytest.mark.parametrize("said", ["vertical", "portrait", "reel", "insta", "shorts", "9:16", " Reel ", "INSTA"])
def test_the_words_for_a_reel_mean_vertical(said):
    assert tools.aspect_as_given(said) == "vertical"


@pytest.mark.parametrize("said", ["", None, "landscape", "wide", "16:9", "square", "cinema"])
def test_anything_else_means_landscape(said):
    assert tools.aspect_as_given(said) == "landscape"


@pytest.fixture
def queue(store, monkeypatch):
    """make_video with a browser said to be present and jobs.submit replaced by a recorder; returns the jobs."""
    monkeypatch.setitem(jobs.hooks, "store", store)
    monkeypatch.setattr(find, "browser_binary", lambda: "/Applications/Some Browser")
    submitted = []

    def record(job):
        submitted.append(job)
        return len(submitted)

    monkeypatch.setattr(jobs, "submit", record)
    return submitted


async def test_make_video_keeps_the_aspect_on_the_job_and_out_of_the_brief(queue):
    out = await tools.make_video("Why ice is slippery", brief="One minute, for the account.", aspect="insta")
    assert "result" in out
    assert "result" in await tools.make_video("Why ice is slippery")
    reel, wide = queue
    assert reel.data["aspect"] == "vertical" and wide.data["aspect"] == "landscape"
    assert "vertical" not in reel.brief and "insta" not in reel.brief


def test_a_job_without_an_aspect_or_with_an_unknown_one_is_landscape():
    job = make_job()
    assert kind.aspect_of(job) == "landscape"
    job.data["aspect"] = "vertical"
    assert kind.aspect_of(job) == "vertical"
    job.data["aspect"] = "square"
    assert kind.aspect_of(job) == "landscape"


# ── 2. The size table ──

def test_the_timeline_sizes():
    assert timeline.size_of("vertical") == timeline.VERTICAL == (1080, 1920)
    assert timeline.size_of("landscape") == timeline.LANDSCAPE == (1920, 1080)
    assert timeline.size_of("") == timeline.size_of("square") == (1920, 1080)


# ── 3. The page and the kit at the job's size ──

def test_a_landscape_page_keeps_todays_style_and_a_vertical_one_is_tall_with_the_safe_area():
    assert page.base_style(timeline.LANDSCAPE) == LANDSCAPE_STYLE
    tall = page.base_style(timeline.VERTICAL)
    assert "width: 1080px; height: 1920px;" in tall
    assert "--safe-top: 140px; --safe-bottom: 340px; --safe-side: 72px;" in tall
    assert "--safe" not in page.base_style(timeline.LANDSCAPE)


@needs_browser
async def test_the_kit_draws_on_the_jobs_stage_and_tells_the_safe_area(tmp_path):
    timings = {"starts": [0.0, 1.5], "lengths": [1.0, 1.0], "beats": [[0.0], [0.0]]}
    browser = Browser(tmp_path / "p", BIN, extra_args=RENDER_ARGS)
    try:
        html = page.assemble(QUESTION_PAGE, timings, size=timeline.VERTICAL)
        async with browser.sealed_page(html, 1080, 1920) as tab:
            assert await tab.eval("[Video.W, Video.H]") == [1080, 1920]
            assert await tab.eval("Video.safe") == {"top": 140, "bottom": 340, "side": 72}
            css = "getComputedStyle(document.documentElement).getPropertyValue('--safe-bottom').trim()"
            assert await tab.eval(css) == "340px"
            assert await tab.eval("__frame(0)") is True
            assert tab.errors == []
        async with browser.sealed_page(page.assemble(QUESTION_PAGE, timings), 1920, 1080) as tab:
            assert await tab.eval("[Video.W, Video.H]") == [1920, 1080]
            assert await tab.eval("Video.safe") == {"top": 0, "bottom": 0, "side": 0}
    finally:
        await browser.close()


# ── 4. The pipeline end to end: a vertical reel, and a landscape video as before ──

def wav_of(seconds: float) -> bytes:
    return make_wav(seconds, rate=24000)


@pytest.fixture
def making(store, monkeypatch):
    """kind.make_video with a stand-in voice (scene lengths as given), the real render, mux and probe, and a low
    frame rate so a minute renders in seconds (frames stay time-based: fps x seconds)."""
    monkeypatch.setitem(jobs.hooks, "store", store)
    monkeypatch.setattr(kind.timeline, "FPS", 2)
    spoken = {}

    async def stand_in_narrate(store, narration, voice_name="", transport=None, style=""):
        lengths = spoken["lengths"]
        joined, _ = joined_wavs([wav_of(length) for length in lengths], gap=timeline.BREATH)
        return joined, lengths, [[0.0] for _ in lengths]

    monkeypatch.setattr(kind, "narrate", stand_in_narrate)
    return spoken


def joined_wavs(parts: list[bytes], gap: float) -> tuple[bytes, list[float]]:
    from odie import media
    return media.join_wavs(parts, gap_ms=int(gap * 1000))


def first_frame(mp4) -> Image.Image:
    out = mp4.parent / "first.png"
    subprocess.run([encode.ffmpeg(), "-v", "error", "-y", "-i", str(mp4), "-frames:v", "1", str(out)], check=True)
    return Image.open(out).convert("RGB")


def near(colour: tuple[int, int, int], hex_colour: str) -> bool:
    wanted = tuple(int(hex_colour[i:i + 2], 16) for i in (1, 3, 5))
    return all(abs(a - b) <= 12 for a, b in zip(colour, wanted))


@needs_browser
async def test_a_vertical_job_renders_a_minute_at_1080_by_1920_opening_on_the_question_card(making, tmp_path):
    making["lengths"] = [4.0, 55.5]  # 4 + 0.5 breath + 55.5 = 60 s
    job = make_job(slug="ice")
    job.data.update({"narration": ["Why is ice slippery?", "A thin wet skin."], "body": QUESTION_PAGE,
                     "aspect": "vertical"})
    browser = Browser(tmp_path / "p", BIN, extra_args=RENDER_ARGS)
    try:
        mp4 = await kind.make_video(job, browser, transport=None)
    finally:
        await browser.close()
    info = await encode.probe(mp4)
    assert (info["width"], info["height"]) == (1080, 1920)
    assert 62.0 <= info["seconds"] <= 64.0  # a reel is a one-minute video: 60 s of narration after the silent card
    frame = first_frame(mp4)
    assert frame.size == (1080, 1920)
    assert near(frame.getpixel((540, 200)), "#FFB020")  # the question card, from the very first frame
    assert near(frame.getpixel((540, 1800)), "#FFB020")


@needs_browser
async def test_a_landscape_job_renders_at_1920_by_1080_as_before(making, tmp_path):
    making["lengths"] = [1.0, 1.0]
    job = make_job(slug="wide")
    job.data.update({"narration": ["Why is ice slippery?", "A thin wet skin."], "body": QUESTION_PAGE})
    browser = Browser(tmp_path / "p", BIN, extra_args=RENDER_ARGS)
    try:
        mp4 = await kind.make_video(job, browser, transport=None)
    finally:
        await browser.close()
    info = await encode.probe(mp4)
    assert (info["width"], info["height"]) == (1920, 1080)
    assert near(first_frame(mp4).getpixel((100, 100)), "#FFB020")


class SizeRecorder:
    """A stand-in browser that keeps the size of every sealed tab asked for, then refuses to draw."""

    def __init__(self):
        self.sizes = []

    def sealed_page(self, html, width, height):
        self.sizes.append((width, height))
        raise RuntimeError("stop here")


async def test_the_render_tabs_and_the_page_check_open_at_the_jobs_size():
    for size in (timeline.LANDSCAPE, timeline.VERTICAL):
        recorder = SizeRecorder()
        with pytest.raises(RuntimeError):
            await render.render_range(recorder, "<html>", None, 2, 0, 1, render.Counter(1, None), size=size)
        with pytest.raises(RuntimeError):
            await page.check_with_cues(QUESTION_PAGE, ["One.", "Two."], recorder, size=size)
        assert recorder.sizes == [size, size]


async def test_the_encoder_is_asked_exactly_as_before(tmp_path, monkeypatch):
    asked = []

    async def recorded(*command, **kwargs):
        asked.append(list(command))
        raise RuntimeError("stop here")

    monkeypatch.setattr(encode.asyncio, "create_subprocess_exec", recorded)
    with pytest.raises(RuntimeError):
        async with encode.Segment(tmp_path / "s.mp4", 30):
            pass
    assert asked[0][1:] == ["-y", "-loglevel", "error", "-f", "image2pipe", "-c:v", "mjpeg", "-framerate", "30", "-i",
                            "-", "-vf", encode.TO_HD_COLOURS, "-c:v", "libx264", "-preset", "medium", "-crf", "18",
                            "-pix_fmt", "yuv420p", str(tmp_path / "s.mp4")]


async def test_a_finished_file_at_the_wrong_size_is_refused(making, monkeypatch, tmp_path):
    making["lengths"] = [4.0, 55.5]  # a reel is a one-minute video: a minute of narration, so it fits as it is

    async def tiny_render(browser, body, timings, folder, fps, tabs, progress=None, assets_script="",
                          credits_script="", size=None):
        path = folder / "segment-0.mp4"
        async with encode.Segment(path, fps=2) as segment:
            buffer = io.BytesIO()
            Image.new("RGB", (1920, 1080), "red").save(buffer, "JPEG")
            for _ in range(5):
                await segment.add(buffer.getvalue())
        return [path]

    monkeypatch.setattr(kind, "render", tiny_render)
    job = make_job(slug="wrong")
    job.data.update({"narration": ["One.", "Two."], "body": QUESTION_PAGE, "aspect": "vertical"})
    with pytest.raises(encode.EncodeError, match="1920x1080, not 1080x1920"):
        await kind.make_video(job, object(), transport=None)


# ── 5. The writer: the vertical rules, and no countdown in either aspect ──

def test_the_writer_gets_the_vertical_rules_only_for_a_vertical_video():
    tall = writer.instruction_for("vertical")
    wide = writer.instruction_for("landscape")
    assert tall.startswith(wide)
    for rule in ("1080 × 1920", "never two columns", "64 px", "20 characters", "stacked", "--safe-bottom",
                 "full-bleed"):
        assert rule in tall, rule
    assert "1080 × 1920" not in wide


def test_no_countdown_and_the_first_frame_is_the_opening_card_in_both_aspects():
    for aspect in ("landscape", "vertical"):
        text = writer.instruction_for(aspect)
        assert "No countdown" in text and "the first frame" in text


async def test_a_vertical_videos_page_is_checked_at_1080_by_1920(tmp_path, monkeypatch):
    seen = []

    async def check(body, narration, browser, assets_script="", size=timeline.LANDSCAPE, one_minute=False):
        seen.append(size)
        return page.CheckResult(problem=None)

    monkeypatch.setattr(page, "check_with_cues", check)
    judged = await writer.checked_submission(["One.", "Two."], QUESTION_PAGE, object(), size=timeline.VERTICAL)
    assert judged.problem is None and seen == [timeline.VERTICAL]


async def test_the_writing_step_tells_the_writer_the_aspect(store, monkeypatch, tmp_path):
    asked = {}

    async def stand_in_write(topic, minutes, brief, folder, turn, browser, listing="", assets_script="",
                             aspect="landscape", one_minute=False):
        asked["aspect"] = aspect
        return writer.Written(title="Ice", narration=["One.", "Two."], body="<div></div>")

    monkeypatch.setattr(kind.writer, "write", stand_in_write)
    job = make_job(slug="reel")
    job.data = {"aspect": "vertical"}
    await kind.write(job, turn=None, browser=object())
    assert asked == {"aspect": "vertical"}


# ── 6. The narration starts at once ──

def quiet_then_speech(quiet: float, speech: float) -> bytes:
    from odie import media
    joined, _ = media.join_wavs([make_wav(quiet, loud=0.0), make_wav(speech)], gap_ms=0)
    return joined


def wav_seconds(wav: bytes) -> float:
    with wave.open(io.BytesIO(wav)) as w:
        return w.getnframes() / w.getframerate()


def lead_seconds(wav: bytes) -> float:
    return narrate.quiet_at_start(wav)


def voice_saying(pieces: dict[str, bytes]) -> httpx.MockTransport:
    """Odie's local voice, answering each text with the WAV given for it."""
    def handler(request):
        text = json.loads(request.content)["text"]
        return httpx.Response(200, content=pieces[text])
    return httpx.MockTransport(handler)


async def test_a_scenes_quiet_before_its_first_word_is_cut_to_a_fifth_of_a_second(store):
    pieces = {"Why?": quiet_then_speech(0.45, 1.0), "Because.": quiet_then_speech(0.1, 1.0),
              "First": quiet_then_speech(0.4, 0.5), "then.": quiet_then_speech(0.3, 0.5)}
    wav, lengths, beats = await narrate.narrate(store, ["Why?", "Because.", "First | then."],
                                                transport=voice_saying(pieces))
    assert abs(lead_seconds(wav) - 0.2) <= 0.011  # the video's first word at 0.2 s, not 0.45 s
    assert abs(lengths[0] - 1.2) <= 0.011  # 0.45 s of quiet cut to 0.2
    assert abs(lengths[1] - 1.1) <= 0.011  # 0.1 s is under the cap: kept
    assert abs(lengths[2] - (0.7 + 0.8)) <= 0.011  # the scene's first phrase cut; the pause before "then." kept
    assert abs(beats[2][1] - 0.7) <= 0.011


def test_quiet_is_measured_and_cut_only_down_to_the_cap():
    assert abs(narrate.quiet_at_start(quiet_then_speech(0.45, 1.0)) - 0.45) <= 0.011
    assert abs(wav_seconds(narrate.lead_cut(quiet_then_speech(0.45, 1.0))) - 1.2) <= 0.011
    short = quiet_then_speech(0.1, 1.0)
    assert narrate.lead_cut(short) == short
    silent = make_wav(1.0, loud=0.0)
    assert narrate.lead_cut(silent) == silent  # nothing said: nothing to start on
