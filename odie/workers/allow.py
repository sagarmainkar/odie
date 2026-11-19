"""What a Worker was refused and what the user's tap lets through on a retry ("Allow it and run again" on Pulse).

A Worker never asks mid-job: a step the Smart rules (or a Worker's own rules, below) would put on a card is refused
and noted as a need:
  {"tool": "run_shell", "command": "rm build.log", "cwd": "<its folder>", "why": "deletes or stops something"}
  {"tool": "GMAIL_SEND_EMAIL", "args": {...}, "why": APP_WHY}
The card lists every need in full, plain words first and the exact command after (odie.workers.cards). His tap lets
exactly those calls run on the job's next run: the same command in the same folder, the same app call with the same
arguments. Never a kind of command. Some needs are never offered at all, whatever the tap (NEVER): reading secrets,
Odie itself, his GitHub sign-in, another agent's approvals; the card says the job can't do those.
Whatever a tap allows, a Worker's commands still run in its sandbox (odie.workers.sandbox): writes only in its folder."""
from __future__ import annotations

import hashlib
import json
import re
import shlex
from pathlib import Path

from odie.workers.store import loads

APP_WHY = "sends, pays, publishes or removes something in an app"
ODIE_ITSELF = "runs Odie itself"
GITHUB = "uses your GitHub sign-in (gh) or pushes code"
INLINE = "runs code written into the command"
OTHER_APPS = "scripts other apps"
GIT_RUNS = "changes how git runs commands"
DOWNLOAD_RUN = "runs code it downloads"
CLIPBOARD = "reads or sets the clipboard"
APP_DATA = "reads apps' data (Library)"
EXTENSION = "installs software (an editor extension)"
OUTSIDE_RUN = "starts something outside its sandbox"
LOCAL_SERVICES = "talks to services on this computer"
HIDDEN_HOME = "reads hidden files in your home"
MIXED = "would mix the web with your apps or folders in one run"
# Needs a tap on a job card may never cover: only the user, in chat, with a full approval.
NEVER = frozenset({"reads secrets", "touches Odie's own files", ODIE_ITSELF, GITHUB,
                   "switches off another agent's approvals", "reaches a hidden file by a pattern", OTHER_APPS, GIT_RUNS,
                   DOWNLOAD_RUN, CLIPBOARD, APP_DATA, EXTENSION, OUTSIDE_RUN, LOCAL_SERVICES, HIDDEN_HOME, MIXED})
PLAIN = {
    "deletes or stops something": "Delete or stop something",
    "writes a file outside /tmp": "Write a file outside its folder",
    "replaces a file": "Replace a file",
    "edits files in place": "Edit files in place",
    "writes a file from code": "Write a file from code",
    "installs software (runs its install scripts)": "Install software",
    "sends data out": "Send data off this computer",
    "runs text as commands": "Run text as commands",
    "sets something to run later or at login": "Set something to run later or at login",
    "reads secrets": "Read secrets",
    "touches Odie's own files": "Touch Odie's own files",
    ODIE_ITSELF: "Run Odie itself",
    GITHUB: "Use your GitHub sign-in or push code",
    INLINE: "Run code written into the command",
    OTHER_APPS: "Script other apps",
    GIT_RUNS: "Change how git runs commands",
    DOWNLOAD_RUN: "Run code it downloads",
    CLIPBOARD: "Read or set the clipboard",
    APP_DATA: "Read apps' data in Library",
    EXTENSION: "Install an editor extension",
    OUTSIDE_RUN: "Start something outside its sandbox",
    LOCAL_SERVICES: "Talk to services on this computer",
    HIDDEN_HOME: "Read hidden files in your home",
}

__all__ = ["APP_WHY", "GITHUB", "NEVER", "ODIE_ITSELF", "covers", "loads", "need_for_app", "need_for_shell",
           "offerable", "plain", "uncovered", "worker_reasons"]

# A command word that starts a piece of a shell line: at the start, or after ; & | ( ` $( or a newline, past any
# VAR=value settings and the wrappers that only run what follows.
_STARTS = r"(?:^|[;&|(`\n]|\$\()\s*(?:\w+=\S*\s+)*(?:(?:sudo|env|exec|command|nohup|time|nice|xargs)\s+(?:-\S+\s+)*)*"
_ODIE = re.compile(_STARTS + r"(?:\S*/)?odie(?:\s|$|;|&|\|)|\bpython[\d.]*\s+(?:-\S+\s+)*-m\s*odie\b|\bodie\.cli\b")
_GH = re.compile(_STARTS + r"(?:\S*/)?gh(?:\s|$|;|&|\|)")
_GIT_OUT = re.compile(r"\bgit\b[^;&|\n]*\s(?:push|send-email|request-pull)\b|\bgit\b[^;&|\n]*\bremote\s+(?:add|set-url)\b")
# What the shared text rules let pass and a Worker refuses (second review, 19 Nov 2026), each with its reason.
_WORKER_RULES = (
    (INLINE, re.compile(r"\b(perl|ruby)\b[^;&|\n]*\s-[a-zA-Z]*[eE]\b")),
    (OTHER_APPS, re.compile(r"\bosascript\b")),
    (GIT_RUNS, re.compile(r"\bgit\b[^;&|\n]*(-c\s*core\.(pager|sshCommand|fsmonitor|hooksPath|editor|askPass)|"
                          r"\bconfig\b[^;&|\n]*(--global|--system|core\.(hooksPath|fsmonitor|sshCommand|pager)))", re.I)),
    (DOWNLOAD_RUN, re.compile(r"\b(curl|wget)\b[\s\S]*(\|\s*(sudo\s+)?(sh|bash|zsh|python3?|node|perl|ruby)\b|"
                              r"(&&|;)\s*(sh|bash|zsh|source|\.|python3?)\s|\bchmod\s+\+?[0-7]*x)")),
    (CLIPBOARD, re.compile(r"\bpb(paste|copy)\b")),
    (APP_DATA, re.compile(r"(~|\$HOME|\$\{HOME\}|/Users/[^/\s]+)/Library/")),
    (EXTENSION, re.compile(r"\bcode\b[^;&|\n]*--install-extension\b")),
    (OUTSIDE_RUN, re.compile(_STARTS + r"(?:\S*/)?(open|launchctl|crontab|at|batch|security|defaults|tmux|screen|"
                             r"nohup\s+open)(?:\s|$)")),
    (LOCAL_SERVICES, re.compile(r"\b(localhost|127\.0\.0\.1|0\.0\.0\.0|\[::1\])\b|::1\b")),
)


ODIE_FILES = "touches Odie's own files"
_PATH_END = r"(?=$|[\s'\";&|)`]|/)"


def path_forms(path: Path) -> list[str]:
    """The ways a command may write a path: in full, and with ~, $HOME or ${HOME} for the home."""
    full = str(path)
    forms = [full]
    home = str(Path.home())
    if full.startswith(home + "/"):
        rest = full[len(home):]
        forms += ["~" + rest, "$HOME" + rest, "${HOME}" + rest]
    return forms


def without_own_folder(command: str, folder: Path | None) -> str:
    """The command with the job's own folder (exactly it, or a path inside it with no "..") written as JOBDIR, so the
    rules about the home's hidden places and Odie's folders never read the Worker naming its own folder (found live,
    19 Nov 2026: on a real install it sits at ~/.odie/data/workspace/jobs/<name>).
      `cd /Users/me/.odie/data/workspace/jobs/primes-7180b6 && python3 x.py` -> `cd JOBDIR && python3 x.py`
      `ls /Users/me/.odie/data/workspace/jobs/primes-7180b6/..` -> unchanged (it leaves the folder)
      `ls /Users/me/.odie/data/workspace/jobs/other-job` -> unchanged (another job's)"""
    if folder is None:
        return command
    out = command
    for form in sorted(set(path_forms(Path(folder)) + path_forms(Path(folder).resolve())), key=len, reverse=True):
        pattern = re.compile(re.escape(form) + _PATH_END + r"(/[^\s'\";&|)`]*)?")

        def masked(match: re.Match) -> str:
            rest = match.group(1) or ""
            if ".." in rest.split("/"):
                return match.group(0)
            return "JOBDIR" + rest
        out = pattern.sub(masked, out)
    return out


def odie_places_rule() -> re.Pattern | None:
    """A rule matching any path inside Odie's own folders (its home, data and settings, in every form)."""
    from odie.workers.sandbox import odie_places
    forms = [f for place in odie_places() for f in path_forms(Path(place))]
    forms += ["~/.odie", "$HOME/.odie", "${HOME}/.odie"]
    if not forms:
        return None
    return re.compile("|".join(re.escape(f) + _PATH_END for f in sorted(set(forms), key=len, reverse=True)))


def hidden_home_rule() -> re.Pattern:
    """A rule matching a hidden place in the home, written in any form (the real home, ~, $HOME, /Users/<name>)."""
    home = re.escape(str(Path.home()))
    return re.compile(rf"(~|\$HOME|\$\{{HOME\}}|/Users/[^/\s]+|{home})/\.")


def worker_reasons(command: str, own_folder: Path | None = None) -> list[str]:
    """What a Worker refuses on top of the Smart rules, read from the command as written and with quotes squeezed out:
      `odie chat hi`, `~/.local/bin/odie show x`, `python -m odie.cli chat`, `echo && odie chat` -> [ODIE_ITSELF]
      `gh pr merge 3`, `gh auth token`, `/opt/homebrew/bin/gh api …`                           -> [GITHUB]
      `git push origin main`, `git -C repo push`                                                -> [GITHUB]
      `perl -e 'unlink …'`, `ruby -e …`                                                          -> [INLINE]
      `osascript run.scpt`                                                                       -> [OTHER_APPS]
      `git -c core.pager='sh run.sh' log`, `git config --global …`                               -> [GIT_RUNS]
      `curl -o i.sh … && sh i.sh`, `curl … | sh`                                                 -> [DOWNLOAD_RUN]
      `pbpaste`, `sqlite3 ~/Library/Messages/chat.db`, `code --install-extension x`              -> their reasons
      `open -a Terminal x.command`, `crontab -l`                                                 -> [OUTSIDE_RUN]
      `curl http://127.0.0.1:8000/api/approvals`                                                 -> [LOCAL_SERVICES]
      `cat ~/.config/mail-app/client.json`                                                      -> [HIDDEN_HOME]
      `python3 fib.py`, `git log`, `ls ~/odie-notes`                                            -> []"""
    from odie.agent.shell_grant import squeezed
    out = []
    command = without_own_folder(command, own_folder)
    path_rules = [(HIDDEN_HOME, hidden_home_rule())]
    odie_rule = odie_places_rule()
    if odie_rule is not None:
        path_rules.append((ODIE_FILES, odie_rule))
    for text in (command, squeezed(command)):
        for why, rule in path_rules:
            if rule.search(text) and why not in out:
                out.append(why)
        if _ODIE.search(text) and ODIE_ITSELF not in out:
            out.append(ODIE_ITSELF)
        if (_GH.search(text) or _GIT_OUT.search(text)) and GITHUB not in out:
            out.append(GITHUB)
        for why, rule in _WORKER_RULES:
            if rule.search(text) and why not in out:
                out.append(why)
    return out


def need_for_shell(command: str, why: str, cwd: str | None) -> dict:
    return {"tool": "run_shell", "command": command, "cwd": cwd or "", "why": why}


def need_for_app(name: str, args: dict | None) -> dict:
    return {"tool": name, "args": dict(args or {}), "why": APP_WHY}


def offerable(need: dict) -> bool:
    """Whether a job card may offer to allow this need: "deletes or stops something" -> True; "sends data out" ->
    True; an app's send -> True; "reads secrets", Odie itself, GitHub -> False (never from a job card)."""
    return need.get("why") not in NEVER


def _same_args(a: dict | None, b: dict | None) -> bool:
    return json.dumps(a or {}, sort_keys=True, default=str) == json.dumps(b or {}, sort_keys=True, default=str)


def files_named(command: str, cwd: str | None, folder: Path) -> dict[str, str]:
    """The files in the job's folder a command reads or runs, with a hash of each, so a tap allows the command only
    with those files as they were (security review, 19 Nov 2026): every word that names a file there (`sh run.sh`,
    `curl -d @report.txt`), and the Makefile for `make`. {"run.sh": "<sha256>"}; a command naming none -> {}."""
    from odie.workers.files import open_inside
    import os
    folder = Path(folder).resolve()
    here = Path(cwd or folder)
    try:
        words = shlex.split(command)
    except ValueError:
        words = command.split()
    names = [w.lstrip("@") for w in words]
    if words and Path(words[0]).name in ("make", "gmake"):
        names += ["Makefile", "makefile", "GNUmakefile"]
    out = {}
    seen = set()
    for name in names:
        path = Path(name) if Path(name).is_absolute() else here / name
        try:
            rel = str(path.resolve().relative_to(folder))
        except (ValueError, OSError):
            continue
        try:
            same_file = (path.stat().st_dev, path.stat().st_ino)  # Makefile and makefile on a case-insensitive disk
        except OSError:
            continue
        if same_file in seen:
            continue
        seen.add(same_file)
        try:
            fd = open_inside(folder, rel, os.O_RDONLY)
        except (OSError, ValueError):
            continue
        with os.fdopen(fd, "rb") as f:
            out[rel] = hashlib.sha256(f.read()).hexdigest()
    return out


def _same_files(allowed_need: dict, folder: Path | None) -> bool:
    """Whether the files the tap saw (allowed_need["files"]) are still exactly as they were: none bound -> True."""
    bound = allowed_need.get("files") or {}
    if not bound:
        return True
    if folder is None:
        return False
    now = files_named(allowed_need.get("command", ""), allowed_need.get("cwd"), folder)
    return all(now.get(name) == digest for name, digest in bound.items())


def _matches(allowed_need: dict, tool_name: str, args: dict, why: str, folder: Path | None = None) -> bool:
    """Whether one allowed need is this very call: the same tool, the same reason, and for the shell the same command
    in the same folder with the files it names unchanged since the tap; for an app the same arguments. A need that may
    never be offered never matches."""
    if allowed_need.get("tool") != tool_name or allowed_need.get("why") != why or not offerable(allowed_need):
        return False
    if tool_name == "run_shell":
        same_command = allowed_need.get("command") == args.get("command")
        same_folder = (allowed_need.get("cwd") or "") == (args.get("cwd") or "")
        return same_command and same_folder and _same_files(allowed_need, folder)
    return _same_args(allowed_need.get("args"), args)


def uncovered(allowed: list[dict], tool_name: str, args: dict | None, reasons: list[str],
              folder: Path | None = None) -> list[str]:
    """The reasons this call would ask for that his tap did not allow, in order ([] = it may run). A tap allows exact
    calls only, never a kind (folder /w/jobs/a):
      allowed `rm build.log` in /w/jobs/a, now the same in the same folder  -> []
      allowed `rm build.log`, now `rm -rf ~/Documents`                      -> ["deletes or stops something"]
      allowed `rm build.log` in /w/jobs/a, now the same in ~                -> ["deletes or stops something"]
      allowed GMAIL_SEND_EMAIL to asha@…, now the same args                 -> []; to someone else -> [APP_WHY]
      allowed `sh run.sh`, run.sh changed since the tap                     -> ["deletes or stops something"]
      anything that "reads secrets", whatever a need says                   -> ["reads secrets"] (never allowed)"""
    args = args or {}
    return [why for why in reasons if not any(_matches(a, tool_name, args, why, folder) for a in allowed)]


def covers(allowed: list[dict], tool_name: str, args: dict | None, reasons: list[str], folder: Path | None = None) -> bool:
    """Whether what his tap allowed lets this call run: every reason it would ask for is covered (see uncovered)."""
    return not uncovered(allowed, tool_name, args, reasons, folder)


def bind_files(needs: list[dict], folder: Path) -> list[dict]:
    """The needs his tap allows, each shell one bound to the files it names as they are at the tap."""
    out = []
    for need in needs:
        bound = dict(need)
        if need.get("tool") == "run_shell":
            bound["files"] = files_named(need.get("command", ""), need.get("cwd"), folder)
        out.append(bound)
    return out


def visible(text: str) -> str:
    """Text with every invisible or direction-changing character written out as an escape, so a card can't show one
    recipient while the tap allows another (third review, 19 Nov 2026): Unicode's format characters (right-to-left
    overrides U+202A-202E, isolates U+2066-2069, zero-width U+200B-200F, U+FEFF…) and control characters but tab and
    newline. "asha@example.com\u202emoc" -> "asha@example.com\\u202emoc"; plain text -> unchanged."""
    import unicodedata
    out = []
    for ch in text:
        category = unicodedata.category(ch)
        hidden = category == "Cf" or (category == "Cc" and ch not in "\n\t")
        if hidden:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    return "".join(out)


def needs_hash(needs: list[dict]) -> str:
    """A short hash of exactly the needs a card shows (with invisible characters written out, as shown): the tap
    sends it back, and the server allows nothing if the job's needs changed since."""
    text = visible(json.dumps(needs, sort_keys=True, default=str, ensure_ascii=False))
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def plain(need: dict) -> str:
    """A need in plain words, for the card's first line: "Delete or stop something"; an app's: "Send something from an
    app (GMAIL_SEND_EMAIL)"; a reason this table doesn't know: the reason itself, capitalised."""
    if need.get("tool") != "run_shell":
        return f"Send something from an app ({need.get('tool', '')})"
    why = need.get("why", "")
    words = PLAIN.get(why)
    if words is None:
        words = why[:1].upper() + why[1:]
    return words


FIRST_FIELDS = ("to", "cc", "bcc", "recipients", "recipient", "attachments", "attachment", "files", "url", "amount")


def raw(need: dict) -> str:
    """The exact call, whole, for the card: the command; or the app call with every argument, who it goes to and what
    it attaches first (FIRST_FIELDS), never cut."""
    if need.get("tool") == "run_shell":
        return visible(need.get("command", ""))
    args = need.get("args") or {}
    ordered = {k: args[k] for k in FIRST_FIELDS if k in args}
    ordered.update({k: v for k, v in args.items() if k not in ordered})
    return visible(f"{need.get('tool', '')} {json.dumps(ordered, ensure_ascii=False)}")


def line(need: dict) -> str:
    """A need in words for the chat's report: "Delete or stop something: `rm build.log`"."""
    return f"{plain(need)}: `{raw(need)}`"
