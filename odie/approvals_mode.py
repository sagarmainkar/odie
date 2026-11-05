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
# publish, share, forward, upload, export, invite, submit, comment, merge, schedule, permission), spends or moves money
# (pay, payment, purchase, order, book, reserve, checkout, transfer, refund, charge, payout) or removes something
# (delete, trash, remove, cancel). password, token and secret say it handles a credential. The generic executors
# (execute, exec, eval, run, call, invoke, perform, action, manage, multi, bash, shell, script, workbench, http, request,
# webhook) take their meaning from their arguments, so the name alone can't clear them. Inflections are listed because
# the words come from the name as written (SLACK_SENDS_A_MESSAGE, GOOGLEDRIVE_ADD_FILE_SHARING_PREFERENCE).
_ASK_WORDS = frozenset({
    "send", "sends", "sent", "sending", "reply", "post", "publish", "share", "shared", "sharing", "permission", "forward",
    "upload", "export", "invite", "invites", "submit", "comment", "merge", "schedule",
    "pay", "payment", "payments", "purchase", "order", "book", "reserve", "reservation", "checkout", "transfer", "refund",
    "charge", "payout",
    "delete", "trash", "remove", "cancel", "password", "token", "secret",
    "execute", "exec", "eval", "run", "call", "invoke", "perform", "action", "manage", "multi", "bash", "shell", "script",
    "workbench", "http", "request", "webhook",
})
# Some names say "create" where they mean "send": a calendar write may send invitations (rule 3) and the name can't say
# whether there are attendees; a message, a delivery or a ride that is "created" goes out. A write word next to one of
# these outgoing words asks. GOOGLECALENDAR_CREATE_EVENT -> asks; DISCORD_CREATE_MESSAGE -> asks; list_events -> runs.
_WRITE_WORDS = frozenset({"create", "update", "add", "new", "patch", "insert"})
_OUTGOING_WORDS = frozenset({"event", "events", "meeting", "meetings", "attendee", "attendees", "appointment",
                             "message", "messages", "dm", "email", "emails", "mail", "delivery", "ride", "booking"})


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
    """Whether the saved mode is Smart: "smart" saved -> True; nothing saved, or "careful" -> False."""
    return mode(store) == SMART


def mail_read_this_turn(store, session_id: str | None) -> bool:
    """Whether the model has read mail since the user's latest message in this chat, which is when words from a mail
    could be steering it. In Smart that turn asks again (the card then says the mail may be behind the action):
    mail opened this turn -> True; mail opened last turn or never -> False; no chat (session_id None) -> False."""
    if not session_id:
        return False
    seen = store.recent_mail_seen(session_id)
    return any(m.get("turn") == "current" for m in seen)


def runs_free(store, session_id: str | None) -> bool:
    """Whether routine work in this chat runs without a tap right now: Smart, and no mail read since the user's
    latest message. Careful -> False; Smart, no mail this turn -> True; Smart, a mail opened this turn -> False."""
    if not is_smart(store):
        return False
    return not mail_read_this_turn(store, session_id)


def asks_by_name(name: str) -> bool:
    """Whether a connected tool's name alone says it sends, pays, publishes, removes or runs whatever it is told, so it
    asks even in Smart. One ask-word anywhere in the name is enough:
    GMAIL_SEND_EMAIL -> True; cancel_order -> True; shareLink -> True; COMPOSIO_MULTI_EXECUTE_TOOL -> True;
    GMAIL_FORWARD_MESSAGE -> True; STRIPE_CREATE_REFUND -> True; set_password -> True; COMPOSIO_REMOTE_BASH_TOOL -> True;
    a calendar write (GOOGLECALENDAR_CREATE_EVENT, calendar_create_event) -> True, it may send invitations;
    DISCORD_CREATE_MESSAGE -> True (a created message goes out); GMAIL_FETCH_EMAILS -> False;
    gmail_find_email -> False; list_events -> False; list_items -> False."""
    words = name_words(name)
    if words & _ASK_WORDS:
        return True
    writes_something_outgoing = bool(words & _WRITE_WORDS) and bool(words & _OUTGOING_WORDS)
    return writes_something_outgoing


def plain_write_needs_tap(store) -> bool:
    """Whether an ordinary write (a note, a file in a safe place, a calendar event) asks for a tap:
    Careful -> True (as today); Smart -> False (it runs, and the activity log still shows it)."""
    return not is_smart(store)


# Set once by the app (hooks["store"]) so tools built at import time, with no store in hand, can read the live mode.
hooks: dict = {}


def plain_write_asks(**_) -> bool:
    """ADK's require_confirmation for a plain local write such as mac_calendar_add or mac_reminder_add (ADK calls it
    with the tool's own arguments, which it ignores). It reads the mode on every call from the app's store:
    Careful -> True (the card); Smart -> False (it runs); no store set yet (a test, a tool run outside the app) -> True."""
    store = hooks.get("store")
    if store is None:
        return True
    return plain_write_needs_tap(store)


def context_line(store) -> str:
    """The one line of each turn's context that tells the model which mode is on, so it never promises a tap that
    won't come (or the reverse): Smart -> "Approvals: smart (commands and app tools run without a tap; installs,
    deletes outside Odie's folders, sends, payments and secrets still ask)"; Careful -> "Approvals: careful (changes
    ask first)"."""
    if is_smart(store):
        return ("Approvals: smart (commands and app tools run without a tap; installs, deletes outside Odie's folders, "
                "sends, payments and secrets still ask, and so does anything right after you read a mail; where a rule "
                "or a skill says a tool asks first, that now means only those)")
    return "Approvals: careful (changes ask first)"
