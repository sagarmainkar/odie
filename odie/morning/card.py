"""The morning card's shape: the model's JSON checked into it (what's broken is dropped), and the plain card code builds
when the model gives nothing usable, so the day always opens with a card."""
from __future__ import annotations

import re
from datetime import datetime

from odie.morning.gather import MorningInputs

CARD_KEYS = ("greeting", "accent", "emoji", "say", "tiles", "nudge", "mail", "recent", "chips", "summary")
SUMMARY_CHARS = 3_500
EMOJI_CHARS = 2
SAY_MOST, SAY_CHARS = 2, 900
TILES_MOST, TILE_VALUE_CHARS = 4, 30
MAIL_MOST = 6
RECENT_MOST = 5
RECENT_STATES = ("done", "stuck", "open")
CHIPS_MOST, CHIP_CHARS = 4, 40
TASK_PREFIX_RE = re.compile(r"^#\d+ \[[^\]]*\] ")  # "#3 [todo] " before a task's title (jobs.brief.format_tasks)
SENTENCE_END_RE = re.compile(r"[.!?…](?=\s)")  # a sentence's last mark, with a space or newline after it


def plain(value) -> str:
    """A value as stripped text when it is text, else "". "  Hi " -> "Hi"; 7 -> ""; None -> ""."""
    if isinstance(value, str):
        return value.strip()
    return ""


def dicts_in(value) -> list[dict]:
    """The dicts in a list; anything else in it, or a value that is not a list, gives nothing."""
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def checked_accent(accent: str, greeting: str) -> str:
    """The accent word, kept only when it is part of the greeting (the web sets it in italics there).
    ("launch", "Two days to the launch") -> "launch"; ("Diwali", "Good morning") -> ""."""
    if accent and accent in greeting:
        return accent
    return ""


def within_say_chars(paragraph: str) -> str:
    """A paragraph of at most SAY_CHARS: as it is when it fits, else cut after its last sentence that ends within
    SAY_CHARS; "" when no sentence ends there. 890 characters -> as it is; 989 characters of 33-character sentences ->
    the first 27 sentences (890 characters); 950 characters with no full stop -> ""."""
    if len(paragraph) <= SAY_CHARS:
        return paragraph
    ends = [m.end() for m in SENTENCE_END_RE.finditer(paragraph[:SAY_CHARS + 1])]  # +1: the space after a last mark
    if not ends:
        return ""
    return paragraph[:ends[-1]]


def checked_say(value) -> list[str]:
    """Odie's one or two paragraphs. A plain string counts as one; a paragraph over SAY_CHARS is cut at a sentence
    end (within_say_chars); one that is not text is dropped.
    ["How was it?", 7] -> ["How was it?"]; "How was it?" -> ["How was it?"]; ["x" * 950] -> []."""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    paragraphs = [within_say_chars(plain(p)) for p in value]
    kept = [p for p in paragraphs if p]
    return kept[:SAY_MOST]


def checked_tiles(value) -> list[dict]:
    """Up to four tiles, each with a label and a short value (a missing note is ""). A tile without a label or value,
    or with a value over TILE_VALUE_CHARS, is dropped. 7 good tiles -> the first 4; {"label": "Due"} -> dropped."""
    tiles = []
    for item in dicts_in(value):
        tile = {"label": plain(item.get("label")), "value": plain(item.get("value")), "note": plain(item.get("note"))}
        if tile["label"] and tile["value"] and len(tile["value"]) <= TILE_VALUE_CHARS:
            tiles.append(tile)
    return tiles[:TILES_MOST]


def checked_nudge(value) -> dict | None:
    """The one nudge, when it has words. {"icon": "🎂", "text": "Gift ideas?"} -> kept; {"icon": "🎂"} -> None."""
    if not isinstance(value, dict):
        return None
    text = plain(value.get("text"))
    if not text:
        return None
    return {"icon": plain(value.get("icon")), "text": text}


def checked_mail(value) -> list[dict]:
    """Up to six mail rows, each with a title (the rest may be ""). A row without a title is dropped."""
    rows = []
    for item in dicts_in(value):
        row = {"icon": plain(item.get("icon")), "title": plain(item.get("title")), "note": plain(item.get("note")),
               "pill": plain(item.get("pill"))}
        if row["title"]:
            rows.append(row)
    return rows[:MAIL_MOST]


def checked_recent(value) -> list[dict]:
    """Up to five rows from the last few days, each done, stuck or open, with words. {"state": "maybe", ...} -> dropped;
    {"state": "stuck", "text": "Reporter timing out"} -> kept with note ""."""
    rows = []
    for item in dicts_in(value):
        row = {"state": plain(item.get("state")), "text": plain(item.get("text")), "note": plain(item.get("note"))}
        if row["state"] in RECENT_STATES and row["text"]:
            rows.append(row)
    return rows[:RECENT_MOST]


def checked_chips(value) -> list[str]:
    """Up to four tap-to-send chips, each short text; a chip over CHIP_CHARS, or not text, is dropped.
    ["Plan my day", "x" * 200, "Fix the reporter"] -> ["Plan my day", "Fix the reporter"]."""
    if not isinstance(value, list):
        return []
    chips = [plain(c) for c in value]
    kept = [c for c in chips if c and len(c) <= CHIP_CHARS]
    return kept[:CHIPS_MOST]


def checked(raw) -> dict | None:
    """The model's card in the card's known shape, or None when it has no greeting or no summary (then the fallback
    card is used). Each part is checked on its own: a broken part is dropped or emptied and the rest is kept; keys the
    card doesn't know are dropped. 7 tiles -> 4; a 200-character chip -> dropped; "summary": "" -> None; a list in
    place of a card -> None."""
    if not isinstance(raw, dict):
        return None
    greeting = plain(raw.get("greeting"))
    summary = plain(raw.get("summary"))
    if not greeting or not summary:
        return None
    emoji = plain(raw.get("emoji"))
    if len(emoji) > EMOJI_CHARS:
        emoji = ""
    return {
        "greeting": greeting,
        "accent": checked_accent(plain(raw.get("accent")), greeting),
        "emoji": emoji,
        "say": checked_say(raw.get("say")),
        "tiles": checked_tiles(raw.get("tiles")),
        "nudge": checked_nudge(raw.get("nudge")),
        "mail": checked_mail(raw.get("mail")),
        "recent": checked_recent(raw.get("recent")),
        "chips": checked_chips(raw.get("chips")),
        "summary": summary[:SUMMARY_CHARS],
    }


# ── the fallback ──
def part_of_day(hour: int) -> str:
    """The part of the day an hour is in, for the greeting: 7 -> "morning"; 15 -> "afternoon"; 19 -> "evening"."""
    if hour < 12:
        return "morning"
    if hour < 17:
        return "afternoon"
    return "evening"


def greeting_for(now: datetime, user: str) -> str:
    """The plain greeting, from the hour. 07:30, "Asha" -> "Good morning, Asha."; 14:00, "" -> "Good afternoon.";
    19:00, "" -> "Good evening."."""
    words = f"Good {part_of_day(now.hour)}"
    if user:
        return f"{words}, {user}."
    return f"{words}."


def lines_of(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip()]


def tile_from_upcoming(line: str) -> dict:
    """A tile from one coming-up line (gather.upcoming_line): when, title, and the rest as the note.
    "Thu 5 Nov 10:00 · Dentist · medical" -> {"label": "Thu 5 Nov 10:00", "value": "Dentist", "note": "medical"}."""
    parts = line.split(" · ")
    label = parts[0]
    value = ""
    if len(parts) > 1:
        value = parts[1][:TILE_VALUE_CHARS]
    note = " · ".join(parts[2:])
    return {"label": label, "value": value, "note": note}


def tasks_tile(task_lines: list[str]) -> dict:
    """The open tasks as one tile: how many, and the first one's title.
    ["#3 [todo] Answer Asha · due 2026-11-05"] -> {"label": "Open tasks", "value": "1 open", "note": "Answer Asha · due ..."}."""
    first_title = TASK_PREFIX_RE.sub("", task_lines[0])
    return {"label": "Open tasks", "value": f"{len(task_lines)} open", "note": first_title}


def mail_row(record: str) -> dict:
    """A mail row from one mail record (gather.mail_record: sender · subject · snippet).
    "Shop · Your refund · We refunded…" -> {"icon": "✉️", "title": "Your refund", "note": "Shop", "pill": ""}."""
    parts = record.split(" · ", 2)
    sender = parts[0]
    subject = sender
    if len(parts) > 1:
        subject = parts[1]
    return {"icon": "✉️", "title": subject, "note": sender, "pill": ""}


def fallback_summary(inp: MorningInputs) -> str:
    sections = []
    if inp.tasks:
        sections.append("Open tasks:\n" + inp.tasks)
    if inp.upcoming:
        sections.append("Coming up:\n" + inp.upcoming)
    if not sections:
        return "No open tasks and nothing coming up in the next two weeks."
    return "\n\n".join(sections)[:SUMMARY_CHARS]


def fallback_card(inp: MorningInputs, now: datetime) -> dict:
    """The plain card code builds when the model's answer can't be used: a greeting from the hour, tiles from what's
    coming up and the open tasks, mail rows from the fresh mail, no paragraphs and no recent rows. Its summary is the
    tasks and what's coming up as plain lines. Nothing gathered -> a greeting, no tiles, the "nothing coming up"
    summary; two coming-up items and a task -> two item tiles and an "Open tasks" tile."""
    task_lines = lines_of(inp.tasks)
    tiles = [tile_from_upcoming(line) for line in lines_of(inp.upcoming)]
    if task_lines:
        tiles = tiles[:TILES_MOST - 1] + [tasks_tile(task_lines)]
    mail = [mail_row(record) for record in lines_of(inp.mail)]
    return {
        "greeting": greeting_for(now, inp.user),
        "accent": "",
        "emoji": "",
        "say": [],
        "tiles": tiles[:TILES_MOST],
        "nudge": None,
        "mail": mail[:MAIL_MOST],
        "recent": [],
        "chips": [],
        "summary": fallback_summary(inp),
        "fallback": True,
    }
