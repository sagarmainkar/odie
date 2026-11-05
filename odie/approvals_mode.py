"""How much Odie asks before it acts, one setting for the whole app, kept in the store's settings as "approvals.mode".

Careful: every tap asks, exactly as before. Smart: routine work runs without a tap; the risky things (installs, deletes,
sending data out, secrets, sending/paying/publishing tools) still ask. An install that never chose is Careful."""
from __future__ import annotations

import re

KEY = "approvals.mode"
CAREFUL = "careful"
SMART = "smart"
MODES = (CAREFUL, SMART)

# Words in a tool's name that make it ask even in Smart. Most say the tool sends something out (send, reply, post,
# publish, share, forward, upload, export, invite, submit), spends or moves money (pay, purchase, order, book, checkout,
# transfer, refund) or removes something (delete, trash, remove, cancel). password, token and secret say it handles a
# credential. The generic executors (execute, run, call, invoke, perform, action, manage, multi) take their meaning from
# their arguments, so the name alone can't clear them.
_ASK_WORDS = frozenset({"send", "reply", "post", "publish", "share", "forward", "upload", "export", "invite", "submit",
                        "pay", "purchase", "order", "book", "checkout", "transfer", "refund",
                        "delete", "trash", "remove", "cancel", "password", "token", "secret",
                        "execute", "run", "call", "invoke", "perform", "action", "manage", "multi"})


def name_words(name: str) -> set[str]:
    """The lower-case words of a tool name, split on _ - . spaces and camelCase humps:
    GMAIL_SEND_EMAIL -> {gmail, send, email}; shareLink -> {share, link}. Lives here, not in odie.plugins.mcp, so this
    module (and the shell check that reads it on every command) imports no ADK or MCP code."""
    return {w.lower() for w in re.split(r"[_\-\s.]+|(?<=[a-z0-9])(?=[A-Z])", name) if w}


def mode(store) -> str:
    """The saved mode; Careful when nothing is saved or the saved value is not one of the two:
    nothing saved -> "careful"; "smart" -> "smart"; "reckless" -> "careful"."""
    saved = store.get_setting(KEY)
    if saved in MODES:
        return saved
    return CAREFUL


def set_mode(store, value: str) -> str:
    """Save Careful or Smart and note it in the audit log; anything else is refused and nothing changes:
    "smart" -> saved, returns "smart"; "yolo" -> ValueError."""
    if value not in MODES:
        raise ValueError(f"The approvals mode is {CAREFUL} or {SMART}, not {value!r}.")
    store.set_setting(KEY, value)
    store.audit("user", "approvals_mode", result_summary=value)
    return value


def is_smart(store) -> bool:
    return mode(store) == SMART


def asks_by_name(name: str) -> bool:
    """Whether a connected tool's name alone says it sends, pays, publishes, removes or runs whatever it is told, so it
    asks even in Smart. One ask-word anywhere in the name is enough:
    GMAIL_SEND_EMAIL -> True; cancel_order -> True; shareLink -> True; COMPOSIO_MULTI_EXECUTE_TOOL -> True;
    GMAIL_FORWARD_MESSAGE -> True; STRIPE_CREATE_REFUND -> True; set_password -> True;
    gmail_find_email -> False; calendar_create_event -> False; list_items -> False."""
    return bool(name_words(name) & _ASK_WORDS)


def plain_write_needs_tap(store) -> bool:
    """Whether an ordinary write (a note, a file in a safe place, a calendar event) asks for a tap:
    Careful -> True (as today); Smart -> False (it runs, and the activity log still shows it)."""
    return not is_smart(store)
