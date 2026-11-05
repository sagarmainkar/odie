"""A tool call as a step: its arguments and result as capped text, and what kind of answer ADK gave back.

The reply's trace shows each tool call. These helpers turn ADK's raw tool responses and arguments into short plain
text that is safe to store and show.
"""
from __future__ import annotations

import json

RESULT_CHARS = 3000  # a result longer than this is cut, with a note of how much was left out
ARG_CHARS = 500  # an argument value longer than this is cut

# The texts ADK writes as an error when a call is gated (see google/adk/tools/function_tool.py).
WAITING = "This tool call requires confirmation"
REJECTED = "This tool call is rejected"

_SHELL_TOOLS = {"run_shell"}  # a command is only useful whole, so it gets the longer result limit


UNPRINTABLE = "(unprintable result)"  # shown when a value cannot be turned into text at all


def _compact_json(value: object) -> str:
    # skipkeys: a dict key that is not text (such as a tuple) is left out instead of raising
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str, skipkeys=True)


def _mcp_texts(response: dict) -> str | None:
    """The joined text parts of an MCP-shaped response, or None when it is not that shape.

    {"content": [{"type": "text", "text": "a"}, {"type": "text", "text": "b"}]} -> "a\\nb";
    {"count": 2} -> None (no content list, so it is not MCP).
    """
    content = response.get("content")
    if not isinstance(content, list):
        return None
    texts = []
    for part in content:
        if isinstance(part, dict) and part.get("type") == "text":
            texts.append(str(part.get("text", "")))
    return "\n".join(texts)


def _render(response: object) -> str:
    """The uncapped text of a tool response (may raise on odd values; result_text catches that)."""
    if response is None:
        return ""
    if isinstance(response, str):
        return response
    if not isinstance(response, dict):
        return _compact_json(response)

    mcp = _mcp_texts(response)
    if "result" in response:
        return str(response["result"])
    if "error" in response:
        return "Error: " + str(response["error"])
    if mcp is not None:
        return mcp
    return _compact_json(response)


def result_text(response: object) -> str:
    """A tool response as plain text, cut at RESULT_CHARS. Never raises.

    {"result": "3 files"} -> "3 files"; {"error": "no such file"} -> "Error: no such file";
    {"content": [{"type": "text", "text": "hi"}]} -> "hi"; {"a": 1} -> '{"a":1}'; None -> "";
    a list that contains itself -> "(unprintable result)".
    """
    try:
        text = _render(response)
    except Exception:  # noqa: BLE001 - a trace line must never break the reply it describes
        text = UNPRINTABLE

    if len(text) > RESULT_CHARS:
        left_out = len(text) - RESULT_CHARS
        text = text[:RESULT_CHARS] + f"… ({left_out} more characters)"
    return text


def _plain_text(value: object) -> str:
    try:
        return str(value)
    except Exception:  # noqa: BLE001 - a trace line must never break the reply it describes
        return UNPRINTABLE


def capped_args(tool: str, args: dict) -> dict:
    """A tool call's arguments with every value made plain and short.

    Numbers, booleans and short strings stay as they are; anything else is turned into text; text longer than
    ARG_CHARS is cut and ends in "…". The one exception is the shell tool's `command`, which keeps up to RESULT_CHARS.
    Example: ("web_search", {"query": <1,200 chars>}) -> the query cut at 500 + "…";
    ("run_shell", {"command": <1,200 chars>}) -> the command whole;
    ("run_shell", {"cwd": <1,200 chars>}) -> the cwd cut at 500 + "…".
    """
    capped: dict = {}
    for name, value in args.items():
        is_shell_command = tool in _SHELL_TOOLS and name == "command"
        limit = RESULT_CHARS if is_shell_command else ARG_CHARS
        if not isinstance(value, (str, int, float, bool)):
            value = _plain_text(value)
        if isinstance(value, str) and len(value) > limit:
            value = value[:limit] + "…"
        capped[name] = value
    return capped


def response_kind(response: object) -> str:
    """What ADK's answer to a tool call means: "wait", "no" or "done".

    {"error": "This tool call requires confirmation, please approve or reject."} -> "wait" (it is waiting for a tap);
    {"error": "This tool call is rejected."} -> "no" (the person said no);
    {"result": "ok"} -> "done"; {"error": "disk full"} -> "done" (the tool ran, it just failed).
    """
    if not isinstance(response, dict):
        return "done"
    error = response.get("error")
    if not isinstance(error, str):
        return "done"
    if error.startswith(WAITING):
        return "wait"
    if error.startswith(REJECTED):
        return "no"
    return "done"
