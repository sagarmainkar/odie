"""The signed-in sites (spec Part 2): the registrable domains where a "Your turn" sign-in finished with Done. The cookies
live in Odie's browser profile; this list is what the guard and Settings use."""
from __future__ import annotations

import ipaddress
from datetime import datetime
from urllib.parse import urlsplit

KEY = "browser.sites"
ORIGINS = 20  # addresses kept per site
SECOND_LEVEL = {"co.in", "co.uk", "com.au", "co.jp", "com.sg", "org.in", "net.in", "gov.in", "ac.in", "edu.in", "co.nz",
                "com.br", "co.za", "org.uk", "ac.uk", "com.mx", "co.id", "com.my"}

# Shared hosting: anyone can have an app here, so each app is a site of its own (evil.herokuapp.com isn't
# the-internet.herokuapp.com). The common ones from the Public Suffix List's private section.
SHARED = {"herokuapp.com", "github.io", "gitlab.io", "vercel.app", "netlify.app", "pages.dev", "workers.dev", "web.app",
          "firebaseapp.com", "appspot.com", "azurewebsites.net", "cloudfront.net", "blogspot.com", "onrender.com", "fly.dev",
          "glitch.me", "repl.co", "replit.app", "ngrok.io", "ngrok-free.app", "wordpress.com", "myshopify.com",
          "amplifyapp.com", "surge.sh", "deno.dev", "railway.app", "s3.amazonaws.com", "translate.goog"}


def site_of(url_or_host: str) -> str:
    """The registrable domain: www.amazon.in and pay.amazon.in are amazon.in; amazon.com is another site."""
    s = (url_or_host or "").strip()
    host = (urlsplit(s).hostname if "://" in s else s.split("/")[0].split(":")[0]) or ""
    host = host.lower().rstrip(".")
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    labels = [x for x in host.split(".") if x]
    if len(labels) <= 2:
        return ".".join(labels)
    for n in (3, 2):  # an app on shared hosting keeps its own name
        if len(labels) > n and ".".join(labels[-n:]) in SHARED:
            return ".".join(labels[-n - 1:])
    return ".".join(labels[-3:]) if ".".join(labels[-2:]) in SECOND_LEVEL else ".".join(labels[-2:])


def _all(store) -> dict:
    return dict(store.get_setting(KEY) or {})


def listing(store) -> list[dict]:
    return sorted(({"domain": d, **v} for d, v in _all(store).items()), key=lambda s: s.get("since") or "", reverse=True)


def origin_of(url: str) -> str:
    u = urlsplit(url if "://" in url else "https://" + url)
    return f"{u.scheme}://{u.netloc}".lower() if u.scheme in ("http", "https") and u.netloc else ""


def record(store, domain: str, now: datetime, origins=()) -> None:
    """The user signed in here; `origins` are the addresses it was seen on (their storage is cleared on Sign out)."""
    d = site_of(domain)
    if not d:
        return
    got = _all(store)
    at = now.isoformat(timespec="seconds")
    mine = {o for o in (origin_of(x) for x in origins) if o and site_of(o) == d}
    got[d] = {"since": got.get(d, {}).get("since") or at, "last_used": at,
              "origins": sorted(set(got.get(d, {}).get("origins") or ()) | mine)[:ORIGINS]}
    store.set_setting(KEY, got)


def seen(store, url: str) -> None:
    """A signed-in site's page was open at this address: remember its origin for Sign out."""
    got, d, o = _all(store), site_of(url), origin_of(url)
    if d in got and o and o not in (got[d].get("origins") or []):
        got[d]["origins"] = sorted({*(got[d].get("origins") or []), o})[:ORIGINS]
        store.set_setting(KEY, got)


def origins_of(store, domain: str) -> list[str]:
    return list(_all(store).get(site_of(domain), {}).get("origins") or [])


def touch(store, domain: str, now: datetime) -> None:
    got = _all(store)
    d = site_of(domain)
    if d in got:
        got[d]["last_used"] = now.isoformat(timespec="seconds")
        store.set_setting(KEY, got)


def remove(store, domain: str) -> bool:
    got = _all(store)
    if got.pop(site_of(domain), None) is None:
        return False
    store.set_setting(KEY, got)
    return True


def is_signed_in(store, url: str) -> bool:
    d = site_of(url)
    return bool(d) and d in _all(store)
