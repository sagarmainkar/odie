"""The research writer: one focused turn, handed research_writer.md, the web (web_search, web_fetch, built without
the private chat's approval card), three of the user's vault tools and one submit tool (submit_research, with the
title and the whole report in Markdown). The report is checked for its length (at least 150 words) and its sources (a
"## Sources" heading with a link or a note under it); a problem goes back to the writer in words it can act on.

Most tests use a stand-in for runner.focused_turn that calls submit_research by name, as a model would, then asks
the follow-up once (the nudge), as focused_turn does. One test runs the real focused turn through ADK with a stand-in
model (an ADK BaseLlm)."""
from pathlib import Path
from typing import ClassVar

import pytest
from google.adk.events.event_actions import EventActions
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.adk.tools import FunctionTool
from google.genai import types

from odie.making import research_writer as writer
from odie.making import writer as harness
from odie.store.db import Store

WRITER_MD = Path(writer.__file__).with_name("research_writer.md")
ACCEPTED = {"result": "Accepted."}
FINDINGS = " ".join(["Kettles with a 1.7 litre jug boil a full load in about four minutes."] * 14)  # 196 words
REPORT = ("## The short answer\n\nA 1.7 litre steel kettle suits a family of four best.\n\n"
          f"## Findings\n\n{FINDINGS}\n\n"
          "## Sources\n\n- https://example.com/kettle-review\n- [[Kitchen wishlist]]\n")


class Context:
    """What ADK hands a tool as tool_context, as far as submit_research uses it: the actions of the tool's event."""

    def __init__(self):
        self.actions = EventActions()


class Turn:
    """Stands in for runner.focused_turn(prompt, instruction, tools, timeout, follow_up): records what it is handed,
    plays `script(turn)`, then asks follow_up once; when that gives a nudge, plays `after_nudge(turn)` (if any)."""

    def __init__(self, script, after_nudge=None):
        self.script = script
        self.after_nudge = after_nudge
        self.prompt = ""
        self.instruction = ""
        self.tools = []
        self.timeout = None
        self.nudge = None
        self.said = []
        self.ended = []

    async def __call__(self, prompt, instruction, tools, timeout, follow_up=None):
        self.prompt = prompt
        self.instruction = instruction
        self.tools = tools
        self.timeout = timeout
        await self.script(self)
        if follow_up is not None:
            self.nudge = follow_up()
        if self.nudge is not None and self.after_nudge is not None:
            await self.after_nudge(self)
        return ""

    def names(self) -> list[str]:
        """The names the model sees: a FunctionTool's name, or a plain function's (the submit tool)."""
        named = []
        for tool in self.tools:
            if isinstance(tool, FunctionTool):
                named.append(tool.name)
            else:
                named.append(tool.__name__)
        return named

    async def submit(self, markdown=REPORT, title="Which kettle to buy"):
        """One submit_research call, as research_writer.md says: the title and the whole report."""
        [submit] = [tool for tool in self.tools if getattr(tool, "__name__", "") == "submit_research"]
        context = Context()
        out = await submit(title, markdown, tool_context=context)
        self.said.append(out)
        self.ended.append(context.actions.skip_summarization is True)
        return out


async def nothing(turn):
    """A script for a model that only talks: no tool call at all."""


async def submits(turn):
    await turn.submit()


@pytest.fixture
def store(isolated_settings, tmp_path):
    """A store for the web and vault tools; everything on disk under tmp_path."""
    assert str(isolated_settings.data_dir).startswith(str(tmp_path))
    store = Store(tmp_path / "assistant.db")
    store.init_schema()
    return store


async def write(turn, store, brief="For Asha: a kettle for a family of four, under ₹3,000."):
    return await writer.write("Which kettle to buy", brief, turn, store)


# Accepted, refused, stopped.

async def test_a_good_report_is_accepted_first_time_and_ends_the_turn(store):
    turn = Turn(submits)
    written = await write(turn, store)
    assert written == writer.Written(title="Which kettle to buy", markdown=REPORT)
    assert turn.said == [ACCEPTED] and turn.ended == [True] and turn.nudge is None


async def test_a_report_with_no_sources_heading_is_refused_in_words_to_act_on(store):
    no_sources = REPORT.split("## Sources")[0]

    async def script(turn):
        await turn.submit(markdown=no_sources)
        await turn.submit()

    turn = Turn(script)
    written = await write(turn, store)
    assert turn.said == [{"error": writer.NO_SOURCES_HEADING}, ACCEPTED]
    assert '"## Sources"' in writer.NO_SOURCES_HEADING and "submit_research again" in writer.NO_SOURCES_HEADING
    assert turn.ended == [False, True] and written.markdown == REPORT


async def test_a_sources_heading_with_nothing_under_it_is_refused(store):
    empty = REPORT.split("## Sources")[0] + "## Sources\n\n"
    turn = Turn(lambda turn: turn.submit(markdown=empty))
    with pytest.raises(harness.WriterFailed):
        await write(turn, store)
    assert turn.said[0] == {"error": writer.NO_SOURCES_LISTED}


async def test_a_report_too_short_is_told_its_length_in_words(store):
    short = "## The short answer\n\nBuy the steel one.\n\n## Sources\n\n- https://example.com/kettle-review\n"

    async def script(turn):
        await turn.submit(markdown=short)
        await turn.submit()

    turn = Turn(script)
    await write(turn, store)
    assert turn.said[0] == {"error": (
        "The report is 9 words; it needs at least 150. Give the findings with their details (what each source "
        "says, the numbers, how they compare), then call submit_research again with the whole report.")}
    assert turn.said[1] == ACCEPTED


@pytest.mark.parametrize("sources", [
    "- https://example.com/a", "- [[Kitchen wishlist]]", "- Kitchen wishlist (a note)",
    "1. [Review](https://example.com/a)",
])
def test_a_link_a_note_or_a_line_under_the_heading_counts_as_a_source(sources):
    assert writer.submission_problem(f"{FINDINGS}\n\n## Sources\n\n{sources}\n") is None


def test_the_sources_heading_is_found_in_any_case_and_a_later_heading_ends_it():
    assert writer.submission_problem(f"{FINDINGS}\n\n## sources\n- https://example.com/a\n") is None
    after = f"{FINDINGS}\n\n## Sources\n\n## Notes\n\n- https://example.com/a\n"
    assert writer.submission_problem(after) == writer.NO_SOURCES_LISTED  # the link is under another heading
    assert writer.submission_problem(f"{FINDINGS}\n\nSources: https://example.com/a") == writer.NO_SOURCES_HEADING


async def test_three_refusals_end_the_turn_and_fail_with_the_last_problem(store):
    async def script(turn):
        for _ in range(3):
            await turn.submit(markdown=FINDINGS)

    turn = Turn(script)
    with pytest.raises(harness.WriterFailed) as failed:
        await write(turn, store)
    assert str(failed.value) == f"I couldn't write a report that passed its check: {writer.NO_SOURCES_HEADING}"
    assert turn.ended == [False, False, True]


async def test_a_writer_that_only_talks_is_nudged_once_and_then_submits(store):
    turn = Turn(nothing, after_nudge=submits)
    written = await write(turn, store)
    assert turn.nudge == writer.LINES.nudge and "submit_research" in turn.nudge
    assert written.markdown == REPORT


async def test_a_writer_that_never_submits_fails_in_words(store):
    with pytest.raises(harness.WriterFailed) as failed:
        await write(Turn(nothing), store)
    assert str(failed.value) == "I couldn't write the report (the writer stopped without one)."


async def test_running_out_of_time_says_thirty_minutes(store):
    async def script(turn):
        raise TimeoutError

    with pytest.raises(harness.WriterFailed) as failed:
        await write(Turn(script), store)
    assert str(failed.value) == "The writer took more than 30 minutes and stopped."


async def test_a_null_title_falls_back_to_the_topic_and_a_null_report_is_refused(store):
    async def script(turn):
        await turn.submit(markdown=None)
        await turn.submit(title=None)

    turn = Turn(script)
    written = await write(turn, store)
    assert "error" in turn.said[0] and turn.said[1] == ACCEPTED
    assert written.title == "Which kettle to buy"


# What the writer is handed.

async def test_the_turn_gets_the_web_three_vault_tools_and_submit_research_for_thirty_minutes(store):
    turn = Turn(submits)
    await write(turn, store)
    assert turn.names() == ["web_search", "web_fetch", "search_everything", "read_note", "related_notes",
                            "submit_research"]
    assert turn.timeout == writer.RESEARCH_TIME_LIMIT == 1800
    web = [tool for tool in turn.tools if isinstance(tool, FunctionTool)]
    assert not any(tool._require_confirmation for tool in web)  # no chat here to show an approval card
    assert turn.instruction == WRITER_MD.read_text() == writer.INSTRUCTION


async def test_the_prompt_gives_the_topic_and_the_brief(store):
    turn = Turn(submits)
    await write(turn, store, brief="For Asha. Compare steel and glass.")
    assert turn.prompt == (
        "Topic: Which kettle to buy\n\n"
        "Brief:\nFor Asha. Compare steel and glass.\n\n"
        "Search and read first, then call submit_research with the title and the whole report.")


def test_an_empty_brief_is_said_plainly():
    assert "Brief:\n(none: find out what matters most about the topic)" in writer.prompt_for("Kettles", "  ")


def test_adk_reads_submit_research_with_its_two_arguments_and_no_context():
    tool = writer.submit_tool_for(harness.Desk(topic="T"))
    declaration = FunctionTool(tool)._get_declaration()
    assert declaration.name == "submit_research"
    assert declaration.parameters_json_schema["required"] == ["title", "markdown"]
    assert "tool_context" not in declaration.parameters_json_schema["properties"]


def test_the_instruction_carries_the_research_rules():
    text = WRITER_MD.read_text()
    assert "submit_research(" in text and "web_search" in text and "read_note" in text
    assert "## Sources" in text and "short answer" in text and "traceable" in text
    assert "no emojis" in text and "never draft the report in your thinking" in text
    assert "## Source material" in text and "UNTRUSTED WEB" in text
    assert "Asha" not in text


# Through the real focused turn: the accepted submit is the last model call.

def submit_call() -> types.Part:
    args = {"title": "Which kettle to buy", "markdown": REPORT}
    return types.Part(function_call=types.FunctionCall(id="c1", name="submit_research", args=args))


class Writes(BaseLlm):
    """A stand-in model for the real focused turn: submits the report straight away, and would reply "done" if it
    were asked again. Records every request it receives."""
    seen: ClassVar[list] = []

    async def generate_content_async(self, llm_request, stream: bool = False):
        Writes.seen.append(llm_request)
        pieces = [piece for content in llm_request.contents or [] for piece in content.parts or []]
        part = submit_call()
        if any(piece.function_response for piece in pieces):
            part = types.Part(text="done")
        yield LlmResponse(content=types.Content(role="model", parts=[part]))


async def test_through_the_real_focused_turn_an_accepted_submit_ends_the_turn(store, monkeypatch):
    from odie.app import runner as runner_mod
    Writes.seen = []
    model = Writes(model="writes")
    monkeypatch.setattr(runner_mod, "model_for", lambda selection, thinking, room=None: model)
    odie = runner_mod.OdieRunner(store)
    await odie.load_plugins()
    try:
        written = await writer.write("Which kettle to buy", "", odie.focused_turn, store)
    finally:
        await odie.close()
    assert written == writer.Written(title="Which kettle to buy", markdown=REPORT)
    assert len(Writes.seen) == 1  # no model call after "Accepted."
    request = Writes.seen[0]
    assert sorted(request.tools_dict) == ["read_note", "related_notes", "search_everything", "submit_research",
                                          "web_fetch", "web_search"]
    assert WRITER_MD.read_text().strip() in str(request.config.system_instruction)
