"""The video writer: one focused turn, handed only writer.md and one tool (submit_video, with the page inline), that
ends with an accepted narration and page, or a WriterFailed that says why.

Most tests use a stand-in for runner.focused_turn: a plain object that records what it was handed and calls the tool
by name, as a model would, following a script per test, then asks the follow-up once (the nudge), as focused_turn
does. page.check is a recorder where no browser is needed. Two tests run the real focused turn through ADK with a
stand-in model (an ADK BaseLlm), and one draws the worked example in a real browser."""
import json
import logging
from pathlib import Path
from typing import ClassVar

import pytest
from google.adk.events.event_actions import EventActions
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.adk.tools import FunctionTool
from google.genai import types

from odie.browser import RENDER_ARGS, find
from odie.browser.engine import Browser, BrowserError, BrowserTimeout
from odie.making import writer as harness
from odie.video import page, writer

SAMPLE = (Path(page.__file__).parent / "kit" / "sample.html").read_text()
WRITER_MD = Path(writer.__file__).with_name("writer.md")
NARRATION = ["Here is how attention works, one word at a time.", "Then one formula does the work for every word."]
ACCEPTED = {"result": "Accepted."}
NUDGE = ("You haven't called submit_video yet. Stop planning and don't count words: write the narration and the "
         "page now, as they are, and call submit_video with the title, the narration and the whole page.")
BIN = find.installed()
needs_browser = pytest.mark.skipif(BIN is None, reason="no Chrome, Edge, Chromium or Brave here")


class Context:
    """What ADK hands a tool as tool_context, as far as submit_video uses it: the actions of the tool's event."""

    def __init__(self):
        self.actions = EventActions()


class Turn:
    """Stands in for runner.focused_turn(prompt, instruction, tools, timeout, follow_up): records what it is handed,
    plays `script(turn)`, then asks follow_up once, as focused_turn does; when that gives a nudge, plays
    `after_nudge(turn)` (if any). Each submit records what the "model" saw and whether the tool ended the turn."""

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

    async def __call__(self, prompt, instruction, tools, timeout, follow_up=None, max_llm_calls=None):
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

    async def submit(self, page=SAMPLE, narration=NARRATION, title="How attention works"):
        """One submit_video call, as the writer.md flow says: the title, the narration and the whole page."""
        by_name = {tool.__name__: tool for tool in self.tools}
        context = Context()
        out = await by_name["submit_video"](title, narration, page, tool_context=context)
        self.said.append(out)
        self.ended.append(context.actions.skip_summarization is True)
        return out


async def nothing(turn):
    """A script for a model that only talks: no tool call at all."""


async def submits(turn):
    await turn.submit()


@pytest.fixture
def checks(monkeypatch):
    """page.check replaced by a recorder: it answers with the next problem from `checks["problems"]` (None, page fine,
    once they run out) and records every (body, narration, browser) it was asked about."""
    record = {"problems": [], "calls": []}

    async def recorded(body, narration, browser):
        record["calls"].append((body, list(narration), browser))
        if record["problems"]:
            return record["problems"].pop(0)
        return None

    monkeypatch.setattr(page, "check", recorded)
    return record


BROWSER = object()  # what write() was handed as the browser; page.check must get this same one


def saved_pages(folder: Path) -> list[str]:
    """The pages kept in the job's folder, in order: page-1.html, page-2.html, …"""
    pages = folder / "pages"
    texts = []
    n = 1
    while (pages / f"page-{n}.html").exists():
        texts.append((pages / f"page-{n}.html").read_text())
        n += 1
    return texts


async def test_accepted_first_time_gives_the_narration_and_the_page_and_ends_the_turn(tmp_path, checks):
    turn = Turn(submits)
    written = await writer.write("How attention works", 2, "For a curious beginner.", tmp_path / "job", turn,
                                 BROWSER)
    assert written == writer.Written(title="How attention works", narration=NARRATION, body=SAMPLE)
    assert turn.said == [ACCEPTED]
    assert turn.ended == [True]  # nothing more is asked of the model
    assert turn.nudge is None  # a finished desk needs no nudge
    assert saved_pages(tmp_path / "job") == [SAMPLE]
    assert checks["calls"] == [(SAMPLE, NARRATION, BROWSER)]


async def test_every_submitted_page_is_kept_and_the_fix_is_what_comes_back(tmp_path, checks):
    checks["problems"] = ["The page threw in scene 2 at t = 1.2 s: boom"]
    fixed = SAMPLE.replace("How attention works", "Attention, fixed")

    async def script(turn):
        await turn.submit()
        await turn.submit(page=fixed)

    turn = Turn(script)
    written = await writer.write("Attention", 2, "", tmp_path / "job", turn, BROWSER)
    assert turn.said == [{"error": "The page threw in scene 2 at t = 1.2 s: boom"}, ACCEPTED]
    assert turn.ended == [False, True]  # a rejection leaves the turn going, so the writer can fix it
    assert written.body == fixed
    assert saved_pages(tmp_path / "job") == [SAMPLE, fixed]  # the rejected page is kept too


async def test_three_rejections_end_the_turn_and_fail_with_the_last_problem(tmp_path, checks):
    checks["problems"] = ["first problem", "second problem", "third problem"]

    async def script(turn):
        for _ in range(3):
            await turn.submit()

    turn = Turn(script)
    with pytest.raises(harness.WriterFailed) as failed:
        await writer.write("Attention", 2, "", tmp_path / "job", turn, BROWSER)
    assert str(failed.value) == "I couldn't write a page that passed its check: third problem"
    assert turn.said[1] == {"error": "second problem"}
    assert turn.said[2]["error"].startswith("third problem")
    assert harness.STOP in turn.said[2]["error"]
    assert turn.ended == [False, False, True]
    assert turn.nudge is None  # stopped is finished: no nudge
    assert len(saved_pages(tmp_path / "job")) == 3


async def test_a_submit_after_the_stop_is_not_checked_and_ends_the_turn(tmp_path, checks):
    checks["problems"] = ["first problem", "second problem", "third problem"]

    async def script(turn):
        for _ in range(4):
            await turn.submit()

    turn = Turn(script)
    with pytest.raises(harness.WriterFailed):
        await writer.write("Attention", 2, "", tmp_path / "job", turn, BROWSER)
    assert turn.said[3] == {"error": harness.STOP}
    assert turn.ended[3] is True
    assert len(checks["calls"]) == 3


async def test_a_submit_after_acceptance_keeps_the_first_video(tmp_path, checks):
    other = SAMPLE.replace("How attention works", "Another")

    async def script(turn):
        await turn.submit()
        await turn.submit(page=other, title="Another")

    turn = Turn(script)
    written = await writer.write("Attention", 2, "", tmp_path / "job", turn, BROWSER)
    assert turn.said == [ACCEPTED, ACCEPTED]
    assert turn.ended == [True, True]
    assert written.body == SAMPLE and written.title == "How attention works"
    assert len(checks["calls"]) == 1


async def test_a_writer_that_only_talks_is_nudged_once_and_then_submits(tmp_path, checks):
    turn = Turn(nothing, after_nudge=submits)
    written = await writer.write("Attention", 2, "", tmp_path / "job", turn, BROWSER)
    assert turn.nudge == NUDGE
    assert turn.said == [ACCEPTED]
    assert written.body == SAMPLE


async def test_a_writer_that_never_submits_even_after_the_nudge_fails(tmp_path, checks):
    turn = Turn(nothing, after_nudge=nothing)
    with pytest.raises(harness.WriterFailed) as failed:
        await writer.write("Attention", 2, "", tmp_path / "job", turn, BROWSER)
    assert turn.nudge == NUDGE
    assert str(failed.value) == "I couldn't write the video's page (the writer stopped without one)."


async def test_a_writer_that_stops_after_a_rejection_is_nudged_with_the_problem(tmp_path, checks):
    checks["problems"] = ["The page threw in scene 2 at t = 1.2 s: boom"]

    async def once(turn):
        await turn.submit()

    turn = Turn(once, after_nudge=submits)
    written = await writer.write("Attention", 2, "", tmp_path / "job", turn, BROWSER)
    assert "The page threw in scene 2 at t = 1.2 s: boom" in turn.nudge
    assert "submit_video" in turn.nudge
    assert written.body == SAMPLE


async def test_a_writer_that_stops_after_a_rejection_fails_with_that_problem(tmp_path, checks):
    checks["problems"] = ["The page threw in scene 2 at t = 1.2 s: boom"]

    async def once(turn):
        await turn.submit()

    with pytest.raises(harness.WriterFailed) as failed:
        await writer.write("Attention", 2, "", tmp_path / "job", Turn(once, after_nudge=nothing), BROWSER)
    assert str(failed.value) == ("I couldn't write a page that passed its check: "
                                 "The page threw in scene 2 at t = 1.2 s: boom")


async def test_the_turn_gets_only_submit_video_writer_md_and_the_time_limit(tmp_path, checks):
    turn = Turn(submits)
    await writer.write("How tides work", 3, "For a ten-year-old. Mention the moon first.", tmp_path / "job", turn,
                       BROWSER)
    assert [tool.__name__ for tool in turn.tools] == ["submit_video"]
    assert turn.instruction == WRITER_MD.read_text()
    assert turn.timeout == 900  # 15 minutes: one refused page on a long video with sources still fits


async def test_the_prompt_gives_the_topic_the_minutes_the_words_and_the_brief(tmp_path, checks):
    turn = Turn(submits)
    await writer.write("How tides work", 3, "For a ten-year-old. Mention the moon first.", tmp_path / "job", turn,
                       BROWSER)
    assert "How tides work" in turn.prompt
    assert "3 minutes" in turn.prompt and "420 words" in turn.prompt  # 3 x 140
    assert "For a ten-year-old. Mention the moon first." in turn.prompt
    assert turn.prompt.rstrip().endswith(writer.PLAN_THEN_WRITE)
    assert "submit_video" in writer.PLAN_THEN_WRITE


async def test_the_prompt_carries_the_source_material_word_for_word(tmp_path, checks):
    from odie.making.sources import Source, brief_with_sources
    tides = "Asha's notes on tides.\n\n| place | high tide |\n|---|---|\n| Goa | 2.1 m |"
    brief = brief_with_sources("For a ten-year-old. Show the table.", [Source("The user's message", tides)])
    turn = Turn(submits)
    await writer.write("How tides work", 3, brief, tmp_path / "job", turn, BROWSER)
    assert "Brief:\nFor a ten-year-old. Show the table." in turn.prompt
    assert "## Source material" in turn.prompt and tides in turn.prompt


def test_writer_md_says_the_brief_may_end_with_the_users_own_material():
    text = WRITER_MD.read_text()
    assert "## Source material" in text and "the user's own text" in text


def test_one_minute_is_said_in_the_singular():
    assert "Length: 1 minute, roughly 140 words" in writer.prompt_for("Tides", 1, "")


async def test_a_narration_problem_is_a_rejection_and_comes_back_before_the_page_is_drawn(tmp_path, checks):
    async def script(turn):
        await turn.submit(narration=["Hi.", "  "])
        await turn.submit()

    turn = Turn(script)
    await writer.write("Attention", 2, "", tmp_path / "job", turn, BROWSER)
    assert turn.said[0] == {"error": "There's no narration for scene 2: every scene needs words to speak."}
    assert len(checks["calls"]) == 1  # only the good try was drawn
    assert saved_pages(tmp_path / "job") == [SAMPLE, SAMPLE]


async def test_a_page_too_big_is_a_rejection_with_the_limit(tmp_path, checks):
    big = "x" * 300_001

    async def script(turn):
        for _ in range(3):
            await turn.submit(page=big)

    turn = Turn(script)
    with pytest.raises(harness.WriterFailed) as failed:
        await writer.write("Attention", 2, "", tmp_path / "job", turn, BROWSER)
    assert "at most 300 KB" in turn.said[0]["error"]
    assert str(failed.value).startswith("I couldn't write a page that passed its check: The page is 300 KB")
    assert checks["calls"] == []  # never drawn
    assert saved_pages(tmp_path / "job") == [big, big, big]  # kept all the same


async def test_a_hang_is_a_rejection_told_in_words(tmp_path, monkeypatch):
    failures = [BrowserTimeout("frame 3 took too long.")]

    async def check(body, narration, browser):
        if failures:
            raise failures.pop(0)
        return None

    monkeypatch.setattr(page, "check", check)

    async def script(turn):
        await turn.submit()
        await turn.submit()

    turn = Turn(script)
    written = await writer.write("Attention", 2, "", tmp_path / "job", turn, BROWSER)
    assert turn.said[0] == {"error": "The page didn't finish drawing in time (a loop that never ends?): "
                                     "frame 3 took too long."}
    assert turn.ended == [False, True]
    assert written.body == SAMPLE


async def test_a_browser_that_fails_ends_the_job_with_its_own_words_and_is_no_rejection(tmp_path, monkeypatch):
    async def check(body, narration, browser):
        raise BrowserError("The browser didn't start.")

    monkeypatch.setattr(page, "check", check)
    turn = Turn(submits, after_nudge=submits)
    with pytest.raises(harness.WriterFailed) as failed:
        await writer.write("Attention", 2, "", tmp_path / "job", turn, BROWSER)
    assert str(failed.value) == "The browser didn't start."
    assert turn.said == [{"error": "The browser didn't start."}]
    assert turn.ended == [True]  # the writer can't fix a browser: the turn ends
    assert turn.nudge is None


async def test_a_null_title_falls_back_to_the_topic(tmp_path, checks):
    async def script(turn):
        await turn.submit(title=None)

    written = await writer.write("Attention", 2, "", tmp_path / "job", Turn(script), BROWSER)
    assert written.title == "Attention"


async def test_narration_sent_as_a_json_string_is_read_as_the_list(tmp_path, checks):
    async def script(turn):
        await turn.submit(narration=json.dumps(NARRATION))

    turn = Turn(script)
    written = await writer.write("Attention", 2, "", tmp_path / "job", turn, BROWSER)
    assert turn.said == [ACCEPTED]
    assert written.narration == NARRATION
    assert checks["calls"][0][1] == NARRATION


async def test_narration_as_text_that_isnt_a_list_is_a_narration_problem(tmp_path, checks):
    async def script(turn):
        await turn.submit(narration="Here is how attention works.")
        await turn.submit(narration=json.dumps({"scene": "one"}))
        await turn.submit()

    turn = Turn(script)
    await writer.write("Attention", 2, "", tmp_path / "job", turn, BROWSER)
    assert turn.said[0] == {"error": writer.NOT_A_LIST}
    assert turn.said[1] == {"error": writer.NOT_A_LIST}
    assert turn.said[2] == ACCEPTED


async def test_an_accepted_page_survives_the_turn_failing_afterwards_and_the_failure_is_logged(tmp_path, checks,
                                                                                                  caplog):
    async def script(turn):
        await turn.submit()
        raise RuntimeError("the model broke after accepting")

    with caplog.at_level(logging.WARNING, logger="odie.video"):
        written = await writer.write("Attention", 2, "", tmp_path / "job", Turn(script), BROWSER)
    assert written.body == SAMPLE
    logged = [record for record in caplog.records if record.exc_info]
    assert logged and "the model broke after accepting" in str(logged[0].exc_info[1])


async def test_a_model_failure_before_any_outcome_goes_up_as_it_is(tmp_path, checks):
    async def script(turn):
        raise RuntimeError("the model is down")

    with pytest.raises(RuntimeError):
        await writer.write("Attention", 2, "", tmp_path / "job", Turn(script), BROWSER)


async def test_a_writer_that_runs_out_of_time_fails_with_the_time_limit(tmp_path, checks):
    async def script(turn):
        raise TimeoutError

    with pytest.raises(harness.WriterFailed) as failed:
        await writer.write("Attention", 2, "", tmp_path / "job", Turn(script), BROWSER)
    assert str(failed.value) == "The writer took more than 15 minutes and stopped."


def test_adk_reads_submit_video_with_its_three_arguments_and_no_context():
    tools = writer.tools_for(writer.Desk(topic="T", pages=Path("unused")), BROWSER)
    declared = {}
    for tool in tools:
        declaration = FunctionTool(tool)._get_declaration()
        declared[declaration.name] = declaration.parameters_json_schema["required"]
        assert "tool_context" not in declaration.parameters_json_schema["properties"]
    assert declared == {"submit_video": ["title", "narration", "page"]}


def function_answers(llm_request) -> list:
    """The tool results the model has seen so far in this request."""
    pieces = [piece for content in llm_request.contents or [] for piece in content.parts or []]
    return [piece.function_response for piece in pieces if piece.function_response]


def submit_call() -> types.Part:
    args = {"title": "How attention works", "narration": NARRATION, "page": SAMPLE}
    return types.Part(function_call=types.FunctionCall(id="c1", name="submit_video", args=args))


class Writes(BaseLlm):
    """A stand-in model for the real focused turn: submits the worked example straight away, and would reply "done"
    if it were asked again. Records every request it receives."""
    seen: ClassVar[list] = []

    async def generate_content_async(self, llm_request, stream: bool = False):
        Writes.seen.append(llm_request)
        part = submit_call()
        if function_answers(llm_request):
            part = types.Part(text="done")
        yield LlmResponse(content=types.Content(role="model", parts=[part]))


class TalksFirst(BaseLlm):
    """A stand-in model that first replies with words only (the slip seen live), and submits once it is nudged."""
    seen: ClassVar[list] = []

    async def generate_content_async(self, llm_request, stream: bool = False):
        TalksFirst.seen.append(llm_request)
        last = llm_request.contents[-1].parts[-1].text or ""
        part = types.Part(text="I have planned the scenes.")
        if last == NUDGE:
            part = submit_call()
        yield LlmResponse(content=types.Content(role="model", parts=[part]))


async def write_through_the_runner(tmp_path, monkeypatch, model):
    from odie.app import runner as runner_mod
    from odie.store.db import Store
    monkeypatch.setattr(runner_mod, "model_for", lambda selection, thinking, room=None: model)
    store = Store(tmp_path / "assistant.db")
    store.init_schema()
    odie = runner_mod.OdieRunner(store)
    await odie.load_plugins()
    try:
        return await writer.write("How attention works", 2, "", tmp_path / "job", odie.focused_turn, BROWSER)
    finally:
        await odie.close()


async def test_through_the_real_focused_turn_an_accepted_submit_ends_the_turn(isolated_settings, tmp_path,
                                                                               monkeypatch, checks):
    Writes.seen = []
    written = await write_through_the_runner(tmp_path, monkeypatch, Writes(model="writes"))
    assert written == writer.Written(title="How attention works", narration=NARRATION, body=SAMPLE)
    assert len(Writes.seen) == 1  # no model call after "Accepted."
    request = Writes.seen[0]
    assert sorted(request.tools_dict) == ["submit_video"]
    assert WRITER_MD.read_text().strip() in str(request.config.system_instruction)


async def test_through_the_real_focused_turn_a_writer_that_talks_is_nudged_and_submits(isolated_settings, tmp_path,
                                                                                        monkeypatch, checks):
    TalksFirst.seen = []
    written = await write_through_the_runner(tmp_path, monkeypatch, TalksFirst(model="talks-first"))
    assert written.body == SAMPLE
    assert len(TalksFirst.seen) == 2  # the slip, then the submit after the nudge; nothing after acceptance
    texts = [p.text for c in TalksFirst.seen[1].contents for p in c.parts or [] if p.text]
    assert "Topic: How attention works" in texts[0]  # the same session: the first prompt is still there
    assert texts[-1] == NUDGE


def test_writer_md_carries_the_sample_page_verbatim():
    assert SAMPLE.strip() in WRITER_MD.read_text()


def test_writer_md_names_only_submit_video_with_the_page_inline():
    text = WRITER_MD.read_text()
    assert "submit_video(" in text and 'page="""' in text
    assert "save_video_page" not in text and "page_file" not in text
    assert "never draft the page in your thinking" in text


@needs_browser
async def test_the_worked_example_is_accepted_in_a_real_browser(tmp_path):
    real = Browser(tmp_path / "render", BIN, extra_args=RENDER_ARGS)

    async def script(turn):
        await turn.submit(narration=["word " * 20, "word " * 20])

    turn = Turn(script)
    try:
        written = await writer.write("Attention", 1, "", tmp_path / "job", turn, real)
    finally:
        await real.close()
    assert turn.said == [ACCEPTED], turn.said
    assert written.narration == ["word " * 20, "word " * 20]


# A rich 4-minute brief made DeepSeek count each scene's words by hand until all 32,000 tokens of its reply were
# thinking, twice, so no page was ever submitted (16 Oct 2026). The length is a guide the writer must not count to.

def test_the_length_is_a_guide_the_writer_is_told_not_to_count():
    from odie.video import writer
    assert "a guide, not a count" in writer.prompt_for("Quantization", 4, "")
    assert "Never count words" in writer.INSTRUCTION and "within about a tenth" not in writer.INSTRUCTION
    assert "don't count words" in writer.LINES.nudge
