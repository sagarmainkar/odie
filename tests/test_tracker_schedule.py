from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from odie.trackers.schedule import next_due, parse_every

IST = ZoneInfo("Asia/Kolkata")
MON_10 = datetime(2026, 10, 5, 10, 0, tzinfo=IST)  # a Monday


@pytest.mark.parametrize("text, spec", [
    ("5m", {"minutes": 5}), ("15m", {"minutes": 15}), ("every 2 hours", {"minutes": 120}), ("1d", {"minutes": 1440}), ("30 min", {"minutes": 30}),
    ("09:00", {"times": ["09:00"], "days": None}), ("daily 08:00, 20:00", {"times": ["08:00", "20:00"], "days": None}),
    ("mon 09:00", {"times": ["09:00"], "days": [0]}), ("weekdays 7:30", {"times": ["07:30"], "days": [0, 1, 2, 3, 4]}),
    ("sat,sun 10:00", {"times": ["10:00"], "days": [5, 6]}),
])
def test_parse(text, spec):
    assert parse_every(text) == spec


@pytest.mark.parametrize("text", ["4m", "sometimes", "25:00", "", "mon", "every 10 days"])
def test_parse_rejects(text):
    assert parse_every(text) is None


def test_next_due_interval_and_times():
    assert next_due({"minutes": 30}, MON_10) == datetime(2026, 10, 5, 10, 30, tzinfo=IST)
    assert next_due({"times": ["09:00", "18:00"], "days": None}, MON_10) == datetime(2026, 10, 5, 18, 0, tzinfo=IST)
    assert next_due({"times": ["09:00"], "days": None}, MON_10) == datetime(2026, 10, 6, 9, 0, tzinfo=IST)
    assert next_due({"times": ["09:00"], "days": [0]}, MON_10) == datetime(2026, 10, 12, 9, 0, tzinfo=IST)  # next Monday
    assert next_due({"times": ["10:00"], "days": [0]}, MON_10) == datetime(2026, 10, 12, 10, 0, tzinfo=IST)  # not the same minute
