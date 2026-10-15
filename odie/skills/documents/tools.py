"""The documents skill's tools: Markdown in, a PowerPoint deck or a Word document out, handed to the chat as a
download (odie.agent.tools.files)."""
from google.adk.tools import FunctionTool

from odie.agent.tools.files import _free, hand_over, safe_name, workspace
from odie.agent.turn import file_asked
from odie.decks import build as decks
from odie.skills.documents import build


NOT_ASKED = ("The user didn't ask for {what} or a file: answer here in chat instead, drawn with visual blocks (a timeline, a table, tiles, a chart). Make {what} only when they ask for one.")


def _save(data: bytes, name: str, ext: str, title: str) -> dict:
    name = name.replace("/", "-").replace("\\", "-")  # a title, not a path: "Pros/Cons" keeps both words
    try:
        path = _free(workspace(), f"{safe_name(name)}.{ext}")
        path.write_bytes(data)
        return hand_over(path, title)
    except OSError as e:
        return {"error": f"The file couldn't be saved ({e.strerror or type(e).__name__})."}


async def make_slides(markdown: str, title: str = "", theme: str = "editorial") -> dict:
    """Make a designed deck: a PDF and an editable PowerPoint with slide previews, under your reply. "# Title" starts
    each slide (the first is the cover). On a slide: "kicker: …", "image: <photo address a tool returned> (credit: …)",
    "- **Lead** — rest" bullets, "## Name" cards (with image: and meta: lines), "1. Step — detail" steps, "stat: value —
    label", a ```chart block, "quote: \"…\" — who", "> " speaker notes, "| a | b |" tables. Photos are optional.
    theme: editorial (dark, great with photos), minimal (clean white: research, business), warm (cream), bold (strong
    colour: pitches). The documents skill lists the layouts."""
    if not file_asked("deck"):
        return {"error": NOT_ASKED.format(what="a deck")}
    return await decks.make_deck(markdown, title, theme)


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


TOOLS = [FunctionTool(make_slides), FunctionTool(make_document)]
