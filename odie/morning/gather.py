"""What the morning hello is written from, gathered by code (no model): the last four days of chats, the memories that
matter this morning, the last day's mail, yesterday's events, what's coming up, the open tasks, the brief's parts and
today's weather. Each part is plain text for the writer's prompt; a part that has nothing, isn't connected or fails is
left empty, and gathering never raises.

No chats are left out, including chats that read a signed-in page (the owner's decision, 4 Nov): they stay on this Mac,
but the chosen chat model (often a cloud model) reads them when it writes the hello."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from odie import config, profile, upcoming
from odie.jobs.brief import BriefInputs
from odie.morning.weather import today_weather
from odie.recall.chats import ChatLine, chat_lines
from odie.watch.fetch import Event, Fetcher, Mail
from odie.watch.sources import saved

log = logging.getLogger("odie.morning.gather")

DAYS_BACK = 4  # chats and dated memories: from local midnight four days back
CHAT_CHARS = 60_000  # the newest chat words kept; fits the chat model's window with room to spare
MESSAGE_CHARS = 1_500  # one message's words, cut
PEOPLE_TOPICS = ("people", "family")  # topics whose every entry comes along, however old (names, birthdays)
MAIL_HOURS = 24
MAIL_MOST = 40
SNIPPET_CHARS = 300
UPCOMING_DAYS = 14


@dataclass
class MorningInputs:
    day: str  # "Wednesday 4 November 2026"
    user: str  # the profile's name, or ""
    chats: str
    memories: str
    mail: str
    yesterday: str
    upcoming: str
    tasks: str
    brief_parts: str
    weather: dict | None
    yesterday_hello: str = ""  # yesterday's greeting and paragraphs, so today's says something different
    brief_line: str = ""  # today's morning brief, when one was written


def user_tz() -> ZoneInfo:
    return ZoneInfo(config.settings.timezone)


def midnight(day: date, tz: ZoneInfo) -> datetime:
    return datetime.combine(day, time(0), tzinfo=tz)


# ── chats ──
def chat_line_text(line: ChatLine) -> str:
    """One message as the prompt shows it: its day, who said it, its words cut at MESSAGE_CHARS.
    ("2026-11-03", "you", "Did it run?") -> "[3 Nov] you: Did it run?"."""
    label = date.fromisoformat(line.day).strftime("%-d %b")
    return f"[{label}] {line.author}: {line.text[:MESSAGE_CHARS]}"


def newest_within(lines: list[str], cap: int) -> list[str]:
    """The newest lines whose total (with a newline each) fits the cap, oldest first. Walking back from the newest,
    the first line that doesn't fit stops the walk. Lines of 40 characters with a cap of 100 -> the newest two."""
    kept: list[str] = []
    size = 0
    for line in reversed(lines):
        newline = 1 if kept else 0  # joins this line to the newer one after it
        if size + len(line) + newline > cap:
            break
        size += len(line) + newline
        kept.append(line)
    kept.reverse()
    return kept


def recent_chats(now: datetime) -> str:
    """Every chat's words from local midnight four days back until now (no chats are left out), newest kept."""
    s = config.settings
    tz = user_tz()
    local_today = now.astimezone(tz).date()
    since = midnight(local_today - timedelta(days=DAYS_BACK), tz).timestamp()
    lines = chat_lines(s.sessions_db_path, s.app_name, s.user_id, since, now.timestamp(), tz)
    texts = [chat_line_text(line) for line in lines]
    return "\n".join(newest_within(texts, CHAT_CHARS))


# ── memories ──
def memory_matters(topic: str, entry_date: str, oldest: str) -> bool:
    """Whether a memory goes to the hello: every entry under a People or Family topic (any case), and any entry dated
    on or after `oldest`. With oldest "2026-10-31": People, 2025-02-01 -> True; Work, 2026-11-02 -> True; Work,
    2026-09-01 -> False; Work, undated -> False."""
    if topic.casefold() in PEOPLE_TOPICS:
        return True
    return bool(entry_date) and entry_date >= oldest


def morning_memories(now: datetime) -> str:
    from odie.agent.agent import memory_file
    local_today = now.astimezone(user_tz()).date()
    oldest = (local_today - timedelta(days=DAYS_BACK)).isoformat()
    doc = memory_file().load()
    blocks = []
    for entry in doc.entries():
        if memory_matters(entry.topic, entry.date, oldest):
            blocks.append(f"[{entry.topic}] {entry.heading}: {entry.body.strip()}")
    return "\n".join(blocks)


# ── mail and calendar ──
def has_source(store, kind: str) -> bool:
    """Whether a mail or calendar source is saved, so the watch's reader has something to read. No sources -> False
    (nothing is read); a Gmail source and kind "mail" -> True; the same and kind "calendar" -> False."""
    return any(src.kind == kind for src in saved(store))


def mail_record(mail: Mail) -> str:
    """One mail as a short record: sender · subject · the snippet on one line, cut at SNIPPET_CHARS. Never the body.
    Each part is kept to one line, so a newline in a sender or subject can't fake a heading in the writer's prompt."""
    sender = " ".join(mail.frm.split())
    subject = " ".join(mail.subject.split())
    snippet = " ".join(mail.snippet.split())[:SNIPPET_CHARS]
    return f"{sender} · {subject} · {snippet}"


async def fresh_mail(store, now: datetime) -> str:
    mails = await Fetcher(store, now).recent_mail(hours=MAIL_HOURS, most=MAIL_MOST)
    return "\n".join(mail_record(m) for m in mails)


def event_line(event: Event) -> str:
    """One of yesterday's events: its time, its title, and where when known. "15:00 · Design review · Room 2"."""
    parts = [event.start[11:16], event.title]
    if event.where:
        parts.append(event.where)
    return " · ".join(part for part in parts if part)


async def yesterdays_events(store, now: datetime) -> str:
    tz = user_tz()
    local_today = now.astimezone(tz).date()
    start = midnight(local_today - timedelta(days=1), tz)
    end = midnight(local_today, tz)
    events = await Fetcher(store, now)._read_events(start, end)
    return "\n".join(event_line(e) for e in events)


# ── coming up ──
def upcoming_line(item: dict) -> str:
    """One coming-up item: when · title · kind, then the place when known. The fallback card splits it on " · ".
    {"date": "2026-11-05", "time": "10:00", "title": "Dentist", "kind": "medical"} -> "Thu 5 Nov 10:00 · Dentist · medical"."""
    when = date.fromisoformat(item["date"]).strftime("%a %-d %b")
    if item.get("time"):
        when = f"{when} {item['time']}"
    parts = [when, item["title"], item["kind"]]
    if item.get("place"):
        parts.append(item["place"])
    if item.get("done"):
        parts.append(f"done: {item['done']}")
    return " · ".join(parts)


async def coming_up(store, now: datetime) -> str:
    got = await upcoming.build(store, now, days=UPCOMING_DAYS)
    return "\n".join(upcoming_line(item) for item in got["items"])


def brief_parts_text(brief: BriefInputs) -> str:
    """The brief's parts with something in them, each under its own title. A part not connected (None) or empty is
    left out."""
    blocks = [f"{part.title}:\n{part.text}" for part in brief.parts if part.text]
    return "\n\n".join(blocks)


# ── all of it ──
async def gather(store, now: datetime, brief: BriefInputs) -> MorningInputs:
    """Everything the hello is written from. Each source is read in its own try: one that fails is logged and left
    empty, and the rest go on. Mail and yesterday's events are read only when a mail or calendar source is saved."""
    chats = ""
    try:
        chats = recent_chats(now)
    except Exception:
        log.info("morning: the chats couldn't be read", exc_info=True)

    memories = ""
    try:
        memories = morning_memories(now)
    except Exception:
        log.info("morning: the memories couldn't be read", exc_info=True)

    mail = ""
    try:
        if has_source(store, "mail"):
            mail = await fresh_mail(store, now)
    except Exception:
        log.info("morning: the mail couldn't be read", exc_info=True)

    yesterday = ""
    try:
        if has_source(store, "calendar"):
            yesterday = await yesterdays_events(store, now)
    except Exception:
        log.info("morning: yesterday's events couldn't be read", exc_info=True)

    coming = ""
    try:
        coming = await coming_up(store, now)
    except Exception:
        log.info("morning: what's coming up couldn't be read", exc_info=True)

    weather = None
    try:
        weather = await today_weather(store)
    except Exception:
        log.info("morning: the weather couldn't be read", exc_info=True)

    day = now.astimezone(user_tz()).strftime("%A %-d %B %Y")
    user = profile.get(store)["user_name"]
    return MorningInputs(day=day, user=user, chats=chats, memories=memories, mail=mail, yesterday=yesterday,
                         upcoming=coming, tasks=brief.tasks, brief_parts=brief_parts_text(brief), weather=weather)
