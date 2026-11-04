"""Today's weather for the morning hello: Open-Meteo's forecast for the saved location, as whole degrees and the sky in
plain words. Only the coordinates, rounded to 2 decimals, go out, and only to Open-Meteo; the model gets the answer."""
from __future__ import annotations

import logging

import httpx

from odie import location

log = logging.getLogger("odie.morning.weather")
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
FORECAST_TIMEOUT = 6.0
# WMO weather code bands, inclusive: (first code, last code, the words the hello uses).
WMO_BANDS = [
    (0, 0, "Clear"),
    (1, 2, "Mostly clear"),
    (3, 3, "Cloudy"),
    (45, 48, "Foggy"),
    (51, 57, "Drizzle"),
    (61, 67, "Rain"),
    (71, 77, "Snow"),
    (80, 82, "Showers"),
    (95, 99, "Thunderstorms"),
]


def weather_words(code: int) -> str:
    """The plain words for a WMO weather code: the first band that holds it, else "" (a code no band names).
    0 -> "Clear"; 63 -> "Rain"; 4 (between two bands) -> ""; 999 -> ""."""
    for first, last, words in WMO_BANDS:
        if first <= code <= last:
            return words
    return ""


def whole_degrees(celsius: float) -> int:
    """A temperature rounded to the nearest whole degree. 26.6 -> 27; 31.2 -> 31; 19.4 -> 19."""
    return round(celsius)


def forecast_params(lat: float, lon: float) -> dict:
    """The Open-Meteo query: the point rounded to 2 decimals (about 1 km), today's current and daily values, the
    device's own timezone, and one forecast day."""
    return {
        "latitude": round(lat, 2),
        "longitude": round(lon, 2),
        "current": "temperature_2m,weather_code",
        "daily": "temperature_2m_max,temperature_2m_min,weather_code",
        "timezone": "auto",
        "forecast_days": 1,
    }


def sky_code(body: dict) -> int | None:
    """The WMO code the words come from: the current one when Open-Meteo gave it, else today's first daily code,
    else None. {"current": {"weather_code": 0}} -> 0; {"current": {}, "daily": {"weather_code": [63]}} -> 63; {} -> None."""
    current_code = (body.get("current") or {}).get("weather_code")
    if current_code is not None:
        return current_code
    daily_codes = (body.get("daily") or {}).get("weather_code") or []
    if daily_codes:
        return daily_codes[0]
    return None


async def today_weather(store, transport=None) -> dict | None:
    """Today's weather at the saved location: {"place", "now_c", "high_c", "low_c", "words"}. None when no coordinates
    are saved (nothing is asked of the network), or when the forecast can't be fetched or read (logged at info; the
    hello goes on without weather)."""
    setting = location.get(store)
    lat = setting.get("lat")
    lon = setting.get("lon")
    if lat is None or lon is None:
        return None
    try:
        async with httpx.AsyncClient(timeout=FORECAST_TIMEOUT, transport=transport,
                                     headers={"User-Agent": location.USER_AGENT}) as client:
            response = await client.get(FORECAST_URL, params=forecast_params(lat, lon))
        if response.status_code != 200:
            log.info("the forecast answered %s", response.status_code)
            return None
        body = response.json()
        current = body["current"]
        daily = body["daily"]
        code = sky_code(body)
    except (httpx.HTTPError, ValueError, KeyError, TypeError, IndexError, AttributeError):
        log.info("the forecast failed", exc_info=True)
        return None
    return {
        "place": setting.get("place") or "",
        "now_c": whole_degrees(current["temperature_2m"]),
        "high_c": whole_degrees(daily["temperature_2m_max"][0]),
        "low_c": whole_degrees(daily["temperature_2m_min"][0]),
        "words": weather_words(code) if code is not None else "",
    }
