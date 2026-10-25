"""Where a request comes from. Two checks, before any route runs (odie.app.main wires them as OriginGate):

1. The Host a request names must be one of Odie's own. A web page can make a browser send requests to any address, but
   it can't choose the browser's idea of *which site* that is: the same-origin policy keys on the name in the address
   bar. In a DNS rebinding attack the attacker's name first points at their server, then at 127.0.0.1, so the page it
   served is now "same-origin" with Odie. The one thing the server can do about it is refuse a Host it doesn't own.
2. A browser request that changes something (POST, PUT, PATCH, DELETE) or opens a WebSocket must come from Odie's own
   page: its Origin, when the browser sends one, must name the same host. Cross-site requests the browser sends without
   a preflight (a multipart upload, a WebSocket handshake) are refused here instead.

Neither check replaces pairing (odie.devices): they are what stands when pairing is off, and what keeps a paired
browser's cookie from being used by a page that isn't Odie's.
"""
from __future__ import annotations

import ipaddress
import os
from urllib.parse import urlsplit

LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1"})
OWN_SUFFIXES = (".localhost", ".local", ".ts.net")  # names no public DNS can point at this computer: mDNS and Tailscale
UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
REFUSED_HOST = {"detail": "This address isn't one Odie answers to. Open Odie at its own address, or add this name to ODIE_HOSTS."}
REFUSED_ORIGIN = {"detail": "This request came from a page that isn't Odie's."}


def hostname_of(host_header: str) -> str:
    """The bare name in a Host header or an address: "127.0.0.1:8000" -> "127.0.0.1"; "[::1]:8000" -> "::1";
    "Mac.ts.net" -> "mac.ts.net"; "" -> ""."""
    text = host_header.strip().lower()
    if not text:
        return ""
    name = urlsplit(f"//{text}").hostname
    return name or ""


def is_ip(name: str) -> bool:
    """Whether a name is an IP address literal: "127.0.0.1" -> True; "::1" -> True; "mac.ts.net" -> False."""
    try:
        ipaddress.ip_address(name)
    except ValueError:
        return False
    return True


def own_names() -> set[str]:
    """The names this Odie is reached by, besides addresses: the phone address's host (ODIE_PUBLIC_URL, or one learned
    after start), the host it listens on, and any names in ODIE_HOSTS (comma-separated). Example: ODIE_PUBLIC_URL=
    https://mac.ts.net and ODIE_HOSTS=odie.lan -> {"mac.ts.net", "odie.lan", "127.0.0.1"} (plus whatever HOST is)."""
    from odie import config
    names = {hostname_of(urlsplit(config.settings.public_url).netloc or ""), hostname_of(config.settings.host)}
    learned = config.phone_address()
    if learned:
        names.add(hostname_of(urlsplit(learned).netloc or ""))
    for extra in os.environ.get("ODIE_HOSTS", "").split(","):
        names.add(hostname_of(extra))
    names.discard("")
    return names


def is_own_name(name: str) -> bool:
    """Whether a bare name (never an address) is one of Odie's own: loopback, a .localhost/.local/.ts.net name, or one in
    own_names. "mac.ts.net" -> True; "localhost" -> True; "rebind.attacker.test" -> False; "203.0.113.5" -> False
    (an address is not a name: see host_allowed)."""
    if not name or is_ip(name):
        return False
    if name in LOOPBACK or name.endswith(OWN_SUFFIXES):
        return True
    return name in own_names()


def host_allowed(host_header: str) -> bool:
    """Whether the name a request gives in Host is one Odie answers to. An IP address is always fine: a rebinding
    attack needs a *name* the attacker controls, and a browser never confuses an IP with another site. Loopback names,
    names under .localhost, .local (mDNS) and .ts.net (Tailscale), and Odie's own names (own_names) are fine too.
    Examples: "127.0.0.1:8000" -> True; "192.168.1.5:8000" -> True; "localhost:8000" -> True; "mac.ts.net" -> True;
    "rebind.attacker.test" -> False; "" (no Host at all) -> False."""
    name = hostname_of(host_header)
    if not name:
        return False
    if is_ip(name):
        return True
    return is_own_name(name)


def origin_allowed(origin_header: str | None, host_header: str) -> bool:
    """Whether a browser's Origin is Odie's own page. The browser sends Origin on every cross-site request, on every
    POST and on every WebSocket handshake, so one that names another host is a page that isn't Odie's. No Origin at
    all is a client that isn't a browser (curl, a test), which the pairing cookie already governs.
    An Origin that is one of Odie's own names (is_own_name) is fine whatever Host says: a proxy in front (Tailscale's)
    may hand the request on with Host rewritten to 127.0.0.1:8000 while the page's Origin stays https://mac.ts.net. An
    Origin that is an address counts only when it is the Host itself (or both are loopback): a page served from some
    other machine's address is not Odie's page.
    Examples: (None, "127.0.0.1:8000") -> True; ("http://127.0.0.1:8000", "127.0.0.1:8000") -> True;
    ("http://192.168.1.5:8000", "192.168.1.5:8000") -> True; ("http://localhost:5173", "127.0.0.1:8000") -> True (the
    dev server, the same computer); ("https://mac.ts.net", "127.0.0.1:8000") -> True (the phone, through the proxy);
    ("https://evil.example", "127.0.0.1:8000") -> False; ("http://203.0.113.5", "127.0.0.1:8000") -> False;
    ("null", anything) -> False (a sandboxed or file: page)."""
    if origin_header is None:
        return True
    origin_name = hostname_of(urlsplit(origin_header.strip().lower()).netloc or "")
    host_name = hostname_of(host_header)
    if not origin_name or not host_name:
        return False
    if origin_name == host_name:
        return True
    if origin_name in LOOPBACK and host_name in LOOPBACK:
        return True
    return is_own_name(origin_name)


def _header(scope, name: bytes) -> str | None:
    for key, value in scope.get("headers") or ():
        if key == name:
            return value.decode("latin-1")
    return None


def refused(scope) -> dict | None:
    """Which check a request fails, or None when it passes. HTTP and WebSocket requests are both looked at; the Origin
    check applies to HTTP requests that change something and to every WebSocket handshake.
    Examples: GET / with Host rebind.attacker.test -> REFUSED_HOST; POST /api/upload with Origin https://evil.example
    -> REFUSED_ORIGIN; GET /api/health from curl (no Origin) -> None; a WebSocket from Odie's own page -> None."""
    if scope["type"] not in ("http", "websocket"):
        return None
    host = _header(scope, b"host") or ""
    if not host_allowed(host):
        return REFUSED_HOST
    changes_something = scope["type"] == "websocket" or scope.get("method", "GET").upper() in UNSAFE_METHODS
    if changes_something and not origin_allowed(_header(scope, b"origin"), host):
        return REFUSED_ORIGIN
    return None


class OriginGate:
    """ASGI middleware: a request from an address Odie doesn't own, or a change from a page that isn't Odie's, is
    refused before any route (421 Misdirected Request for the Host, 403 for the Origin; a WebSocket is closed with 4403)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        problem = refused(scope)
        if problem is None:
            await self.app(scope, receive, send)
            return
        if scope["type"] == "websocket":
            from starlette.websockets import WebSocketClose
            await WebSocketClose(code=4403)(scope, receive, send)
            return
        from fastapi.responses import JSONResponse
        status = 421 if problem is REFUSED_HOST else 403
        await JSONResponse(problem, status_code=status)(scope, receive, send)
