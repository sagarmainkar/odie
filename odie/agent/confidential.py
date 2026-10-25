"""What a tool result exposes: the user's own mail, notes, memory or messages, read into the chat's context. Once a
chat holds them, anything that sends words to the web (a search, a fetch, another site) asks first (odie.signin.guard),
the way it does after a signed-in page: the words a model picks for a search can carry what it just read, and an
instruction hidden in a mail is written to make it do exactly that."""
from __future__ import annotations

MAIL_WORDS = ("mail", "inbox", "imap", "outlook", "thread", "watch_item")
MESSAGE_WORDS = ("message", "sms", "imessage", "whatsapp", "chat_history")
CALENDAR_WORDS = ("calendar", "event", "reminder")
NOTES = frozenset({"read_note", "related_notes", "search_everything"})
MEMORY = frozenset({"fetch_memory", "search_memories"})
# Odie's own plumbing: a skill's name ("mcp-gmail-calendar") says nothing about what the chat has read.


def label_for(tool_name: str) -> str | None:
    """What a tool's result puts into the chat, as the card will name it, or None for a tool that exposes nothing of the
    user's own (the web, the shell, a file Odie made). Judged by the tool's name, erring towards "something": a wrong
    "your mail" costs one tap, a wrong None costs a leak. Examples: "gmail_find_email" -> "your mail";
    "GMAIL_FETCH_EMAILS" -> "your mail"; "mac_mail_read" -> "your mail"; "watch_item" -> "your mail"; "read_note" ->
    "your notes"; "fetch_memory" -> "your memory"; "mac_calendar_events" -> "your calendar"; "web_search" -> None;
    "run_shell" -> None."""
    name = tool_name.lower()
    if name in NOTES:
        return "your notes"
    if name in MEMORY:
        return "your memory"
    if any(word in name for word in MAIL_WORDS):
        return "your mail"
    if any(word in name for word in MESSAGE_WORDS):
        return "your messages"
    if any(word in name for word in CALENDAR_WORDS):
        return "your calendar"
    return None
