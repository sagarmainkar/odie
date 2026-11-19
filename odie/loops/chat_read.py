"""Chat promises and his commitments (proactive design §4 "Chats", §17; phase 4). After a chat turn in the app, ONE
model call with no tools reads what he typed and Odie's reply, and answers:
  "odie": Odie's own promises to do something later ("I'll look at the build again tonight") -> a loop owned by Odie
          with the playbook "promise", due at the promised time (odie.loops.promise_run carries it out);
  "you":  his own commitments ("I need to call the bank Friday") -> a "Track this?" offer (odie.loops.offers);
          nothing is tracked without his tap.

The model thinks, code keeps it safe (§3):
  - the call sees only his typed words and Odie's reply, never a tool's result (mail, pages, job reports), and the
    reply is fenced: it may quote other people;
  - each item quotes its words, and code checks them: Odie's must be in Odie's reply outside any quotation marks or
    "> " lines, his in his own typed words (also outside quotes); words a button or the terminal sent never propose;
  - never a secret; not what this turn's own reminder covers (the same minute) or what is already followed (the same
    words as an open loop, one of his tasks or a waiting offer); at most MOST_EACH of each;
  - the call is made only when a cheap word check says the turn may hold one (worth_reading), at most CHAT_DAILY a
    day, and each one is spent from the day's proactive budget (odie.loops.budget), so it stops when that is gone."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, time, timedelta
from pathlib import Path

from odie.agent.callbacks import wrap_untrusted
from odie.loops import budget, findings, ledger, offers
from odie.loops.secret import secret_in

log = logging.getLogger("odie.loops")
SKILL = Path(__file__).parent / "skill" / "CHAT.md"  # the prompt: the owner reads and edits it
CHAT_DAILY = 30
KEY = "loops.chat_reads"  # {"day": "2026-11-19", "used": 4}
MOST_EACH = 2
REPLY_MOST = 4000
TYPED_MOST = 1500
FOLLOWED_SHOWN = 30
SAID_LEAST = 6  # characters a quote must have to be checked against the turn
MORNING = time(9, 0)

# The gate's word lists (worth_reading). Wide on purpose: they only spare a call when nothing could be a promise;
# the model decides what is one.
LATER = (r"tomorrow|tonight|later|again|back|follow[ -]?up|remind|next|soon|weekend|morning|afternoon|evening|"
         r"monday|tuesday|wednesday|thursday|friday|saturday|sunday|in an? (?:minute|hour|day|week)|"
         r"in \d+ (?:minute|hour|day|week)s?|by (?:the )?\w+|keep an eye|keep watching|look out")
ODIE_PROMISES = re.compile(r"\b(?:i'll|i will|i'm going to|i am going to|let me|i can)\b[^.!?\n]{0,80}?\b(?:"
                           + LATER + r")\b", re.I)
HIS_COMMITMENTS = re.compile(r"\b(?:i need to|i have to|i've got to|i got to|i gotta|i must|i should|i'll|i will|"
                             r"i'm going to|i am going to|i promised|i owe|remind me|don't let me forget|"
                             r"do not let me forget|i'm supposed to|i need to remember|have to remember|"
                             r"i mustn't forget|to-?do)\b", re.I)
QUOTED = re.compile(r'"[^"\n]*"|“[^”\n]*”|«[^»\n]*»')
QUOTE_LINE = re.compile(r"^\s*>.*$", re.M)


def instruction() -> str:
    """The prompt's text, after its front matter."""
    return SKILL.read_text().split("---", 2)[-1].strip()


def plain(text: str) -> str:
    """Text as quotes are compared: curly apostrophes made straight, lower case, spaces collapsed.
    "I’ll  CHECK it" -> "i'll check it"."""
    straight = (text or "").replace("’", "'").replace("‘", "'")
    return " ".join(straight.split()).casefold()


def worth_reading(typed: str, reply: str) -> bool:
    """Whether a turn may hold a promise or a commitment, so the model is asked (the gate: no call otherwise). Odie's
    reply says it will do something with a word of later in the same sentence, or his typed words say he must or will
    do something.
      reply "I'll look at it again tonight." -> True;  he typed "I need to call the bank Friday" -> True;
      he typed "what's the weather", reply "It's sunny." -> False;  reply "I'll be here if you need me." -> False"""
    if ODIE_PROMISES.search(plain(reply)):
        return True
    return bool(HIS_COMMITMENTS.search(plain(typed)))


def should_read(store, pid: str, via: str | None, private: bool) -> bool:
    """Whether a finished chat turn is read for promises at all.
      a turn the terminal sent (an agent or a script typed it; it reads the reply at once) -> False
      a turn that read a signed-in page (nothing of it is kept, as the memory review) -> False
      a personality whose Proactive intelligence is off (its switch stops everything) -> False
      everyday Odie, or a personality with it on, typed or a tap -> True (a tap's words still never propose: read)"""
    from odie.watch import owner
    if via == "terminal" or private:
        return False
    if pid and not owner.is_proactive(store, pid):
        return False
    return True


def used_today(store, now: datetime) -> int:
    saved = store.get_setting(KEY) or {}
    if saved.get("day") != now.date().isoformat():
        return 0
    return int(saved.get("used") or 0)


def spend(store, now: datetime) -> bool:
    """Takes one chat read from today's: True when one is left (counted, and spent from the proactive budget too);
    False when today's CHAT_DAILY are used or the proactive budget is gone. 29 used -> True; 30 -> False."""
    used = used_today(store, now)
    if used >= CHAT_DAILY:
        return False
    if not budget.spend(store, now):
        return False
    store.set_setting(KEY, {"day": now.date().isoformat(), "used": used + 1})
    return True


def made_this_turn(store, pid: str, since: str) -> list[dict]:
    """The reminders and to-dos the model made in this turn (task_add), as [{"title", "due_at"}]: the call is told
    of them, and code never offers or promises what one already covers. since: when the turn began (UTC ISO)."""
    mine, values = ledger._whose(pid)
    rows = store.query(f"select title, due_at from tasks where origin='agent' and created_at >= ? and {mine} "
                       "order by id", (since[:19], *values))
    return [{"title": r["title"], "due_at": r["due_at"]} for r in rows]


def followed(store, pid: str, now: datetime) -> list[str]:
    """What is already followed for this owner, one title each: open loops, his open tasks, waiting offers."""
    titles = [lp["title"] for lp in ledger.open_loops(store, pid)]
    mine, values = ledger._whose(pid)
    titles += [r["title"] for r in store.query(f"select title from tasks where status in ('open','waiting') and {mine}",
                                               values)]
    titles += [o["what"] for o in offers.open_offers(store, pid, now)]
    return titles[-FOLLOWED_SHOWN:]


def prompt_for(store, pid: str, now: datetime, typed: str, reply: str, made: list[dict]) -> str:
    """What the call reads: the time, his typed words (his own), Odie's reply (fenced: it may quote others), the
    reminders this turn made and what is already followed (fenced: titles may come from mail)."""
    said = typed[:TYPED_MOST] or "(nothing: a button sent this turn, so write no \"you\")"
    made_lines = [f"- {m['title']}" + (f" · {m['due_at'][:16]}" if m["due_at"] else "") for m in made]
    known = [f"- {t}" for t in followed(store, pid, now)]
    parts = [f"It is {now.strftime('%A %d %B %Y, %H:%M')} (offset {now.strftime('%z')[:3]}:{now.strftime('%z')[3:]}).",
             f"What the user typed:\n{said}",
             f"Odie's reply:\n{wrap_untrusted(reply[:REPLY_MOST])}",
             f"Reminders this turn already made:\n{chr(10).join(made_lines) or '(none)'}",
             f"Already followed:\n{wrap_untrusted(chr(10).join(known) or '(nothing)')}"]
    return "\n\n".join(parts)


def parse(text: str) -> dict[str, list[dict]] | None:
    """The model's answer: {"odie": [...], "you": [...]} from the first JSON object in its reply; None when there is
    none it can read. Items that aren't objects are left out.
      'Sure: {"odie": [{"what": "Check", "said": "I'll check"}], "you": []}' -> that;  "no idea" -> None"""
    found = re.search(r"\{.*\}", text or "", re.S)
    if found is None:
        return None
    try:
        raw = json.loads(found.group(0))
    except ValueError:
        return None
    if not isinstance(raw, dict):
        return None
    out = {}
    for side in ("odie", "you"):
        items = raw.get(side) or []
        if not isinstance(items, list):
            items = []
        out[side] = [i for i in items if isinstance(i, dict)]
    return out


def unquoted(text: str) -> str:
    """Text without what it quotes: "> " lines and anything in double quotation marks.
      'Raj wrote: "I\\'ll send it Friday." Nothing yet.' -> "Raj wrote:  Nothing yet." """
    return QUOTED.sub(" ", QUOTE_LINE.sub(" ", text or ""))


def said_in(said: str, text: str) -> bool:
    """Whether a quote is in this text in the speaker's own voice: found there, outside any quotation, and long
    enough to mean something.
      "I'll look at the build again tonight" in "It failed. I'll look at the build again tonight." -> True
      "I'll send the signed contract" in 'Raj wrote: "I\\'ll send the signed contract on Friday."' -> False
      "ok" in anything -> False (too short to tell)"""
    words = plain(said).strip(" .,!?;:")
    if len(words) < SAID_LEAST:
        return False
    return words in plain(unquoted(text))


def next_morning(now: datetime) -> str:
    """09:00 tomorrow on his clock: 19 Nov 10:00 -> "2026-11-20T09:00:00+05:30"."""
    return datetime.combine(now.date() + timedelta(days=1), MORNING, now.tzinfo).isoformat(timespec="seconds")


def due_of(value, now: datetime) -> str | None:
    """A time the model wrote, as an ISO time with his offset, when it is one and still ahead; else None.
      "2026-11-20T09:00:00+05:30" -> that;  "2026-11-20" -> "2026-11-20T09:00:00+05:30";
      "2026-11-20T18:00" (no offset) -> his zone's 18:00;  "soon", "", an hour ago -> None"""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        when = datetime.fromisoformat(text)
    except ValueError:
        return None
    if len(text) == 10:
        when = datetime.combine(when.date(), MORNING)
    if when.tzinfo is None:
        when = when.replace(tzinfo=now.tzinfo)
    if when <= now:
        return None
    return when.isoformat(timespec="seconds")


def title_of(item: dict) -> str:
    return " ".join(str(item.get("what") or "").split())[:findings.TITLE_MOST]


def covered(made: list[dict], when: str | None) -> bool:
    """Whether a reminder this turn made rings at the same minute, so the item is that reminder said again ("remind
    me at 6 pm" made one at 18:00; "I'll remind you at 18:00" is it). No time -> False."""
    from odie.loops.consolidate import same_minute
    if not when:
        return False
    return any(same_minute(m["due_at"], when) for m in made)


def already_followed(store, pid: str, now: datetime, title: str) -> bool:
    """Whether something already followed has the same words: an open loop, one of his open tasks, a waiting offer.
    "Call the bank" with his to-do "Call the bank" -> True; "Call the bank" with "Pay the bank" -> False."""
    words = findings.same_words(title)
    return any(findings.same_words(t) == words for t in followed(store, pid, now))


def keep_promise(store, pid: str, session_id: str, now: datetime, item: dict, typed: str, reply: str,
                 made: list[dict]) -> int | None:
    """One of Odie's promises as a loop of its own, when the rails allow; None otherwise."""
    title = title_of(item)
    said = str(item.get("said") or "").strip()
    if not title or not said_in(said, reply) or secret_in(f"{title} {said}"):
        return None
    when = due_of(item.get("when"), now)
    if covered(made, when) or already_followed(store, pid, now, title):
        return None
    if when is None:
        when = next_morning(now)
    lid = ledger.open_loop(store, pid, now, title, "promise", owner="odie", playbook="promise", state="waiting",
                           due_at=when, source="chat", ref=f"chat:{session_id}",
                           fact=f"Odie said in chat: “{said[:300]}”",
                           card={"chat": session_id, "said": said[:300], "asked": typed[:300]})
    from odie.watch import cards as card_text
    ledger.update(store, lid, now, has_news=0, next_check_at=when, next_step=f"due {card_text.day(when[:16])}")
    return lid


def offer_commitment(store, pid: str, session_id: str, now: datetime, item: dict, typed: str,
                     made: list[dict]) -> int | None:
    """One of his commitments as a "Track this?" offer, when the rails allow; None otherwise."""
    title = title_of(item)
    said = str(item.get("said") or "").strip()
    if not typed or not title or not said_in(said, typed) or secret_in(f"{title} {said}"):
        return None
    when = due_of(item.get("when"), now)
    if covered(made, when) or already_followed(store, pid, now, title):
        return None
    return offers.add(store, pid, now, title, when, said[:300], session_id)


def apply(store, pid: str, session_id: str, now: datetime, answer: dict, typed: str, reply: str,
          made: list[dict]) -> dict:
    """Writes what the rails allow: Odie's promises as loops, his commitments as offers, at most MOST_EACH of each."""
    got: dict[str, list[int]] = {"promises": [], "offers": []}
    for item in answer.get("odie", []):
        if len(got["promises"]) >= MOST_EACH:
            break
        lid = keep_promise(store, pid, session_id, now, item, typed, reply, made)
        if lid is not None:
            got["promises"].append(lid)
    for item in answer.get("you", []):
        if len(got["offers"]) >= MOST_EACH:
            break
        oid = offer_commitment(store, pid, session_id, now, item, typed, made)
        if oid is not None:
            got["offers"].append(oid)
    return got


async def read(store, session_id: str, now: datetime, typed: str, reply: str, think,
               made: list[dict] | None = None) -> dict:
    """Reads one finished turn (the caller has checked should_read and worth_reading). typed: his typed or dictated
    words ("" when a button sent them); reply: Odie's reply; think(prompt, instruction): the call with no tools on
    the owner's brain; made: the reminders this turn made (made_this_turn). Returns {"promises": [loop ids],
    "offers": [offer ids]}; nothing when today's reads or the proactive budget are used up, or the call fails."""
    from odie import personalities
    nothing = {"promises": [], "offers": []}
    pid = personalities.of_session(store, session_id)
    made = made or []
    if not spend(store, now):
        return nothing
    try:
        answer = parse(await think(prompt_for(store, pid, now, typed, reply, made), instruction()))
    except Exception:  # noqa: BLE001 (a failed call: nothing this time, the chat is untouched)
        log.warning("chat read: the model call failed", exc_info=True)
        return nothing
    if answer is None:
        return nothing
    return apply(store, pid, session_id, now, answer, typed, reply, made)
