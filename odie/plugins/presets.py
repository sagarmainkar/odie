"""Ready-made connected apps: Zapier and Composio. The user pastes the link the service gives them, and a key if it
uses one. Odie checks the link, lists its tools, and saves it like any other MCP server."""
from __future__ import annotations

from urllib.parse import urlsplit

PRESETS: dict[str, dict] = {
    "zapier": {
        "title": "Zapier", "hosts": ("mcp.zapier.com", "actions.zapier.com"),
        "where": ("On mcp.zapier.com, make a new MCP server for “Other”, add the apps you want (Gmail, Calendar…) and "
                  "connect your accounts, then open Connect and copy its server link and its code."),
        "key_label": "Zapier's code (if any)", "key_header": "Authorization", "key_format": "Bearer {key}",
        "description": "Apps connected through Zapier: Gmail, Calendar, Sheets, Slack and more",
    },
    "composio": {
        "title": "Composio", "hosts": ("composio.dev",),
        "where": "On dashboard.composio.dev, open MCP, make a server with the apps you want, and copy its URL.",
        "key_label": "API key, only if your link needs one", "key_header": "x-api-key", "key_format": "{key}",
        "description": "Apps connected through Composio: Gmail, Calendar, GitHub, Notion and more",
    },
}


def _on(host: str, hosts: tuple[str, ...]) -> bool:
    return any(host == h or host.endswith("." + h) for h in hosts)


def preset_of(url: str) -> str | None:
    """Which service a link belongs to, or None."""
    host = (urlsplit(url.strip()).hostname or "").lower()
    return next((pid for pid, p in PRESETS.items() if _on(host, p["hosts"])), None)


def spec_for(preset: str, url: str, key: str = "") -> dict:
    """The server spec for a pasted link (and key). ValueError, in plain words, for anything else."""
    p = PRESETS.get(preset)
    if p is None:
        raise ValueError("Zapier or Composio only.")
    url, key = (url or "").strip(), (key or "").strip()
    u = urlsplit(url)
    if u.scheme != "https" or not u.hostname:
        raise ValueError(f"Paste the https link {p['title']} gives you.")
    if not _on(u.hostname.lower(), p["hosts"]):
        raise ValueError(f"That isn't a {p['title']} link: it should be on {p['hosts'][0]}.")
    spec = {"url": url, "title": p["title"], "description": p["description"]}
    if key and not carries_token(url):  # a link with its own token: a second code makes the service refuse it
        spec["headers"] = {p["key_header"]: p["key_format"].format(key=key)}
    return spec


def carries_token(url: str) -> bool:
    """The link has its code in it (?token=…, ?api_key=…), so the code box isn't needed."""
    from urllib.parse import parse_qsl
    return any(k.lower() in ("token", "api_key", "apikey", "key", "secret") and v for k, v in parse_qsl(urlsplit(url).query))


STALE = (("not found or invalid secret", "{title} doesn't accept this link any more: its server was deleted or its secret "
                                         "changed. On {where}, open your server, then Connect, and copy the link again."),
         ("invalid oauth token", "{title} doesn't accept the code: copy the server link and its code again from {where}'s "
                                 "Connect page (a link with ?token= in it needs no code)."))


def plain_reason(preset: str, reason: str) -> str:
    """What a service's refusal means, in plain words, with what to do; any other reason as it was."""
    p = PRESETS.get(preset) or {}
    for needle, said in STALE:
        if needle in reason.lower():
            return said.format(title=p.get("title", "The service"), where=p.get("hosts", ("its site",))[0])
    return reason
