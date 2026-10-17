"""Research as one kind of thing Odie makes in the background (odie.making.jobs): its writing step is the research
writer (odie.making.research_writer), which searches the web and the user's notes and writes a report with its
sources; its making step (no AI) saves the report as <job folder>/<slug>.md and posts it as a file card. The message
with the card carries the report's short answer, so the user reads it in the chat and the chat model can answer
follow-ups from it. Importing this module registers the kind as "research", with its jobs under
<workspace>/research/<slug>/ (job.json, brief.md and the report). The report stays in the workspace, not the vault.

job.data carries "markdown" (the accepted report) from the writing step to the making step and the ready message."""
import re

from odie.agent.tools.files import hand_over
from odie.making import jobs, research_writer

FOLDER = "research"
WORD = "research"
SHORT_ANSWER_LIMIT = 600  # characters of the short answer in the ready message: a few sentences, not the report
SHORT_ANSWER_HEADING = re.compile(r"^#{1,6}\s+the short answer\s*$", re.IGNORECASE)
HEADING = re.compile(r"^#{1,6}\s")
SENTENCE_END = re.compile(r"[.!?](?=\s)")  # a full stop, ! or ? with a space after it ("1.7" isn't one)


def with_title(markdown: str, title: str) -> str:
    """The report as it is saved: with the title as its top heading, unless it starts with one of its own, and one
    closing newline. "## The short answer\\n\\nYes." and "Kettles" -> "# Kettles\\n\\n## The short answer\\n\\nYes.\\n";
    "# Kettles, compared\\n\\nYes." -> kept as it is (with its newline)."""
    report = markdown.strip()
    if report.startswith("# "):
        return report + "\n"
    return f"# {title}\n\n{report}\n"


def first_paragraph(lines: list[str]) -> str:
    """The first paragraph in these lines, headings and blank lines before it skipped, its own lines kept:
    ["", "## Findings", "", "Steel wins.", "It lasts.", "", "More."] -> "Steel wins.\nIt lasts."; only headings and
    blank lines -> ""."""
    paragraph = []
    for line in lines:
        text = line.strip()
        is_break = not text or HEADING.match(text) is not None
        if is_break and paragraph:
            break
        if not is_break:
            paragraph.append(text)
    return "\n".join(paragraph)


def cut_to_limit(text: str) -> str:
    """The text, kept whole when it is at most 600 characters; a longer one cut at the last sentence end within them
    (or, with none, at the last space), with " …" after it. 700 characters of sentences -> the sentences that fit, then
    " …"; 700 characters with no full stop -> the words that fit, then " …"."""
    if len(text) <= SHORT_ANSWER_LIMIT:
        return text
    within = text[:SHORT_ANSWER_LIMIT + 1]  # one more, so a full stop right at the limit shows its space
    ends = [match.end() for match in SENTENCE_END.finditer(within)]
    if ends:
        return text[:ends[-1]] + " …"
    words = text[:SHORT_ANSWER_LIMIT].rsplit(maxsplit=1)[0]
    return words.rstrip() + " …"


def short_answer(markdown: str) -> str:
    """The report's short answer, for the ready message: the first paragraph under its "## The short answer" heading
    (any level, any case), or, with no such heading, the report's first paragraph (after its title), cut to about 600
    characters (cut_to_limit). "# Kettles\n\n## The short answer\n\nBuy the steel one.\n\n## Findings…" -> "Buy the
    steel one."; "# Kettles\n\nSteel wins.\n\n## Findings…" -> "Steel wins."; only headings -> ""."""
    lines = markdown.splitlines()
    start = 0
    for number, line in enumerate(lines):
        if SHORT_ANSWER_HEADING.match(line.strip()):
            start = number + 1
            break
    return cut_to_limit(first_paragraph(lines[start:]))


def ready_text(job: jobs.Job) -> str:
    """The ready message: "The research about Kettles is ready.", a blank line, and the report's short answer, so the
    chat sees the answer, not only a file; a report with no paragraph to show -> the first line alone."""
    line = jobs.ready_line(WORD, job.title)
    answer = short_answer(job.data["markdown"])
    if not answer:
        return line
    return f"{line}\n\n{answer}"


async def write(job: jobs.Job, turn, browser) -> None:
    """The writing step: the research writer's focused turn (with the store the queue was given, for the web and the
    vault tools), then the title and the report onto the job. Research never uses the render browser."""
    written = await research_writer.write(job.topic, job.brief, turn, jobs.hooks["store"])
    job.title = jobs.title_after_writing(written.title, job)
    job.data["markdown"] = written.markdown


async def make(job: jobs.Job, browser, transport) -> dict:
    """The making step: the report saved as <job folder>/<slug>.md; returns its file card for the message."""
    path = job.folder / f"{job.slug}.md"
    path.write_text(with_title(job.data["markdown"], job.title), encoding="utf-8")
    return hand_over(path, job.title)["media"]


# Saving a file in the job's own folder has no failure written for the user: anything else is "something went wrong".
KIND = jobs.Kind(word=WORD, folder=FOLDER, write=write, make=make, ready_text=ready_text)
jobs.KINDS["research"] = KIND
