"""The podcast writer: one focused turn, handed only podcast_writer.md and one tool (submit_podcast, with the whole
script inline), that ends with an accepted title and script, or a WriterFailed that says why. The script is checked
by parse_script (two hosts, one turn per line, at most 60 turns) and for its length (140 words a minute, give or take
40%); a problem goes back to the writer in words it can act on.

Most tests use a stand-in for runner.focused_turn that calls the tool by name, as a model would, then asks the
follow-up once (the nudge), as focused_turn does. One test runs the real focused turn through ADK with a stand-in model
(an ADK BaseLlm)."""
from pathlib import Path
from typing import ClassVar

import pytest
from google.adk.events.event_actions import EventActions
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.adk.tools import FunctionTool
from google.genai import types

from odie.making import podcast_writer as writer
from odie.making import writer as harness

WRITER_MD = Path(writer.__file__).with_name("podcast_writer.md")
ACCEPTED = {"result": "Accepted."}
NUDGE = ("You haven't called submit_podcast yet. Stop planning and don't count words: write the script now, as it "
         "is, and call submit_podcast with the title and the whole script.")


def turn_words(count: int) -> str:
    """One turn's speech of exactly `count` words: "tides tides … tides."."""
    return " ".join(["tides"] * count) + "."


def script_of(turns: int, words_each: int) -> str:
    """A script of `turns` turns, Host A first, each of `words_each` words."""
    lines = []
    for number in range(turns):
        host = "Host A"
        if number % 2:
            host = "Host B"
        lines.append(f"{host}: {turn_words(words_each)}")
    return "\n".join(lines)


SCRIPT = script_of(10, 28)  # 280 words: a 2-minute podcast
TURNS = writer.parse_script(SCRIPT)


class Context:
    """What ADK hands a tool as tool_context, as far as submit_podcast uses it: the actions of the tool's event."""

    def __init__(self):
        self.actions = EventActions()


class Turn:
    """Stands in for runner.focused_turn(prompt, instruction, tools, timeout, follow_up): records what it is handed,
    plays `script(turn)`, then asks follow_up once; when that gives a nudge, plays `after_nudge(turn)` (if any). Each
    submit records what the "model" saw and whether the tool ended the turn."""

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

    async def submit(self, script=SCRIPT, title="How tides work"):
        """One submit_podcast call, as podcast_writer.md says: the title and the whole script."""
        by_name = {tool.__name__: tool for tool in self.tools}
        context = Context()
        out = await by_name["submit_podcast"](title, script, tool_context=context)
        self.said.append(out)
        self.ended.append(context.actions.skip_summarization is True)
        return out


async def nothing(turn):
    """A script for a model that only talks: no tool call at all."""


async def submits(turn):
    await turn.submit()


async def write(turn, minutes=2, brief="For Asha, who sails."):
    return await writer.write("How tides work", minutes, brief, turn)


# Accepted, refused, stopped.

async def test_accepted_first_time_gives_the_title_and_the_turns_and_ends_the_turn():
    turn = Turn(submits)
    written = await write(turn)
    assert written == writer.Written(title="How tides work", turns=TURNS)
    assert written.turns[0] == ("Host A", turn_words(28)) and len(written.turns) == 10
    assert turn.said == [ACCEPTED]
    assert turn.ended == [True]  # nothing more is asked of the model
    assert turn.nudge is None


async def test_both_hosts_on_one_line_is_parse_scripts_problem_sent_back_to_the_writer():
    one_line = f"Host A: {turn_words(140)} Host B: {turn_words(140)}"

    async def script(turn):
        await turn.submit(script=one_line)
        await turn.submit()

    turn = Turn(script)
    written = await write(turn)
    assert turn.said == [{"error": "A podcast has two hosts, a woman and then a man; this script has 1."}, ACCEPTED]
    assert turn.ended == [False, True]  # a refusal leaves the turn going, so the writer can fix it
    assert written.turns == TURNS


async def test_lines_without_host_labels_get_parse_scripts_words():
    turn = Turn(lambda turn: turn.submit(script="Today we look at tides.\nAnd why they matter."))
    with pytest.raises(harness.WriterFailed):
        await write(turn)
    assert "Write each line as Host A: or Host B:" in turn.said[0]["error"]


async def test_a_script_too_short_is_told_its_length_in_words():
    short = script_of(4, 10)  # 40 words for 2 minutes

    async def script(turn):
        await turn.submit(script=short)
        await turn.submit()

    turn = Turn(script)
    await write(turn)
    assert turn.said[0] == {"error": (
        "The script is too short: about 280 words for 2 minutes; this is 40. Anything from 168 to 392 words is "
        "fine: add a point, an example or a question, then call submit_podcast again with the whole script.")}
    assert turn.said[1] == ACCEPTED


async def test_a_script_too_long_is_told_its_length_in_words():
    long = script_of(20, 30)  # 600 words for 2 minutes

    async def script(turn):
        await turn.submit(script=long)
        await turn.submit()

    turn = Turn(script)
    await write(turn)
    assert turn.said[0] == {"error": (
        "The script is too long: about 280 words for 2 minutes; this is 600. Anything from 168 to 392 words is "
        "fine: cut a point or shorten the turns, then call submit_podcast again with the whole script.")}


def test_the_length_allows_forty_percent_either_way():
    two_minutes = [writer.length_problem(writer.parse_script(script_of(4, words)), 2) for words in (42, 98)]
    assert two_minutes == [None, None]  # 168 and 392 words: the edges are fine
    assert "this is 164" in writer.length_problem(writer.parse_script(script_of(4, 41)), 2)
    assert "this is 396" in writer.length_problem(writer.parse_script(script_of(4, 99)), 2)
    one = writer.length_problem(writer.parse_script(script_of(2, 10)), 1)
    assert "about 140 words for 1 minute;" in one  # one minute in the singular


def test_the_words_counted_are_the_spoken_ones_not_the_labels():
    assert writer.spoken_words([("Host A", "Hello there."), ("Host B", "Hi.")]) == 3


async def test_three_refusals_end_the_turn_and_fail_with_the_last_problem():
    async def script(turn):
        for _ in range(3):
            await turn.submit(script="Host A: only me.")

    turn = Turn(script)
    with pytest.raises(harness.WriterFailed) as failed:
        await write(turn)
    problem = "A podcast has two hosts, a woman and then a man; this script has 1."
    assert str(failed.value) == f"I couldn't write a script that passed its check: {problem}"
    assert turn.said[2]["error"] == f"{problem} {harness.STOP}"
    assert turn.ended == [False, False, True]
    assert turn.nudge is None


async def test_a_writer_that_only_talks_is_nudged_once_and_then_submits():
    turn = Turn(nothing, after_nudge=submits)
    written = await write(turn)
    assert turn.nudge == NUDGE
    assert turn.said == [ACCEPTED] and written.turns == TURNS


async def test_a_writer_that_never_submits_fails_in_words():
    turn = Turn(nothing)
    with pytest.raises(harness.WriterFailed) as failed:
        await write(turn)
    assert str(failed.value) == "I couldn't write the podcast's script (the writer stopped without one)."


async def test_a_writer_that_stops_after_a_refusal_is_nudged_with_the_problem():
    turn = Turn(lambda turn: turn.submit(script="Host A: only me."))
    with pytest.raises(harness.WriterFailed):
        await write(turn)
    assert turn.nudge == (
        "submit_podcast hasn't accepted the script yet. Its last answer was: A podcast has two hosts, a woman and then "
        "a man; this script has 1. Fix exactly that and call submit_podcast again with the title and the whole fixed "
        "script.")


async def test_a_null_title_falls_back_to_the_topic_and_a_null_script_is_refused():
    async def script(turn):
        await turn.submit(script=None)
        await turn.submit(title=None)

    turn = Turn(script)
    written = await write(turn)
    assert "error" in turn.said[0] and turn.said[1] == ACCEPTED
    assert written.title == "How tides work"


# What the writer is handed.

async def test_the_turn_gets_only_submit_podcast_the_instruction_and_the_time_limit():
    turn = Turn(submits)
    await write(turn)
    assert [tool.__name__ for tool in turn.tools] == ["submit_podcast"]
    assert turn.instruction == WRITER_MD.read_text() == writer.INSTRUCTION
    assert turn.timeout == harness.TIME_LIMIT


async def test_the_prompt_gives_the_topic_the_length_as_a_guide_and_the_brief():
    turn = Turn(lambda turn: turn.submit(script=script_of(20, 28)))  # 560 words: 4 minutes
    await write(turn, minutes=4, brief="For Asha, who sails. 1. The moon pulls. 2. Two bulges.")
    assert turn.prompt == (
        "Topic: How tides work\n"
        "Length: 4 minutes, roughly 560 words of script (a guide, not a count).\n\n"
        "Brief:\nFor Asha, who sails. 1. The moon pulls. 2. Two bulges.\n\n"
        "Plan in a few lines, then call submit_podcast with the title and the whole script.")


def test_an_empty_brief_and_one_minute_are_said_plainly():
    prompt = writer.prompt_for("Tides", 1, "  ")
    assert "Length: 1 minute, roughly 140 words" in prompt
    assert "Brief:\n(none: use what you know about the topic)" in prompt


def test_adk_reads_submit_podcast_with_its_two_arguments_and_no_context():
    [tool] = writer.tools_for(harness.Desk(topic="T"), 2)
    declaration = FunctionTool(tool)._get_declaration()
    assert declaration.name == "submit_podcast"
    assert declaration.parameters_json_schema["required"] == ["title", "script"]
    assert "tool_context" not in declaration.parameters_json_schema["properties"]


def test_the_instruction_carries_the_podcast_rules():
    text = WRITER_MD.read_text()
    assert "submit_podcast(" in text and "speak(" not in text and 'style="podcast"' not in text
    assert "Host A (a woman) and Host B (a man)" in text
    assert "never say their own names or each other's" in text
    assert "Asha" not in text and "Rohan" not in text
    assert "no emojis" in text and "140 words" in text and "Never count words" in text
    assert "never draft the script in your thinking" in text
    assert "Never put both hosts on one line" in text
    assert "can't see" in text  # the writer knows it sees only the brief


# Through the real focused turn: the accepted submit is the last model call.

def submit_call() -> types.Part:
    args = {"title": "How tides work", "script": SCRIPT}
    return types.Part(function_call=types.FunctionCall(id="c1", name="submit_podcast", args=args))


class Writes(BaseLlm):
    """A stand-in model for the real focused turn: submits the script straight away, and would reply "done" if it were
    asked again. Records every request it receives."""
    seen: ClassVar[list] = []

    async def generate_content_async(self, llm_request, stream: bool = False):
        Writes.seen.append(llm_request)
        pieces = [piece for content in llm_request.contents or [] for piece in content.parts or []]
        part = submit_call()
        if any(piece.function_response for piece in pieces):
            part = types.Part(text="done")
        yield LlmResponse(content=types.Content(role="model", parts=[part]))


async def test_through_the_real_focused_turn_an_accepted_submit_ends_the_turn(isolated_settings, tmp_path,
                                                                               monkeypatch):
    from odie.app import runner as runner_mod
    from odie.store.db import Store
    Writes.seen = []
    model = Writes(model="writes")
    monkeypatch.setattr(runner_mod, "model_for", lambda selection, thinking, room=None: model)
    store = Store(tmp_path / "assistant.db")
    store.init_schema()
    odie = runner_mod.OdieRunner(store)
    await odie.load_plugins()
    try:
        written = await writer.write("How tides work", 2, "", odie.focused_turn)
    finally:
        await odie.close()
    assert written == writer.Written(title="How tides work", turns=TURNS)
    assert len(Writes.seen) == 1  # no model call after "Accepted."
    request = Writes.seen[0]
    assert sorted(request.tools_dict) == ["submit_podcast"]
    assert WRITER_MD.read_text().strip() in str(request.config.system_instruction)


# The script's shape (parse_script, moved here from speak with the podcast).

@pytest.mark.parametrize("script, why", [
    ("Ana: hi\nBen: hello\nCal: hey\nCal: again", "two hosts"), ("Ana: just me talking.", "two hosts"),
    ("no names at all here", "Host A:"),
    ("\n".join(f"{'Ana' if i % 2 else 'Ben'}: line {i}" for i in range(61)), "60"),
])
def test_scripts_are_checked(script, why):
    with pytest.raises(ValueError) as e:
        writer.parse_script(script)
    assert why in str(e.value)


def test_lines_with_colons_continue_the_turn():
    turns = writer.parse_script("Asha: Hi there.\nRohan: Let's start.\nAt 10:30 we met the team.\nNote: this matters.\n"
                                "https://example.com/page was the link.\nAsha: Right.")
    assert [n for n, _ in turns] == ["Asha", "Rohan", "Asha"]
    assert turns[1][1] == "Let's start. At 10:30 we met the team. Note: this matters. was the link."


def test_a_recurring_third_speaker_is_refused():
    with pytest.raises(ValueError) as e:
        writer.parse_script("Asha: Hi.\nRohan: Hello.\nMeera: Hey.\nAsha: So.\nMeera: Me again.")
    assert "two hosts" in str(e.value)


def test_names_in_any_script():
    turns = writer.parse_script("Élodie: Bonjour à tous.\nआशा: नमस्ते।\nÉlodie: On commence.")
    assert [n for n, _ in turns] == ["Élodie", "आशा", "Élodie"]


def test_bold_labels_and_continued_lines_are_read():
    turns = writer.parse_script("Asha: Welcome back!\n**Rohan:** Today, our session.\nAsha: So where do we start?\n"
                                "it continues here.\n\nRohan: With the basics.")
    assert turns == [("Asha", "Welcome back!"), ("Rohan", "Today, our session."),
                     ("Asha", "So where do we start? it continues here."), ("Rohan", "With the basics.")]


def test_a_host_with_only_links_is_a_plain_error():
    with pytest.raises(ValueError) as e:
        writer.parse_script("Asha: Hi there.\nRohan: https://example.com")
    assert "two hosts" in str(e.value) and "something to say" in str(e.value)


def test_podcast_writer_md_says_the_brief_may_end_with_the_users_own_material():
    text = WRITER_MD.read_text()
    assert "## Source material" in text and "the user's own text" in text
