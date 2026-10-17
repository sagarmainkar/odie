"""The deck writer: one focused turn, handed only deck_writer.md and one tool (submit_deck, with the whole deck
inline), that ends with an accepted title, deck Markdown and theme, or a WriterFailed that says why. The deck is
checked by the deck parser (odie.decks.model.parse: its DeckError words go back to the writer), its theme by name, and
every photo address against the brief (and, for a revision, the earlier deck): the writer can't search, so an address
it made up is refused with the ones it may use.

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

from odie.decks.model import parse
from odie.making import deck_writer as writer
from odie.making import writer as harness

WRITER_MD = Path(writer.__file__).with_name("deck_writer.md")
ACCEPTED = {"result": "Accepted."}
DECK = ("# Tides\nkicker: For Asha, who sails\nWhy the sea comes in twice a day\n\n"
        "# Two bulges\n- **The moon** — pulls\n")
PHOTO = "https://images.unsplash.com/photo-tides.jpg"
BRIEF = f"For Asha, who sails. 1. The moon pulls. 2. Two bulges.\nPhotos: {PHOTO} (credit: Photo by Ana on Unsplash)."
BRIDGE = "https://upload.wikimedia.org/wikipedia/commons/a/ab/Living_root_bridge_(Meghalaya).jpg"
PHOTO_DECK = f"# Tides\nimage: {PHOTO} (credit: Photo by Ana on Unsplash)\nWhy the sea comes in twice a day\n"


class Context:
    """What ADK hands a tool as tool_context, as far as submit_deck uses it: the actions of the tool's event."""

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

    async def submit(self, markdown=DECK, title="Why tides come twice", theme="minimal"):
        """One submit_deck call, as deck_writer.md says: the title, the whole deck and the theme."""
        by_name = {tool.__name__: tool for tool in self.tools}
        context = Context()
        out = await by_name["submit_deck"](title, markdown, theme, tool_context=context)
        self.said.append(out)
        self.ended.append(context.actions.skip_summarization is True)
        return out


async def nothing(turn):
    """A script for a model that only talks: no tool call at all."""


async def submits(turn):
    await turn.submit()


async def write(turn, brief=BRIEF, theme="minimal", earlier=""):
    return await writer.write("How tides work", brief, theme, turn, earlier=earlier)


# Accepted, refused, stopped.

async def test_a_valid_deck_is_accepted_with_its_title_markdown_and_theme_and_ends_the_turn():
    turn = Turn(submits)
    written = await write(turn)
    assert written == writer.Written(title="Why tides come twice", markdown=DECK, theme="minimal")
    assert turn.said == [ACCEPTED]
    assert turn.ended == [True]  # nothing more is asked of the model
    assert turn.nudge is None


async def test_the_deck_parsers_words_go_back_to_the_writer():
    too_many = "# A\n\n# B\n" + "".join(f"- point {n}\n" for n in range(9))

    async def script(turn):
        await turn.submit(markdown=too_many)
        await turn.submit()

    turn = Turn(script)
    written = await write(turn)
    assert turn.said == [{"error": "Slide 2 has 9 bullets; keep 6 or split it."}, ACCEPTED]
    assert turn.ended == [False, True]  # a refusal leaves the turn going, so the writer can fix it
    assert written.markdown == DECK


async def test_text_before_the_first_slide_gets_the_parsers_words():
    turn = Turn(lambda turn: turn.submit(markdown="just some text, no slides"))
    with pytest.raises(harness.WriterFailed):
        await write(turn)
    assert turn.said[0] == {"error": 'Start each slide with "# " and its title.'}


async def test_a_theme_that_doesnt_exist_is_refused_naming_the_four():
    async def script(turn):
        await turn.submit(theme="neon")
        await turn.submit(theme="Bold")

    turn = Turn(script)
    written = await write(turn)
    assert turn.said[0] == {"error": "There's no theme called neon: use one of editorial, minimal, warm, bold."}
    assert written.theme == "bold"  # any case, kept as the theme's own name


async def test_no_theme_from_the_writer_keeps_the_one_it_was_given():
    turn = Turn(lambda turn: turn.submit(theme=None))
    written = await write(turn, theme="warm")
    assert written.theme == "warm"


async def test_a_photo_address_from_the_brief_is_accepted():
    turn = Turn(lambda turn: turn.submit(markdown=PHOTO_DECK))
    written = await write(turn)
    assert turn.said == [ACCEPTED] and written.markdown == PHOTO_DECK


async def test_an_invented_photo_address_is_refused_with_the_ones_it_may_use():
    invented = PHOTO_DECK.replace(PHOTO, "https://example.com/made-up.jpg")

    async def script(turn):
        await turn.submit(markdown=invented)
        await turn.submit(markdown=PHOTO_DECK)

    turn = Turn(script)
    await write(turn)
    assert turn.said[0] == {"error": (
        "https://example.com/made-up.jpg isn't a photo address the brief gave, and you can't search or make one up. "
        f"Use only these, with their credits: {PHOTO}. Or leave the photo out. Then call submit_deck again with the "
        "whole deck.")}
    assert turn.said[1] == ACCEPTED


async def test_with_no_addresses_in_the_brief_no_image_lines_at_all():
    turn = Turn(lambda turn: turn.submit(markdown=PHOTO_DECK))
    with pytest.raises(harness.WriterFailed):
        await write(turn, brief="For Asha, who sails.")
    assert turn.said[0] == {"error": (
        f"{PHOTO} isn't a photo address the brief gave, and you can't search or make one up. The brief gave no photo "
        "addresses, so no image: lines: take them out, then call submit_deck again with the whole deck.")}


async def test_a_revision_may_keep_the_earlier_decks_photos():
    turn = Turn(lambda turn: turn.submit(markdown=PHOTO_DECK))
    written = await write(turn, brief="Make slide 2 shorter.", earlier=PHOTO_DECK)
    assert turn.said == [ACCEPTED] and written.markdown == PHOTO_DECK


def test_photo_addresses_are_read_without_their_brackets_and_closing_punctuation():
    text = ("Cover: <https://a.com/1.jpg>, credit Pexels. Also (https://b.com/2.jpg). Map: screenshot:ab12; "
            "theirs: upload:cd34. Again https://a.com/1.jpg")
    assert writer.addresses_in(text) == ["https://a.com/1.jpg", "https://b.com/2.jpg", "screenshot:ab12",
                                         "upload:cd34"]


def test_an_address_with_parentheses_in_it_is_read_whole():
    text = f"Bridge: {BRIDGE} (credit: Wikimedia Commons). Also ({BRIDGE})."
    assert writer.addresses_in(text) == [BRIDGE]


async def test_a_wikimedia_address_with_parentheses_from_the_brief_is_accepted_and_an_invented_one_refused():
    brief = f"Living root bridges. Photo: {BRIDGE} (credit: Wikimedia Commons)."
    deck = f"# Root bridges\nimage: {BRIDGE} (credit: Wikimedia Commons)\nGrown, not built\n"
    other = BRIDGE.replace("Living_root_bridge_(Meghalaya)", "Root_bridge_(Cherrapunji)")
    invented = deck.replace(BRIDGE, other)

    async def script(turn):
        await turn.submit(markdown=invented)
        await turn.submit(markdown=deck)

    turn = Turn(script)
    written = await write(turn, brief=brief)
    assert turn.said[0]["error"].startswith(f"{other} isn't a photo address the brief gave")
    assert f"Use only these, with their credits: {BRIDGE}." in turn.said[0]["error"]  # the whole address
    assert turn.said[1] == ACCEPTED and written.markdown == deck


def test_the_photo_check_reads_every_photo_the_deck_shows_and_its_credit_is_not_part_of_the_address():
    deck = parse(f"# A\nimage: {PHOTO} (credit: Ana)\n\n# B\n## One\nIMAGE: screenshot:ab12\n## Two\nx\n\n"
                 f"# C\nimage: upload:zz\n")
    given = f"{PHOTO} (credit: Ana), screenshot:ab12"
    assert writer.photo_problem(deck, given).startswith("upload:zz isn't a photo address the brief gave")
    assert writer.photo_problem(deck, f"{given}, upload:zz") is None


async def test_three_refusals_end_the_turn_and_fail_with_the_last_problem():
    async def script(turn):
        for _ in range(3):
            await turn.submit(theme="neon")

    turn = Turn(script)
    with pytest.raises(harness.WriterFailed) as failed:
        await write(turn)
    problem = "There's no theme called neon: use one of editorial, minimal, warm, bold."
    assert str(failed.value) == f"I couldn't write a deck that passed its check: {problem}"
    assert turn.said[2]["error"] == f"{problem} {harness.STOP}"
    assert turn.ended == [False, False, True]
    assert turn.nudge is None


async def test_a_writer_that_only_talks_is_nudged_once_and_then_submits():
    turn = Turn(nothing, after_nudge=submits)
    written = await write(turn)
    assert turn.nudge == ("You haven't called submit_deck yet. Stop planning: write the deck now, as it is, and call "
                          "submit_deck with the title, the whole deck and the theme.")
    assert turn.said == [ACCEPTED] and written.markdown == DECK


async def test_a_writer_that_never_submits_fails_in_words():
    turn = Turn(nothing)
    with pytest.raises(harness.WriterFailed) as failed:
        await write(turn)
    assert str(failed.value) == "I couldn't write the deck (the writer stopped without one)."


async def test_a_writer_that_stops_after_a_refusal_is_nudged_with_the_problem():
    turn = Turn(lambda turn: turn.submit(theme="neon"))
    with pytest.raises(harness.WriterFailed):
        await write(turn)
    assert turn.nudge == (
        "submit_deck hasn't accepted the deck yet. Its last answer was: There's no theme called neon: use one of "
        "editorial, minimal, warm, bold. Fix exactly that and call submit_deck again with the title, the whole fixed "
        "deck and the theme.")


async def test_a_null_title_falls_back_to_the_given_title_and_a_null_deck_is_refused():
    async def script(turn):
        await turn.submit(markdown=None)
        await turn.submit(title=None)

    turn = Turn(script)
    written = await write(turn)
    assert turn.said[0] == {"error": 'Start each slide with "# " and its title.'} and turn.said[1] == ACCEPTED
    assert written.title == "How tides work"


async def test_a_revision_without_a_title_keeps_the_earlier_decks_title():
    turn = Turn(lambda turn: turn.submit(title=" "))
    written = await writer.write("Tides, shorter", "Make slide 2 shorter.", "minimal", turn, earlier=DECK,
                                 title="Tides")
    assert written.title == "Tides"


# What the writer is handed.

async def test_the_turn_gets_only_submit_deck_the_instruction_and_the_time_limit():
    turn = Turn(submits)
    await write(turn)
    assert [tool.__name__ for tool in turn.tools] == ["submit_deck"]
    assert turn.instruction == WRITER_MD.read_text() == writer.INSTRUCTION
    assert turn.timeout == harness.TIME_LIMIT == 900


async def test_the_prompt_gives_the_topic_the_theme_and_the_brief():
    turn = Turn(submits)
    await write(turn, theme="warm")
    assert turn.prompt == (
        "Topic: How tides work\n"
        "Theme: warm (submit with it unless the brief asks for another)\n\n"
        f"Brief:\n{BRIEF}\n\n"
        "Plan in a few lines, then call submit_deck with the title, the whole deck and the theme.")


def test_an_empty_brief_is_said_plainly():
    prompt = writer.prompt_for("Tides", "  ", "editorial")
    assert "Brief:\n(none: use what you know about the topic, and no photos)" in prompt


def test_a_revision_hands_the_writer_the_earlier_deck_and_what_to_change():
    prompt = writer.prompt_for("Tides, shorter", "Make slide 2 shorter.", "minimal", earlier=DECK)
    assert prompt == (
        "Topic: Tides, shorter\n"
        "Theme: minimal (submit with it unless the brief asks for another)\n\n"
        "This revises an earlier deck. Keep everything the changes don't touch: its slides, words, photos and "
        "credits.\n\n"
        f"The earlier deck:\n<deck>\n{DECK.strip()}\n</deck>\n\n"
        "What to change:\nMake slide 2 shorter.\n\n"
        "Plan in a few lines, then call submit_deck with the title, the whole revised deck and the theme.")


def test_adk_reads_submit_deck_with_its_three_arguments_and_no_context():
    [tool] = writer.tools_for(harness.Desk(topic="T"), "editorial", "")
    declaration = FunctionTool(tool)._get_declaration()
    assert declaration.name == "submit_deck"
    assert declaration.parameters_json_schema["required"] == ["title", "markdown", "theme"]
    assert "tool_context" not in declaration.parameters_json_schema["properties"]


def test_the_instruction_carries_the_deck_rules():
    text = WRITER_MD.read_text()
    assert "submit_deck(" in text and "make_slides" not in text and "find_images" not in text
    for line in ("kicker:", "image:", "## ", "stat:", "```chart", "quote:", "layout: split", "> "):
        assert line in text, line
    for theme in ("editorial", "minimal", "warm", "bold"):
        assert f"`{theme}`" in text
    assert "only the photo addresses the brief gives" in text  # the writer can't search
    assert "never draft the deck in your thinking" in text
    assert "can't see" in text  # the writer knows it sees only the brief
    assert "What to change" in text  # a revision
    assert "Asha" not in text


# Through the real focused turn: the accepted submit is the last model call.

def submit_call() -> types.Part:
    args = {"title": "Why tides come twice", "markdown": DECK, "theme": "minimal"}
    return types.Part(function_call=types.FunctionCall(id="c1", name="submit_deck", args=args))


class Writes(BaseLlm):
    """A stand-in model for the real focused turn: submits the deck straight away, and would reply "done" if it were
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
        written = await writer.write("How tides work", "", "editorial", odie.focused_turn)
    finally:
        await odie.close()
    assert written == writer.Written(title="Why tides come twice", markdown=DECK, theme="minimal")
    assert len(Writes.seen) == 1  # no model call after "Accepted."
    request = Writes.seen[0]
    assert sorted(request.tools_dict) == ["submit_deck"]
    assert WRITER_MD.read_text().strip() in str(request.config.system_instruction)


def test_deck_writer_md_says_the_brief_may_end_with_the_users_own_material():
    text = WRITER_MD.read_text()
    assert "## Source material" in text and "the user's own text" in text
