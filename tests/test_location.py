"""Where the user is (odie.location): the setting, the fixes kept, home as the place seen most on nights. Places and
coordinates below are made up."""
from datetime import datetime, timedelta, timezone

from odie import location
from odie.store.db import Store

TZ = timezone(timedelta(hours=5, minutes=30))
NORTHVALE = "Northvale, Westshire"
SEAPORT = "Seaport, Eastmarch"


def fix(place, when, lat=18.52, lon=73.85):
    return {"place": place, "lat": lat, "lon": lon, "at": when.isoformat()}


def test_home_is_the_place_seen_most_on_nights():
    nights = [fix(NORTHVALE, datetime(2026, 10, d, 23, 30, tzinfo=TZ)) for d in range(1, 9)]
    days = [fix(SEAPORT, datetime(2026, 10, d, 14, 0, tzinfo=TZ)) for d in range(1, 20)]
    assert location.home_of(nights + days) == NORTHVALE  # days don't count, however many


def test_home_needs_five_nights_and_a_clear_winner():
    few = [fix(NORTHVALE, datetime(2026, 10, d, 1, 0, tzinfo=TZ)) for d in range(1, 5)]
    assert location.home_of(few) == ""
    tie = few + [fix("Harbour Town", datetime(2026, 10, d, 2, 0, tzinfo=TZ)) for d in range(10, 14)]
    tie += [fix(NORTHVALE, datetime(2026, 10, 20, 2, 0, tzinfo=TZ))]
    assert location.home_of(tie + [fix("Harbour Town", datetime(2026, 10, 21, 2, 0, tzinfo=TZ))]) == ""  # 5 vs 5
    assert location.home_of(tie) == NORTHVALE  # 5 vs 4


def test_is_night_reads_the_fixs_own_clock():
    assert location.is_night(datetime(2026, 10, 25, 23, 0, tzinfo=TZ)) and location.is_night(datetime(2026, 10, 25, 5, 59, tzinfo=TZ))
    assert not location.is_night(datetime(2026, 10, 25, 6, 0, tzinfo=TZ)) and not location.is_night(datetime(2026, 10, 25, 22, 59, tzinfo=TZ))


def test_record_decline_set_home_and_forget(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    assert location.get(s)["on"] is None and location.get(s)["place"] == ""
    now = datetime(2026, 10, 25, 14, 12, tzinfo=TZ)
    v = location.record(s, 18.52, 73.85, NORTHVALE, now)
    assert v["on"] is True and v["place"] == NORTHVALE and v["seen"] == now.isoformat() and v["home"] == ""
    v = location.set_home(s, "Northvale")
    assert v["home"] == "Northvale" and v["home_set_by_user"] is True
    v = location.record(s, 15.49, 73.82, "Harbour Town", now + timedelta(days=1))
    assert v["home"] == "Northvale"  # a stated home is not overwritten by inference
    assert location.decline(s)["on"] is False and location.get(s)["place"] == "Harbour Town"  # declining keeps what was known
    assert location.set_on(s, True)["on"] is True
    assert location.forget(s) == location.get(s) and location.get(s)["on"] is None and location.get(s)["fixes"] == []


def test_fixes_are_kept_to_thirty_days_and_two_hundred(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    now = datetime(2026, 10, 25, 14, 0, tzinfo=TZ)
    location.record(s, 18.52, 73.85, "Old", now - timedelta(days=31))
    for i in range(205):
        location.record(s, 18.52, 73.85, NORTHVALE, now - timedelta(minutes=i))
    fixes = location.get(s)["fixes"]
    assert len(fixes) == 200 and all(f["place"] != "Old" for f in fixes)
