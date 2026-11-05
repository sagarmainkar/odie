"""A tool call as a step: its arguments and result as capped text."""
from __future__ import annotations

import json

from odie.app.steps import (
    ARG_CHARS,
    REJECTED,
    RESULT_CHARS,
    WAITING,
    allowed_of,
    capped_args,
    response_kind,
    result_text,
)


def test_result_text_renders_each_shape():
    assert result_text({"result": "3 files"}) == "3 files"
    assert result_text({"error": "no such file"}) == "Error: no such file"
    mcp = {"content": [{"type": "text", "text": "one"}, {"type": "text", "text": "two"}], "isError": False}
    assert result_text(mcp) == "one\ntwo"
    assert result_text({"count": 2, "name": "é"}) == '{"count":2,"name":"é"}'
    assert result_text("plain") == "plain"
    assert result_text(None) == ""
    assert result_text([1, "a"]) == '[1,"a"]'


def test_result_text_is_capped():
    assert result_text("x" * RESULT_CHARS) == "x" * RESULT_CHARS
    cut = result_text({"result": "x" * (RESULT_CHARS + 1)})
    assert cut == "x" * RESULT_CHARS + "… (1 more characters)"


def test_capped_args_keeps_a_shell_command_whole():
    command = "echo " + "a" * 1195
    assert capped_args("run_shell", {"command": command}) == {"command": command}
    cwd = "c" * 1200
    assert capped_args("run_shell", {"cwd": cwd}) == {"cwd": "c" * ARG_CHARS + "…"}
    query = "q" * 1200
    assert capped_args("web_search", {"query": query}) == {"query": "q" * ARG_CHARS + "…"}
    mixed = capped_args("t", {"n": 3, "f": 1.5, "b": True, "l": [1, 2], "s": "ok"})
    assert mixed == {"n": 3, "f": 1.5, "b": True, "l": "[1, 2]", "s": "ok"}


def test_response_kind():
    assert response_kind({"error": WAITING + ", please approve or reject."}) == "wait"
    assert response_kind({"error": REJECTED + "."}) == "no"
    assert response_kind({"error": "boom"}) == "done"
    assert response_kind({"result": "ok"}) == "done"
    assert response_kind(None) == "done"
    assert response_kind("This tool call requires confirmation") == "done"


def test_result_text_never_raises():
    circular: list = []
    circular.append(circular)

    class Broken:
        def __str__(self):
            raise RuntimeError("no text")

    assert result_text(circular) == "(unprintable result)"
    assert result_text({("a", "b"): 1}) == "{}"
    assert result_text({"result": Broken()}) == "(unprintable result)"
    assert capped_args("t", {"x": Broken()}) == {"x": "(unprintable result)"}


def _store(tmp_path):
    from odie.store.db import Store

    store = Store(tmp_path / "a.db")
    store.init_schema()
    return store


def test_create_approval_keeps_the_call_id(tmp_path):
    store = _store(tmp_path)
    with_id = store.create_approval("chat-1", "inv-1", "req-1", "gmail_trash", {"message_id": "m1"}, "Trash", {}, [], call_id="call-1")
    without = store.create_approval("chat-1", "inv-1", "req-2", "gmail_trash", {"message_id": "m2"}, "Trash", {}, [])
    assert store.get_approval(with_id)["call_id"] == "call-1"
    assert store.get_approval(without)["call_id"] is None


def test_an_old_approvals_table_gains_the_call_id_column(tmp_path):
    import sqlite3

    from odie.store.db import Store

    path = tmp_path / "old.db"
    old = sqlite3.connect(str(path))
    old.execute("create table approvals(id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, invocation_id TEXT NOT NULL, "
                "request_id TEXT NOT NULL, tool TEXT NOT NULL, args_json TEXT NOT NULL, summary TEXT NOT NULL, "
                "detail_json TEXT, provenance_json TEXT, status TEXT NOT NULL DEFAULT 'pending', "
                "created_at TEXT NOT NULL DEFAULT 'x', decided_at TEXT, result_text TEXT)")
    old.close()
    store = Store(path)
    store.init_schema()
    columns = {row["name"] for row in store.query("pragma table_info(approvals)")}
    assert "call_id" in columns


def test_approvals_for_calls_returns_only_decided_rows_of_the_session(tmp_path):
    store = _store(tmp_path)
    yes = store.create_approval("chat-1", "inv-1", "r1", "gmail_trash", {}, "Trash", {}, [], call_id="c1")
    no = store.create_approval("chat-1", "inv-1", "r2", "gmail_trash", {}, "Trash", {}, [], call_id="c2")
    store.create_approval("chat-1", "inv-1", "r3", "gmail_trash", {}, "Trash", {}, [], call_id="c3")  # still pending
    store.create_approval("chat-2", "inv-2", "r4", "gmail_trash", {}, "Trash", {}, [], call_id="c4")  # another session
    store.decide_approval(yes, True)
    store.decide_approval(no, False)
    rows = store.approvals_for_calls("chat-1")
    assert [row["call_id"] for row in rows] == ["c1", "c2"]


def test_allowed_by_call_id(tmp_path):
    store = _store(tmp_path)
    yes = store.create_approval("chat-1", "inv-1", "r1", "gmail_trash", {"message_id": "m1"}, "Trash", {}, [], call_id="c1")
    no = store.create_approval("chat-1", "inv-1", "r2", "gmail_trash", {"message_id": "m2"}, "Trash", {}, [], call_id="c2")
    store.decide_approval(yes, True)
    store.decide_approval(no, False)
    rows = store.approvals_for_calls("chat-1")

    said_yes = allowed_of("gmail_trash", "c1", "inv-1", {"message_id": "m1"}, {"result": "ok"}, rows)
    assert said_yes == {"by": "you", "at": store.get_approval(yes)["decided_at"]}
    said_no = allowed_of("gmail_trash", "c2", "inv-1", {"message_id": "m2"}, {"error": REJECTED}, rows)
    assert said_no == {"by": "no", "at": store.get_approval(no)["decided_at"]}


def test_allowed_by_old_row_args_match(tmp_path):
    # An approval made before call_id existed has call_id None: it is found by invocation, tool and the exact arguments.
    store = _store(tmp_path)
    args = {"message_id": "m1", "note": "é"}
    old = store.create_approval("chat-1", "inv-1", "r1", "gmail_trash", args, "Trash", {}, [])
    store.decide_approval(old, True)
    rows = store.approvals_for_calls("chat-1")
    assert rows[0]["call_id"] is None

    found = allowed_of("gmail_trash", "call-x", "inv-1", args, {"result": "ok"}, rows)
    assert found == {"by": "you", "at": store.get_approval(old)["decided_at"]}
    assert allowed_of("gmail_trash", "call-x", "inv-1", {"message_id": "m2"}, {"result": "ok"}, rows) is None
    assert allowed_of("gmail_trash", "call-x", "inv-2", args, {"result": "ok"}, rows) is None
    assert allowed_of("gmail_archive", "call-x", "inv-1", args, {"result": "ok"}, rows) is None


def test_no_match_is_no_pill_not_pass():
    assert allowed_of("web_fetch", "c1", "inv-1", {"url": "https://studio.local"}, {"result": "page"}, []) is None
    assert allowed_of("run_shell", "c1", "inv-1", {"command": "rm x"}, {"error": WAITING}, []) is None
    assert allowed_of("web_search", "c1", "inv-1", {"query": "q"}, {"result": "hits"}, []) is None


def test_shell_without_a_row_ran_under_the_pass():
    ran = allowed_of("run_shell", "c1", "inv-1", {"command": "ls"}, {"result": "a.txt"}, [])
    assert ran == {"by": "pass"}
    failed = allowed_of("run_shell", "c1", "inv-1", {"command": "false"}, {"result": "exit 1"}, [])
    assert failed == {"by": "pass"}


def test_a_shell_refusal_from_the_args_check_gets_no_pill():
    refused = {"error": "refused: command not allowed"}
    assert allowed_of("run_shell", "c1", "inv-1", {"command": "x"}, refused, []) is None


def test_a_row_decides_before_the_pass_rule(tmp_path):
    store = _store(tmp_path)
    row_id = store.create_approval("chat-1", "inv-1", "r1", "run_shell", {"command": "rm x"}, "Run rm", {}, [], call_id="c1")
    store.decide_approval(row_id, True)
    rows = store.approvals_for_calls("chat-1")
    allowed = allowed_of("run_shell", "c1", "inv-1", {"command": "rm x"}, {"result": ""}, rows)
    assert allowed["by"] == "you"
    assert json.dumps({"command": "rm x"}, default=str) == rows[0]["args_json"]
