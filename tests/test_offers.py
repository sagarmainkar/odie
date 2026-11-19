""""Track this?" (proactive design §17, phase 4): his own commitment said in chat is offered as a card; Track (his tap)
makes a loop of his with its due time and a reminder; No forgets it. Nothing is tracked without his tap."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest

from odie import config, devices, personalities
from odie.loops import ledger, offers
from odie.store.db import Store
from odie.watch import needs

TZ = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 11, 19, 10, 0, tzinfo=TZ)
FRIDAY = "2026-11-20T09:00:00+05:30"


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


def test_an_offer_is_a_card_with_track_and_no(store):
    oid = offers.add(store, "", NOW, "Call the bank", FRIDAY, "I need to call the bank Friday", "chat-2026-11-19")
    [card] = offers.cards(store, "", NOW)
    assert card["ref"] == f"offer:{oid}" and card["title"] == "Track this? Call the bank"
    assert card["why"] == "You said: “I need to call the bank Friday”" and card["badge"] == "20 Nov, 09:00"
    assert card["main"] == {"label": "Track", "action": "track", "value": oid}
    assert card["other"] == {"label": "No", "action": "dismiss", "value": f"offer:{oid}"}  # every app knows dismiss
    assert "later" not in card


def test_offers_are_on_their_owners_pulse_only(store):
    mira = personalities.create(store, "Mira")
    offers.add(store, mira.id, NOW, "Book the physio", None, "I have to book the physio", "chat-m")
    assert [c["title"] for c in needs.cards(store, NOW, mira.id)] == ["Track this? Book the physio"]
    assert needs.cards(store, NOW, "") == []


def test_track_makes_his_loop_with_its_due_time_and_a_reminder(store):
    oid = offers.add(store, "", NOW, "Call the bank", FRIDAY, "I need to call the bank Friday", "chat-2026-11-19")
    lid = offers.track(store, "", oid, NOW)
    loop = ledger.get(store, lid)
    assert loop["owner"] == "you" and loop["state"] == "ready" and loop["due_at"] == FRIDAY and loop["playbook"] == ""
    [task_id] = ledger.reminders_of(loop)
    task = store.one("select * from tasks where id=?", (task_id,))
    assert task["due_at"] == FRIDAY and task["source_kind"] == "loop" and task["status"] == "open"
    assert offers.cards(store, "", NOW) == []  # answered
    assert offers.track(store, "", oid, NOW) is None  # never twice
    assert [c["ref"] for c in needs.cards(store, NOW)] == [f"loop:{lid}"]  # his card, its reminder behind it


def test_track_with_no_time_makes_no_reminder(store):
    oid = offers.add(store, "", NOW, "Renew the passport", None, "remind me to renew the passport", "chat-1")
    loop = ledger.get(store, offers.track(store, "", oid, NOW))
    assert ledger.reminders_of(loop) == [] and loop["due_at"] is None


def test_no_forgets_the_offer_and_tracks_nothing(store):
    oid = offers.add(store, "", NOW, "Call the bank", FRIDAY, "I need to call the bank", "chat-1")
    assert offers.decline(store, "", oid)
    assert offers.cards(store, "", NOW) == [] and ledger.open_loops(store, "") == []
    assert offers.track(store, "", oid, NOW) is None


def test_an_unanswered_offer_fades(store):
    oid = offers.add(store, "", NOW, "Call the bank", FRIDAY, "I need to call the bank", "chat-1")
    assert offers.cards(store, "", NOW + timedelta(days=1, hours=1)) == []  # its time has passed
    later = offers.add(store, "", NOW, "Renew the passport", None, "renew the passport", "chat-1")
    assert offers.cards(store, "", NOW + timedelta(days=8)) == []  # a week on
    assert offers.track(store, "", later, NOW + timedelta(days=8)) is None
    assert oid


def test_one_owners_offer_cannot_be_tracked_by_another(store):
    mira = personalities.create(store, "Mira")
    oid = offers.add(store, mira.id, NOW, "Book the physio", None, "I have to book the physio", "chat-m")
    assert offers.track(store, "", oid, NOW) is None
    assert offers.decline(store, "", oid) is False


# --- the routes: his tap in the app, the picked one's own ---

@pytest.fixture
async def api(store, monkeypatch):
    from odie.app.main import create_app
    from tests.test_api import FakeRunner
    monkeypatch.setenv("ODIE_SCHEDULER", "0")
    app = create_app(runner=FakeRunner(), store=store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c, \
            app.router.lifespan_context(app):
        yield c


def now():
    return datetime.now(ZoneInfo(config.settings.timezone))


async def test_the_track_route_makes_the_loop(api, store):
    oid = offers.add(store, "", now(), "Call the bank", None, "I need to call the bank", "chat-1")
    got = (await api.post(f"/api/offers/{oid}/track")).json()
    assert ledger.get(store, got["loop"])["owner"] == "you"
    assert (await api.post(f"/api/offers/{oid}/track")).status_code == 404  # answered already


async def test_no_is_the_dismiss_every_app_already_sends(api, store):
    oid = offers.add(store, "", now(), "Call the bank", None, "I need to call the bank", "chat-1")
    assert (await api.post("/api/watch/done", json={"ref": f"offer:{oid}"})).status_code == 200
    assert offers.open_offers(store, "", now()) == []
    assert ledger.open_loops(store, "") == []


async def test_the_routes_are_scoped_to_the_picked_one(api, store):
    mira = personalities.create(store, "Mira")
    oid = offers.add(store, mira.id, now(), "Book the physio", None, "I have to book the physio", "chat-m")
    assert (await api.post(f"/api/offers/{oid}/track")).status_code == 404  # asked as everyday Odie
    await api.post("/api/watch/done", json={"ref": f"offer:{oid}"})
    assert offers.open_offers(store, mira.id, now())  # still Mira's, untouched
    got = await api.post(f"/api/offers/{oid}/track?personality={mira.id}")
    assert got.status_code == 200


def test_the_terminals_key_can_never_track():
    assert devices.terminal_may("POST", "/api/offers/3/track") is False
    assert devices.terminal_may("POST", "/api/watch/done") is False
