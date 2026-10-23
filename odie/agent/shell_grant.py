"""'Allow for 30 min' for run_shell: one tap lets shell commands in the same conversation run
without asking, for GRANT_MINUTES. Commands that read secrets, delete or stop things, send data out, or write outside
/tmp, Odie's workspace and the user's vault always ask anyway. Inline code (python3 -c, a script fed to python3 from a
heredoc) runs under the pass unless its own text reads secrets, deletes or sends data out (23 Oct 2026, the user's
choice: on their own Mac that's a fair trade). Text a command only writes to a file (a heredoc fed to cat) is data,
never read as commands. A New chat is a new conversation, so it starts without a grant.

The check is ADK's require_confirmation predicate: it gets the tool's arguments and tool_context.
"""
from __future__ import annotations

import os
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
        r"shred|mv|crontab)\b|\bgit\s+(push|reset|clean|rebase|checkout\s+--)|"
        r"\bos\.(remove|unlink|rmdir|kill)\b|\bshutil\.(rmtree|move)\b|\.unlink\(|\.rmdir\(|"
        r"\.(rm|rmSync|unlinkSync|rmdirSync)\(|\bsubprocess\b|\bos\.system\b|child_process")),
    ("sends data out", re.compile(
        r"\bcurl\b[^|;]*(-X\s*(POST|PUT|PATCH|DELETE)|--data|\s-d\s|\s-F\s|--form|\s-T\s|--upload)|\bwget\b[^|;]*--post|"
        r"\b(scp|ssh|ftp|sftp|nc|ncat|sendmail)\b|\brsync\b[^|;]*\S+:|"
        r"\brequests\.(post|put|patch|delete)\b|\bhttpx\.(post|put|patch|delete)\b|\bsmtplib\b|"
        r"method\s*:\s*['\"](POST|PUT|PATCH|DELETE)")),
    ("edits files in place", re.compile(r"\b(sed|perl)\s+(-\w*\s+)*-i|\btee\b")),
]
_REDIRECT = re.compile(r"\d?>>?\s*(&\d*|'[^']*'|\"[^\"]*\"|[^\s;&|<>]+)")
_HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1")
_INTERPRETER = re.compile(r"\b(python3?|node|ruby|perl|osascript|bash|sh|zsh|deno|bun)\b")
_SEGMENT = re.compile(r"&&|\|\||;|\n")
_CD = re.compile(r"^\s*cd\s+(.+?)\s*$")
_ALWAYS_SAFE = ("/dev/null", "/tmp", "/private/tmp")


def split_heredocs(command: str) -> tuple[str, str]:
    """The command's own shell text, and the code an interpreter reads from its heredocs. A heredoc fed to cat is the
    file's words, in neither: `cat > a.md <<'EOF'\nrm this\nEOF` -> ("cat > a.md <<'EOF'", "");
    `python3 - <<'EOF'\nimport os\nEOF` -> ("python3 - <<'EOF'", "import os")."""
    lines = command.split("\n")
    shell = []
    code = []
    i = 0
    while i < len(lines):
        line = lines[i]
        shell.append(line)
        i += 1
        heredoc = _HEREDOC.search(line)
        if heredoc is None:
            continue
        end = heredoc.group(2)
        body = []
        while i < len(lines) and lines[i].strip() != end:
            body.append(lines[i])
            i += 1
        i += 1  # the line that ends it
        fed_to = line[:heredoc.start()]
        if _INTERPRETER.search(fed_to):
            code.extend(body)
    return "\n".join(shell), "\n".join(code)


def _unquoted(text: str) -> str:
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        return text[1:-1]
    return text


def _expanded(path: str, here: str) -> str:
    """A path as the shell would find it: ~ and $HOME made the home folder, a relative one taken from `here`, links
    followed: ("~/vault/a.md", any) -> the vault's real folder + "/a.md"; ("b.py", "/tmp") -> "/private/tmp/b.py"."""
    path = _unquoted(path).replace("\\ ", " ").replace("$HOME", "~").replace("${HOME}", "~")
    path = os.path.expanduser(path)
    if not os.path.isabs(path):
        path = os.path.join(here, path)
    return os.path.realpath(path)


def is_safe_place(path: str, safe_dirs: tuple[str, ...]) -> bool:
    """Whether a file written there needs no tap under a pass: /tmp, /dev/null, or inside one of `safe_dirs` (Odie's
    workspace, the user's vault). "/private/tmp/b.py" -> True; "<vault>/Stories/cast.md" -> True; "~/notes.txt" ->
    False."""
    places = [os.path.realpath(place) for place in (*_ALWAYS_SAFE, *safe_dirs)]
    return any(path == place or path.startswith(place.rstrip("/") + "/") for place in places)


def quoted(text: str) -> set[int]:
    """The positions inside quotes, where a ">" is words, not a redirect: 'echo "a > b" > f' -> the positions of
    a > b; a backslash-escaped quote inside double quotes stays inside."""
    inside = set()
    quote = ""
    escaped = False
    for i, char in enumerate(text):
        if quote:
            if escaped:
                escaped = False
            elif char == "\\" and quote == '"':
                escaped = True
            elif char == quote:
                quote = ""
                continue
            inside.add(i)
        elif char in "'\"":
            quote = char
    return inside


def segments(shell: str) -> list[str]:
    """The shell text cut at &&, ||, ; and line ends, but never inside quotes (an awk program's ";", an AppleScript
    over several lines): "cd /tmp && awk '{a; b}' f" -> ["cd /tmp ", " awk '{a; b}' f"]."""
    words = quoted(shell)
    out = []
    start = 0
    for cut in _SEGMENT.finditer(shell):
        if cut.start() in words:
            continue
        out.append(shell[start:cut.start()])
        start = cut.end()
    out.append(shell[start:])
    return out


def unsafe_write(shell: str, safe_dirs: tuple[str, ...], cwd: str | None) -> bool:
    """Whether the shell text writes (>, >>) anywhere but a safe place, following its `cd`s: `cd /tmp && cat > b.py`
    -> False; `echo hi > ~/notes.txt` -> True; `cat > notes.md` run in the workspace -> False; a ">" inside quotes
    is words -> False. A relative path with no folder known is taken from the home folder, where run_shell starts."""
    here = os.path.realpath(os.path.expanduser(cwd or "~"))
    for segment in segments(shell):
        moved = _CD.match(segment)
        if moved:
            here = _expanded(moved.group(1), here)
            continue
        words = quoted(segment)
        for redirect in _REDIRECT.finditer(segment):
            if redirect.start() in words:
                continue  # a ">" inside quotes: words (an arrow, a comparison), not a file
            target = redirect.group(1)
            if target.startswith("&"):
                continue  # 2>&1: one stream into another, no file
            if not is_safe_place(_expanded(target, here), safe_dirs):
                return True
    return False


def always_ask(command: str, safe_dirs: tuple[str, ...] = (), cwd: str | None = None) -> str | None:
    """Why this command must be tapped even under a grant, or None if a grant covers it. The rules read the shell
    text and any code fed to an interpreter (split_heredocs); file writes are judged from the shell text, with Odie's
    workspace and the vault (`safe_dirs`) as safe as /tmp. Examples: `ls ~/Downloads` -> None; `rm old.txt` ->
    "deletes or stops something"; `echo hi > /tmp/x` -> None; `echo hi > notes.txt` -> "writes a file outside /tmp";
    `python3 -c "import PIL"` -> None; `python3 -c "import shutil; shutil.rmtree(p)"` -> "deletes or stops
    something"."""
    shell, code = split_heredocs(command)
    looked_at = f"{shell}\n{code}"
    for why, rule in _RULES:
        if rule.search(looked_at):
            return why
    if unsafe_write(shell, safe_dirs, cwd):
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


def safe_places(store: Store) -> tuple[str, ...]:
    """Where a pass lets commands write besides /tmp: Odie's workspace, and the user's vault when one is set."""
    from odie import config
    from odie.vault import settings as vault_settings
    places = [str(config.settings.data_dir / "workspace")]
    vault = vault_settings.get(store).get("dir")
    if vault:
        places.append(str(vault))
    return tuple(places)


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

        why = always_ask(command, safe_dirs=safe_places(store), cwd=cwd)
        audit_args = {"command": command, "cwd": cwd}
        if why is not None:
            store.audit("agent", "shell_asked_under_grant", tool="run_shell", args=audit_args,
                        result_summary=why, session_id=session_id)
            return True

        store.audit("agent", "shell_auto_approved", tool="run_shell", args=audit_args,
                    result_summary="allowed for 30 min", session_id=session_id)
        return False
    return needs_tap
