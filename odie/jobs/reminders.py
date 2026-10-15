"""Reminder runner: every minute, anything due is raised as a notice (the app shows it as a curtain from the top, with
Dismiss and Act; Act is what puts it in the chat) and sent to the phone as a push."""
from __future__ import annotations

import asyncio
import json
import logging

import httpx

from odie.push.send import send_to_all
from odie.store.db import Store, now_iso

log = logging.getLogger("odie.reminders")
SPEAK_WITHIN = 15  # seconds: a busy voice never holds a reminder (or the next one) up longer than this


def phrase(row) -> str:
    title = row["title"]
    if row["kind"] == "reminder":
        return f"Reminder: {title}"
    if row["kind"] in ("waiting", "followup"):
        return f"Time to check on this: {title}"
    return f"Due now: {title}"


async def _spoken(store: Store, text: str, transport: httpx.AsyncBaseTransport | None) -> dict | None:
    """The reminder as a voice memo in the chosen voice, or None (then it goes out as text, as before)."""
    from odie import media, voice
    try:
        eng, vid = voice.get_tts(store)
        audio = await asyncio.wait_for(voice.speak_wav(store, text, transport=transport), SPEAK_WITHIN)
        label = next((x["label"] for x in voice.engine_voices(eng) if x["id"] == vid), vid)
        return media.save(audio, "memo", "wav", "audio/wav", text, {**media.wav_info(audio), "transcript": text, "voice": label})
    except Exception:  # noqa: BLE001 (anything at all: the reminder still goes out, as text)
        log.warning("the spoken reminder couldn't be made; sending it as text", exc_info=True)
        return None


async def run_due(store: Store, runner, now: str | None = None, transport: httpx.AsyncBaseTransport | None = None) -> int:
    from odie import voice
    now = now or now_iso()
    n = 0
    for row in store.due_tasks(now):
        text = phrase(row)
        memo = await _spoken(store, text, transport) if voice.reminders_spoken(store) else None
        try:
            await runner.notify(text, row["id"], media=[memo] if memo else None)
        except Exception:  # noqa: BLE001
            log.exception("reminder notice failed for task %s", row["id"])
            continue
        # The task stays open until the curtain is answered: Act puts it in the chat and closes a timed ping; Dismiss
        # leaves it on Today under Now, for the user to tick off.
        store.mark_delivered(row["id"], now, notice_media=json.dumps([memo]) if memo else None)
        try:
            from odie import persona
            send_to_all(store, persona.get(store)["name"], text, url="/#chat", tag=f"task-{row['id']}")
        except Exception:  # noqa: BLE001
            log.warning("reminder push failed", exc_info=True)
        store.audit("job", "reminder", result_summary=text)
        n += 1
    return n
