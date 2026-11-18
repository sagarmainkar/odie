"""What a Worker was refused and what the user's tap lets through on a retry ("Allow it and run again" on Pulse).

A Worker never asks mid-job: a step the Smart rules would put on a card is refused, and noted as a need:
  {"tool": "run_shell", "command": "rm old.txt", "why": "deletes or stops something"}
  {"tool": "GMAIL_SEND_EMAIL", "args": {...}, "why": APP_WHY}
His tap copies the job's needs into what the next run may do, and nothing else. A kind of command a chat pass may
cover (odie.agent.shell_grant.PASSABLE: deletes, writes, edits in place...) is allowed as a kind for that run; every
other need (installs, secrets, sending out, Odie itself, running text as commands, an app's send) is allowed only as
that exact call, the one he saw on the card."""
from __future__ import annotations

import json

from odie.workers.store import loads

APP_WHY = "sends, pays, publishes or removes something in an app"

__all__ = ["APP_WHY", "covers", "line", "loads", "need_for_shell", "need_for_app"]


def need_for_shell(command: str, why: str) -> dict:
    return {"tool": "run_shell", "command": command, "why": why}


def need_for_app(name: str, args: dict | None) -> dict:
    return {"tool": name, "args": dict(args or {}), "why": APP_WHY}


def _same_args(a: dict | None, b: dict | None) -> bool:
    return json.dumps(a or {}, sort_keys=True, default=str) == json.dumps(b or {}, sort_keys=True, default=str)


def covers(allowed: list[dict], tool_name: str, args: dict | None, reasons: list[str]) -> bool:
    """Whether what his tap allowed lets this call run. Every reason it would ask for must be covered:
      allowed deletes (`rm old.txt`), now `rm -f build.log`           -> True  (deletes are a kind a pass may cover)
      allowed deletes, now `cat ~/.env` (reads secrets)               -> False
      allowed `npm install left-pad`, now the same command            -> True  (that exact call)
      allowed `npm install left-pad`, now `npm install evil`          -> False (installs: only the exact call)
      allowed GMAIL_SEND_EMAIL to asha@…, now the same args           -> True; to someone else -> False
      nothing allowed                                                 -> False"""
    from odie.agent.shell_grant import PASSABLE
    if not reasons:
        return True
    args = args or {}
    for why in reasons:
        covered = False
        for a in allowed:
            if a.get("tool") != tool_name or a.get("why") != why:
                continue
            if tool_name == "run_shell":
                same_command = a.get("command") == args.get("command")
                covered = why in PASSABLE or same_command
            else:
                covered = _same_args(a.get("args"), args)
            if covered:
                break
        if not covered:
            return False
    return True


def line(need: dict) -> str:
    """A need in words for the report and the card: "`rm old.txt` (deletes or stops something)";
    "GMAIL_SEND_EMAIL (sends, pays, publishes or removes something in an app)"."""
    if need.get("tool") == "run_shell":
        return f"`{need.get('command', '')}` ({need.get('why', '')})"
    return f"{need.get('tool', '')} ({need.get('why', '')})"
