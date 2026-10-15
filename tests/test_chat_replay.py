"""The chat replay's own pieces (odie/chat_replay.py): the turn list, the read-only import of a live chat, the persona,
the results' shape and the throwaway home. The live runs themselves are scripts/chat_replay.sh; the reply scorer is
web/src/blocks/eval/chatScore.ts (with its own tests)."""
import json
import os
import sqlite3
from pathlib import Path

import pytest

from odie import blocks_eval as be
from odie import chat_replay as cr


# ── The turns ──

@pytest.mark.skipif(not cr.DEFAULT_TURNS.exists(), reason="no turn list in evals/chats (your own test chats are never committed)")
def test_the_committed_turn_list_is_the_owners_chat_in_order():
    conversation = cr.load_turns(cr.DEFAULT_TURNS)
    turns = conversation["turns"]
    assert len(turns) == 17
    assert turns[0] == "What can you do?"
    assert turns[3] == "Yes" and turns[5] == "yes"  # follow-ups that only make sense in one chat
    assert turns[-1] == "can you create a podcast from our conversation an interesting one"
    assert not any("nothing is visual" in t for t in turns)  # his reactions to Gemma are left out


def test_load_turns_refuses_an_empty_turn(tmp_path):
    bad = tmp_path / "bad.turns.json"
    bad.write_text(json.dumps({"id": "x", "turns": ["ok", "  "]}))
    with pytest.raises(ValueError, match="turn 2"):
        cr.load_turns(bad)
    none = tmp_path / "none.turns.json"
    none.write_text(json.dumps({"id": "x", "turns": []}))
    with pytest.raises(ValueError, match="no turns"):
        cr.load_turns(none)


def test_short_args_and_podcast_hosts():
    long = "x" * 500
    assert cr.short_args({"query": "Pixel 10a", "max_results": 5}) == {"query": "Pixel 10a", "max_results": 5}
    assert cr.short_args({"script": long})["script"] == "x" * cr.SHORT_ARG + "…"
    assert cr.podcast_hosts("Asha: Welcome!\nRohan: Hi.\nAsha: So…") == ["Asha", "Rohan"]
    assert cr.podcast_hosts("just words") == []
    call = cr.tool_record("speak", {"style": "podcast", "script": "Asha: Hi\nRohan: Hey"})
    assert call["hosts"] == ["Asha", "Rohan"]
    assert "hosts" not in cr.tool_record("speak", {"style": "memo", "script": "Hello"})


def test_loaded_visuals():
    assert cr.loaded_visuals([{"tool": "load_skill", "args": {"skill_name": "visuals"}}])
    assert not cr.loaded_visuals([{"tool": "load_skill", "args": {"skill_name": "podcast"}}, {"tool": "web_search", "args": {}}])


# ── Importing a live chat, from a small fake sessions database ──

def _event(ts: float, author: str, parts: list[dict], usage: dict | None = None) -> tuple:
    data = {"author": author, "content": {"role": "user" if author == "user" else "model", "parts": parts}, "timestamp": ts}
    if usage:
        data["usage_metadata"] = usage
    return ("chat-2026-10-11", ts, json.dumps(data))


def _fake_sessions_db(path: Path) -> None:
    rows = [
        _event(100.0, "user", [{"text": "Compare phones\n\n[context: now 18:13 Sun 11 Oct]"}]),
        _event(101.0, "odie", [{"function_call": {"id": "a", "name": "web_search", "args": {"query": "Pixel 10a price"}}}],
               {"prompt_token_count": 5000, "candidates_token_count": 20}),
        _event(102.0, "odie", [{"function_response": {"id": "a", "name": "web_search", "response": {"result": "…"}}}]),
        _event(103.0, "odie", [{"function_call": {"id": "b", "name": "load_skill", "args": {"skill_name": "visuals"}}}],
               {"prompt_token_count": 6000, "candidates_token_count": 10}),
        _event(104.0, "odie", [{"text": "Here:", "thought": False}, {"text": "secret reasoning", "thought": True}]),
        _event(105.0, "odie", [{"text": "```odie-blocks\n[{\"type\":\"divider\"}]\n```"}],
               {"prompt_token_count": 7000, "candidates_token_count": 300}),
        _event(106.0, "user", [{"text": "[odie check] Your reply says it was saved…"}]),  # a nudge stays in its turn
        _event(107.0, "odie", [{"text": "Done."}]),
        _event(200.0, "user", [{"text": "I see json\n[image:871a5acbefc94de3a2a77702cd9dd8f2]\n\n[context: now 18:28 Sun 11 Oct]"}]),
        _event(210.5, "odie", [{"function_call": {"id": "c", "name": "speak",
                                                  "args": {"style": "podcast", "script": "Asha: Hi\nRohan: Hey"}}}]),
        _event(211.0, "odie", [{"function_response": {"id": "c", "name": "speak",
                                                      "response": {"media": {"id": "m1", "kind": "podcast", "title": "Recap"}}}}]),
        _event(212.0, "odie", [{"text": "Enjoy the listen!"}]),
        ("another-session", 300.0, json.dumps({"author": "user", "content": {"parts": [{"text": "not this one"}]}})),
    ]
    with sqlite3.connect(path) as conn:
        conn.execute("create table events (session_id text, timestamp real, event_data text)")
        conn.executemany("insert into events values (?, ?, ?)", rows)


def test_import_session_reads_turns_in_the_replays_format(tmp_path):
    db = tmp_path / "sessions.db"
    _fake_sessions_db(db)
    turns = cr.import_session(db, "chat-2026-10-11")
    assert [t["user"] for t in turns] == ["Compare phones", "I see json"]  # trailer and image marker taken off

    first = turns[0]
    assert [t["tool"] for t in first["tools"]] == ["web_search", "load_skill"]
    assert first["tools"][0]["args"] == {"query": "Pixel 10a price"}
    assert first["visuals"] is True
    assert first["reply"] == "Here:\n\n```odie-blocks\n[{\"type\":\"divider\"}]\n```\n\nDone."  # no thoughts, no nudge text
    assert first["seconds"] == 7.0
    assert first["tokens"] == {"input": 18000, "cached": 0, "output": 330, "calls": 3}

    second = turns[1]
    assert second["images"] == 1
    assert second["tools"][0]["hosts"] == ["Asha", "Rohan"]
    assert second["media"] == [{"kind": "podcast", "title": "Recap"}]
    assert second["reply"] == "Enjoy the listen!"
    assert second["visuals"] is False


def test_import_session_never_writes_the_database(tmp_path):
    db = tmp_path / "sessions.db"
    _fake_sessions_db(db)
    db.chmod(0o444)  # read only on disk too: the import must still work
    try:
        assert len(cr.import_session(db, "chat-2026-10-11")) == 2
        with cr.read_only(db) as conn, pytest.raises(sqlite3.OperationalError):
            conn.execute("delete from events")
    finally:
        db.chmod(0o644)


# ── The persona ──

def test_owner_names_from_a_read_only_database(tmp_path):
    db = tmp_path / "assistant.db"
    with sqlite3.connect(db) as conn:
        conn.execute("create table settings (key text primary key, value_json text not null)")
        conn.execute("insert into settings values ('profile', ?)", (json.dumps({"user_name": "Asha"}),))
        conn.execute("insert into settings values ('persona', ?)", (json.dumps({"name": "Iris", "avatar": "x"}),))
    assert cr.owner_names(db) == {"user_name": "Asha", "assistant_name": "Iris"}
    assert cr.owner_names(tmp_path / "missing.db") == {"user_name": "", "assistant_name": ""}


def test_copy_persona_copies_soul_and_sets_names_like_setup(tmp_path):
    from odie import persona, profile
    from odie.store.db import Store
    owner = tmp_path / "owner"
    owner.mkdir()
    (owner / "SOUL.md").write_text("You are Iris, a personal assistant.")
    home = tmp_path / "throwaway" / "home"
    store = Store(tmp_path / "throwaway.db")
    store.init_schema()
    assert cr.copy_persona(owner, home, store, {"user_name": "Asha", "assistant_name": "Iris"}) is True
    assert (home / "SOUL.md").read_text() == "You are Iris, a personal assistant."
    assert profile.get(store)["user_name"] == "Asha"
    assert persona.get(store)["name"] == "Iris"
    assert (owner / "SOUL.md").read_text() == "You are Iris, a personal assistant."  # the owner's copy untouched


def test_prompt_differences_ignores_blank_lines():
    assert cr.prompt_differences("A\nB\nC", "A\nC\nD") == ["- B", "+ D"]
    assert cr.prompt_differences("A\n\nB", "A\nB") == []


def test_first_live_system_prompt_reads_the_oldest_saved_request(tmp_path):
    (tmp_path / "20261011-183201-1.json").write_text(json.dumps({"messages": [{"role": "system", "content": "old"}]}))
    (tmp_path / "20261011-184316-2.json").write_text(json.dumps({"messages": [{"role": "system", "content": "new"}]}))
    assert cr.first_live_system_prompt(tmp_path) == "old"
    assert cr.first_live_system_prompt(tmp_path / "none") == ""


# ── The throwaway home and the keys ──

def test_the_throwaway_home_is_never_the_owners(tmp_path):
    env = be.throwaway_env(tmp_path)
    real = Path.home() / ".odie"
    for name in ("ODIE_HOME", "ODIE_DATA_DIR", "ODIE_CONFIG_DIR", "ODIE_MEMORY_FILE"):
        assert be.is_inside(env[name], tmp_path), name
        assert not be.is_inside(env[name], real), name


def test_use_throwaway_home_stops_when_odie_still_points_elsewhere(tmp_path, monkeypatch):
    # Settings already loaded (as here, in the test process) point outside the new root: the run must stop, not write.
    monkeypatch.setattr(os, "environ", dict(os.environ))
    with pytest.raises(SystemExit, match="isn't the throwaway one"):
        be.use_throwaway_home(tmp_path / "root")


def test_keys_are_copied_by_name_only(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("TAVILY_API_KEY=tvly-test\nOTHER=nope\n")
    # setenv, not delenv: pytest undoes a delenv of an absent name by doing nothing, so the copied key would leak
    # into later tests. An empty value counts as unset for load_secret, and teardown removes it again.
    monkeypatch.setenv("TAVILY_API_KEY", "")
    monkeypatch.setenv("OTHER", "")
    assert be.copy_key(cr.SEARCH_KEY, env_file) is True
    assert os.environ["TAVILY_API_KEY"] == "tvly-test"
    assert os.environ["OTHER"] == ""


# ── The results ──

def _turn(n: int, kinds: list[str], tools: list[str], error: str | None = None, not_drawn: list | None = None) -> dict:
    return {"n": n, "user": f"turn {n}", "reply": "" if error else "x", "tools": [{"tool": t, "args": {}} for t in tools],
            "visuals": False, "media": [], "events": [], "error": error, "seconds": 2.5,
            "tokens": {"input": 1000, "cached": 0, "output": 50, "calls": 1},
            "score": {"fences": len(kinds), "parsed": True, "kinds": kinds, "dropped": [], "not_drawn": not_drawn or []}}


def test_totals_and_what_it_did():
    turns = [_turn(1, ["table", "callout"], ["web_search", "load_skill"]), _turn(2, [], [], error="no reply in 240 s"),
             _turn(3, [], ["web_search"], not_drawn=[{"as": "inline code", "lang": "", "text": "odie-images: {…"}])]
    assert cr.totals(turns) == {"seconds": 7.5, "input": 3000, "cached": 0, "output": 150, "calls": 3, "errors": 1}
    assert cr.what_it_did(turns[0]) == "table, callout · web_search, load_skill"
    assert cr.what_it_did(turns[1]) == "error: no reply in 240 s"
    assert cr.what_it_did(turns[2]) == "plain text, 1 not drawn (inline code) · web_search"


def test_chat_markdown_has_a_line_per_turn():
    chat = {"provider": "anthropic", "model": "claude-opus-5-5", "date": "2026-10-11", "source": "replay",
            "odie_commit": "abc1234", "turns": [_turn(1, ["checklist"], ["load_skill"])]}
    chat["totals"] = cr.totals(chat["turns"])
    md = cr.chat_markdown(chat, "2026-10-11-anthropic-claude-opus-5-5")
    assert md.startswith("# Chat: `anthropic/claude-opus-5-5`")
    assert "| 1 | turn 1 | checklist · load_skill | 2.5 s |" in md


def test_turn_record_shape():
    asked = {"reply": "Hi", "tools": [{"tool": "load_skill", "args": {"skill_name": "visuals"}}], "media": [],
             "events": [], "error": None, "seconds": 1.2, "tokens": {"input": 1, "cached": 0, "output": 1, "calls": 1}}
    record = cr.turn_record(4, "Yes", asked)
    assert set(record) == {"n", "user", "reply", "tools", "visuals", "media", "events", "error", "seconds", "tokens"}
    assert record["n"] == 4 and record["visuals"] is True


def test_saved_chats_leaves_out_the_turn_lists(tmp_path):
    (tmp_path / "2026-10-11-test-chat.turns.json").write_text("{}")
    (tmp_path / "2026-10-11-anthropic-claude-opus-5-5.json").write_text("{}")
    assert [p.name for p in cr.saved_chats(tmp_path)] == ["2026-10-11-anthropic-claude-opus-5-5.json"]


def test_session_date_and_option():
    assert cr.session_date("chat-2026-10-11") == "2026-10-11"
    assert cr.session_date("eval-x") == ""
    assert cr.option(["--label", "lmstudio/gemma"], "--label") == "lmstudio/gemma"
    assert cr.option(["--label"], "--label") is None
