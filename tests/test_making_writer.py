"""The shared writer harness (odie.making.writer), driven by a stand-in kind: a note whose one tool is
submit_note(title, text), checked by a small check that refuses an empty text. The video writer's own tests
(test_video_writer.py) cover the same harness through submit_video; these show it works for any kind's tool."""
import pytest
from google.adk.events.event_actions import EventActions
from google.adk.tools import FunctionTool

from odie.making import jobs
from odie.making import writer as harness

DOC = """Submit the whole note: title (short) and text (the note itself).
{"error": …}: fix exactly that and call submit_note again. {"result": "Accepted."}: the note is done."""
LINES = harness.Lines(
    nudge="You haven't called submit_note yet. Call it now with the title and the text.",
    nudge_after_problem="submit_note hasn't accepted the note yet. Its last answer was: {problem} Fix that.",
    never_submitted="I couldn't write the note (the writer stopped without one).",
    not_passed="I couldn't write a note that passed its check: {problem}",
)
ACCEPTED = {"result": "Accepted."}


class Context:
    """What ADK hands a tool as tool_context, as far as a submit tool uses it: the actions of the tool's event."""

    def __init__(self):
        self.actions = EventActions()


class Checks:
    """The note's check: refuses an empty text, or raises `cant` (the check itself can't run). Records each call."""

    def __init__(self):
        self.calls = []
        self.cant = None

    async def __call__(self, fields):
        self.calls.append(dict(fields))
        if self.cant is not None:
            raise self.cant
        if not fields["text"].strip():
            return "The text is empty: write the note."
        return None


def accept(fields):
    return (fields["title"], fields["text"])


def note_tool(desk, checks):
    return harness.submit_tool(desk, "submit_note", DOC, {"title": str, "text": str}, checks, accept)


class Turn:
    """Stands in for runner.focused_turn: plays `script(turn)`, then asks follow_up once and, given a nudge, plays
    `after_nudge(turn)`."""

    def __init__(self, script, after_nudge=None):
        self.script = script
        self.after_nudge = after_nudge
        self.nudge = None
        self.said = []
        self.ended = []
        self.handed = None

    async def __call__(self, prompt, instruction, tools, timeout, follow_up=None):
        self.handed = (prompt, instruction, [tool.__name__ for tool in tools], timeout)
        self.tools = tools
        await self.script(self)
        if follow_up is not None:
            self.nudge = follow_up()
        if self.nudge is not None and self.after_nudge is not None:
            await self.after_nudge(self)
        return ""

    async def submit(self, title="Tides", text="The moon pulls the sea."):
        context = Context()
        by_name = {tool.__name__: tool for tool in self.tools}
        out = await by_name["submit_note"](title=title, text=text, tool_context=context)
        self.said.append(out)
        self.ended.append(context.actions.skip_summarization is True)
        return out


async def submits(turn):
    await turn.submit()


async def nothing(turn):
    pass


async def write(turn, checks=None, topic="tides"):
    desk = harness.Desk(topic=topic)
    tool = note_tool(desk, checks or Checks())
    return await harness.write(desk, "Topic: tides", "the note rules", tool, LINES, turn)


def test_the_factory_builds_one_tool_adk_reads_with_its_name_doc_and_fields():
    tool = note_tool(harness.Desk(), Checks())
    declaration = FunctionTool(tool)._get_declaration()
    assert declaration.name == "submit_note"
    assert declaration.description.startswith("Submit the whole note")
    assert declaration.parameters_json_schema["required"] == ["title", "text"]
    assert "tool_context" not in declaration.parameters_json_schema["properties"]


async def test_adk_calls_it_with_the_models_arguments_and_its_context(tmp_path):
    desk = harness.Desk(topic="tides")
    checks = Checks()
    context = Context()
    out = await FunctionTool(note_tool(desk, checks)).run_async(args={"title": "Tides", "text": "The moon."},
                                                               tool_context=context)
    assert out == ACCEPTED and desk.accepted == ("Tides", "The moon.")
    assert checks.calls == [{"title": "Tides", "text": "The moon."}]
    assert context.actions.skip_summarization is True


async def test_accepted_first_time_ends_the_turn_with_what_accept_made():
    turn = Turn(submits)
    assert await write(turn) == ("Tides", "The moon pulls the sea.")
    assert turn.handed == ("Topic: tides", "the note rules", ["submit_note"], 900)
    assert turn.said == [ACCEPTED] and turn.ended == [True] and turn.nudge is None


async def test_three_refusals_stop_the_writing_with_the_kinds_words():
    async def script(turn):
        for _ in range(4):
            await turn.submit(text="  ")

    turn = Turn(script)
    with pytest.raises(harness.WriterFailed) as failed:
        await write(turn)
    assert str(failed.value) == "I couldn't write a note that passed its check: The text is empty: write the note."
    assert turn.said[2] == {"error": f"The text is empty: write the note. {harness.STOP}"}
    assert turn.said[3] == {"error": harness.STOP}  # after the stop: not checked, the turn ends again
    assert turn.ended == [False, False, True, True]


async def test_a_check_that_cant_run_ends_the_turn_with_its_words_and_is_no_refusal():
    checks = Checks()
    checks.cant = harness.CantCheck("The browser didn't start.")
    turn = Turn(submits, after_nudge=submits)
    with pytest.raises(harness.WriterFailed) as failed:
        await write(turn, checks)
    assert str(failed.value) == "The browser didn't start."
    assert turn.said == [{"error": "The browser didn't start."}] and turn.ended == [True] and turn.nudge is None


async def test_a_writer_that_only_talks_gets_the_kinds_nudge_once():
    turn = Turn(nothing, after_nudge=nothing)
    with pytest.raises(harness.WriterFailed) as failed:
        await write(turn)
    assert turn.nudge == LINES.nudge
    assert str(failed.value) == LINES.never_submitted


async def test_a_writer_that_stops_after_a_refusal_is_nudged_with_the_problem():
    async def once(turn):
        await turn.submit(text="")

    turn = Turn(once, after_nudge=submits)
    assert await write(turn) == ("Tides", "The moon pulls the sea.")
    assert turn.nudge == ("submit_note hasn't accepted the note yet. Its last answer was: "
                          "The text is empty: write the note. Fix that.")


async def test_running_out_of_time_is_the_time_limit_line():
    async def script(turn):
        raise TimeoutError

    with pytest.raises(harness.WriterFailed) as failed:
        await write(Turn(script))
    assert str(failed.value) == "The writer took more than 15 minutes and stopped."


async def test_a_time_limit_given_reaches_the_turn_and_its_line():
    desk = harness.Desk(topic="tides")
    turn = Turn(submits)
    await harness.write(desk, "Topic: tides", "the note rules", note_tool(desk, Checks()), LINES, turn,
                        time_limit=1800)
    assert turn.handed[3] == 1800

    async def script(turn):
        raise TimeoutError

    desk = harness.Desk(topic="tides")
    with pytest.raises(harness.WriterFailed) as failed:
        await harness.write(desk, "Topic: tides", "the note rules", note_tool(desk, Checks()), LINES, Turn(script),
                            time_limit=1800)
    assert str(failed.value) == "The writer took more than 30 minutes and stopped."


async def test_other_tools_are_handed_to_the_turn_before_the_submit_tool():
    async def look_up(query: str) -> str:
        """Look something up."""
        return "found"

    desk = harness.Desk(topic="tides")
    turn = Turn(submits)
    await harness.write(desk, "Topic: tides", "the note rules", note_tool(desk, Checks()), LINES, turn,
                        other_tools=[look_up])
    assert turn.handed[2] == ["look_up", "submit_note"]
    assert turn.said == [ACCEPTED]


async def test_a_model_failure_after_acceptance_keeps_the_result():
    async def script(turn):
        await turn.submit()
        raise RuntimeError("broke after accepting")

    assert await write(Turn(script)) == ("Tides", "The moon pulls the sea.")


def test_a_title_falls_back_to_the_topic():
    assert harness.title_given("  Tides  ", "tides") == "Tides"
    assert harness.title_given(None, "tides") == "tides"
    assert harness.title_given("  ", "tides") == "tides"


def test_the_writers_own_failure_words_are_always_shown_in_the_chat():
    assert jobs.one_line(harness.WriterFailed("I couldn't write the note."), ()) == "I couldn't write the note"

