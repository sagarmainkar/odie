"""The video writer: one focused model turn, in the background, that writes an explainer video's narration and page.

It sees only writer.md (the page contract, the kit, the worked example, the style) and one tool, submit_video, which
takes the title, the narration and the whole page at once. Every page sent is kept in the job's folder
(pages/page-1.html, page-2.html, …), then checked: its size, the narration, and the page drawn in a browser. A problem
goes back to the writer to fix. An accepted video, a third refusal or a browser that fails ends the turn there and
then, with no more model calls. A writer that stops without any of those is nudged once, in the same session. The
turn ends with the accepted video (Written) or WriterFailed."""
import json
import logging
from dataclasses import dataclass
from pathlib import Path

from google.adk.tools import ToolContext

from odie.browser.engine import BrowserError, BrowserTimeout
from odie.video import page as video_page
from odie.video import timeline
from odie.video.limits import narration_problem, page_problem

log = logging.getLogger("odie.video.writer")

INSTRUCTION = Path(__file__).with_name("writer.md").read_text(encoding="utf-8")
TIME_LIMIT = 600  # seconds the whole writing turn may take, the nudge included
MAX_REJECTIONS = 3  # submits that may be refused before the writing stops

HANG = "The page didn't finish drawing in time (a loop that never ends?): "
NOT_A_LIST = ('narration is a list of strings, one string of plain speech per scene, in order: ["The first scene\'s '
              'words.", "The second scene\'s words."]')
ACCEPTED = "Accepted."
STOP = "That's three tries, so the writing stops here."
BROWSER_FAILED = "The browser failed while checking the page."  # a BrowserError with no words of its own
NUDGE = "You haven't called submit_video yet. Call it now with the title, the narration and the whole page."
NUDGE_AFTER_PROBLEM = ("submit_video hasn't accepted the video yet. Its last answer was: {problem} Fix exactly that "
                       "and call submit_video again with the title, the whole narration and the whole fixed page.")
PLAN_THEN_WRITE = "Plan in a few lines, then call submit_video with the title, the narration and the whole page."
NEVER_SUBMITTED = "I couldn't write the video's page (the writer stopped without one)."
NOT_PASSED = "I couldn't write a page that passed its check: {problem}"
TIMED_OUT = f"The writer took more than {TIME_LIMIT // 60} minutes and stopped."


class WriterFailed(Exception):
    """The writer ended without an accepted video. The message is the line the user is told."""


@dataclass
class Written:
    """The accepted video: its title, one string of narration per scene, and the page body that draws them."""
    title: str
    narration: list[str]
    body: str


@dataclass
class Desk:
    """What submit_video keeps during one turn: where the pages go, how many submits were refused (and the last
    problem), the accepted video once there is one, and the browser's own words if it failed."""
    topic: str
    pages: Path
    rejected: int = 0
    last_problem: str = ""
    accepted: Written | None = None
    browser_failure: str = ""

    def finished(self) -> bool:
        """Decides whether the turn already has its outcome, so nothing more is asked of the model and a failure
        afterwards doesn't change it: a submit was accepted -> True; three submits refused -> True (the writing
        stops); the browser failed -> True (the writer can't fix that); one refusal, or nothing submitted yet ->
        False."""
        if self.accepted is not None:
            return True
        if self.browser_failure:
            return True
        return self.rejected >= MAX_REJECTIONS


def next_page_name(folder: Path) -> str:
    """The first free page name in the folder: nothing kept yet -> "page-1"; page-1 and page-2 there -> "page-3"."""
    n = 1
    while (folder / f"page-{n}.html").exists():
        n += 1
    return f"page-{n}"


def keep_page(folder: Path, body: str) -> None:
    """Keep a submitted page in the job's pages folder under the next free name, before it is checked, so every try
    (refused ones too) can be looked at afterwards: the first submit -> pages/page-1.html."""
    folder.mkdir(parents=True, exist_ok=True)
    name = next_page_name(folder)
    (folder / f"{name}.html").write_text(body, encoding="utf-8")


def prompt_for(topic: str, minutes: int, brief: str) -> str:
    """The writer's whole message: the topic, the length in minutes and in words (140 a minute: 2 minutes -> about
    280 words), the brief, and what to do."""
    words = minutes * timeline.WORDS_PER_MINUTE
    unit = "minutes"
    if minutes == 1:
        unit = "minute"
    brief_text = brief.strip()
    if not brief_text:
        brief_text = "(none: use what you know about the topic)"
    return (f"Topic: {topic}\n"
            f"Length: {minutes} {unit}, about {words} words of narration.\n\n"
            f"Brief:\n{brief_text}\n\n"
            f"{PLAN_THEN_WRITE}")


def text_or_empty(value) -> str:
    """A text argument the model may have sent as null: None -> ""; "How attention works" -> the same."""
    if value is None:
        return ""
    return value


def narration_as_given(narration):
    """The narration the model meant. Some models send the list as JSON text: '["One.", "Two."]' -> ["One.", "Two."].
    Anything else is passed on unchanged for the check to judge: ["One."] -> ["One."]; "One." or '{"a": "b"}' -> the
    same text, refused there as not a list."""
    if not isinstance(narration, str):
        return narration
    try:
        parsed = json.loads(narration)
    except ValueError:
        return narration
    if is_list_of_strings(parsed):
        return parsed
    return narration


def is_list_of_strings(value) -> bool:
    """Decides whether the narration has the shape of one: ["One.", "Two."] -> True; [] -> True (refused later as no
    narration); "One." -> False; ["One.", 2] -> False."""
    if not isinstance(value, list):
        return False
    return all(isinstance(item, str) for item in value)


async def submission_problem(narration, body: str, browser) -> str | None:
    """Decides whether a video can be accepted: the first problem as words to fix, or None. In this order: a page over
    300 KB -> the limit; narration that isn't a list of strings -> NOT_A_LIST; a narration problem (["Hi.", "  "] ->
    scene 2 has no words), and then nothing is drawn; the page drawn in the browser (a draw that throws -> "The page
    threw in scene 2 at t = 1.2 s: …"; a frame that never finishes -> the HANG wording). The worked example with two
    narration strings -> None. A browser that fails in another way (it won't start) is not the page's problem: its
    BrowserError goes up to submit_video."""
    problem = page_problem(body)
    if problem:
        return problem
    if not is_list_of_strings(narration):
        return NOT_A_LIST
    problem = narration_problem(narration)
    if problem:
        return problem
    try:
        return await video_page.check(body, narration, browser)
    except BrowserTimeout as e:
        return HANG + str(e)


def settled_answer(desk: Desk) -> dict:
    """What a submit after the outcome is settled answers (the turn ends again): accepted -> {"result": "Accepted."};
    the browser failed -> its words as the error; three refusals -> {"error": STOP}."""
    if desk.accepted is not None:
        return {"result": ACCEPTED}
    if desk.browser_failure:
        return {"error": desk.browser_failure}
    return {"error": STOP}


def tools_for(desk: Desk, browser) -> list:
    """The writer's one tool, submit_video, keeping what it learns on `desk`. Its docstring is what the writer model
    reads; ADK hands it tool_context itself (the model never sees that argument)."""

    async def submit_video(title: str, narration: list[str], page: str, tool_context: ToolContext) -> dict:
        """Submit the whole video at once: title (the topic, short), narration (one string of plain speech per scene,
        in order) and page (the whole page: the HTML body, one <script> that calls Video.scenes([...]) once, with one
        scene per narration string). It checks the narration and draws the page.
        {"error": …}: fix exactly that and call submit_video again with the whole narration and the whole fixed page.
        {"result": "Accepted."}: the video is done."""
        if desk.finished():
            tool_context.actions.skip_summarization = True  # the outcome stands: end the turn again
            return settled_answer(desk)

        body = text_or_empty(page)
        keep_page(desk.pages, body)
        narration = narration_as_given(narration)
        try:
            problem = await submission_problem(narration, body, browser)
        except BrowserError as e:
            # Not the page's fault, so no rejection: the job ends with the browser's own words.
            words = str(e).strip()
            if not words:
                words = BROWSER_FAILED
            desk.browser_failure = words
            tool_context.actions.skip_summarization = True
            return {"error": words}

        if problem:
            desk.rejected += 1
            desk.last_problem = problem
            if desk.rejected < MAX_REJECTIONS:
                return {"error": problem}
            tool_context.actions.skip_summarization = True
            return {"error": f"{problem} {STOP}"}

        name = text_or_empty(title).strip()
        if not name:
            name = desk.topic
        desk.accepted = Written(title=name, narration=list(narration), body=body)
        tool_context.actions.skip_summarization = True  # ADK ends the turn here: no model call after acceptance
        return {"result": ACCEPTED}

    return [submit_video]


def nudge_for(desk: Desk) -> str | None:
    """Decides what the writer is told, once, when its turn ends: a finished desk (accepted, stopped, the browser
    failed) -> None, nothing is sent; nothing submitted -> NUDGE ("You haven't called submit_video yet. …"); one
    refused submit and nothing since -> the last problem and a call to submit the fixed page."""
    if desk.finished():
        return None
    if desk.rejected == 0:
        return NUDGE
    return NUDGE_AFTER_PROBLEM.format(problem=desk.last_problem)


def outcome(desk: Desk) -> Written:
    """The turn's result, from what is on the desk: accepted -> the video; the browser failed -> WriterFailed with its
    words; refused (once, twice or three times) and nothing accepted -> WriterFailed with the last problem; nothing
    submitted -> WriterFailed(NEVER_SUBMITTED)."""
    if desk.accepted is not None:
        return desk.accepted
    if desk.browser_failure:
        raise WriterFailed(desk.browser_failure)
    if desk.rejected > 0:
        raise WriterFailed(NOT_PASSED.format(problem=desk.last_problem))
    raise WriterFailed(NEVER_SUBMITTED)


async def write(topic: str, minutes: int, brief: str, folder: Path, turn, browser) -> Written:
    """Writes the video in one focused turn: `turn(prompt, instruction, tools, timeout, follow_up=…)` is
    runner.focused_turn in Odie, `browser` the one page.check draws in (render_browser()). Every submitted page is kept
    under folder/pages. When the turn ends unfinished, follow_up gives the one nudge (nudge_for). Returns the accepted
    video; raises WriterFailed when there's none (see outcome), or TIMED_OUT when the time ran out first. A model
    failure before any outcome goes up as it is, for the job to tell (as "something went wrong"); one after the
    outcome is settled is only logged."""
    desk = Desk(topic=topic, pages=folder / "pages")
    tools = tools_for(desk, browser)

    def follow_up() -> str | None:
        return nudge_for(desk)

    try:
        await turn(prompt_for(topic, minutes, brief), INSTRUCTION, tools, TIME_LIMIT, follow_up=follow_up)
    except TimeoutError:
        if not desk.finished():
            raise WriterFailed(TIMED_OUT) from None
        log.warning("the video writer's turn timed out after its outcome was settled", exc_info=True)
    except Exception:
        if not desk.finished():
            raise
        log.warning("the video writer's turn failed after its outcome was settled", exc_info=True)
    return outcome(desk)
