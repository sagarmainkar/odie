"""Downloading from the web by code (a photo for a deck, an attachment's link): public addresses only, every redirect
checked again, the size capped while it streams."""
from __future__ import annotations

from urllib.parse import urljoin

import httpx

from odie.agent.tools.web import public_url, resolve_host

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36"
_transport: httpx.AsyncBaseTransport | None = None  # tests put a MockTransport here


class DownloadError(Exception):
    """Why a download didn't happen, in a sentence."""


async def safe_download(url: str, max_bytes: int, referer: str | None = None, timeout: float = 30) -> tuple[bytes, str]:
    """The body and its content type."""
    headers = {"User-Agent": UA, **({"Referer": referer} if referer else {})}
    async with httpx.AsyncClient(timeout=timeout, transport=_transport, headers=headers) as c:
        for _ in range(6):
            if problem := await public_url(url, lambda host: resolve_host(host)):
                raise DownloadError(f"The link isn't a public web address ({problem}).")
            async with c.stream("GET", url, follow_redirects=False) as resp:
                if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("location"):
                    url = urljoin(url, resp.headers["location"])
                    continue
                if resp.status_code >= 400:
                    raise DownloadError(f"The link answered {resp.status_code}.")
                body = bytearray()
                async for chunk in resp.aiter_bytes():
                    body += chunk
                    if len(body) > max_bytes:
                        raise DownloadError(f"It's over {max(1, max_bytes // (1024 * 1024))} MB.")
                return bytes(body), resp.headers.get("content-type", "")
    raise DownloadError("The link redirected too many times.")
