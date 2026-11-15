"""Talking to the running Odie from the terminal, so another program (Claude Code, Hermes, a script) can use it:

    odie chat "what's on today?"        send to today's chat and print the reply as it comes
    odie chat --thread <id> "and then?" continue a thread;  --new starts a new chat first;  "-" reads stdin
    odie threads [-q words]             the chat threads, pinned first, then the most recent
    odie show <id> [-n 20]              a thread's messages
    --json                              one JSON answer for a program; chat --events prints every event as a line

It goes through the server's own routes (/api/chat, /api/threads), so every guard, tap and memory rule still applies.
Nothing is approved from here: a turn that needs a tap says so and ends with exit code 3, and the tap is made in the
app. Only this Mac: it calls 127.0.0.1, and its device key lives in Odie's data folder.

The key: with pairing on, the first command pairs this terminal as a device ("Terminal (odie chat)") and keeps the key
in <ODIE_HOME>/data/terminal.key (readable by this user only). Removing that device in Settings → Devices cuts it off;
the command then says how to pair it again. Standard library only, like odie.cli."""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Iterator, Mapping
from datetime import datetime
from typing import TYPE_CHECKING, Any, TextIO

if TYPE_CHECKING:
    from odie.cli import Install

NEEDS_TAP = 3  # the exit code of a chat turn that stopped at a card: tap it in the app
CHAT_TIMEOUT = 600.0  # seconds a turn may take (a long research turn), the same as a patient person waiting


class ApiError(Exception):
    """A call that didn't work, with the line to show the person."""


class Refused(ApiError):
    """Odie answered 401: this terminal isn't (or is no longer) a paired device."""


# ── the key ──

def key_file(inst: Install):
    return inst.home / "data" / "terminal.key"


def read_key(inst: Install) -> str | None:
    path = key_file(inst)
    if not path.exists():
        return None
    return path.read_text().strip() or None


def pair_terminal(inst: Install) -> str:
    """A new device key for this terminal, saved where only this user can read it."""
    from odie import devices
    from odie.store.db import Store
    store = Store(inst.database)
    try:
        key = devices.add_terminal(store)
    finally:
        store.close()
    path = key_file(inst)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(key + "\n")
    return key


def key_for(inst: Install, environ: Mapping[str, str], err: TextIO) -> str | None:
    """The key to send, or None when none is needed. With pairing on and no key saved yet, this terminal is paired now.
      pairing off                        -> None (Odie lets every caller in)
      pairing on, terminal.key saved     -> that key
      pairing on, nothing saved          -> a new key, saved, and one line on stderr saying so"""
    from odie.cli import pairing_asked_for
    saved = read_key(inst)
    if saved:
        return saved
    if not pairing_asked_for(inst, environ):
        return None
    if not inst.database.exists():
        raise ApiError("Odie hasn't started yet: odie start first.")
    key = pair_terminal(inst)
    err.write("Paired this terminal with Odie (Settings → Devices shows it as \"Terminal (odie chat)\").\n")
    return key


# ── HTTP ──

class Api:
    """Odie's routes on this Mac, with the terminal's key as the device cookie. Tests pass a fake with the same two
    methods."""

    def __init__(self, base: str, key: str | None):
        self.base = base
        self.key = key

    def _request(self, path: str, body: dict | None) -> urllib.request.Request:
        headers = {"Accept": "application/json"}
        if self.key:
            from odie import devices
            headers["Cookie"] = f"{devices.COOKIE}={self.key}"
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        return urllib.request.Request(self.base + path, data=data, headers=headers)

    def _open(self, req: urllib.request.Request, timeout: float):
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as e:
            if e.code == 401:
                raise Refused("Odie refused this terminal.") from e
            detail = _detail(e.read().decode("utf-8", "replace"))
            raise ApiError(f"Odie answered {e.code}: {detail}") from e
        except (urllib.error.URLError, OSError) as e:
            raise ApiError(f"Odie isn't answering at {self.base}: is it running? (odie status)") from e

    def get(self, path: str) -> Any:
        with self._open(self._request(path, None), timeout=30) as r:
            return json.loads(r.read().decode("utf-8", "replace"))

    def post(self, path: str, body: dict) -> Any:
        with self._open(self._request(path, body), timeout=30) as r:
            return json.loads(r.read().decode("utf-8", "replace"))

    def stream(self, path: str, body: dict) -> Iterator[dict]:
        """The events of a server-sent stream, one dict each. Lines that aren't `data:` (pings, blank lines) are skipped."""
        with self._open(self._request(path, body), timeout=CHAT_TIMEOUT) as r:
            for raw in r:
                line = raw.decode("utf-8", "replace").rstrip("\r\n")
                if not line.startswith("data:"):
                    continue
                payload = line[len("data:"):].strip()
                if payload:
                    yield json.loads(payload)


def _detail(body: str) -> str:
    """FastAPI's {"detail": "..."} as its words, else the body itself: '{"detail": "not a chat thread"}' -> 'not a chat
    thread'."""
    try:
        data = json.loads(body)
    except ValueError:
        return body.strip()[:200] or "no details"
    if isinstance(data, dict) and isinstance(data.get("detail"), str):
        return data["detail"]
    return body.strip()[:200]


# ── odie chat ──

def message_text(given: str, stdin: TextIO) -> str:
    """The message: the words given, or stdin when they are "-". "hi" -> "hi"; "-" with "long\\ntext" piped -> that text."""
    if given == "-":
        return stdin.read().strip()
    return given.strip()


class Turn:
    """What a chat turn printed and found, gathered from its events."""

    def __init__(self) -> None:
        self.thread: str | None = None
        self.text = ""
        self.taps: list[str] = []
        self.errors: list[str] = []
        self.streamed = ""  # words printed from tokens since the last whole text

    def needs_tap(self) -> bool:
        """Whether the turn stopped at a card waiting for the person: any approval event came.
          a reply only -> False;  an approval for "Send mail to the bank" -> True (exit 3: tap it in the app)"""
        return bool(self.taps)


def show_event(e: dict, turn: Turn, out: TextIO, err: TextIO) -> None:
    """One event for a person: the words as they come on stdout, tools and cards on stderr."""
    kind = e.get("type")
    if e.get("session_id"):
        turn.thread = e["session_id"]
    if kind == "token":
        out.write(e.get("text", ""))
        out.flush()
        turn.streamed += e.get("text", "")
    elif kind == "text":
        if not turn.streamed:  # the model didn't stream this part: print it whole
            out.write(e.get("text", ""))
        out.write("\n")
        out.flush()
        turn.streamed = ""
    elif kind == "message":
        out.write(f"{e.get('text', '')}\n")
    elif kind == "tool_start":
        err.write(f"  · {e.get('tool', '')}\n")
    elif kind == "approval":
        err.write(f"  ⏸ needs your tap: {e.get('summary', '')} (tap it in the Odie app)\n")
    elif kind == "error":
        err.write(f"  ! {e.get('text') or e.get('error') or e}\n")


def note_event(e: dict, turn: Turn) -> None:
    """What --json reports, gathered from one event."""
    kind = e.get("type")
    if e.get("session_id"):
        turn.thread = e["session_id"]
    if kind == "approval":
        turn.taps.append(e.get("summary", ""))
    elif kind == "error":
        turn.errors.append(str(e.get("text") or e.get("error") or e))
    elif kind == "done":
        turn.text = e.get("text", "")


def cmd_chat(api: Api, text: str, thread: str | None, new: bool, mode: str, out: TextIO, err: TextIO) -> int:
    """mode: "text" (a person), "json" (one object at the end), "events" (every event, one JSON line each)."""
    if not text:
        err.write("Nothing to send: give the message, or \"-\" to read it from stdin.\n")
        return 2
    if new:
        thread = api.post("/api/chat/new", {})["session_id"]
    body: dict[str, Any] = {"text": text, "via": "terminal"}
    if thread:
        body["session_id"] = thread
    turn = Turn()
    turn.thread = thread
    for e in api.stream("/api/chat", body):
        note_event(e, turn)
        if mode == "events":
            out.write(json.dumps(e) + "\n")
            out.flush()
        elif mode == "text":
            show_event(e, turn, out, err)
    if mode == "json":
        answer = {"thread": turn.thread, "text": turn.text, "needs_tap": turn.taps, "errors": turn.errors}
        out.write(json.dumps(answer, ensure_ascii=False) + "\n")
    if mode == "text" and turn.thread:
        err.write(f"(thread {turn.thread})\n")
    if turn.needs_tap():
        return NEEDS_TAP
    if turn.errors:
        return 1
    return 0


# ── odie threads / odie show ──

def cmd_threads(api: Api, q: str | None, as_json: bool, out: TextIO) -> int:
    path = "/api/threads"
    if q:
        path += "?" + urllib.parse.urlencode({"q": q})
    threads = api.get(path)["threads"]
    if as_json:
        out.write(json.dumps(threads, ensure_ascii=False) + "\n")
        return 0
    if not threads:
        out.write("No threads yet.\n")
        return 0
    for t in threads:
        pin = "★" if t.get("pinned") else " "
        out.write(f"{pin} {t['id']:<22} {t.get('messages', 0):>4} msgs  {t.get('title', '')}\n")
    return 0


def clock(ts: float | None) -> str:
    """A message's time as the person reads it: 1763190000.0 -> "15 Nov 12:30" (local time); none -> ""."""
    if not ts:
        return ""
    return datetime.fromtimestamp(ts).strftime("%-d %b %H:%M")


def who_said(item: dict) -> str:
    """The heading of a message: "You", "You (via Terminal)", "Odie", or "Card" for an approval."""
    role = item.get("role")
    if role == "user":
        if item.get("via") == "terminal":
            return "You (via Terminal)"
        return "You"
    if role == "approval":
        return "Card"
    return "Odie"


def cmd_show(api: Api, thread: str, limit: int | None, as_json: bool, out: TextIO) -> int:
    path = f"/api/threads/{urllib.parse.quote(thread, safe='')}/history"
    if limit:
        path += f"?limit={limit}"
    items = api.get(path)["items"]
    if as_json:
        out.write(json.dumps(items, ensure_ascii=False) + "\n")
        return 0
    for item in items:
        out.write(f"── {who_said(item)}  {clock(item.get('ts'))}\n")
        if item.get("role") == "approval":
            card = item.get("approval") or {}
            out.write(f"{card.get('summary', '')} [{card.get('status', '')}]\n\n")
            continue
        steps = item.get("steps") or []
        out.writelines(f"  · {step.get('name', '')}\n" for step in steps)
        if item.get("text"):
            out.write(item["text"].rstrip() + "\n")
        out.write("\n")
    return 0


# ── the entry point odie.cli calls ──

def run(inst: Install, environ: Mapping[str, str], args: Any, out: TextIO = sys.stdout, err: TextIO = sys.stderr,
        stdin: TextIO = sys.stdin, api: Api | None = None) -> int:
    """odie chat / threads / show. A refused key says how to pair again; any other failure says what went wrong."""
    try:
        if api is None:
            api = Api(inst.api, key_for(inst, environ, err))
        if args.command == "chat":
            mode = "text"
            if args.json:
                mode = "json"
            if args.events:
                mode = "events"
            return cmd_chat(api, message_text(args.text, stdin), args.thread, args.new, mode, out, err)
        if args.command == "threads":
            return cmd_threads(api, args.q, args.json, out)
        return cmd_show(api, args.thread, args.lines, args.json, out)
    except Refused:
        err.write("Odie doesn't know this terminal (was it removed in Settings → Devices?). To pair it again:\n"
                  f"  rm {key_file(inst)}\nthen run the command again.\n")
        return 1
    except ApiError as e:
        err.write(f"{e}\n")
        return 1
