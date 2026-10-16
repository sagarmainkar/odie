"""The explainer-video skill's tool: make_video checks the request within the chat turn (instantly) and puts the video
in line (odie.video.jobs). In the background the writer (odie.video.writer) turns the topic, length and brief into the
narration and the page; then the video is narrated, rendered and posted to this chat. The chat only briefs the video.
Plain trusted code of a built-in skill: no shell, no approval card."""
import re
from pathlib import Path

from google.adk.tools import FunctionTool, ToolContext

from odie import voice
from odie.agent.context import session_id_of
from odie.agent.tools.files import safe_name, workspace
from odie.browser import find
from odie.video import jobs, timeline

NARRATING_SPEED = 10  # seconds of speech the voice narrates in a second
JOINING_SECONDS = 10  # joining the segments and the sound into the MP4
WRITING_MINUTES = 2  # the writer's turn (live: about 100 s for a 7-scene page, from a ~4.7k-token prompt)
SCENE_SECONDS = 20  # a scene lasts about this long, for counting the breaths between scenes before there are any
ESTIMATE_SPREAD = 2  # the range told is N to N + 2 minutes: writing time varies the most
MIN_MINUTES = 1
DEFAULT_MINUTES = 2
MAX_BRIEF_CHARACTERS = 6000

NO_BROWSER = ("An explainer video needs Chrome, Edge, Brave or Chromium on this computer to draw its frames, and none "
              "was found. Tell the user to install one (any of them) and ask again.")
NO_TOPIC = 'Give the topic: a few words saying what the video is about, like "How attention works".'
AFTER_THE_ESTIMATE = ("It'll appear in this chat, with a ping on the phone, as soon as it's ready. Tell the user that "
                      "in one or two lines, and that they can keep chatting meanwhile.")


def slug_of(title: str) -> str:
    """The title as a folder name: lower case, words joined by hyphens, only a-z, 0-9 and hyphens.
    "Speculative decoding" -> "speculative-decoding"; "TCP/IP, explained" -> "tcp-ip-explained"; "!!!" -> "video"."""
    no_slashes = title.replace("/", " ").replace("\\", " ")  # safe_name would keep only what follows a slash
    lowered = safe_name(no_slashes).lower()
    hyphenated = re.sub(r"\s+", "-", lowered)
    kept = re.sub(r"[^a-z0-9-]", "", hyphenated)
    slug = re.sub(r"-{2,}", "-", kept).strip("-")
    if not slug:
        return "video"
    return slug


def free_folder(root: Path, slug: str) -> Path:
    """The folder for a new video: root/slug, or root/slug-2, root/slug-3 … when earlier videos have those, so an
    earlier video's folder is never reused or overwritten. "attention" with videos/attention there -> attention-2."""
    folder = root / slug
    number = 2
    while folder.exists():
        folder = root / f"{slug}-{number}"
        number += 1
    return folder


def making_seconds(speech_seconds: float, frames: int) -> float:
    """How long making a video takes, in seconds: narrating its speech (10 seconds of speech a second), drawing its
    frames (timeline.RENDER_RATE a second) and joining them (10 s). The first live run, 96.25 s of speech in a 98.75 s
    video of 2,963 frames -> 9.6 + 42.3 + 10 = 62 s."""
    narrating = speech_seconds / NARRATING_SPEED
    drawing = frames / timeline.RENDER_RATE
    return narrating + drawing + JOINING_SECONDS


def minutes_to_make(minutes: int) -> int:
    """The low end of the estimate told to the user, in whole minutes: 2 minutes of writing, plus making a video of
    that length (rounded to the nearest minute, at least 1). The scenes aren't written yet, so it counts one scene per
    20 seconds and a 0.5 s breath between scenes.
    2 minutes of video: 120 s of speech in 6 scenes, 122.5 s with the 5 breaths, 3,675 frames -> 12 + 52.5 + 10 =
    74.5 s -> 1 minute of making + 2 of writing -> 3, told as "about 3–5 minutes". 6 minutes: 203.9 s -> 3 + 2 -> 5."""
    speech_seconds = minutes * 60
    scenes = max(1, round(speech_seconds / SCENE_SECONDS))
    breaths = (scenes - 1) * timeline.BREATH
    frames = timeline.frame_count(speech_seconds + breaths, timeline.FPS)
    seconds = making_seconds(speech_seconds, frames)
    making = max(1, round(seconds / 60))
    return WRITING_MINUTES + making


def reply(place: int, low: int) -> str:
    """What the model is told once the video is in line, with low = minutes_to_make. Place 1 (nothing else being
    made), low 3 -> "Making it now: about 3–5 minutes (writing …). …"; place 2 (one being made already), low 3 ->
    "It's number 2 in line, about 3–5 minutes after the one before. …". Either way it says the video comes to this
    chat with a ping, and that the chat stays free."""
    high = low + ESTIMATE_SPREAD
    if place <= 1:
        return (f"Making it now: about {low}–{high} minutes (writing the script and the animation, then drawing it). "
                f"{AFTER_THE_ESTIMATE}")
    return f"It's number {place} in line, about {low}–{high} minutes after the one before. {AFTER_THE_ESTIMATE}"


def minutes_problem(minutes) -> str | None:
    """Decides whether the length can be made: a whole number of minutes from 1 to 6 -> None; 0, 7 or 2.5 -> the
    range, as words to act on ("… from 1 to 6 …, not 7"). True/False are not lengths, though Python counts them as
    numbers."""
    is_whole = isinstance(minutes, int) and not isinstance(minutes, bool)
    if is_whole and MIN_MINUTES <= minutes <= timeline.MAX_MINUTES:
        return None
    given = f"not {minutes}"
    if isinstance(minutes, str):
        given = f"got the text '{minutes}'"
    return (f"minutes is the video's length in whole minutes, from {MIN_MINUTES} to {timeline.MAX_MINUTES} (the "
            f"user's length, else 2), {given}.")


def minutes_as_given(minutes):
    """The length the model meant, before it is checked. Some models send numbers as text or leave an optional
    argument null: "2" or " 3 " -> 2 or 3; None -> 2 (the default). Anything else is passed on unchanged for
    minutes_problem to judge: 4 -> 4; "two", "2.5" or "²" (a digit to str.isdigit, but not a number int() reads) ->
    the same text, refused there as text."""
    if minutes is None:
        return DEFAULT_MINUTES
    if isinstance(minutes, str) and minutes.strip().isdecimal():
        return int(minutes.strip())
    return minutes


def text_or_empty(value) -> str:
    """An optional text argument the model may have sent as null: None -> ""; "Michael" -> "Michael"."""
    if value is None:
        return ""
    return value


def brief_problem(brief: str) -> str | None:
    """Decides whether the brief is short enough for the writer: up to 6,000 characters -> None; 6,001 -> the limit,
    as words to act on."""
    if len(brief) <= MAX_BRIEF_CHARACTERS:
        return None
    return (f"The brief is {len(brief):,} characters; it can be at most {MAX_BRIEF_CHARACTERS:,}. Keep only what the "
            "video needs: who it's for, the key points in order, the examples and the facts it must use.")


async def make_video(topic: str, minutes: int = 2, brief: str = "", voice_name: str = "",
                     tool_context: ToolContext | None = None) -> dict:
    """Make a narrated, animated explainer video that plays in this chat. A separate writer makes the narration and
    the animation from your brief, in the background; it can't see this chat, the user's notes, memory or the web.
    topic: what the video is about, short ("How attention works").
    minutes: its length, from 1 to 6: the user's length, else 2.
    brief: everything the writer needs: who it's for and their level, the key points in order, examples, numbers or
    formulas that must appear, and any facts from this chat or the user's notes. Up to 6,000 characters.
    voice_name: leave empty; only when the user asks for a voice, one of the Settings engine's voices.
    It returns at once. {"error": …}: fix exactly that and call again. {"result": …}: the video is being made; reply
    in one or two lines as the result says, and don't repeat the brief."""
    if find.browser_binary() is None:
        return {"error": NO_BROWSER}

    topic = text_or_empty(topic)
    brief = text_or_empty(brief)
    voice_name = text_or_empty(voice_name)
    minutes = minutes_as_given(minutes)

    title = topic.strip()
    if not title:
        return {"error": NO_TOPIC}

    problem = minutes_problem(minutes)
    if problem:
        return {"error": problem}

    problem = brief_problem(brief)
    if problem:
        return {"error": problem}

    voice_id = ""
    if voice_name.strip():
        try:
            voice_id = voice.voice_in_chosen_engine(jobs.hooks["store"], voice_name)["id"]
        except ValueError as e:
            return {"error": str(e)}

    folder = free_folder(workspace() / "videos", slug_of(title))
    folder.mkdir(parents=True)
    job = jobs.Job(slug=folder.name, title=title, topic=title, minutes=minutes, brief=brief,
                   session_id=session_id_of(tool_context), voice_name=voice_id, folder=folder)
    place = jobs.submit(job)
    return {"result": reply(place, minutes_to_make(minutes))}


TOOLS = [FunctionTool(make_video)]
