"""Learning from his taps (proactive design §8, phase 5). Every tap on a loop's card is logged (loop_taps, written by
odie.loops.ledger.update whenever it records a tap). Once a day, at the evening review, code counts them per card
kind: a kind he acts on less than 1 time in 5, over at least 5 cards, becomes a digest line instead of a card, and
Odie says so once ("I'll put X in the evening digest instead of cards: you rarely act on them." [Undo] [OK]). No
model takes part: the count is code's, so a mail can't talk Odie into hiding or showing anything.

What a card's outcome is:
  acted    he used it: its move (the app posts it; chat's watch_item notes "ask"), Merge, Done (on Pulse or in chat)
  ignored  he never acted on it: still his card (ready, owner you) with only Later, shown IGNORED_AFTER or longer;
           or it ended unused (the ladder's day-14 drop, Sunday's "Drop them", Less like this)
  neutral  too early to say; it moved on without a tap (stage 2 saw his reply: now waiting on them); or Odie closed it
           by evidence or the evening review dropped it: not counted
Pull requests and promises (playbook loops) are never learned: they carry Odie's finished work.

The day's taps are context for stages 2 and 4 (today_text), fenced there as data: their titles may come from mail."""
from __future__ import annotations

from datetime import datetime, time, timedelta

from odie.loops import ledger

ACTED = ("move", "ask", "merge", "done", "done in chat")
ENDED_UNUSED = ("less", "drop")
LEARN_DAYS = 30  # the cards counted: shown in the last 30 days
IGNORED_AFTER = timedelta(days=3)
FEWEST = 5  # cards of a kind before Odie judges it
ONE_IN = 5
KEY = "loops.learned"  # per owner (odie.watch.owner.key): {"next": 2, "kinds": [{"id", "kind", "acted", "of", "at", "state", "said"}]}
REF = "learn:"
WORDS = {"move": "Opened", "ask": "Asked about", "merge": "Merged", "done": "Done", "done in chat": "Done in chat",
         "later": "Later", "less": "Less like this", "drop": "Dropped", "split": "Split", "reopen": "Reopened"}
TODAY_MOST = 20


def kind_of(kind: str) -> str:
    """A card kind as it is counted: lower case, one space. " Reply  Owed" -> "reply owed"; "" -> ""."""
    return " ".join((kind or "").lower().split())


def _key(pid: str) -> str:
    from odie.watch.owner import key
    return key(KEY, pid)


def log_tap(store, loop: dict, now: datetime, tap: str) -> None:
    """Keeps one tap on a loop's card, with the loop's kind and owner (the loop may be forgotten later; the count is
    per kind)."""
    store.execute("insert into loop_taps(loop_id, personality, kind, tap, at) values (?,?,?,?,?)",
                  (int(loop["id"]), loop["personality"] or None, kind_of(loop["kind"]), tap,
                   now.isoformat(timespec="seconds")))


def taps_of(store, loop_id: int) -> list[str]:
    return [r["tap"] for r in store.query("select tap from loop_taps where loop_id=? order by id", (int(loop_id),))]


def outcome(store, loop: dict, now: datetime) -> str | None:
    """What came of one card (this module's notes): "acted", "ignored" or None (not counted).
      his Done or his move -> "acted";  shown 5 days ago, only Later since -> "ignored";  shown yesterday -> None;
      closed by Odie's evidence ("paid 18 Nov") before he did anything -> None;  dropped by the ladder -> "ignored";
      dropped as stale by the evening review -> None;  he replied in Mail, so it waits on them now -> None"""
    from odie.loops import ladder
    taps = taps_of(store, loop["id"])
    if any(t in ACTED for t in taps):
        return "acted"
    if any(t in ENDED_UNUSED for t in taps):
        return "ignored"
    if loop["state"] == "dropped" and loop.get("closed_by") == "odie" and loop.get("closed_why") == ladder.DROP_WHY:
        return "ignored"  # the ladder's day-14 drop: shown two weeks, never used
    if loop["state"] not in ledger.OPEN:
        return None  # Odie closed it by evidence (he dealt with the thing itself), or the review dropped it
    if loop["state"] != "ready" or loop["owner"] != "you":
        return None  # no longer his card: it moved on without a tap (his reply seen in Mail, say)
    shown = loop.get("shown_at")
    if not shown or now - datetime.fromisoformat(shown) < IGNORED_AFTER:
        return None
    return "ignored"


def rarely_acted(acted: int, of: int) -> bool:
    """Whether a kind goes to the digest: at least FEWEST cards counted and fewer than 1 in ONE_IN acted on.
    0 of 5 -> True; 1 of 6 -> True; 1 of 5 -> False (exactly one in five); 0 of 4 -> False (too few to say)."""
    if of < FEWEST:
        return False
    return acted * ONE_IN < of


def tally(store, pid: str, now: datetime) -> dict[str, dict]:
    """Per kind, this owner's cards shown in the last LEARN_DAYS that have an outcome: {"newsletter": {"acted": 0,
    "of": 6}}. Playbook loops are left out."""
    since = (now - timedelta(days=LEARN_DAYS)).isoformat(timespec="seconds")
    mine, values = ledger._whose(pid)
    rows = store.query(f"select id from loops where shown_at is not null and shown_at >= ? and playbook = '' and {mine}",
                       (since, *values))
    out: dict[str, dict] = {}
    for row in rows:
        loop = ledger.get(store, row["id"])
        kind = kind_of(loop["kind"])
        got = outcome(store, loop, now)
        if not kind or got is None:
            continue
        counts = out.setdefault(kind, {"acted": 0, "of": 0})
        counts["of"] += 1
        if got == "acted":
            counts["acted"] += 1
    return out


def saved(store, pid: str) -> dict:
    found = store.get_setting(_key(pid)) or {}
    return {"next": int(found.get("next") or 1), "kinds": list(found.get("kinds") or [])}


def is_learned(store, pid: str, kind: str) -> bool:
    """Whether cards of this kind go to the digest because he rarely acts on them (learned and not undone)."""
    wanted = kind_of(kind)
    return any(k["kind"] == wanted and k["state"] == "on" for k in saved(store, pid)["kinds"])


def learn(store, pid: str, now: datetime) -> list[dict]:
    """Once a day (the evening part): the kinds that newly became digest lines, each with its notice waiting. A kind
    already learned, or one he undid, is never learned again."""
    kept = saved(store, pid)
    known = {k["kind"] for k in kept["kinds"]}
    new = []
    for kind, counts in sorted(tally(store, pid, now).items()):
        if kind in known or not rarely_acted(counts["acted"], counts["of"]):
            continue
        entry = {"id": kept["next"], "kind": kind, "acted": counts["acted"], "of": counts["of"],
                 "at": now.isoformat(timespec="seconds"), "state": "on", "said": False}
        kept["next"] += 1
        kept["kinds"].append(entry)
        new.append(entry)
    if new:
        store.set_setting(_key(pid), kept)
    return new


def notice_card(entry: dict) -> dict:
    """The notice, said once: in the shape of every card (odie.watch.needs), two buttons only: Undo (learn_undo: the
    kind's cards come back, for good) and OK (dismiss, which every app already carries out)."""
    ref = f"{REF}{entry['id']}"
    kind = entry["kind"]
    why = (f"I'll put {kind} in the evening digest instead of cards: you rarely act on them "
           f"({entry['acted']} of the last {entry['of']}).")
    return {"ref": ref, "title": f"Fewer cards for {kind}", "why": why, "brief": "", "icon": "spark", "badge": "",
            "ask": f"Why do {kind} cards go to the digest now?",
            "main": {"label": "Undo", "action": "learn_undo", "value": entry["id"]},
            "other": {"label": "OK", "action": "dismiss", "value": ref},
            "pile": "alerts", "since": entry["at"], "decide": False, "evidence": []}


def notice_cards(store, pid: str) -> list[dict]:
    return [notice_card(k) for k in saved(store, pid)["kinds"] if k["state"] == "on" and not k["said"]]


def _change(store, pid: str, entry_id: int, **fields) -> bool:
    kept = saved(store, pid)
    for entry in kept["kinds"]:
        if entry["id"] == int(entry_id):
            entry.update(fields)
            store.set_setting(_key(pid), kept)
            return True
    return False


def said(store, pid: str, entry_id: int) -> bool:
    """His OK on the notice: it is said; the kind stays in the digest."""
    return _change(store, pid, entry_id, said=True)


def undo(store, pid: str, entry_id: int) -> bool:
    """His Undo (on the notice, or in Pulse's Quiet list): the kind's cards come back and it is never learned again.
    False when this owner has no such entry."""
    return _change(store, pid, entry_id, state="undone", said=True)


def learned_list(store, pid: str) -> list[dict]:
    """The kinds in the digest by learning, for Pulse's Quiet section (each with Undo)."""
    return [{"id": k["id"], "kind": k["kind"], "acted": k["acted"], "of": k["of"], "at": k["at"]}
            for k in saved(store, pid)["kinds"] if k["state"] == "on"]


def number_of(ref: str) -> int | None:
    """The notice a card's ref names: "learn:2" -> 2; "learn:x", "loop:2" -> None."""
    if not ref.startswith(REF) or not ref[len(REF):].isdigit():
        return None
    return int(ref[len(REF):])


def today_text(store, pid: str, now: datetime) -> str:
    """His taps on this owner's cards today, oldest first, one line each, for stages 2 and 4 (fenced there):
    "- 10:02 Done: Reply to Asha (reply)". "" when none."""
    start = datetime.combine(now.date(), time(0, 0), now.tzinfo)
    whose, values = "t.personality is null", ()
    if pid:
        whose, values = "t.personality = ?", (pid,)
    rows = store.query(f"select t.tap, t.at, t.kind, l.title from loop_taps t join loops l on l.id = t.loop_id "
                       f"where t.at >= ? and {whose} order by t.id",
                       ((start - timedelta(days=1)).isoformat(timespec="seconds"), *values))  # a day early: offsets differ
    lines = []
    for row in rows:
        at = datetime.fromisoformat(row["at"])
        if at < start:
            continue
        word = WORDS.get(row["tap"], row["tap"])
        lines.append(f"- {at.astimezone(now.tzinfo).strftime('%H:%M')} {word}: {row['title']} ({row['kind'] or '?'})")
    return "\n".join(lines[-TODAY_MOST:])
