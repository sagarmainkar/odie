"""The explainer video as one kind of thing Odie makes in the background (odie.making.jobs): its writing step is the
video writer (odie.video.writer), which turns the topic, length and brief into the title, the narration and the page;
its making step narrates, draws and joins them into an MP4 and hands it over for the chat. Importing this module
registers the kind as "video", with its jobs under <workspace>/videos/<slug>/.

A video job's folder holds pages/ (every page the writer submitted), page.html (the accepted page as it was drawn,
with its timings), narration.wav, the segment files, <slug>.mp4 and job.json. job.data carries "narration" (one
string per scene) and "body" (the page) from the writing step to the making step."""
from pathlib import Path

from odie import voice
from odie.agent.tools.files import hand_over
from odie.browser.engine import BrowserError
from odie.making import jobs
from odie.video import timeline, writer
from odie.video.encode import EncodeError, mux, probe
from odie.video.narrate import narrate
from odie.video.page import assemble
from odie.video.render import render

FOLDER = "videos"


def needs_writing(job: jobs.Job) -> bool:
    """Decides whether the writer must make this job's page first: a job with a topic and no page yet -> True; a job
    that already carries its narration and page (made the old way, with the page in hand) -> False, it goes straight
    to drawing."""
    narration = job.data.get("narration")
    body = job.data.get("body")
    has_page = bool(narration) and bool(body)
    return not has_page


async def write(job: jobs.Job, turn, browser) -> None:
    """The writing step: the video writer's focused turn, then the title, narration and page onto the job."""
    written = await writer.write(job.topic, job.minutes, job.brief, job.folder, turn, browser)
    job.title = jobs.title_after_writing(written.title, job)
    job.data["narration"] = written.narration
    job.data["body"] = written.body


async def make_video(job: jobs.Job, browser, transport) -> Path:
    """The steps from narration to a checked MP4 file; returns the MP4's path. Any step may raise."""
    folder = job.folder
    narration = job.data["narration"]
    body = job.data["body"]
    wav, lengths, beats = await narrate(jobs.hooks["store"], narration, job.voice_name, transport=transport)

    starts, _total = timeline.scene_starts(lengths, timeline.BREATH)
    timings = {"starts": starts, "lengths": lengths, "beats": beats}

    narration_wav = folder / "narration.wav"
    narration_wav.write_bytes(wav)
    (folder / "page.html").write_text(assemble(body, timings), encoding="utf-8")

    segments = await render(browser, body, timings, folder, timeline.FPS, timeline.TABS)
    mp4 = folder / f"{job.slug}.mp4"
    await mux(segments, narration_wav, mp4)

    info = await probe(mp4)
    if not info["video"] or not info["audio"]:
        raise EncodeError("The finished file is missing its picture or its sound.")
    return mp4


async def make(job: jobs.Job, browser, transport) -> dict:
    """The making step: the MP4, handed over for the chat; returns its media (the player under the message)."""
    mp4 = await make_video(job, browser, transport)
    handed = hand_over(mp4, job.title)
    return handed["media"]


# Errors whose words are written for the user: the voice isn't running, ffmpeg's complaint, the browser's.
KNOWN_ERRORS = (voice.VoiceUnavailable, EncodeError, BrowserError)
KIND = jobs.Kind(word="video", folder=FOLDER, write=write, make=make, known_errors=KNOWN_ERRORS,
                 needs_writing=needs_writing)
jobs.KINDS["video"] = KIND
