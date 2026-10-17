"""The deck writer: one focused model turn, in the background, that writes a deck in Odie's deck Markdown.

It runs on the shared writer harness (odie.making.writer). It sees only deck_writer.md (the slide Markdown, the
layouts, the themes, the photos) and one tool, submit_deck, which takes the title, the whole deck and the theme at
once. The deck is checked by the deck parser (odie.decks.model.parse, whose DeckError words go back as they are), its
theme by name, and its photo addresses: the writer can't search, so every image: address must be one the brief gave
(or, for a revision, one the earlier deck had). A problem goes back to the writer to fix. An accepted deck or a third
refusal ends the turn there and then; a writer that stops without either is nudged once, in the same session. The
turn ends with the accepted deck (Written) or WriterFailed."""
import re
from dataclasses import dataclass
from pathlib import Path

from odie.decks.model import DeckError, parse
from odie.decks.themes import THEMES
from odie.making import writer as harness
from odie.making.chat import text_or_empty

INSTRUCTION = Path(__file__).with_name("deck_writer.md").read_text(encoding="utf-8")

# The address on a deck's "image:" line: "image: https://x.com/a.jpg (credit: Ana)" -> "https://x.com/a.jpg".
IMAGE_LINE = re.compile(r"^\s*image:\s*(\S+)", re.IGNORECASE | re.MULTILINE)
# A photo address written anywhere in a brief: a web address, or a browser screenshot's or the user's photo's id.
ADDRESS = re.compile(r"(?:https?://|screenshot:|upload:)[^\s<>\"'()\[\]]+", re.IGNORECASE)
CLOSING_PUNCTUATION = ".,;:!?"

PLAN_THEN_WRITE = "Plan in a few lines, then call submit_deck with the title, the whole deck and the theme."
PLAN_THEN_REVISE = "Plan in a few lines, then call submit_deck with the title, the whole revised deck and the theme."
KEEP_THE_REST = ("This revises an earlier deck. Keep everything the changes don't touch: its slides, words, photos and "
                 "credits.")
LINES = harness.Lines(
    nudge=("You haven't called submit_deck yet. Stop planning: write the deck now, as it is, and call submit_deck "
           "with the title, the whole deck and the theme."),
    nudge_after_problem=("submit_deck hasn't accepted the deck yet. Its last answer was: {problem} Fix exactly that "
                         "and call submit_deck again with the title, the whole fixed deck and the theme."),
    never_submitted="I couldn't write the deck (the writer stopped without one).",
    not_passed="I couldn't write a deck that passed its check: {problem}",
)
SUBMIT_DOC = ('Submit the whole deck at once: title (short, about the topic), markdown (the deck, every slide starting '
              'with "# ") and theme (editorial, minimal, warm or bold). It checks the slides, the theme and that '
              "every image: address is one the brief gave.\n"
              '{"error": …}: fix exactly that and call submit_deck again with the whole fixed deck.\n'
              '{"result": "Accepted."}: the deck is done.')
SUBMIT_FIELDS = {"title": str, "markdown": str, "theme": str}


@dataclass
class Written:
    """The accepted deck: its title, its Markdown and its theme's name."""
    title: str
    markdown: str
    theme: str


def addresses_in(text: str) -> list[str]:
    """Every photo address written in the text, in order, each once: web addresses and screenshot:/upload: ids,
    without the brackets or closing punctuation around them. "Cover: <https://a.com/1.jpg>, credit Pexels. Map:
    screenshot:ab12;" -> ["https://a.com/1.jpg", "screenshot:ab12"]."""
    found = []
    for match in ADDRESS.finditer(text):
        address = match.group(0).rstrip(CLOSING_PUNCTUATION)
        if address not in found:
            found.append(address)
    return found


def photo_problem(markdown: str, allowed: list[str]) -> str | None:
    """Decides whether every photo in the deck is one the writer was given: each image: line's address must be in
    `allowed` (the brief's addresses, and a revised deck's). With ["https://a.com/1.jpg"]: "image: https://a.com/1.jpg
    (credit: Ana)" -> None; "image: https://example.com/made-up.jpg" -> "https://example.com/made-up.jpg isn't a photo
    address the brief gave, … Use only these, with their credits: https://a.com/1.jpg. …"; with [] any image: line ->
    "… The brief gave no photo addresses, so no image: lines: take them out, …"."""
    invented = []
    for address in IMAGE_LINE.findall(markdown):
        if address not in allowed and address not in invented:
            invented.append(address)
    if not invented:
        return None

    named = ", ".join(invented)
    if len(invented) == 1:
        said = f"{named} isn't a photo address the brief gave"
    else:
        said = f"{named} aren't photo addresses the brief gave"
    said += ", and you can't search or make one up."
    if not allowed:
        return (f"{said} The brief gave no photo addresses, so no image: lines: take them out, then call submit_deck "
                f"again with the whole deck.")
    return (f"{said} Use only these, with their credits: {', '.join(allowed)}. Or leave the photo out. Then call "
            f"submit_deck again with the whole deck.")


def theme_problem(theme: str) -> str | None:
    """Decides whether the theme is one of the four, in any case: "minimal" or "Bold" -> None; "neon" -> "There's no
    theme called neon: use one of editorial, minimal, warm, bold."."""
    if theme.strip().lower() in THEMES:
        return None
    return f"There's no theme called {theme}: use one of {', '.join(THEMES)}."


def theme_given(theme, default: str) -> str:
    """The theme the writer chose, as its own name, or the one it was given when it sent none: "Bold" -> "bold";
    None or "" with default "warm" -> "warm"."""
    chosen = text_or_empty(theme).strip().lower()
    if not chosen:
        return default
    return chosen


def submission_problem(markdown: str, theme: str, allowed: list[str]) -> str | None:
    """Decides whether a deck can be accepted: the first problem as words to fix, or None. The slides first (the deck
    parser's own words: nine bullets on slide 2 -> "Slide 2 has 9 bullets; keep 6 or split it."), then the photos
    (photo_problem), then the theme (theme_problem). Two plain slides, no photos, "minimal" -> None."""
    try:
        parse(markdown)
    except DeckError as e:
        return str(e)
    problem = photo_problem(markdown, allowed)
    if problem:
        return problem
    return theme_problem(theme)


def prompt_for(topic: str, brief: str, theme: str, earlier: str = "") -> str:
    """The writer's whole message: the topic, the theme, then the brief and what to do. For a revision (`earlier` is
    the earlier deck's Markdown) the earlier deck comes first and the brief is "What to change"."""
    heading = (f"Topic: {topic}\n"
               f"Theme: {theme} (submit with it unless the brief asks for another)\n\n")
    brief_text = brief.strip()
    if not earlier.strip():
        if not brief_text:
            brief_text = "(none: use what you know about the topic, and no photos)"
        return f"{heading}Brief:\n{brief_text}\n\n{PLAN_THEN_WRITE}"

    if not brief_text:
        brief_text = "(nothing named: tidy what reads badly, and keep the rest)"
    return (f"{heading}{KEEP_THE_REST}\n\n"
            f"The earlier deck:\n<deck>\n{earlier.strip()}\n</deck>\n\n"
            f"What to change:\n{brief_text}\n\n"
            f"{PLAN_THEN_REVISE}")


def tools_for(desk: harness.Desk, theme: str, allowed: list[str]) -> list:
    """The writer's one tool, submit_deck (title, markdown, theme), built by the shared harness on `desk`. Its check is
    submission_problem with the photo addresses in `allowed`; accepting makes the Written deck, the title falling back
    to the desk's topic and the theme to `theme`."""

    async def check(fields: dict) -> str | None:
        markdown = text_or_empty(fields["markdown"])
        chosen = theme_given(fields["theme"], theme)
        return submission_problem(markdown, chosen, allowed)

    def accept(fields: dict) -> Written:
        title = harness.title_given(fields["title"], desk.topic)
        markdown = text_or_empty(fields["markdown"])
        return Written(title=title, markdown=markdown, theme=theme_given(fields["theme"], theme))

    return [harness.submit_tool(desk, "submit_deck", SUBMIT_DOC, SUBMIT_FIELDS, check, accept)]


async def write(topic: str, brief: str, theme: str, turn, earlier: str = "", title: str = "") -> Written:
    """Writes the deck in one focused turn: `turn(prompt, instruction, tools, timeout, follow_up=…)` is
    runner.focused_turn in Odie. `earlier` is the Markdown of the deck being revised ("" for a new deck), and `title`
    the title to keep when the writer gives none (the topic when it is ""). Photos may come only from the brief and
    the earlier deck. Returns the accepted deck; raises WriterFailed when there's none, with the deck's words (LINES),
    or the harness's time-limit line (see odie.making.writer.write)."""
    fallback_title = title.strip()
    if not fallback_title:
        fallback_title = topic
    desk = harness.Desk(topic=fallback_title)
    allowed = addresses_in(f"{brief}\n{earlier}")
    [tool] = tools_for(desk, theme, allowed)
    return await harness.write(desk, prompt_for(topic, brief, theme, earlier), INSTRUCTION, tool, LINES, turn)
