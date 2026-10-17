"""The research skill's tool: make_research checks the request within the chat turn (instantly) and puts the research
in Odie's background queue (odie.making.jobs, kind "research" from odie.making.research) with the chat's brief and the
sources it named (odie.making.sources, word for word), kept as the job's brief.md. In the background the writer
(odie.making.research_writer) searches the web and the user's notes, reads what matters and writes a report with its
sources; the report is posted to this chat as a Markdown file with a ping. The chat only briefs the research. Plain
trusted code of a built-in skill: no shell, no approval card."""
from google.adk.tools import FunctionTool, ToolContext

from odie.agent.context import session_id_of
from odie.agent.tools.files import workspace
from odie.making import chat, jobs, research
from odie.making import sources as making_sources
from odie.signin import guard

# The estimate told to the user, in minutes: a few searches and pages read, then the report written. It doesn't
# depend on anything the chat knows, so it is the same range every time.
LOW_MINUTES = 5
HIGH_MINUTES = 15
WORD = "research"
DOING = "searching and reading, then writing"  # the middle of the reply: what making it involves

NO_TOPIC = 'Give the topic: a few words saying what to research, like "Which kettle to buy for a family of four".'
PRIVATE_CHAT = ("This chat is private (it read a signed-in site), and research searches the web and reads pages, which "
                "a private chat asks about each time, so I can't research it here. Tell the user to ask for the "
                "research outside the private chat (a new chat).")


def is_private_chat(store) -> bool:
    """Decides whether research is refused here: the writer searches and reads pages in the background, with nobody
    to tap the approval card a private chat shows before each search (guard.query_needs_tap). A chat that read the
    user's amazon.in orders, with signed-in browsing on -> True, refused; a chat that read no signed-in page, or
    signed-in browsing off -> False, queued."""
    return guard.query_needs_tap(store)


async def make_research(topic: str, brief: str = "", sources: list[str] | None = None,
                        tool_context: ToolContext | None = None) -> dict:
    """Research a question in the background and post a report (a Markdown file) to this chat: a separate writer
    searches the web and the user's notes, reads what matters and writes the answer with its sources. Use it for
    anything time-consuming that is mostly reading: research, look into, compare, find out, a report on. The writer
    can't see this chat or the user's memory.
    topic: what to find out, short ("Which kettle to buy for a family of four").
    brief: the question as the user means it, what matters to them, what is known already (facts from this chat),
    what to skip, and where to look (their notes, sites they trust). Up to 6,000 characters.
    sources: what the user gave, passed to the writer word for word (never retype it): "my message" (the user's
    latest message), a note's name or path in their vault, or a text file's path in Odie's workspace. Up to 5.
    It returns at once. {"error": …}: fix exactly that and call again (in a private chat, tell the user what it says).
    {"result": …}: the research is being made; reply in one or two lines as the result says, and don't repeat the
    brief."""
    if is_private_chat(jobs.hooks["store"]):
        return {"error": PRIVATE_CHAT}

    topic = chat.text_or_empty(topic)
    brief = chat.text_or_empty(brief)

    title = topic.strip()
    if not title:
        return {"error": NO_TOPIC}

    problem = chat.brief_problem(brief, WORD)
    if problem:
        return {"error": f"{problem} {chat.USE_SOURCES}"}

    try:
        references = making_sources.sources_as_given(sources)
        found = making_sources.resolve(references, jobs.hooks["store"])
    except making_sources.SourceProblem as e:
        return {"error": str(e)}

    folder = chat.free_folder(workspace() / research.FOLDER, chat.slug_of(title, WORD))
    folder.mkdir(parents=True)
    whole_brief = making_sources.brief_with_sources(brief, found)
    job = jobs.Job(kind="research", slug=folder.name, title=title, topic=title, brief=whole_brief,
                   session_id=session_id_of(tool_context), folder=folder)
    place = jobs.submit(job)
    return {"result": chat.reply(place, LOW_MINUTES, HIGH_MINUTES, DOING)}


TOOLS = [FunctionTool(make_research)]
