"""The explainer video as one kind of thing Odie makes in the background (odie.making.jobs): its writing step is the
video writer (odie.video.writer), which turns the topic, length and brief into the title, the narration and the page;
its making step narrates, draws and joins them into an MP4 and hands it over for the chat. Importing this module
registers the kind as "video", with its jobs under <workspace>/videos/<slug>/.

A video job's folder holds brief.md (the writer's brief, then the picture and clip lines as the chat gave them),
assets/ (the prepared pictures and clips: img1.jpg, clip1.webm, …), pages/ (every page the writer submitted),
page.html (the accepted page as it was drawn, with its timings, pictures and credits card), narration.wav, mix.wav
(the narration with the page's sound cues under it, when it placed any), the segment files, <slug>.mp4 and job.json.

job.data carries, from make_video: "given" ({"images": [...], "clips": [...]}, the chat's lines), "private" (the
signed-in sites the asking chat had read), "sounds" (False when the user asked for no sound effects), "style" (how
an OpenAI narrator should sound, "" for Odie's usual; older jobs have none) and "aspect" ("landscape" or "vertical",
see aspect_of; older jobs have none and are landscape); from the writing step: "assets" (each
prepared one's name, kind, words, credit, size, length and file; never its data), "dropped" (the lines the writer
was told about the ones that couldn't be used), "narration" (one string per scene), "body" (the page) and "cues" (the
sound cues the page placed with Video.sounds, as odie.video.page.CheckResult gives them; [] when none). job.json never
holds any of these."""
import logging
from pathlib import Path

from odie import voice
from odie.agent import turn as chat_turn
from odie.agent.tools.files import hand_over
from odie.browser.engine import BrowserError
from odie.making import jobs
from odie.video import assets, sounds, timeline, writer
from odie.video.encode import EncodeError, mux, probe
from odie.video.narrate import narrate
from odie.video.page import assemble, credits_scene
from odie.video.render import render

FOLDER = "videos"
CREDITS_SECONDS = 3.0  # Odie's credits card for web pictures and clips, after the last scene

log = logging.getLogger("odie.video")


def needs_writing(job: jobs.Job) -> bool:
    """Decides whether the writer must make this job's page first: a job with a topic and no page yet -> True; a job
    that already carries its narration and page (made the old way, with the page in hand) -> False, it goes straight
    to drawing."""
    narration = job.data.get("narration")
    body = job.data.get("body")
    has_page = bool(narration) and bool(body)
    return not has_page


def aspect_of(job: jobs.Job) -> str:
    """Decides the video's shape from its job: "vertical" (a 1080 x 1920 reel) only when make_video stored it; a job
    with no "aspect" (every video before aspects) or an unknown one is "landscape". {"aspect": "vertical"} ->
    "vertical"; {} -> "landscape"; {"aspect": "square"} -> "landscape"."""
    aspect = job.data.get("aspect", "landscape")
    if aspect in timeline.SIZES:
        return aspect
    return "landscape"


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
                                 assets_script=assets_script, aspect=aspect_of(job))
    job.title = jobs.title_after_writing(written.title, job)
    job.data["narration"] = written.narration
    job.data["body"] = written.body
    job.data["cues"] = written.cues


def wants_sounds(job: jobs.Job) -> bool:
    """Decides whether the page's sound cues are mixed into this video: yes unless the chat turned sounds off for it.
    A job with no "sounds" in its data (the default, and every job made before the switch) -> True;
    {"sounds": False} -> False, and the video has its narration only."""
    return job.data.get("sounds", True)


async def voice_track(job: jobs.Job, narration_wav: Path, timings: dict) -> Path:
    """The sound mux lays under the picture: the narration with the page's sound cues mixed under it (mix.wav), or
    the narration as it is when there is nothing to mix. A job without cues, with sounds off, or whose cues all drop
    (odie.video.sounds.resolve) -> narration.wav, and ffmpeg doesn't run for it. A mix that fails is logged and the
    video keeps its narration: a sound never fails a video."""
    if not wants_sounds(job):
        return narration_wav
    cues = job.data.get("cues", [])
    narrated_scenes = len(job.data["narration"])  # the timings may end with Odie's silent credits card
    placed = sounds.resolve(cues, timings, narrated_scenes)
    if not placed:
        return narration_wav
    mixed_wav = job.folder / "mix.wav"
    try:
        await sounds.mix(narration_wav, placed, mixed_wav)
    except EncodeError as e:
        log.warning("video %r: the sound mix failed, so the video has its narration only: %s", job.slug, e)
        return narration_wav
    return mixed_wav


async def make_video(job: jobs.Job, browser, transport) -> Path:
    """The steps from narration to a checked MP4 file; returns the MP4's path. Any step may raise. When the video has
    web pictures or clips, their credits get a card of Odie's own after the writer's last scene (CREDITS_SECONDS,
    silent): one more scene in the timings than the narration has, and the voice padded to the picture's end. The
    page's sound cues are mixed under the narration (voice_track) before mux. The video is drawn at its aspect's size
    (aspect_of, timeline.size_of), and a finished file of any other size is refused."""
    folder = job.folder
    narration = job.data["narration"]
    body = job.data["body"]
    size = timeline.size_of(aspect_of(job))
    style = job.data.get("style", "")  # a job queued before styles has none: Odie's usual voice
    wav, lengths, beats = await narrate(jobs.hooks["store"], narration, job.voice_name, transport=transport,
                                        style=style)

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
    sound_wav = await voice_track(job, narration_wav, timings)
    assets_script = assets.staple(gathered)
    page_html = assemble(body, timings, assets_script, credits_script, size=size)
    (folder / "page.html").write_text(page_html, encoding="utf-8")

    segments = await render(browser, body, timings, folder, timeline.FPS, timeline.TABS, assets_script=assets_script,
                            credits_script=credits_script, size=size)
    mp4 = folder / f"{job.slug}.mp4"
    await mux(segments, sound_wav, mp4)

    info = await probe(mp4)
    if not info["video"] or not info["audio"]:
        raise EncodeError("The finished file is missing its picture or its sound.")
    made = (info["width"], info["height"])
    if made != size:
        raise EncodeError(f"The finished file is {made[0]}x{made[1]}, not {size[0]}x{size[1]}.")
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
