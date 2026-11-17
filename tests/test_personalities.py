"""Personalities: each has its own threads, memory, name, picture and instructions, and nothing of one reaches another
or everyday Odie. Most tests here try to cross one of those lines."""
import io
import re
import sqlite3
import time

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
