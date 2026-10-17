"""The podcast skill's tool: make_podcast checks the request within the chat turn (instantly) and puts the podcast in
Odie's background queue (odie.making.jobs, kind "podcast" from odie.making.podcast) with the chat's brief and the
sources it named (odie.making.sources, word for word), kept as the job's brief.md. In the background the writer
(odie.making.podcast_writer) turns the topic, length and brief into a two-host script; then the script is spoken in
two voices and posted to this chat with a ping. The chat only briefs the podcast. Plain trusted code of a built-in
skill: no shell, no approval card."""
import math

from google.adk.tools import FunctionTool, ToolContext

from odie import voice
from odie.agent.context import session_id_of
from odie.agent.tools.files import workspace
from odie.making import chat, jobs, podcast
from odie.making import sources as making_sources

MIN_MINUTES = 1
MAX_MINUTES = 10
DEFAULT_MINUTES = 4
LOCAL_SPEED = 10  # minutes of speech Kokoro speaks in a minute, on this computer
CLOUD_SPEED = 1  # OpenAI's voice speaks about as fast as the podcast plays
WRITING_MINUTES = (1, 2)  # the writer's turn: about a minute or two for a script of a few hundred words
WORD = "podcast"
DOING = "writing the script, then speaking it in two voices"  # the middle of the reply: what making it involves

NO_TOPIC = 'Give the topic: a few words saying what the podcast is about, like "How vaccines train the immune system".'
def speaking_speed(engine: str) -> int:
    """Decides how fast the podcast is spoken, in minutes of podcast a minute, from the engine chosen in Settings:
    "openai" -> 1 (about real time, over the network); "kokoro" -> 10 (on this computer); "maya1" -> 10 too, because
    a podcast with Maya1 chosen is spoken by Kokoro (voice.podcast_voices)."""
    if engine == "openai":
        return CLOUD_SPEED
    return LOCAL_SPEED


def speaking_minutes(minutes: int, engine: str) -> int:
    """Whole minutes the voice takes to speak the podcast, rounded up: 4 minutes with Kokoro -> 0.4 -> 1; 4 minutes
    with OpenAI -> 4."""
    return math.ceil(minutes / speaking_speed(engine))


def minutes_to_make(minutes: int, engine: str) -> tuple[int, int]:
    """The estimate told to the user, as (low, high) whole minutes: the writing (1 to 2 minutes) plus the speaking.
    4 minutes with Kokoro -> 1–2 + 1 -> (2, 3), told as "about 2–3 minutes"; with OpenAI -> 1–2 + 4 -> (5, 6)."""
    speaking = speaking_minutes(minutes, engine)
    low_writing, high_writing = WRITING_MINUTES
    return low_writing + speaking, high_writing + speaking


async def make_podcast(topic: str, minutes: int = 4, brief: str = "", sources: list[str] | None = None,
                       tool_context: ToolContext | None = None) -> dict:
    """Make a podcast the user can play in this chat: two hosts (a woman, then a man) talking a topic through,
    NotebookLM style. A separate writer writes the script from your brief, in the background; it can't see this chat,
    the user's notes, memory or the web.
    topic: what it's about, short ("How vaccines train the immune system", "Our session on the move to Pune").
    minutes: its length, from 1 to 10: the user's length, else 4.
    brief: the angle, the key points in order, and the facts from this chat or the notes it must use (for a podcast
    of this conversation: its decisions, questions and surprises). Up to 6,000 characters.
    sources: what the user gave, passed to the writer word for word (never retype it): "my message" (the user's
    latest message), a note's name or path in their vault, or a text file's path in Odie's workspace. Up to 5.
    It returns at once. {"error": …}: fix exactly that and call again. {"result": …}: the podcast is being made; reply
    in one or two lines as the result says, and don't repeat the brief."""
    topic = chat.text_or_empty(topic)
    brief = chat.text_or_empty(brief)
    minutes = chat.minutes_as_given(minutes, DEFAULT_MINUTES)

    title = topic.strip()
    if not title:
        return {"error": NO_TOPIC}

    problem = chat.minutes_problem(minutes, MIN_MINUTES, MAX_MINUTES, WORD, DEFAULT_MINUTES)
    if problem:
        return {"error": problem}

    problem = chat.brief_problem(brief, WORD)
    if problem:
        return {"error": f"{problem} {chat.USE_SOURCES}"}

    try:
        references = making_sources.sources_as_given(sources)
        found = making_sources.resolve(references, jobs.hooks["store"])
    except making_sources.SourceProblem as e:
        return {"error": str(e)}

    folder = chat.free_folder(workspace() / podcast.FOLDER, chat.slug_of(title, WORD))
    folder.mkdir(parents=True)
    whole_brief = making_sources.brief_with_sources(brief, found)
    job = jobs.Job(kind="podcast", slug=folder.name, title=title, topic=title, minutes=minutes, brief=whole_brief,
                   session_id=session_id_of(tool_context), folder=folder)
    place = jobs.submit(job)
    engine, _voice_id = voice.get_tts(jobs.hooks["store"])
    low, high = minutes_to_make(minutes, engine)
    return {"result": chat.reply(place, low, high, DOING)}


TOOLS = [FunctionTool(make_podcast)]
