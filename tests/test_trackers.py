import json
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from odie import trackers as T
from odie.store.db import Store
from tests.test_api import client  # noqa: F401  (fixture)

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 10, 5, 4, 30, tzinfo=UTC)  # 10:00 in India


@pytest.fixture
def store(tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


def _reply(state="0-0 HT", summary="Arsenal 0-0 Spurs at half time", done=False, met=False, blocks=None, tell=None):
    body = {"state": state, "summary": summary, "done": done, "met": met}
    if blocks is not None:
        body["blocks"] = blocks
    if tell is not None:
        body["tell"] = tell
    return "Checked the live score.\n```json\n" + json.dumps(body) + "\n```"


def test_create_and_limits(store):
    t = T.create(store, "Arsenal v Spurs", "Arsenal vs Spurs score and status", "15m", now=NOW)
    assert isinstance(t, dict) and t["status"] == "active" and t["notify"] == "change"
    assert t["next_check_at"] == NOW.isoformat(timespec="seconds")  # first check right away
    assert datetime.fromisoformat(t["until_at"]) == NOW + timedelta(days=14)
    assert "every" in T.create(store, "x", "y", "sometimes", now=NOW)
    assert "condition" in T.create(store, "x", "y", "1h", notify="condition", now=NOW)
    for i in range(9):
        T.create(store, f"t{i}", "c", "1h", now=NOW)
    assert "10" in T.create(store, "one too many", "c", "1h", now=NOW)


def test_due_and_expiry(store):
    a = T.create(store, "a", "c", "1h", now=NOW)
    b = T.create(store, "b", "c", "1h", until=(NOW + timedelta(hours=1)).date().isoformat(), now=NOW)
    T.set_status(store, b["id"], "paused")
    assert [r["id"] for r in T.due(store, NOW)] == [a["id"]]
    T.create(store, "c", "c", "1h", until="2026-10-01", now=NOW)  # already over
    assert [r["title"] for r in T.due(store, NOW)] == ["a"]
    assert T.get(store, 3)["status"] == "done"


@pytest.mark.parametrize("text, ok", [
    (_reply(), True),
    ('Sure. {"state": "x", "summary": "y", "done": false, "met": false}', True),
    ("No JSON here.", False),
    ('```json\n{"summary": "no state"}\n```', False),
])
def test_parse_reply(text, ok):
    assert (T.parse_reply(text) is not None) is ok


def test_notify_rules(store):
    t = T.create(store, "a", "c", "15m", now=NOW)
    row = T.get(store, t["id"])
    assert T.record(store, row, T.parse_reply(_reply("0-0 HT")), NOW, IST) is False   # first check: baseline only
    row = T.get(store, t["id"])
    assert T.record(store, row, T.parse_reply(_reply("0-0  ht")), NOW, IST) is False  # same state, other spacing/case
    row = T.get(store, t["id"])
    assert T.record(store, row, T.parse_reply(_reply("1-0 55'", "Arsenal score!")), NOW, IST) is True
    row = T.get(store, t["id"])
    assert row["last_summary"] == "Arsenal score!" and row["next_check_at"] == (NOW + timedelta(minutes=15)).isoformat(timespec="seconds")
    assert T.record(store, row, T.parse_reply(_reply("2-1 FT", "Full time", done=True)), NOW, IST) is True
    assert T.get(store, t["id"])["status"] == "done"

    c = T.create(store, "price", "TCS price", "1h", notify="condition", condition="below 3000", now=NOW)
    assert T.record(store, T.get(store, c["id"]), T.parse_reply(_reply("3100", met=False)), NOW, IST) is False
    assert T.record(store, T.get(store, c["id"]), T.parse_reply(_reply("2990", met=True)), NOW, IST) is True
    al = T.create(store, "weather", "Pune weather", "1d", notify="always", now=NOW)
    assert T.record(store, T.get(store, al["id"]), T.parse_reply(_reply("rain")), NOW, IST) is True


def test_a_reworded_state_with_nothing_new_stays_quiet(store):
    """The state's words drift between checks ("no new note since 10:25" then "still nothing since 10:25"): when the
    check itself says there is nothing to tell, the user hears nothing, and the card still shows the latest line."""
    t = T.create(store, "Asha's parcel", "parcel status", "1h", now=NOW)
    T.record(store, T.get(store, t["id"]), T.parse_reply(_reply("In transit, Pune hub")), NOW, IST)
    quiet = T.parse_reply(_reply("Still in transit at the Pune hub", "No change: still at the Pune hub", tell=False))
    assert T.record(store, T.get(store, t["id"]), quiet, NOW, IST) is False
    assert T.get(store, t["id"])["last_summary"] == "No change: still at the Pune hub"  # kept on the card, not posted
    news = T.parse_reply(_reply("Out for delivery", "Asha's parcel is out for delivery", tell=True))
    assert T.record(store, T.get(store, t["id"]), news, NOW, IST) is True
    over = T.parse_reply(_reply("Delivered", "Delivered", done=True, tell=False))
    assert T.record(store, T.get(store, t["id"]), over, NOW, IST) is True  # the tracker ending is always said


def test_the_check_is_asked_whether_its_worth_telling():
    assert '"tell"' in T.REPLY_FORMAT


def test_blocks_are_kept(store):
    t = T.create(store, "a", "c", "15m", now=NOW)
    T.record(store, T.get(store, t["id"]), T.parse_reply(_reply(blocks=[{"type": "kpis", "items": [{"label": "Score", "value": 1}]}])), NOW, IST)
    assert json.loads(T.get(store, t["id"])["last_blocks_json"])[0]["type"] == "kpis"


async def test_check_runs_turn_and_notifies(store):
    t = T.create(store, "Arsenal v Spurs", "score", "15m", now=NOW)
    prompts, sent = [], []

    async def turn(prompt):
        prompts.append(prompt)
        return _reply("1-0", "Arsenal lead 1-0") if len(prompts) > 1 else _reply("0-0")

    async def notify(row, summary):
        sent.append((row["title"], summary))
    await T.run_due(store, turn, notify, NOW, IST)
    assert "score" in prompts[0] and "first check" in prompts[0] and sent == []
    later = NOW + timedelta(minutes=16)
    await T.run_due(store, turn, notify, later, IST)
    assert "0-0" in prompts[1] and sent == [("Arsenal v Spurs", "Arsenal lead 1-0")]


async def test_three_failures_pause_and_say_so(store):
    T.create(store, "a", "c", "15m", now=NOW)
    sent = []

    async def turn(prompt):
        return "I couldn't find anything."

    async def notify(row, summary):
        sent.append(summary)
    for k in range(3):
        await T.run_due(store, turn, notify, NOW + timedelta(minutes=16 * k), IST)
    row = T.get(store, 1)
    assert row["status"] == "paused" and row["fails"] == 3 and len(sent) == 1 and "paused" in sent[0]


async def test_a_crashing_turn_counts_as_a_failure(store):
    T.create(store, "a", "c", "15m", now=NOW)

    async def turn(prompt):
        raise RuntimeError("model down")

    async def notify(row, summary):
        pass
    await T.run_due(store, turn, notify, NOW, IST)
    assert T.get(store, 1)["fails"] == 1


def test_guard_refuses_gated_tools():
    class Tool:
        def __init__(self, name, confirm=False):
            self.name, self._require_confirmation = name, confirm
    assert T.guard(Tool("run_shell"), {}, None)["error"]
    assert T.guard(Tool("install_skill"), {}, None)["error"]
    assert T.guard(Tool("write_note", confirm=True), {}, None)["error"]
    assert T.guard(Tool("web_search"), {}, None) is None


async def test_tracker_routes(client):
    c, s = client if isinstance(client, tuple) else (client, None)
    st = s or c._transport.app.state.store
    T.create(st, "Arsenal v Spurs", "score", "15m")
    rows = (await c.get("/api/trackers")).json()["trackers"]
    assert rows[0]["title"] == "Arsenal v Spurs" and rows[0]["schedule"] == {"minutes": 15}
    tid = rows[0]["id"]
    assert (await c.post(f"/api/trackers/{tid}/pause")).json()["status"] == "paused"
    assert (await c.post(f"/api/trackers/{tid}/resume")).json()["status"] == "active"
    assert (await c.post(f"/api/trackers/{tid}/stop")).json()["status"] == "stopped"
    assert (await c.post(f"/api/trackers/{tid}/explode")).status_code == 422
    assert (await c.post("/api/trackers/999/pause")).status_code == 404


async def test_a_five_minute_tracker_runs_on_every_tick(store):
    """The background tick is every 5 minutes and lands a little early or late: a 5-minute tracker is due on each tick."""
    T.create(store, "Arsenal v Spurs", "score", "5m", now=NOW)
    prompts = []

    async def turn(prompt):
        prompts.append(prompt)
        return _reply("0-0")

    async def notify(row, summary):
        pass
    await T.run_due(store, turn, notify, NOW, IST)
    await T.run_due(store, turn, notify, NOW + timedelta(minutes=4, seconds=50), IST)  # this tick came 10 s early
    assert len(prompts) == 2
    await T.run_due(store, turn, notify, NOW + timedelta(minutes=6), IST)  # 70 s after the last check: not due yet
    assert len(prompts) == 2
