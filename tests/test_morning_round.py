"""One morning round: the brief when it's due, and the day's hello, saved once a day."""
import asyncio
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from odie.jobs import brief as brief_mod
from odie.jobs.brief import BriefInputs, missed_today
from odie.morning import round as round_mod
from odie.morning import write
from odie.morning.gather import MorningInputs
from odie.morning.round import hello_due, hello_for, morning_day, morning_round
from odie.store.db import Store

IST = ZoneInfo("Asia/Kolkata")


def at(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=IST)


def store_at(tmp_path) -> Store:
    db_path = tmp_path / "a.db"
    assert db_path.parent == tmp_path
    s = Store(db_path)
    s.init_schema()
    return s


def card_answer(greeting: str = "Morning, Asha. Two days to the launch") -> str:
    return json.dumps({
        "greeting": greeting, "accent": "launch", "emoji": "",
        "say": ["How was the design review?"], "tiles": [], "nudge": None, "mail": [], "recent": [],
        "chips": ["Plan my day", "Fix the reporter"], "summary": "The day: a design review, the reporter open.",
    })


def plain_gather(seen: list | None = None):
    """A stand-in for the hello's gatherer (no chats, memories or mail read): the brief's tasks pass through."""
    async def fake(store, now, brief):
        if seen is not None:
            seen.append(brief)
        return MorningInputs(day="Wednesday 4 November 2026", user="Asha", chats="", memories="", mail="",
                             yesterday="", upcoming="", tasks=brief.tasks, brief_parts="", weather=None)
    return fake


def a_model(monkeypatch, prompts: list):
    async def answer(store, role, messages, **kw):
        prompts.append(messages[-1]["content"])
        return card_answer()
    monkeypatch.setattr(write, "chat_completion", answer)


def a_brief_writer(monkeypatch, prompts: list):
    async def fake_write(prompt, store=None):
        prompts.append(prompt)
        return "The invoice is due Friday."
    monkeypatch.setattr(brief_mod, "write_with_model", fake_write)
    monkeypatch.setattr(brief_mod, "send_to_all", lambda *a, **k: 1)


class Runner:
    def __init__(self):
        self.invalidated = 0

    async def post_message(self, text, session_id=None):
        pass

    def invalidate_prompt(self):
        self.invalidated += 1


def watch_card_with_a_held_item(store):
    from odie.watch import report
    store.set_setting(report.CARD, {"needs_you": [{"title": "Invoice due Friday", "why": "from Dev"}], "events": []})
    store.set_setting(report.HELD, [{"ref": "mail:m9", "title": "Passport email came", "why": "at 23:10"}])


def test_morning_day_starts_at_five():
    assert morning_day(at(5, 4, 30)) == "2026-11-04"  # before five: still yesterday's hello
    assert morning_day(at(5, 5, 0)) == "2026-11-05"
    assert morning_day(at(5, 23, 59)) == "2026-11-05"


def test_no_hello_is_due_before_five(tmp_path):
    s = store_at(tmp_path)
    assert hello_due(s, at(5, 4, 30)) is False
    assert hello_due(s, at(5, 5, 0)) is True


async def test_one_hello_a_day_even_when_asked_twice(tmp_path, monkeypatch):
    s = store_at(tmp_path)
    monkeypatch.setattr(round_mod, "gather", plain_gather())
    brief_prompts = []
    a_brief_writer(monkeypatch, brief_prompts)
    started = asyncio.Event()
    release = asyncio.Event()
    calls = []

    async def slow_model(store, role, messages, **kw):
        calls.append(1)
        started.set()
        await release.wait()
        return card_answer()
    monkeypatch.setattr(write, "chat_completion", slow_model)

    async def second_while_the_first_writes():
        await started.wait()
        await morning_round(s, at(4, 7, 30), push=False)  # returns at once: one is running
        release.set()

    await asyncio.gather(morning_round(s, at(4, 7, 30), push=False), second_while_the_first_writes())
    assert calls == [1]
    assert len(brief_prompts) == 1
    assert s.one("select count(*) n from mornings")["n"] == 1
    assert s.one("select count(*) n from briefs")["n"] == 1

    await morning_round(s, at(4, 9, 0), push=False)  # later the same day: nothing is due
    assert calls == [1]
    assert s.one("select count(*) n from mornings")["n"] == 1


async def test_a_hello_only_round_leaves_the_held_list(tmp_path, monkeypatch):
    from odie.watch import report
    s = store_at(tmp_path)
    watch_card_with_a_held_item(s)
    brief_prompts = []
    a_brief_writer(monkeypatch, brief_prompts)
    seen = []
    monkeypatch.setattr(round_mod, "gather", plain_gather(seen))
    a_model(monkeypatch, [])

    await morning_round(s, at(4, 6, 10), push=False)
    assert hello_for(s, "2026-11-04") is not None
    assert brief_prompts == []  # the brief's time hasn't come
    assert [i["ref"] for i in s.get_setting(report.HELD)] == ["mail:m9"]  # left for the brief
    [watch] = [p for p in seen[0].parts if p.key == "watch"]
    assert "Passport email came" in watch.text  # the hello saw it too

    await morning_round(s, at(4, 7, 30), push=False)
    assert s.get_setting(report.HELD) == []
    assert len(brief_prompts) == 1 and "Passport email came" in brief_prompts[0]
    assert s.one("select count(*) n from mornings")["n"] == 1


async def test_the_seven_thirty_round_gathers_once_for_both(tmp_path, monkeypatch):
    s = store_at(tmp_path)
    a_brief_writer(monkeypatch, [])
    gathered = []

    async def counting_gather_inputs(store, now, post_message=None, clear_held=True):
        gathered.append(clear_held)
        return BriefInputs(tasks="#1 [todo] Answer Asha")
    monkeypatch.setattr(round_mod, "gather_inputs", counting_gather_inputs)
    monkeypatch.setattr(brief_mod, "gather_inputs", counting_gather_inputs)  # run_brief must not gather again
    seen = []
    monkeypatch.setattr(round_mod, "gather", plain_gather(seen))
    prompts = []
    a_model(monkeypatch, prompts)

    await morning_round(s, at(4, 7, 30), push=False)
    assert gathered == [True]
    assert seen[0].tasks == "#1 [todo] Answer Asha"
    assert s.one("select text from briefs")["text"] == "The invoice is due Friday."
    assert "The morning brief's line:\nThe invoice is due Friday." in prompts[0]


async def test_an_afternoon_start_still_makes_the_hello(tmp_path, monkeypatch):
    s = store_at(tmp_path)
    now = at(4, 15, 0)
    assert hello_due(s, now) is True
    assert missed_today(s, now) is False
    brief_prompts = []
    a_brief_writer(monkeypatch, brief_prompts)
    gathered = []

    async def counting_gather_inputs(store, now, post_message=None, clear_held=True):
        gathered.append(clear_held)
        return BriefInputs(tasks="")
    monkeypatch.setattr(round_mod, "gather_inputs", counting_gather_inputs)
    monkeypatch.setattr(round_mod, "gather", plain_gather())
    a_model(monkeypatch, [])

    await morning_round(s, now, push=False)
    assert gathered == [False]
    assert brief_prompts == []
    assert s.one("select count(*) n from briefs")["n"] == 0
    assert hello_for(s, "2026-11-04")["card"]["greeting"].startswith("Morning, Asha")
    assert hello_due(s, now) is False


async def test_a_saved_hello_rebuilds_open_chats_prompts(tmp_path, monkeypatch):
    s = store_at(tmp_path)
    monkeypatch.setattr(round_mod, "gather", plain_gather())
    a_model(monkeypatch, [])
    runner = Runner()

    await morning_round(s, at(4, 15, 0), runner=runner)
    assert runner.invalidated == 1
    hello = hello_for(s, "2026-11-04")
    assert hello["summary"] == "The day: a design review, the reporter open."
    assert hello["card"]["day"] == "2026-11-04"
    assert hello["made_at"] == "2026-11-04T15:00:00+05:30"
    saved = json.loads(s.one("select inputs_json from mornings")["inputs_json"])
    assert saved["user"] == "Asha"


async def test_a_round_just_after_midnight_keeps_the_mornings_day(tmp_path, monkeypatch):
    """A hello made at 05:00 belongs to that day; the saved card's day is the morning's day, not write_card's."""
    s = store_at(tmp_path)
    monkeypatch.setattr(round_mod, "gather", plain_gather())
    a_model(monkeypatch, [])

    async def card_with_another_day(store, now, inp):
        return {**json.loads(card_answer()), "day": "1999-01-01", "made_at": now.isoformat(timespec="seconds"),
                "weather": None, "fallback": False}
    monkeypatch.setattr(round_mod, "write_card", card_with_another_day)

    await morning_round(s, at(5, 5, 0), push=False)
    assert hello_for(s, "2026-11-05")["card"]["day"] == "2026-11-05"


async def test_yesterdays_hello_and_todays_brief_feed_the_writer(tmp_path, monkeypatch):
    s = store_at(tmp_path)
    yesterday = {"greeting": "Morning, Asha. Rain again", "say": ["Did the reporter run?", "Start with the invoice?"]}
    s.execute("insert into mornings(day, card_json, summary, made_at) values(?,?,?,?)",
              ("2026-11-03", json.dumps(yesterday), "x", "2026-11-03T07:30:00+05:30"))
    s.execute("insert into briefs(date, text, items_json) values(?,?,?)", ("2026-11-04", "Dentist at 10.", "{}"))
    monkeypatch.setattr(round_mod, "gather", plain_gather())
    prompts = []
    a_model(monkeypatch, prompts)

    await morning_round(s, at(4, 15, 0), push=False)
    assert ("Your hello yesterday (say something different today):\n"
            "Morning, Asha. Rain again\nDid the reporter run?\nStart with the invoice?") in prompts[0]
    assert "The morning brief's line:\nDentist at 10." in prompts[0]


async def test_with_nothing_connected_the_hello_is_still_written(tmp_path, monkeypatch, isolated_settings):
    assert isolated_settings.sessions_db_path.parent == tmp_path
    s = store_at(tmp_path)
    a_model(monkeypatch, [])

    await morning_round(s, at(4, 15, 0), push=False)
    hello = hello_for(s, "2026-11-04")
    assert hello is not None and hello["card"]["fallback"] is False
