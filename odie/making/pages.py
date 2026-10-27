"""Reading the user's own pages for an audio story (the audio-story skill's read_pages): photos of a book's pages,
sent in the chat, made into one text in reading order, for the story writer to adapt.

Each photo goes to the user's chosen chat model, one call a page, with one fixed instruction (TRANSCRIBE): the page's
words exactly, nothing else. A page the model has read is kept beside its upload (uploads/{id}.txt), so asking again
for fewer pages costs no second reading.

Photos are read at the size the chat keeps them (1280 px on the long edge, odie.app.images). Measured on 27 Oct with
DeepSeek V4.1 Flash on phone photos of paperback pages: 10 pt and 8 pt pages, and a two-page spread in 7 pt, all came
back word for word at 1280 px; only a 7 pt spread shot from far off (the book a third of the frame) went wrong, and
it went wrong at 2400 px too (names misread). So the upload size stays as it is."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from odie.app.images import ID_RE, load_image, uploads_dir

PAGES_AT_ONCE = 4  # pages the model reads at the same time
SOURCE_PREFIX = "pages-"
SOURCE_ID = re.compile(r"^pages-[0-9a-f]{10}$")
UPLOAD_ID = re.compile(r"[0-9a-f]{32}")
TRANSCRIBE = ("Transcribe the printed text in this photo of a book page exactly, word for word. Keep the paragraphs (a "
              "blank line between them), the punctuation and the quotation marks as printed. Leave out running heads, "
              "page numbers and footnotes. If the photo shows two pages, write the left page, then the right. Write "
              "only the page's text: no comments, no headings, no Markdown.")
CANT_SEE = "Your chat model can't read photos. Choose a model that can see images."
# Words a provider uses when it refuses a picture, or a model uses when it was given one it can't see.
CANT_SEE_WORDS = ("image", "vision", "multimodal", "unknown variant", "can't see", "cannot see", "unable to see",
                  "can't view", "cannot view", "unable to view")
NOT_A_LIST = "sources is a list of the photos' upload ids in reading order, from the [image:…] marks in the chat."

# Which user message each source was read in (source id -> that message), so make_audio_story can tell when the user
# hasn't answered the cast form yet. Kept here, not in the skill's tools.py, which is loaded afresh with each agent.
READ_IN: dict[str, str | None] = {}

# The model call that reads one page: the JPEG in, the page's words out (Odie's is model_reads, below).
Reader = Callable[[bytes], Awaitable[str]]


class PagesProblem(Exception):
    """A page that can't be read. The message is the words the chat model is told."""


@dataclass
class Page:
    """One photo to read: what the user calls it ("photo 2"), the JPEG, and where the model's reading is kept."""
    label: str
    image: bytes
    kept: Path


@dataclass
class Reading:
    """What read_pages found: each page's text in order, with its label, and whether they ran past the most a story
    can take (then the pages after that weren't read)."""
    texts: list[str]
    labels: list[str]
    past_the_limit: bool = False


# Which pages.

def sources_as_given(sources) -> list[str]:
    """The upload ids the model meant: a list as it is; ids in text (one, or a JSON-looking list) -> those ids; None or
    anything else -> PagesProblem. ["ab…", "cd…"] -> the same; '["ab…"]' -> ["ab…"]."""
    if isinstance(sources, list) and sources:
        return [str(item).strip() for item in sources]
    if isinstance(sources, str):
        found = UPLOAD_ID.findall(sources)
        if found:
            return found
    raise PagesProblem(NOT_A_LIST)


def page_of(upload_id: str, number: int, directory: Path | None = None) -> Page:
    """The photo an upload id names, as "photo {number}" (its place in sources); an id that isn't a photo's ->
    PagesProblem."""
    if directory is None:
        directory = uploads_dir()
    if not ID_RE.match(upload_id):
        raise PagesProblem(f'"{upload_id}" isn\'t an upload id. {NOT_A_LIST}')
    photo = load_image(upload_id, directory)
    if photo is None:
        raise PagesProblem(f"There is no photo with the id {upload_id}: use the ids from the chat's [image:…] marks.")
    return Page(label=f"photo {number}", image=photo[0], kept=directory / f"{upload_id}.txt")


# Reading.

def cant_see(said: str) -> bool:
    """Decides whether a failed or odd reading means the model can't take pictures: the provider's refusal or the
    model's own words. "litellm.BadRequestError: … does not support image input" -> True; "I can't see images." ->
    True; "Connection reset" -> False."""
    lowered = said.lower()
    return any(word in lowered for word in CANT_SEE_WORDS)


async def model_reads(store, image: bytes) -> str:
    """One page read by the user's chosen chat model (the same litellm path as the brief and memory review), the
    JPEG sent inline with TRANSCRIBE."""
    from odie.models import chat_completion
    picture = "data:image/jpeg;base64," + base64.b64encode(image).decode()
    content = [{"type": "text", "text": TRANSCRIBE}, {"type": "image_url", "image_url": {"url": picture}}]
    return await chat_completion(store, "chat", [{"role": "user", "content": content}], temperature=0)


async def read_one(page: Page, reader: Reader) -> str:
    """One page's words: what the model read before (kept), else the model reads it now and it is kept. A model that
    can't take pictures -> PagesProblem(CANT_SEE); an empty reading -> PagesProblem asking for a clearer photo."""
    if page.kept.exists():
        return page.kept.read_text(encoding="utf-8")
    try:
        said = await reader(page.image)
    except Exception as e:  # noqa: BLE001  any provider's refusal, told by its words
        if cant_see(str(e)):
            raise PagesProblem(CANT_SEE) from e
        raise PagesProblem(f"I couldn't read {page.label}: {type(e).__name__}. Try again in a moment.") from e
    said = said.strip()
    if not said:
        raise PagesProblem(f"{page.label.capitalize()} came back empty: ask the user for a clearer photo of it, closer "
                           "and in good light.")
    if len(said) < 200 and cant_see(said):
        raise PagesProblem(CANT_SEE)
    page.kept.write_text(said, encoding="utf-8")
    return said


def word_count(text: str) -> int:
    """Words as the length is sized: "Go back to the house, Elsie." -> 6."""
    return len(text.split())


async def read(pages: list[Page], reader: Reader, max_words: int) -> Reading:
    """The pages' words in order, PAGES_AT_ONCE at a time, stopping once they run past max_words (the pages after
    that aren't read)."""
    texts: list[str] = []
    labels: list[str] = []
    for start in range(0, len(pages), PAGES_AT_ONCE):
        batch = pages[start:start + PAGES_AT_ONCE]
        said = await asyncio.gather(*(read_one(page, reader) for page in batch))
        texts.extend(said)
        labels.extend(page.label for page in batch)
        if sum(word_count(text) for text in texts) > max_words:
            return Reading(texts=texts, labels=labels, past_the_limit=True)
    return Reading(texts=texts, labels=labels)


def pages_that_fit(texts: list[str], max_words: int) -> int:
    """How many pages, from the first, fit in max_words: pages of 300, 300 and 300 words in 700 -> 2; a first page
    over it alone -> 0."""
    total = 0
    for count, text in enumerate(texts):
        total += word_count(text)
        if total > max_words:
            return count
    return len(texts)


def source_id(text: str) -> str:
    """The id the story finds the text by: its hash, "pages-3fa9c1d2e4"; the same pages give the same id."""
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()
    return f"{SOURCE_PREFIX}{digest[:10]}"


def source_path(folder: Path, source: str) -> Path | None:
    """Where a source's text is kept in the stories folder, or None for a source that isn't an id read_pages gave:
    "pages-3fa9c1d2e4" -> folder/pages-3fa9c1d2e4.txt; "../notes" -> None."""
    if not SOURCE_ID.match(source):
        return None
    return folder / f"{source}.txt"
