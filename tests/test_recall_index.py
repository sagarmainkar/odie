"""The recall index lives in a temp copy of odie-index.db (never the real one)."""
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from odie.memory.store import Entry, norm
from odie.recall.chats import Exchange
from odie.recall.index import RecallHit, RecallIndex
from odie.vault.index import VaultIndex


def at(day: int, hour: int = 10) -> float:
    return datetime(2026, 11, day, hour, tzinfo=UTC).timestamp()


def make_index(tmp_path: Path) -> tuple[RecallIndex, Path]:
    db = tmp_path / "odie-index.db"
    assert db.resolve().is_relative_to(tmp_path.resolve())
    return RecallIndex(db), db


def exchange(session: str, day: int, hour: int, text: str) -> Exchange:
    return Exchange(session_id=session, ts=at(day, hour), day=f"2026-11-{day:02d}", text=text)


def count(db: Path, sql: str) -> int:
    c = sqlite3.connect(db)
    try:
        return c.execute(sql).fetchone()[0]
    finally:
        c.close()


def test_exchanges_are_added_once(tmp_path):
    index, db = make_index(tmp_path)
    rows = [
        exchange("chat-1", 3, 9, "you: hello\nOdie: hi Asha"),
        exchange("chat-1", 3, 10, "you: the weather\nOdie: sunny"),
    ]
    assert index.add_exchanges(rows) == 2
    assert index.add_exchanges(rows) == 0
    assert count(db, "select count(*) from passages where kind='chat'") == 2
    assert count(db, "select count(*) from passages_fts") == 2


def test_last_chat_ts_lets_a_long_session_carry_on(tmp_path):
    index, _ = make_index(tmp_path)
    assert index.last_chat_ts("chat-book") == 0.0
    index.add_exchanges([
        exchange("chat-book", 3, 9, "you: chapter one\nOdie: noted"),
        exchange("chat-book", 3, 15, "you: chapter two\nOdie: noted"),
        exchange("chat-other", 3, 20, "you: unrelated\nOdie: ok"),
    ])
    assert index.last_chat_ts("chat-book") == at(3, 15)
    # The next pass reads from that time on: the same session's 4 Nov exchange is new and gets added.
    since = index.last_chat_ts("chat-book")
    later = exchange("chat-book", 4, 8, "you: chapter three\nOdie: noted")
    assert later.ts > since
    assert index.add_exchanges([later]) == 1
    assert index.last_chat_ts("chat-book") == at(4, 8)


def test_memories_follow_the_file(tmp_path):
    index, db = make_index(tmp_path)
    keep = Entry(topic="Work", title="Mac app price", date="2026-10-20", body="Charge ten dollars.")
    gone = Entry(topic="Work", title="Old plan", date="2026-10-21", body="Ship in spring.")
    assert index.sync_memories([keep, gone]) == 2
    c = sqlite3.connect(db)
    c.execute("insert into vectors values ('memory', ?, x'00')", (norm(keep.title),))
    c.execute("insert into vectors values ('memory', ?, x'00')", (norm(gone.title),))
    c.commit()
    c.close()

    changed = Entry(topic="Work", title="Mac app price", date="2026-10-20", body="Charge twelve dollars.")
    assert index.sync_memories([changed]) == 1  # one row replaced; the missing title is deleted
    c = sqlite3.connect(db)
    rows = c.execute("select ref, text from passages where kind='memory'").fetchall()
    vectors = c.execute("select ref from vectors where kind='memory'").fetchall()
    fts = c.execute("select count(*) from passages_fts").fetchone()[0]
    c.close()
    assert rows == [(norm("Mac app price"), "Charge twelve dollars.")]
    assert vectors == []  # the changed body dropped its vector, the removed title took its vector with it
    assert fts == 1
    assert index.sync_memories([changed]) == 0  # nothing changed: nothing touched


def test_keyword_finds_chats_and_memories(tmp_path):
    index, _ = make_index(tmp_path)
    index.add_exchanges([
        exchange("chat-1", 3, 9, "you: what about the mac app price\nOdie: ten dollars"),
        exchange("chat-2", 4, 9, "you: mac app price again\nOdie: still ten"),
        exchange("chat-2", 4, 11, "you: lunch ideas\nOdie: soup"),
    ])
    index.sync_memories([Entry(topic="Work", title="Pricing", date="2026-10-20", body="The mac app price is ten dollars.")])

    hits = index.keyword("mac app price")
    assert all(isinstance(h, RecallHit) for h in hits)
    assert {h.kind for h in hits} == {"chat", "memory"}
    chat_days = sorted(h.day for h in hits if h.kind == "chat")
    assert chat_days == ["2026-11-03", "2026-11-04"]
    memory = next(h for h in hits if h.kind == "memory")
    assert memory.day == "2026-10-20"
    assert memory.title == "Pricing"

    recent = index.keyword("mac app price", since="2026-11-04")
    assert [h.day for h in recent if h.kind == "chat"] == ["2026-11-04"]
    assert "2026-11-03" not in [h.day for h in recent]

    before = index.keyword("mac app price", until="2026-11-03")
    assert "2026-11-04" not in [h.day for h in before]
    assert index.keyword("") == []


def test_the_notes_tables_are_untouched(tmp_path):
    db = tmp_path / "odie-index.db"
    assert db.resolve().is_relative_to(tmp_path.resolve())
    vault = tmp_path / "vault"
    vault.mkdir()
    (vault / "a.md").write_text("# A\n\nPlans for the studio.\n")
    notes = VaultIndex(db, vault)
    notes.scan()
    before = count(db, "select count(*) from chunks")
    assert before > 0

    index = RecallIndex(db)
    index.add_exchanges([exchange("chat-1", 3, 9, "you: studio plans\nOdie: ok")])
    index.sync_memories([Entry(topic="Work", title="Studio", date="2026-10-20", body="Plans.")])
    VaultIndex(db, vault)  # opening it again beside the recall tables changes nothing

    assert count(db, "select count(*) from chunks") == before
    assert count(db, "select count(*) from chunks_fts") == before
