import importlib
import sqlite3

from odie.identity import DEFAULT_APP, DEFAULT_USER, stored_identity


def _sessions(path, rows):
    con = sqlite3.connect(path)
    con.execute("create table sessions (app_name text, user_id text, id text)")
    con.executemany("insert into sessions values (?, ?, ?)", rows)
    con.commit()
    con.close()


def test_keeps_the_names_existing_chats_use(tmp_path):
    db = tmp_path / "sessions.db"
    _sessions(db, [("old", "owner", "a"), ("old", "owner", "b"), ("eval", "bot", "c")])
    assert stored_identity(db) == ("old", "owner")  # the one with the most sessions


def test_unreadable_sessions_fall_back(tmp_path):
    assert stored_identity(tmp_path / "missing.db") is None
    (tmp_path / "junk.db").write_text("not sqlite")
    assert stored_identity(tmp_path / "junk.db") is None
    empty = tmp_path / "empty.db"
    sqlite3.connect(empty).close()
    assert stored_identity(empty) is None  # no sessions table
    _sessions(tmp_path / "none.db", [])
    assert stored_identity(tmp_path / "none.db") is None


def test_config_uses_stored_names_else_odies(isolated_settings, tmp_path, monkeypatch):
    import odie.config as c
    assert (c.settings.app_name, c.settings.user_id) == (DEFAULT_APP, DEFAULT_USER)
    _sessions(tmp_path / "sessions.db", [("old", "owner", "a")])
    s = importlib.reload(c).settings
    assert (s.app_name, s.user_id) == ("old", "owner")
    monkeypatch.setenv("ODIE_USER_ID", "someone")
    assert importlib.reload(c).settings.user_id == "someone"
