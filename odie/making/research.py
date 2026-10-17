"""Research as one kind of thing Odie makes in the background (odie.making.jobs): its writing step is the research
writer (odie.making.research_writer), which searches the web and the user's notes and writes a report with its
sources; its making step (no AI) saves the report as <job folder>/<slug>.md and posts it as a file card. Importing this
module registers the kind as "research", with its jobs under <workspace>/research/<slug>/ (job.json, brief.md and
the report). The report stays in the workspace, not the vault.

job.data carries "markdown" (the accepted report) from the writing step to the making step."""
from odie.agent.tools.files import hand_over
from odie.making import jobs, research_writer

FOLDER = "research"


def with_title(markdown: str, title: str) -> str:
    """The report as it is saved: with the title as its top heading, unless it starts with one of its own, and one
    closing newline. "## The short answer\\n\\nYes." and "Kettles" -> "# Kettles\\n\\n## The short answer\\n\\nYes.\\n";
    "# Kettles, compared\\n\\nYes." -> kept as it is (with its newline)."""
    report = markdown.strip()
    if report.startswith("# "):
        return report + "\n"
    return f"# {title}\n\n{report}\n"


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
KIND = jobs.Kind(word="research", folder=FOLDER, write=write, make=make)
jobs.KINDS["research"] = KIND
