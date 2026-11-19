"""Pulse (Pulse design §1, proactive design §8): each personality's own; one card per ready loop with the same three
buttons; Odie is on it; Done today with Reopen; Odie's Pulse shows the others as a count only."""
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest

from odie import config, personalities
from odie.loops import ledger
from odie.store.db import Store
from odie.watch import needs
from odie.watch import owner as watch_owner


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


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


def ready_loop(store, pid="", number=49):
    lid = ledger.open_loop(store, pid, now(), f"app #{number} Threads newest first", "pull request",
                           refs=[f"example/app#{number}"], playbook="github-pr")
    ledger.update(store, lid, now(), state="ready", has_news=0, result="Open · CI green · 3 files, +41 −9",
                  brief="Sorts threads newest first.", link=f"https://github.com/example/app/pull/{number}")
    return lid


def test_a_ready_loop_is_one_card_with_the_three_buttons(store):
    lid = ready_loop(store)
    working = ledger.open_loop(store, "", now(), "app #50 Draft", "pull request", refs=["example/app#50"])
    cards = needs.cards(store, now())
    card = cards[0]
    assert [c["ref"] for c in cards] == [f"loop:{lid}"]  # the working one isn't a card
    assert card["why"] == "Open · CI green · 3 files, +41 −9" and card["brief"] == "Sorts threads newest first."
    assert card["main"] == {"label": "Open PR #49", "action": "open", "value": "https://github.com/example/app/pull/49"}
    assert card["other"] == {"label": "Done", "action": "loop_done", "value": lid}
    assert card["later"]["value"] == f"loop:{lid}"
    assert needs.later(store, f"loop:{lid}", now()) is not None
    assert needs.cards(store, now()) == []  # put off until tomorrow 09:00
    assert working


async def test_pulse_follows_the_pick_and_odie_sees_others_as_a_count(api, store):
    mira = personalities.create(store, "Mira").id
    watch_owner.set_proactive(store, mira, True)
    ready_loop(store, mira, 7)
    ready_loop(store, mira, 8)
    on_it = ledger.open_loop(store, mira, now(), "app #9 waiting on CI", "pull request", refs=["example/app#9"])
    odies = (await api.get("/api/needs_you")).json()
    assert odies["items"] == [] and odies["others"] == [{"id": mira, "name": "Mira", "waiting": 2}]
    hers = (await api.get(f"/api/needs_you?personality={mira}")).json()
    assert [i["ref"] for i in hers["items"]] == ["loop:2", "loop:1"] or len(hers["items"]) == 2
    assert [o["id"] for o in hers["on_it"]] == [on_it] and "others" not in hers
    assert hers["proactive"]["on"] is True


async def test_done_and_reopen_on_a_loop(api, store):
    mira = personalities.create(store, "Mira").id
    lid = ready_loop(store)
    assert (await api.post(f"/api/loops/{lid}/done?personality={mira}")).status_code == 404  # not hers
    assert (await api.post(f"/api/loops/{lid}/done")).json()["ok"] is True
    assert ledger.get(store, lid)["state"] == "closed"
    other = ready_loop(store, number=50)
    ledger.close(store, other, now(), "odie", "merged 18 Nov 09:00")
    got = (await api.get("/api/needs_you")).json()
    assert [d["id"] for d in got["loops_done"]] == [other] and got["loops_done"][0]["why"] == "merged 18 Nov 09:00"
    assert (await api.post(f"/api/loops/{other}/reopen")).json()["ok"] is True
    assert ledger.get(store, other)["state"] == "new"
    later = await api.post("/api/needs_you/later", json={"ref": f"loop:{ready_loop(store, number=51)}"})
    assert later.status_code == 200


def test_old_closes_leave_done_today(store):
    lid = ready_loop(store)
    ledger.close(store, lid, now() - timedelta(days=2), "odie", "merged")
    from odie.loops import cards
    assert cards.done_today(store, "", now()) == []


async def test_the_watch_count_follows_the_pick(api, store):
    mira = personalities.create(store, "Mira").id
    store.set_setting(f"watch.card:{mira}", {"line": ""})
    store.set_setting("watch.card", {"line": ""})
    for title in ("x", "y"):
        ledger.open_loop(store, mira, now(), title, "reply owed", owner="you", state="ready")
    ledger.open_loop(store, "", now(), "z", "reply owed", owner="you", state="ready")
    assert (await api.get(f"/api/watch?personality={mira}")).json()["unseen"] == 2
    assert (await api.get("/api/watch")).json()["unseen"] == 1


def test_a_personalitys_push_opens_its_own_pulse(store, monkeypatch):
    from odie.app import main
    from odie.push import send
    sent = []
    monkeypatch.setattr(send, "send_to_all", lambda store_, title, body, url="/", tag=None: sent.append(url))

    class Bus:
        def emit(self, event):
            pass
    runner = type("R", (), {"bus": Bus()})()
    main.watch_pushed(store, runner, "Mira · Invoice", "due Friday", owner="ab12cd34ef56")
    main.watch_pushed(store, runner, "Reply to Asha", "today")
    assert sent == ["/#today?personality=ab12cd34ef56", "/#today"]
