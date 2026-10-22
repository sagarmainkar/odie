"""A timed segment inside a video (odie.video.timed): a segment of exactly N seconds, for a countdown character, inside
a longer video. make_video takes timed_segment_seconds; vertical is only the frame size. The writer marks the segment's
first and last scene in Video.scenes (timed_start, timed_end); only that segment's voice is fitted to N seconds, first
word to last; the scenes before and after keep their natural length. The page gets window.ODIE_TIMED, which the kit
turns into s.left() and Video.clockAt(T): N at the segment's first word, 0 at its last; the chime plays at 0."""
import io
import json
import wave

import pytest

from odie.browser import RENDER_ARGS, find
from odie.browser.engine import Browser
from odie.making import jobs
from odie.video import encode, kind, page, sounds, timed, timeline, writer
from tests.test_media import make_wav
from tests.test_video_jobs import make_job
from tests.test_video_tool import load_tools
from tests.test_video_vertical import first_frame, joined_wavs, near, store  # noqa: F401 (store is a fixture)

tools = load_tools()
BIN = find.installed()
needs_browser = pytest.mark.skipif(BIN is None, reason="no Chrome, Edge, Chromium or Brave here")
MINUTE = timed.Segment(seconds=60.0, tolerance=0.10)

# Scene 1 is the cold open (an amber question card); scenes 2 and 3 are the timed segment (slate), scene 4 the pause
# (black), scene 5 the brand card (white). Every scene draws a red timer box at the top right, with the seconds left in
# it, only while the segment clock runs (s.left() isn't null).
TIMED_PAGE = """<script>
function timer(s) {
  const left = s.left();
  if (left === null) { return; }
  s.ctx.fillStyle = "#E0182D"; s.ctx.fillRect(s.W - 300, 200, 220, 160);
  s.text("timer", String(Math.ceil(left)), {x: s.W - 190, y: 280, size: 96, weight: 800});
}
function fill(s, colour) { s.ctx.fillStyle = colour; s.ctx.fillRect(0, 0, s.W, s.H); }
Video.scenes([
  {draw(t, s) { fill(s, "#FFB020"); s.text("q", "Why is ice slippery?", {size: 72, color: "#12161C"}); timer(s); }},
  {timed_start: true, draw(t, s) { fill(s, "#12161C"); s.text("a", "Sixty seconds", {size: 72}); timer(s); }},
  {timed_end: true, draw(t, s) { fill(s, "#12161C"); s.text("b", "A thin wet skin.", {size: 72}); timer(s); }},
  {draw(t, s) { fill(s, "#000000"); timer(s); }},
  {draw(t, s) { fill(s, "#FFFFFF"); s.text("c", "odie", {size: 72, color: "#12161C"}); }},
]);
</script>"""
# Two plain scenes, no marks: an amber question card, then a slate answer
TWO_SCENES = """<script>
Video.scenes([
  {draw(t, s) { s.ctx.fillStyle = "#FFB020"; s.ctx.fillRect(0, 0, s.W, s.H); }},
  {draw(t, s) { s.ctx.fillStyle = "#12161C"; s.ctx.fillRect(0, 0, s.W, s.H); }},
]);
</script>"""
NARRATION = ["Why is ice slippery?", "Sixty seconds: watch the skin.", "A thin wet skin.", "So.", "Odie."]


def wav_of(seconds: float, loud: float = 0.5) -> bytes:
    return make_wav(seconds, rate=24000, loud=loud)


def seconds_of(wav: bytes) -> float:
    with wave.open(io.BytesIO(wav)) as w:
        return w.getnframes() / w.getframerate()


def joined(lengths: list[float]) -> bytes:
    wav, _starts = joined_wavs([wav_of(length) for length in lengths], gap=timeline.BREATH)
    return wav


# ── 1. make_video: vertical is the frame size only; the timed segment is its own option ──

@pytest.fixture
def queued(store, monkeypatch):
    monkeypatch.setitem(jobs.hooks, "store", store)
    monkeypatch.setattr(find, "browser_binary", lambda: "/Applications/Some Browser")
    jobs_queued = []
    monkeypatch.setattr(jobs, "submit", lambda job: jobs_queued.append(job) or len(jobs_queued))
    return jobs_queued


async def test_vertical_sets_only_the_frame_size_and_the_length_stays_as_asked(queued):
    assert "result" in await tools.make_video("Why ice is slippery", aspect="insta")
    assert "result" in await tools.make_video("Why ice is slippery", minutes=3, aspect="reel")
    assert "result" in await tools.make_video("Why ice is slippery", minutes=1)
    reel, longer_reel, one_minute = queued
    assert (reel.minutes, reel.data["aspect"]) == (2, "vertical")
    assert (longer_reel.minutes, longer_reel.data["aspect"]) == (3, "vertical")
    assert one_minute.minutes == 1
    assert all("timed_segment" not in job.data for job in queued)  # no segment unless asked: the free length


async def test_a_timed_segment_goes_on_the_job_with_its_tolerance(queued):
    assert "result" in await tools.make_video("Why ice is slippery", minutes=2, aspect="vertical",
                                              timed_segment_seconds=60)
    assert "result" in await tools.make_video("Why ice is slippery", timed_segment_seconds="45")
    first, second = queued
    assert first.data["timed_segment"] == {"seconds": 60, "tolerance": 0.10}
    assert first.minutes == 2
    assert second.data["timed_segment"]["seconds"] == 45


@pytest.mark.parametrize(("minutes", "given", "said"), [
    (1, 90, "longer than the video"), (2, "soon", "a whole number of seconds"), (2, -5, "a whole number of seconds")])
async def test_a_timed_segment_that_cant_be_is_refused(queued, minutes, given, said):
    out = await tools.make_video("Why ice is slippery", minutes=minutes, timed_segment_seconds=given)
    assert said in out["error"] and queued == []


# ── 2. The writer marks the segment: exactly one start and one end, the start first ──

@pytest.mark.parametrize(("starts", "ends", "problem"), [
    ([2], [3], None), ([3], [3], None),
    ([], [], "Mark the 60-second segment"), ([2], [], "timed_end"), ([], [3], "timed_start"),
    ([1, 2], [3], "only one scene with timed_start"), ([2], [3, 4], "only one scene with timed_end"),
    ([4], [2], "comes before"),
])
def test_the_marks_must_make_one_segment(starts, ends, problem):
    got = timed.marks_problem(starts, ends, 60)
    if problem is None:
        assert got is None
    else:
        assert problem in got


def test_the_marked_scenes_as_the_segment():
    assert timed.segment_scenes([2], [3]) == (1, 2)  # 0-based: scene 2 to scene 3
    assert timed.segment_scenes([3], [3]) == (2, 2)  # a segment of one scene


def test_the_segments_word_budget():
    assert timed.word_budget(60) == (140, 115, 170)
    assert timed.word_budget(30) == (70, 57, 85)


def test_the_segment_is_held_to_its_seconds_of_words_and_the_rest_is_free():
    words_140 = " ".join(["word"] * 70)
    narration = ["A long cold open " + " ".join(["intro"] * 80), words_140, words_140, "Bye."]
    assert timed.words_problem(narration, 1, 2, 60) is None  # 140 words in the segment; the 80 before don't count
    short = ["Hi.", " ".join(["word"] * 30), "Bye."]
    said = timed.words_problem(short, 1, 1, 60)
    assert "30 words" in said and "60 seconds" in said


# ── 3. Only the segment's voice is fitted, first word to last ──

def test_starts_from_the_lengths_and_each_gap():
    assert timed.starts_with_gaps([6.0, 30.0, 30.0], [0.5, 0.45]) == ([0.0, 6.5, 36.95], 66.95)


async def test_only_the_segment_is_fitted_to_its_seconds(tmp_path):
    lengths = [6.0, 30.0, 35.5, 2.0, 4.0]  # the segment: 30 + 0.5 breath + 35.5 = 66 s of speech, fitted to 60
    beats = [[0.0], [0.0, 15.0], [0.0], [0.0], [0.0]]
    fitted = await timed.fit(joined(lengths), lengths, beats, 1, 2, MINUTE, tmp_path)
    assert fitted.lengths[0] == 6.0 and fitted.lengths[3:] == [2.0, 4.0]  # untimed scenes keep their length
    assert fitted.gaps[0] == timeline.BREATH and fitted.gaps[2:] == [timeline.BREATH, timeline.BREATH]
    scale = 60.0 / 66.0
    assert fitted.lengths[1] == pytest.approx(30.0 * scale, abs=0.02)
    assert fitted.gaps[1] == pytest.approx(timeline.BREATH * scale, abs=0.001)
    assert fitted.beats[1][1] == pytest.approx(15.0 * scale, abs=0.02)
    assert fitted.clock["start"] == pytest.approx(6.5, abs=0.001)  # the segment's first word, after the cold open
    assert fitted.clock["end"] - fitted.clock["start"] == pytest.approx(60.0, abs=0.02)
    assert fitted.clock["seconds"] == 60
    assert seconds_of(fitted.wav) == pytest.approx(6.0 + 0.5 + 60.0 + 0.5 + 2.0 + 0.5 + 4.0, abs=0.05)


async def test_quiet_before_the_first_word_and_after_the_last_is_not_counted(tmp_path):
    first, _ = joined_wavs([wav_of(0.2, loud=0.0), wav_of(29.8)], gap=0)  # 0.2 s quiet, then the words
    last, _ = joined_wavs([wav_of(29.2), wav_of(0.3, loud=0.0)], gap=0)  # the words, then 0.3 s quiet
    whole, _ = joined_wavs([wav_of(3.0), first, last], gap=timeline.BREATH)
    fitted = await timed.fit(whole, [3.0, 30.0, 29.5], [[0.0], [0.0], [0.0]], 1, 2, MINUTE, tmp_path)
    assert fitted.clock["end"] - fitted.clock["start"] == pytest.approx(60.0, abs=0.03)
    assert fitted.clock["start"] > 3.5 + 0.15  # its first word, after the scene's quiet


async def test_a_segment_too_far_from_its_seconds_fails_naming_its_length(tmp_path):
    lengths = [3.0, 71.2]
    with pytest.raises(timed.DoesntFit) as caught:
        await timed.fit(joined(lengths), lengths, [[0.0], [0.0]], 1, 1, MINUTE, tmp_path)
    assert str(caught.value).startswith("segment narration is 71.2 s; needs 60 s")


def test_only_a_segment_that_ends_the_video_needs_room_for_the_blink():
    assert timed.ends_the_video(last_scene=1, narrated_scenes=2)
    assert not timed.ends_the_video(last_scene=2, narrated_scenes=5)  # a pause and a closing card hold the blink


# ── 4. The page: window.ODIE_TIMED, read by s.left() and Video.clockAt ──

@needs_browser
async def test_the_kit_counts_the_segment_from_its_first_word_to_its_last(tmp_path):
    timings = {"starts": [0.0, 6.5, 36.95, 67.0, 69.5], "lengths": [6.0, 29.5, 29.55, 2.0, 4.0],
               "beats": [[0.0]] * 5, "timed": {"start": 6.5, "seconds": 60, "end": 66.5}}
    html = page.assemble(TIMED_PAGE, timings, size=timeline.VERTICAL)
    browser = Browser(tmp_path / "p", BIN, extra_args=RENDER_ARGS)
    try:
        async with browser.sealed_page(html, 1080, 1920) as tab:
            assert await tab.eval("window.ODIE_TIMED") == {"start": 6.5, "seconds": 60, "end": 66.5}
            at = await tab.eval("[Video.clockAt(3), Video.clockAt(6.5), Video.clockAt(36.5), Video.clockAt(66.5), "
                                "Video.clockAt(70)]")
            assert at == [None, 60, 30, 0, 0]
            assert await tab.eval("Video.timedScenes()") == {"starts": [2], "ends": [3]}
    finally:
        await browser.close()


@needs_browser
async def test_a_page_marking_no_segment_for_a_timed_video_is_told_to_mark_it(tmp_path):
    unmarked = TIMED_PAGE.replace("timed_start: true, ", "").replace("timed_end: true, ", "")
    browser = Browser(tmp_path / "p", BIN, extra_args=RENDER_ARGS)
    try:
        told = await page.check_with_cues(unmarked, NARRATION, browser, size=timeline.VERTICAL, timed_seconds=60)
        marked = await page.check_with_cues(TIMED_PAGE, NARRATION, browser, size=timeline.VERTICAL, timed_seconds=60)
        free = await page.check_with_cues(TIMED_PAGE, NARRATION, browser, size=timeline.VERTICAL)
    finally:
        await browser.close()
    assert "Mark the 60-second segment" in told.problem
    assert marked.problem is None and marked.segment == (1, 2)
    assert free.problem is None and free.segment is None  # no timed segment asked: the marks are ignored


# ── 5. The writer is told, and the writing step keeps the marks ──

def test_the_writer_gets_the_segment_rules_only_for_a_timed_video():
    assert writer.instruction_for("landscape") == writer.INSTRUCTION
    plain = writer.instruction_for("vertical")
    with_segment = writer.instruction_for("vertical", timed_seconds=60)
    assert with_segment.startswith(plain.rstrip())
    assert "Everything between the flags is the 60-second segment" in with_segment
    assert "timed_start: true" in with_segment and "s.left()" in with_segment
    assert "__SECONDS__" not in with_segment


async def test_the_writer_is_held_to_the_segments_words(monkeypatch):
    async def drawn(body, narration, browser, assets_script="", size=None, timed_seconds=None):
        return page.CheckResult(problem=None, segment=(1, 1))

    monkeypatch.setattr(page, "check_with_cues", drawn)
    short = ["Hi.", " ".join(["word"] * 30), "Bye."]
    judged = await writer.checked_submission(short, TIMED_PAGE, object(), timed_seconds=60)
    assert "30 words" in judged.problem
    free = await writer.checked_submission(short, TIMED_PAGE, object())
    assert free.problem is None


async def test_the_writing_step_asks_for_the_segment_and_keeps_its_scenes(store, monkeypatch):
    seen = {}

    async def stand_in_write(topic, minutes, brief, folder, turn, browser, listing="", assets_script="",
                             aspect="landscape", timed_seconds=None, kit=None):
        seen.update(minutes=minutes, aspect=aspect, timed_seconds=timed_seconds)
        return writer.Written(title="Ice", narration=NARRATION, body=TIMED_PAGE, cues=[], segment=(1, 2))

    monkeypatch.setattr(kind.writer, "write", stand_in_write)
    job = make_job(slug="reel")
    job.minutes = 2
    job.data = {"aspect": "vertical", "timed_segment": {"seconds": 60, "tolerance": 0.1}}
    await kind.write(job, turn=None, browser=None)
    assert seen == {"minutes": 2, "aspect": "vertical", "timed_seconds": 60}
    assert job.data["timed_scenes"] == [1, 2]


# ── 6. The chime at the segment's 0, ringing on past its scene ──

async def test_the_chime_plays_as_the_segment_clock_reaches_zero(store, monkeypatch, tmp_path):
    mixed = {}

    async def keep_mix(narration_wav, placed, out):
        mixed["placed"] = placed
        out.write_bytes(narration_wav.read_bytes())

    monkeypatch.setattr(sounds, "mix", keep_mix)
    job = make_job(slug="reel")
    job.data.update({"narration": NARRATION, "cues": []})
    timings = {"starts": [0.0, 6.5, 36.95, 67.0, 69.5], "lengths": [6.0, 29.5, 29.55, 2.0, 4.0],
               "beats": [[0.0]] * 5, "timed": {"start": 6.5, "seconds": 60, "end": 66.5}}
    narration_wav = tmp_path / "narration.wav"
    narration_wav.write_bytes(wav_of(73.5))
    await kind.voice_track(job, narration_wav, timings)
    [chime] = mixed["placed"]
    assert chime.name == "chime" and chime.start == pytest.approx(66.5, abs=0.001)
    assert chime.seconds > 0.5  # it rings on into the pause, past the segment's last scene


# ── 7. Acceptance: a reel with a timed minute inside it; a reel without one; a wide video as before ──

@pytest.fixture
def making(store, monkeypatch):
    """kind.make_video with a stand-in voice (scene lengths as given), the real fit, render, mux and probe, and a low
    frame rate so a minute renders in seconds (frames stay time-based: fps x seconds)."""
    monkeypatch.setitem(jobs.hooks, "store", store)
    monkeypatch.setattr(kind.timeline, "FPS", 2)
    spoken = {}

    async def stand_in_narrate(store, narration, voice_name="", transport=None, style=""):
        lengths = spoken["lengths"]
        return joined(lengths), lengths, [[0.0] for _ in lengths]

    monkeypatch.setattr(kind, "narrate", stand_in_narrate)
    return spoken


async def page_clock(page_html, tmp_path) -> dict:
    """The segment clock the finished video's page carries, and what Video.clockAt reads at its first and last word."""
    browser = Browser(tmp_path / "q", BIN, extra_args=RENDER_ARGS)
    try:
        async with browser.sealed_page(page_html, 1080, 1920) as tab:
            clock = await tab.eval("window.ODIE_TIMED || null")
            ends = None
            if clock:
                ends = await tab.eval(f"[Video.clockAt({clock['start']}), Video.clockAt({clock['end']})]")
    finally:
        await browser.close()
    return {"clock": clock, "ends": ends}


async def made(job, tmp_path):
    browser = Browser(tmp_path / "p", BIN, extra_args=RENDER_ARGS)
    try:
        return await kind.make_video(job, browser, transport=None)
    finally:
        await browser.close()


@needs_browser
async def test_a_two_minute_reel_with_a_timed_minute_inside_it(making, tmp_path):
    making["lengths"] = [6.0, 30.0, 35.5, 2.0, 4.0]  # cold open, the segment (66 s of speech -> 60), pause, brand card
    job = make_job(slug="ice")
    job.minutes = 2
    job.data.update({"narration": NARRATION, "body": TIMED_PAGE, "aspect": "vertical", "timed_scenes": [1, 2],
                     "timed_segment": {"seconds": 60, "tolerance": 0.1}})
    mp4 = await made(job, tmp_path)
    info = await encode.probe(mp4)
    assert (info["width"], info["height"]) == (1080, 1920)
    assert 71.0 <= info["seconds"] <= 75.0  # 6 + 60 + 2 + 4 and the breaths: about 72 s
    frame = first_frame(mp4)
    assert near(frame.getpixel((540, 200)), "#FFB020")  # the question card from the first frame
    assert near(frame.getpixel((900, 220)), "#FFB020")  # and no timer on it (its red box would be drawn there)
    seen = await page_clock((job.folder / "page.html").read_text(encoding="utf-8"), tmp_path)
    assert seen["clock"]["start"] == pytest.approx(6.5, abs=0.001)
    assert seen["clock"]["end"] - seen["clock"]["start"] == pytest.approx(60.0, abs=0.05)
    assert seen["ends"] == [60, 0]


@needs_browser
async def test_a_segment_that_ends_the_video_holds_the_blink_after_its_last_word(making, tmp_path):
    making["lengths"] = [3.0, 64.0]  # a short question, then the segment to the end (64 s -> 60)
    job = make_job(slug="ice")
    job.data.update({"narration": ["Why is ice slippery?", "Sixty seconds: watch the skin."], "aspect": "vertical",
                     "timed_scenes": [1, 1], "timed_segment": {"seconds": 60, "tolerance": 0.1},
                     "body": '<script>Video.scenes([{draw(t, s) {}}, {timed_start: true, timed_end: true, '
                             'draw(t, s) {}}]);</script>'})
    mp4 = await made(job, tmp_path)
    info = await encode.probe(mp4)
    seen = await page_clock((job.folder / "page.html").read_text(encoding="utf-8"), tmp_path)
    after_zero = info["seconds"] - seen["clock"]["end"]
    assert after_zero == pytest.approx(timed.BLINK, abs=0.3)  # the blink and the chime, then the cut


@needs_browser
async def test_a_reel_without_a_timed_segment_keeps_its_free_length(making, tmp_path):
    making["lengths"] = [4.0, 70.0]  # 74.5 s of narration: nothing fitted, nothing refused
    job = make_job(slug="ice")
    job.data.update({"narration": ["Why is ice slippery?", "A thin wet skin."], "aspect": "vertical",
                     "body": TWO_SCENES})
    mp4 = await made(job, tmp_path)
    info = await encode.probe(mp4)
    assert (info["width"], info["height"]) == (1080, 1920)
    assert info["seconds"] == pytest.approx(4.0 + 0.5 + 70.0, abs=0.6)
    seen = await page_clock((job.folder / "page.html").read_text(encoding="utf-8"), tmp_path)
    assert seen["clock"] is None


@needs_browser
async def test_a_three_minute_wide_video_is_made_as_before(making, tmp_path):
    making["lengths"] = [1.5, 2.0]
    job = make_job(slug="tides")
    job.minutes = 3
    job.data.update({"narration": ["Why do tides turn?", "The moon pulls."], "body": TWO_SCENES})
    mp4 = await made(job, tmp_path)
    info = await encode.probe(mp4)
    assert (info["width"], info["height"]) == (1920, 1080)
    assert info["seconds"] == pytest.approx(1.5 + 0.5 + 2.0, abs=0.6)
    page_html = (job.folder / "page.html").read_text(encoding="utf-8")
    timings = json.loads(page_html.split("<script>window.__timings = ", 1)[1].split(";</script>", 1)[0])
    assert "timed" not in timings and "<script>window.ODIE_TIMED =" not in page_html and timings["starts"][0] == 0.0
