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
from odie.making import deck_writer, jobs

log = logging.getLogger("odie.making.deck")

FOLDER = "decks"


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
    web, as make_deck does within a private chat turn. The queue's worker keeps the context of whichever chat started
    it, so the job's own sites are set here, empty ones included."""
    private = chat_turn.PRIVATE.set(set(job.data["private"]))
    try:
        built = await build.make_deck(job.data["markdown"], job.title, job.data["theme"])
    finally:
        chat_turn.PRIVATE.reset(private)

    if "error" in built:
        raise DeckNotBuilt(built["error"])
    log.info("deck %s: %s", job.slug, built["result"])  # it names any photos that couldn't be fetched
    return built["media"]


# Errors whose words are written for the user: the deck code's reasons the deck can't be built.
KNOWN_ERRORS = (DeckNotBuilt,)
KIND = jobs.Kind(word="deck", folder=FOLDER, write=write, make=make, known_errors=KNOWN_ERRORS)
jobs.KINDS["deck"] = KIND
