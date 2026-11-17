"""Personalities: each has its own threads, memory, name, picture and instructions, and nothing of one reaches another
or everyday Odie. Most tests here try to cross one of those lines."""
import io
import re
import sqlite3
import time
from types import SimpleNamespace

import pytest
from PIL import Image

from odie import config, persona, personalities, threads
from odie.app.runner import OdieRunner
from odie.store.db import Store
from tests.test_threads import _say

D = "2026-11-17"
ODIE = personalities.ODIE


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    return s


@pytest.fixture
async def runner(store):
    r = OdieRunner(store)
    yield r
    await r.close()


@pytest.fixture
def odies_soul(monkeypatch, tmp_path):
    """Everyday Odie with a SOUL.md of its own, in this test's folder."""
    from odie.app import routes
    path = tmp_path / "SOUL.md"
    path.write_text("You are Odie, the everyday one. Sunny.")
    monkeypatch.setattr(routes, "SOUL_PATH", path)
    return path


MIRAS_SOUL = "You are Mira. Dry and brief."


async def _mira_with_a_thread(runner, soul: str = MIRAS_SOUL):
    """A personality called Mira, her instructions, and her first thread."""
    mira = personalities.create(runner.store, "Mira")
    if soul:
        personalities.save_soul(mira.id, soul)
    sid = await runner.session_for(mira.id, D)
    return mira, sid


def _ctx(session_id: str) -> SimpleNamespace:
    """What ADK hands a callback or a tool, as far as Odie reads it: the chat it is running in."""
    return SimpleNamespace(session=SimpleNamespace(id=session_id))


def _said(history: dict) -> list[str]:
    """The user's words in a history answer, oldest first."""
    return [item["text"] for item in history["items"] if item["role"] == "user"]


def _jpeg() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 120, 60)).save(buf, "JPEG")
    return buf.getvalue()


# ── the personalities themselves ──

def test_create_get_and_list(store):
    mira = personalities.create(store, "Mira")
    personalities.create(store, "Coach")
    assert re.fullmatch(r"[0-9a-f]{12}", mira.id)
    assert personalities.get(store, mira.id) == mira
    assert [p.name for p in personalities.list_all(store)] == ["Mira", "Coach"]  # oldest first
    assert personalities.get(store, "") is None
    assert personalities.get(store, "nope") is None


def test_names(store):
    assert personalities.name_problem(store, "  ") == "Give it a name."
    assert personalities.name_problem(store, "odie") == "That is the everyday one's name."
    assert personalities.name_problem(store, "ODIE ") == "That is the everyday one's name."
    mira = personalities.create(store, "Mira")
    assert personalities.name_problem(store, "mira") == "You already have one called Mira."
    assert personalities.name_problem(store, "mira", but=mira.id) is None  # renaming it to its own name
    with pytest.raises(ValueError, match="You already have one called Mira."):
        personalities.create(store, " MIRA ")
    assert personalities.create(store, "x" * 40).name == "x" * 24
    assert personalities.create(store, "Mira 🌙").name == "Mira 🌙"
    persona.set_name(store, "Iris")  # the name the user gave Odie is taken too
    assert personalities.name_problem(store, "iris") == "That is the everyday one's name."


def test_rename_and_picture(store):
    mira = personalities.create(store, "Mira")
    assert personalities.rename(store, mira.id, "Mira B").name == "Mira B"
    with pytest.raises(ValueError, match="everyday"):
        personalities.rename(store, mira.id, "Odie")
    aid = persona.store_picture(_jpeg())
    assert personalities.set_avatar(store, mira.id, aid).avatar == aid
    assert personalities.set_avatar(store, mira.id, None).avatar is None


def test_soul_round_trip(store):
    mira = personalities.create(store, "Mira")
    assert personalities.folder(mira.id) == config.settings.config_dir / "personalities" / mira.id
    assert personalities.load_soul(mira.id) is None
    assert personalities.save_soul(mira.id, "You are Mira. Dry and brief.") is True
    assert personalities.load_soul(mira.id) == "You are Mira. Dry and brief."
    assert personalities.save_soul(mira.id, "   ") is False  # blank: back to the default
    assert personalities.load_soul(mira.id) is None
    assert not (personalities.folder(mira.id) / "SOUL.md").exists()


def test_its_memory_file_is_in_its_folder(store):
    mira = personalities.create(store, "Mira")
    mf = personalities.memory_file(mira)
    assert mf.path == personalities.folder(mira.id) / "memories.md"
    assert mf.lock_path == config.settings.data_dir / f"memory-{mira.id}.lock"
    assert mf.profile == "Mira"


def test_a_thread_belongs_to_one(store):
    mira = personalities.create(store, "Mira")
    coach = personalities.create(store, "Coach")
    sid = "chat-2026-11-17-2"
    assert personalities.of_session(store, sid) == personalities.ODIE  # nobody claimed it
    assert personalities.of_session(store, None) == personalities.ODIE
    personalities.claim(store, sid, mira.id)
    assert personalities.of_session(store, sid) == mira.id
    personalities.claim(store, sid, mira.id)  # again, for the same one: nothing changes
    with pytest.raises(ValueError):
        personalities.claim(store, sid, coach.id)
    with pytest.raises(ValueError):
        personalities.claim(store, "chat-2026-11-17-3", "nope")  # no such personality
    assert personalities.sessions_of(store, mira.id) == [sid]
    assert personalities.owned_sessions(store) == frozenset({sid})
    assert sid in personalities.hidden_from(store, personalities.ODIE)
    assert sid not in personalities.hidden_from(store, mira.id)
    assert sid in personalities.hidden_from(store, coach.id)


def test_a_thread_odie_already_has_cannot_be_claimed(store):
    mira = personalities.create(store, "Mira")
    threads.set_pinned(store, "chat-2026-11-16", True)  # an everyday thread the user pinned: it has a row
    with pytest.raises(ValueError):
        personalities.claim(store, "chat-2026-11-16", mira.id)
    assert personalities.of_session(store, "chat-2026-11-16") == personalities.ODIE


def test_an_older_database_gains_the_columns(isolated_settings, tmp_path):
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.executescript("""
        CREATE TABLE threads(session_id TEXT PRIMARY KEY, title TEXT, pinned_at TEXT);
        INSERT INTO threads(session_id, title) VALUES ('chat-2026-10-02', 'Goa');
    """)
    old.close()
    s = Store(path)
    s.init_schema()
    assert "personality" in {r["name"] for r in s.query("pragma table_info(threads)")}
    assert "personality" in {r["name"] for r in s.query("pragma table_info(tasks)")}
    assert personalities.of_session(s, "chat-2026-10-02") == personalities.ODIE


def test_a_picture_for_a_personality_leaves_odies_alone(store):
    before = persona.get(store)
    aid = persona.store_picture(_jpeg())
    assert persona.avatar_path(aid) is not None
    assert persona.get(store) == before  # Odie's own picture setting was not touched
    odies = persona.save_avatar(store, _jpeg())["avatar"]
    assert odies and odies != aid
    persona.delete_picture(aid)
    assert persona.avatar_path(aid) is None
    assert persona.avatar_path(odies) is not None


# ── thread ids and the current chat ──

def test_segment_of():
    assert threads.segment_of("chat-2026-11-17") == 1
    assert threads.segment_of("chat-2026-11-17-4") == 4


async def test_the_next_free_id_is_above_every_id_in_use(runner):
    assert threads.next_free_id(runner.store, D) == f"chat-{D}-2"  # nothing yet: never the bare id
    await _say(runner, f"chat-{D}-5", "user", "x", time.time())
    assert threads.session_ids_on(D) == [f"chat-{D}-5"]
    assert threads.next_free_id(runner.store, D) == f"chat-{D}-6"
    mira = personalities.create(runner.store, "Mira")
    personalities.claim(runner.store, f"chat-{D}-9", mira.id)  # claimed, its session not made yet
    assert threads.next_free_id(runner.store, D) == f"chat-{D}-10"


async def test_a_personalitys_thread_never_takes_the_bare_id(runner):
    mira = personalities.create(runner.store, "Mira")
    assert runner.current_thread(mira.id) is None
    sid = await runner.session_for(mira.id, D)
    assert sid == f"chat-{D}-2"
    assert personalities.of_session(runner.store, sid) == mira.id
    assert runner.current_thread(mira.id) == sid
    assert await runner.session_for(mira.id, D) == sid  # asked again: the same thread
    assert runner.current_session_id(D) == f"chat-{D}"  # the bare id stays Odie's
    assert await runner.session_for(ODIE, D) == f"chat-{D}"
    assert personalities.of_session(runner.store, f"chat-{D}") == ODIE


async def test_odies_new_chat_skips_a_taken_number(runner):
    mira = personalities.create(runner.store, "Mira")
    await _say(runner, f"chat-{D}", "user", "Morning", time.time())
    hers = await runner.session_for(mira.id, D)
    assert hers == f"chat-{D}-2"
    new = await runner.new_chat(D)
    assert new == f"chat-{D}-3"
    assert runner.current_session_id(D) == new
    assert personalities.of_session(runner.store, new) == ODIE
    assert personalities.of_session(runner.store, hers) == mira.id


async def test_the_day_view_is_odies_and_skips_gaps(runner):
    mira = personalities.create(runner.store, "Mira")
    t = time.time()
    await _say(runner, f"chat-{D}", "user", "Odie one", t)
    hers = await runner.session_for(mira.id, D)
    await _say(runner, hers, "user", "Only for Mira", t + 1)
    third = await runner.new_chat(D)
    await _say(runner, third, "user", "Odie three", t + 2)
    day = await runner.history(D)
    assert _said(day) == ["Odie one", "Odie three"]
    assert "thread" not in day
    her_view = await runner.history(D, personality=mira.id)
    assert _said(her_view) == ["Only for Mira"]
    assert her_view["thread"] == hers


async def test_a_personality_with_no_thread_has_an_empty_view_and_gets_no_thread_from_looking(runner):
    mira = personalities.create(runner.store, "Mira")
    view = await runner.history(D, personality=mira.id)
    assert view["items"] == [] and view["thread"] is None
    assert runner.current_thread(mira.id) is None
    assert personalities.sessions_of(runner.store, mira.id) == []


async def test_a_personalitys_thread_goes_on_past_midnight(runner):
    mira = personalities.create(runner.store, "Mira")
    sid = await runner.session_for(mira.id, "2026-11-17")
    assert await runner.session_for(mira.id, "2026-11-18") == sid  # the same thread, a day later
    assert runner.current_session_id("2026-11-18") == "chat-2026-11-18"  # the new day's bare id is Odie's
    assert personalities.of_session(runner.store, "chat-2026-11-18") == ODIE
    assert await runner.new_chat("2026-11-18", mira.id) == "chat-2026-11-18-2"
    assert runner.current_thread(mira.id) == "chat-2026-11-18-2"
    assert personalities.sessions_of(runner.store, mira.id) == [sid, "chat-2026-11-18-2"]


async def test_the_thread_list_is_by_personality(runner):
    mira = personalities.create(runner.store, "Mira")
    coach = personalities.create(runner.store, "Coach")
    t = time.time()
    await _say(runner, f"chat-{D}", "user", "Everyday question", t)
    hers = await runner.session_for(mira.id, D)
    await _say(runner, hers, "user", "The lighthouse plan", t + 1)
    assert [x["id"] for x in threads.list_threads(runner.store)] == [f"chat-{D}"]
    assert [x["id"] for x in threads.list_threads(runner.store, personality=mira.id)] == [hers]
    assert threads.list_threads(runner.store, personality=coach.id) == []
    assert threads.list_threads(runner.store, q="lighthouse") == []  # a word said only to Mira
    assert [x["id"] for x in threads.list_threads(runner.store, q="lighthouse", personality=mira.id)] == [hers]


async def test_an_imported_thread_stays_out_of_the_day_and_does_not_push_the_numbers(runner):
    # odie.replay_threads numbers imported threads from 101, far past any new chat of the day
    t = time.time()
    await _say(runner, f"chat-{D}", "user", "Good morning", t)
    await _say(runner, f"chat-{D}-101", "user", "An imported conversation", t + 1)
    assert threads.is_imported(f"chat-{D}-101") and not threads.is_imported(f"chat-{D}-3")
    assert threads.next_free_id(runner.store, D) == f"chat-{D}-2"  # not 102
    assert _said(await runner.history(D)) == ["Good morning"]


# ── a prompt per thread ──

async def test_two_threads_keep_their_own_prompts(runner, odies_soul):
    mira, hers = await _mira_with_a_thread(runner)
    odies = f"chat-{D}"
    runner._prepare_prompt(hers, "hi")  # her turn starts
    runner._prepare_prompt(odies, "hi")  # then Odie's, while hers is still running
    her_prompt = runner._prompt_of(_ctx(hers))
    odie_prompt = runner._prompt_of(_ctx(odies))
    assert her_prompt.startswith(MIRAS_SOUL) and "Sunny" not in her_prompt
    assert odie_prompt.startswith("You are Odie, the everyday one. Sunny.") and "Dry and brief" not in odie_prompt


async def test_a_tap_resumes_as_the_threads_own_personality(runner, odies_soul):
    mira, hers = await _mira_with_a_thread(runner)
    runner._prepare_prompt(hers, "hi")
    runner._prepare_prompt(f"chat-{D}", "hi")  # Odie's turn ran after hers paused on a card
    assert runner._prompt_of(_ctx(hers)).startswith(MIRAS_SOUL)  # the tap resumes her turn: still hers
    runner._prompts.clear()  # a restart: nothing built is remembered
    assert runner._prompt_of(_ctx(hers)).startswith(MIRAS_SOUL)  # read from the thread's own row, not from memory


async def test_a_personality_keeps_odies_rules(runner, odies_soul):
    mira, hers = await _mira_with_a_thread(runner)
    her_prompt = runner._prompt_of(_ctx(hers))
    assert "\n\nRules:\n" in her_prompt and "<<<UNTRUSTED EMAIL>>>" in her_prompt
    assert re.search(r"\bOdie\b", her_prompt) is None  # where Odie's prompt says Odie, hers says Mira
    assert re.search(r"\bOdie\b", runner._prompt_of(_ctx(f"chat-{D}"))) is not None


async def test_blank_instructions_fall_back(runner):
    mira, hers = await _mira_with_a_thread(runner, soul="")
    assert runner._prompt_of(_ctx(hers)).startswith("You are Mira,")
    assert runner.who(mira.id).assistant == "Mira" and runner.who().assistant == "Odie"


def test_joined_index():
    assert personalities.joined_index("", "## Finance\n- Rent day") == (
        "Yours alone (what you save goes here):\nnothing yet\n\n"
        "Shared, the everyday memory (read it, don't change it):\n## Finance\n- Rent day")
    assert personalities.joined_index("## Private\n- The plan", "").startswith(
        "Yours alone (what you save goes here):\n## Private\n- The plan\n\nShared, the everyday memory")


async def test_her_index_lists_hers_then_the_shared(runner):
    mira, hers = await _mira_with_a_thread(runner)
    runner.memory.update("Rent day", "Paid on the first.", topic="Finance")
    runner.memory_of(mira.id).update("The lighthouse plan", "Kept between us.", topic="Private")
    index = runner.memory_index(mira.id)
    places = [index.index("Yours alone (what you save goes here):"), index.index("The lighthouse plan"),
              index.index("Shared, the everyday memory (read it, don't change it):"), index.index("Rent day")]
    assert places == sorted(places)  # hers first, under her label; then the shared ones under theirs
    assert "Rent day" in runner.memory_index() and "lighthouse" not in runner.memory_index()
    her_prompt = runner._prompt_of(_ctx(hers))
    assert "The lighthouse plan" in her_prompt and "Rent day" in her_prompt
    assert "lighthouse" not in runner._prompt_of(_ctx(f"chat-{D}"))


async def test_prefetch_reads_hers_and_the_shared_but_odies_reads_only_the_shared(runner):
    mira, hers = await _mira_with_a_thread(runner)
    runner.memory.update("Rent day", "Paid on the first.", topic="Finance")
    runner.memory_of(mira.id).update("The lighthouse plan", "Kept between us.", topic="Private")
    assert "Kept between us." in runner.prefetch("what was the lighthouse plan", mira.id)
    assert "Paid on the first." in runner.prefetch("when is rent day", mira.id)
    assert "Kept between us." not in runner.prefetch("what was the lighthouse plan")
    assert "Kept between us." in runner._prepare_prompt(hers, "what was the lighthouse plan")  # her message's trailer
    assert "Kept between us." not in runner._prepare_prompt(f"chat-{D}", "what was the lighthouse plan")


async def test_a_thread_that_lives_for_days_gets_todays_date(runner):
    mira, hers = await _mira_with_a_thread(runner)
    first = runner._static_prompt(hers)
    assert runner._static_prompt(hers) is first  # the same day: built once
    first.day = "2000-01-01"  # as if it had been built on an earlier day
    again = runner._static_prompt(hers)
    assert again is not first and again.day != "2000-01-01"


# ── memory by who is asking ──

def _memory_tools(runner) -> dict:
    """fetch_memory, update_memory and forget_memory as the chat agent has them, by name."""
    from odie.memory.tools import make_memory_tools
    tools = make_memory_tools(runner.memory, memory_for=runner._memory_for_chat)
    return {t.name: t.func for t in tools}


async def test_a_memory_saved_with_mira_is_hers_alone(runner):
    mira, hers = await _mira_with_a_thread(runner)
    tools = _memory_tools(runner)
    said = tools["update_memory"]("The lighthouse plan", "Kept between us.", "Private", tool_context=_ctx(hers))
    assert said.startswith("Saved 'The lighthouse plan'")
    assert runner.memory_of(mira.id).load().find("The lighthouse plan") is not None
    assert runner.memory.load().find("The lighthouse plan") is None  # not in the shared memory
    tools["update_memory"]("Rent day", "Paid on the first.", "Finance", tool_context=_ctx(f"chat-{D}"))
    assert runner.memory.load().find("Rent day") is not None  # said in the everyday chat: the shared one
    assert runner.memory_of(mira.id).load().find("Rent day") is None


async def test_she_can_read_the_shared_memory_and_odie_cannot_read_hers(runner):
    mira, hers = await _mira_with_a_thread(runner)
    tools = _memory_tools(runner)
    runner.memory.update("Rent day", "Paid on the first.", topic="Finance")
    runner.memory_of(mira.id).update("The lighthouse plan", "Kept between us.", topic="Private")
    assert "Paid on the first." in tools["fetch_memory"]("Rent day", tool_context=_ctx(hers))
    assert "Kept between us." in tools["fetch_memory"]("The lighthouse plan", tool_context=_ctx(hers))
    from_odie = tools["fetch_memory"]("The lighthouse plan", tool_context=_ctx(f"chat-{D}"))
    assert from_odie.startswith("Nothing remembered under")
    # she reads the shared memory but can't change it
    assert tools["forget_memory"]("Rent day", tool_context=_ctx(hers)) == "No memory called 'Rent day'."
    assert runner.memory.load().find("Rent day") is not None


async def test_a_watch_asked_of_a_personality_is_refused_without_a_card(runner):
    from odie.memory.tools import WATCH_IS_ODIES, watch_for_needs_tap
    mira, hers = await _mira_with_a_thread(runner)
    tools = _memory_tools(runner)
    needs_tap = watch_for_needs_tap(runner.memory, runner._memory_for_chat)
    watch = {"title": "Passport email", "content": "When: it comes. Do: tell me.", "topic": "Watch for"}
    assert needs_tap(**watch, tool_context=_ctx(hers)) is False  # no card: the tool itself says no
    assert needs_tap(**watch, tool_context=_ctx(f"chat-{D}")) is True  # in the everyday chat, the card as before
    said = tools["update_memory"](watch["title"], watch["content"], watch["topic"], tool_context=_ctx(hers))
    assert said == WATCH_IS_ODIES
    assert runner.memory.load().find("Passport email") is None  # not a watch in the shared memory
    assert not runner.memory_of(mira.id).exists()  # and nothing was written to hers


async def test_the_review_reads_and_writes_the_thread_owners_memory(runner, monkeypatch):
    mira, hers = await _mira_with_a_thread(runner)
    runner.review_every = 2
    reviewed = {}

    async def fake_review(memory, turns, index_text, on_change=None, store=None):
        reviewed.update(path=memory.path, turns=turns)
        return []

    monkeypatch.setattr("odie.app.runner.run_review", fake_review)
    runner._note_turn(f"chat-{D}", "an everyday thing", "ok")
    runner._note_turn(hers, "a private thing", "ok")
    runner._note_turn(hers, "another private thing", "ok")  # her second turn: hers are reviewed, into her memory
    await runner._review_task
    assert reviewed["path"] == runner.memory_of(mira.id).path
    assert reviewed["turns"] == [("a private thing", "ok"), ("another private thing", "ok")]
    assert runner._turns[ODIE] == [("an everyday thing", "ok")]  # Odie's turn still waits, not mixed in with hers


async def test_a_personality_that_never_saved_anything(runner):
    mira, hers = await _mira_with_a_thread(runner)
    tools = _memory_tools(runner)
    runner.memory.update("Rent day", "Paid on the first.", topic="Finance")
    assert not runner.memory_of(mira.id).exists()
    index = runner.memory_index(mira.id)
    assert "nothing yet" in index and "Rent day" in index
    assert "Paid on the first." in runner.prefetch("when is rent day", mira.id)
    assert tools["fetch_memory"]("Nope", tool_context=_ctx(hers)).startswith("Nothing remembered under")


# ── recall and the morning hello ──

def _exchange(session_id: str, text: str, day: int = 3, hour: int = 10):
    from datetime import UTC, datetime

    from odie.recall.chats import Exchange
    ts = datetime(2026, 11, day, hour, tzinfo=UTC).timestamp()
    return Exchange(session_id=session_id, ts=ts, day=f"2026-11-{day:02d}", text=text)


def _recall(runner):
    """The recall tool as the chat agent has it."""
    from odie.recall.tools import make_recall_tool
    return make_recall_tool(runner.store, runner.memory, memory_for=runner._memory_for_chat).func


async def test_a_word_said_only_to_mira_is_not_in_odies_recall(runner):
    from odie.recall.fill import recall_index
    from odie.recall.tools import NOTHING
    mira, hers = await _mira_with_a_thread(runner)
    recall_index().add_exchanges([_exchange(hers, "you: the lighthouse plan\nOdie: kept between us")])
    recall = _recall(runner)
    assert await recall(query="lighthouse", tool_context=_ctx(f"chat-{D}")) == NOTHING
    assert await recall(query="lighthouse") == NOTHING  # a background turn, in no chat at all
    hers_found = await recall(query="lighthouse", tool_context=_ctx(hers))
    assert hers_found.startswith("[chat 3 Nov] you: the lighthouse plan")


async def test_mira_recalls_everyday_chats_too_but_another_personality_cannot_recall_hers(runner):
    from odie.recall.fill import recall_index
    from odie.recall.tools import NOTHING
    mira, hers = await _mira_with_a_thread(runner)
    coach = personalities.create(runner.store, "Coach")
    coachs = await runner.session_for(coach.id, D)
    recall_index().add_exchanges([_exchange(hers, "you: the lighthouse plan\nOdie: kept between us"),
                                  _exchange(f"chat-{D}", "you: which kettle\nOdie: the steel kettle", hour=11)])
    recall = _recall(runner)
    assert "steel kettle" in await recall(query="kettle", tool_context=_ctx(hers))
    assert "steel kettle" in await recall(query="kettle", tool_context=_ctx(coachs))
    assert await recall(query="lighthouse", tool_context=_ctx(coachs)) == NOTHING


async def test_hidden_hits_do_not_use_up_the_answer(runner):
    from odie.recall.fill import recall_index
    mira, hers = await _mira_with_a_thread(runner)
    ix = recall_index()
    ix.add_exchanges([_exchange(hers, f"you: lighthouse note {i}\nOdie: ok", hour=i) for i in range(9)])
    ix.add_exchanges([_exchange(f"chat-{D}", "you: the lighthouse museum hours\nOdie: ten to five", day=2)])
    hidden = personalities.hidden_from(runner.store, ODIE)
    assert len(ix.keyword("lighthouse", k=8)) == 8  # with nothing hidden: the eight best, as before
    everyday = ix.keyword("lighthouse", k=8, hidden_sessions=hidden)
    assert [h.text for h in everyday] == ["you: the lighthouse museum hours\nOdie: ten to five"]
    assert len(await ix.search("lighthouse", k=8, hidden_sessions=hidden)) == 1
    # the meaning path scores only the passages _days lets through: her nine are not among them
    refs = ix._days(None, None, hidden)
    assert len(refs) == 1 and len(ix._days(None, None)) == 10


async def test_her_own_memory_is_found_only_by_her(runner):
    from odie.recall.tools import NOTHING
    mira, hers = await _mira_with_a_thread(runner)
    runner.memory_of(mira.id).update("The lighthouse plan", "Kept between us.", topic="Private")
    recall = _recall(runner)
    assert (await recall(query="lighthouse plan", tool_context=_ctx(hers))).startswith("[memory] The lighthouse plan")
    assert await recall(query="lighthouse plan", tool_context=_ctx(f"chat-{D}")) == NOTHING


async def test_with_no_index_the_memory_files_answer_and_hers_stays_hers(runner, monkeypatch):
    def no_index():
        raise OSError("the index won't open")

    monkeypatch.setattr("odie.recall.fill.recall_index", no_index)
    mira, hers = await _mira_with_a_thread(runner)
    runner.memory_of(mira.id).update("The lighthouse plan", "Kept between us.", topic="Private")
    runner.memory.update("Rent day", "Paid on the first.", topic="Finance")
    recall = _recall(runner)
    assert "[memory] The lighthouse plan" in await recall(query="lighthouse plan", tool_context=_ctx(hers))
    assert "[memory] Rent day" in await recall(query="rent day", tool_context=_ctx(hers))
    assert "lighthouse" not in await recall(query="lighthouse plan", tool_context=_ctx(f"chat-{D}"))


async def test_dropping_a_threads_passages(runner):
    from odie.recall.fill import recall_index
    ix = recall_index()
    ix.add_exchanges([_exchange("chat-2026-11-03-2", "you: the lighthouse plan\nOdie: kept"),
                      _exchange("chat-2026-11-03", "you: which kettle\nOdie: the steel kettle", hour=11)])
    assert ix.drop_sessions(["chat-2026-11-03-2"]) == 1
    assert ix.keyword("lighthouse") == [] and len(ix.keyword("kettle")) == 1


async def test_the_morning_hello_does_not_read_her_chats(runner, monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from odie.jobs.brief import BriefInputs
    from odie.morning import gather as morning
    mira, hers = await _mira_with_a_thread(runner)
    t = time.time()
    await _say(runner, f"chat-{D}", "user", "Remind me about the dentist", t - 60)
    await _say(runner, hers, "user", "The lighthouse plan stays between us", t - 30)
    now = datetime.now(ZoneInfo(config.settings.timezone))
    assert "lighthouse" in morning.recent_chats(now)  # with nothing hidden it would be read
    everyday = morning.recent_chats(now, personalities.owned_sessions(runner.store))
    assert "dentist" in everyday and "lighthouse" not in everyday

    async def no_weather(store):
        return None

    monkeypatch.setattr(morning, "today_weather", no_weather)
    gathered = await morning.gather(runner.store, now, BriefInputs(tasks=""))
    assert "dentist" in gathered.chats and "lighthouse" not in gathered.chats


# ── a reminder stays with whoever it was asked of; Odie's background jobs stay Odie's ──

def _task_tools(runner) -> dict:
    """task_add, task_update and task_list as the chat agent has them, by name."""
    from odie.agent.tools.local import make_local_tools
    return {t.name: t.func for t in make_local_tools(runner.store, config.settings.timezone)}


def _odie_said(history: dict) -> list[str]:
    """The assistant's words in a history answer, oldest first."""
    return [item["text"] for item in history["items"] if item["role"] == "odie"]


def test_quiet_push_says_who_and_never_what():
    assert personalities.quiet_push("Mira", "replied") == ("Mira replied", "Open Odie to read it.")
    assert personalities.quiet_push("Mira", "needs you") == ("Mira needs you", "Open Odie to answer.")
    assert personalities.quiet_push("Mira", "lapsed") == ("Mira: a request lapsed", "Open Odie to see it.")
    assert personalities.quiet_push("Mira", "reminder") == ("Mira", "A reminder is waiting.")


async def test_a_reminder_set_with_mira_is_hers(runner):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from odie import upcoming
    from odie.agent.tools.local import threads_summary
    from odie.jobs.brief import users_open_tasks
    mira, hers = await _mira_with_a_thread(runner)
    tools = _task_tools(runner)
    tools["task_add"]("Call the clinic", "reminder", "2026-11-20T10:00", tool_context=_ctx(hers))
    tools["task_add"]("Buy milk", "todo", tool_context=_ctx(f"chat-{D}"))
    rows = runner.store.query("select title, personality from tasks order by id")
    assert [(r["title"], r["personality"]) for r in rows] == [("Call the clinic", mira.id), ("Buy milk", None)]
    # everyday places: Today, the brief and the hello, what's coming up, the count in a message's context
    assert [r["title"] for r in runner.store.open_tasks()] == ["Buy milk"]
    assert [r["title"] for r in runner.store.list_tasks("open")] == ["Buy milk"]
    now = datetime(2026, 11, 18, 9, 0, tzinfo=ZoneInfo(config.settings.timezone))
    assert [r["title"] for r in users_open_tasks(runner.store, now)] == ["Buy milk"]
    assert all("clinic" not in str(item) for item in upcoming.from_tasks(runner.store, now))
    assert threads_summary(runner.store) == "Open threads: 1 to do."
    assert "clinic" not in tools["task_list"](tool_context=_ctx(f"chat-{D}"))
    assert "Call the clinic" not in runner._prepare_prompt(f"chat-{D}", "hi")
    # in her own chat she sees hers and the everyday ones
    assert sorted(r["title"] for r in runner.store.open_tasks(personality=mira.id)) == ["Buy milk", "Call the clinic"]
    her_list = tools["task_list"](tool_context=_ctx(hers))
    assert "Call the clinic" in her_list and "Buy milk" in her_list
    assert threads_summary(runner.store, mira.id) == "Open threads: 2 to do."
    assert "Call the clinic" in runner._prepare_prompt(hers, "hi")


async def test_her_reminder_fires_in_her_thread(runner, monkeypatch):
    from odie.jobs import reminders
    mira, hers = await _mira_with_a_thread(runner)
    pushed = []
    monkeypatch.setattr(reminders, "send_to_all", lambda store, title, body, url="/", tag=None: pushed.append((title, body)) or 1)
    _task_tools(runner)["task_add"]("Call the clinic", "reminder", "2026-11-17T10:00", tool_context=_ctx(hers))
    listening = runner.bus.queue()
    assert await reminders.run_due(runner.store, runner, "2026-11-17T10:00:30+05:30") == 1
    events = []
    while not listening.empty():
        events.append(listening.get_nowait())
    assert [(e["type"], e.get("kind"), e.get("session_id")) for e in events] == [("message", "reminder", hers)]
    assert _odie_said(await runner.history(D, personality=mira.id)) == ["Reminder: Call the clinic"]
    assert (await runner.history(D))["items"] == []  # nothing in the everyday chat
    assert runner.store.pending_notices() == []  # and nothing rings the curtain
    assert pushed == [("Mira", "A reminder is waiting.")]  # her name, not the reminder's words
    row = runner.store.one("select status, delivered_at, seen_at from tasks")
    assert row["status"] == "done" and row["delivered_at"] and row["seen_at"]
    assert await reminders.run_due(runner.store, runner, "2026-11-17T10:05:00+05:30") == 0  # once


async def test_odie_cannot_close_her_task_but_she_can_close_an_everyday_one(runner):
    mira, hers = await _mira_with_a_thread(runner)
    tools = _task_tools(runner)
    tools["task_add"]("Call the clinic", "reminder", "2026-11-20T10:00", tool_context=_ctx(hers))
    tools["task_add"]("Buy milk", "todo", tool_context=_ctx(f"chat-{D}"))
    her_task = runner.store.one("select id from tasks where title='Call the clinic'")["id"]
    milk = runner.store.one("select id from tasks where title='Buy milk'")["id"]
    said = await tools["task_update"](her_task, status="done", tool_context=_ctx(f"chat-{D}"))
    assert said == f"No task #{her_task}."  # as for an id that doesn't exist
    assert runner.store.one("select status from tasks where id=?", (her_task,))["status"] == "open"
    assert "status=done" in await tools["task_update"](her_task, status="done", tool_context=_ctx(hers))
    assert "status=done" in await tools["task_update"](milk, status="done", tool_context=_ctx(hers))


async def test_a_tracker_asked_of_a_personality_is_refused(runner):
    from odie.skills.trackers.tools import TOOLS
    mira, hers = await _mira_with_a_thread(runner)
    by_name = {t.name: t for t in TOOLS}
    assert personalities.ODIE_ONLY_TOOLS == frozenset({"track", "stop_tracker"})
    for name in ("track", "stop_tracker"):
        refused = await runner.plugin.before_tool_callback(tool=by_name[name], tool_args={}, tool_context=_ctx(hers))
        assert refused == {"error": personalities.ODIE_ONLY}
        allowed = await runner.plugin.before_tool_callback(tool=by_name[name], tool_args={}, tool_context=_ctx(f"chat-{D}"))
        assert allowed is None
    listing = await runner.plugin.before_tool_callback(tool=by_name["list_trackers"], tool_args={}, tool_context=_ctx(hers))
    assert listing is None  # reading Odie's trackers is fine: she reads the everyday side


# ── the routes and the terminal ──

@pytest.fixture
async def api(runner, monkeypatch):
    """The real app around the real runner, with no background jobs."""
    import httpx

    from odie.app.main import create_app
    monkeypatch.setenv("ODIE_SCHEDULER", "0")
    app = create_app(runner=runner, store=runner.store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c, app.router.lifespan_context(app):
        yield c


def _card(store, session_id: str, summary: str) -> int:
    """A card waiting for the user's tap in this thread."""
    return store.create_approval(session_id, "inv-" + summary, "req-" + summary, "run_shell", {"command": "ls"}, summary,
                                 None, None)


async def test_the_personalities_list_and_making_one(api, runner):
    assert (await api.get("/api/personalities")).json() == {"personalities": [], "everyday_waiting": 0}
    made = await api.post("/api/personalities", json={"name": "Mira"})
    assert made.status_code == 200
    pid = made.json()["id"]
    assert made.json() == {"id": pid, "name": "Mira", "avatar_url": None, "threads": 0, "waiting": 0}
    refused = await api.post("/api/personalities", json={"name": "odie"})
    assert refused.status_code == 422 and refused.json()["detail"] == "That is the everyday one's name."
    hers = await runner.session_for(pid, D)
    _card(runner.store, hers, "Run ls")
    listed = (await api.get("/api/personalities")).json()["personalities"]
    assert listed == [{"id": pid, "name": "Mira", "avatar_url": None, "threads": 1, "waiting": 1}]


async def test_a_chat_with_a_pick_goes_to_its_thread(api, runner, monkeypatch):
    mira, hers = await _mira_with_a_thread(runner)
    sent = []

    async def fake_chat(text, thinking=None, session_id=None, images=None, via=None):
        sent.append(session_id)
        yield {"type": "done", "text": "ok"}

    monkeypatch.setattr(runner, "chat", fake_chat)
    async with api.stream("POST", f"/api/chat?personality={mira.id}", json={"text": "hi"}) as r:
        await r.aread()
    async with api.stream("POST", "/api/chat", json={"text": "hi"}) as r:
        await r.aread()
    assert sent == [hers, None]  # with no pick the runner takes today's everyday chat, as before


async def test_a_thread_named_with_the_wrong_pick_is_not_found(api, runner):
    mira, hers = await _mira_with_a_thread(runner)
    odies = f"chat-{D}"
    await _say(runner, odies, "user", "Everyday question", time.time())
    await _say(runner, hers, "user", "The lighthouse plan", time.time())
    assert (await api.get(f"/api/threads/{hers}/history")).status_code == 404  # hers, with no pick
    assert (await api.get(f"/api/threads/{odies}/history?personality={mira.id}")).status_code == 404  # Odie's, her pick
    assert (await api.get(f"/api/threads/{hers}/history?personality={mira.id}")).status_code == 200
    assert (await api.post("/api/chat", json={"text": "hi", "session_id": hers})).status_code == 404
    assert (await api.post(f"/api/threads/{hers}/pin", json={"pinned": True})).status_code == 404
    assert (await api.post(f"/api/threads/{hers}/rename", json={"title": "x"})).status_code == 404
    assert (await api.post(f"/api/threads/{hers}/pin?personality={mira.id}", json={"pinned": True})).status_code == 200
    assert personalities.of_session(runner.store, hers) == mira.id  # pinning it didn't change whose it is
    assert [t["id"] for t in (await api.get("/api/threads")).json()["threads"]] == [odies]
    assert [t["id"] for t in (await api.get(f"/api/threads?personality={mira.id}")).json()["threads"]] == [hers]
    assert _said((await api.get(f"/api/history?date={D}")).json()) == ["Everyday question"]
    her_day = (await api.get(f"/api/history?date={D}&personality={mira.id}")).json()
    assert _said(her_day) == ["The lighthouse plan"] and her_day["thread"] == hers


async def test_new_chat_with_a_pick_is_a_new_thread_of_hers(api, runner):
    mira, hers = await _mira_with_a_thread(runner)
    made = (await api.post(f"/api/chat/new?personality={mira.id}")).json()["session_id"]
    assert made != hers and personalities.of_session(runner.store, made) == mira.id
    assert runner.current_thread(mira.id) == made


async def test_soul_name_and_picture_follow_the_pick(api, runner, odies_soul):
    mira, hers = await _mira_with_a_thread(runner)
    pick = f"?personality={mira.id}"
    got = (await api.get("/api/soul" + pick)).json()
    assert got["text"] == MIRAS_SOUL and got["custom"] is True
    assert got["path"].endswith(f"personalities/{mira.id}/SOUL.md")
    assert runner._prompt_of(_ctx(hers)).startswith(MIRAS_SOUL)
    assert (await api.put("/api/soul" + pick, json={"text": "You are Mira. Warm."})).json() == {"ok": True, "custom": True}
    assert personalities.load_soul(mira.id) == "You are Mira. Warm."
    assert runner._prompt_of(_ctx(hers)).startswith("You are Mira. Warm.")  # her next message talks the new way
    assert odies_soul.read_text() == "You are Odie, the everyday one. Sunny."  # Odie's SOUL.md is untouched
    await api.put("/api/soul" + pick, json={"text": ""})
    blank = (await api.get("/api/soul" + pick)).json()
    assert blank["custom"] is False and blank["text"].startswith("You are Mira,")
    # her name
    assert (await api.get("/api/persona" + pick)).json() == {"name": "Mira", "avatar_url": None}
    bad = await api.put("/api/persona" + pick, json={"name": "Odie"})
    assert bad.status_code == 422 and bad.json()["detail"] == "That is the everyday one's name."
    assert (await api.put("/api/persona" + pick, json={"name": "Mira B"})).json()["name"] == "Mira B"
    assert (await api.get("/api/persona")).json()["name"] == "Odie"
    # her picture
    up = await api.post("/api/persona/avatar" + pick, files={"file": ("m.jpg", _jpeg(), "image/jpeg")})
    first_picture = up.json()["avatar_url"]
    assert first_picture.startswith("/api/persona/avatar/")
    assert (await api.get(first_picture)).status_code == 200
    assert (await api.get("/api/persona")).json()["avatar_url"] is None  # Odie keeps the orb
    assert (await api.delete("/api/persona/avatar" + pick)).json()["avatar_url"] is None
    assert (await api.get(first_picture)).status_code == 404  # her old picture's file went with it


async def test_an_unknown_pick_is_404(api):
    for url in ("/api/threads?personality=nope", f"/api/history?date={D}&personality=nope",
                "/api/persona?personality=nope", "/api/soul?personality=nope", "/api/approvals?personality=nope"):
        assert (await api.get(url)).status_code == 404, url


async def test_cards_are_listed_and_answered_only_with_their_own_pick(api, runner):
    mira, hers = await _mira_with_a_thread(runner)
    pick = f"?personality={mira.id}"
    her_card = _card(runner.store, hers, "Run ls")
    odies_card = _card(runner.store, f"chat-{D}", "Run pwd")
    assert [a["id"] for a in (await api.get("/api/approvals")).json()] == [odies_card]
    assert [a["id"] for a in (await api.get("/api/approvals" + pick)).json()] == [her_card]
    assert (await api.get(f"/api/approvals/{her_card}")).status_code == 404
    assert (await api.get(f"/api/approvals/{her_card}" + pick)).status_code == 200
    assert (await api.get(f"/api/approvals/{odies_card}" + pick)).status_code == 404
    assert (await api.post(f"/api/approvals/{her_card}/decide", json={"approve": False})).status_code == 404
    assert runner.store.get_approval(her_card)["status"] == "pending"  # nobody answered it from the everyday side


async def test_think_harder_stop_and_context_follow_the_pick(api, runner, monkeypatch):
    mira = personalities.create(runner.store, "Mira")
    pick = f"?personality={mira.id}"
    assert (await api.get("/api/chat/thinking" + pick)).json() == {"session_id": None, "on": False}  # no thread yet
    assert (await api.post("/api/chat/stop" + pick, json={})).json() == {"ok": True, "session_id": None}
    hers = await runner.session_for(mira.id, D)
    assert (await api.get("/api/chat/thinking" + pick)).json() == {"session_id": hers, "on": False}
    assert (await api.put("/api/chat/thinking" + pick, json={"on": True})).json() == {"session_id": hers, "on": True}
    assert (await api.post("/api/chat/stop" + pick, json={})).json() == {"ok": True, "session_id": hers}
    assert (await api.get(f"/api/chat/thinking?session_id={hers}")).status_code == 404  # hers, named with no pick
    asked = []

    async def fake_usage(date, personality=""):
        asked.append(personality)
        return {"used": 1, "limit": 2}

    monkeypatch.setattr(runner, "context_usage", fake_usage)
    assert (await api.get("/api/chat/context" + pick)).json() == {"used": 1, "limit": 2}
    assert asked == [mira.id]


async def test_context_usage_of_a_personality_is_its_current_threads(runner):
    mira, hers = await _mira_with_a_thread(runner)
    runner._history_limits[hers] = 1000
    assert await runner.context_usage(D, personality=mira.id) == {"used": 0, "limit": 1000}


def test_the_terminal_may_never_name_a_personality():
    from odie import devices
    assert devices.terminal_may("POST", "/api/chat", "")
    assert devices.terminal_may("GET", "/api/threads", "q=goa")
    assert not devices.terminal_may("GET", "/api/threads", "personality=abc")
    assert not devices.terminal_may("GET", "/api/threads", "q=goa&personality=abc")
    assert not devices.terminal_may("POST", "/api/chat", "personality=abc")
    assert not devices.terminal_may("GET", "/api/threads/chat-2026-11-17-2/history", "limit=5&personality=abc")
    assert not devices.terminal_may("POST", "/api/chat/new", "personality=")  # naming it at all, even empty


async def test_the_terminals_key_never_reaches_a_personality(runner, monkeypatch):
    import httpx

    from odie import devices
    from odie.app.main import create_app
    monkeypatch.setenv("ODIE_PAIRING", "on")
    monkeypatch.setenv("ODIE_SCHEDULER", "0")
    mira, hers = await _mira_with_a_thread(runner)
    await _say(runner, hers, "user", "The lighthouse plan", time.time())
    terminal = devices.add_terminal(runner.store)
    app = create_app(runner=runner, store=runner.store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c, app.router.lifespan_context(app):
        c.cookies.set(devices.COOKIE, terminal)
        assert (await c.get("/api/threads")).json()["threads"] == []  # hers is not listed
        assert (await c.get(f"/api/threads?personality={mira.id}")).status_code == 403
        assert (await c.get(f"/api/threads/{hers}/history")).status_code == 404
        assert (await c.get(f"/api/threads/{hers}/history?personality={mira.id}")).status_code == 403
        assert (await c.post(f"/api/chat?personality={mira.id}", json={"text": "hi"})).status_code == 403
        assert (await c.post("/api/chat", json={"text": "hi", "session_id": hers})).status_code == 404
        assert (await c.get("/api/personalities")).status_code == 403


# ── what the server sends on its own: live updates, cards, pushes ──

def test_event_for_stream():
    event_for = personalities.event_for_stream
    everyday = {"type": "message", "text": "hi", "session_id": "chat-2026-11-17"}
    hers = {"type": "message", "text": "the lighthouse plan", "session_id": "chat-2026-11-17-2"}
    card = {"type": "approval", "id": 7, "status": "pending", "summary": "Run ls", "session_id": "chat-2026-11-17-2"}
    decided = {**card, "status": "approved"}
    answered = {"type": "answered", "session_id": "chat-2026-11-17-2"}
    thinking = {"type": "thinking", "session_id": "chat-2026-11-17-2", "on": True}
    for pick in (None, "", "mira", "coach"):  # an everyday event reaches every stream, as it is
        assert event_for(everyday, "", pick) == everyday
    for event in (hers, card, decided, answered, thinking):  # hers never reaches a stream that named nobody
        assert event_for(event, "mira", None) is None
    assert event_for(hers, "mira", "mira") == {**hers, "personality": "mira"}  # her own stream: the event, marked hers
    assert event_for(card, "mira", "mira") == {**card, "personality": "mira"}
    for pick in ("", "coach"):  # another pick hears only that something of hers waits: no words, no summary
        assert event_for(hers, "mira", pick) == {"type": "elsewhere", "personality": "mira", "what": "reply"}
        assert event_for(answered, "mira", pick) == {"type": "elsewhere", "personality": "mira", "what": "reply"}
        assert event_for(card, "mira", pick) == {"type": "elsewhere", "personality": "mira", "what": "card"}
        assert event_for(decided, "mira", pick) is None
        assert event_for(thinking, "mira", pick) is None


async def test_a_stream_that_named_nobody_gets_only_everyday_events(runner):
    from odie.app import routes
    mira, hers = await _mira_with_a_thread(runner)

    def request(query: dict) -> SimpleNamespace:
        return SimpleNamespace(query_params=query, app=SimpleNamespace(state=SimpleNamespace(store=runner.store)))

    assert routes._stream_pick(request({})) is None  # the Mac app, the terminal, an older web app
    assert routes._stream_pick(request({"personality": ""})) == ""  # a web app that knows of personalities, on Odie
    assert routes._stream_pick(request({"personality": mira.id})) == mira.id
    assert routes._stream_pick(request({"personality": "gone"})) == ""  # one that was deleted: it hears as Odie's does
    her_event = {"type": "message", "text": "the lighthouse plan", "session_id": hers}
    everyday = {"type": "message", "text": "hi", "session_id": f"chat-{D}"}
    no_thread = {"type": "task", "id": 3}
    assert personalities.stream_view(runner.store, her_event, None) is None
    assert personalities.stream_view(runner.store, everyday, None) == everyday
    assert personalities.stream_view(runner.store, no_thread, None) == no_thread
    assert personalities.stream_view(runner.store, her_event, mira.id) == {**her_event, "personality": mira.id}
    assert personalities.stream_view(runner.store, her_event, "") == {"type": "elsewhere", "personality": mira.id, "what": "reply"}


async def test_her_reminder_and_late_messages_carry_their_thread_on_the_live_stream(runner):
    mira, hers = await _mira_with_a_thread(runner)
    listening = runner.bus.queue()
    await runner.post_message("A late reply", session_id=hers, kind="reply")
    event = listening.get_nowait()
    assert event["session_id"] == hers
    assert personalities.stream_view(runner.store, event, None) is None  # never to the Mac app or the terminal


async def test_her_lapsed_card_is_said_in_her_thread(runner, monkeypatch):
    from datetime import UTC, datetime, timedelta

    from odie.app import main
    from odie.push import send as push
    mira, hers = await _mira_with_a_thread(runner)
    await _say(runner, f"chat-{D}", "user", "Everyday question", time.time())
    her_card = _card(runner.store, hers, "Delete the lighthouse notes")
    two_days_ago = (datetime.now(UTC) - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    runner.store.execute("update approvals set created_at=? where id=?", (two_days_ago, her_card))
    pushed = []
    monkeypatch.setattr(push, "send_to_all", lambda store, title, body, url="/", tag=None: pushed.append((title, body)) or 1)
    await main.expire_approvals(runner.store, runner)
    assert runner.store.get_approval(her_card)["status"] == "expired"
    her_lines = _odie_said(await runner.session_history(hers))
    assert len(her_lines) == 1 and "Delete the lighthouse notes" in her_lines[0]  # said where it was asked
    assert _odie_said(await runner.history(D)) == []  # and not in the everyday chat
    assert pushed == [("Mira: a request lapsed", "Open Odie to see it.")]  # no summary on the lock screen


async def test_her_card_goes_out_with_its_thread_and_a_quiet_push(runner, monkeypatch):
    from google.genai import types

    from odie.app import runner as runner_module
    mira, hers = await _mira_with_a_thread(runner)
    pushed = []
    monkeypatch.setattr(runner_module, "send_to_all", lambda store, title, body, url="/", tag=None: pushed.append((title, body)) or 1)
    call = types.FunctionCall(id="req-1", name=runner_module.CONFIRM, args={
        "originalFunctionCall": {"id": "c1", "name": "run_shell", "args": {"command": "rm lighthouse.txt"}},
        "toolConfirmation": {"hint": "Run rm lighthouse.txt"}})
    event = SimpleNamespace(partial=False, invocation_id="inv-1", content=types.Content(role="model", parts=[types.Part(function_call=call)]))
    cards = runner._approvals_in(event, hers)
    assert len(cards) == 1 and cards[0]["session_id"] == hers  # the live stream can tell whose card it is
    assert pushed == [("Mira needs you", "Open Odie to answer.")]
    everyday_cards = runner._approvals_in(SimpleNamespace(partial=False, invocation_id="inv-2", content=event.content), f"chat-{D}")
    assert everyday_cards[0]["session_id"] == f"chat-{D}"
    assert pushed[1][0] == "Odie needs your tap"  # an everyday card: as before


async def test_her_reply_while_away_is_a_quiet_push_and_a_wordless_notice(api, runner, monkeypatch):
    from odie.push import send as push
    mira, hers = await _mira_with_a_thread(runner)
    pushed = []
    monkeypatch.setattr(push, "send_to_all", lambda store, title, body, url="/", tag=None: pushed.append((title, body)) or 1)
    from odie.app import routes
    listening = runner.bus.queue()
    routes.say_answered_while_away(runner.store, runner.bus, hers, "The lighthouse plan is ready.")
    routes.say_answered_while_away(runner.store, runner.bus, f"chat-{D}", "It is 9:31.")
    assert pushed == [("Mira replied", "Open Odie to read it."), ("Odie answered", "It is 9:31.")]
    events = []
    while not listening.empty():
        events.append(listening.get_nowait())
    assert events == [{"type": "answered", "session_id": hers}]  # the dot for her; nothing new for an everyday reply


async def test_a_made_thing_in_her_thread_is_a_quiet_push(runner, monkeypatch):
    from odie.making import jobs
    mira, hers = await _mira_with_a_thread(runner)
    pushed = []
    monkeypatch.setattr(jobs, "send_to_all", lambda store, title, body, url="/", tag=None: pushed.append((title, body)) or 1)
    jobs.hooks.update(runner=runner, store=runner.store)
    await jobs.tell("video-lighthouse", hers, "Your video about the lighthouse is ready.")
    await jobs.tell("video-kettles", f"chat-{D}", "Your video about kettles is ready.")
    assert pushed == [("Mira replied", "Open Odie to read it."), ("Odie", "Your video about kettles is ready.")]
    assert _odie_said(await runner.session_history(hers)) == ["Your video about the lighthouse is ready."]


# ── deleting a personality ──

async def _mira_with_everything(runner):
    """Mira with one thread and something of hers in every place Odie keeps things for a thread."""
    from odie import media, thinking
    from odie.app.images import prepare_image, uploads_dir
    from odie.recall.fill import recall_index
    from odie.signin import guard
    store = runner.store
    mira, hers = await _mira_with_a_thread(runner)
    await _say(runner, hers, "user", "The lighthouse plan", time.time())
    picture = persona.store_picture(_jpeg())
    personalities.set_avatar(store, mira.id, picture)
    runner.memory_of(mira.id).update("The lighthouse plan", "Kept between us.", topic="Private")
    card = _card(store, hers, "Delete the lighthouse notes")
    store.audit("user", "message", result_summary="The lighthouse plan", session_id=hers)
    store.save_block_state(hers, "reply-1", "0", True)
    _task_tools(runner)["task_add"]("Call the clinic", "reminder", "2026-11-20T10:00", tool_context=_ctx(hers))
    recall_index().add_exchanges([_exchange(hers, "you: the lighthouse plan\nOdie: kept between us")])
    thinking.put(store, hers, True)
    store.set_setting(guard.PRIVATE_KEY + hers, ["example.com"])
    made = media.save(b"a voice memo", "memo", "wav", "audio/wav", "A memo about the lighthouse")
    await runner.post_message("Here it is.", session_id=hers, media=[made])
    upload = prepare_image(_jpeg(), uploads_dir())
    await _say(runner, hers, "user", f"Look at this\n[image:{upload['id']}]", time.time())
    return mira, hers, {"card": card, "picture": picture, "made": made["id"], "upload": upload["id"]}


async def test_delete_erases_everything_odie_keeps_for_it(runner):
    from odie import media, thinking
    from odie.app.images import load_image
    from odie.recall.fill import recall_index
    from odie.signin import guard
    store = runner.store
    mira, hers, kept = await _mira_with_everything(runner)
    assert media.get(kept["made"]) is not None and load_image(kept["upload"]) is not None  # there before
    assert await personalities.delete(store, runner, mira.id) == {"threads": 1}
    assert personalities.get(store, mira.id) is None and personalities.list_all(store) == []
    assert hers not in threads.session_ids_on(D)  # the thread's messages are gone from the session store
    for table in ("approvals", "audit_log", "block_state"):
        assert store.query(f"select 1 from {table} where session_id=?", (hers,)) == [], table
    mark = store.one("select title, pinned_at from threads where session_id=?", (hers,))
    assert mark["title"] is None and mark["pinned_at"] is None  # only an empty mark that the thread was erased
    assert personalities.is_erased(store, hers)
    assert threads.next_free_id(store, D) != hers  # its number is never given out again
    assert threads.list_threads(store) == []  # and it is in nobody's list
    assert store.query("select 1 from tasks where personality=?", (mira.id,)) == []
    assert recall_index().keyword("lighthouse") == []
    assert not personalities.folder(mira.id).exists()  # her SOUL and her memories
    assert not (config.settings.data_dir / f"memory-{mira.id}.lock").exists()
    assert persona.avatar_path(kept["picture"]) is None
    assert media.get(kept["made"]) is None and load_image(kept["upload"]) is None
    assert hers not in thinking._load(store)["chats"]
    assert store.get_setting(guard.PRIVATE_KEY + hers) is None
    assert store.get_setting(f"current:{mira.id}") is None
    assert hers not in runner._prompts and mira.id not in runner._turns


async def test_delete_leaves_odie_and_the_others_alone(runner, odies_soul):
    from odie.recall.fill import recall_index
    store = runner.store
    mira, hers, _ = await _mira_with_everything(runner)
    # everyday Odie's things
    odies = f"chat-{D}"
    await _say(runner, odies, "user", "Everyday question", time.time())
    runner.memory.update("Rent day", "Paid on the first.", topic="Finance")
    odies_picture = persona.save_avatar(store, _jpeg())["avatar"]
    odies_card = _card(store, odies, "Run pwd")
    store.save_block_state(odies, "reply-1", "0", True)
    _task_tools(runner)["task_add"]("Buy milk", "todo", tool_context=_ctx(odies))
    recall_index().add_exchanges([_exchange(odies, "you: which kettle\nOdie: the steel kettle", hour=11)])
    # another personality's things
    coach = personalities.create(store, "Coach")
    personalities.save_soul(coach.id, "You are Coach. Direct.")
    coachs = await runner.session_for(coach.id, D)
    await _say(runner, coachs, "user", "The training plan", time.time())
    runner.memory_of(coach.id).update("Training plan", "Three runs a week.", topic="Health")

    await personalities.delete(store, runner, mira.id)

    assert _said(await runner.history(D)) == ["Everyday question"]
    assert runner.memory.load().find("Rent day") is not None
    assert odies_soul.read_text() == "You are Odie, the everyday one. Sunny."
    assert persona.avatar_path(odies_picture) is not None and persona.get(store)["avatar"] == odies_picture
    assert store.get_approval(odies_card)["status"] == "pending"
    assert store.block_state(odies, "reply-1") != {}
    assert [r["title"] for r in store.open_tasks()] == ["Buy milk"]
    assert len(recall_index().keyword("kettle")) == 1
    assert personalities.get(store, coach.id) is not None and personalities.load_soul(coach.id) == "You are Coach. Direct."
    assert _said(await runner.history(D, personality=coach.id)) == ["The training plan"]
    assert runner.memory_of(coach.id).load().find("Training plan") is not None


async def test_nothing_comes_back_after_delete(api, runner):
    from odie.app.runner import SessionGone
    mira, hers, kept = await _mira_with_everything(runner)
    await _say(runner, f"chat-{D}", "user", "Everyday question", time.time())
    gone = await api.delete(f"/api/personalities/{mira.id}")
    assert gone.status_code == 200 and gone.json() == {"ok": True, "threads": 1}
    assert (await api.get(f"/api/approvals/{kept['card']}")).status_code == 404  # her waiting card went with her
    with pytest.raises(SessionGone):
        await runner.post_message("a late reply", session_id=hers)  # a turn still finishing can't bring the thread back
    assert hers not in threads.session_ids_on(D)
    assert _odie_said(await runner.history(D)) == []  # and its words didn't land in the everyday chat
    assert (await api.delete(f"/api/personalities/{mira.id}")).status_code == 404
    assert (await api.get("/api/personalities")).json() == {"personalities": [], "everyday_waiting": 0}
    assert (await api.get(f"/api/threads?personality={mira.id}")).status_code == 404


async def test_deleting_stops_a_review_of_her_turns(runner):
    import asyncio
    mira, hers = await _mira_with_a_thread(runner)
    started = asyncio.Event()

    async def slow_review():
        started.set()
        await asyncio.sleep(30)  # a review still waiting for the model

    runner._review_task = asyncio.create_task(slow_review())
    runner._review_for = mira.id
    await started.wait()
    await personalities.delete(runner.store, runner, mira.id)
    assert runner._review_task.cancelled()  # it can no longer write her memory file back
    assert not personalities.folder(mira.id).exists()


# ── what the final review found ──

async def test_the_switcher_is_told_how_many_everyday_cards_wait(api, runner):
    mira, hers = await _mira_with_a_thread(runner)
    _card(runner.store, f"chat-{D}", "Send the invoice")
    _card(runner.store, hers, "Run ls")
    got = (await api.get("/api/personalities")).json()
    assert got["everyday_waiting"] == 1  # so a chat with Mira can show that Odie needs a tap, even after a reload
    assert got["personalities"][0]["waiting"] == 1
    everyday = (await api.get("/api/approvals?personality=")).json()  # what Today and the Ask bar ask for, whoever is picked
    assert [a["summary"] for a in everyday] == ["Send the invoice"]


async def test_whose_thread(runner):
    mira, hers = await _mira_with_a_thread(runner)
    assert personalities.whose_thread(runner.store, f"chat-{D}") == (ODIE, None)
    assert personalities.whose_thread(runner.store, None) == (ODIE, None)
    assert personalities.whose_thread(runner.store, hers) == (mira.id, personalities.get(runner.store, mira.id))
    runner.store.execute("delete from personalities where id=?", (mira.id,))  # being deleted: the record goes first
    assert personalities.whose_thread(runner.store, hers) == (mira.id, None)


async def test_while_a_personality_is_being_deleted_nothing_of_its_goes_out_under_odies_name(runner, monkeypatch):
    from datetime import UTC, datetime, timedelta

    from google.genai import types

    from odie.app import main, routes
    from odie.app import runner as runner_module
    from odie.push import send as push
    mira, hers = await _mira_with_a_thread(runner)
    lapsing = _card(runner.store, hers, "Delete the lighthouse notes")
    two_days_ago = (datetime.now(UTC) - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    runner.store.execute("update approvals set created_at=? where id=?", (two_days_ago, lapsing))
    pushed = []
    monkeypatch.setattr(push, "send_to_all", lambda store, title, body, url="/", tag=None: pushed.append((title, body)) or 1)
    monkeypatch.setattr(runner_module, "send_to_all", lambda store, title, body, url="/", tag=None: pushed.append((title, body)) or 1)
    # delete() removes the record first; for a moment her threads still stand, with a turn finishing in one
    runner.store.execute("delete from personalities where id=?", (mira.id,))
    routes.say_answered_while_away(runner.store, runner.bus, hers, "The lighthouse plan is ready.")
    call = types.FunctionCall(id="req-1", name=runner_module.CONFIRM, args={
        "originalFunctionCall": {"id": "c1", "name": "run_shell", "args": {"command": "rm lighthouse.txt"}},
        "toolConfirmation": {"hint": "Run rm lighthouse.txt"}})
    event = SimpleNamespace(partial=False, invocation_id="inv-1", content=types.Content(role="model", parts=[types.Part(function_call=call)]))
    runner._approvals_in(event, hers)
    await main.expire_approvals(runner.store, runner)  # her lapsed card: no line anywhere, no push, and no error
    assert pushed == []  # not "Odie answered: The lighthouse plan…", not "Odie needs your tap"
    assert _odie_said(await runner.history(D)) == []


async def test_odies_new_chat_and_a_personalitys_first_thread_never_take_the_same_id(runner):
    import asyncio
    mira = personalities.create(runner.store, "Mira")
    await _say(runner, f"chat-{D}", "user", "Morning", time.time())
    odies, hers = await asyncio.gather(runner.new_chat(D), runner.session_for(mira.id, D))  # two devices, the same moment
    assert odies != hers
    assert personalities.of_session(runner.store, odies) == ODIE
    assert personalities.of_session(runner.store, hers) == mira.id
    assert runner.current_session_id(D) == odies


async def test_delete_removes_the_files_its_chats_left_in_the_workspace(runner):
    import json

    from odie.agent.tools.files import hand_over, workspace
    mira, hers = await _mira_with_a_thread(runner)
    odies = f"chat-{D}"
    her_file = workspace() / "lighthouse notes.md"
    her_file.write_text("The lighthouse plan")
    await runner.post_message("Here it is.", session_id=hers, media=[hand_over(her_file)["media"]])
    rewritten = workspace() / "plan.md"  # made in her chat, then written over with something else
    rewritten.write_text("Her first draft")
    await runner.post_message("And this.", session_id=hers, media=[hand_over(rewritten)["media"]])
    rewritten.write_text("An everyday rewrite")
    odies_file = workspace() / "kettles.md"
    odies_file.write_text("Steel kettles")
    await runner.post_message("Yours.", session_id=odies, media=[hand_over(odies_file)["media"]])
    her_job = workspace() / "podcasts" / "lighthouse"
    odies_job = workspace() / "podcasts" / "kettles"
    for folder, sid in ((her_job, hers), (odies_job, odies)):
        folder.mkdir(parents=True)
        (folder / "job.json").write_text(json.dumps({"status": "done", "session_id": sid, "title": folder.name, "slug": folder.name}))
        (folder / "brief.md").write_text("what it was asked to make")

    await personalities.delete(runner.store, runner, mira.id)

    assert not her_file.exists() and not her_job.exists()
    assert rewritten.read_text() == "An everyday rewrite"  # no longer the file her chat made: left alone
    assert odies_file.exists() and (odies_job / "brief.md").exists()


async def test_an_interrupted_job_of_an_erased_thread_is_removed_not_told(runner):
    import json

    from odie.agent.tools.files import workspace
    from odie.making import jobs
    mira, hers = await _mira_with_a_thread(runner)
    await personalities.delete(runner.store, runner, mira.id)
    jobs.hooks.update(runner=runner, store=runner.store)
    jobs.load_kinds()
    kind_name, kind = next(iter(jobs.KINDS.items()))
    folder = workspace() / kind.folder / "lighthouse"  # a job that was still running when she was deleted wrote it back
    folder.mkdir(parents=True)
    (folder / "job.json").write_text(json.dumps({"status": "making", "session_id": hers, "title": "The lighthouse", "slug": "lighthouse"}))
    assert await jobs.tell_if_interrupted(folder / "job.json", kind_name, kind) is False
    assert not folder.exists()  # so the next start has nothing to trip over, and nothing of hers is left

