"""Today's weather for the morning hello (odie.morning.weather): Open-Meteo's forecast for the saved location, rounded
to whole degrees, with the sky in plain words. Coordinates are made up; nothing reaches the network."""
from datetime import datetime, timedelta, timezone

import httpx

from odie import location
from odie.morning import weather
from odie.store.db import Store

TZ = timezone(timedelta(hours=5, minutes=30))
NOW = datetime(2026, 11, 4, 7, 30, tzinfo=TZ)
OPEN_METEO_SHAPE = {
    "current": {"temperature_2m": 26.6, "weather_code": 0},
    "daily": {"temperature_2m_max": [31.2], "temperature_2m_min": [19.4], "weather_code": [1]},
}


def saved_store(tmp_path, lat=12.3456, lon=78.9012, place="Harbour Town, Eastmarch"):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    location.record(s, lat, lon, place, NOW)
    return s


async def test_weather_reads_open_meteo(isolated_settings, tmp_path):
    s = saved_store(tmp_path)
    seen = {}

    def answer(request):
        seen["request"] = request
        return httpx.Response(200, json=OPEN_METEO_SHAPE)

    got = await weather.today_weather(s, httpx.MockTransport(answer))
    assert got == {"place": "Harbour Town, Eastmarch", "now_c": 27, "high_c": 31, "low_c": 19, "words": "Clear"}
    request = seen["request"]
    assert request.url.host == "api.open-meteo.com" and request.url.path == "/v1/forecast"
    assert request.url.params["latitude"] == "12.35"  # rounded to 2 decimals
    assert request.url.params["longitude"] == "78.9"
    assert request.url.params["current"] == "temperature_2m,weather_code"
    assert request.url.params["daily"] == "temperature_2m_max,temperature_2m_min,weather_code"
    assert request.url.params["timezone"] == "auto" and request.url.params["forecast_days"] == "1"
    assert request.headers["user-agent"] == location.USER_AGENT


async def test_words_fall_back_to_the_daily_code_when_current_has_none(isolated_settings, tmp_path):
    s = saved_store(tmp_path)
    body = {"current": {"temperature_2m": 19.4}, "daily": {"temperature_2m_max": [31.2], "temperature_2m_min": [19.4],
                                                          "weather_code": [63]}}
    got = await weather.today_weather(s, httpx.MockTransport(lambda r: httpx.Response(200, json=body)))
    assert got["words"] == "Rain" and got["now_c"] == 19


async def test_no_location_no_weather(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()  # nothing saved: no coordinates

    def never(request):
        raise AssertionError("no network without a location")
    assert await weather.today_weather(s, httpx.MockTransport(never)) is None


async def test_a_location_with_no_coordinates_is_no_weather(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    s.set_setting(location.KEY, {"on": True, "place": "Harbour Town", "lat": None, "lon": None})

    def never(request):
        raise AssertionError("no network without coordinates")
    assert await weather.today_weather(s, httpx.MockTransport(never)) is None


async def test_a_failing_forecast_is_none(isolated_settings, tmp_path):
    s = saved_store(tmp_path)

    def server_error(request):
        return httpx.Response(500, text="oops")

    def timeout(request):
        raise httpx.ConnectTimeout("too slow")
    assert await weather.today_weather(s, httpx.MockTransport(server_error)) is None
    assert await weather.today_weather(s, httpx.MockTransport(timeout)) is None


def test_weather_words():
    assert weather.weather_words(0) == "Clear"
    assert weather.weather_words(1) == "Mostly clear" and weather.weather_words(2) == "Mostly clear"
    assert weather.weather_words(3) == "Cloudy"
    assert weather.weather_words(45) == "Foggy" and weather.weather_words(48) == "Foggy"
    assert weather.weather_words(51) == "Drizzle" and weather.weather_words(57) == "Drizzle"
    assert weather.weather_words(61) == "Rain" and weather.weather_words(67) == "Rain"
    assert weather.weather_words(71) == "Snow" and weather.weather_words(77) == "Snow"
    assert weather.weather_words(80) == "Showers" and weather.weather_words(82) == "Showers"
    assert weather.weather_words(95) == "Thunderstorms" and weather.weather_words(99) == "Thunderstorms"
    assert weather.weather_words(999) == ""
    assert weather.weather_words(4) == ""  # between two bands: no words
