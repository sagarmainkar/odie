"""A bot waiting on the user (spike, Nov 2026). A bot with the browser power never decides a risky step alone: when
the chat would ask for a tap (a click that may order, pay, book or send; text typed into a site; leaving a site whose
signed-in pages it read), the bot's job waits. So does a sign-in: the user signs in in the live view, then says Done.

The question is a row in job_asks and a card on Today (Jobs). The chat gets a message with a push saying what waits.
Only the app's buttons answer it (POST /api/jobs/asks/{id}); there is no tool and no chat words that answer, so a model
(the bot itself, the chief, the chat, or an agent at the terminal) can never say yes for the user. No answer within
WAIT_SECONDS (9 minutes) counts as no. A restart of Odie expires every open question (the bot that asked is gone)."""
from __future__ import annotations

import asyncio
import json
import logging
import secrets

from odie.store.db import Store, now_iso

log = logging.getLogger("odie.workers")

WAIT_SECONDS = 9 * 60  # under the browser's 10 idle minutes, so an Allow still finds the page open
KINDS = ("tap", "sign_in")
ANSWERS = ("yes", "no")
_waiting: dict[str, asyncio.Future] = {}  # ask id -> the future the bot's guard awaits


def new_id() -> str:
    return "ask-" + secrets.token_hex(3)


def open_for(store: Store, job_id: str | None = None) -> list[dict]:
    """The open questions, oldest first (one job's when job_id is given), with their detail as a dict."""
    if job_id:
        rows = store.query("select * from job_asks where status='open' and job_id=? order by created_at", (job_id,))
    else:
        rows = store.query("select * from job_asks where status='open' order by created_at")
    out = []
    for r in rows:
        item = dict(r)
        item["detail"] = json.loads(item.pop("detail_json") or "{}")
        out.append(item)
    return out


def answer(store: Store, ask_id: str, said: str) -> bool:
    """The user's tap: "yes" (Allow, or Done after signing in) or "no" (Deny, Skip). Decides whether the answer
    lands: an open question whose bot is still waiting -> True, and the bot goes on; an unknown id, one already
    answered or expired, or a word other than yes/no -> False."""
    if said not in ANSWERS:
        return False
    row = store.one("select status from job_asks where id=?", (ask_id,))
    if row is None or row["status"] != "open":
        return False
    store.execute("update job_asks set status=?, answered_at=? where id=?", (said, now_iso(), ask_id))
    waiting = _waiting.get(ask_id)
    if waiting is not None and not waiting.done():
        waiting.set_result(said)
    return True


def expire_all(store: Store) -> int:
    """Odie started: no bot from before is waiting any more, so every open question expires. Returns how many."""
    n = store.one("select count(*) as n from job_asks where status='open'")["n"]
    store.execute("update job_asks set status='expired', answered_at=? where status='open'", (now_iso(),))
    return n


def waits_on_user(store: Store, job_id: str) -> bool:
    """Is this job waiting for the user right now (an open question)? The watchdog doesn't call a job stuck while it
    waits. A bot at a "Place order" tap -> True; a bot searching -> False."""
    return bool(store.one("select 1 from job_asks where job_id=? and status='open'", (job_id,)))


async def ask(store: Store, runner, job, kind: str, text: str, detail: dict | None = None,
              wait_seconds: float = WAIT_SECONDS) -> str:
    """Ask the user and wait: post the question into the job's chat (with a push), keep it open on Today, and return
    "yes" or "no" once the user taps, or "no" when WAIT_SECONDS pass without an answer (the row says expired).
    A sign-in's detail carries the Sign in card (site, tab, why, url), posted with the message so the live view opens
    from the chat."""
    assert kind in KINDS
    ask_id = new_id()
    store.execute("insert into job_asks(id,job_id,kind,text,detail_json,status,created_at) values(?,?,?,?,?,?,?)",
                  (ask_id, job.id, kind, text, json.dumps(detail or {}), "open", now_iso()))
    future: asyncio.Future = asyncio.get_running_loop().create_future()
    _waiting[ask_id] = future
    line = ask_line(job, kind, text)
    try:
        if job.conv_id:  # asked in the bot's conversation, with Allow / Deny there too
            from odie.workers import convs
            await convs.ask_posted(store, runner, job, ask_id, kind, text, detail or {})
        if job.session_id:  # asked from a chat: a line there; a conversation-only job never posts to Odie's chat
            await runner.post_message(line, job.session_id, kind="job")
        _push(store, line, job.id)
        return await asyncio.wait_for(future, wait_seconds)
    except TimeoutError:
        store.execute("update job_asks set status='expired', answered_at=? where id=? and status='open'",
                      (now_iso(), ask_id))
        return "no"
    except BaseException:  # cancelled, or the post failed: the question must not stay open with nobody waiting
        store.execute("update job_asks set status='expired', answered_at=? where id=? and status='open'",
                      (now_iso(), ask_id))
        raise
    finally:
        _waiting.pop(ask_id, None)


def ask_line(job, kind: str, text: str) -> str:
    """The chat's message for a question; the buttons are on Today (the chat's own Sign in card would tell the chat,
    not the bot). A tap -> "✋ shopper waits for your tap (job-…): Click "Buy" on amazon.in. Allow or Deny it on Today.";
    a sign-in -> "🔑 shopper needs you to sign in (job-…): amazon.in: …. Sign in from Today, then tap Done."
    """
    who = job.bot or "A Worker"
    if kind == "sign_in":
        return f"🔑 {who} needs you to sign in ({job.id}): {text}. Sign in from Today, then tap Done."
    return f"✋ {who} waits for your tap ({job.id}): {text}. Allow or Deny it on Today."


def _push(store: Store, text: str, tag: str) -> None:
    """A push to the phone; a failed push never stops the question."""
    from odie import persona
    from odie.push.send import send_to_all
    try:
        send_to_all(store, persona.get(store)["name"], text[:160], url="/#today", tag=tag)
    except Exception:  # noqa: BLE001
        log.warning("push failed for %s", tag, exc_info=True)
