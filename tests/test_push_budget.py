"""Pushes Odie starts on its own: three a day, shared by everyday Odie and every personality (proactive design §8)."""
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from odie import personalities
from odie.store.db import Store
from odie.watch import pushes

DAY = datetime(2026, 11, 18, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


def test_three_a_day_across_everyone(store):
    mira = personalities.create(store, "Mira").id
    sent = []

    def send(title, body):
        sent.append((title, body))
    assert pushes.started_by_odie(store, DAY, "", "Reply to Asha", "asks for the deck\nmore", send)
    assert pushes.started_by_odie(store, DAY, mira, "Invoice 12", "due Friday", send)
    assert pushes.started_by_odie(store, DAY, "", "Lamp", "arrives today", send)
    assert not pushes.started_by_odie(store, DAY, mira, "One more", "too many", send)
    assert sent == [("Reply to Asha", "asks for the deck"), ("Mira · Invoice 12", "due Friday"), ("Lamp", "arrives today")]
    assert store.get_setting(pushes.HELD)[-1]["title"] == "Mira · One more"  # kept for the digest
    tomorrow = DAY.replace(day=19)
    assert pushes.sent_today(store, tomorrow) == 0
    assert pushes.started_by_odie(store, tomorrow, "", "New day", "fresh budget", send)
