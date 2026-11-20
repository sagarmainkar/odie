"""The morning learning check (proactive design §18, his shape of 20 Nov): once a day from 08:30, after the morning
hello and never in the way of a chat, Odie looks back at yesterday's chats for what is worth learning:

  - his corrections ("no, CC my accountant", "shorter"),
  - Odie correcting itself (a step failed and it found the way that works),
  - work he asked for again.

Code first finds, for each of yesterday's exchanges, the most alike older exchanges (recall's search, by meaning when
it can). Then ONE model call with no tools reads yesterday with those, his memory titles, his skills and the evening
review's skill ideas, and answers in a fixed schema. Code applies the answer within rails:

  skills  a "Learn this?" loop (kind "skill", his card: Teach, Done, Later) only when the answer names at least one
          of yesterday's exchanges AND one older exchange from another day (seen twice or more: a pattern, never a
          one-off), only ids it was shown, at most MOST_NEW a day, never one already open or turned down (Done) in the
          last REMEMBER_DAYS. Its Why? is those chats. A change to a skill names one of his own skills.
  rules   a repeated always/never of his, saved as a rule (odie.memory.rules) only when its quote is his typed words.

Teach sends a chat request naming the loop; the skill builder drafts (staging, checked, nothing runs) and his Approve
installs; the install closes the loop and the skill is marked learned, so it fades when unused (odie.skills.fade).
No call when yesterday had no chats. Chats are data: fenced, and the answer can only do the above."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from pathlib import Path

from odie.agent.callbacks import wrap_untrusted
from odie.loops import budget, ledger
from odie.loops.secret import secret_in

log = logging.getLogger("odie.loops")
SKILL = Path(__file__).parent / "skill" / "LEARN.md"  # the prompt: the owner reads and edits it
AT = (8, 30)
DAY = "learning.day"  # per owner (odie.watch.owner.key): the day it last ran
KIND = "skill"
MOST_NEW = 2  # "Learn this?" cards a day
MOST_RULES = 2
YESTERDAY_MOST = 16  # exchanges read from yesterday (his longest first)
ALIKE = 3  # older exchanges found for each
EXCHANGE_CHARS = 900
REMEMBER_DAYS = ledger.REMEMBER_DAYS  # a "Learn this?" he turned down is not asked again for this long
ID = re.compile(r"^([YO])(\d+)$")


def _key(pid: str, name: str) -> str:
    from odie.watch.owner import key
    return key(name, pid)


def instruction() -> str:
    """The prompt's text, after its front matter."""
    return SKILL.read_text().split("---", 2)[-1].strip()


# --- when ---

def due(store, pid: str, now: datetime) -> bool:
    """Whether this owner's learning check is due: it is AT (08:30) or later today and it hasn't run today.
    08:29 -> False; 08:30 -> True; ran at 08:31, asked at 14:00 -> False; the next morning -> True."""
    if (now.hour, now.minute) < AT:
        return False
    return store.get_setting(_key(pid, DAY)) != now.date().isoformat()


def mark_ran(store, pid: str, now: datetime) -> None:
    store.set_setting(_key(pid, DAY), now.date().isoformat())


def owners_due(store, now: datetime) -> list[str]:
    """The owners whose check is due: everyday Odie, and each personality with Proactive intelligence on."""
    from odie.loops import clock
    return [pid for pid in clock.owners(store) if due(store, pid, now)]


# --- what it reads ---

def yesterdays_lines(store, pid: str, now: datetime) -> list:
    """Yesterday's chat lines of this owner's threads (odie.recall.chats), oldest first."""
    from zoneinfo import ZoneInfo

    from odie import config, personalities
    from odie.recall.chats import chat_lines
    s = config.settings
    start = datetime.combine((now - timedelta(days=1)).date(), datetime.min.time(), tzinfo=now.tzinfo)
    end = start + timedelta(days=1)
    lines = chat_lines(s.sessions_db_path, s.app_name, s.user_id, since=start.timestamp(), until=end.timestamp(),
                       tz=ZoneInfo(s.timezone))
    return [ln for ln in lines if personalities.of_session(store, ln.session_id) == pid]


def his_typed(lines: list) -> list[str]:
    """His own words among the lines: what he typed, never what the odie command typed for him. (A card's request
    is told apart later, by its "loop #": odie.memory.rules.his_words.)"""
    return [ln.text for ln in lines if ln.author == "you" and ln.via != "terminal"]


def pick(exchanges: list) -> list:
    """Yesterday's exchanges worth reading, at most YESTERDAY_MOST: the ones where he said the most, back in time
    order. A card's request ("Tell me about loop #3") is left out: it says nothing he hadn't been asked."""
    from odie.memory.rules import CARD_WORDS
    mine = [e for e in exchanges if not CARD_WORDS.search(e.text.split("\n", 1)[0])]
    longest = sorted(mine, key=lambda e: len(e.text.split("\n", 1)[0]), reverse=True)[:YESTERDAY_MOST]
    return sorted(longest, key=lambda e: e.ts)


async def alike(store, pid: str, picked: list, before: str) -> dict[int, list]:
    """For each picked exchange (by position), the ALIKE older chat passages most like his words in it, from days
    before `before` (ISO day), never a thread this owner may not read. A search that fails finds nothing."""
    from odie import personalities
    from odie.recall.fill import recall_index
    from odie.vault.settings import embedder_for
    hidden = personalities.hidden_from(store, pid)
    until = (datetime.fromisoformat(before) - timedelta(days=1)).date().isoformat()
    out: dict[int, list] = {}
    try:
        index = recall_index()
        embedder = embedder_for(store)
    except Exception:  # noqa: BLE001
        log.warning("learning: recall can't be opened", exc_info=True)
        return out
    for n, e in enumerate(picked):
        his = e.text.split("\n", 1)[0].removeprefix("you: ")
        try:
            hits = await index.search(his, k=ALIKE, embedder=embedder, until=until, hidden_sessions=hidden)
        except Exception:  # noqa: BLE001
            log.warning("learning: a recall search failed", exc_info=True)
            hits = []
        out[n] = [h for h in hits if h.kind == "chat"]
    return out


def numbered(picked: list, found: dict[int, list]) -> tuple[dict[str, dict], str]:
    """Every exchange the model may name, by id (Y1.. yesterday's, O1.. older ones, each older one once), with the text
    it reads: "Y1 (19 Nov, chat-2026-11-19-2)\nyou: …\nOdie: …\n  alike: O1, O2". Returns (ids -> what each is, text)."""
    ids: dict[str, dict] = {}
    older: dict[str, str] = {}
    blocks = []
    for n, e in enumerate(picked, 1):
        yid = f"Y{n}"
        ids[yid] = {"session": e.session_id, "day": e.day, "text": e.text}
        alike_ids = []
        for hit in found.get(n - 1, []):
            if hit.ref not in older:
                oid = f"O{len(older) + 1}"
                older[hit.ref] = oid
                ids[oid] = {"session": hit.ref.split("@", 1)[0], "day": hit.day, "text": hit.text}
            alike_ids.append(older[hit.ref])
        line = f"{yid} ({e.day})\n{e.text[:EXCHANGE_CHARS]}"
        if alike_ids:
            line += "\n  alike: " + ", ".join(alike_ids)
        blocks.append(line)
    for ref, oid in older.items():
        blocks.append(f"{oid} ({ids[oid]['day']})\n{ids[oid]['text'][:EXCHANGE_CHARS]}")
    return ids, "\n\n".join(blocks)


def skills_text() -> str:
    """His skills and the built-in ones, one line each: "travel-itinerary (yours): Plans trips day by day"."""
    from odie.skills import builder
    lines = []
    for root, whose in ((builder.user_dir(), "yours"), (builder.BUILTIN_DIR, "built in")):
        if not root.is_dir():
            continue
        for d in sorted(root.iterdir()):
            md = d / "SKILL.md"
            if not md.exists():
                continue
            found = re.search(r"^description:\s*(.+)$", md.read_text(), re.M)
            words = found.group(1).strip() if found else ""
            lines.append(f"{d.name} ({whose}): {words[:140]}")
    return "\n".join(lines)


def learn_loops_text(store, pid: str, now: datetime) -> str:
    """The "Learn this?" loops open or turned down lately: the model must not ask again."""
    lines = []
    for lp in ledger.open_loops(store, pid):
        if lp["kind"] == KIND:
            lines.append(f"open: {lp['title']}")
    for lp in ledger.finished(store, pid, now):
        if lp["kind"] == KIND:
            lines.append(f"turned down or done: {lp['title']}")
    return "\n".join(lines)


def prompt_for(store, pid: str, now: datetime, chats: str, memory_index: str) -> str:
    """What the check reads. The chats, memory titles, skills and ideas are fenced as data."""
    from odie.loops import review
    ideas = "\n".join(f"{i['title']}: {i.get('why') or ''}" for i in review.skill_ideas(store, pid)[-5:])
    parts = [f"It is {now.strftime('%A %-d %B %Y')}. These are yesterday's chats (Y…), each with the older chats most"
             " like it (O…).",
             f"Chats:\n{wrap_untrusted(chats)}",
             f"What Odie remembers (titles):\n{wrap_untrusted(memory_index or '(nothing)')}",
             f"Skills Odie has:\n{wrap_untrusted(skills_text() or '(none)')}",
             f"Skill ideas from the evening reviews:\n{wrap_untrusted(ideas or '(none)')}",
             f"Already asked:\n{wrap_untrusted(learn_loops_text(store, pid, now) or '(nothing)')}"]
    return "\n\n".join(parts)


def parse(text: str) -> dict | None:
    """The answer in the fixed schema, from the first JSON object in the reply; None when there is none. A part of the
    wrong shape is empty.  '{"skills": [{"title": "x"}], "rules": "no"}' -> skills kept, rules [];  "hm" -> None"""
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
    for name in ("skills", "rules"):
        value = raw.get(name)
        if not isinstance(value, list):
            value = []
        out[name] = [item for item in value if isinstance(item, dict)]
    return out


# --- the rails ---

def one_line(value, most: int) -> str:
    return " ".join(str(value or "").split())[:most]


def seen_ids(item: dict, ids: dict[str, dict]) -> list[str]:
    """The exchange ids an answer names that it was shown, each once, in order. ["Y1", "O9", "y2", "Y1"] with O9 never
    shown -> ["Y1", "Y2"]."""
    out = []
    for raw in item.get("seen") or []:
        name = str(raw).strip().upper()
        if ID.match(name) and name in ids and name not in out:
            out.append(name)
    return out


def is_pattern(seen: list[str], ids: dict[str, dict]) -> bool:
    """Whether what the answer saw is a pattern, not a one-off: one of yesterday's exchanges and one older one from
    another day. ["Y1", "O2"] with O2 on 3 Nov -> True;  ["Y1", "Y2"] -> False (yesterday only);  ["O1", "O2"] -> False
    (nothing from yesterday);  ["Y1", "O1"] with O1 also yesterday's day -> False."""
    yesterday = {ids[i]["day"] for i in seen if i.startswith("Y")}
    older = {ids[i]["day"] for i in seen if i.startswith("O")}
    return bool(yesterday) and bool(older - yesterday)


def asked_lately(store, pid: str, title: str, now: datetime) -> bool:
    """Whether a "Learn this?" like this one is open, or was turned down or done within REMEMBER_DAYS: the same words
    (odie.loops.migrate.says_the_same). "Learn to forward the bill" open -> True for "Learn to forward the bill"."""
    from odie.loops.migrate import says_the_same
    for lp in ledger.open_loops(store, pid):
        if lp["kind"] == KIND and says_the_same(lp["title"], title):
            return True
    for lp in ledger.finished(store, pid, now):
        if lp["kind"] == KIND and says_the_same(lp["title"], title):
            return True
    return False


def own_skill(name: str) -> str:
    """The skill a change names, when it is one of his own (the builder changes only those); else "".
    "travel-itinerary" he has -> "travel-itinerary";  "research" (built in) -> "";  "../x" -> "";  "" -> """""
    from odie.skills import builder
    name = one_line(name, 60)
    if not builder.NAME_RE.match(name):
        return ""
    if not (builder.user_dir() / name).is_dir():
        return ""
    return name


def open_learn_loop(store, pid: str, now: datetime, item: dict, seen: list[str], ids: dict[str, dict]) -> int | None:
    """A "Learn this?" loop from one answer item, within the rails above; its evidence is the chats it rests on.
    Returns its id, or None when a rail said no."""
    title = one_line(item.get("title"), 120)
    lesson = one_line(item.get("lesson"), 400)
    why = one_line(item.get("why"), 200)
    if not title or not lesson or secret_in(f"{title} {lesson}"):
        return None
    if not is_pattern(seen, ids) or asked_lately(store, pid, title, now):
        return None
    skill = own_skill(str(item.get("skill") or ""))
    card = {"lesson": lesson, "skill": skill, "pile": "alerts"}
    refs = [f"chat:{ids[i]['session']}" for i in seen]
    lid = ledger.open_loop(store, pid, now, title, KIND, owner="you", refs=refs, next_step="Teach Odie this",
                           state="ready", card=card, result=why or lesson[:200])
    for i in seen:
        said = ids[i]["text"].split("\n", 1)[0].removeprefix("you: ")
        ledger.add_event(store, lid, now, "chat", f"chat:{ids[i]['session']}", f"{ids[i]['day']}: {said[:160]}")
    return lid


def apply(store, pid: str, now: datetime, answer: dict, ids: dict[str, dict], typed: list[str], memory) -> dict:
    """Writes the answer within the rails (this module's notes): the loops opened and the rules saved."""
    from odie.memory import rules
    opened = []
    for item in answer["skills"]:
        if len(opened) >= MOST_NEW:
            break
        lid = open_learn_loop(store, pid, now, item, seen_ids(item, ids), ids)
        if lid is not None:
            opened.append(lid)
    saved = []
    if memory is not None:
        for item in answer["rules"][:MOST_RULES]:
            notice = rules.save(store, memory, pid, now, str(item.get("title") or ""), str(item.get("rule") or ""),
                                str(item.get("quote") or ""), typed)
            if notice is not None:
                saved.append(notice["title"])
    return {"opened": opened, "rules": saved}


async def run(store, pid: str, now: datetime, think, memory=None, memory_index: str = "") -> dict:
    """This owner's morning check: yesterday's chats, the alike older ones (code), then one call when there was a chat
    yesterday and a call left today, then the rails. think(prompt, instruction) is the call with no tools on the
    owner's brain. Marked as run first: once a day, whatever comes of it."""
    from odie.recall.chats import exchanges
    mark_ran(store, pid, now)
    lines = yesterdays_lines(store, pid, now)
    picked = pick(exchanges(lines))
    if not picked:
        return {"called": False, "opened": [], "rules": []}
    found = await alike(store, pid, picked, now.date().isoformat())
    ids, chats = numbered(picked, found)
    if not budget.spend(store, now):
        return {"called": False, "opened": [], "rules": []}
    try:
        answer = parse(await think(prompt_for(store, pid, now, chats, memory_index), instruction()))
    except Exception:  # noqa: BLE001 (a failed call: nothing learned today)
        log.warning("learning: the model call failed", exc_info=True)
        answer = None
    if answer is None:
        return {"called": True, "opened": [], "rules": []}
    done = apply(store, pid, now, answer, ids, his_typed(lines), memory)
    return {"called": True, **done}


# --- Teach and after ---

def teach_request(loop: dict) -> str:
    """The chat request Teach sends: the lesson, the loop's number for the builder (draft_skill's for_loop) and the
    rule that nothing installs without his Approve."""
    lid = loop["id"]
    lesson = loop["card"].get("lesson") or loop["title"]
    skill = loop["card"].get("skill") or ""
    if skill:
        what = f"Change my {skill} skill: {lesson}"
    else:
        what = f"Learn this as a new skill: {lesson}"
    return (f"{what} (loop #{lid}). Use the skill builder, pass for_loop={lid} to draft_skill, and show me the draft "
            "to approve.")


def taught(store, loop_id: int, name: str) -> bool:
    """His Approve installed a skill drafted for a "Learn this?" loop: the loop is done (his tap) and the skill is
    learned, so it fades when unused. Only an open loop of kind "skill"; anything else -> False, nothing changes."""
    from zoneinfo import ZoneInfo

    from odie import config
    from odie.skills import fade
    loop = ledger.get(store, int(loop_id))
    if loop is None or loop["kind"] != KIND or loop["state"] not in ledger.OPEN:
        return False
    now = datetime.now(ZoneInfo(config.settings.timezone))
    ledger.close(store, loop["id"], now, ledger.CLOSED_BY_USER, f"Learned: the {name} skill is installed")
    if not loop["card"].get("skill"):  # a new skill fades; one of his own he had Odie change stays his
        fade.mark_learned(store, name, now, loop["id"])
    return True


async def fade_unused(store, now: datetime) -> list[dict]:
    """Puts away the learned skills unused too long (odie.skills.fade), then reloads the skills."""
    from odie.skills import builder, fade
    made = fade.fade(store, now, builder.user_dir())
    if made and builder.hooks.get("reload"):
        await builder.hooks["reload"]()
    return made
