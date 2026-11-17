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
