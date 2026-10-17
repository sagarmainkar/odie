"""make_deck, the documents skill's chat tool for decks: the chat only briefs the deck. What it refuses (no topic, a
brief over 6,000 characters, a theme that doesn't exist, a revise that is a path or names no deck), the job it queues
(a topic, a theme and a brief; for a revision, the earlier deck's Markdown and title), a folder of its own for every
deck, and the reply that says how long."""
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from google.adk.tools import FunctionTool

from odie.agent import turn
from odie.agent.tools.files import workspace
from odie.making import chat as making_chat
from odie.making import deck, jobs
from odie.skills.documents import tools
from odie.store.db import Store

SKILL = Path(tools.__file__).parent
GOLDEN = Path(__file__).parent / "golden" / "tool_declarations.json"
EARLIER = "# Tides\nkicker: For Asha, who sails\nimage: https://ex.com/sea.jpg (credit: Ana)\n\n# Two bulges\n- a\n"


@pytest.fixture
def world(isolated_settings, tmp_path, monkeypatch):
    """A store and jobs.submit replaced by a recorder. Everything on disk is under tmp_path."""
    assert str(isolated_settings.data_dir).startswith(str(tmp_path))
    store = Store(tmp_path / "assistant.db")
    store.init_schema()
    monkeypatch.setitem(jobs.hooks, "store", store)
    submitted = []

    def record(job):
        submitted.append(job)
        return len(submitted)

    monkeypatch.setattr(jobs, "submit", record)
    return store, submitted


async def call_as_adk_does(**args) -> dict:
    """make_deck called the way ADK calls it: through its FunctionTool, with the model's arguments as they came."""
    chat = SimpleNamespace(session=SimpleNamespace(id="chat-7"))
    return await FunctionTool(tools.make_deck).run_async(args=args, tool_context=chat)


def earlier_deck(name="Tides", markdown=EARLIER) -> Path:
    path = workspace() / f"{name}.deck.md"
    path.write_text(markdown, encoding="utf-8")
    return path


# The refusals: each one comes back before anything is queued.

async def test_an_empty_topic_is_refused(world):
    out = await tools.make_deck("   ")
    assert out["error"] == tools.NO_TOPIC and world[1] == []


async def test_a_null_topic_is_the_topic_refusal(world):
    out = await call_as_adk_does(topic=None)
    assert out["error"] == tools.NO_TOPIC and world[1] == []


async def test_a_brief_over_6000_characters_is_refused(world):
    out = await tools.make_deck("Tides", brief="x" * 6001)
    assert "6,001" in out["error"] and "at most 6,000" in out["error"] and "what the deck needs" in out["error"]
    assert world[1] == []
    assert "result" in await tools.make_deck("Tides", brief="x" * 6000)


async def test_a_theme_that_doesnt_exist_is_refused_naming_the_four(world):
    out = await tools.make_deck("Tides", theme="neon")
    assert out["error"] == "There's no theme called neon: use one of editorial, minimal, warm, bold."
    assert world[1] == []


@pytest.mark.parametrize("revise", ["../x", "notes/Tides", "..\\Tides", "~Tides", "/etc/hosts", "Tides/.."])
async def test_a_revise_that_is_a_path_is_refused(world, revise):
    earlier_deck()
    out = await tools.make_deck("Tides, shorter", brief="Make slide 2 shorter.", revise=revise)
    assert out["error"] == (f'revise is the name of an earlier deck in the workspace, as its files are named '
                            f'("Meghalaya Trip Guide"), not a path; got "{revise}".')
    assert world[1] == []


async def test_a_revise_that_names_no_deck_is_refused_with_the_decks_there(world):
    earlier_deck("Tides")
    earlier_deck("Moon")
    out = await tools.make_deck("Tides, shorter", brief="Make slide 2 shorter.", revise="Sun")
    assert out["error"] == ('There\'s no deck called "Sun" in the workspace. The decks there: Moon, Tides. Leave '
                            'revise empty to make a new deck.')
    assert world[1] == []


async def test_with_no_decks_at_all_the_refusal_says_so(world):
    out = await tools.make_deck("Tides, shorter", revise="Tides")
    assert out["error"] == ('There\'s no deck called "Tides" in the workspace. There are no decks there yet. Leave '
                            'revise empty to make a new deck.')


async def test_a_deck_file_that_leads_out_of_the_workspace_is_no_deck(world, tmp_path):
    outside = tmp_path / "elsewhere.md"
    outside.write_text(EARLIER)
    (workspace() / "Leak.deck.md").symlink_to(outside)
    out = await tools.make_deck("Leak", revise="Leak")
    assert out["error"].startswith('There\'s no deck called "Leak"') and world[1] == []


async def test_a_deck_is_made_only_when_the_user_asked_for_one(world):
    token = turn.USER_TEXT.set("Make a itinerary for four with food and stays")
    try:
        out = await tools.make_deck("Coorg weekend")
    finally:
        turn.USER_TEXT.reset(token)
    assert "chat" in out["error"] and "visual blocks" in out["error"] and world[1] == []


# A good call: the job carries what the writer needs, and no deck yet.

async def test_a_good_call_queues_a_deck_job_with_the_topic_theme_and_brief(world, tmp_path):
    _store, submitted = world
    chat = SimpleNamespace(session=SimpleNamespace(id="chat-7"))
    brief = "For Asha, who sails. 1. The moon pulls the sea. 2. Two bulges, two tides a day."
    out = await tools.make_deck(" How tides work ", brief=brief, theme="Warm", tool_context=chat)
    assert "result" in out, out
    job = submitted[0]
    assert (job.topic, job.title, job.brief) == ("How tides work", "How tides work", brief)
    assert job.kind == "deck" and job.data == {"theme": "warm", "earlier": "", "private": []}
    assert job.slug == "how-tides-work" and job.session_id == "chat-7"
    assert job.folder.is_dir() and job.folder.parent.name == "decks"
    assert str(job.folder).startswith(str(tmp_path))


async def test_null_brief_theme_and_revise_are_read_as_not_given(world):
    out = await call_as_adk_does(topic="Tides", brief=None, theme=None, revise=None)
    assert "result" in out, out
    job = world[1][0]
    assert job.brief == "" and job.data == {"theme": "editorial", "earlier": "", "private": []}


async def test_a_revision_hands_the_writer_the_earlier_deck_and_keeps_its_title(world):
    earlier_deck("Tides")
    out = await tools.make_deck("Tides, slide 2 shorter", brief="Make slide 2 shorter.", theme="minimal",
                                revise="Tides")
    assert "result" in out, out
    job = world[1][0]
    assert job.data["earlier"] == EARLIER and job.data["theme"] == "minimal"
    assert job.title == "Tides" and job.topic == "Tides, slide 2 shorter"
    assert job.brief == "Make slide 2 shorter."


async def test_a_revise_takes_the_newest_version_of_the_deck_by_its_number(world):
    earlier_deck("Tides", "# Tides\n- the first\n")
    earlier_deck("Tides (2)", "# Tides\n- the second\n")
    earlier_deck("Tides (10)", "# Tides\n- the tenth\n")
    earlier_deck("Tides (9)", "# Tides\n- the ninth\n")
    earlier_deck("Tides at night", "# Night\n- another deck\n")
    out = await tools.make_deck("Tides", brief="Shorter.", revise="Tides")
    assert "result" in out, out
    assert world[1][0].data["earlier"] == "# Tides\n- the tenth\n"  # by the number: 10 is newer than 9


def test_the_newest_deck_is_chosen_by_its_number(world):
    folder = workspace()
    for name in ("Tides", "Tides (2)", "Tides (3)", "Tides at night", "Old Tides (4)"):
        (folder / f"{name}.deck.md").write_text("# T\n")
    assert tools.newest_deck("Tides").name == "Tides (3).deck.md"
    (folder / "Moon.deck.md").write_text("# M\n")
    assert tools.newest_deck("Moon").name == "Moon.deck.md"
    assert tools.newest_deck("Sun") is None


@pytest.mark.parametrize("revise", ["Tides.deck.md", "Tides.pptx", "Tides.pdf", " Tides "])
async def test_a_revise_may_name_one_of_the_decks_files(world, revise):
    earlier_deck("Tides")
    out = await tools.make_deck("Tides", brief="Shorter.", revise=revise)
    assert "result" in out, out
    assert world[1][0].data["earlier"] == EARLIER


async def test_a_revised_deck_that_wont_parse_goes_by_its_name(world):
    earlier_deck("Old notes", "a deck someone edited by hand")
    out = await tools.make_deck("Notes", revise="Old notes")
    assert "result" in out and world[1][0].title == "Old notes"


async def test_a_private_chat_marks_the_job_so_its_photos_arent_fetched(world):
    token = turn.PRIVATE.set({"amazon.in"})
    try:
        await tools.make_deck("My orders")
    finally:
        turn.PRIVATE.reset(token)
    assert world[1][0].data["private"] == ["amazon.in"]


async def test_the_same_topic_twice_gets_two_folders(world):
    _store, submitted = world
    await tools.make_deck("How Tides Work!")
    await tools.make_deck("How Tides Work!")
    first, second = submitted
    assert first.folder.name == "how-tides-work" and second.folder.name == "how-tides-work-2"


# The estimate and the reply.

def test_the_estimate_is_the_writing_plus_the_building():
    assert tools.minutes_to_make() == (2, 3)  # 1–2 writing + 20–60 s building, each rounded up to a minute


async def test_the_reply_says_how_long_and_that_the_chat_stays_free(world, monkeypatch):
    out = await tools.make_deck("Tides")
    assert out["result"].startswith("Making it now: about 2–3 minutes (writing the slides, then building the PDF and "
                                    "the PowerPoint). It'll appear in this chat, with a ping on the phone")
    assert "keep chatting" in out["result"]

    monkeypatch.setattr(jobs, "submit", lambda job: 2)
    queued = await tools.make_deck("Tides")
    assert queued["result"].startswith("It's number 2 in line, about 2–3 minutes after the one before.")
    assert re.search(r"about \d+–\d+ minutes", queued["result"])


# What the chat model is offered.

def test_the_skill_offers_make_deck_and_make_document_without_an_approval_card(isolated_settings, tmp_path):
    from odie.skills.registry import discover
    store = Store(tmp_path / "skills.db")
    store.init_schema()
    entry = {e.name: e for e in discover(store, user_dir=tmp_path / "none")}["documents"]
    assert entry.status == "ok" and entry.tools == ["make_deck", "make_document"]
    assert not any(tool._require_confirmation for tool in entry.tool_objs)


def test_the_declaration_has_exactly_topic_brief_theme_revise_and_sources():
    declaration = FunctionTool(tools.make_deck)._get_declaration()
    properties = declaration.parameters_json_schema["properties"]
    assert sorted(properties) == ["brief", "revise", "sources", "theme", "topic"]
    assert declaration.parameters_json_schema["required"] == ["topic"]

    golden = {d["name"]: d for d in json.loads(GOLDEN.read_text())}
    assert sorted(golden["make_deck"]["parameters_json_schema"]["properties"]) == sorted(properties)
    assert "make_slides" not in golden and "submit_deck" not in golden  # gone; the writer's tool, never the chat's


def test_find_images_sends_its_photos_to_the_decks_brief():
    from odie.agent.tools import browser
    source = Path(browser.__file__).read_text()  # find_images is declared only with a browser, so not in golden
    assert "in a deck's brief (make_deck" in source and "make_slides" not in source


def test_the_skill_says_how_to_write_the_brief():
    text = (SKILL / "SKILL.md").read_text()
    assert "make_deck(" in text and "make_slides" not in text and "brief" in text and "can't see" in text
    assert "6,000" in text and "revise=" in text
    assert "photo addresses" in text and "credit" in text and "find_images" in text  # the writer can't search
    assert "stat:" not in text and "```chart" not in text  # the slide Markdown is the writer's business
    assert "make_document" in text and "Nous Research" in text  # Word documents unchanged
    assert "Only when the user asks for a deck, slides, a document or a file" in text


def test_the_deck_kind_is_built_in(world):
    assert "odie.making.deck" in jobs.BUILT_IN_KINDS
    jobs.load_kinds()
    assert jobs.KINDS["deck"] is deck.KIND and deck.KIND.word == "deck" and deck.KIND.folder == "decks"


# Sources: what the user gave, read by Odie's code and put after the brief, word for word.

TIDES = "Asha's notes on tides.\n\n| place | high tide |\n|---|---|\n| Goa | 2.1 m |"


async def test_my_message_goes_into_the_jobs_brief_after_the_plan(world):
    _store, submitted = world
    chat = SimpleNamespace(session=SimpleNamespace(id="chat-7"))
    said = "Make a deck from this:\n\n" + TIDES
    token = turn.USER_TEXT.set(said)  # the runner sets the user's words for the turn's tools
    try:
        out = await tools.make_deck("How tides work", brief="For a ten-year-old. Show the table.",
                                 sources=["my message"], tool_context=chat)
    finally:
        turn.USER_TEXT.reset(token)
    assert "result" in out, out
    brief = submitted[0].brief
    assert brief.startswith("For a ten-year-old. Show the table.")
    assert "## Source material" in brief and TIDES in brief and "[context:" not in brief


async def test_a_workspace_file_is_quoted_word_for_word_into_the_jobs_brief(world):
    _store, submitted = world
    (workspace() / "tides.md").write_text(TIDES, encoding="utf-8")
    out = await tools.make_deck("How tides work", brief="For Asha.", sources=["tides.md"])
    assert "result" in out, out
    brief = submitted[0].brief
    assert brief.startswith("For Asha.") and "### File: tides.md" in brief and TIDES in brief


async def test_the_sources_text_reaches_brief_md_when_the_job_is_written(world):
    _store, submitted = world
    (workspace() / "tides.md").write_text(TIDES, encoding="utf-8")
    await tools.make_deck("How tides work", brief="For Asha.", sources=["tides.md"])
    job = submitted[0]
    jobs.write_brief(job)
    assert TIDES in (job.folder / "brief.md").read_text(encoding="utf-8")


async def test_a_source_that_cant_be_read_is_an_error_and_nothing_is_queued(world):
    out = await tools.make_deck("How tides work", brief="For Asha.", sources=["../../outside.txt"])
    assert "workspace" in out["error"] and world[1] == []
    out = await tools.make_deck("How tides work", sources=["a.txt"] * 6)
    assert "at most 5" in out["error"] and world[1] == []
    assert not (workspace() / "decks").exists()  # no folder made for a refused deck


@pytest.mark.parametrize("given", [None, []])
async def test_no_sources_leaves_the_brief_as_it_is(world, given):
    out = await call_as_adk_does(topic="Tides", brief="For Asha.", sources=given)
    assert "result" in out, out
    assert world[1][0].brief == "For Asha."


async def test_sources_sent_as_json_text_are_read_as_the_list(world):
    out = await call_as_adk_does(topic="How tides work", brief="For Asha.", sources='["my message"]')
    assert "error" in out and "user's message" in out["error"]  # read as the list: no user turn here, so refused


async def test_sources_that_arent_a_list_are_an_error(world):
    out = await call_as_adk_does(topic="How tides work", sources={"note": "Tides"})
    assert "list" in out["error"] and world[1] == []


async def test_a_brief_over_the_limit_is_told_to_use_sources(world):
    out = await tools.make_deck("Tides", brief="x" * 6001)
    assert out["error"].endswith(making_chat.USE_SOURCES) and world[1] == []
    assert making_chat.USE_SOURCES == "Pass what the user gave in sources instead of copying it."


def test_the_declaration_offers_sources_last_as_a_list_of_texts_or_nothing():
    declaration = FunctionTool(tools.make_deck)._get_declaration()
    properties = declaration.parameters_json_schema["properties"]
    assert list(properties)[-1] == "sources"
    assert properties["sources"]["anyOf"][0] == {"items": {"type": "string"}, "type": "array"}
    golden = {d["name"]: d for d in json.loads(GOLDEN.read_text())}
    assert golden["make_deck"]["parameters_json_schema"]["properties"]["sources"] == properties["sources"]


def test_the_skill_says_to_pass_what_the_user_gave_in_sources():
    text = (SKILL / "SKILL.md").read_text()
    assert "`sources`" in text and "my message" in text and "instead of" in text
