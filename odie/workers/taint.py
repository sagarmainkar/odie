"""Which chats have read outside text, for the life of the chat (second security review, 19 Nov 2026). Once mail,
messages, a web page or an app's answer has entered a chat, any brief written there may carry its words: every job
started from that chat afterwards is tainted (no web, no apps, no network), not only one started in the same turn.
A new chat starts clean. Kept in the settings under the chat's id, so erasing a thread forgets it with the thread.

Mail and messages are noted as the chat already notes them (odie.signin.guard.remember_read: "your mail", "your
messages"); the web and the apps are noted here, from the chat's after-tool callback (odie.agent.callbacks)."""
from __future__ import annotations

import re

KEY = "chat.outside."  # + the chat's session id: ["web pages", "an app"]
WEB_TOOLS = frozenset({"web_fetch", "web_search"})
MAIL = "mail"
WEB = "web pages"
APP = "an app"
JOB = "a job's report"
# A shell command that reaches the network brings outside text in: an address, a download tool, git's network verbs.
NETWORK_COMMAND = re.compile(r"https?://|\b(curl|wget|xh|https?|httpie|lynx|w3m|aria2c|nc|ncat|telnet)\b|"
                             r"\bgit\b[^;&|\n]*\b(clone|fetch|pull|ls-remote)\b", re.I)


def label_of_call(tool_name: str, server: str | None, args: dict | None = None) -> str:
    """What outside text a tool call brought into the chat, or "": web_fetch, web_search, browser_* -> WEB; the
    chat's own shell reaching the network (`curl https://…`, `git clone …`) -> WEB; a connected app's tool (it has a
    server) -> APP; anything else (a local command, notes, memory) -> ""."""
    if tool_name in WEB_TOOLS or tool_name.startswith("browser_"):
        return WEB
    if tool_name == "run_shell" and NETWORK_COMMAND.search(str((args or {}).get("command") or "")):
        return WEB
    if server:
        return APP
    return ""


def note_call(store, session_id: str | None, tool_name: str, server: str | None, args: dict | None = None) -> None:
    """Notes that this chat has now read outside text, when the call brought some."""
    note(store, session_id, label_of_call(tool_name, server, args))


def note(store, session_id: str | None, label: str) -> None:
    """Notes that this chat now holds outside text of this kind (a job's report posted into it: JOB)."""
    if store is None or not session_id or not label:
        return
    kept = set(store.get_setting(KEY + session_id) or [])
    if label not in kept:
        store.set_setting(KEY + session_id, sorted(kept | {label}))


def of_chat(store, session_id: str | None) -> str:
    """The outside text this chat has read at any point, as a job's taint, or "" when none: mail or messages first,
    then web pages, then an app.
      read a mail two turns ago, then "go ahead"  -> "mail"
      fetched a page earlier in the chat          -> "web pages"
      a new chat                                  -> "" """
    from odie.signin import guard as signin_guard
    if not session_id:
        return ""
    read = signin_guard.read_of(store, session_id)
    if "your mail" in read or "your messages" in read:
        return MAIL
    kept = set(store.get_setting(KEY + session_id) or [])
    for label in (WEB, APP, JOB):
        if label in kept:
            return label
    return ""
