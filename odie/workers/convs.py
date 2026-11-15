"""Conversations with a bot (spike, Nov 2026): the user talks to a bot the way he talks to Odie, each bot with its own
conversations. Design: docs/bots-design.md (Fable, 15 Nov), "a bot is someone you chat with".

A conversation is a row in bot_convs; its messages are rows in bot_msgs (the user's, the bot's replies, and the
questions the bot waits on). Each message the user sends is answered by one of the bot's jobs (odie.workers.router
start_bot with conv_id): the job's brief is the conversation so far plus the new message, so a long answer keeps
working when the app is closed, the team card follows it, and a tap it needs is asked in the conversation. The reply
lands here as the bot's message, with a push.

"@chief …" in Odie's own chat makes a conversation too (origin "chat"), so nothing a bot did is missing from its own
history."""
from __future__ import annotations

import json
import secrets

from odie.store.db import Store, now_iso

NEW_TITLE = "New conversation"
TITLE_MAX = 60
HISTORY_MESSAGES = 16      # the last messages a turn's brief carries
HISTORY_CHARS = 1500       # each one cut to this many characters
PREVIEW_MAX = 140
ROLES = ("user", "bot", "ask", "note")


def new_id() -> str:
    return "conv-" + secrets.token_hex(4)


def make(store: Store, bot: str, title: str = NEW_TITLE, origin: str = "") -> str:
    """A new, empty conversation with a bot. origin "chat": asked from Odie's chat ("@chief …")."""
    conv_id = new_id()
    now = now_iso()
    store.execute("insert into bot_convs(id,bot,title,origin,preview,unread,created_at,updated_at) values(?,?,?,?,?,?,?,?)",
                  (conv_id, bot, title[:TITLE_MAX] or NEW_TITLE, origin, "", 0, now, now))
    return conv_id


def get(store: Store, conv_id: str) -> dict | None:
    row = store.one("select * from bot_convs where id=?", (conv_id,))
    return dict(row) if row else None


def of_bot(store: Store, bot: str) -> list[dict]:
    """A bot's conversations, the latest first."""
    return [dict(r) for r in store.query("select * from bot_convs where bot=? order by updated_at desc", (bot,))]


def latest(store: Store, bot: str) -> dict | None:
    """The conversation a tap on the bot opens: its latest, or None when it has none yet."""
    row = store.one("select * from bot_convs where bot=? order by updated_at desc limit 1", (bot,))
    return dict(row) if row else None


def preview_of(text: str) -> str:
    """One line for the list: the first line with words, Markdown marks dropped, cut to PREVIEW_MAX.
    "**Go for North Goa** — base in Candolim" -> "Go for North Goa — base in Candolim"; "" -> ""."""
    for line in (text or "").splitlines():
        words = line.replace("**", "").replace("__", "").strip("#*>- \t")
        if words:
            if len(words) > PREVIEW_MAX:
                return words[: PREVIEW_MAX - 1].rstrip() + "…"
            return words
    return ""


def title_from(text: str) -> str:
    """A new conversation's title from its first message: "Which is better for a family: North Goa or South Goa?" ->
    the same, cut at a word under TITLE_MAX characters."""
    one = " ".join((text or "").split())
    if len(one) <= TITLE_MAX:
        return one or NEW_TITLE
    cut = one[:TITLE_MAX].rsplit(" ", 1)[0]
    return cut + "…"


def add(store: Store, conv_id: str, role: str, text: str, job_id: str = "", media: dict | list | None = None) -> int:
    """One message. The conversation's preview and time follow it; a bot's reply or question marks it unread."""
    assert role in ROLES
    now = now_iso()
    cur = store.execute("insert into bot_msgs(conv_id,role,text,job_id,media_json,ts) values(?,?,?,?,?,?)",
                        (conv_id, role, text, job_id, json.dumps(media) if media else None, now))
    unread = 1 if role in ("bot", "ask") else 0
    store.execute("update bot_convs set preview=?, updated_at=?, unread=max(unread, ?) where id=?",
                  (preview_of(text), now, unread, conv_id))
    return cur.lastrowid if cur is not None else 0


def messages(store: Store, conv_id: str) -> list[dict]:
    """The conversation's messages in order, each with its media; a question with its state (open, yes, no,
    expired) from job_asks."""
    out = []
    for r in store.query("select * from bot_msgs where conv_id=? order by id", (conv_id,)):
        m = dict(r)
        m["media"] = json.loads(m.pop("media_json") or "null")
        if m["role"] == "ask" and isinstance(m["media"], dict) and m["media"].get("ask"):
            row = store.one("select status from job_asks where id=?", (m["media"]["ask"],))
            m["media"]["status"] = row["status"] if row else "expired"
        out.append(m)
    return out


def mark_read(store: Store, conv_id: str) -> None:
    store.execute("update bot_convs set unread=0 where id=?", (conv_id,))


def running_job(store: Store, conv_id: str) -> str | None:
    """The job answering in this conversation now, or None. One turn at a time: a second message waits."""
    row = store.one("select id from jobs where conv_id=? and parent_id='' and status in ('queued','running') "
                    "order by created_at desc limit 1", (conv_id,))
    return row["id"] if row else None


def brief_for(store: Store, conv_id: str, text: str) -> str:
    """What the bot's job is told: the conversation so far (the last HISTORY_MESSAGES, each cut to HISTORY_CHARS),
    then the new message. A first message -> just the message."""
    earlier = [m for m in messages(store, conv_id) if m["role"] in ("user", "bot")][-HISTORY_MESSAGES:]
    if not earlier:
        return text
    lines = []
    for m in earlier:
        who = "The user" if m["role"] == "user" else "You"
        body = m["text"] if len(m["text"]) <= HISTORY_CHARS else m["text"][:HISTORY_CHARS] + " …"
        lines.append(f"{who}: {body}")
    so_far = "\n\n".join(lines)
    return f"Our conversation so far:\n\n{so_far}\n\nThe user's new message:\n\n{text}"


def send(store: Store, conv_id: str, text: str):
    """The user's message: kept, then answered by a job of the conversation's bot. Returns the job, or a line saying
    why not (a turn already running here). The conversation's privacy goes with the brief (odie.workers.privacy)."""
    from odie.workers import privacy, router
    conv = get(store, conv_id)
    if conv is None:
        return "There's no such conversation."
    if running_job(store, conv_id):
        return f"{conv['bot']} is still answering here: wait for it, or stop it."
    brief = brief_for(store, conv_id, text)
    add(store, conv_id, "user", text)
    if conv["title"] == NEW_TITLE:
        store.execute("update bot_convs set title=? where id=?", (title_from(text), conv_id))
    title = (get(store, conv_id) or conv)["title"]
    return router.start_bot(conv["bot"], title, brief, None, conv_id=conv_id, private=privacy.marks_of(store, conv_id))


async def reply(store: Store, runner, job, text: str, media: list[dict] | None) -> None:
    """A bot job's answer lands in its conversation (and the phone hears, opening that conversation)."""
    if not job.conv_id:
        return
    add(store, job.conv_id, "bot", text, job_id=job.id, media=media or None)
    await publish(runner, job)
    push(store, job, preview_of(text))


async def ask_posted(store: Store, runner, job, ask_id: str, kind: str, text: str, detail: dict) -> None:
    """A question the bot waits on shows in its conversation, with Allow / Deny there."""
    if not job.conv_id:
        return
    add(store, job.conv_id, "ask", text, job_id=job.id, media={"ask": ask_id, "kind": kind, "why": detail.get("why"),
                                                               "card": detail.get("card")})
    await publish(runner, job)


async def publish(runner, job) -> None:
    """Tell the apps a conversation changed (the bots list and an open conversation load again)."""
    bus = getattr(runner, "bus", None)
    if bus is None:
        return
    await bus.publish({"type": "bot_message", "conv": job.conv_id, "bot": job.bot})


def push(store: Store, job, line: str) -> None:
    """A push that opens the conversation; a failed push never loses the message."""
    import logging

    from odie.push.send import send_to_all
    try:
        send_to_all(store, job.bot or "A bot", line[:160] or "answered", url=f"/#bot/{job.bot}/{job.conv_id}", tag=job.id)
    except Exception:  # noqa: BLE001
        logging.getLogger("odie.workers").warning("push failed for %s", job.id, exc_info=True)


def list_row(store: Store, bot: str) -> dict:
    """How a bot stands, for its row in the list and its avatar in the drawer: its latest conversation (id, preview,
    time), whether a job of it is at work now (and the live line), whether one waits on the user's tap, whether a
    reply is unread.
      a chief whose team is at work -> working True, live "waiting for 3 bots";  a shopper at a tap -> needs_you True"""
    from odie.workers import asks, progress
    last = latest(store, bot)
    lead = store.one("select * from jobs where bot=? and parent_id='' and status in ('queued','running') "
                     "order by created_at desc limit 1", (bot,))
    open_ask = None
    for a in asks.open_for(store):
        job = store.one("select bot, parent_id from jobs where id=?", (a["job_id"],))
        if job is None:
            continue
        if job["bot"] == bot:
            open_ask = a
            break
        lead_of = store.one("select bot from jobs where id=?", (job["parent_id"],)) if job["parent_id"] else None
        if lead_of is not None and lead_of["bot"] == bot:
            open_ask = a
            break
    unread = store.one("select count(*) as n from bot_convs where bot=? and unread=1", (bot,))["n"]
    return {"conversation": last["id"] if last else None, "preview": last["preview"] if last else "",
            "updated_at": last["updated_at"] if last else None, "working": lead is not None,
            "live": progress.now_line(store, dict(lead)) if lead is not None else "",
            "needs_you": open_ask is not None, "ask": open_ask["text"] if open_ask else "", "unread": unread > 0}
