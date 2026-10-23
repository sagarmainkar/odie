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
an OpenAI narrator should sound, "" for Odie's usual; older jobs have none), "aspect" ("landscape" or "vertical",
see aspect_of; older jobs have none and are landscape) and, when asked, "timed_segment" ({"seconds": 60,
"tolerance": 0.1}, odie.video.timed), and "brand_kit" ({"name", "version", "path"}: the brand kit it was asked with,
copied into the job's brand/ folder, odie.video.brand); from the writing step: "timed_scenes" (the segment's first and
last scene, 0-based, when it has one), "brand_vars" (the kit's bookend words the writer gave), "assets" (each
prepared one's name, kind, words, credit, size, length and file; never its data), "dropped" (the lines the writer
was told about the ones that couldn't be used), "narration" (one string per scene), "body" (the page) and "cues" (the
sound cues the page placed with Video.sounds, as odie.video.page.CheckResult gives them; [] when none). job.json never
holds any of these. A dialogue video (odie.video.dialogue) also carries "dialogue": {"script" (the user's script as
Script.as_data keeps it), "voices" (speaker -> voice id)}; it is spoken line by line (narrate_dialogue), its page gets
the line timeline, and timeline.json is kept next to the MP4. Without "dialogue" nothing of it runs."""
import json
import logging
from pathlib import Path

from odie import voice
from odie.agent import turn as chat_turn
from odie.agent.tools.files import hand_over
from odie.browser.engine import BrowserError
from odie.making import jobs
from odie.video import assets, brand, dialogue, sounds, timed, timeline, writer
from odie.video import cast as cast_module
from odie.video.encode import EncodeError, ffmpeg, mux, probe, run, tail
from odie.video.narrate import narrate, narrate_dialogue
from odie.video.page import assemble, credits_scene
from odie.video.render import render

FOLDER = "videos"
TIMELINE = "timeline.json"  # a dialogue video's lines and scenes, next to its MP4
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


def credits_on_screen(job: jobs.Job, credits: list[str]) -> list[str]:
    """Decides which credits get Odie's card at the video's end. A reel (a vertical video, whatever its length) shows
    none and keeps them as job.data["caption_credits"] for the ready message (the owner's choice: credits in the
    caption); a landscape video shows them all. A reel with ["Photo by A on Unsplash"] -> [] (and the caption line); a
    landscape video -> ["Photo by A on Unsplash"]."""
    if aspect_of(job) != "vertical":
        return credits
    if credits:
        job.data["caption_credits"] = credits
    return []


def ready_text(job: jobs.Job) -> str:
    """The chat's ready message: "The video about Ice is ready.", and for a reel with web pictures, their credits as
    a line to paste into the post's caption: "For the caption: Photo by A on Unsplash · Pexels, by B". A dialogue
    video also says where its timeline.json is."""
    line = jobs.ready_line("video", job.title)
    if job.data.get("dialogue"):
        where = f"videos/{job.slug}/{TIMELINE}"
        line = f"{line}\n\nIts timeline (every line's time and voice) is {where} in Odie's workspace."
    credits = job.data.get("caption_credits") or []
    if not credits:
        return line
    return f"{line}\n\nFor the caption: {' · '.join(credits)}"


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
    pictures = pictures + cast_pictures(job)  # a dialogue video's cast references, after the chat's own
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
    aspect = aspect_of(job)
    segment = timed.segment_of(job.data)
    timed_seconds = None
    if segment is not None:
        timed_seconds = segment.seconds
    kit = brand.kit_of(job.data, job.folder)  # None for a video without a brand kit
    script = script_of(job)
    if script is None:
        written = await writer.write(job.topic, job.minutes, job.brief, job.folder, turn, browser, listing=listing,
                                     assets_script=assets_script, aspect=aspect, timed_seconds=timed_seconds, kit=kit)
    else:
        look = job.data["dialogue"].get("look", "")
        staging = dialogue.staging(script, characters_of(job), look)
        written = await writer.write(job.topic, job.minutes, job.brief, job.folder, turn, browser, listing=listing,
                                     assets_script=assets_script, aspect=aspect, staging=staging)
    job.title = jobs.title_after_writing(written.title, job)
    job.data["narration"] = written.narration
    job.data["body"] = written.body
    job.data["cues"] = written.cues
    if written.segment is not None:
        job.data["timed_scenes"] = list(written.segment)
    if kit is not None:
        job.data["brand_vars"] = written.brand_vars


MAX_CAST_PICTURES = 3  # reference pictures per character a video carries
MAX_CAST_PICTURES_IN_ALL = 6  # and in all, after the chat's own pictures


def characters_of(job: jobs.Job) -> list[cast_module.Character]:
    """A dialogue video's cast as make_video kept it; [] for a video without one."""
    kept = job.data.get("dialogue") or {}
    return [cast_module.from_data(data) for data in kept.get("cast", [])]


def cast_pictures(job: jobs.Job) -> list[assets.Given]:
    """The cast's reference pictures as picture lines only Odie writes ("cast:<path>", odie.decks.photos reads them),
    for those who speak in it, a few per character and MAX_CAST_PICTURES_IN_ALL in all, named for whose they are:
    Mira's refs/mira-front.jpg -> ("cast:/…/refs/mira-front.jpg", "Mira: a reference picture of how they look
    (mira-front.jpg)"). A video without a cast -> []."""
    script = script_of(job)
    speakers = set(script.speakers()) if script is not None else set()
    out = []
    for character in characters_of(job):
        if character.id not in speakers:
            continue  # on a sheet in the folder, but not in this video
        for path in character.pictures()[:MAX_CAST_PICTURES]:
            words = f"{character.display_name}: a reference picture of how they look ({path.name})"
            out.append(assets.Given(address=f"cast:{path}", words=words, credit="", cast=True))
    return out[:MAX_CAST_PICTURES_IN_ALL]


def script_of(job: jobs.Job) -> dialogue.Script | None:
    """A dialogue video's script, as make_video kept it; None for any other video (and every video before
    dialogue), which then takes the narrator's path exactly as before. {"dialogue": {"script": [...]}} -> that
    script; {} -> None."""
    kept = job.data.get("dialogue")
    if not kept:
        return None
    return dialogue.from_data(kept["script"])


def timeline_record(job: jobs.Job, script: dialogue.Script, starts: list[float], lengths: list[float],
                    lines: list[dict]) -> dict:
    """What timeline.json keeps, so the work can be re-voiced or re-cut elsewhere: the title, each scene's place
    (where, start, length) and each line's (index, scene, speaker, voice, text, start, dur), in seconds into the
    video."""
    scenes = [{"number": number + 1, "where": scene.where, "start": starts[number], "length": lengths[number]}
              for number, scene in enumerate(script.scenes)]
    kept_lines = [{"index": line["index"], "scene": line["scene"], "speaker": line["speaker"], "voice": line["voice"],
                   "text": line["text"], "start": line["t"], "dur": line["dur"]} for line in lines]
    return {"title": job.title, "scenes": scenes, "lines": kept_lines}


def placed_lines(spoken: list[dict], starts: list[float]) -> list[dict]:
    """The spoken lines put on the video's timeline: each line's seconds into its scene ("at") plus its scene's start,
    as "t". A line 1.5 s into scene 1, which starts at 0 -> t 1.5; the first line of scene 2 starting at 3.0 -> 3.0."""
    out = []
    for line in spoken:
        placed = {key: value for key, value in line.items() if key != "at"}
        placed["t"] = round(starts[line["scene"] - 1] + line["at"], 3)
        out.append(placed)
    return out


async def keep_stills(mp4: Path, lines: list[dict], folder: Path, slug: str) -> None:
    """One still of each speaker from the finished video, kept in the cast folder's refs/stills/ for the user to use
    as a reference later: the frame in the middle of their first line, as refs/stills/<id>-<video>.jpg (Mira's first
    line at 4.0 s for 2.0 s, in "lighthouse" -> refs/stills/mira-lighthouse.jpg, the frame at 5.0 s). A file already
    there is never overwritten; a still that can't be made is logged: it never fails the video."""
    firsts: dict[str, dict] = {}
    for line in lines:
        if line["speaker"] != dialogue.NARRATOR and line["speaker"] not in firsts:
            firsts[line["speaker"]] = line
    if not firsts:
        return
    stills = folder / "refs" / "stills"
    try:
        stills.mkdir(parents=True, exist_ok=True)
    except OSError:
        log.warning("video: no refs/stills folder in the cast folder %s", folder, exc_info=True)
        return
    for speaker, line in firsts.items():
        at = round(line["t"] + line["dur"] / 2, 3)
        still = stills / f"{speaker}-{slug}.jpg"
        if still.exists():
            continue
        code, stderr = await run([ffmpeg(), "-n", "-loglevel", "error", "-ss", f"{at}", "-i", str(mp4),
                                  "-frames:v", "1", "-q:v", "3", str(still)])
        if code != 0:
            log.warning("video: the still of %s couldn't be made: %s", speaker, tail(stderr))


def wants_sounds(job: jobs.Job) -> bool:
    """Decides whether the page's sound cues are mixed into this video: yes unless the chat turned sounds off for it.
    A job with no "sounds" in its data (the default, and every job made before the switch) -> True;
    {"sounds": False} -> False, and the video has its narration only."""
    return job.data.get("sounds", True)


def end_chime(timings: dict, kit_sounds: dict[str, Path] | None = None) -> list[sounds.Placed]:
    """Odie's chime for a video with a timed segment, as its clock reaches 0 on the segment's last word; it rings on
    past that scene's end (into the blink, the pause or the closing card after it) and stops where the video does.
    Timings with {"timed": {"start": 6.5, "seconds": 60, "end": 66.5}} -> [the chime at 66.5 s]; any other video ->
    []. A brand kit's own "chime" (`kit_sounds`) rings instead of Odie's."""
    clock = timings.get("timed")
    if not clock:
        return []
    _sound, sound_path = sounds.lookup("chime", kit_sounds)
    file = sounds.readable_format(sound_path)
    if file is None:
        log.info("video: the chime's file is missing, so the segment ends without it")
        return []
    zero = clock["end"]
    video_end = timings["starts"][-1] + timings["lengths"][-1]
    file_seconds = file.frames / file.rate
    seconds = round(min(file_seconds, video_end - zero), 3)
    if seconds <= 0:
        return []
    chime = sounds.Placed(start=zero, path=sound_path, seconds=seconds, gain=sounds.cue_gain({}, "hit"), kind="hit",
                          name="chime", frames=file.frames, cut=seconds < round(file_seconds, 3))
    sounds.loudness_dbfs(chime)  # measured now, and remembered for the mix
    return [chime]


async def voice_track(job: jobs.Job, narration_wav: Path, timings: dict, kit: brand.Kit | None = None,
                      order: list | None = None) -> Path:
    """The sound mux lays under the picture: the narration with the page's sound cues mixed under it (mix.wav), or
    the narration as it is when there is nothing to mix. A job without cues, with sounds off, or whose cues all drop
    (odie.video.sounds.resolve) -> narration.wav, and ffmpeg doesn't run for it. A mix that fails is logged and the
    video keeps its narration: a sound never fails a video. A video with a timed segment also gets Odie's chime as its
    clock reaches 0 (end_chime). With a brand kit, the timings hold its bookends too (`order`, brand.scene_order): the
    writer's cues are moved to their scenes' places among them, the kit's sounds play instead of Odie's of the same
    name, and its bookends' own sounds are added (brand.bookend_sounds)."""
    if not wants_sounds(job):
        return narration_wav
    cues = job.data.get("cues", [])
    narrated_scenes = len(job.data["narration"])  # the timings may end with Odie's silent credits card
    kit_sounds = None
    if kit is not None:
        cues = brand.cues_in_order(cues, order)
        narrated_scenes = order.index(narrated_scenes) + 1  # where the writer's last scene plays
        kit_sounds = kit.sounds
    placed = sounds.resolve(cues, timings, narrated_scenes, kit_sounds)
    placed += end_chime(timings, kit_sounds)
    if kit is not None:
        placed += brand.bookend_sounds(kit, timings, order)
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
    web pictures or clips, their credits get a card of Odie's own after the writer's last scene (a reel's go in the
    caption instead, credits_on_screen; CREDITS_SECONDS,
    silent): one more scene in the timings than the narration has, and the voice padded to the picture's end. The
    page's sound cues are mixed under the narration (voice_track) before mux. The video is drawn at its aspect's size
    (aspect_of, timeline.size_of), and a finished file of any other size is refused. A video with a timed segment
    (odie.video.timed: job.data["timed_segment"], and the scenes the writer marked, "timed_scenes") has only that
    segment's voice fitted to its seconds, first word to last (timed.fit; too far off fails the video in words), the
    segment clock in its timings (the page's window.ODIE_TIMED), and the chime at 0; when the segment ends the
    narration, its last scene holds timed.BLINK longer for the blink. Every other scene, and every other video, keeps
    its natural length. A video with a brand kit (odie.video.brand, its copy in the job's folder) gets the kit's
    bookends put into its timeline after the fit (brand.lay_out: the handoff speaking the writer's line, the ending,
    the card), the kit drawn in its page, and the kit's sounds in its mix; its ending replaces the blink's hold."""
    folder = job.folder
    kit = brand.kit_of(job.data, folder)
    narration = job.data["narration"]
    body = job.data["body"]
    size = timeline.size_of(aspect_of(job))
    style = job.data.get("style", "")  # a job queued before styles has none: Odie's usual voice
    script = script_of(job)
    spoken_lines = []
    if script is None:
        wav, lengths, beats = await narrate(jobs.hooks["store"], narration, job.voice_name, transport=transport,
                                            style=style)
    else:
        voices = job.data["dialogue"].get("voices", {})
        wav, lengths, beats, spoken_lines = await narrate_dialogue(jobs.hooks["store"], script, voices,
                                                                   transport=transport, style=style,
                                                                   narrator_voice=job.voice_name)
    gaps = [timeline.BREATH] * (len(lengths) - 1)
    clock = None
    fitted_scenes = None  # the timed segment's first and last scene, once its voice is fitted
    segment = timed.segment_of(job.data)
    marked = job.data.get("timed_scenes")
    if segment is not None and not marked:
        log.warning("video %r: a timed segment was asked for but no scenes are marked; made at its free length",
                    job.slug)
    if segment is not None and marked:
        first, last = marked
        fitted = await timed.fit(wav, lengths, beats, first, last, segment, folder)
        wav = fitted.wav
        lengths = fitted.lengths
        beats = fitted.beats
        gaps = fitted.gaps  # the segment's breaths were sped or slowed with it
        clock = fitted.clock
        fitted_scenes = (first, last)
        holds_blink = not brand.has(kit, "ending")  # a kit's ending plays there instead
        if timed.ends_the_video(last, len(narration)) and holds_blink:
            lengths[last] = round(lengths[last] + timed.BLINK, 3)
            wav = timed.blink_silence(wav)

    gathered = assets_from(job)
    credits = credits_on_screen(job, assets.credits(gathered))  # a reel's go in the caption instead
    credits_script = credits_scene(credits)
    if credits:
        lengths = lengths + [CREDITS_SECONDS]
        beats = beats + [[0.0]]
        gaps = gaps + [timeline.BREATH]
    order = None
    brand_script = ""
    if kit is None:
        starts, _total = timed.starts_with_gaps(lengths, gaps)
    else:
        spoken = await bookend_lines(job, kit, transport, around_segment=fitted_scenes is not None)
        laid = brand.lay_out(wav, lengths, beats, gaps, clock, fitted_scenes, len(narration), kit, spoken)
        wav = laid.wav
        starts = laid.starts
        lengths = laid.lengths
        beats = laid.beats
        clock = laid.clock
        order = laid.order
        branded = brand.Branded(kit, job.data.get("brand_vars", {}))
        brand_script = brand.page_script(branded, timed_video=fitted_scenes is not None)
    timings = {"starts": starts, "lengths": lengths, "beats": beats}
    if clock is not None:
        timings["timed"] = clock

    narration_wav = folder / "narration.wav"
    narration_wav.write_bytes(wav)
    sound_wav = await voice_track(job, narration_wav, timings, kit, order)
    assets_script = assets.staple(gathered)
    lines_script = ""
    if script is not None:
        lines = placed_lines(spoken_lines, starts)
        lines_script = dialogue.lines_script(lines)
        record = timeline_record(job, script, starts, lengths, lines)
        (folder / TIMELINE).write_text(json.dumps(record, indent=1, ensure_ascii=False), encoding="utf-8")
    page_html = assemble(body, timings, assets_script, credits_script, size=size, brand_script=brand_script,
                         lines_script=lines_script)
    (folder / "page.html").write_text(page_html, encoding="utf-8")

    if script is None:
        segments = await render(browser, body, timings, folder, timeline.FPS, timeline.TABS,
                                assets_script=assets_script, credits_script=credits_script, size=size,
                                brand_script=brand_script)
    else:
        segments = await render(browser, body, timings, folder, timeline.FPS, timeline.TABS,
                                assets_script=assets_script, credits_script=credits_script, size=size,
                                brand_script=brand_script, lines_script=lines_script)
    mp4 = folder / f"{job.slug}.mp4"
    await mux(segments, sound_wav, mp4)

    info = await probe(mp4)
    if not info["video"] or not info["audio"]:
        raise EncodeError("The finished file is missing its picture or its sound.")
    made = (info["width"], info["height"])
    if made != size:
        raise EncodeError(f"The finished file is {made[0]}x{made[1]}, not {size[0]}x{size[1]}.")
    if script is not None and job.data["dialogue"].get("cast_folder"):  # only a video that came out right
        await keep_stills(mp4, lines, Path(job.data["dialogue"]["cast_folder"]), job.slug)
    return mp4


async def bookend_lines(job: jobs.Job, kit: brand.Kit, transport, around_segment: bool) -> dict[str, bytes]:
    """Each speaking bookend's line, spoken in the video's voice and style at natural speed: a handoff that says
    "intro", with the writer's {"intro": "Here is the short version."} -> {"handoff": <its WAV>}; a kit whose bookends
    say nothing -> {}. The handoff and ending go only around a fitted timed segment, so without one
    (`around_segment` False) their lines aren't spoken."""
    kit_vars = job.data.get("brand_vars", {})
    style = job.data.get("style", "")
    spoken = {}
    for name, bookend in kit.bookends.items():
        line = kit_vars.get(bookend.says, "")
        if not bookend.says or not line.strip():
            continue
        placed_around_segment = name in ("handoff", "ending")
        if placed_around_segment and not around_segment:
            continue
        wav, _lengths, _beats = await narrate(jobs.hooks["store"], [line], job.voice_name, transport=transport,
                                              style=style)
        spoken[name] = wav
    return spoken


async def make(job: jobs.Job, browser, transport) -> dict:
    """The making step: the MP4, handed over for the chat; returns its media (the player under the message)."""
    mp4 = await make_video(job, browser, transport)
    handed = hand_over(mp4, job.title)
    return handed["media"]


# Errors whose words are written for the user: the voice isn't running, ffmpeg's complaint, the browser's, the
# pictures over what a video can carry, a brand kit that is missing or broken.
KNOWN_ERRORS = (voice.VoiceUnavailable, EncodeError, BrowserError, assets.AssetProblem, brand.KitProblem)
KIND = jobs.Kind(word="video", folder=FOLDER, write=write, make=make, known_errors=KNOWN_ERRORS,
                 needs_writing=needs_writing, ready_text=ready_text)
jobs.KINDS["video"] = KIND
