from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from odie import upcoming as U
from odie.store.db import Store
from tests.test_api import client  # noqa: F401  (fixture)

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 10, 5, 9, 30, tzinfo=IST)
TODAY = NOW.date()

CAL = """## 2026-10-05
e1 | 08:00-09:00 | Standup | a@x.com
e2 | 18:30-19:15 | Dr. Mehta, cardiology follow-up @ Ruby Hall Clinic
## 2026-10-07
e3 | all day 2026-10-07 | Asha's birthday
## 2026-10-08
e4 | 06:10-08:20 | Flight 6E 532 PNQ-GOI
"""


@pytest.mark.parametrize("title, kind", [
    ("Dr. Mehta, cardiology follow-up", "medical"), ("Dentist", "medical"), ("Asha's birthday", "birthday"),
    ("Aai BD", "birthday"),
    ("Flight 6E 532 PNQ-GOI", "travel"), ("Weekly sync with client", "meeting"), ("Zoom call with Ravi", "call"),
    ("Dinner at Malaka Spice", "meal"), ("Yoga", "fitness"), ("Wedding anniversary", "celebration"),
    ("HDFC credit card bill", "card"), ("LIC premium due", "insurance"), ("Airtel postpaid bill", "bill"),
    ("Amazon delivery", "delivery"), ("PTM at school", "school"), ("Coldplay concert", "show"), ("Buy milk", "general"),
])
def test_kind_for(title, kind):
    assert U.kind_for(title) == kind


def test_tasks_with_due_dates_but_not_ledger_copies(tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    s.add_task("Renew passport", "todo", due_at="2026-10-12T10:00:00+05:30")
    s.add_task("Pay HDFC card", "reminder", due_at="2026-10-09T09:00:00+05:30", source_kind="ledger", source_ref="r1")
    s.add_task("Someday", "todo")
    items = U.from_tasks(s, NOW, 14)
    assert [i["title"] for i in items] == ["Renew passport"] and items[0]["time"] == "10:00"
