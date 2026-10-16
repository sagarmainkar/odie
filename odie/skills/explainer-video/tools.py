"""The explainer-video skill's tool: make_video checks the request within the chat turn (instantly) and puts the video
in Odie's background queue (odie.making.jobs, kind "video" from odie.video.kind). In the background the writer
(odie.video.writer) turns the topic, length and brief into the narration and the page; then the video is narrated,
rendered and posted to this chat. The chat only briefs the video. Plain trusted code of a built-in skill: no shell, no
approval card."""
from google.adk.tools import FunctionTool, ToolContext

from odie import voice
from odie.agent.context import session_id_of
from odie.agent.tools.files import workspace
from odie.browser import find
from odie.making import chat, jobs
from odie.video import kind, timeline

NARRATING_SPEED = 10  # seconds of speech the voice narrates in a second
JOINING_SECONDS = 10  # joining the segments and the sound into the MP4
WRITING_MINUTES = 2  # the writer's turn (live: about 100 s for a 7-scene page, from a ~4.7k-token prompt)
SCENE_SECONDS = 20  # a scene lasts about this long, for counting the breaths between scenes before there are any
ESTIMATE_SPREAD = 2  # the range told is N to N + 2 minutes: writing time varies the most
MIN_MINUTES = 1
DEFAULT_MINUTES = 2
WORD = "video"
DOING = "writing the script and the animation, then drawing it"  # the middle of the reply: what making it involves

NO_BROWSER = ("An explainer video needs Chrome, Edge, Brave or Chromium on this computer to draw its frames, and none "
              "was found. Tell the user to install one (any of them) and ask again.")
NO_TOPIC = 'Give the topic: a few words saying what the video is about, like "How attention works".'


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

    problem = chat.brief_problem(brief, WORD)
    if problem:
        return {"error": problem}

    voice_id = ""
    if voice_name.strip():
        try:
            voice_id = voice.voice_in_chosen_engine(jobs.hooks["store"], voice_name)["id"]
        except ValueError as e:
            return {"error": str(e)}

    folder = chat.free_folder(workspace() / kind.FOLDER, chat.slug_of(title, WORD))
    folder.mkdir(parents=True)
    job = jobs.Job(kind="video", slug=folder.name, title=title, topic=title, minutes=minutes, brief=brief,
                   session_id=session_id_of(tool_context), voice_name=voice_id, folder=folder)
    place = jobs.submit(job)
    low = minutes_to_make(minutes)
    high = low + ESTIMATE_SPREAD
    return {"result": chat.reply(place, low, high, DOING)}


TOOLS = [FunctionTool(make_video)]
