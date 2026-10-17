"""The sources of an explainer video (odie.video.sources): what the user gave, named by the chat model and read by
Odie's code word for word. "my message" is the user's message of this chat turn without Odie's trailer; a file in
Odie's workspace is read when one is there by that path, else a note by the vault's own reader. Limits and refusals
come back as words to act on. Everything here is made up and lives under tmp_path."""
import os
from contextlib import contextmanager

import pytest

from odie.agent import turn
from odie.agent.tools.files import in_workspace
from odie.store.db import Store
from odie.video import sources

TIDES = "Asha's notes on tides.\n\n| place | high tide |\n|---|---|\n| Goa | 2.1 m |\n| Kochi | 0.9 m |"


@contextmanager
def chat_turn(text: str):
    """A chat turn as the runner runs it: the user's words of this turn in turn.USER_TEXT, for its tools."""
    token = turn.USER_TEXT.set(text)
    try:
        yield
    finally:
        turn.USER_TEXT.reset(token)


@pytest.fixture
def store(isolated_settings, tmp_path):
    assert str(isolated_settings.data_dir).startswith(str(tmp_path))
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    return s


@pytest.fixture
def vault(store, tmp_path):
    """A tiny vault of made-up notes, set as the notes folder."""
    from odie.vault import settings
    folder = tmp_path / "vault"
    (folder / "Science").mkdir(parents=True)
    (folder / "Science" / "Tides.md").write_text(TIDES, encoding="utf-8")
    settings.put(store, dir=str(folder))
    settings.index_for(store).scan()  # so names, titles and aliases match too, as in Odie
    return folder


def workspace():
    from odie.agent.tools.files import workspace as odie_workspace
    return odie_workspace()


# Which kind a reference is.

@pytest.mark.parametrize("reference", ["my message", "My Message", "  the user's message ", "The User's Message"])
def test_the_users_message_is_named_in_either_form_in_any_case(reference):
    assert sources.is_users_message(reference) is True


@pytest.mark.parametrize("reference", ["my messages", "message", "notes/my message.txt", "Tides"])
def test_other_references_are_not_the_users_message(reference):
    assert sources.is_users_message(reference) is False


@pytest.mark.parametrize("name", ["notes.md", "a.txt", "t.csv", "d.json", "p.html", "e.ics", "s.svg", "UP.MD"])
def test_text_files_may_be_sources(name):
    assert sources.is_text_file(name) is True


@pytest.mark.parametrize("name", ["photo.png", "deck.pptx", "song.mp3", "README", "archive.zip"])
def test_other_files_may_not(name):
    assert sources.is_text_file(name) is False


# "my message"

def test_my_message_is_this_turns_message(store):
    with chat_turn(TIDES):
        found = sources.resolve(["my message"], store)
    assert [(s.label, s.text) for s in found] == [("The user's message", TIDES)]


def test_my_message_from_a_resumed_turn_loses_the_context_block_and_picture_markers(store):
    # a turn resumed after an approval card gets the stored message back, trailer and all
    stored = TIDES + "\n[image:871a5acbefc94de3]\n\n[context: now 09:30 Fri 16 Oct · Goa]"
    with chat_turn(stored):
        found = sources.resolve(["The user's message"], store)
    assert found[0].text == TIDES


def test_my_message_in_background_work_is_refused(store):
    assert turn.USER_TEXT.get() is None  # a tracker or watch check: no user turn
    with pytest.raises(sources.SourceProblem, match="user's message"):
        sources.resolve(["my message"], store)
    with chat_turn("   \n\n[context: now 09:30]"), pytest.raises(sources.SourceProblem, match="user's message"):
        sources.resolve(["my message"], store)


# What the model sent as sources.

@pytest.mark.parametrize(("given", "meant"), [(None, []), (["my message"], ["my message"]),
                                              ('["my message", "Tides"]', ["my message", "Tides"]),
                                              ("my message", ["my message"])])
def test_sources_as_given(given, meant):
    assert sources.sources_as_given(given) == meant


@pytest.mark.parametrize("given", [5, {"note": "Tides"}, 2.5, True])
def test_sources_that_arent_a_list_or_text_are_refused(given):
    with pytest.raises(sources.SourceProblem, match="list"):
        sources.sources_as_given(given)


# Notes, read by the vault's own reader.

def test_a_note_is_read_by_its_name_or_its_path(store, vault):
    by_path = sources.resolve(["Science/Tides.md"], store)
    assert [(s.label, s.text) for s in by_path] == [("Note: Science/Tides.md", TIDES)]
    by_name = sources.resolve(["Science/Tides"], store)
    assert by_name[0].text == TIDES


def test_a_workspace_file_wins_over_a_loose_note_match(store, vault):
    (workspace() / "tides.md").write_text("Made in the workspace: Kochi 0.9 m.", encoding="utf-8")
    found = sources.resolve(["tides.md"], store)  # the vault's "Science/Tides.md" matches "tides" by its name
    assert [(s.label, s.text) for s in found] == [("File: tides.md", "Made in the workspace: Kochi 0.9 m.")]
    assert sources.resolve(["Tides"], store)[0].label == "Note: Tides"  # no such file: the note


def test_a_note_or_file_that_isnt_there_is_an_error_naming_it(store, vault):
    with pytest.raises(sources.SourceProblem, match="Ocean currents"):
        sources.resolve(["Ocean currents"], store)


# Files in Odie's workspace.

def test_a_text_file_in_the_workspace_is_read_word_for_word(store):
    (workspace() / "notes").mkdir()
    (workspace() / "notes" / "tides.txt").write_text(TIDES, encoding="utf-8")
    found = sources.resolve(["notes/tides.txt"], store)
    assert [(s.label, s.text) for s in found] == [("File: notes/tides.txt", TIDES)]


def test_a_path_outside_the_workspace_is_refused(store, tmp_path):
    (tmp_path / "secret.txt").write_text("not for the video", encoding="utf-8")
    assert not (tmp_path / "secret.txt").resolve().is_relative_to(workspace().resolve())
    with pytest.raises(sources.SourceProblem, match="workspace"):
        sources.resolve(["../secret.txt"], store)
    with pytest.raises(sources.SourceProblem, match="workspace"):
        sources.resolve([str(tmp_path / "secret.txt")], store)


def test_a_link_out_of_the_workspace_is_refused(store, tmp_path):
    (tmp_path / "secret.txt").write_text("not for the video", encoding="utf-8")
    os.symlink(tmp_path / "secret.txt", workspace() / "link.txt")
    assert in_workspace("link.txt") is None
    with pytest.raises(sources.SourceProblem, match="workspace"):
        sources.resolve(["link.txt"], store)


def test_a_home_path_and_a_nul_byte_are_refused_cleanly(store):
    assert in_workspace("~/secret.txt") is None  # the home folder isn't the workspace
    assert in_workspace("notes\x00.txt") is None
    with pytest.raises(sources.SourceProblem, match="workspace"):
        sources.resolve(["~/secret.txt"], store)
    with pytest.raises(sources.SourceProblem, match="workspace"):
        sources.resolve(["notes\x00.txt"], store)


def test_a_binary_file_is_refused(store):
    (workspace() / "photo.png").write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00")
    with pytest.raises(sources.SourceProblem, match="text"):
        sources.resolve(["photo.png"], store)


def test_a_text_named_file_that_isnt_text_is_refused(store):
    (workspace() / "odd.txt").write_bytes(b"\xff\xfe\x00\x81 not utf-8")
    with pytest.raises(sources.SourceProblem, match="text"):
        sources.resolve(["odd.txt"], store)


# Limits.

def test_at_most_five_sources(store):
    for n in range(6):
        (workspace() / f"part-{n}.txt").write_text("tides", encoding="utf-8")
    five = sources.resolve([f"part-{n}.txt" for n in range(5)], store)
    assert len(five) == 5
    with pytest.raises(sources.SourceProblem, match="at most 5"):
        sources.resolve([f"part-{n}.txt" for n in range(6)], store)


def test_one_source_is_at_most_40000_characters(store):
    (workspace() / "long.txt").write_text("x" * 40_000, encoding="utf-8")
    (workspace() / "longer.txt").write_text("x" * 40_001, encoding="utf-8")
    assert len((sources.resolve(["long.txt"], store))[0].text) == 40_000
    with pytest.raises(sources.SourceProblem, match="40,000") as raised:
        sources.resolve(["longer.txt"], store)
    assert "longer.txt" in str(raised.value)


def test_a_long_note_is_measured_whole_not_cut(store, vault):
    (vault / "Long.md").write_text("y" * 40_001, encoding="utf-8")
    with pytest.raises(sources.SourceProblem, match="40,000"):
        sources.resolve(["Long.md"], store)


def test_all_sources_together_are_at_most_60000_characters(store):
    (workspace() / "a.txt").write_text("a" * 30_000, encoding="utf-8")
    (workspace() / "b.txt").write_text("b" * 30_000, encoding="utf-8")
    (workspace() / "c.txt").write_text("c", encoding="utf-8")
    assert len(sources.resolve(["a.txt", "b.txt"], store)) == 2
    with pytest.raises(sources.SourceProblem, match="60,000"):
        sources.resolve(["a.txt", "b.txt", "c.txt"], store)


# The brief with its sources: what brief.md holds and the writer reads.

def test_the_brief_is_followed_by_each_source_word_for_word():
    found = [sources.Source(label="The user's message", text=TIDES),
             sources.Source(label="File: notes/extra.txt", text="Kochi has two tides a day.")]
    text = sources.brief_with_sources("For a ten-year-old. 1. The moon pulls. 2. The table of places.", found)
    plan, material = text.split("## Source material", 1)
    assert plan.startswith("For a ten-year-old. 1. The moon pulls.")
    assert "### The user's message\n\n" + TIDES in material
    assert material.index(TIDES) < material.index("### File: notes/extra.txt\n\nKochi has two tides a day.")


def test_without_sources_the_brief_is_as_it_is():
    assert sources.brief_with_sources("  For a ten-year-old.  ", []) == "For a ten-year-old."
