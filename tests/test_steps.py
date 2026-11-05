"""A tool call as a step: its arguments and result as capped text."""
from __future__ import annotations

from odie.app.steps import (
    ARG_CHARS,
    REJECTED,
    RESULT_CHARS,
    WAITING,
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
