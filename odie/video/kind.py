"""The explainer video as one kind of thing Odie makes in the background (odie.making.jobs): its writing step is the
video writer (odie.video.writer), which turns the topic, length and brief into the title, the narration and the page;
its making step narrates, draws and joins them into an MP4 and hands it over for the chat. Importing this module
registers the kind as "video", with its jobs under <workspace>/videos/<slug>/.

A video job's folder holds brief.md (the writer's brief, then the picture and clip lines as the chat gave them),
assets/ (the prepared pictures and clips: img1.jpg, clip1.webm, …), pages/ (every page the writer submitted),
page.html (the accepted page as it was drawn, with its timings, pictures and credits card), narration.wav, the
segment files, <slug>.mp4 and job.json.

job.data carries, from make_video: "given" ({"images": [...], "clips": [...]}, the chat's lines) and "private" (the
signed-in sites the asking chat had read); from the writing step: "assets" (each prepared one's name, kind, words,
credit, size, length and file; never its data), "dropped" (the lines the writer was told about the ones that couldn't
be used), "narration" (one string per scene), "body" (the page) and "cues" (the sound cues the page placed with
Video.sounds, as odie.video.page.CheckResult gives them; [] when none). job.json never holds any of these."""
from pathlib import Path

from odie import voice
from odie.agent import turn as chat_turn
from odie.agent.tools.files import hand_over
from odie.browser.engine import BrowserError
from odie.making import jobs
from odie.video import assets, timeline, writer
from odie.video.encode import EncodeError, mux, probe
from odie.video.narrate import narrate
from odie.video.page import assemble, credits_scene
from odie.video.render import render

FOLDER = "videos"
CREDITS_SECONDS = 3.0  # Odie's credits card for web pictures and clips, after the last scene


def needs_writing(job: jobs.Job) -> bool:
    """Decides whether the writer must make this job's page first: a job with a topic and no page yet -> True; a job
    that already carries its narration and page (made the old way, with the page in hand) -> False, it goes straight
    to drawing."""
    narration = job.data.get("narration")
    body = job.data.get("body")
    has_page = bool(narration) and bool(body)
    return not has_page


def given_lines(job: jobs.Job) -> tuple[list[str], list[str]]:
    """The picture and clip lines the chat gave make_video; a job made before pictures (no "given") has none."""
    given = job.data.get("given", {})
    return given.get("images", []), given.get("clips", [])


def keep_lines_in_brief(job: jobs.Job) -> None:
    """Add the chat's picture and clip lines to the job's brief.md under "## Pictures", word for word, so the brief
    kept for revisions has them. The writer's own brief (job.brief) never has them: it reads names and words only."""
    images, clips = given_lines(job)
    section = assets.brief_section(images, clips)
    if not section:
        return
    pieces = [job.brief.strip(), section]
    text = "\n\n".join(piece for piece in pieces if piece)
    (job.folder / "brief.md").write_text(text + "\n", encoding="utf-8")


async def gather_assets(job: jobs.Job) -> tuple[list[assets.Asset], list[str]]:
    """The job's pictures and clips fetched and prepared into its assets/ folder (odie.video.assets.gather), as the
    asking chat was: a private chat's web addresses are refused, with the deck's words. The queue's worker runs in an
    empty context of its own, so the chat's sites are set here from the job, as the deck's making step does."""
    images, clips = given_lines(job)
    pictures, moving = assets.parse(images, clips)
    private = chat_turn.PRIVATE.set(set(job.data.get("private", [])))
    try:
        return await assets.gather(pictures, moving, job.folder)
    finally:
        chat_turn.PRIVATE.reset(private)


def assets_from(job: jobs.Job) -> list[assets.Asset]:
    """The prepared pictures and clips the writing step recorded, their files in the job's assets/ folder; a job
    with none (or made before pictures) -> []."""
    records = job.data.get("assets", [])
    return assets.from_records(records, job.folder / "assets")


async def write(job: jobs.Job, turn, browser) -> None:
    """The writing step: the pictures and clips first (so the writer is told what it has, by name), then the video
    writer's focused turn, then the title, narration, page and sound cues onto the job."""
    keep_lines_in_brief(job)
    gathered, dropped = await gather_assets(job)
    job.data["assets"] = [assets.as_record(asset) for asset in gathered]
    job.data["dropped"] = dropped
    listing = assets.listing(gathered, dropped)
    assets_script = assets.staple(gathered)  # the writer's page check draws the same pictures the render will
    written = await writer.write(job.topic, job.minutes, job.brief, job.folder, turn, browser, listing=listing,
                                 assets_script=assets_script)
    job.title = jobs.title_after_writing(written.title, job)
    job.data["narration"] = written.narration
    job.data["body"] = written.body
    job.data["cues"] = written.cues


async def make_video(job: jobs.Job, browser, transport) -> Path:
    """The steps from narration to a checked MP4 file; returns the MP4's path. Any step may raise. When the video has
    web pictures or clips, their credits get a card of Odie's own after the writer's last scene (CREDITS_SECONDS,
    silent): one more scene in the timings than the narration has, and the voice padded to the picture's end."""
    folder = job.folder
    narration = job.data["narration"]
    body = job.data["body"]
    wav, lengths, beats = await narrate(jobs.hooks["store"], narration, job.voice_name, transport=transport)

    gathered = assets_from(job)
    credits = assets.credits(gathered)
    credits_script = credits_scene(credits)
    if credits:
        lengths = lengths + [CREDITS_SECONDS]
        beats = beats + [[0.0]]
    starts, _total = timeline.scene_starts(lengths, timeline.BREATH)
    timings = {"starts": starts, "lengths": lengths, "beats": beats}

    narration_wav = folder / "narration.wav"
    narration_wav.write_bytes(wav)
    assets_script = assets.staple(gathered)
    page_html = assemble(body, timings, assets_script, credits_script)
    (folder / "page.html").write_text(page_html, encoding="utf-8")

    segments = await render(browser, body, timings, folder, timeline.FPS, timeline.TABS, assets_script=assets_script,
                            credits_script=credits_script)
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


# Errors whose words are written for the user: the voice isn't running, ffmpeg's complaint, the browser's, the
# pictures over what a video can carry.
KNOWN_ERRORS = (voice.VoiceUnavailable, EncodeError, BrowserError, assets.AssetProblem)
KIND = jobs.Kind(word="video", folder=FOLDER, write=write, make=make, known_errors=KNOWN_ERRORS,
                 needs_writing=needs_writing)
jobs.KINDS["video"] = KIND
