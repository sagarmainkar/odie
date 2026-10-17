"""The explainer-video skill's tool: make_video checks the request within the chat turn (instantly), reads the sources
the chat named (odie.making.sources: the user's message, a note, a workspace file, word for word) and puts the video in
Odie's background queue (odie.making.jobs, kind "video" from odie.video.kind) with the brief and the sources as one
text, the job's brief.md. The pictures and clips the chat found (images, clips: "address — what it shows" lines) are
checked here and go with the job, with the chat's private sites; the job fetches them before the writer runs
(odie.video.assets). A picture from the user's library that can't go in (only a small copy on this Mac) is left out
here, and the result says so, so the chat can tell the user at once. In the background the writer (odie.video.writer)
turns the topic, length, that brief and the pictures' names into the narration and the page; then the video is
narrated, rendered and posted to this chat. The chat only briefs the video. Plain trusted code of a built-in skill:
no shell, no approval card."""
import asyncio

from google.adk.tools import FunctionTool, ToolContext

from odie import voice
from odie.agent.context import session_id_of
from odie.agent.tools.files import workspace
from odie.agent.turn import private_sites
from odie.browser import find
from odie.decks import photos
from odie.making import chat, jobs
from odie.making import sources as making_sources
from odie.video import assets, kind, timeline

NARRATING_SPEED = 10  # seconds of speech the voice narrates in a second
JOINING_SECONDS = 10  # joining the segments and the sound into the MP4
MIN_WRITING_MINUTES = 2  # the writer's turn, at least (live: about 100 s for a 7-scene page, from a ~4.7k-token prompt)
SCENE_SECONDS = 20  # a scene lasts about this long, for counting the breaths between scenes before there are any
ESTIMATE_SPREAD = 2  # the range told is N to N + 2 minutes: writing time varies the most
SECONDS_A_PICTURE = 1  # fetching and preparing one picture before the writer starts
SECONDS_A_CLIP = 5  # downloading one clip and re-encoding its first 15 s (about 3 s measured, for 1080p)
MIN_MINUTES = 1
DEFAULT_MINUTES = 2
MAX_BRIEF_CHARACTERS = 20_000  # the chat model's own brief; the sources have their own limits (odie.making.sources)
WORD = "video"
DOING = "writing the script and the animation, then drawing it"  # the middle of the reply: what making it involves

NO_BROWSER = ("An explainer video needs Chrome, Edge, Brave or Chromium on this computer to draw its frames, and none "
              "was found. Tell the user to install one (any of them) and ask again.")
NO_TOPIC = 'Give the topic: a few words saying what the video is about, like "How attention works".'
LEFT_OUT = ("Left out: {pictures}. Add that to the reply in a few words, with what the user can do; the video goes "
            "on without them.")


def making_seconds(speech_seconds: float, frames: int) -> float:
    """How long making a video takes, in seconds: narrating its speech (10 seconds of speech a second), drawing its
    frames (timeline.RENDER_RATE a second) and joining them (10 s). The first live run, 96.25 s of speech in a 98.75 s
    video of 2,963 frames -> 9.6 + 42.3 + 10 = 62 s."""
    narrating = speech_seconds / NARRATING_SPEED
    drawing = frames / timeline.RENDER_RATE
    return narrating + drawing + JOINING_SECONDS


def writing_minutes(minutes: int) -> int:
    """How long the writer's turn takes, in whole minutes: about a minute per minute of video, at least 2. Live: a
    2-minute video took ~1.5 minutes -> 2; a 4-minute one with a 9,400-character source took ~5.5 -> 4 (the estimate
    told is a range of 4 + making to 2 more); 6 -> 6."""
    return max(MIN_WRITING_MINUTES, minutes)


def gathering_seconds(images: int, clips: int) -> int:
    """How long fetching and preparing the pictures and clips adds, in seconds: about a second a picture and five a
    clip. 12 pictures and 3 clips -> 12 + 15 = 27 s; 20 and 6 -> 50 s; none -> 0."""
    pictures = images * SECONDS_A_PICTURE
    moving = clips * SECONDS_A_CLIP
    return pictures + moving


def minutes_to_make(minutes: int, images: int = 0, clips: int = 0) -> int:
    """The low end of the estimate told to the user, in whole minutes: the writing (writing_minutes), plus making a
    video of that length with its pictures and clips (gathering_seconds), rounded to the nearest minute, at least 1.
    The scenes aren't written yet, so it counts one scene per 20 seconds and a 0.5 s breath between scenes.
    2 minutes of video: 120 s of speech in 6 scenes, 122.5 s with the 5 breaths, 3,675 frames -> 12 + 52.5 + 10 =
    74.5 s -> 1 minute of making + 2 of writing -> 3, told as "about 3–5 minutes". With 20 pictures and 6 clips:
    74.5 + 50 = 124.5 s -> 2 + 2 -> 4. 6 minutes: 203.9 s -> 3 + 6 -> 9."""
    speech_seconds = minutes * 60
    scenes = max(1, round(speech_seconds / SCENE_SECONDS))
    breaths = (scenes - 1) * timeline.BREATH
    frames = timeline.frame_count(speech_seconds + breaths, timeline.FPS)
    seconds = making_seconds(speech_seconds, frames) + gathering_seconds(images, clips)
    making = max(1, round(seconds / 60))
    return writing_minutes(minutes) + making


def library_pictures_left_out(lines: list[str], pictures: list[assets.Given]) -> tuple[list[str], list[str]]:
    """Decides which picture lines go to the job. A photo:<id> from the user's library that can't go in (only a small
    copy on this Mac, none at all, a video, an id the library doesn't have) is left out now, with why, so the chat can
    tell the user while they're here; every other line goes on, and the job fetches it. Gives (the lines kept, what
    was left out).
      ["photo:3F2A — us at the gate", "photo:5A11 — Tsomgo lake"], 5A11 with only a 360 px copy here ->
      (["photo:3F2A — us at the gate"], ["Tsomgo lake (photo:5A11 has only a small copy on this Mac (360 px); open
      it in Photos once so the full picture comes down)"])
      ["https://… — Red Fort"] -> kept unchecked: a web picture is the job's to fetch"""
    kept = []
    left_out = []
    for line, picture in zip(lines, pictures):
        if not picture.address.startswith("photo:"):
            kept.append(line)
            continue
        try:
            photos.library_copy(picture.address)
        except photos.PhotoError as e:
            left_out.append(f"{picture.words} ({e})")
            continue
        kept.append(line)
    return kept, left_out


async def make_video(topic: str, minutes: int = 2, brief: str = "", sources: list[str] | None = None,
                     images: list[str] | None = None, clips: list[str] | None = None, voice_name: str = "",
                     tool_context: ToolContext | None = None) -> dict:
    """Make a narrated, animated explainer video that plays in this chat. A separate writer makes the narration and
    the animation from your brief, in the background; it can't see this chat, the user's notes, memory or the web.
    topic: what the video is about, short ("How attention works").
    minutes: its length, from 1 to 6: the user's length, else 2.
    brief: the plan: who it's for and their level, the key points in order, the look, examples, numbers or formulas
    that must appear, and any facts you found. Up to 20,000 characters.
    sources: what the user gave, passed to the writer word for word (never retype it): "my message" (the user's
    latest message), a note's name or path in their vault, or a text file's path in Odie's workspace. Up to 5.
    images: pictures for the film, at most 20, each one line "address — what it shows": the address a tool gave
    (https://… from find_images, photo:<id>, upload:<id>, screenshot:<id>), then what the picture shows, its mood, its
    orientation if unusual, and a web picture's credit in brackets at the end. The writer sees only these words.
    clips: short stock clips, at most 6, the same way, with the https:// address find_clips gave.
    voice_name: leave empty; only when the user asks for a voice, one of the Settings engine's voices.
    It returns at once. {"error": …}: fix exactly that and call again. {"result": …}: the video is being made; reply
    in one or two lines as the result says, and don't repeat the brief."""
    if find.browser_binary() is None:
        return {"error": NO_BROWSER}

    topic = chat.text_or_empty(topic)
    brief = chat.text_or_empty(brief)
    voice_name = chat.text_or_empty(voice_name)
    minutes = chat.minutes_as_given(minutes, DEFAULT_MINUTES)

    title = topic.strip()
    if not title:
        return {"error": NO_TOPIC}

    problem = chat.minutes_problem(minutes, MIN_MINUTES, timeline.MAX_MINUTES, WORD, DEFAULT_MINUTES)
    if problem:
        return {"error": problem}

    problem = chat.brief_problem(brief, WORD, MAX_BRIEF_CHARACTERS)
    if problem:
        return {"error": f"{problem} {chat.USE_SOURCES}"}

    try:
        references = making_sources.sources_as_given(sources)
        found = making_sources.resolve(references, jobs.hooks["store"])
    except making_sources.SourceProblem as e:
        return {"error": str(e)}

    try:
        pictures, _moving = assets.parse(images, clips)
    except assets.AssetProblem as e:
        return {"error": str(e)}
    image_lines = assets.lines_as_given(images, "images")
    image_lines, left_out = await asyncio.to_thread(library_pictures_left_out, image_lines, pictures)
    clip_lines = assets.lines_as_given(clips, "clips")
    given = {"images": image_lines, "clips": clip_lines}

    voice_id = ""
    if voice_name.strip():
        try:
            voice_id = voice.voice_in_chosen_engine(jobs.hooks["store"], voice_name)["id"]
        except ValueError as e:
            return {"error": str(e)}

    folder = chat.free_folder(workspace() / kind.FOLDER, chat.slug_of(title, WORD))
    folder.mkdir(parents=True)
    whole_brief = making_sources.brief_with_sources(brief, found)
    data = {"given": given, "private": sorted(private_sites())}  # the job fetches as this chat would
    job = jobs.Job(kind="video", slug=folder.name, title=title, topic=title, minutes=minutes, brief=whole_brief,
                   session_id=session_id_of(tool_context), voice_name=voice_id, folder=folder, data=data)
    place = jobs.submit(job)
    low = minutes_to_make(minutes, len(image_lines), len(clip_lines))
    high = low + ESTIMATE_SPREAD
    reply = chat.reply(place, low, high, DOING)
    if left_out:
        told = LEFT_OUT.format(pictures="; ".join(left_out))
        reply = f"{reply} {told}"
    return {"result": reply}


TOOLS = [FunctionTool(make_video)]
