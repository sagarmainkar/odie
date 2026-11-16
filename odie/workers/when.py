"""When a routine runs, in the user's words (16 Nov 2026). The user asked for a flexible scheduler: one box where they
write "weekdays at 9:15 and 6pm", "every 30 minutes from 9 to 6", "1st and 15th at 9", "last Friday of the month at 5pm",
"tomorrow 3pm" or "every morning at 8 until 30 Nov", and see the next runs before saving.

A schedule is stored as a small dict (clean() makes and checks one):
  {"kind": "daily", "times": ["08:00", "18:00"], "days": [0, 1, 2, 3, 4]}           weekdays at 8 and 6
  {"kind": "every", "minutes": 120, "from": "09:00", "to": "18:00", "days": [0..6]}  every 2 hours, 9 to 6
  {"kind": "monthly", "times": ["09:00"], "dates": [1, 15, -1], "nth": [[-1, 4]]}   1st, 15th, last day, last Fri
  {"kind": "once", "at": "2026-11-17T15:00"}                                           once, local time
Any of them may end: "until": "2026-11-30" (local date, that day included).
Days are 0=Mon … 6=Sun. Times are local, "HH:MM". The words for one (words()) read back through parse() to the same."""
from __future__ import annotations

import calendar
import re
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

DAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
ALL_DAYS = list(range(7))
WEEKDAYS = [0, 1, 2, 3, 4]
WEEKENDS = [5, 6]
MIN_EVERY_MINUTES = 15
MAX_EVERY_MINUTES = 7 * 24 * 60
MAX_TIMES = 12
LOOK_AHEAD_DAYS = 400  # far enough for a yearly-ish monthly date; beyond that the routine has no next run
KINDS = ("daily", "every", "monthly", "once")
HELP = ("Try 'weekdays at 9:15', 'every day at 8 and 6pm', 'every 2 hours from 9 to 6', '1st of the month at 9', "
        "'last Friday at 5pm', or 'tomorrow 3pm'.")

# ── the stored form ──────────────────────────────────────────────────────────


def _hhmm(value) -> str | None:
    """A time as stored: "8:30" -> "08:30"; "25:00" -> None; "x" -> None."""
    try:
        hh, mm = (int(x) for x in str(value).strip().split(":", 1))
    except ValueError:
        return None
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return None
    return f"{hh:02d}:{mm:02d}"


def _days(value) -> list[int]:
    """Weekdays as stored, sorted and unique: None -> every day; [4, 0, 0] -> [0, 4]; ["x", 9] -> []."""
    if value is None:
        return list(ALL_DAYS)
    return sorted({int(d) for d in value if isinstance(d, int | float) and 0 <= int(d) <= 6})


def _times(schedule: dict) -> list[str] | str:
    """A schedule's times, cleaned: {"times": ["18:00", "8:00"]} -> ["08:00", "18:00"]; the older {"at": "8:30"} ->
    ["08:30"]; none -> "Say a time, like 08:30."; a bad one -> "A time like 08:30."."""
    raw = schedule.get("times")
    if raw is None and schedule.get("at") is not None:
        raw = [schedule["at"]]
    if not raw:
        return "Say a time, like 08:30."
    cleaned = []
    for value in raw:
        got = _hhmm(value)
        if got is None:
            return "A time like 08:30."
        cleaned.append(got)
    cleaned = sorted(set(cleaned))
    if len(cleaned) > MAX_TIMES:
        return f"At most {MAX_TIMES} times a day."
    return cleaned


def _until(schedule: dict) -> str | None | bool:
    """The last day, as stored: "2026-11-30" -> "2026-11-30"; none -> None; not a date -> False."""
    raw = schedule.get("until")
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw)[:10]).isoformat()
    except ValueError:
        return False


def clean(schedule: dict) -> dict | str:
    """A schedule as stored, or a line saying what's wrong. Older forms are taken too ({"kind": "daily", "at": "8:30"},
    {"kind": "every", "hours": 3}).
      {"kind": "daily", "times": ["8:30"]} -> {"kind": "daily", "times": ["08:30"], "days": [0..6]}
      {"kind": "every", "hours": 3} -> {"kind": "every", "minutes": 180, "from": "00:00", "to": "23:59", "days": [0..6]}
      {"kind": "every", "minutes": 5} -> "Every 15 minutes at the most often."
      {"kind": "monthly", "times": ["09:00"], "dates": []} -> "Say which days of the month."
      {"kind": "weekly"} -> "Say when: …\""""
    if not isinstance(schedule, dict) or schedule.get("kind") not in KINDS:
        return "Say when: " + HELP
    kind = schedule["kind"]
    until = _until(schedule)
    if until is False:
        return "An end date like 2026-11-30."
    out: dict
    if kind == "once":
        try:
            at = datetime.fromisoformat(str(schedule.get("at") or ""))
        except ValueError:
            return "A date and time, like tomorrow 3pm."
        out = {"kind": "once", "at": at.strftime("%Y-%m-%dT%H:%M")}
        return out
    if kind == "every":
        minutes = schedule.get("minutes")
        if minutes is None and schedule.get("hours") is not None:
            try:
                minutes = int(schedule["hours"]) * 60
            except (TypeError, ValueError):
                minutes = None
        try:
            minutes = int(minutes)
        except (TypeError, ValueError):
            return "Say how often, like every 2 hours."
        if minutes < MIN_EVERY_MINUTES:
            return f"Every {MIN_EVERY_MINUTES} minutes at the most often."
        if minutes > MAX_EVERY_MINUTES:
            return "At least once a week."
        start = _hhmm(schedule.get("from") or "00:00")
        end = _hhmm(schedule.get("to") or "23:59")
        if start is None or end is None:
            return "A time like 08:30."
        if end <= start:
            return "The window ends before it starts."
        days = _days(schedule.get("days"))
        if not days:
            return "Pick at least one day."
        out = {"kind": "every", "minutes": minutes, "from": start, "to": end, "days": days}
    else:
        times = _times(schedule)
        if isinstance(times, str):
            return times
        if kind == "daily":
            days = _days(schedule.get("days"))
            if not days:
                return "Pick at least one day."
            out = {"kind": "daily", "times": times, "days": days}
        else:
            dates = sorted({int(d) for d in schedule.get("dates") or [] if isinstance(d, int | float) and (1 <= int(d) <= 31 or int(d) == -1)})
            nth = []
            for pair in schedule.get("nth") or []:
                try:
                    n, weekday = int(pair[0]), int(pair[1])
                except (TypeError, ValueError, IndexError):
                    continue
                if n in (-1, 1, 2, 3, 4) and 0 <= weekday <= 6 and [n, weekday] not in nth:
                    nth.append([n, weekday])
            if not dates and not nth:
                return "Say which days of the month."
            out = {"kind": "monthly", "times": times, "dates": dates, "nth": nth}
    if until:
        out["until"] = until
    return out


# ── when it runs next ────────────────────────────────────────────────────────


def _on_monthly_day(schedule: dict, day: date) -> bool:
    """Whether a monthly schedule runs on this day: dates [1, -1] -> the 1st and the month's last day; nth [[-1, 4]] ->
    the last Friday; [[2, 0]] -> the second Monday. A 31st in a 30-day month is skipped, as cron does."""
    last_day = calendar.monthrange(day.year, day.month)[1]
    if day.day in schedule["dates"]:
        return True
    if -1 in schedule["dates"] and day.day == last_day:
        return True
    for n, weekday in schedule["nth"]:
        if day.weekday() != weekday:
            continue
        if n == -1 and day.day + 7 > last_day:
            return True
        if n > 0 and (day.day - 1) // 7 + 1 == n:
            return True
    return False


def _clock(text: str) -> time:
    hh, mm = (int(x) for x in text.split(":"))
    return time(hh, mm)


def next_run(schedule: dict, after: datetime, zone: ZoneInfo) -> datetime | None:
    """When a schedule runs next, strictly after `after` (UTC in, UTC out), or None when it has no runs left (a once
    that has passed, a schedule past its until). Worked examples, in IST:
      daily 08:30 every day, after Mon 09:00 -> Tue 08:30;  after Mon 08:00 -> Mon 08:30
      daily 08:00 and 18:00, after Mon 09:00 -> Mon 18:00
      every 120 min from 09:00 to 18:00 weekdays, after Mon 10:05 -> Mon 11:00; after Fri 17:30 -> Mon 09:00
      monthly the last Fri at 17:00, after Mon 16 Nov 2026 -> Fri 27 Nov 17:00
      once 2026-11-17T15:00, after it -> None;  daily until 2026-11-16, after Mon 16 Nov 20:00 -> None"""
    local = after.astimezone(zone)
    until = date.fromisoformat(schedule["until"]) if schedule.get("until") else None
    if schedule["kind"] == "once":
        when = datetime.fromisoformat(schedule["at"]).replace(tzinfo=zone)
        return when.astimezone(UTC) if when > local else None
    for step in range(LOOK_AHEAD_DAYS):
        day = local.date() + timedelta(days=step)
        if until and day > until:
            return None
        if schedule["kind"] == "every":
            if day.weekday() not in schedule["days"]:
                continue
            start = datetime.combine(day, _clock(schedule["from"]), tzinfo=zone)
            end = datetime.combine(day, _clock(schedule["to"]), tzinfo=zone)
            interval = timedelta(minutes=schedule["minutes"])
            when = start
            if local >= start:
                steps_passed = (local - start) // interval + 1
                when = start + steps_passed * interval
            if when <= end:
                return when.astimezone(UTC)
            continue
        if schedule["kind"] == "daily" and day.weekday() not in schedule["days"]:
            continue
        if schedule["kind"] == "monthly" and not _on_monthly_day(schedule, day):
            continue
        for at in schedule["times"]:
            when = datetime.combine(day, _clock(at), tzinfo=zone)
            if when > local:
                return when.astimezone(UTC)
    return None


def next_runs(schedule: dict, after: datetime, zone: ZoneInfo, count: int = 3) -> list[datetime]:
    """The next few runs, for the preview under the box: daily 08:00 after Mon 09:00 -> [Tue, Wed, Thu 08:00]."""
    out = []
    when = after
    for _ in range(count):
        got = next_run(schedule, when, zone)
        if got is None:
            break
        out.append(got)
        when = got
    return out


# ── in words ─────────────────────────────────────────────────────────────────


def _listed(parts: list[str]) -> str:
    """["a"] -> "a"; ["a", "b"] -> "a and b"; ["a", "b", "c"] -> "a, b and c"."""
    if len(parts) <= 1:
        return "".join(parts)
    return ", ".join(parts[:-1]) + " and " + parts[-1]


def _days_words(days: list[int]) -> str:
    """[0..6] -> "Every day"; [0..4] -> "Weekdays"; [5, 6] -> "Weekends"; [0] -> "Every Mon"; [0, 3] -> "Mon, Thu"."""
    if days == ALL_DAYS:
        return "Every day"
    if days == WEEKDAYS:
        return "Weekdays"
    if days == WEEKENDS:
        return "Weekends"
    if len(days) == 1:
        return f"Every {DAY_NAMES[days[0]]}"
    return ", ".join(DAY_NAMES[d] for d in days)


def _ordinal(n: int) -> str:
    """1 -> "1st"; 2 -> "2nd"; 13 -> "13th"; 22 -> "22nd"."""
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


NTH_WORDS = {1: "first", 2: "second", 3: "third", 4: "fourth", -1: "last"}


def _date_words(day: date) -> str:
    """date(2026, 11, 30) -> "30 Nov 2026"."""
    return f"{day.day} {calendar.month_abbr[day.month]} {day.year}"


def words(schedule: dict) -> str:
    """A schedule in words, which parse() reads back to the same schedule. Worked examples:
      daily ["08:30"] every day -> "Every day at 08:30";  daily ["09:15"] weekdays -> "Weekdays at 09:15"
      daily ["08:00", "18:00"] Mon, Thu -> "Mon, Thu at 08:00 and 18:00"
      every 60 -> "Every hour";  every 120 from 09:00 to 18:00 weekdays -> "Every 2 hours from 09:00 to 18:00 on weekdays"
      every 30 -> "Every 30 minutes";  every 90 -> "Every 90 minutes"
      monthly dates [1, 15] at 09:00 -> "Monthly on the 1st and 15th at 09:00"
      monthly dates [-1] nth [[-1, 4]] at 18:00 -> "Monthly on the last day and last Fri at 18:00"
      once 2026-11-17T15:00 -> "Once on 17 Nov 2026 at 15:00";  any with until -> "… until 30 Nov 2026\""""
    kind = schedule["kind"]
    if kind == "once":
        at = datetime.fromisoformat(schedule["at"])
        return f"Once on {_date_words(at.date())} at {at.strftime('%H:%M')}"
    if kind == "every":
        minutes = schedule["minutes"]
        if minutes == 60:
            said = "Every hour"
        elif minutes % 60 == 0:
            said = f"Every {minutes // 60} hours"
        else:
            said = f"Every {minutes} minutes"
        if (schedule["from"], schedule["to"]) != ("00:00", "23:59"):
            said += f" from {schedule['from']} to {schedule['to']}"
        if schedule["days"] != ALL_DAYS:
            days_text = _days_words(schedule["days"])
            if schedule["days"] in (WEEKDAYS, WEEKENDS):
                days_text = days_text.lower()
            said += f" on {days_text}"
    elif kind == "daily":
        said = f"{_days_words(schedule['days'])} at {_listed(schedule['times'])}"
    else:
        which = [_ordinal(d) for d in schedule["dates"] if d > 0]
        if -1 in schedule["dates"]:
            which.append("last day")
        which += [f"{NTH_WORDS[n]} {DAY_NAMES[wd]}" for n, wd in schedule["nth"]]
        said = f"Monthly on the {_listed(which)} at {_listed(schedule['times'])}"
    if schedule.get("until"):
        said += f" until {_date_words(date.fromisoformat(schedule['until']))}"
    return said


# ── reading the user's words ─────────────────────────────────────────────────

_MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}
_DAY_BY_PREFIX = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}
_DAY = (r"(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tues|tue|weds|wed|thurs|thur|thu|fri|sat|"
        r"sun)s?")
_COUNT_WORDS = r"a|an|one|two|three|four|five|six|eight|ten|twelve|fifteen|twenty|thirty|ninety"
_NUMBER_WORDS = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "eight": 8,
                 "ten": 10, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "ninety": 90}
_ORDINAL_WORDS = {"first": 1, "1st": 1, "second": 2, "2nd": 2, "third": 3, "3rd": 3, "fourth": 4, "4th": 4, "last": -1}
_TIME = r"(?:noon|midnight|\d{1,2}(?::\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)?)"
_MONTH = r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*"
_DATE = (rf"(?:\d{{4}}-\d{{2}}-\d{{2}}|\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTH}(?:,?\s+\d{{4}})?|"
         rf"{_MONTH}\s+\d{{1,2}}(?:st|nd|rd|th)?(?:,?\s+\d{{4}})?|today|tonight|tomorrow|next\s+{_DAY}|next\s+week)")
# Words that only join the others: "every day at 8 and 6pm on weekdays" leaves nothing else.
_FILLER = re.compile(r"\b(at|on|the|and|of|in|each|every|month|monthly|months|a|an|day|days|time|times|run|runs|it|"
                     r"please|starting|start|from|then|also|o'?clock|morning|evening|afternoon|night|daily|once)\b|"
                     r"[,.&]")
_PM_WORDS = re.compile(r"\b(evening|night|tonight|afternoon)\b")


def _day_number(word: str) -> int:
    """A day's name as its number: "mon" -> 0; "Thursdays" -> 3; "sun" -> 6."""
    return _DAY_BY_PREFIX[word.lower()[:3]]


def _blank(text: str, span: tuple[int, int]) -> str:
    """The text with one part made spaces, so every other part keeps its place: ("at 8 daily", (5, 10)) -> "at 8     "."""
    start, end = span
    return text[:start] + " " * (end - start) + text[end:]


def _clock_of(token: str, pm_hint: bool = False) -> str | None:
    """A spoken time as "HH:MM": "9" -> "09:00"; "9:15" -> "09:15"; "6pm" -> "18:00"; "12am" -> "00:00"; "noon" ->
    "12:00"; "25" -> None. pm_hint (the end of "9-6", or "evening at 8") makes a bare "6" into "18:00"."""
    token = token.strip().replace(".", "")
    if token == "noon":
        return "12:00"
    if token == "midnight":
        return "00:00"
    got = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", token)
    if got is None:
        return None
    hh = int(got.group(1))
    mm = int(got.group(2) or 0)
    half = got.group(3)
    if half == "pm" and hh < 12:
        hh += 12
    if half == "am" and hh == 12:
        hh = 0
    if half is None and pm_hint and 1 <= hh < 12:
        hh += 12
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return None
    return f"{hh:02d}:{mm:02d}"


def _date_of(text: str, today: date) -> date | None:
    """A spoken date: "today" -> today; "tomorrow" -> today + 1; "next fri" -> the coming Friday (after today);
    "next week" -> today + 7; "30 nov" / "nov 30" / "30th nov 2026" / "2026-11-30" -> that day (this year, or next
    year when it has passed); "31 feb" -> None."""
    text = " ".join(text.split())
    if text in ("today", "tonight"):
        return today
    if text == "tomorrow":
        return today + timedelta(days=1)
    if text == "next week":
        return today + timedelta(days=7)
    if text.startswith("next "):
        weekday = _day_number(text[5:])
        ahead = (weekday - today.weekday()) % 7 or 7
        return today + timedelta(days=ahead)
    iso = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", text)
    if iso:
        try:
            return date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        except ValueError:
            return None
    day_first = re.fullmatch(rf"(\d{{1,2}})(?:st|nd|rd|th)?\s+({_MONTH})(?:,?\s+(\d{{4}}))?", text)
    month_first = re.fullmatch(rf"({_MONTH})\s+(\d{{1,2}})(?:st|nd|rd|th)?(?:,?\s+(\d{{4}}))?", text)
    if day_first:
        day_text, month_text, year = day_first.groups()
    elif month_first:
        month_text, day_text, year = month_first.groups()
    else:
        return None
    month = _MONTHS.get(month_text[:3])
    try:
        when = date(int(year) if year else today.year, month, int(day_text))
    except (TypeError, ValueError):
        return None
    if not year and when < today:
        when = when.replace(year=when.year + 1)
    return when


def _days_in(text: str) -> tuple[list[int] | None, str]:
    """The weekdays a text names, and the text without them: "weekdays at 9" -> ([0..4], "         at 9");
    "mon-fri" -> [0..4]; "mon to wed and fri" -> [0, 1, 2, 4]; "every day" / "daily" -> [0..6]; "weekends" ->
    [5, 6]; nothing named -> (None, text)."""
    found: set[int] = set()
    named = False
    patterns = [
        (rf"\b({_DAY})\s*(?:-|to|through|thru)\s*({_DAY})\b", None),
        (r"\b(?:every\s*day|everyday|each\s+day|daily|all\s+week)\b", ALL_DAYS),
        (r"\b(?:weekdays?|working\s+days|work\s+days|business\s+days)\b", WEEKDAYS),
        (r"\bweekends?\b", WEEKENDS),
        (rf"\b({_DAY})\b", None),
    ]
    for pattern, days in patterns:
        spans = []
        for got in re.finditer(pattern, text):
            if days is not None:
                found.update(days)
            elif got.lastindex == 2:
                first, last = _day_number(got.group(1)), _day_number(got.group(2))
                if first <= last:
                    found.update(range(first, last + 1))
                else:
                    found.update([*range(first, 7), *range(0, last + 1)])  # "fri-mon"
            else:
                found.add(_day_number(got.group(1)))
            named = True
            spans.append(got.span())
        for span in spans:
            text = _blank(text, span)
    if not named:
        return None, text
    return sorted(found), text


def parse(text: str, now: datetime, zone: ZoneInfo) -> dict | str:
    """The user's words as a stored schedule (clean() applied), or a line saying what wasn't understood. `now` (UTC)
    places "today", "tomorrow" and dates. Worked examples (now: Mon 16 Nov 2026, 10:00 IST):
      "every day at 8"                   -> daily ["08:00"] every day
      "weekdays at 9:15 and 6pm"          -> daily ["09:15", "18:00"] [0..4]
      "mondays and thursdays at 7am"      -> daily ["07:00"] [0, 3]
      "every evening at 8"                -> daily ["20:00"]
      "every 30 minutes"                  -> every 30, all day, every day
      "every 2 hours from 9 to 6 weekdays" / "every 2 hours 9-6 on weekdays" -> every 120 from 09:00 to 18:00 [0..4]
      "hourly"                            -> every 60
      "1st and 15th at 9" / "monthly on the 1st at 9" -> monthly dates [1, 15] / [1] at 09:00
      "last friday of the month at 5pm"   -> monthly nth [[-1, 4]] at 17:00
      "last day of the month at 18:00"    -> monthly dates [-1]
      "tomorrow 3pm" / "once on 20 nov at 15:00" -> once 2026-11-17T15:00 / 2026-11-20T15:00
      "every day at 8 until 30 nov" / "every day at 8 for 2 weeks" -> daily … until 2026-11-30 / 2026-11-30
      "every day at 8 except holidays"    -> 'I didn't follow "except holidays". Try …'
      "every 5 minutes"                   -> "Every 15 minutes at the most often.\""""
    original = " ".join((text or "").split())
    if not original:
        return "Say when it should run. " + HELP
    work = " " + original.lower().replace("–", "-").replace("—", "-").rstrip(".") + " "
    today = now.astimezone(zone).date()
    pm_hint = _PM_WORDS.search(work) is not None

    # The end: "until 30 nov", "for 2 weeks".
    until = None
    got = re.search(rf"\b(?:until|till|til|through|thru|up\s+to)\s+(?:the\s+)?({_DATE})\b", work)
    if got:
        until = _date_of(got.group(1), today)
        if until is None:
            return f'I didn\'t follow the end date "{got.group(1)}".'
        work = _blank(work, got.span())
    got = re.search(rf"\bfor\s+(?:the\s+next\s+)?(\d+|{_COUNT_WORDS})\s+(days?|weeks?|months?)\b", work)
    if got and until is None:
        amount = got.group(1)
        count = int(amount) if amount.isdigit() else _NUMBER_WORDS[amount]
        unit_days = {"d": 1, "w": 7, "m": 30}[got.group(2)[0]]
        until = today + timedelta(days=count * unit_days)
        work = _blank(work, got.span())

    # A day for a single run: "tomorrow", "20 nov", "next fri".
    once_day = None
    got = re.search(rf"(?<![\w-])({_DATE})\b", work)
    if got:
        once_day = _date_of(got.group(1), today)
        if once_day is None:
            return f'I didn\'t follow the date "{got.group(1)}".'
        work = _blank(work, got.span())

    # Hours for "every …": "from 9 to 6", "9-6".
    window = None
    got = re.search(rf"\b(?:from|between)\s+({_TIME})\s*(?:to|and|-|until|till)\s*({_TIME})(?![\w:])", work)
    if got is None:
        got = re.search(rf"(?<![\w:])({_TIME})\s*-\s*({_TIME})(?![\w:])", work)
    if got:
        start = _clock_of(got.group(1))
        end = _clock_of(got.group(2))
        if start and end and end <= start:
            end = _clock_of(got.group(2), pm_hint=True)  # "9-6": 9 in the morning to 6 in the evening
        if not start or not end:
            return f'I didn\'t follow the hours "{got.group(0).strip()}".'
        window = (start, end)
        work = _blank(work, got.span())

    # How often: "every 30 minutes", "every 2 hours", "hourly", "every half hour".
    every = None
    got = re.search(r"\bevery\s+(half\s+an?\s+hour|half\s+hour|quarter\s+hour)\b", work)
    if got:
        every = 15 if "quarter" in got.group(1) else 30
        work = _blank(work, got.span())
    if every is None:
        got = re.search(r"\bhourly\b", work)
        if got:
            every = 60
            work = _blank(work, got.span())
    if every is None:
        got = re.search(rf"\bevery\s+(?:(\d+|{_COUNT_WORDS})\s*)?(minutes?|mins?|hours?|hrs?|h|m)\b", work)
        if got:
            amount = got.group(1)
            if amount is None:
                count = 1
            elif amount.isdigit():
                count = int(amount)
            else:
                count = _NUMBER_WORDS[amount]
            every = count * (60 if got.group(2).startswith("h") else 1)
            work = _blank(work, got.span())

    # Not something a schedule here can say: every few days or weeks. Weekly needs its day.
    if re.search(rf"\bevery\s+(?:\d+|{_COUNT_WORDS})\s+(?:days|weeks)\b|\bevery\s+other\s+(?:day|week)\b", work):
        return "Every few days isn't something I can do yet: pick the days instead, like 'mon, wed, fri at 9'."
    weekly = re.search(r"\b(?:weekly|every\s+week|each\s+week|once\s+a\s+week)\b", work)
    if weekly:
        work = _blank(work, weekly.span())

    # Days of the month: "1st and 15th", "last day", "last friday", "second monday".
    dates: list[int] = []
    nth: list[list[int]] = []
    for got in list(re.finditer(rf"\b(first|second|third|fourth|last|1st|2nd|3rd|4th)\s+({_DAY})\b", work)):
        nth.append([_ORDINAL_WORDS[got.group(1)], _day_number(got.group(2))])
        work = _blank(work, got.span())
    for got in list(re.finditer(r"\blast\s+day\b", work)):
        dates.append(-1)
        work = _blank(work, got.span())
    for got in list(re.finditer(r"\b(\d{1,2})(?:st|nd|rd|th)\b", work)):
        dates.append(int(got.group(1)))
        work = _blank(work, got.span())
    said_monthly = re.search(r"\b(monthly|every\s+month|each\s+month|of\s+the\s+month)\b", work) is not None
    monthly = bool(dates or nth) or said_monthly

    days, work = _days_in(work)
    if weekly and days is None:
        return "Say which day of the week, like 'every monday at 9'."

    # Times: "at 8", "9:15", "6pm", "at 9, 12 and 6pm", "noon".
    times = []
    for got in list(re.finditer(rf"(?<![\w:])({_TIME})(?![\w:])", work)):
        token = got.group(1)
        bare_number = re.fullmatch(r"\d{1,2}", token.strip()) is not None
        said_as_time = re.search(r"\b(at|and)\s*$|[,&]\s*$", work[:got.start()]) is not None
        if bare_number and not said_as_time:
            continue  # a lone number that isn't said as a time: the leftover check names it
        clock = _clock_of(token, pm_hint=pm_hint and "am" not in token)
        if clock is None:
            return f'I didn\'t follow the time "{token.strip()}".'
        times.append(clock)
        work = _blank(work, got.span())

    leftover = " ".join(_FILLER.sub(" ", work).split())
    if leftover:
        return f'I didn\'t follow "{leftover}". {HELP}'

    if every is not None:
        start, end = window or (times[0] if times else "00:00", "23:59")
        schedule = {"kind": "every", "minutes": every, "from": start, "to": end, "days": days}
    elif once_day is not None and not monthly and days is None:
        if not times:
            return "Say a time for it, like tomorrow 3pm."
        if len(times) > 1:
            return "Once means one time: say one time, or say which days to repeat on."
        schedule = {"kind": "once", "at": f"{once_day.isoformat()}T{times[0]}"}
    elif monthly:
        if not dates and not nth:
            return "Say which days of the month, like the 1st and 15th."
        schedule = {"kind": "monthly", "times": times, "dates": dates, "nth": nth}
    elif times:
        schedule = {"kind": "daily", "times": times, "days": days}
    else:
        return "Say a time for it. " + HELP
    if until:
        schedule["until"] = until.isoformat()
    cleaned = clean(schedule)
    if isinstance(cleaned, str):
        return cleaned
    if next_run(cleaned, now, zone) is None:
        if cleaned["kind"] == "once":
            return "That time has passed."
        return "It has no runs left before it ends."
    return cleaned
