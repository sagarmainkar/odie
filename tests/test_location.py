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


# --- From a point to a place name (place_for) ---


async def test_place_comes_from_a_remembered_fix_nearby_before_the_network(isolated_settings, tmp_path):
    import httpx
    s = Store(tmp_path / "a.db")
    s.init_schema()
    location.record(s, 18.52, 73.85, NORTHVALE, datetime(2026, 10, 25, 9, 0, tzinfo=TZ))

    def never(request):
        raise AssertionError("no network for a place already known")
    assert await location.place_for(s, 18.55, 73.88, httpx.MockTransport(never)) == NORTHVALE  # ~4.6 km away
    assert round(location.km_between(18.52, 73.85, 18.55, 73.88), 1) == 4.6


async def test_place_is_asked_of_nominatim_when_nothing_nearby_is_known(isolated_settings, tmp_path):
    import httpx
    s = Store(tmp_path / "a.db")
    s.init_schema()
    seen = []

    def handler(request):
        seen.append(request)
        return httpx.Response(200, json={"address": {"town": "Harbour Town", "state": "Eastmarch", "country": "Nowhere"}})
    assert await location.place_for(s, 15.49, 73.82, httpx.MockTransport(handler)) == "Harbour Town, Eastmarch"
    assert seen[0].url.host == "nominatim.openstreetmap.org" and seen[0].url.params["zoom"] == "10"
    assert seen[0].url.params["format"] == "jsonv2" and seen[0].headers["user-agent"].startswith("Odie (")
    only_state = httpx.MockTransport(lambda r: httpx.Response(200, json={"address": {"state": "Eastmarch"}}))
    assert await location.place_for(s, 15.49, 73.82, only_state) == "Eastmarch"


async def test_place_is_empty_when_nominatim_cannot_answer(isolated_settings, tmp_path):
    import httpx
    s = Store(tmp_path / "a.db")
    s.init_schema()

    def down(request):
        raise httpx.ConnectError("down")
    assert await location.place_for(s, 15.49, 73.82, httpx.MockTransport(down)) == ""
    junk = httpx.MockTransport(lambda r: httpx.Response(200, text="<html>"))
    assert await location.place_for(s, 15.49, 73.82, junk) == ""
    refused = httpx.MockTransport(lambda r: httpx.Response(429, json={}))
    assert await location.place_for(s, 15.49, 73.82, refused) == ""
    no_address = httpx.MockTransport(lambda r: httpx.Response(200, json={"error": "Unable to geocode"}))
    assert await location.place_for(s, 15.49, 73.82, no_address) == ""


# --- The routes a device and Settings use ---


def test_a_point_must_be_plausible():
    assert location.point_is_plausible(18.52, 73.85) and location.point_is_plausible(-33.9, 151.2)
    for lat, lon in ((0, 0), (91, 0), (-91, 0), (1, 181), (1, -181)):
        assert not location.point_is_plausible(lat, lon), (lat, lon)


async def test_location_routes(isolated_settings, tmp_path, monkeypatch):
    import httpx

    from odie.app.main import create_app
    from tests.test_api import FakeRunner
    s = Store(tmp_path / "a.db")
    s.init_schema()

    async def fake_place(store, lat, lon, transport=None):
        return NORTHVALE
    monkeypatch.setattr(location, "place_for", fake_place)
    app = create_app(runner=FakeRunner(), store=s)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t") as c, app.router.lifespan_context(app):
        assert (await c.get("/api/location")).json()["on"] is None
        r = await c.post("/api/location", json={"lat": 18.52, "lon": 73.85})
        assert r.status_code == 200 and r.json()["place"] == NORTHVALE and r.json()["seen"]
        assert set(r.json()) == {"on", "place", "seen", "home", "home_set_by_user"}  # never coordinates, never the fixes
        r = await c.post("/api/location", json={"lat": 15.49, "lon": 73.82, "place": "Harbour Town, Eastmarch"})
        assert r.json()["place"] == "Harbour Town, Eastmarch"  # a device's own name is taken as is
        for bad in ({"lat": 0, "lon": 0}, {"lat": 91, "lon": 0}, {"lat": 1, "lon": 181}):
            assert (await c.post("/api/location", json=bad)).status_code == 422, bad
        assert location.get(s)["place"] == "Harbour Town, Eastmarch"  # a bad point changed nothing
        assert (await c.put("/api/location", json={"home": "Northvale"})).json()["home"] == "Northvale"
        assert (await c.put("/api/location", json={"on": False})).json()["on"] is False
        assert (await c.put("/api/location", json={"on": True})).json()["on"] is True
        assert (await c.delete("/api/location")).json() == {"on": None, "place": "", "seen": "", "home": "", "home_set_by_user": False}
    rows = s.query("select result_summary, args_json from audit_log where event='location'")
    assert len(rows) >= 5
    for row in rows:
        assert "18.52" not in (row["result_summary"] or "") and "73.8" not in (row["args_json"] or "")  # nothing of the point itself


# --- The context line and the prompt rule ---


def test_the_context_line_carries_where_the_user_is_and_home():
    from odie.agent.prompt import build_turn_context
    now = datetime(2026, 10, 25, 14, 16, tzinfo=TZ)
    out = build_turn_context(now, "", "", place=NORTHVALE, seen="14:12", home="Northvale")
    assert out.startswith(f"[context: now 14:16 Sun 25 Oct · near {NORTHVALE} (seen 14:12) · home: Northvale]")
    assert "near" not in build_turn_context(now, "", "")
    assert build_turn_context(now, "", "", place="Harbour Town").startswith("[context: now 14:16 Sun 25 Oct · near Harbour Town]")
    assert build_turn_context(now, "", "", home="Northvale").startswith("[context: now 14:16 Sun 25 Oct · home: Northvale]")


def test_location_bits_render_the_time_and_respect_the_switch():
    now = datetime(2026, 10, 25, 14, 16, tzinfo=TZ)
    today = {"on": True, "place": NORTHVALE, "seen": "2026-10-25T14:12:00+05:30", "home": "Northvale"}
    assert location.location_bits(today, now) == (NORTHVALE, "14:12", "Northvale")
    stale = {**today, "seen": "2026-10-24T21:40:00+05:30"}
    assert location.location_bits(stale, now) == (NORTHVALE, "Sat 24 Oct 21:40", "Northvale")  # old, but still sent, with its time
    assert location.location_bits({**today, "on": False}, now) == ("", "", "")
    assert location.location_bits({**today, "on": None}, now) == ("", "", "")
    assert location.location_bits({**today, "seen": ""}, now) == (NORTHVALE, "", "Northvale")
    assert location.location_bits({**today, "place": ""}, now) == ("", "", "Northvale")  # a fix with no name yet: home alone


def test_the_rule_tells_the_model_how_to_use_the_place():
    from odie.agent.prompt import ALL_CAPS, Who, rules_text
    text = rules_text(Who(caps=ALL_CAPS), gated=True)
    assert "where the user is now and where home is" in text and "may be travelling" in text
    assert "where the user is now" in rules_text(Who(caps=frozenset()), gated=True)  # every install has the line


def test_the_runner_puts_the_place_into_the_context_line(isolated_settings, tmp_path):
    from odie.app.runner import OdieRunner
    s = Store(tmp_path / "a.db")
    s.init_schema()
    r = OdieRunner(s)
    assert "near" not in r._prepare_prompt("chat-1", "hello")
    location.record(s, 18.52, 73.85, NORTHVALE, datetime.now(TZ))
    assert f"near {NORTHVALE} (seen " in r._prepare_prompt("chat-1", "hello")
    location.decline(s)
    assert "near" not in r._prepare_prompt("chat-1", "hello")
