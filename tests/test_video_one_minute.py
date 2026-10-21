"""One-minute videos (odie.video.minute): a reel, or any video asked for at one minute, has its narration fitted to
exactly 60 s, opens silent on the question card for COLD_OPEN seconds, and gives the page a narration clock (60 at the
first word, 0 at the last) for the countdown character; after 0 comes the chime and a hard cut. A 2-6 minute video
keeps its free length and today's pipeline."""
import io
import json
import wave

import pytest

from odie.browser import RENDER_ARGS, find
from odie.browser.engine import Browser
from odie.making import jobs
from odie.video import encode, kind, minute, page, sounds, timeline, writer
from tests.test_media import make_wav
from tests.test_video_jobs import make_job
from tests.test_video_tool import load_tools
from tests.test_video_vertical import first_frame, joined_wavs, near, store  # noqa: F401 (store is a fixture)

tools = load_tools()
BIN = find.installed()
needs_browser = pytest.mark.skipif(BIN is None, reason="no Chrome, Edge, Chromium or Brave here")

# Scene 1 is the question card (an amber stage with the question); it draws a red timer box at the top right, with the
# seconds left in it, only while the narration clock runs. Scene 2 is a slate stage with the same timer.
CLOCK_PAGE = """<script>
function timer(s) {
  const left = s.left();
  if (left === null) { return; }
  s.ctx.fillStyle = "#E0182D"; s.ctx.fillRect(s.W - 300, 200, 220, 160);
  s.text("timer", String(Math.ceil(left)), {x: s.W - 190, y: 280, size: 96, weight: 800});
}
Video.scenes([
  {draw(t, s) {
    s.ctx.fillStyle = "#FFB020"; s.ctx.fillRect(0, 0, s.W, s.H);
    s.text("q", "Why is ice slippery?", {size: 72, weight: 700, color: "#12161C"});
    timer(s);
  }},
  {draw(t, s) {
    s.ctx.fillStyle = "#12161C"; s.ctx.fillRect(0, 0, s.W, s.H);
    s.text("a", "A thin wet skin.", {size: 72});
    timer(s);
  }},
]);
</script>"""


def wav_of(seconds: float) -> bytes:
    return make_wav(seconds, rate=24000)


def seconds_of(wav: bytes) -> float:
    with wave.open(io.BytesIO(wav)) as w:
        return w.getnframes() / w.getframerate()


# ── 1. The mode: one minute only when asked ──

@pytest.mark.parametrize(("minutes", "aspect", "meant"), [
    (1, "landscape", True), (1, "vertical", True), (2, "vertical", True),
    (2, "landscape", False), (3, "landscape", False), (6, "landscape", False)])
def test_one_minute_is_a_mode_for_a_minute_or_a_reel(minutes, aspect, meant):
    assert minute.is_one_minute(minutes, aspect) is meant


async def test_a_reel_is_queued_as_a_one_minute_job_and_a_wide_three_minute_one_as_asked(store, monkeypatch):
    monkeypatch.setitem(jobs.hooks, "store", store)
    monkeypatch.setattr(find, "browser_binary", lambda: "/Applications/Some Browser")
    queued = []
    monkeypatch.setattr(jobs, "submit", lambda job: queued.append(job) or len(queued))
    assert "result" in await tools.make_video("Why ice is slippery", aspect="insta")
    assert "result" in await tools.make_video("How tides work", minutes=3)
    reel, wide = queued
    assert reel.minutes == 1 and reel.data["aspect"] == "vertical"
    assert wide.minutes == 3 and wide.data["aspect"] == "landscape"


# ── 2. The clamp: the voice fitted to exactly 60 s, within what still sounds like it ──

@pytest.mark.parametrize(("spoken", "tempo"), [(60.0, 1.0), (66.0, 1.1), (54.0, 0.9), (72.0, 1.2), (49.0, 0.817)])
def test_the_tempo_that_fits_a_narration_into_a_minute(spoken, tempo):
    assert minute.tempo_for(spoken) == pytest.approx(tempo, abs=0.001)


@pytest.mark.parametrize("spoken", [80.0, 40.0])
def test_a_narration_too_far_from_a_minute_is_not_stretched(spoken):
    assert minute.tempo_for(spoken) is None


async def test_the_narration_is_fitted_to_60_seconds_and_its_times_with_it(tmp_path):
    lengths = [6.0, 30.0, 29.0]  # 65 s of speech with the two 0.5 s breaths: 66 s, sped up 1.1 times
    wav, _ = joined_wavs([wav_of(length) for length in lengths], gap=timeline.BREATH)
    fitted = await minute.fit(wav, lengths, [[0.0], [0.0, 11.0], [0.0]], tmp_path)
    assert seconds_of(fitted.wav) == pytest.approx(60.0, abs=0.05)
    assert fitted.seconds == pytest.approx(seconds_of(fitted.wav), abs=0.001)
    assert fitted.lengths == pytest.approx([6.0 / 1.1, 30.0 / 1.1, 29.0 / 1.1], abs=0.05)
    assert fitted.beats[1][1] == pytest.approx(11.0 / 1.1, abs=0.05)
    assert fitted.breath == pytest.approx(0.5 / 1.1, abs=0.01)
    starts, total = timeline.scene_starts(fitted.lengths, fitted.breath)
    assert total == pytest.approx(fitted.seconds, abs=0.05)  # the page's scenes end with the fitted voice


async def test_a_narration_far_from_a_minute_fails_the_video_in_words(tmp_path):
    lengths = [40.0, 40.0]
    wav, _ = joined_wavs([wav_of(length) for length in lengths], gap=timeline.BREATH)
    with pytest.raises(minute.DoesntFit) as caught:
        await minute.fit(wav, lengths, [[0.0], [0.0]], tmp_path)
    assert "80.5 s" in str(caught.value) and "one minute" in str(caught.value)
    assert issubclass(minute.DoesntFit, encode.EncodeError)  # told in the chat like any making error


def test_the_writer_is_held_to_a_minutes_words():
    assert minute.words_problem(["word " * 140]) is None
    assert "90 words" in minute.words_problem(["word " * 90])
    assert "200 words" in minute.words_problem(["word " * 100, "word | " * 100])  # the "|" marks are not words


# ── 3. The cold open and the clock ──

def test_the_clock_timings_open_silent_and_end_with_the_blink():
    timings = {"starts": [0.0, 6.5], "lengths": [6.0, 53.5], "beats": [[0.0], [0.0]]}
    got = minute.on_the_clock(timings, narrated_scenes=2)
    assert got["starts"] == [minute.COLD_OPEN, 6.5 + minute.COLD_OPEN]
    assert got["lengths"] == [6.0, 53.5 + minute.END]
    assert got["clock"] == {"start": minute.COLD_OPEN, "length": 60.0}  # the narration's length, never the video's


def test_a_credits_card_after_the_clock_moves_with_it():
    timings = {"starts": [0.0, 6.5, 60.5], "lengths": [6.0, 53.5, 3.0], "beats": [[0.0], [0.0], [0.0]]}
    got = minute.on_the_clock(timings, narrated_scenes=2)
    assert got["starts"][2] == 60.5 + minute.COLD_OPEN + minute.END and got["lengths"][2] == 3.0
    assert got["clock"]["length"] == 60.0


def test_the_audio_is_framed_silent_before_and_after():
    framed = minute.framed(wav_of(60.0))
    assert seconds_of(framed) == pytest.approx(minute.COLD_OPEN + 60.0 + minute.END, abs=0.001)


@needs_browser
async def test_the_kit_reads_the_clock_from_the_timings(tmp_path):
    timings = minute.on_the_clock({"starts": [0.0, 6.5], "lengths": [6.0, 53.5], "beats": [[0.0], [0.0]]}, 2)
    html = page.assemble(CLOCK_PAGE, timings, size=timeline.VERTICAL)
    browser = Browser(tmp_path / "p", BIN, extra_args=RENDER_ARGS)
    try:
        async with browser.sealed_page(html, 1080, 1920) as tab:
            at = await tab.eval(f"[Video.clockAt(0), Video.clockAt({minute.COLD_OPEN}), Video.clockAt(32.5), "
                                f"Video.clockAt({minute.COLD_OPEN + 60}), Video.clockAt(63.4)]")
            assert at == [None, 60, 30, 0, 0]
            shown = {}
            for t in (1.0, minute.COLD_OPEN, 40.0, minute.COLD_OPEN + 60):
                await tab.eval(f"window.__frame({t})")
                shown[t] = await tab.eval('(function () { const el = document.getElementById("v-timer"); '
                                          'return el && el.style.visibility !== "hidden" ? el.textContent : null; })()')
            assert shown == {1.0: None, minute.COLD_OPEN: "60", 40.0: "23", minute.COLD_OPEN + 60: "0"}
    finally:
        await browser.close()


def test_a_page_without_a_clock_has_none():
    assert "clock" not in page.estimated_timings(["One.", "Two."])


# ── 4. The writer is told, only for a one-minute video ──

def test_the_writer_gets_the_one_minute_rules_only_for_a_one_minute_video():
    assert writer.instruction_for("landscape") == writer.INSTRUCTION
    plain_reel = writer.instruction_for("vertical")
    minute_reel = writer.instruction_for("vertical", one_minute=True)
    assert minute_reel.startswith(plain_reel.rstrip()) and minute_reel.endswith(writer.MINUTE_RULES)
    assert "s.left()" in writer.MINUTE_RULES and "60" in writer.MINUTE_RULES
    assert writer.instruction_for("landscape", one_minute=True).endswith(writer.MINUTE_RULES)


async def test_the_writing_step_asks_for_a_minute_when_the_job_is_one(store, monkeypatch, tmp_path):
    seen = {}

    async def stand_in_write(topic, minutes, brief, folder, turn, browser, listing="", assets_script="",
                             aspect="landscape", one_minute=False):
        seen.update(minutes=minutes, aspect=aspect, one_minute=one_minute)
        return writer.Written(title="Ice", narration=["Why?"], body="<script></script>", cues=[])

    monkeypatch.setattr(kind.writer, "write", stand_in_write)
    reel = make_job(slug="reel")
    reel.minutes = 2
    reel.data = {"aspect": "vertical"}
    await kind.write(reel, turn=None, browser=None)
    assert seen == {"minutes": 1, "aspect": "vertical", "one_minute": True}
    wide = make_job(slug="wide")
    wide.minutes = 3
    wide.data = {}
    await kind.write(wide, turn=None, browser=None)
    assert seen == {"minutes": 3, "aspect": "landscape", "one_minute": False}


# ── 5. The end: the chime at 0, then the cut ──

async def test_the_chime_plays_as_the_clock_reaches_zero(store, monkeypatch, tmp_path):
    mixed = {}

    async def keep_mix(narration_wav, placed, out):
        mixed["placed"] = placed
        out.write_bytes(narration_wav.read_bytes())

    monkeypatch.setattr(sounds, "mix", keep_mix)
    job = make_job(slug="reel")
    job.minutes = 1
    job.data.update({"cues": []})
    timings = minute.on_the_clock({"starts": [0.0, 6.5], "lengths": [6.0, 53.5], "beats": [[0.0], [0.0]]}, 2)
    narration_wav = tmp_path / "narration.wav"
    narration_wav.write_bytes(wav_of(64.0))
    await kind.voice_track(job, narration_wav, timings)
    [chime] = mixed["placed"]
    assert chime.name == "chime" and chime.start == pytest.approx(minute.COLD_OPEN + 60.0, abs=0.001)


# ── 6. Acceptance: a reel end to end, and a three-minute video as before ──

@pytest.fixture
def making(store, monkeypatch):
    """kind.make_video with a stand-in voice (scene lengths as given), the real fit, render, mux and probe, and a low
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


async def page_clock(page_html, tmp_path) -> dict:
    """The clock the finished video's page carries, and what Video.clockAt reads at its first and last word."""
    browser = Browser(tmp_path / "q", BIN, extra_args=RENDER_ARGS)
    try:
        async with browser.sealed_page(page_html, 1080, 1920) as tab:
            clock = await tab.eval("window.__timings.clock")
            ends = await tab.eval(f"[Video.clockAt({clock['start']}), Video.clockAt({clock['start'] + clock['length']})]")
    finally:
        await browser.close()
    return {"clock": clock, "first": ends[0], "last": ends[1]}


@needs_browser
async def test_a_reel_is_a_minute_of_narration_after_a_silent_question_card(making, tmp_path):
    making["lengths"] = [6.0, 59.5]  # 66 s of speech with the breath: fitted to 60
    job = make_job(slug="ice")
    job.minutes = 1
    job.data.update({"narration": ["Why is ice slippery?", "A thin wet skin."], "body": CLOCK_PAGE,
                     "aspect": "vertical"})
    browser = Browser(tmp_path / "p", BIN, extra_args=RENDER_ARGS)
    try:
        mp4 = await kind.make_video(job, browser, transport=None)
    finally:
        await browser.close()
    info = await encode.probe(mp4)
    assert (info["width"], info["height"]) == (1080, 1920)
    assert 62.0 <= info["seconds"] <= 64.0
    frame = first_frame(mp4)
    assert near(frame.getpixel((540, 200)), "#FFB020")       # the question card from the first frame
    assert near(frame.getpixel((900, 220)), "#FFB020")       # and no timer on it yet (its red box is drawn there)
    seen = await page_clock((job.folder / "page.html").read_text(encoding="utf-8"), tmp_path)
    assert seen["clock"]["start"] == minute.COLD_OPEN
    assert seen["clock"]["length"] == pytest.approx(60.0, abs=0.05)
    assert (seen["first"], seen["last"]) == (pytest.approx(60.0, abs=0.05), 0)
    after_zero = info["seconds"] - (seen["clock"]["start"] + seen["clock"]["length"])
    assert after_zero == pytest.approx(minute.END, abs=0.3)  # the blink and the chime, then nothing


@needs_browser
async def test_a_three_minute_video_keeps_its_free_length_with_no_clock(making, tmp_path):
    making["lengths"] = [1.5, 2.0]
    job = make_job(slug="tides")
    job.minutes = 3
    job.data.update({"narration": ["Why do tides turn?", "The moon pulls."], "body": CLOCK_PAGE})
    browser = Browser(tmp_path / "p", BIN, extra_args=RENDER_ARGS)
    try:
        mp4 = await kind.make_video(job, browser, transport=None)
    finally:
        await browser.close()
    info = await encode.probe(mp4)
    assert (info["width"], info["height"]) == (1920, 1080)
    assert info["seconds"] == pytest.approx(1.5 + 0.5 + 2.0, abs=0.6)  # the narration's own length, no 60 s
    page_html = (job.folder / "page.html").read_text(encoding="utf-8")
    timings = json.loads(page_html.split("<script>window.__timings = ", 1)[1].split(";</script>", 1)[0])
    assert "clock" not in timings and timings["starts"][0] == 0.0
