"""The documents skill's tools: a designed deck (PDF and PowerPoint) made in the background from the chat's brief, or a
Word document made from Markdown and handed to the chat as a download (odie.agent.tools.files).

make_deck checks the request within the chat turn (instantly) and puts the deck in Odie's background queue
(odie.making.jobs, kind "deck" from odie.making.deck) with the chat's brief, kept as the job's brief.md. In the
background the writer (odie.making.deck_writer) writes the slides from the brief (and, for a revision, the earlier
deck); then the deck is built and its card posted to this chat with a ping. Plain trusted code of a built-in skill: no
shell, no approval card."""
import math
from pathlib import Path

from google.adk.tools import FunctionTool, ToolContext

from odie.agent.context import session_id_of
from odie.agent.tools.files import _free, hand_over, in_workspace, safe_name, workspace
from odie.agent.turn import file_asked, private_sites
from odie.decks.model import DeckError, parse
from odie.decks.themes import THEMES
from odie.making import chat, deck, jobs
from odie.skills.documents import build

NOT_ASKED = ("The user didn't ask for {what} or a file: answer here in chat instead, drawn with visual blocks (a timeline, a table, tiles, a chart). Make {what} only when they ask for one.")

DEFAULT_THEME = "editorial"
WRITING_MINUTES = (1, 2)  # the writer's turn: about a minute or two for a deck of 5 to 12 slides
BUILDING_SECONDS = (20, 60)  # the PowerPoint, PDF and previews: about 20 seconds, up to a minute with photos to fetch
WORD = "deck"
DOING = "writing the slides, then building the PDF and the PowerPoint"  # the middle of the reply: what making it is
DECK_ENDING = ".deck.md"
FILE_ENDINGS = (DECK_ENDING, ".pptx", ".pdf")  # the files a deck is saved as; revise may name it by any of them

NO_TOPIC = 'Give the topic: a few words saying what the deck is about, like "A weekend in Coorg".'
NOT_A_NAME = ('revise is the name of an earlier deck in the workspace, as its files are named ("Meghalaya Trip '
              'Guide"), not a path; got "{name}".')
NO_SUCH_DECK = 'There\'s no deck called "{name}" in the workspace. {decks} Leave revise empty to make a new deck.'


def _save(data: bytes, name: str, ext: str, title: str) -> dict:
    name = name.replace("/", "-").replace("\\", "-")  # a title, not a path: "Pros/Cons" keeps both words
    try:
        path = _free(workspace(), f"{safe_name(name)}.{ext}")
        path.write_bytes(data)
        return hand_over(path, title)
    except OSError as e:
        return {"error": f"The file couldn't be saved ({e.strerror or type(e).__name__})."}


def minutes_to_make() -> tuple[int, int]:
    """The estimate told to the user, as (low, high) whole minutes: the writing (1 to 2 minutes) plus the building
    (about 20 seconds, up to a minute with photos), the building rounded up to a whole minute: 1 + 1 -> 2 and 2 + 1 ->
    3, told as "about 2–3 minutes"."""
    low_writing, high_writing = WRITING_MINUTES
    low_building = math.ceil(BUILDING_SECONDS[0] / 60)
    high_building = math.ceil(BUILDING_SECONDS[1] / 60)
    return low_writing + low_building, high_writing + high_building


def theme_problem(theme: str) -> str | None:
    """Decides whether the theme is one of the four: "warm" -> None; "neon" -> "There's no theme called neon: use one
    of editorial, minimal, warm, bold."."""
    if theme in THEMES:
        return None
    return f"There's no theme called {theme}: use one of {', '.join(THEMES)}."


def deck_name(revise: str) -> str:
    """The deck's name as revise gives it, without the ending of one of its files: " Tides " -> "Tides";
    "Tides.deck.md", "Tides.pptx" or "Tides.pdf" -> "Tides"; "Pros-Cons (2)" -> the same."""
    name = revise.strip()
    for ending in FILE_ENDINGS:
        if name.lower().endswith(ending):
            return name[: -len(ending)]
    return name


def is_plain_name(name: str) -> bool:
    """Decides whether revise names a deck rather than a path, so it can only ever point at a file in the workspace
    itself: "Meghalaya Trip Guide" or "Pros-Cons (2)" -> True; "../x", "notes/Tides", "..\\Tides", "~Tides",
    "/etc/hosts" or "" -> False."""
    if not name:
        return False
    if "/" in name or "\\" in name or ".." in name or "\x00" in name:
        return False
    if name.startswith("~"):
        return False
    return True


def earlier_deck(name: str) -> Path | None:
    """The .deck.md of the workspace's deck called `name`, or None when there is none: "Tides" with
    <workspace>/Tides.deck.md there -> that path; with none, or with one that is a link leading out of the workspace
    -> None."""
    path = in_workspace(f"{name}{DECK_ENDING}")
    if path is None or not path.is_file():
        return None
    return path


def decks_there() -> str:
    """The workspace's decks by name, for the refusal: "The decks there: Moon, Tides."; with none, "There are no decks
    there yet."."""
    names = sorted(path.name[: -len(DECK_ENDING)] for path in workspace().glob(f"*{DECK_ENDING}"))
    if not names:
        return "There are no decks there yet."
    return f"The decks there: {', '.join(names)}."


def deck_title(markdown: str, name: str) -> str:
    """The title a revised deck already has: its first slide's title ("# Tides\\n…" -> "Tides"); a .deck.md the deck
    parser can't read (edited by hand) goes by its name."""
    try:
        return parse(markdown).title
    except DeckError:
        return name


async def make_deck(topic: str, brief: str = "", theme: str = "editorial", revise: str = "",
                    tool_context: ToolContext | None = None) -> dict:
    """Make a designed deck: a PDF and an editable PowerPoint with slide previews, posted to this chat. A separate
    writer writes the slides from your brief, in the background; it can't see this chat, the user's notes, memory or
    the web, and can't search for photos.
    topic: what it's about, short ("A weekend in Coorg", "Nvidia's Q2").
    brief: the angle, the slides' points in order, the facts it must use, and the photo addresses with their credits
    that find_images or the browser gave you (only those can go on the slides). Up to 6,000 characters.
    theme: editorial (dark, great with photos), minimal (clean white: research, business), warm (cream), bold (strong
    colour: pitches).
    revise: to change a deck made earlier, its name ("Meghalaya Trip Guide"); the brief then says what to change.
    It returns at once. {"error": …}: fix exactly that and call again. {"result": …}: the deck is being made; reply in
    one or two lines as the result says, and don't repeat the brief."""
    if not file_asked("deck"):
        return {"error": NOT_ASKED.format(what="a deck")}

    topic = chat.text_or_empty(topic).strip()
    brief = chat.text_or_empty(brief)
    theme = chat.text_or_empty(theme).strip().lower()
    revise = chat.text_or_empty(revise)
    if not theme:
        theme = DEFAULT_THEME

    if not topic:
        return {"error": NO_TOPIC}

    problem = chat.brief_problem(brief, WORD)
    if problem:
        return {"error": problem}

    problem = theme_problem(theme)
    if problem:
        return {"error": problem}

    title = topic
    earlier = ""
    if revise.strip():
        name = deck_name(revise)
        if not is_plain_name(name):
            return {"error": NOT_A_NAME.format(name=revise)}
        path = earlier_deck(name)
        if path is None:
            return {"error": NO_SUCH_DECK.format(name=name, decks=decks_there())}
        earlier = path.read_text(encoding="utf-8")
        title = deck_title(earlier, name)

    folder = chat.free_folder(workspace() / deck.FOLDER, chat.slug_of(topic, WORD))
    folder.mkdir(parents=True)
    data = {"theme": theme, "earlier": earlier, "private": sorted(private_sites())}
    job = jobs.Job(kind="deck", slug=folder.name, title=title, topic=topic, brief=brief,
                   session_id=session_id_of(tool_context), folder=folder, data=data)
    place = jobs.submit(job)
    low, high = minutes_to_make()
    return {"result": chat.reply(place, low, high, DOING)}


async def make_document(markdown: str, title: str = "") -> dict:
    """Make a Word document from Markdown and attach it to the chat: "#" and "##" headings, paragraphs with **bold**
    and *italic*, "- " and "1. " lists, "| a | b |" tables, "---" for a page break. `title` names the file (else the
    first heading)."""
    if not file_asked("document"):
        return {"error": NOT_ASKED.format(what="a document")}
    blocks = build.blocks_from_markdown(markdown)
    if not blocks:
        return {"error": "There's nothing to put in the document: pass its text as Markdown."}
    try:
        data = build.build_doc(blocks)
    except Exception as e:  # noqa: BLE001
        return {"error": f"The document couldn't be built: {e}"}
    first = next((b["text"] for b in blocks if b["type"] == "heading"), "Document")
    return _save(data, title or first, "docx", title)


TOOLS = [FunctionTool(make_deck), FunctionTool(make_document)]
