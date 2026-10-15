"""One call, everything (spec part 4): read the Markdown; fetch the photos; write the HTML deck; render it in Odie's own
browser to a PDF and a picture of each slide; build the native PowerPoint; save them all in the workspace under one
name; hand the chat one card (the PDF, carrying its PowerPoint and previews). Without a browser, or when rendering
fails, the PowerPoint still arrives and the card says why there are no previews."""
from __future__ import annotations

import asyncio
import io
import logging
from pathlib import Path

from PIL import Image

from odie import media
from odie.decks.html import H, W, render_html
from odie.decks.model import DeckError, parse
from odie.decks.photos import fetch_all
from odie.decks.pptx import build_pptx
from odie.decks.themes import theme

log = logging.getLogger("odie.decks")
PPTX_MIME = "application/vnd.openxmlformats-officedocument.presentationml.presentation"
NO_CHROME = "The PDF and previews need Chrome, Edge or Brave on this computer."
EXTS = ("pdf", "pptx", "html", "deck.md")


def _browser():
    from odie.browser import find, shared
    return shared() if find.browser_binary() else None


def _free_stem(folder: Path, name: str) -> str:
    """name, or "name (2)" and so on: no file of this deck overwrites an older one."""
    stem, n = name, 2
    while any((folder / f"{stem}.{ext}").exists() for ext in EXTS):
        stem = f"{name} ({n})"
        n += 1
    return stem


def _jpeg(data: bytes, size: tuple[int, int], quality: int) -> bytes:
    img = Image.open(io.BytesIO(data)).convert("RGB").resize(size, Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, "JPEG", quality=quality, optimize=True, progressive=True)
    return out.getvalue()


def _hand_over(path: Path, data: bytes, mime: str, title: str) -> dict:
    path.write_bytes(data)
    m = media.save(data, "file", path.suffix.lstrip("."), mime, title, {"filename": path.name})
    return {k: m[k] for k in ("id", "kind", "title", "filename", "size")}


async def make_deck(markdown: str, title: str = "", theme_name: str = "editorial", browser="default") -> dict:
    """{"result", "media"} for the chat, or {"error"} saying what to change. browser: Odie's (by default), None for
    no browser, or a stand-in with render()."""
    from odie.agent.tools.files import safe_name, workspace
    try:
        deck = parse(markdown, title)
    except DeckError as e:
        return {"error": str(e)}
    th = theme(theme_name)
    photos, failed = await fetch_all(deck.photo_refs())
    try:  # heavy (every photo embedded twice): off the event loop, so chat and the browser keep answering
        html = await asyncio.to_thread(render_html, deck, th, photos)
        pptx = await asyncio.to_thread(build_pptx, deck, th, photos)
    except Exception as e:  # noqa: BLE001 (a builder bug never ends the chat turn: the model hears why)
        log.warning("deck build failed", exc_info=True)
        return {"error": f"The deck couldn't be built ({type(e).__name__}: {str(e)[:160]}). Simplify the slide that has it, or try again."}
    ws = workspace()
    stem = _free_stem(ws, safe_name((title or deck.title or "Slides").replace("/", "-").replace("\\", "-")))
    (ws / f"{stem}.html").write_text(html, encoding="utf-8")
    (ws / f"{stem}.deck.md").write_text(markdown, encoding="utf-8")
    pptx_media = _hand_over(ws / f"{stem}.pptx", pptx, PPTX_MIME, f"{deck.title} · PowerPoint")
    browser = _browser() if browser == "default" else browser
    note, pages, pdf = "", [], None
    if browser is None:
        note = NO_CHROME
    else:
        try:
            pdf, shots = await browser.render(html, W, H, len(deck.slides))
            for i, shot in enumerate(shots, 1):
                thumb = await asyncio.to_thread(_jpeg, shot, (480, 270), 80)
                view = await asyncio.to_thread(_jpeg, shot, (1600, 900), 85)
                t = media.save(thumb, "page", "jpg", "image/jpeg", f"{deck.title} · slide {i}")
                v = media.save(view, "page", "jpg", "image/jpeg", f"{deck.title} · slide {i}")
                pages.append({"thumb": t["id"], "view": v["id"]})
        except Exception as e:  # noqa: BLE001 (the PowerPoint still goes)
            log.warning("deck render failed", exc_info=True)
            note, pdf, pages = f"Previews weren't available this time ({str(e)[:120]}).", None, []
    info = {"slides": len(deck.slides), "theme": th.name, "pages": pages, **({"note": note} if note else {})}
    if pdf is not None:
        m = _hand_over(ws / f"{stem}.pdf", pdf, "application/pdf", deck.title)
        info["pptx"] = pptx_media
        formats = "as a PDF and a PowerPoint"
    else:
        m = pptx_media
        formats = "as a PowerPoint"
    media.update(m["id"], {"deck": info})
    m = {**m, "deck": info}
    text = f"Made {deck.title}: {len(deck.slides)} slides ({th.label}), {formats}; they're under your reply."
    if failed:
        text += f" Photos that couldn't be fetched (their slides use the no-photo layout): {', '.join(failed)}."
        from odie.agent import turn
        if turn.private_sites():
            text += " This chat read a signed-in page, so photos from the web aren't fetched here: a new chat can make it with photos."
    if note:
        text += f" {note}"
    return {"result": text, "media": m}
