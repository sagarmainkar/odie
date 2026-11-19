"""Who is behind a turn that is running now, by its session (19 Nov 2026, the phase-3 security pass): a turn the odie
command sent from the terminal (an agent or a script typed it), or a background run (the watch, a tracker) where nobody
is there to tap. A chat turn in the app is neither. Tools that act as the user (his Done said in chat:
odie.loops.chat_done) refuse the first two. Kept in memory: a turn marks itself when it starts and unmarks when it
ends (OdieRunner.chat, OdieRunner.background_turn)."""
from __future__ import annotations

TERMINAL = "terminal"
BACKGROUND = "background"
_running: dict[str, str] = {}


def mark(session_id: str | None, kind: str) -> None:
    if session_id:
        _running[session_id] = kind


def unmark(session_id: str | None) -> None:
    if session_id:
        _running.pop(session_id, None)


def kind_of(session_id: str | None) -> str:
    """Who is behind this session's running turn: "terminal", "background", or "" (the app's own chat, or none)."""
    if not session_id:
        return ""
    return _running.get(session_id, "")
