"""The recall tool: past chats and memories in one search. Every path is a temp copy (never the real ~/.odie)."""
import pytest

from odie.memory.store import MemoryFile
from odie.recall.chats import Exchange
from odie.recall.tools import make_recall_tool
from odie.store.db import Store


@pytest.fixture
def home(isolated_settings, tmp_path):
    """The settings with every path in tmp_path, checked before anything is read or written."""
    assert isolated_settings.data_dir == tmp_path
    assert isolated_settings.memory_file.parent == tmp_path
    return isolated_settings


@pytest.fixture
def store(home, tmp_path):
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    return s


@pytest.fixture
def memory(home, tmp_path):
    mf = MemoryFile(tmp_path / "m.md", tmp_path / ".lock", "odie")
    mf.update("Rent day", "The studio.local rent is paid on the first.", topic="Home")
    return mf


def exchange(text: str, day: int = 3, hour: int = 10) -> Exchange:
    from datetime import UTC, datetime
    ts = datetime(2026, 11, day, hour, tzinfo=UTC).timestamp()
    return Exchange(session_id="chat-1", ts=ts, day=f"2026-11-{day:02d}", text=text)


async def test_recall_lines_are_tagged_and_dated(store, memory):
    from odie.recall.fill import recall_index
    ix = recall_index()
    ix.add_exchanges([exchange("you: which kettle should Dev buy\nOdie: the steel kettle, it boils fast")])
    ix.sync_memories(memory.load().entries())
    tool = make_recall_tool(store, memory)
    assert tool.name == "recall"
    out = await tool.func(query="kettle")
    assert out == "[chat 3 Nov] you: which kettle should Dev buy · Odie: the steel kettle, it boils fast"
    out = await tool.func(query="rent")
    assert out.startswith("[memory] Rent day (")
    assert "The studio.local rent is paid on the first." in out


async def test_recall_cuts_each_line_at_500_characters(store, memory):
    from odie.recall.fill import recall_index
    recall_index().add_exchanges([exchange("you: kettle " + "x" * 900 + "\nOdie: ok")])
    out = await make_recall_tool(store, memory).func(query="kettle")
    assert out.endswith("…")
    assert len(out.split("] ", 1)[1]) == 501  # 500 characters of the passage, then the ellipsis


async def test_recall_dates_can_narrow_the_search(store, memory):
    from odie.recall.fill import recall_index
    recall_index().add_exchanges([exchange("you: kettle on Monday\nOdie: ok", day=2),
                                  exchange("you: kettle on Tuesday\nOdie: ok", day=3)])
    out = await make_recall_tool(store, memory).func(query="kettle", since="2026-11-03")
    assert "Tuesday" in out and "Monday" not in out


async def test_recall_says_when_nothing_matches(store, memory):
    out = await make_recall_tool(store, memory).func(query="zebra")
    assert out == "Nothing in past chats or memories matches that."


async def test_recall_falls_back_to_memory_words(store, memory, monkeypatch):
    def broken():
        raise RuntimeError("index is locked")
    monkeypatch.setattr("odie.recall.fill.recall_index", broken)
    out = await make_recall_tool(store, memory).func(query="rent")
    assert "(past chats aren't indexed yet)" in out
    assert "[memory] Rent day" in out


async def test_recall_fallback_with_nothing_remembered(store, memory, monkeypatch):
    def broken():
        raise RuntimeError("index is locked")
    monkeypatch.setattr("odie.recall.fill.recall_index", broken)
    out = await make_recall_tool(store, memory).func(query="zebra")
    assert out == "Nothing in past chats or memories matches that.\n(past chats aren't indexed yet)"


def test_recall_is_a_memory_tool_for_confidentiality():
    from odie.agent import confidential
    assert "recall" in confidential.MEMORY
    assert confidential.label_for("recall") == "your memory"


def test_search_memories_is_gone(memory):
    from odie.memory.tools import make_memory_tools
    assert "search_memories" not in {t.name for t in make_memory_tools(memory)}
