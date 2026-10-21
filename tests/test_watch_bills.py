"""Bills, payments and orders in the watch (odie.watch.bills): a bill goes on the calendar with a reminder, a payment
confirmation closes its reminder and marks the event paid, an order's event follows its status, a once-only catch-up
reads the last 30 days of such mail, Up next reads two weeks and shows a done item as done, and the user sees (and can
undo) what the watch closed."""
import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import httpx
import pytest

from odie import upcoming
from odie.store.db import Store
from odie.watch import bills, check, fetch, report, sources
from tests.test_watch_calls import spec_for

NOW = datetime(2026, 10, 21, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))

BILL = {"id": "b1", "from": "bills@utility.example", "subject": "Your electricity bill of Rs 4,280 is due on 09-Nov-2026",
        "date": "2026-10-20T08:00:00Z", "body_plain": "Consumer 1234. Amount Rs 4,280. Due 09-Nov-2026."}
ORDER = {"id": "o1", "from": "shipment-tracking@shop.example", "subject": "Your order of Wireless Earbuds has shipped",
         "date": "2026-10-02T08:00:00Z", "body_plain": "Arriving Friday 24 October."}
CHAT = {"id": "c1", "from": "friend@example.com", "subject": "Lunch tomorrow?", "date": "2026-10-19T08:00:00Z", "body_plain": "Hi"}
SOON = {"id": "e1", "summary": "Pay electricity bill - Rs 4,280", "start": {"dateTime": "2026-11-09T09:00:00+05:30"},
        "end": {"dateTime": "2026-11-09T09:20:00+05:30"}}


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


async def connect(store, tmp_path, mail=(), events=()):
    """A plain mail-and-calendar app, detected as the watch's sources; returns the file its calls are logged in."""
    from odie.plugins import mcp
    mcp.write_config({"mymail": spec_for("plain", tmp_path, mail=mail, events=events)})
    await sources.detect_and_save(store)
    return tmp_path / "calls.log"


def logged(log_file, tool):
    lines = [json.loads(line) for line in log_file.read_text().splitlines()]
    return [line["args"] for line in lines if line["tool"] == tool]


async def call(tools, tool_name, **args):
    tool = next(t for t in tools if t.name == tool_name)
    return await tool.run_async(args=args, tool_context=SimpleNamespace())


# ── what counts as a bill, a payment or an order ──

@pytest.mark.parametrize(("subject", "counts"), [
    ("Your electricity bill of Rs 4,280 is due on 09-Nov-2026", True),
    ("Your order of Wireless Earbuds has shipped", True),
    ("Payment received: thank you", True),
    ("Your credit card statement for October", True),
    ("Out for delivery today", True),
    ("Lunch tomorrow?", False),
    ("Diwali sale: 50% off everything", False),
])
def test_what_looks_like_a_bill_a_payment_or_an_order(subject, counts):
    assert bills.looks_like_bill_or_order(subject) is counts


@pytest.mark.parametrize(("title", "state", "plain"), [
    ("✓ Paid · Pay electricity bill - Rs 4,280", "paid", "Pay electricity bill - Rs 4,280"),
    ("✓ Delivered · Order: Wireless Earbuds", "delivered", "Order: Wireless Earbuds"),
    ("✗ Cancelled · Order: Wireless Earbuds", "cancelled", "Order: Wireless Earbuds"),
    ("Pay electricity bill - Rs 4,280", None, "Pay electricity bill - Rs 4,280"),
])
def test_a_done_mark_on_an_event_title(title, state, plain):
    assert bills.done_state(title) == (state, plain)


# ── reminders the watch may close, and the user may reopen ──

def test_the_watch_closes_an_open_reminder_with_its_reason_and_the_user_can_reopen_it(store):
    tid = store.add_task("Pay electricity bill - Rs 4,280", "reminder", due_at="2026-11-08T09:00+05:30")
    assert bills.close(store, tid, "paid: confirmation mail 21 Oct") == f"Closed reminder #{tid}."
    row = store.one("select * from tasks where id=?", (tid,))
    assert row["status"] == "done" and row["notes"] == "Closed by the watch: paid: confirmation mail 21 Oct"
    [closed] = bills.closed_by_watch(store, NOW - timedelta(days=3))
    assert (closed["id"], closed["why"]) == (tid, "paid: confirmation mail 21 Oct")
    assert bills.close(store, tid, "again") == f"Reminder #{tid} is already closed."
    bills.reopen(store, tid)
    row = store.one("select * from tasks where id=?", (tid,))
    assert row["status"] == "open" and not row["notes"]
    assert bills.closed_by_watch(store, NOW - timedelta(days=3)) == []


def test_closing_needs_a_reason_and_a_real_reminder(store):
    tid = store.add_task("Pay electricity bill - Rs 4,280", "reminder")
    assert bills.close(store, tid, "  ") == "Say why it's done (which mail showed it)."
    assert bills.close(store, 999, "paid") == "No reminder #999."


def test_the_open_bills_and_orders_are_the_reminders_that_look_like_one(store):
    bill = store.add_task("Pay electricity bill - Rs 4,280", "reminder", due_at="2026-11-08T09:00+05:30")
    order = store.add_task("Order: Wireless Earbuds arriving Fri", "reminder")
    store.add_task("Buy medicine", "reminder")
    paid = store.add_task("Pay card bill - Rs 9,999", "reminder")
    store.update_task(paid, status="done")
    assert [r["id"] for r in bills.open_bills_and_orders(store)] == [bill, order]


# ── the fetcher: the catch-up's mail, and two weeks of events for the card ──

async def test_the_catch_up_reads_30_days_of_bill_payment_and_order_mail_only(store, tmp_path):
    calls = await connect(store, tmp_path, mail=[BILL, ORDER, CHAT])
    f = fetch.Fetcher(store, NOW)
    got = await f.catch_up_mail()
    assert [m.id for m in got] == ["b1", "o1"]  # newest first, the lunch mail left out
    [args] = logged(calls, "search_emails")
    thirty_days_back = int((NOW - timedelta(days=30)).timestamp())
    assert args["query"].startswith(f"after:{thirty_days_back} ") and "subject:(" in args["query"]
    assert f.read_mail("o1").subject == ORDER["subject"]  # readable in full like new mail


async def test_the_card_reads_two_weeks_of_events_without_touching_the_checks_list(store, tmp_path):
    calls = await connect(store, tmp_path, events=[SOON])
    f = fetch.Fetcher(store, NOW)
    got = await f.events_ahead(14)
    assert [e.title for e in got] == ["Pay electricity bill - Rs 4,280"]
    [args] = logged(calls, "list_events")
    assert args["time_max"].startswith((NOW + timedelta(days=14)).date().isoformat())
    assert f._events == []  # the check's own events (moves and cancellations) are left alone


# ── the watch's tools, its permission, its catch-up and its card ──

def test_the_watch_may_update_a_calendar_event_but_still_never_edit_a_task():
    assert check.guard(SimpleNamespace(name="calendar_update_event", _require_confirmation=True), {}, None) is None
    assert check.guard(SimpleNamespace(name="task_update", _require_confirmation=False), {}, None) is not None


async def test_a_check_closes_a_paid_bill_and_sees_the_open_ones(store, tmp_path):
    await connect(store, tmp_path, mail=[CHAT], events=[SOON])
    tid = store.add_task("Pay electricity bill - Rs 4,280", "reminder", due_at="2026-11-08T09:00+05:30")
    store.set_setting("watch.state", {"last_check": None, "seen": [], "events": {}, "sources": {}, "caught_up": bills.CATCH_UP})
    seen = {}

    async def turn(prompt, tools, instruction):
        seen["open"] = json.loads((await call(tools, "bills_and_orders"))["result"])
        seen["closed"] = (await call(tools, "close_reminder", task_id=tid, why="paid: confirmation mail 21 Oct"))["result"]
        await call(tools, "report", needs_you=[], line="Electricity bill paid.")
    assert await check.run_check(store, NOW, turn, _post, _push) == "ok"
    assert [r["id"] for r in seen["open"]["reminders"]] == [tid]
    assert [e["title"] for e in seen["open"]["events"]] == ["Pay electricity bill - Rs 4,280"]
    assert seen["closed"] == f"Closed reminder #{tid}."
    assert store.one("select status from tasks where id=?", (tid,))["status"] == "done"
    assert store.get_setting(report.CARD)["line"] == "Electricity bill paid."


async def test_the_first_check_catches_up_once(store, tmp_path):
    await connect(store, tmp_path, mail=[BILL, ORDER, CHAT])
    prompts = []

    async def turn(prompt, tools, instruction):
        prompts.append(prompt)
        await call(tools, "report", needs_you=[], line="Caught up.")
    await check.run_check(store, NOW, turn, _post, _push)
    await check.run_check(store, NOW + timedelta(minutes=30), turn, _post, _push)
    assert "catch-up" in prompts[0] and "Wireless Earbuds" in prompts[0] and "Lunch tomorrow" not in prompts[0]
    assert "catch-up" not in prompts[1]


async def _post(text, media=None):
    pass


def _push(title, body):
    pass


# ── Today: a done event, and what the watch closed ──

async def test_up_next_shows_a_paid_event_as_done_under_its_own_title(store):
    store.set_setting("watch.card", {"events": [
        {"id": "e1", "title": "✓ Paid · Pay electricity bill - Rs 4,280", "start": "2026-10-25T09:00:00+05:30"}]})
    [item] = (await upcoming.build(store, NOW))["items"]
    assert (item["done"], item["title"]) == ("paid", "Pay electricity bill - Rs 4,280")


async def test_the_api_lists_what_the_watch_closed_and_reopens_it(store):
    from odie.app.main import create_app
    from tests.test_api import FakeRunner
    tid = store.add_task("Pay electricity bill - Rs 4,280", "reminder")
    bills.close(store, tid, "paid: confirmation mail 21 Oct")
    app = create_app(runner=FakeRunner(), store=store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c, app.router.lifespan_context(app):
        listed = (await c.get("/api/tasks/closed_by_watch")).json()
        assert [(t["id"], t["why"]) for t in listed] == [(tid, "paid: confirmation mail 21 Oct")]
        assert (await c.post(f"/api/tasks/{tid}/reopen")).status_code == 200
        assert (await c.get("/api/tasks/closed_by_watch")).json() == []
    assert store.one("select status from tasks where id=?", (tid,))["status"] == "open"


def test_the_card_keeps_a_busy_fortnight_of_events():
    events = [fetch.Event(f"e{n}", f"Meeting {n}", f"2026-10-{22 + n:02d}T10:00:00+05:30", "", "", [], "calendar:x")
              for n in range(9)]
    events += [fetch.Event(f"f{n}", f"Call {n}", f"2026-10-{22 + n:02d}T16:00:00+05:30", "", "", [], "calendar:x")
               for n in range(9)]
    assert len(report._events(events)) == 18  # Up next shows a big card and up to 14 small ones


def test_the_watch_skill_shows_bills_payments_and_orders_by_example():
    text = check.SKILL.read_text()
    for name in ("bills_and_orders", "close_reminder", "calendar_update_event", "calendar_create_event", "task_add"):
        assert name in text
    for mark, _state in bills.DONE_MARKS:  # the same marks Up next reads (bills.done_state)
        assert mark.strip() in text
    assert "same amount" in text and "Example" in text


async def test_a_catch_up_that_keeps_failing_is_given_up_after_two_tries(store, tmp_path):
    await connect(store, tmp_path, mail=[BILL, ORDER])
    prompts = []

    async def times_out(prompt, tools, instruction):
        prompts.append(prompt)
        raise TimeoutError("the model took too long")
    for n in range(3):
        await check.run_check(store, NOW + timedelta(minutes=30 * n), times_out, _post, _push)
    catching = ["catch-up" in p for p in prompts if p.startswith("Run the watch check.")]
    assert catching == [True, True, False]  # two tries, then new mail only
