"""The research writer: one focused model turn, in the background, that searches, reads and writes one report.

It runs on the shared writer harness (odie.making.writer). It sees only research_writer.md and its tools: Odie's
web_search and web_fetch (built without the private chat's approval card: there is no chat here to show one, and
make_research is refused in a private chat), the user's notes (search_everything, read_note, related_notes) and one
submit tool, submit_research, which takes the title and the whole report in Markdown at once. The report is checked
for its length (at least 150 words) and its sources (a "## Sources" heading with a link or a note under it). A problem
goes back to the writer to fix. An accepted report or a third refusal ends the turn there and then; a writer that
stops without either is nudged once, in the same session. The turn may take up to 30 minutes, since searching and
reading take longer than writing alone. The turn ends with the accepted report (Written) or WriterFailed."""
import re
from dataclasses import dataclass
from pathlib import Path

import httpx

from odie.agent.tools.web import make_web_tools
from odie.making import writer as harness
from odie.making.chat import text_or_empty
from odie.store.db import Store
from odie.vault.tools import make_vault_tools

INSTRUCTION = Path(__file__).with_name("research_writer.md").read_text(encoding="utf-8")

RESEARCH_TIME_LIMIT = 1800  # seconds: searching and reading pages takes longer than the other kinds' writing alone
MIN_WORDS = 150
VAULT_TOOLS = ("search_everything", "read_note", "related_notes")  # the vault's reading tools (not index_status)

SOURCES_HEADING = re.compile(r"^##\s+sources\s*$", re.IGNORECASE)
TOP_HEADING = re.compile(r"^#{1,2}\s")  # a heading of the report's own level ends the Sources section
WORD = re.compile(r"\w")  # a word has a letter or a digit in it: "##" and "-" aren't words

SEARCH_THEN_WRITE = "Search and read first, then call submit_research with the title and the whole report."
NO_SOURCES_HEADING = ('The report has no "## Sources" heading. End it with "## Sources" and, under it, one per line, '
                      "the links of the pages you used and the names of the notes you used, then call "
                      "submit_research again with the whole report.")
NO_SOURCES_LISTED = ('The "## Sources" section is empty. Under it, one per line, list the links of the pages you used '
                     "and the names of the notes you used, then call submit_research again with the whole report.")
LINES = harness.Lines(
    nudge=("You haven't called submit_research yet. Stop searching: write the report now from what you have read, "
           "and call submit_research with the title and the whole report."),
    nudge_after_problem=("submit_research hasn't accepted the report yet. Its last answer was: {problem} Fix exactly "
                         "that and call submit_research again with the title and the whole fixed report."),
    never_submitted="I couldn't write the report (the writer stopped without one).",
    not_passed="I couldn't write a report that passed its check: {problem}",
)
SUBMIT_DOC = ("Submit the whole report at once: title (short, about the topic) and markdown (the report: the short "
              'answer, the findings, then "## Sources" with the links and note names you used). It checks the '
              "report's length and its sources.\n"
              '{"error": …}: fix exactly that and call submit_research again with the whole fixed report.\n'
              '{"result": "Accepted."}: the report is done.')
SUBMIT_FIELDS = {"title": str, "markdown": str}


@dataclass
class Written:
    """The accepted report: its title and its Markdown, as the writer wrote it."""
    title: str
    markdown: str


def words_in(markdown: str) -> int:
    """The report's words, Markdown marks left out: "## The answer\\n\\n- Buy the steel one." -> 6 ("##" and "-"
    aren't words; "1.7" and a link are)."""
    count = 0
    for piece in markdown.split():
        if WORD.search(piece):
            count += 1
    return count


def sources_listed(markdown: str) -> list[str] | None:
    """The lines under the report's "## Sources" heading, up to the next heading of its level, blank lines and
    sub-headings left out; None when there is no such heading. "…\\n## Sources\\n\\n- https://a.example\\n- [[Kitchen
    wishlist]]" -> ["- https://a.example", "- [[Kitchen wishlist]]"]; "## Sources\\n\\n## Notes\\n- https://…" -> [];
    no heading -> None."""
    lines = markdown.splitlines()
    start = None
    for number, line in enumerate(lines):
        if SOURCES_HEADING.match(line.strip()):
            start = number
            break
    if start is None:
        return None

    listed = []
    for line in lines[start + 1:]:
        text = line.strip()
        if TOP_HEADING.match(text):
            break
        if text and not text.startswith("#"):
            listed.append(text)
    return listed


def submission_problem(markdown: str) -> str | None:
    """Decides whether a report can be accepted: the first problem as words to fix, or None. Its length first (at
    least 150 words: a 9-word report -> "The report is 9 words; it needs at least 150. …"), then its sources: no
    "## Sources" heading -> NO_SOURCES_HEADING; the heading with nothing under it -> NO_SOURCES_LISTED; a link, a
    "[[note]]" or any line under it (a note's name) -> None."""
    words = words_in(markdown)
    if words < MIN_WORDS:
        return (f"The report is {words} words; it needs at least {MIN_WORDS}. Give the findings with their details "
                "(what each source says, the numbers, how they compare), then call submit_research again with the "
                "whole report.")
    listed = sources_listed(markdown)
    if listed is None:
        return NO_SOURCES_HEADING
    if not listed:
        return NO_SOURCES_LISTED
    return None


def prompt_for(topic: str, brief: str) -> str:
    """The writer's whole message: the topic, the brief (the question, what matters to the user, what is known
    already, the sources the user gave) and what to do."""
    brief_text = brief.strip()
    if not brief_text:
        brief_text = "(none: find out what matters most about the topic)"
    return (f"Topic: {topic}\n\n"
            f"Brief:\n{brief_text}\n\n"
            f"{SEARCH_THEN_WRITE}")


def submit_tool_for(desk: harness.Desk):
    """The writer's submit tool, submit_research (title, markdown), built by the shared harness on `desk`. Its check is
    submission_problem; accepting makes the Written report, the title falling back to the topic."""

    async def check(fields: dict) -> str | None:
        markdown = text_or_empty(fields["markdown"])
        return submission_problem(markdown)

    def accept(fields: dict) -> Written:
        title = harness.title_given(fields["title"], desk.topic)
        markdown = text_or_empty(fields["markdown"])
        return Written(title=title, markdown=markdown)

    return harness.submit_tool(desk, "submit_research", SUBMIT_DOC, SUBMIT_FIELDS, check, accept)


def reading_tools(store: Store, transport: httpx.AsyncBaseTransport | None = None) -> list:
    """What the writer reads with before it submits: web_search and web_fetch with no approval card (the turn has
    no chat to show one in), then the vault's search_everything, read_note and related_notes."""
    web = make_web_tools(store=store, transport=transport, ask_first=False)
    vault = []
    for tool in make_vault_tools(store):
        if tool.name in VAULT_TOOLS:
            vault.append(tool)
    return web + vault


async def write(topic: str, brief: str, turn, store: Store,
                transport: httpx.AsyncBaseTransport | None = None) -> Written:
    """Researches and writes the report in one focused turn: `turn(prompt, instruction, tools, timeout, follow_up=…)`
    is runner.focused_turn in Odie. Returns the accepted report; raises WriterFailed when there's none, with the
    report's words (LINES), or the harness's time-limit line for 30 minutes (see odie.making.writer.write)."""
    desk = harness.Desk(topic=topic)
    tool = submit_tool_for(desk)
    return await harness.write(desk, prompt_for(topic, brief), INSTRUCTION, tool, LINES, turn,
                               time_limit=RESEARCH_TIME_LIMIT, other_tools=reading_tools(store, transport))
