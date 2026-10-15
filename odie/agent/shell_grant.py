"""'Allow for 30 min' for run_shell: one tap lets shell commands in the same conversation run
without asking, for GRANT_MINUTES. Commands that read secrets, delete or stop things, send data out, or write outside
/tmp always ask anyway. A New chat is a new conversation, so it starts without a grant.

The check is ADK's require_confirmation predicate: it gets the tool's arguments and tool_context.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

from odie.agent.context import session_id_of
from odie.store.db import Store

GRANT_MINUTES = 30

_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("switches off another agent's approvals", re.compile(
        r"--yolo\b|--dangerously[\w-]*|--skip[\w-]*permissions|--no[\w-]*(approval|confirm)[\w-]*|--auto[\w-]*approve")),
    ("reads secrets", re.compile(
        r"\.env\b|\.netrc|\.ssh\b|id_rsa|id_ed25519|\.pem\b|keychain|security\s+find-|_PAT\b|_KEY\b|_TOKEN\b|SECRET|"
        r"PASSWORD|passwd|credential|auth\.json|token\.json|client_secret|\.(zshrc|zshenv|zprofile|bashrc|bash_profile|profile)\b|"
        r"(^|[;&|(]\s*)(env|printenv)\b", re.IGNORECASE)),
    ("deletes or stops something", re.compile(
        r"(^|[;&|(`]\s*|\s)(rm|rmdir|kill|pkill|killall|sudo|chmod|chown|dd|mkfs|shutdown|reboot|launchctl|truncate|"
        r"shred|mv|crontab)\b|\bgit\s+(push|reset|clean|rebase|checkout\s+--)")),
    ("sends data out", re.compile(
        r"\bcurl\b[^|;]*(-X\s*(POST|PUT|PATCH|DELETE)|--data|\s-d\s|\s-F\s|--form|\s-T\s|--upload)|\bwget\b[^|;]*--post|"
        r"\b(scp|ssh|ftp|sftp|nc|ncat|sendmail)\b|\brsync\b[^|;]*\S+:")),
    ("edits files in place", re.compile(r"\b(sed|perl)\s+(-\w*\s+)*-i|\btee\b")),
    ("runs inline code", re.compile(r"\b(python3?|node|ruby|perl|osascript)\s+(-\w+\s+)*-(c|e)\b")),
]
_REDIRECT = re.compile(r"\d?>>?\s*(&?[^\s;&|<>]+)")
_SAFE_TARGETS = ("/dev/null", "/tmp/", "/private/tmp/")


def always_ask(command: str) -> str | None:
    """Why this command must be tapped even under a grant, or None if a grant covers it.
    Examples: `ls ~/Downloads` -> None; `rm old.txt` -> "deletes or stops something";
    `echo hi > /tmp/x` -> None; `echo hi > notes.txt` -> "writes a file outside /tmp"."""
    for why, rule in _RULES:
        if rule.search(command):
            return why
    for target in _REDIRECT.findall(command):
        if not target.startswith("&") and not target.startswith(_SAFE_TARGETS):
            return "writes a file outside /tmp"
    return None


def _key(session_id: str) -> str:
    return f"shell_grant:{session_id}"


def grant(store: Store, session_id: str, now: datetime, minutes: int = GRANT_MINUTES) -> datetime:
    until = now + timedelta(minutes=minutes)
    store.set_setting(_key(session_id), {"until": until.isoformat()})
    return until


def active(store: Store, session_id: str, now: datetime) -> bool:
    """Is this chat's 'Allow for 30 min' pass still running? Example: granted at 10:00 -> True at 10:29, False at 10:31;
    never granted, or a stored value that can't be read -> False."""
    got = store.get_setting(_key(session_id))
    try:
        return bool(got) and datetime.fromisoformat(got["until"]) > now
    except (KeyError, TypeError, ValueError):
        return False


def make_check(store: Store, clock: Callable[[], datetime] = datetime.now) -> Callable[..., bool]:
    """require_confirmation for run_shell: True means show the user the card."""
    def needs_tap(command: str = "", cwd: str | None = None, tool_context: Any = None, **_: Any) -> bool:
        """Does this shell command need the user's tap? Decided in three steps:
        1. No 'Allow for 30 min' pass in this chat (or it ran out) -> ask (the card).
        2. A pass, but the command is on the always-ask list (always_ask) -> ask anyway, and note it in the audit log.
        3. A pass and an ordinary command -> run it without a card, and note it in the audit log.

        Examples:
          `ls ~/Downloads`, no pass         -> card
          `ls ~/Downloads`, with a pass     -> runs, no card
          `rm old.txt`, with a pass         -> card anyway ("deletes or stops something")
          `cat ~/.env`, with a pass         -> card anyway ("reads secrets")
        """
        session_id = session_id_of(tool_context)
        if not session_id:
            return True  # outside a chat there is no pass to look up
        if not active(store, session_id, clock()):
            return True  # no pass, or it ran out

        why = always_ask(command)
        audit_args = {"command": command, "cwd": cwd}
        if why is not None:
            store.audit("agent", "shell_asked_under_grant", tool="run_shell", args=audit_args,
                        result_summary=why, session_id=session_id)
            return True

        store.audit("agent", "shell_auto_approved", tool="run_shell", args=audit_args,
                    result_summary="allowed for 30 min", session_id=session_id)
        return False
    return needs_tap
