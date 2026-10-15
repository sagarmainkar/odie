"""Two small readers for ADK objects, so callers don't repeat getattr(getattr(...)) chains.

ADK hands Odie a tool_context (or callback context) and a stream of events. Either may be a real ADK object, a test's
stand-in, or None, so both readers fall back quietly instead of raising.
"""
from __future__ import annotations

from typing import Any


def session_id_of(ctx: Any) -> str | None:
    """The chat's session id from a tool_context (or anything with .session.id), or None when there isn't one.

    Example: a tool_context inside chat "abc123" -> "abc123"; tool_context=None (a background check) -> None.
    """
    session = getattr(ctx, "session", None)
    return getattr(session, "id", None)


def parts_of(event: Any) -> list:
    """The parts (text, tool calls, tool results) of an ADK event's content, or [] when it has none.

    Example: an event whose model reply calls web_search -> [Part(function_call=web_search(...))];
    an event with no content (a state update) -> [].
    """
    content = getattr(event, "content", None)
    parts = getattr(content, "parts", None)
    if not parts:
        return []
    return parts
