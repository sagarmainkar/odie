"""The sources of anything Odie makes in the background (a video, a podcast, a deck): what the user gave (a message
pasted in the chat, a note, a file), passed to the writer word for word instead of retold in the chat model's brief,
so no detail is lost on the way.

The chat model only names them in the make tool's `sources` (make_video, make_podcast, make_deck); Odie's code reads
each one here, within the chat turn, so a source that can't be read comes back to the chat model as words to act on
before anything is queued:
  - "my message" (or "the user's message"): the user's message of this chat turn, without what Odie adds after it;
  - a text file in Odie's workspace, by its path there (an exact path, so it wins over a note's looser match);
  - a note in the user's vault, by the name or path read_note takes, read by the vault's own reader.
brief_with_sources puts them after the brief under "## Source material"; that text is the job's brief.md and the
writer's brief."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from odie.agent import turn
from odie.agent.tools.files import MAKE_TYPES, in_workspace, workspace

MAX_SOURCES = 5
MAX_SOURCE_CHARACTERS = 40_000  # one source
MAX_ALL_CHARACTERS = 60_000  # all of them together
BYTES_PER_CHARACTER = 4  # the most UTF-8 takes, so a file over 4 x 40,000 bytes is too long without reading it
TEXT_TYPES = tuple(MAKE_TYPES)  # the kinds of file make_file makes: md, txt, csv, html, json, ics, svg
USERS_MESSAGE = ("my message", "the user's message")
MESSAGE_LABEL = "The user's message"
HEADING = "## Source material"
SOURCES_SAID = ("What the user gave, word for word. Take facts, numbers and wording from it; the plan above decides "
                "what it covers.")


NOT_A_LIST = ('sources is a list of short texts: ["my message"], a note\'s name or path, or a file\'s path in Odie\'s '
              "workspace.")
NO_MESSAGE = ("The user's message isn't here (this isn't a chat turn, or it has no words), so \"my message\" can't be "
              "a source.")


class SourceProblem(Exception):
    """A source that can't be used. The message is the words the chat model is told, to fix the call."""


@dataclass
class Source:
    """One source, read: what it is called in the brief ("The user's message", "Note: Tides") and its whole text."""
    label: str
    text: str


def sources_as_given(sources) -> list:
    """The list the model meant. Some models send a list as JSON text or a single reference as text, or leave the
    argument null: None -> []; '["my message"]' -> ["my message"]; "my message" -> ["my message"];
    ["my message", "Tides"] -> the same list. Anything else (5, {"note": "Tides"}) -> SourceProblem."""
    if sources is None:
        return []
    if isinstance(sources, list):
        return sources
    if not isinstance(sources, str):
        raise SourceProblem(NOT_A_LIST)
    try:
        parsed = json.loads(sources)
    except ValueError:
        return [sources]
    if isinstance(parsed, list):
        return parsed
    return [sources]


def is_users_message(reference: str) -> bool:
    """Decides whether a reference means the user's latest message in this chat, in either form and any case:
    "my message", " The User's Message " -> True; "my messages", "notes/my message.txt" -> False."""
    return reference.strip().lower() in USERS_MESSAGE


def is_text_file(name: str) -> bool:
    """Decides whether a workspace file may be a source, by its extension: "tides.md", "table.csv", "UP.MD" -> True
    (a text type make_file makes); "photo.png", "deck.pptx", "README" (no extension) -> False."""
    extension = Path(name).suffix.lower().lstrip(".")
    return extension in TEXT_TYPES


def count_problem(references: list) -> str | None:
    """Decides whether there are few enough sources: up to 5 -> None; 6 -> the limit, as words to act on."""
    if len(references) <= MAX_SOURCES:
        return None
    return (f"There are {len(references)} sources; there can be at most {MAX_SOURCES}. Pass only the ones the "
            "thing being made is about.")


def length_problem(source: Source, reference: str) -> str | None:
    """Decides whether one source is short enough: up to 40,000 characters -> None; 40,001 -> the limit, naming the
    source ("notes/long.txt is over 40,000 characters …")."""
    if len(source.text) <= MAX_SOURCE_CHARACTERS:
        return None
    return too_long(reference)


def too_long(reference: str) -> str:
    return (f"{reference} is over {MAX_SOURCE_CHARACTERS:,} characters, the most one source can be. Put the part the "
            "writer needs in the brief instead.")


def total_problem(found: list[Source]) -> str | None:
    """Decides whether all the sources together are short enough: 30,000 + 30,000 characters -> None; 30,000 + 30,000
    + 1 -> the limit of 60,000, as words to act on."""
    total = sum(len(source.text) for source in found)
    if total <= MAX_ALL_CHARACTERS:
        return None
    return (f"The sources are {total:,} characters together; they can be at most {MAX_ALL_CHARACTERS:,}. Pass fewer, "
            "or put the parts the writer needs in the brief.")


def users_message() -> str:
    """The user's message of this chat turn, as they wrote it: the words the runner keeps for the turn's tools
    (turn.USER_TEXT). A turn resumed after an approval card gets the stored message back, so what Odie adds after the
    words (prefetched notes, the "[context: …]" note) and picture markers are taken off with the app's own helpers:
    "Tides…\\n\\n[context: now 09:30 Fri]" -> "Tides…". Background work (a tracker or watch check) has no user turn ->
    SourceProblem, as does a message with no words."""
    from odie.app.runner import split_images, strip_trailer
    said = turn.USER_TEXT.get()
    if said is None:
        raise SourceProblem(NO_MESSAGE)
    words, _pictures = split_images(strip_trailer(said))
    if not words.strip():
        raise SourceProblem(NO_MESSAGE)
    return words.strip()


def note_text(store, reference: str) -> str | None:
    """A note's whole text, read by the vault's own reader (the names and paths read_note takes), or None when the
    vault has no such note or isn't set up. A note longer than one source may be comes back just over the limit
    (the reader cuts it there), so length_problem still sees that it is too long."""
    from odie.vault import settings
    index = settings.index_for(store)
    if index is None:
        return None
    return index.read(reference, limit=MAX_SOURCE_CHARACTERS + 1)


def file_text(reference: str) -> str:
    """A text file's whole text from Odie's workspace, by its path there. Refused: a path outside the workspace, no
    file there, a file that isn't a text type, or one that isn't UTF-8 text."""
    path = in_workspace(reference)
    if path is None:
        raise SourceProblem(f"{reference} isn't a note in the vault, and it's outside Odie's workspace "
                            f"({workspace()}): a file source must be a file in the workspace.")
    if not path.is_file():
        raise SourceProblem(f"There's no note called {reference!r} in the vault and no file {reference} in Odie's "
                            "workspace. Give the note's name or path, or the file's path in the workspace.")
    if not is_text_file(path.name):
        raise SourceProblem(f"{reference} isn't a text file: a file source is one of "
                            f"{', '.join('.' + t for t in TEXT_TYPES)}.")
    if path.stat().st_size > MAX_SOURCE_CHARACTERS * BYTES_PER_CHARACTER:
        raise SourceProblem(too_long(reference))  # too long for certain, so it isn't read
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise SourceProblem(f"{reference} isn't text that can be read (not UTF-8).") from None


def is_workspace_file(reference: str) -> bool:
    """Decides whether a reference names a file that is in Odie's workspace: "tides.md" with <workspace>/tides.md
    there -> True; "Tides" (no such file), "../secret.txt" (outside) or "notes" (a folder) -> False."""
    path = in_workspace(reference)
    if path is None:
        return False
    return path.is_file()


def read_one(reference: str, store) -> Source:
    """Decides which kind a reference is and reads it, in this order: "my message" -> the user's message; a file
    that is in Odie's workspace by that path ("tides.md", made by make_file) -> that file, even when a vault note
    "Tides" would also match the name loosely; a name or path the vault finds ("Tides", "Science/Tides.md") -> that
    note; anything else -> refused, saying why (outside the workspace, or not found)."""
    name = reference.strip()
    if is_users_message(name):
        return Source(MESSAGE_LABEL, users_message())
    if is_workspace_file(name):
        return Source(f"File: {name}", file_text(name))
    note = note_text(store, name)
    if note is not None:
        return Source(f"Note: {name}", note)
    return Source(f"File: {name}", file_text(name))  # not there: file_text says why


def resolve(references: list, store) -> list[Source]:
    """Every source read, in the order given, or SourceProblem with the first problem: too many, one that isn't a
    reference (an empty text), one that can't be read, one too long, or all of them too long together."""
    problem = count_problem(references)
    if problem:
        raise SourceProblem(problem)
    found = []
    for reference in references:
        if not isinstance(reference, str) or not reference.strip():
            raise SourceProblem('Each source is a short text: "my message", a note\'s name or path, or a file\'s '
                                "path in Odie's workspace.")
        source = read_one(reference, store)
        problem = length_problem(source, reference.strip())
        if problem:
            raise SourceProblem(problem)
        found.append(source)
    problem = total_problem(found)
    if problem:
        raise SourceProblem(problem)
    return found


def brief_with_sources(brief: str, found: list[Source]) -> str:
    """The brief the writer reads (and brief.md holds): the chat model's brief, then, when there are sources, a
    "## Source material" section with each one under its own heading, word for word. No sources -> the brief as it is.
    "For a ten-year-old." and the user's message "Tides…" -> "For a ten-year-old.\\n\\n## Source material\\n\\n…\\n\\n
    ### The user's message\\n\\nTides…"."""
    plan = brief.strip()
    if not found:
        return plan
    pieces = []
    if plan:
        pieces.append(plan)
    pieces.append(f"{HEADING}\n\n{SOURCES_SAID}")
    for source in found:
        pieces.append(f"### {source.label}\n\n{source.text.strip()}")
    return "\n\n".join(pieces)
