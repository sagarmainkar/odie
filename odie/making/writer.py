"""The writer harness: one focused model turn, in the background, that writes one thing Odie makes (a video's
narration and page, a podcast's script, a deck's slides) and hands it in through one submit tool.

The turn sees only the kind's instruction and that one tool (no Odie prompt, no memory, no chat). The tool takes the
whole result at once and runs the kind's check: a problem goes back to the writer to fix. An accepted result, a third
refusal, or a check that can't run at all (the browser failed) ends the turn there and then, with no more model calls.
A writer that stops without any of those is nudged once, in the same session. The turn ends with the accepted result
(whatever the kind's accept made) or WriterFailed, whose words the chat is told."""
import inspect
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from google.adk.tools import ToolContext

from odie.making.chat import text_or_empty

log = logging.getLogger("odie.making.writer")

TIME_LIMIT = 900  # seconds the whole writing turn may take, the nudge included (a long video with sources took
                  # 331 s live on its first try, so one refused page still fits)
MAX_REJECTIONS = 3  # submits that may be refused before the writing stops

ACCEPTED = "Accepted."
STOP = "That's three tries, so the writing stops here."
TIMED_OUT = f"The writer took more than {TIME_LIMIT // 60} minutes and stopped."


class WriterFailed(Exception):
    """The writer ended without an accepted result. The message is the line the user is told."""


class CantCheck(Exception):
    """The kind's check couldn't run at all (the browser didn't start): not the writer's fault, so it is no refusal.
    The turn ends and the job fails with these words."""


@dataclass
class Lines:
    """One kind's words for a writer that hasn't finished.
    nudge: what the writer is told, once, when it stopped without submitting.
    nudge_after_problem: what it is told when its last submit was refused; {problem} is that refusal.
    never_submitted: the failure the user hears when nothing was ever submitted.
    not_passed: the failure the user hears when nothing passed the check; {problem} is the last refusal."""
    nudge: str
    nudge_after_problem: str
    never_submitted: str
    not_passed: str


@dataclass
class Desk:
    """What the submit tool keeps during one turn: the topic (the title when the writer gives none), how many submits
    were refused (and the last problem), the accepted result once there is one, and the words of a check that
    couldn't run."""
    topic: str = ""
    rejected: int = 0
    last_problem: str = ""
    accepted: object | None = None
    failure: str = ""

    def finished(self) -> bool:
        """Decides whether the turn already has its outcome, so nothing more is asked of the model and a failure
        afterwards doesn't change it: a submit was accepted -> True; three submits refused -> True (the writing
        stops); the check couldn't run (the browser failed) -> True (the writer can't fix that); one refusal, or
        nothing submitted yet -> False."""
        if self.accepted is not None:
            return True
        if self.failure:
            return True
        return self.rejected >= MAX_REJECTIONS


def title_given(title, topic: str) -> str:
    """The title the writer gave, trimmed; with none, the topic: "  Tides " -> "Tides"; None or "  " and topic "tides"
    -> "tides"."""
    name = text_or_empty(title).strip()
    if name:
        return name
    return topic


def settled_answer(desk: Desk) -> dict:
    """What a submit after the outcome is settled answers (the turn ends again): accepted -> {"result": "Accepted."};
    the check couldn't run -> its words as the error; three refusals -> {"error": STOP}."""
    if desk.accepted is not None:
        return {"result": ACCEPTED}
    if desk.failure:
        return {"error": desk.failure}
    return {"error": STOP}


async def answer(desk: Desk, fields: dict, tool_context: ToolContext,
                 check: Callable[[dict], Awaitable[str | None]], accept: Callable[[dict], object]) -> dict:
    """One submit, start to end: after the outcome is settled -> the settled answer, unchecked; the check couldn't run
    -> its words, and the turn ends; a problem -> {"error": problem} (the third time with STOP added, and the turn
    ends); no problem -> accept(fields) goes on the desk, {"result": "Accepted."}, and the turn ends. Ending the turn is
    skip_summarization: ADK makes no model call after this tool's answer."""
    if desk.finished():
        tool_context.actions.skip_summarization = True
        return settled_answer(desk)

    try:
        problem = await check(fields)
    except CantCheck as e:
        desk.failure = str(e)
        tool_context.actions.skip_summarization = True
        return {"error": desk.failure}

    if problem:
        desk.rejected += 1
        desk.last_problem = problem
        if desk.rejected < MAX_REJECTIONS:
            return {"error": problem}
        tool_context.actions.skip_summarization = True
        return {"error": f"{problem} {STOP}"}

    desk.accepted = accept(fields)
    tool_context.actions.skip_summarization = True
    return {"result": ACCEPTED}


def submit_tool(desk: Desk, name: str, doc: str, fields: dict[str, object],
                check: Callable[[dict], Awaitable[str | None]], accept: Callable[[dict], object]) -> Callable:
    """Build a kind's one submit tool. name: what the writer calls ("submit_video"); doc: what the writer reads about
    it; fields: its arguments, in order, with their types ({"title": str, "narration": list[str], "page": str}).
    check(fields) is async and returns the problem to fix, or None to accept; it raises CantCheck when it can't run.
    accept(fields) makes the accepted result, which the turn ends with.

    ADK reads the tool's name, doc and arguments from the function it is handed, so the function carries them as its
    own: submit_video(title: str, narration: list[str], page: str, tool_context: ToolContext). ADK hands it
    tool_context itself (the model never sees that argument); the fields reach check and accept as a dict by name."""
    parameters = []
    for field_name, annotation in fields.items():
        parameters.append(inspect.Parameter(field_name, inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=annotation))
    parameters.append(inspect.Parameter("tool_context", inspect.Parameter.POSITIONAL_OR_KEYWORD,
                                        annotation=ToolContext))
    signature = inspect.Signature(parameters, return_annotation=dict)

    async def submit(*args, **kwargs) -> dict:
        given = dict(signature.bind(*args, **kwargs).arguments)
        tool_context = given.pop("tool_context")
        return await answer(desk, given, tool_context, check, accept)

    submit.__name__ = name
    submit.__qualname__ = name
    submit.__doc__ = doc
    submit.__signature__ = signature
    submit.__annotations__ = {**fields, "tool_context": ToolContext, "return": dict}
    return submit


def nudge_for(desk: Desk, lines: Lines) -> str | None:
    """Decides what the writer is told, once, when its turn ends: a finished desk (accepted, stopped, the check
    couldn't run) -> None, nothing is sent; nothing submitted -> lines.nudge ("You haven't called submit_video yet.
    …"); one refused submit and nothing since -> lines.nudge_after_problem with the last problem."""
    if desk.finished():
        return None
    if desk.rejected == 0:
        return lines.nudge
    return lines.nudge_after_problem.format(problem=desk.last_problem)


def outcome(desk: Desk, lines: Lines) -> object:
    """The turn's result, from what is on the desk: accepted -> the result; the check couldn't run -> WriterFailed
    with its words; refused (once, twice or three times) and nothing accepted -> WriterFailed(lines.not_passed) with
    the last problem; nothing submitted -> WriterFailed(lines.never_submitted)."""
    if desk.accepted is not None:
        return desk.accepted
    if desk.failure:
        raise WriterFailed(desk.failure)
    if desk.rejected > 0:
        raise WriterFailed(lines.not_passed.format(problem=desk.last_problem))
    raise WriterFailed(lines.never_submitted)


async def write(desk: Desk, prompt: str, instruction: str, tool: Callable, lines: Lines, turn) -> object:
    """Write in one focused turn: `turn(prompt, instruction, tools, timeout, follow_up=…)` is runner.focused_turn in
    Odie, handed only `instruction` and the one `tool` (made by submit_tool on this `desk`). When the turn ends
    unfinished, follow_up gives the one nudge (nudge_for). Returns the accepted result; raises WriterFailed when there's
    none (see outcome), or TIMED_OUT when the time ran out first. A model failure before any outcome goes up as it is,
    for the job to tell (as "something went wrong"); one after the outcome is settled is only logged."""

    def follow_up() -> str | None:
        return nudge_for(desk, lines)

    try:
        await turn(prompt, instruction, [tool], TIME_LIMIT, follow_up=follow_up)
    except TimeoutError:
        if not desk.finished():
            raise WriterFailed(TIMED_OUT) from None
        log.warning("the writer's turn (%s) timed out after its outcome was settled", tool.__name__, exc_info=True)
    except Exception:
        if not desk.finished():
            raise
        log.warning("the writer's turn (%s) failed after its outcome was settled", tool.__name__, exc_info=True)
    return outcome(desk, lines)
