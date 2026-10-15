"""Replays copied in as chat threads (odie/replay_threads.py): a throwaway replay home built with ADK's real session
service is imported into a throwaway target home, then opened through the app's own thread list and history code.
The target is always under tmp_path, never a real ~/.odie."""
import importlib
import json
import socket
import sqlite3
import time
from pathlib import Path

import pytest
from google.adk.events import Event
from google.adk.sessions.sqlite_session_service import SqliteSessionService
from google.genai import types

from odie import replay_threads as rt

MEDIA_ID = "73ac143af5d147a7"   # the podcast the replay made
OTHER_MEDIA = "0123456789abcdef"  # a file in the replay's media folder that no event names
TABLE_REPLY = "Here's how they compare:\n\n```odie-blocks\n[{\"type\": \"table\", \"rows\": [[\"Pixel\", \"8/10\"]]}]\n```"
PODCAST_REPLY = "Here's your podcast. 🎧"
TITLE = "Replay · Opus 5.5 · think longer"


def free_port() -> int:
    """A port nothing listens on (asked of the OS, then let go)."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def add_events(db: Path, app_name: str, user_id: str, session_id: str, events: list[Event]) -> None:
    """Saves the events in a session, through ADK's own session service (as the runner does)."""
    service = SqliteSessionService(db_path=str(db))
    session = await service.create_session(app_name=app_name, user_id=user_id, session_id=session_id)
    for event in events:
        await service.append_event(session=session, event=event)


def said(author: str, ts: float, *parts: types.Part, inv: str = "e-1") -> Event:
    role = "user" if author == "user" else "model"
    return Event(author=author, invocation_id=inv, timestamp=ts, content=types.Content(role=role, parts=list(parts)))


def text(t: str) -> types.Part:
    return types.Part(text=t)


def call(name: str, args: dict) -> types.Part:
    return types.Part(function_call=types.FunctionCall(id=f"call-{name}", name=name, args=args))


def result(name: str, response: dict) -> types.Part:
    return types.Part(function_response=types.FunctionResponse(id=f"call-{name}", name=name, response=response))


@pytest.fixture
async def replay_home(tmp_path):
    """A throwaway home as scripts/chat_replay.sh leaves it: a two-turn replay (a search and a table, then a podcast),
    the podcast's file, a file nothing names, and the task and memory the replay made (which must stay behind)."""
    home = tmp_path / "temp" / "odie-chat-replay-ab12cd34" / "home"
    data = home / "data"
    (data / "media").mkdir(parents=True)
    t = time.time() - 3600
    await add_events(data / "sessions.db", "odie", "user", "replay-2026-10-11", [
        said("user", t, text("Compare Pixel 10a and Galaxy A76\n\n[context: now 19:02 Sun 11 Oct]"), inv="e-1"),
        said("odie", t + 1, call("web_search", {"query": "Pixel 10a camera"}), inv="e-1"),
        said("odie", t + 2, result("web_search", {"result": "Pixel 10a: great camera"}), inv="e-1"),
        said("odie", t + 3, text(TABLE_REPLY), inv="e-1"),
        said("user", t + 10, text("can you create a podcast from our conversation\n\n[context: now 19:03 Sun 11 Oct]"), inv="e-2"),
        said("odie", t + 11, call("speak", {"style": "podcast", "script": "Asha: Hi!\nRohan: Hello."}), inv="e-2"),
        said("odie", t + 12, result("speak", {"media": {"id": MEDIA_ID, "kind": "podcast", "title": "Our chat"}}), inv="e-2"),
        said("odie", t + 13, text(PODCAST_REPLY), inv="e-2"),
    ])
    for mid in (MEDIA_ID, OTHER_MEDIA):
        (data / "media" / f"{mid}.wav").write_bytes(b"RIFF fake wav")
        (data / "media" / f"{mid}.json").write_text(json.dumps({"id": mid, "kind": "podcast", "title": "Our chat",
                                                               "mime": "audio/wav", "size": 13, "ext": "wav"}))
    from odie.store.db import Store
    store = Store(data / "assistant.db")
    store.init_schema()
    store.add_task("renew car insurance", "todo")
    store.close()
    (home / "memories.md").write_text("- Prefers window seats\n")
    return home


@pytest.fixture
def evals_dir(tmp_path, monkeypatch):
    """The saved runs: the replay's own (its replies), a different model's, and a live chat (never a replay)."""
    d = tmp_path / "evals"
    d.mkdir()
    runs = {
        "2026-10-11-anthropic-claude-opus-5-5-think-longer": {"source": "replay", "provider": "anthropic", "model": "claude-opus-5-5",
                                                             "settings": {"thinking": True}, "replies": [TABLE_REPLY, PODCAST_REPLY]},
        "2026-10-11-anthropic-claude-sonnet-5-5": {"source": "replay", "provider": "anthropic", "model": "claude-sonnet-5-5",
                                                  "settings": {"thinking": False}, "replies": ["Something else", "Another"]},
        "2026-10-11-lmstudio-gemma-4-26b-a4b-it-qat": {"source": "live", "provider": "lmstudio", "model": "gemma-4-26b-a4b-it-qat",
                                                      "replies": [TABLE_REPLY, PODCAST_REPLY]},
    }
    for stem, run in runs.items():
        turns = [{"n": i + 1, "user": "…", "reply": r} for i, r in enumerate(run.pop("replies"))]
        (d / f"{stem}.json").write_text(json.dumps({"kind": "chat", "date": "2026-10-11", **run, "turns": turns}))
    (d / "2026-10-11-test-chat.turns.json").write_text(json.dumps({"id": "t", "turns": ["a", "b"]}))
    monkeypatch.setattr(rt, "EVALS_DIR", d)
    return d


@pytest.fixture
async def target(tmp_path, monkeypatch):
    """Odie's folder to import into: a throwaway home with one chat of its own, stored under an older install's app
    and user names (so the import must use the target's names, not the replay's). Settings point at it, and at a
    port nothing answers on."""
    home = tmp_path / "target" / "home"
    data = home / "data"
    data.mkdir(parents=True)
    await add_events(data / "sessions.db", "oldapp", "someone", "chat-2026-10-11", [
        said("user", time.time() - 7200, text("Good morning")),
        said("odie", time.time() - 7199, text("Morning, Asha!")),
    ])
    from odie.store.db import Store
    store = Store(data / "assistant.db")
    store.init_schema()
    store.close()
    monkeypatch.setenv("ODIE_HOME", str(home))
    monkeypatch.setenv("ODIE_DATA_DIR", str(data))
    monkeypatch.setenv("ODIE_CONFIG_DIR", str(home))
    monkeypatch.setenv("ODIE_MEMORY_FILE", str(home / "memories.md"))
    monkeypatch.setenv("ODIE_PORT", str(free_port()))
    monkeypatch.delenv("ODIE_APP_NAME", raising=False)
    monkeypatch.delenv("ODIE_USER_ID", raising=False)
    import odie.config as c
    importlib.reload(c)
    assert c.settings.data_dir == data and data.is_relative_to(tmp_path)  # never the real ~/.odie
    assert not data.resolve().is_relative_to((Path.home() / ".odie").resolve())
    assert (c.settings.app_name, c.settings.user_id) == ("oldapp", "someone")
    yield home
    monkeypatch.undo()
    importlib.reload(c)


def thread_rows(home: Path) -> list[tuple]:
    with sqlite3.connect(home / "data" / "assistant.db") as conn:
        return conn.execute("select session_id, title from threads").fetchall()


# ── The import, end to end ──────────────────────────────────────────────────────────────────────────────────────────

async def test_a_replay_becomes_a_thread_the_app_opens(target, replay_home, evals_dir, capsys):
    assert rt.main([str(replay_home)]) == 0

    from odie import config, threads
    from odie.app.runner import OdieRunner
    from odie.store.db import Store
    store = Store(config.settings.db_path)
    listed = threads.list_threads(store)
    assert [(t["id"], t["title"]) for t in listed][:1] == [("chat-2026-10-11-101", TITLE)]
    assert {t["id"] for t in listed} == {"chat-2026-10-11-101", "chat-2026-10-11"}  # the owner's own chat is still there

    runner = OdieRunner(store)
    try:
        history = await runner.session_history("chat-2026-10-11-101")
        day = await runner.history("2026-10-11")
    finally:
        await runner.close()
    items = history["items"]
    users = [i["text"] for i in items if i["role"] == "user"]
    assert users == ["Compare Pixel 10a and Galaxy A76", "can you create a podcast from our conversation"]  # trailers off
    replies = [i for i in items if i["role"] == "odie"]
    assert [r["tools"] for r in replies] == [["web_search"], ["speak"]]  # the tool chips, folded into each reply
    assert [r["text"] for r in replies] == [TABLE_REPLY, PODCAST_REPLY]  # the blocks fence as it was written
    assert replies[1]["media"][0]["id"] == MEDIA_ID and replies[1]["media"][0]["kind"] == "podcast"
    assert all(r["key"] and r["sid"] == "chat-2026-10-11-101" for r in replies)  # checklist ticks can be saved
    assert [i["text"] for i in day["items"]] == ["Good morning", "Morning, Asha!"]  # the day's own chat doesn't pull it in

    media = target / "data" / "media"
    assert sorted(p.name for p in media.iterdir()) == [f"{MEDIA_ID}.json", f"{MEDIA_ID}.wav"]  # not the file nothing names
    with sqlite3.connect(target / "data" / "sessions.db") as conn:
        owners = conn.execute("select distinct app_name, user_id from events where session_id='chat-2026-10-11-101'").fetchall()
    assert owners == [("oldapp", "someone")]
    out = capsys.readouterr().out
    assert "odie-chat-replay-ab12cd34 = 2026-10-11-anthropic-claude-opus-5-5-think-longer.json (2 of 2" in out


async def test_only_the_conversation_is_copied(target, replay_home, evals_dir):
    assert rt.main([str(replay_home)]) == 0
    with sqlite3.connect(target / "data" / "assistant.db") as conn:
        assert conn.execute("select count(*) from tasks").fetchone()[0] == 0
        assert conn.execute("select count(*) from trackers").fetchone()[0] == 0
    assert not (target / "memories.md").exists()


async def test_refuses_while_odie_answers_on_its_port(target, replay_home, evals_dir, monkeypatch, capsys):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    try:
        monkeypatch.setenv("ODIE_PORT", str(listener.getsockname()[1]))
        import odie.config as c
        importlib.reload(c)
        assert rt.main([str(replay_home)]) == 1
    finally:
        listener.close()
    assert "run odie stop first" in capsys.readouterr().out
    assert thread_rows(target) == []
    assert not (target.parent / ".odie-backups").exists()


async def test_backs_up_both_databases_before_writing(target, replay_home, evals_dir, capsys):
    assert rt.main([str(replay_home)]) == 0
    folders = list((target.parent / ".odie-backups").iterdir())
    assert len(folders) == 1 and folders[0].name.startswith("before-replay-threads-")
    assert sorted(p.name for p in folders[0].iterdir()) == ["assistant.db", "sessions.db"]
    with sqlite3.connect(folders[0] / "sessions.db") as conn:
        assert [r[0] for r in conn.execute("select id from sessions")] == ["chat-2026-10-11"]  # as it was before
    out = capsys.readouterr().out
    assert f"Backed up assistant.db and sessions.db to {folders[0]}" in out and ".restore" in out


async def test_running_it_again_adds_nothing(target, replay_home, evals_dir, capsys):
    assert rt.main([str(replay_home)]) == 0
    assert rt.main([str(replay_home)]) == 0
    assert "Nothing to import." in capsys.readouterr().out
    assert thread_rows(target) == [("chat-2026-10-11-101", TITLE)]

    from odie import config, threads
    from odie.store.db import Store
    threads.rename(Store(config.settings.db_path), "chat-2026-10-11-101", "Opus test")  # renamed since: still found
    assert rt.main([str(replay_home)]) == 0
    assert "already imported as chat-2026-10-11-101" in capsys.readouterr().out
    assert len(thread_rows(target)) == 1


async def test_dry_run_writes_nothing(target, replay_home, evals_dir, capsys):
    before = (target / "data" / "sessions.db").read_bytes()
    assert rt.main([str(replay_home), "--dry-run"]) == 0
    assert f'"{TITLE}" as chat-2026-10-11-101: 2 user turns, 8 events, 1 media' in capsys.readouterr().out
    assert (target / "data" / "sessions.db").read_bytes() == before
    assert thread_rows(target) == [] and not (target.parent / ".odie-backups").exists()


async def test_all_finds_the_homes_and_leaves_trial_runs(target, replay_home, evals_dir, capsys):
    trial = replay_home.parent.parent / "odie-chat-replay-trial000" / "home" / "data"
    trial.mkdir(parents=True)
    await add_events(trial / "sessions.db", "odie", "user", "replay-2026-10-11",
                     [said("user", time.time(), text("What can you do?")), said("odie", time.time() + 1, text("Lots."))])
    assert rt.main(["--all", "--from", str(replay_home.parent.parent)]) == 0
    out = capsys.readouterr().out
    assert "odie-chat-replay-trial000: skipped, no saved run matches it (user turns: 1)" in out
    assert thread_rows(target) == [("chat-2026-10-11-101", TITLE)]


# ── The decisions, one by one ───────────────────────────────────────────────────────────────────────────────────────

def test_is_sure_match():
    assert rt.is_sure_match(15, 0, 17)
    assert not rt.is_sure_match(3, 0, 17)
    assert not rt.is_sure_match(0, 0, 1)
    assert not rt.is_sure_match(17, 12, 17)  # two runs both match: not sure which


def test_thread_titles():
    opus = {"date": "2026-10-11", "provider": "anthropic", "model": "claude-opus-5-5", "settings": {"thinking": True}}
    gemma = {"date": "2026-10-11", "provider": "lmstudio", "model": "gemma-4-26b-a4b-it-qat", "settings": {"thinking": False}}
    sonnet = {"date": "2026-10-11", "provider": "anthropic", "model": "claude-sonnet-5-5", "settings": {"thinking": False}}
    assert rt.thread_title(opus, "2026-10-11-anthropic-claude-opus-5-5-think-longer") == "Replay · Opus 5.5 · think longer"
    assert rt.thread_title(gemma, "2026-10-11-lmstudio-gemma-4-26b-a4b-it-qat-after-fixes") == "Replay · Gemma 4 26B · after fixes"
    assert rt.thread_title(sonnet, "2026-10-11-anthropic-claude-sonnet-5-5") == "Replay · Sonnet 5.5"
    assert rt.display_name("some-new-model") == "some-new-model"


def test_free_session_id_starts_past_the_days_own_segments():
    conn = sqlite3.connect(":memory:")
    conn.execute("create table sessions (id text)")
    assert rt.free_session_id(conn, "2026-10-11", set()) == "chat-2026-10-11-101"
    conn.execute("insert into sessions values ('chat-2026-10-11-101')")
    assert rt.free_session_id(conn, "2026-10-11", {"chat-2026-10-11-102"}) == "chat-2026-10-11-103"
    from odie import threads
    assert threads.valid_id("chat-2026-10-11-101")  # a thread id the app accepts


def test_backups_go_beside_the_home_never_inside_it():
    from datetime import datetime
    folder = rt.backup_folder(Path("/Users/me/.odie"), datetime(2026, 10, 11, 21, 40, 5))
    assert folder == Path("/Users/me/.odie-backups/before-replay-threads-2026-10-11-214005")
