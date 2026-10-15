"""The key catcher: anything that looks like a key in a setup message is stopped before the model or the history sees
it, and the user is pointed to the key form."""
from __future__ import annotations

import re

SHAPES = [
    ("anthropic", re.compile(r"\bsk-ant-[A-Za-z0-9_-]{16,}")),
    ("openrouter", re.compile(r"\bsk-or-[A-Za-z0-9_-]{16,}")),
    ("openai", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    ("tavily", re.compile(r"\btvly-[A-Za-z0-9_-]{12,}")),
    ("gemini", re.compile(r"\bAIza[0-9A-Za-z_-]{30,}")),
    ("composio", re.compile(r"\bck_[A-Za-z0-9_-]{12,}")),
    ("brave", re.compile(r"\bBSA[A-Za-z0-9_-]{20,}")),
    ("bearer", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{16,}")),
]


SECRET_NAME = re.compile(r"key|token|secret|pass(word|wd)?|pwd|auth|sig(nature)?|credential", re.I)
KEY_PREFIX = re.compile(r"^(sk-|sk_|ghp_|gho_|github_pat_|xox[abp]-|AIza|tvly-|lsv2_|ck_|BSA)[A-Za-z0-9_\-]{8,}")
_UUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_HEX = re.compile(r"^[0-9a-fA-F]{32,}$")
_LINK_SAFE = re.compile(r"^[A-Za-z0-9_\-=+.~%]{20,}$")


def secret_part(s: str) -> bool:
    """A piece of a link (a path segment, a query value) that looks like a key: a known key prefix, a UUID, 32 or more
    hex digits, or 20 or more link-safe characters mixing upper case, lower case and digits. Zapier puts its key in the
    path; Composio, a server id."""
    if KEY_PREFIX.match(s) or _UUID.match(s) or _HEX.match(s):
        return True
    return bool(_LINK_SAFE.match(s)) and any(c.isupper() for c in s) and any(c.islower() for c in s) and any(c.isdigit() for c in s)


def secret_link(token: str) -> bool:
    """An http(s) link with a key in it: a Zapier or Composio link with a key-like part, or any link with a value named
    like a secret (?token=…) or a known key prefix. Other long ids (a Google Doc's, a commit's) are left alone: only
    Settings masks those."""
    from urllib.parse import parse_qsl, urlsplit
    from odie.plugins.presets import preset_of
    if not re.match(r"https?://", token):
        return False
    u = urlsplit(token)
    parts, query = u.path.split("/"), parse_qsl(u.query)
    if any(SECRET_NAME.search(k) and v for k, v in query) or any(KEY_PREFIX.match(p) for p in parts):
        return True
    return preset_of(token) is not None and (any(secret_part(p) for p in parts) or any(secret_part(v) for _, v in query))


def _random(token: str) -> bool:
    """A long string of mixed upper case, lower case and digits, with no dots or slashes (not a URL, path or hash)."""
    return (len(token) >= 32 and re.fullmatch(r"[A-Za-z0-9_-]+", token) is not None and any(c.isupper() for c in token)
            and any(c.islower() for c in token) and any(c.isdigit() for c in token))


def key_in(text: str) -> str | None:
    """The provider the text's key looks like, "app_link" for a link with a key in it, "unknown" for a long random
    string, or None."""
    for provider, rx in SHAPES:
        if rx.search(text or ""):
            return provider
    words = [t.strip(".,;:()[]{}<>'\"") for t in (text or "").split()]
    if any(secret_link(w) for w in words):
        return "app_link"
    return "unknown" if any(_random(w) for w in words) else None
