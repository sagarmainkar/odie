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

import json
import re

from odie.workers.store import loads

APP_WHY = "sends, pays, publishes or removes something in an app"
ODIE_ITSELF = "runs Odie itself"
GITHUB = "uses your GitHub sign-in (gh) or pushes code"
# Needs a tap on a job card may never cover: only the user, in chat, with a full approval.
NEVER = frozenset({"reads secrets", "touches Odie's own files", ODIE_ITSELF, GITHUB,
                   "switches off another agent's approvals", "reaches a hidden file by a pattern"})
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
}

__all__ = ["APP_WHY", "GITHUB", "NEVER", "ODIE_ITSELF", "covers", "loads", "need_for_app", "need_for_shell",
           "offerable", "plain", "uncovered", "worker_reasons"]

# A command word that starts a piece of a shell line: at the start, or after ; & | ( ` $( or a newline, past any
# VAR=value settings and the wrappers that only run what follows.
_STARTS = r"(?:^|[;&|(`\n]|\$\()\s*(?:\w+=\S*\s+)*(?:(?:sudo|env|exec|command|nohup|time|nice|xargs)\s+(?:-\S+\s+)*)*"
_ODIE = re.compile(_STARTS + r"(?:\S*/)?odie(?:\s|$|;|&|\|)|\bpython[\d.]*\s+(?:-\S+\s+)*-m\s*odie\b|\bodie\.cli\b")
_GH = re.compile(_STARTS + r"(?:\S*/)?gh(?:\s|$|;|&|\|)")
_GIT_OUT = re.compile(r"\bgit\b[^;&|\n]*\s(?:push|send-email|request-pull)\b|\bgit\b[^;&|\n]*\bremote\s+(?:add|set-url)\b")


def worker_reasons(command: str) -> list[str]:
    """What a Worker refuses on top of the Smart rules, read from the command as written and with quotes squeezed out:
      `odie chat hi`, `~/.local/bin/odie show x`, `python -m odie.cli chat`, `echo && odie chat` -> [ODIE_ITSELF]
      `gh pr merge 3`, `gh auth token`, `/opt/homebrew/bin/gh api …`                           -> [GITHUB]
      `git push origin main`, `git -C repo push`                                                -> [GITHUB]
      `python3 fib.py`, `git log`, `ls ~/odie-notes`                                            -> []"""
    from odie.agent.shell_grant import squeezed
    out = []
    for text in (command, squeezed(command)):
        if _ODIE.search(text) and ODIE_ITSELF not in out:
            out.append(ODIE_ITSELF)
        if (_GH.search(text) or _GIT_OUT.search(text)) and GITHUB not in out:
            out.append(GITHUB)
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


def _matches(allowed_need: dict, tool_name: str, args: dict, why: str) -> bool:
    """Whether one allowed need is this very call: the same tool, the same reason, and for the shell the same command
    in the same folder, for an app the same arguments. A need that may never be offered never matches."""
    if allowed_need.get("tool") != tool_name or allowed_need.get("why") != why or not offerable(allowed_need):
        return False
    if tool_name == "run_shell":
        same_command = allowed_need.get("command") == args.get("command")
        same_folder = (allowed_need.get("cwd") or "") == (args.get("cwd") or "")
        return same_command and same_folder
    return _same_args(allowed_need.get("args"), args)


def uncovered(allowed: list[dict], tool_name: str, args: dict | None, reasons: list[str]) -> list[str]:
    """The reasons this call would ask for that his tap did not allow, in order ([] = it may run). A tap allows exact
    calls only, never a kind (folder /w/jobs/a):
      allowed `rm build.log` in /w/jobs/a, now the same in the same folder  -> []
      allowed `rm build.log`, now `rm -rf ~/Documents`                      -> ["deletes or stops something"]
      allowed `rm build.log` in /w/jobs/a, now the same in ~                -> ["deletes or stops something"]
      allowed GMAIL_SEND_EMAIL to asha@…, now the same args                 -> []; to someone else -> [APP_WHY]
      anything that "reads secrets", whatever a need says                   -> ["reads secrets"] (never allowed)"""
    args = args or {}
    return [why for why in reasons if not any(_matches(a, tool_name, args, why) for a in allowed)]


def covers(allowed: list[dict], tool_name: str, args: dict | None, reasons: list[str]) -> bool:
    """Whether what his tap allowed lets this call run: every reason it would ask for is covered (see uncovered)."""
    return not uncovered(allowed, tool_name, args, reasons)


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


def raw(need: dict) -> str:
    """The exact call, for the card's second line: the command, or the app call with its arguments."""
    if need.get("tool") == "run_shell":
        return need.get("command", "")
    return f"{need.get('tool', '')} {json.dumps(need.get('args') or {}, ensure_ascii=False)[:300]}"


def line(need: dict) -> str:
    """A need in words for the chat's report: "Delete or stop something: `rm build.log`"."""
    return f"{plain(need)}: `{raw(need)}`"
