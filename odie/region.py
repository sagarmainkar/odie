"""Where the user is, as this computer says: its timezone, its language and region (the locale), and the currency
that goes with the region. Read once at start; ODIE_TIMEZONE, ODIE_LOCALE and ODIE_CURRENCY override them."""
from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

CURRENCY_BY_COUNTRY = {
    "IN": "INR", "US": "USD", "GB": "GBP", "CA": "CAD", "AU": "AUD", "NZ": "NZD", "SG": "SGD", "AE": "AED",
    "JP": "JPY", "CN": "CNY", "HK": "HKD", "CH": "CHF", "SE": "SEK", "NO": "NOK", "DK": "DKK", "ZA": "ZAR",
    "BR": "BRL", "MX": "MXN", "IE": "EUR", "DE": "EUR", "FR": "EUR", "ES": "EUR", "IT": "EUR", "NL": "EUR",
    "BE": "EUR", "AT": "EUR", "PT": "EUR", "FI": "EUR",
}
SYMBOL = {"INR": "₹", "USD": "$", "GBP": "£", "EUR": "€", "JPY": "¥", "CNY": "¥", "AUD": "A$", "CAD": "C$",
          "NZD": "NZ$", "SGD": "S$", "HKD": "HK$"}


def valid_zone(name: str) -> bool:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return False
    return True


def system_timezone(localtime: Path = Path("/etc/localtime"), debian: Path = Path("/etc/timezone")) -> str:
    """The IANA name ("Asia/Kolkata") from /etc/localtime's link (macOS and most Linux), else /etc/timezone, else UTC."""
    try:
        target = str(localtime.readlink())
    except OSError:
        target = ""
    if "zoneinfo/" in target and valid_zone(name := target.split("zoneinfo/", 1)[1]):
        return name
    try:
        name = debian.read_text().strip()
    except OSError:
        name = ""
    return name if name and valid_zone(name) else "UTC"


def normalize_locale(raw: str | None) -> str | None:
    """"en_IN", "en_US.UTF-8", "zh_Hans_CN", "de_DE@euro" -> BCP 47 ("en-IN"); None for C/POSIX or nonsense."""
    s = (raw or "").split(".")[0].split("@")[0].strip().replace("_", "-")
    parts = [p for p in s.split("-") if p]
    if not parts or not parts[0].isalpha() or parts[0].upper() in ("C", "POSIX"):
        return None
    tail = [p.title() if len(p) == 4 and p.isalpha() else p.upper() for p in parts[1:] if p.isalnum()]
    return "-".join([parts[0].lower(), *tail])


def system_locale(platform: str = sys.platform, environ: Mapping[str, str] = os.environ,
                  run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> str:
    """macOS: the region chosen in System Settings (AppleLocale); Linux: LC_ALL, LC_MESSAGES or LANG. Else en-US."""
    if platform == "darwin":
        try:
            r = run(["defaults", "read", "-g", "AppleLocale"], capture_output=True, text=True, timeout=3)
            if loc := normalize_locale(r.stdout.strip()):
                return loc
        except (OSError, subprocess.SubprocessError):
            pass
    for key in ("LC_ALL", "LC_MESSAGES", "LANG"):
        if loc := normalize_locale(environ.get(key)):
            return loc
    return "en-US"


def country_of(locale: str) -> str:
    """"en-IN" -> "IN"; "" when the locale names no region."""
    last = locale.split("-")[-1]
    return last if len(last) == 2 and last.isalpha() and last.isupper() else ""


def currency_for(country: str) -> str:
    return CURRENCY_BY_COUNTRY.get(country, "USD")


def currency_symbol(code: str) -> str:
    return SYMBOL.get(code, code)
