"""The deck as one kind of thing Odie makes in the background (odie.making.jobs): its writing step is the deck writer
(odie.making.deck_writer), which turns the topic, theme and brief (and, for a revision, the earlier deck) into a title,
the deck Markdown and a theme; its making step builds that with Odie's deck code (odie.decks.build.make_deck: the
PowerPoint, and with a browser the PDF and slide previews) and posts the deck's card. Importing this module registers
the kind as "deck", with its jobs under <workspace>/decks/<slug>/ (job.json and brief.md); the deck's own files go
where make_deck has always put them, in the workspace itself, so a later revision finds its .deck.md there.

job.data carries, from the chat tool: "theme" (the chat's choice), "earlier" (the revised deck's Markdown, or "")
and "private" (the signed-in sites the asking chat had read); from the writing step: "markdown" and "theme"."""
import logging

from odie.agent import turn as chat_turn
from odie.decks import build
from odie.decks.model import parse
from odie.making import deck_writer, jobs

log = logging.getLogger("odie.making.deck")

FOLDER = "decks"
WORD = "deck"
WEB_PHOTOS_LEFT_OUT = "It was built without its web photos, because this chat is private."


class DeckNotBuilt(Exception):
    """The deck code said why it couldn't build the deck ("The deck couldn't be built (ValueError: …)…"), in words
    the user can be told."""


async def write(job: jobs.Job, turn, browser) -> None:
    """The writing step: the deck writer's focused turn, then the title, the Markdown and the theme onto the job. A
    revision keeps the earlier deck's title (the job's title) when the writer gives none. A deck's writer never uses
    the browser."""
    written = await deck_writer.write(job.topic, job.brief, job.data["theme"], turn, earlier=job.data["earlier"],
                                      title=job.title)
    job.title = jobs.title_after_writing(written.title, job)
    job.data["markdown"] = written.markdown
    job.data["theme"] = written.theme


async def make(job: jobs.Job, browser, transport) -> dict:
    """The making step: the written deck built by make_deck with its own browser (Odie's, when there is one; without
    one the PowerPoint still arrives). Returns the deck's card for the message; a deck that can't be built is a
    DeckNotBuilt with make_deck's words.

    The build runs as the asking chat was: a private chat (one that read a signed-in site) fetches no photos from the
    web, as make_deck does within a private chat turn. The queue's worker runs in an empty context of its own, so the
    asking chat's sites are set here from the job, empty ones included."""
    private = chat_turn.PRIVATE.set(set(job.data["private"]))
    try:
        built = await build.make_deck(job.data["markdown"], job.title, job.data["theme"])
    finally:
        chat_turn.PRIVATE.reset(private)

    if "error" in built:
        raise DeckNotBuilt(built["error"])
    log.info("deck %s: %s", job.slug, built["result"])  # it names any photos that couldn't be fetched
    return built["media"]


def web_photos_left_out(job: jobs.Job) -> bool:
    """Decides whether the deck was built without photos it asked for from the web: the asking chat was private (it
    had read a signed-in site, so make fetched nothing from the web) and the deck has an image: line with a web
    address. Private, "image: https://example.com/moon.jpg" -> True; private, no image: lines -> False; a public
    chat with that photo -> False (it was fetched); private, only "image: screenshot:abc" -> False (Odie's own
    screenshot, used in any chat)."""
    if not job.data["private"]:
        return False
    for address, _credit in parse(job.data["markdown"]).photo_refs():
        if address.startswith(("http://", "https://")):
            return True
    return False


def ready_text(job: jobs.Job) -> str:
    """The ready message: "The deck about Tides is ready.", and, when its web photos were left out because the chat is
    private, one more sentence saying so (otherwise the slides arrive with no photos and no word why)."""
    line = jobs.ready_line(WORD, job.title)
    if web_photos_left_out(job):
        return f"{line} {WEB_PHOTOS_LEFT_OUT}"
    return line


# Errors whose words are written for the user: the deck code's reasons the deck can't be built.
KNOWN_ERRORS = (DeckNotBuilt,)
KIND = jobs.Kind(word=WORD, folder=FOLDER, write=write, make=make, known_errors=KNOWN_ERRORS, ready_text=ready_text)
jobs.KINDS["deck"] = KIND
