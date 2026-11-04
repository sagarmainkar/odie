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


# ── recall by meaning ──


class FakeEmbedder:
    """Gives a text a 3-d one-hot vector by its topic word: money, travel, or (anything else) the third. Stands for a
    real model, in which "bill" and "invoice" land close together without sharing a word."""

    def __init__(self, name: str = "fake", fail: bool = False) -> None:
        self.name = name
        self.fail = fail
        self.calls = 0

    async def embed(self, texts, kind: str = "document") -> list[list[float]]:
        self.calls += 1
        if self.fail:
            raise RuntimeError("embedder is down")
        return [self._vector(t["text"] if isinstance(t, dict) else t) for t in texts]

    def _vector(self, text: str) -> list[float]:
        words = text.lower()
        if any(w in words for w in ("invoice", "bill", "rent")):
            return [1.0, 0.0, 0.0]
        if any(w in words for w in ("flight", "train", "trip")):
            return [0.0, 1.0, 0.0]
        return [0.0, 0.0, 1.0]


def meta_value(db: Path, key: str) -> str | None:
    c = sqlite3.connect(db)
    try:
        row = c.execute("select value from meta where key=?", (key,)).fetchone()
    finally:
        c.close()
    return row[0] if row else None


def fill(index: RecallIndex) -> None:
    index.add_exchanges([
        exchange("chat-1", 3, 9, "you: the invoice from the studio\nOdie: due on Friday"),
        exchange("chat-1", 3, 10, "you: book a flight to Pune\nOdie: noted"),
        exchange("chat-1", 4, 9, "you: what shall we cook\nOdie: dal"),
    ])
    index.sync_memories([Entry(topic="Home", title="Rent day", date="2026-10-01", body="rent is paid on the first")])


async def test_meaning_ranks_by_likeness(tmp_path):
    index, db = make_index(tmp_path)
    fill(index)
    embedder = FakeEmbedder()
    assert await index.embed_pending(embedder) == 4
    assert await index.embed_pending(embedder) == 0  # all have a vector now
    # "bill payment" shares no word with "invoice", yet the money passages come first.
    hits = await index.search("bill payment", k=2, embedder=embedder)
    assert {h.title for h in hits} == {"chat 2026-11-03", "Rent day"}
    assert all(h.score == 1.0 for h in hits)
    assert meta_value(db, "model") == "fake"
    assert meta_value(db, "embed_error") is None


async def test_meaning_respects_since_and_until(tmp_path):
    index, _ = make_index(tmp_path)
    fill(index)
    embedder = FakeEmbedder()
    await index.embed_pending(embedder)
    hits = await index.search("bill payment", k=8, embedder=embedder, since="2026-11-01")
    assert hits[0].title == "chat 2026-11-03"
    assert all(h.day >= "2026-11-01" for h in hits)
    hits = await index.search("bill payment", k=8, embedder=embedder, until="2026-10-31")
    assert [h.title for h in hits] == ["Rent day"]


async def test_without_an_embedder_words_are_used(tmp_path):
    index, _ = make_index(tmp_path)
    fill(index)
    assert await index.search("invoice", k=3) == index.keyword("invoice", k=3)
    assert [h.title for h in await index.search("invoice", k=3)] == ["chat 2026-11-03"]
    # Vectors exist, but no embedder is given: still words.
    await index.embed_pending(FakeEmbedder())
    assert [h.title for h in await index.search("invoice", k=3)] == ["chat 2026-11-03"]


async def test_another_models_vectors_are_left_alone(tmp_path):
    index, db = make_index(tmp_path)
    fill(index)
    c = sqlite3.connect(db)
    c.execute("insert into meta values ('model', 'other')")
    c.execute("insert into vectors values ('chunk', '1', x'00')")
    c.commit()
    c.close()
    embedder = FakeEmbedder()
    assert await index.embed_pending(embedder) == 0
    assert embedder.calls == 0
    assert meta_value(db, "model") == "other"
    assert count(db, "select count(*) from vectors") == 1  # the notes' vector is still there
    assert [h.title for h in await index.search("invoice", k=3, embedder=embedder)] == ["chat 2026-11-03"]


async def test_a_failing_embedder_is_recorded(tmp_path):
    index, db = make_index(tmp_path)
    fill(index)
    broken = FakeEmbedder(fail=True)
    assert await index.embed_pending(broken) == 0
    assert "embedder is down" in meta_value(db, "embed_error")
    assert [h.title for h in await index.search("invoice", k=3, embedder=broken)] == ["chat 2026-11-03"]
    # The next run, with the embedder back, tries again and clears the error.
    assert await index.embed_pending(FakeEmbedder()) == 4
    assert meta_value(db, "embed_error") is None


async def test_vectors_cleared_by_another_pass_are_embedded_again(tmp_path):
    index, db = make_index(tmp_path)
    fill(index)
    embedder = FakeEmbedder()
    await index.embed_pending(embedder)
    # The notes' pass cleared every vector (a model switch back to the same name), leaving model as it was.
    c = sqlite3.connect(db)
    c.execute("delete from vectors")
    c.commit()
    c.close()
    assert await index.search("bill payment", k=2, embedder=embedder) == index.keyword("bill payment", k=2)
    assert await index.embed_pending(embedder) == 4
    assert len(await index.search("bill payment", k=2, embedder=embedder)) == 2
