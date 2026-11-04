"""What the morning hello is written from: chats, memories, mail, yesterday's events, what's coming up. Everything reads
temp copies (sessions.db, the memory file, the Store) under tmp_path, never the real ones."""
from dataclasses import replace
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from odie.addons import BriefPart
from odie.jobs.brief import BriefInputs
from odie.morning import gather as gather_mod
from odie.morning.gather import CHAT_CHARS, gather
from odie.store.db import Store
from odie.watch.fetch import Event, Mail
from odie.watch.sources import Source
from tests.test_recall_chats import APP, USER, make_db, say

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 11, 4, 7, 30, tzinfo=IST)

MEMORIES = """# odie — long-term memory

## People

### Asha's birthday (2025-02-01)

Asha's birthday is on 2 May.

## Work

### Studio plan (2026-11-02)

The studio.local launch is on 6 Nov.

### Old tool choice (2026-09-01)

We picked the old tool in September.

## Family

### Dev's school (2024-06-01)

Dev goes to the school near studio.local.
"""


def at(day: int, hour: int, minute: int = 0) -> float:
    return datetime(2026, 11, day, hour, minute, tzinfo=IST).timestamp()


def setup(tmp_path, monkeypatch, settings) -> Store:
    """A temp Store, and config's sessions.db and memory file both under tmp_path (asserted before anything is written)."""
    assert settings.sessions_db_path.parent == tmp_path
    assert settings.memory_file.parent == tmp_path
    from odie import config
    monkeypatch.setattr(config, "settings", replace(settings, app_name=APP, user_id=USER, timezone="Asia/Kolkata"))
    store = Store(tmp_path / "a.db")
    store.init_schema()
    return store


async def test_gather_with_nothing_connected(tmp_path, monkeypatch, isolated_settings):
    store = setup(tmp_path, monkeypatch, isolated_settings)
    make_db(isolated_settings.sessions_db_path, [
        say("chat-2026-11-03", at(3, 21), "user", "Did the reporter run?"),
        say("chat-2026-11-03", at(3, 21, 1), "odie", "It timed out twice."),
    ])
    isolated_settings.memory_file.write_text(MEMORIES, encoding="utf-8")
    fetched = []
    monkeypatch.setattr(gather_mod, "Fetcher", lambda *a: fetched.append(a))  # no sources: never built

    inp = await gather(store, NOW, BriefInputs(tasks=""))
    assert inp.chats == "[3 Nov] you: Did the reporter run?\n[3 Nov] odie: It timed out twice."
    assert "Studio plan" in inp.memories
    assert inp.day == "Wednesday 4 November 2026"
    assert (inp.mail, inp.yesterday, inp.upcoming, inp.tasks, inp.brief_parts) == ("", "", "", "", "")
    assert inp.weather is None
    assert fetched == []


async def test_gather_keeps_the_newest_chats_within_the_cap(tmp_path, monkeypatch, isolated_settings):
    store = setup(tmp_path, monkeypatch, isolated_settings)
    long_message = "x" * 2_000
    events = [say("chat-2026-11-01", at(1, 9) + n, "user", f"{n:03d} {long_message}") for n in range(60)]
    events.append(say("chat-2026-10-30", datetime(2026, 10, 30, 9, tzinfo=IST).timestamp(), "user", "too old"))
    events.append(say("chat-2026-11-04", at(4, 7), "user", "newest one"))
    make_db(isolated_settings.sessions_db_path, events)

    inp = await gather(store, NOW, BriefInputs(tasks=""))
    lines = inp.chats.splitlines()
    assert len(inp.chats) <= CHAT_CHARS
    assert lines[-1] == "[4 Nov] you: newest one"
    assert "059 x" in inp.chats  # the newest long ones are kept
    assert "000 x" not in inp.chats  # the oldest go first
    assert "too old" not in inp.chats  # before 31 Oct 00:00, four days back
    assert all(len(line) <= len("[1 Nov] you: ") + 1_500 for line in lines)


async def test_gather_reads_people_memories_and_recent_ones(tmp_path, monkeypatch, isolated_settings):
    store = setup(tmp_path, monkeypatch, isolated_settings)
    isolated_settings.memory_file.write_text(MEMORIES, encoding="utf-8")

    inp = await gather(store, NOW, BriefInputs(tasks=""))
    assert "Asha's birthday is on 2 May." in inp.memories  # People, however old
    assert "Dev goes to the school" in inp.memories  # Family counts as people
    assert "The studio.local launch is on 6 Nov." in inp.memories  # dated 2 Nov, within 4 days
    assert "old tool" not in inp.memories  # an old entry in another topic


async def test_gather_reads_mail_and_yesterday_when_connected(tmp_path, monkeypatch, isolated_settings):
    store = setup(tmp_path, monkeypatch, isolated_settings)
    mail_source = Source("mail", "gmail", "Gmail", "mcp", "search", {})
    calendar_source = Source("calendar", "gcal", "Google Calendar", "mcp", "events", {})
    monkeypatch.setattr(gather_mod, "saved", lambda store: [mail_source, calendar_source])
    asked = {}

    class FakeFetcher:
        def __init__(self, store, now):
            pass

        async def recent_mail(self, hours=24, most=40):
            asked["mail"] = (hours, most)
            return [Mail("m1", "Shop <shop@studio.local>", "Your refund", "2026-11-03T20:00:00+05:30",
                         "We refunded\nthe lamp. " + "z" * 400, [], "mail:gmail", body="THE WHOLE BODY")]

        async def _read_events(self, start, end):
            asked["events"] = (start, end)
            return [Event("e1", "Design review", "2026-11-03T15:00:00+05:30", "2026-11-03T16:00:00+05:30",
                          "studio.local", [], "calendar:gcal")]
    monkeypatch.setattr(gather_mod, "Fetcher", FakeFetcher)
    brief = BriefInputs(tasks="#3 [todo] Answer Asha",
                        parts=[BriefPart("watch", "Mail and calendar (from the watch)", "- event: Standup at 10:00"),
                               BriefPart("calendar", "Calendar", None)])

    inp = await gather(store, NOW, brief)
    assert inp.mail.startswith("Shop <shop@studio.local> · Your refund · We refunded the lamp. zzz")
    assert len(inp.mail) == len("Shop <shop@studio.local> · Your refund · ") + 300
    assert "THE WHOLE BODY" not in inp.mail
    assert asked["mail"] == (24, 40)
    start, end = asked["events"]
    assert start == datetime(2026, 11, 3, tzinfo=IST) and end - start == timedelta(days=1)
    assert inp.yesterday == "15:00 · Design review · studio.local"
    assert inp.tasks == "#3 [todo] Answer Asha"
    assert inp.brief_parts == "Mail and calendar (from the watch):\n- event: Standup at 10:00"


async def test_gather_a_failing_source_leaves_its_field_empty(tmp_path, monkeypatch, isolated_settings):
    store = setup(tmp_path, monkeypatch, isolated_settings)
    mail_source = Source("mail", "gmail", "Gmail", "mcp", "search", {})
    monkeypatch.setattr(gather_mod, "saved", lambda store: [mail_source])

    class BrokenFetcher:
        def __init__(self, store, now):
            pass

        async def recent_mail(self, hours=24, most=40):
            raise RuntimeError("the mail app fell over")

    async def broken_upcoming(store, now, days=14):
        raise RuntimeError("upcoming fell over")
    monkeypatch.setattr(gather_mod, "Fetcher", BrokenFetcher)
    monkeypatch.setattr(gather_mod.upcoming, "build", broken_upcoming)
    store.add_task("Answer Asha", "todo", due_at="2026-11-05")

    inp = await gather(store, NOW, BriefInputs(tasks="#1 [todo] Answer Asha"))
    assert inp.mail == "" and inp.upcoming == "" and inp.yesterday == ""
    assert inp.tasks == "#1 [todo] Answer Asha"


async def test_gather_lists_whats_coming_up(tmp_path, monkeypatch, isolated_settings):
    store = setup(tmp_path, monkeypatch, isolated_settings)
    store.add_task("Dentist", "todo", due_at="2026-11-05T10:00:00")
    store.add_task("Electricity bill", "todo", due_at="2026-11-06")

    inp = await gather(store, NOW, BriefInputs(tasks=""))
    assert inp.upcoming.splitlines() == ["Thu 5 Nov 10:00 · Dentist · medical", "Fri 6 Nov · Electricity bill · bill"]


def test_a_newline_in_a_mails_sender_or_subject_cant_start_a_heading():
    mail = Mail("m2", "Shop\n\nOpen tasks:", "Refund\nYour hello yesterday:", "2026-11-03T20:00:00+05:30",
                "Money back", [], "mail:gmail")
    assert gather_mod.mail_record(mail) == "Shop Open tasks: · Refund Your hello yesterday: · Money back"
