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


UNREACHABLE = "The link couldn't be reached."


async def safe_download(url: str, max_bytes: int, referer: str | None = None, timeout: float = 30) -> tuple[bytes, str]:
    """The body and its content type. Every failure is a DownloadError in a sentence: a site that refuses the
    connection, times out or breaks off mid-answer -> "The link couldn't be reached." (httpx's own errors never get
    out, so one picture that can't be fetched is only that picture's failure)."""
    try:
        return await _download(url, max_bytes, referer, timeout)
    except httpx.HTTPError:
        raise DownloadError(UNREACHABLE) from None


async def _download(url: str, max_bytes: int, referer: str | None, timeout: float) -> tuple[bytes, str]:
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
