"""The explainer-video skill's tool: make_video checks the request and the page within the chat turn (seconds), then
puts the video in line to be narrated, rendered and posted to this chat in the background (odie.video.jobs). Plain
trusted code of a built-in skill: no shell, no approval card."""
import re
from pathlib import Path

from google.adk.tools import FunctionTool, ToolContext

from odie import voice
from odie.agent.context import session_id_of
from odie.agent.tools.files import safe_name, workspace
from odie.browser import find, render_browser
from odie.browser.engine import BrowserError, BrowserTimeout
from odie.video import jobs, timeline
from odie.video import page as video_page

SCENE_CHARACTERS = 4000  # the most narration one scene may have (one piece of speech)
MAX_SCENES = 40  # the most scenes a video may have (a 6-minute video needs far fewer)
MAX_PAGE_KB = 300  # the largest page body, in kilobytes (the worked example is about 3)
NARRATING_SPEED = 10  # seconds of speech the voice narrates in a second
JOINING_SECONDS = 10  # joining the segments and the sound into the MP4
ESTIMATE_SPREAD = 1  # the range told is N to N + 1 minutes, so it isn't a promise

NO_BROWSER = ("An explainer video needs Chrome, Edge, Brave or Chromium on this computer to draw its frames, and none "
              "was found. Tell the user to install one (any of them) and ask again.")
HANG = "The page didn't finish drawing in time (a loop that never ends?): "
AFTER_THE_ESTIMATE = ("It'll appear in this chat, with a ping on the phone, as soon as it's ready. Tell the user that "
                      "in one or two lines, and that they can keep chatting meanwhile; don't repeat the script.")


def narration_problem(narration: list[str]) -> str | None:
    """Decides whether the narration can be spoken as it is, before anything is drawn: the first problem as words to
    act on, or None. In this order: [] -> no narration; 41 strings -> over the 40-scene limit; ["Hi.", "  "] ->
    scene 2 has no words; ["ok.", 4,001 characters] -> scene 2 is over the 4,000-character limit; seven scenes of 140
    words (7 minutes of speech) -> over 6 minutes; ["Hi."] -> None."""
    if not narration:
        return "There's no narration: give one string of speech per scene, in order."
    if len(narration) > MAX_SCENES:
        return (f"There are {len(narration)} scenes; a video can have at most {MAX_SCENES}. Join some scenes "
                "(and their narration) together.")

    for number, text in enumerate(narration, start=1):
        if not text.strip():
            return f"There's no narration for scene {number}: every scene needs words to speak."
        if len(text) > SCENE_CHARACTERS:
            return (f"The narration of scene {number} is {len(text):,} characters; one scene can have at most "
                    f"{SCENE_CHARACTERS:,}. Split it into two scenes (and two scenes on the page) or shorten it.")

    minutes = timeline.spoken_minutes(narration)
    if minutes > timeline.MAX_MINUTES:
        return (f"The narration is about {minutes:.1f} minutes of speech; a video can be at most "
                f"{timeline.MAX_MINUTES} minutes. Shorten it (about {timeline.WORDS_PER_MINUTE} words a minute).")
    return None


def page_problem(page: str) -> str | None:
    """Decides whether the page is small enough to check and render: a body over 300 KB (in UTF-8) -> the limit, as
    words to act on; the worked example's 3 KB, or exactly 300,000 bytes -> None."""
    size = len(page.encode("utf-8"))
    if size > MAX_PAGE_KB * 1000:
        return (f"The page is {size / 1000:,.0f} KB; a page can be at most {MAX_PAGE_KB} KB. Draw with code (loops, "
                "helpers) instead of long lists of data or pasted content.")
    return None


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


def minutes_to_make(narration: list[str]) -> int:
    """The low end of the estimate told to the user, in whole minutes (the nearest, at least 1), from the words alone.
    The first live run (62 s, see making_seconds) -> 1, told as "about 1–2 minutes"; 420 words in 7 scenes (180 s of
    speech, 183 s of video with the breaths, 5,490 frames) -> 18 + 78.4 + 10 = 106.4 s -> 2, "about 2–3 minutes"."""
    lengths = video_page.estimated_timings(narration)["lengths"]
    _starts, total = timeline.scene_starts(lengths)
    seconds = making_seconds(sum(lengths), timeline.frame_count(total))
    minutes = round(seconds / 60)
    return max(1, minutes)


def reply(place: int, low: int) -> str:
    """What the model is told once the video is in line, with low = minutes_to_make. Place 1 (nothing else being
    made), low 1 -> "Making it now: about 1–2 minutes. …"; place 2 (one rendering already), low 2 -> "It's number 2 in
    line, about 2–3 minutes after the one before. …". Either way it says the video comes to this chat with a ping, and
    that the chat stays free."""
    high = low + ESTIMATE_SPREAD
    if place <= 1:
        return f"Making it now: about {low}–{high} minutes. {AFTER_THE_ESTIMATE}"
    return f"It's number {place} in line, about {low}–{high} minutes after the one before. {AFTER_THE_ESTIMATE}"


async def make_video(title: str, narration: list[str], page: str, voice_name: str = "",
                     tool_context: ToolContext | None = None) -> dict:
    """Make a narrated, animated explainer video that plays in this chat. Call it once the scenes are planned and the
    page is written, as the explainer-video skill says.
    title: the topic, short ("Speculative decoding").
    narration: one string of plain speech per scene, in order; each is spoken in the voice chosen in Settings.
    page: the HTML body: one <script> that calls Video.scenes([...]) with one scene per narration string.
    voice_name: leave empty; only when the user asks for a voice, one of the Settings engine's voices.
    It checks everything now and returns at once. {"error": …}: fix exactly that and call again. {"result": …}: the
    video is being made in the background; reply in one or two lines as the result says, and don't repeat the
    script."""
    if find.browser_binary() is None:
        return {"error": NO_BROWSER}

    problem = narration_problem(narration)
    if problem:
        return {"error": problem}

    problem = page_problem(page)
    if problem:
        return {"error": problem}

    voice_id = ""
    if voice_name.strip():
        try:
            voice_id = voice.voice_in_chosen_engine(jobs.hooks["store"], voice_name)["id"]
        except ValueError as e:
            return {"error": str(e)}

    try:
        problem = await video_page.check(page, narration, render_browser())
    except BrowserTimeout as e:
        return {"error": HANG + str(e)}
    except BrowserError as e:
        return {"error": str(e)}  # the browser's own words: "The browser didn't start …"
    if problem:
        return {"error": problem}

    folder = free_folder(workspace() / "videos", slug_of(title))
    folder.mkdir(parents=True)
    topic = title.strip()
    if not topic:
        topic = "your topic"
    job = jobs.Job(slug=folder.name, title=topic, session_id=session_id_of(tool_context),
                   narration=list(narration), body=page, voice_name=voice_id, folder=folder)
    place = jobs.submit(job)
    return {"result": reply(place, minutes_to_make(narration))}


TOOLS = [FunctionTool(make_video)]
