from datetime import datetime
from zoneinfo import ZoneInfo


from odie.jobs.brief import BriefInputs, gather_inputs, render_prompt, run_brief
from odie.store.db import Store

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 10, 1, 7, 30, tzinfo=IST)


def test_render_prompt_mentions_only_what_is_available():
    from odie.addons import BriefPart
    inp = BriefInputs(tasks="#1 [waiting] Waiting on Rahul\n#2 [reminder] Electricity ₹2,480 · due 2026-10-12",
                      parts=[BriefPart("calendar", "Calendar", None)])
    p = render_prompt(NOW, inp)
    assert "Thursday 1 October" in p and "Electricity" in p and "Rahul" in p
    assert "Calendar:\n(not connected yet)" in p
    assert "mail" not in p.lower()  # no add-on brought any


async def test_gather_inputs_without_addons_is_the_task_list(tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    s.add_task("Answer Asha", "todo", due_at="2026-10-03")
    inp = await gather_inputs(s, NOW)
    assert inp.parts == [] and "Asha" in inp.tasks


async def test_run_brief_stores_and_pushes(monkeypatch, tmp_path):
    import odie.jobs.brief as b
    s = Store(tmp_path / "a.db")
    s.init_schema()

    async def fake_gather(store, now, **kw):
        return BriefInputs(tasks="#1 [reminder] Dentist at 10")

    async def fake_write(prompt, store=None):
        return "Dentist at 10. Nothing else needs you."
    pushed = []
    monkeypatch.setattr(b, "gather_inputs", fake_gather)
    monkeypatch.setattr(b, "write_with_model", fake_write)
    monkeypatch.setattr(b, "send_to_all", lambda store, title, body, url="/", tag=None: pushed.append((title, body, url)) or 1)
    posted = []

    async def post(text, session_id=None):
        posted.append((text, session_id))
    text = await run_brief(s, NOW, post_message=post)
    assert text.startswith("Dentist at 10")
    row = s.one("select * from briefs order by id desc")
    assert row["date"] == "2026-10-01" and row["text"] == text
    assert pushed == [("Good morning", "Dentist at 10. Nothing else needs you.", "/#today")]  # nothing needs them yet
    assert posted == []  # the cards are on Today, not in a conversation
    assert s.one("select count(*) n from audit_log where event='brief'")["n"] == 1


async def test_brief_lists_open_tasks_with_ids_and_skips_snoozed(tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    t1, _ = s.upsert_source_task("ledger", "7", "ICICI card ₹12,345", "reminder", due_at="2026-09-29")
    t2, _ = s.upsert_source_task("ledger", "4", "Electricity ₹2,480", "reminder", due_at="2026-10-12")
    s.snooze_task(t2, "2026-10-05T09:00:00+05:30")
    inp = await gather_inputs(s, NOW)
    p = render_prompt(NOW, inp)
    assert f"#{t1}" in p and "ICICI" in p and "Electricity" not in p
    assert "Dues and deadlines" not in p  # raw ledger text no longer feeds the brief


async def test_the_watchs_threads_are_not_listed_as_needing_the_user(tmp_path):
    """The watch follows orders and replies on its own and shows what needs the user on its card; listing its threads
    as open threads too counted them twice, and an order in transit read as "needs you"."""
    from odie.watch import threads
    s = Store(tmp_path / "a.db")
    s.init_schema()
    s.add_task("Answer Asha", "todo", due_at="2026-10-03")
    threads.track(s, "mail:o1", "order", "Order: desk lamp", "shipped", due="2026-10-02")
    inp = await gather_inputs(s, NOW)
    assert "Asha" in inp.tasks
    assert "desk lamp" not in inp.tasks


async def test_manual_brief_does_not_push(monkeypatch, tmp_path):
    import odie.jobs.brief as b
    s = Store(tmp_path / "a.db")
    s.init_schema()

    async def fake_gather(store, now, **kw):
        return BriefInputs(tasks="")

    async def fake_write(prompt, store=None):
        return "Nothing needs you."
    pushed = []
    monkeypatch.setattr(b, "gather_inputs", fake_gather)
    monkeypatch.setattr(b, "write_with_model", fake_write)
    monkeypatch.setattr(b, "send_to_all", lambda *a, **k: pushed.append(1) or 1)
    await run_brief(s, NOW, push=False)
    assert pushed == []


def test_brief_system_without_addons_has_no_mail_or_calendar():
    from odie.jobs.brief import brief_system
    text = brief_system("")
    assert "not connected" in text.lower() and "mail" not in text.lower() and "calendar" not in text.lower()


def test_turn_context_says_brief_is_not_a_calendar():
    from odie.agent.prompt import build_turn_context
    out = build_turn_context(NOW, "", "", "", "Schedule is clear.")
    assert "calendar_list_events" in out and "Schedule is clear." in out



async def test_the_morning_ping_counts_what_needs_the_user_and_opens_today(monkeypatch, tmp_path):
    # The cards live on Today's Needs you; the morning round is a ping that says how many and opens Today, never a
    # post in a conversation.
    import odie.jobs.brief as b
    from odie.watch import report
    s = Store(tmp_path / "a.db")
    s.init_schema()
    s.set_setting(report.CARD, {"needs_you": [
        {"ref": "mail:m1", "title": "Workshop invite", "why": "Asks your fee by Friday", "pile": "alerts", "done": False},
        {"ref": "mail:m2", "title": "Old thing", "why": "x", "done": True}]})
    s.add_task("Pay the gas bill", "reminder", due_at="2026-10-01T09:00+05:30")

    async def fake_write(prompt, store=None):
        return "Two things need you today."
    pushed = []
    monkeypatch.setattr(b, "write_with_model", fake_write)
    monkeypatch.setattr(b, "send_to_all", lambda store, title, body, url="/", tag=None: pushed.append((title, body, url)) or 1)
    posted = []

    async def post(text, session_id=None):
        posted.append((text, session_id))
    await run_brief(s, NOW, post_message=post)
    assert posted == []
    assert pushed == [("2 things need you", "Two things need you today.", "/#today")]


def test_the_opener_is_short():
    from odie.jobs.brief import brief_system
    assert "Two short sentences at most" in brief_system("Asha")


def test_a_missed_morning_round_runs_when_odie_starts_before_noon(tmp_path):
    """The Mac was off at 07:30: Odie starting at 11:21 sends the morning round then; after noon, or once it ran
    today, it doesn't."""
    from odie.jobs.brief import missed_today
    s = Store(tmp_path / "a.db")
    s.init_schema()
    assert missed_today(s, datetime(2026, 10, 23, 11, 21, tzinfo=IST)) is True
    assert missed_today(s, datetime(2026, 10, 23, 7, 0, tzinfo=IST)) is False   # its time hasn't come
    assert missed_today(s, datetime(2026, 10, 23, 12, 30, tzinfo=IST)) is False  # too late to be a morning round
    s.execute("insert into briefs(date, text, items_json) values(?,?,?)", ("2026-10-23", "x", "{}"))
    assert missed_today(s, datetime(2026, 10, 23, 11, 21, tzinfo=IST)) is False  # it ran
