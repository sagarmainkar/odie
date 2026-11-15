"""The index worker keeps recall filled: past days' chats and the memory file go in by words every pass, and by meaning
on the embedding schedule. Every path is a temp copy (never the real ~/.odie)."""
import json
import shutil
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from odie.store.db import Store
from tests.test_vault_embed import FakeEmbedder

SAMPLE = Path(__file__).parent / "fixtures" / "sample-vault"


@pytest.fixture
def home(isolated_settings, tmp_path):
    """The settings with every path in tmp_path, checked before anything is read or written."""
    assert isolated_settings.data_dir == tmp_path
    assert isolated_settings.sessions_db_path.parent == tmp_path
    assert isolated_settings.memory_file.parent == tmp_path
    return isolated_settings


@pytest.fixture
def store(home, tmp_path):
    s = Store(tmp_path / "assistant.db")
    s.init_schema()
    return s


def local(home, day: int, hour: int) -> datetime:
    return datetime(2026, 11, day, hour, tzinfo=ZoneInfo(home.timezone))


def write_chats(home, chats: list[tuple[str, float, str, str]]) -> None:
    """chats: (session_id, timestamp, author, text), into a temp sessions.db the way ADK keeps them."""
    db = sqlite3.connect(home.sessions_db_path)
    db.execute("create table if not exists events(session_id text, app_name text, user_id text, timestamp real, "
               "event_data text)")
    for sid, ts, author, text in chats:
        data = json.dumps({"author": author, "content": {"parts": [{"text": text}]}})
        db.execute("insert into events values (?,?,?,?,?)", (sid, home.app_name, home.user_id, ts, data))
    db.commit()
    db.close()


def write_memories(home) -> None:
    home.memory_file.write_text("# odie — long-term memory\n\n## Home\n\n### Rent day (2026-10-01)\n\n"
                                "The studio.local rent is paid on the first.\n", encoding="utf-8")


def test_start_of_today_is_local_midnight(home):
    from odie.recall.fill import start_of_today
    assert start_of_today(local(home, 4, 15)) == local(home, 4, 0).timestamp()


def test_fill_words_skips_today(home):
    from odie.recall.fill import fill_words, recall_index
    ix = recall_index()
    assert ix.db_path == home.data_dir / "odie-index.db"
    write_chats(home, [
        ("chat-book", local(home, 3, 10).timestamp(), "user", "What happens to the lighthouse keeper?"),
        ("chat-book", local(home, 3, 10).timestamp() + 5, "odie", "Asha finds the keeper's log."),
        ("chat-book", local(home, 4, 10).timestamp(), "user", "And the harbour?"),
        ("chat-book", local(home, 4, 10).timestamp() + 5, "odie", "Dev rows across at dawn."),
    ])
    write_memories(home)

    assert fill_words(ix, local(home, 4, 15)) == {"chats": 1, "memories": 1}
    assert [h.day for h in ix.keyword("lighthouse")] == ["2026-11-03"]
    assert ix.keyword("harbour") == []  # today's exchange waits for tomorrow
    assert [h.title for h in ix.keyword("rent")] == ["Rent day"]

    # The next morning the same long-lived chat's 4 Nov exchange goes in, and nothing is added twice.
    assert fill_words(ix, local(home, 5, 8)) == {"chats": 1, "memories": 0}
    assert [h.day for h in ix.keyword("harbour")] == ["2026-11-04"]
    assert len(ix.keyword("lighthouse")) == 1


def test_fill_words_reads_the_chats_once_a_day(home, monkeypatch):
    from odie.recall import fill
    ix = fill.recall_index()
    write_chats(home, [("chat-1", local(home, 3, 9).timestamp(), "user", "Pack the blue raincoat")])
    reads = []
    real = fill.chat_lines

    def counting(*args, **kwargs):
        reads.append(kwargs)
        return real(*args, **kwargs)
    monkeypatch.setattr(fill, "chat_lines", counting)

    assert fill.fill_words(ix, local(home, 4, 9))["chats"] == 1
    assert fill.fill_words(ix, local(home, 4, 9) + timedelta(minutes=5))["chats"] == 0
    assert len(reads) == 1  # the second pass the same day doesn't open sessions.db
    assert reads[0]["since"] == 0.0 and reads[0]["until"] == local(home, 4, 0).timestamp()
    fill.fill_words(ix, local(home, 5, 9))
    assert len(reads) == 2 and reads[1]["since"] == local(home, 4, 0).timestamp()


async def test_fill_words_runs_with_no_vault(store, home, monkeypatch):
    from odie.recall.fill import recall_index
    from odie.recall.index import RecallIndex
    from odie.vault import settings
    from odie.vault.worker import VaultWorker
    yesterday = datetime.now(ZoneInfo(home.timezone)) - timedelta(days=1)
    chat_title = f"chat {yesterday.date().isoformat()}"
    write_chats(home, [("chat-1", yesterday.timestamp(), "user", "Remind me about the invoice")])
    write_memories(home)
    assert settings.get(store)["dir"] is None  # no notes folder, and photos are off by default
    monkeypatch.setattr(settings, "embedder_and_reason", lambda s: (None, ""))
    w = VaultWorker(store)
    await w.run_once()
    assert settings.index_for(store) is None  # recall's rows alone aren't a notes or photos index
    ix = recall_index()
    assert [h.title for h in ix.keyword("invoice")] == [chat_title]
    assert [h.title for h in ix.keyword("rent")] == ["Rent day"]
    assert w.progress()["error"] == "" and w.progress()["running"] is False

    # With an embedder, recall is read by meaning on the same schedule, through the no-vault path.
    steps = []
    real_adopt, real_embed = RecallIndex.adopt_model, RecallIndex.embed_pending

    def adopt(self, embedder):
        steps.append(("adopt", embedder.name))
        return real_adopt(self, embedder)

    async def embed(self, embedder, batch=32, progress=None):
        steps.append(("embed", embedder.name))
        return await real_embed(self, embedder, batch=batch, progress=progress)
    monkeypatch.setattr(RecallIndex, "adopt_model", adopt)
    monkeypatch.setattr(RecallIndex, "embed_pending", embed)
    embedder = FakeEmbedder()
    monkeypatch.setattr(settings, "embedder_and_reason", lambda s: (embedder, ""))
    await w.run_once()
    assert steps == [("adopt", "fake:words"), ("embed", "fake:words")]
    assert {d["title"] for d in embedder.documents} == {chat_title, "Rent day"}
    hits = await ix.search("invoice", embedder=embedder)
    assert hits[0].title == chat_title and w.last_embedded()
    await w.run_once()  # a keyword pass a moment later: not due, nothing embedded again
    assert len(embedder.documents) == 2 and len(steps) == 2

    # Another model: recall drops its old vectors and reads everything again with the new one.
    other = FakeEmbedder(name="fake:other")
    monkeypatch.setattr(settings, "embedder_and_reason", lambda s: (other, ""))
    w.kick()
    await w.run_once()
    assert steps[2:] == [("adopt", "fake:other"), ("embed", "fake:other")]
    assert {d["title"] for d in other.documents} == {chat_title, "Rent day"}
    assert settings.index_for(store) is None


async def test_a_home_with_only_recall_still_has_no_notes_index(store, home):
    from odie.recall.fill import fill_words, recall_index
    from odie.vault import settings
    from odie.vault.tools import make_vault_tools
    write_memories(home)
    fill_words(recall_index(), datetime.now(ZoneInfo(home.timezone)))
    assert (home.data_dir / "odie-index.db").is_file()
    assert settings.index_for(store) is None
    search = next(t for t in make_vault_tools(store) if t.name == "search_everything").func
    assert await search(query="rent") == "Neither notes nor photos are set up."


async def test_the_meaning_pass_embeds_recall_after_notes(store, home, tmp_path, monkeypatch):
    from odie.recall.fill import recall_index
    from odie.vault import settings
    from odie.vault.worker import VaultWorker
    vault = tmp_path / "vault"
    shutil.copytree(SAMPLE, vault)
    settings.put(store, dir=str(vault))
    yesterday = datetime.now(ZoneInfo(home.timezone)) - timedelta(days=1)
    write_chats(home, [("chat-1", yesterday.timestamp(), "user", "Remind me about the invoice")])
    embedder = FakeEmbedder()
    monkeypatch.setattr(settings, "embedder_and_reason", lambda s: (embedder, ""))
    w = VaultWorker(store)
    phases = []
    real_count = w._count

    def counting(phase):
        phases.append(phase)
        return real_count(phase)
    monkeypatch.setattr(w, "_count", counting)
    await w.run_once()

    chat_title = f"chat {yesterday.date().isoformat()}"
    titles = [d["title"] for d in embedder.documents]
    assert titles[-1] == chat_title and chat_title not in titles[:-1]  # the notes' batch first, recall last
    assert len(titles) > 1
    assert phases.index("meaning") < phases.index("recall")
    ix = settings.index_for(store)
    assert ix.status()["vectors"] == ix.status()["chunks"]  # the notes are all embedded, and kept
    assert (await recall_index().search("invoice", embedder=embedder))[0].title == chat_title
    assert w.progress()["error"] == ""
