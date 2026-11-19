"""The Now list (proactive design §5, §15-16 Q5, §17): five to seven lines of what matters to him now, one list per
owner (everyday Odie, each personality). Stage 2 reads it to set a loop's priority, stage 4 to judge what is worth his
attention.

Written only by his tap, in the app (PUT /api/now, the Accept on Odie's weekly proposal): it lives in the settings
table, never in a memory file, so no model tool (update_memory, the memory review) can ever write it. Odie drafts the
first one from what it remembers and his recent chats, and proposes changes once a week; both wait for his tap."""
from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

from odie.agent.callbacks import wrap_untrusted
from odie.loops import budget, ledger
from odie.loops.secret import secret_in

log = logging.getLogger("odie.loops")
KEY = "now.list"  # per owner (odie.watch.owner.key): {"lines": [...], "at": "2026-11-19T10:00:00+05:30", "by": "you"}
PROPOSAL = "now.proposal"  # per owner: {"id", "lines", "why", "first", "at", "state": open | accepted | edited | declined}
PROPOSED_WEEK = "now.proposed_week"  # per owner: "2026-W47", the week a proposal was last made
SKILL = Path(__file__).parent / "skill" / "NOW.md"  # the prompt: the owner reads and edits it
MOST_LINES = 7
LINE_MOST = 120
REF = "now:"
SUNDAY = 6  # datetime.weekday()
PROPOSE_FROM = 9  # o'clock on Sunday
WORDS_DAYS = 7  # his own messages read, and the loops of the week
WORDS_MOST = 40
WORD_CHARS = 200
LOOPS_MOST = 40


def _key(pid: str, name: str = KEY) -> str:
    from odie.watch.owner import key
    return key(name, pid)


def lines(store, pid: str) -> list[str]:
    """This owner's Now lines, in his order; [] when he has none."""
    saved = store.get_setting(_key(pid)) or {}
    return [str(line) for line in saved.get("lines") or []]


def text(store, pid: str) -> str:
    """The Now list as a model reads it, one "- " line each; "" when there is none.
    ["Ship Odie", "Asha's deck"] -> "- Ship Odie\\n- Asha's deck"."""
    return "\n".join(f"- {line}" for line in lines(store, pid))


def clean(given: list[str]) -> list[str]:
    """His lines as they are kept: each trimmed, blanks left out. More than MOST_LINES, a line over LINE_MOST
    characters, or a line holding a secret raises ValueError with words he can read.
      ["  Ship Odie ", "", "Asha's deck"] -> ["Ship Odie", "Asha's deck"];  eight lines -> ValueError;
      "Pay from account 123456789012 …" -> ValueError ("Not kept: it holds a bank account number.")"""
    kept = [" ".join(str(line).split()) for line in given]
    kept = [line for line in kept if line]
    if len(kept) > MOST_LINES:
        raise ValueError(f"Keep it to {MOST_LINES} lines.")
    for line in kept:
        if len(line) > LINE_MOST:
            raise ValueError(f"Keep each line under {LINE_MOST} characters.")
        why = secret_in(line)
        if why:
            raise ValueError(f"Not kept: it holds {why}.")
    return kept


def save(store, pid: str, given: list[str], now: datetime, by: str = "you") -> list[str]:
    """Saves this owner's Now list as he wrote it (clean decides what is kept). Only his tap calls this."""
    kept = clean(given)
    store.set_setting(_key(pid), {"lines": kept, "at": now.isoformat(timespec="seconds"), "by": by})
    return kept


# --- Odie's drafts and weekly proposals: every change still waits for his tap ---

def instruction() -> str:
    """The prompt's text, after its front matter."""
    return SKILL.read_text().split("---", 2)[-1].strip()


def his_words(store, pid: str, now: datetime) -> list[str]:
    """His own messages of the last WORDS_DAYS in this owner's threads, oldest first: what he typed or dictated (never
    what a button or the terminal sent: odie.workers.tools.not_typed), never from a chat that read a signed-in page."""
    from odie import personalities
    from odie.signin import guard as signin_guard
    from odie.workers.tools import not_typed
    since = (now - timedelta(days=WORDS_DAYS)).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S")  # the log's clock
    rows = store.query("select session_id, args_json, result_summary from audit_log where actor='user' and "
                       "event='message' and ts >= ? order by id desc limit 300", (since,))
    out = []
    for row in rows:
        if not_typed(row["args_json"]) or personalities.of_session(store, row["session_id"]) != pid:
            continue
        if signin_guard.private_of(store, row["session_id"]):
            continue
        text = " ".join((row["result_summary"] or "").split())[:WORD_CHARS]
        if text:
            out.append(text)
        if len(out) >= WORDS_MOST:
            break
    return list(reversed(out))


def week_loops(store, pid: str, now: datetime) -> list[str]:
    """The loops of this owner that were open in the last WORDS_DAYS or closed in them, one line each:
    "Reply to Asha · you · open", "Order: lamp · them · closed: delivered"."""
    since = (now - timedelta(days=WORDS_DAYS)).isoformat(timespec="seconds")
    mine, values = ledger._whose(pid)
    rows = store.query(f"select id from loops where {mine} and (state in ('new','working','ready','waiting') or "
                       f"closed_at >= ?) order by id desc limit {LOOPS_MOST}", (*values, since))
    out = []
    for row in rows:
        loop = ledger.get(store, row["id"])
        state = "open"
        if loop["state"] not in ledger.OPEN:
            state = f"closed: {loop['closed_why'] or ''}"[:80]
        out.append(f"{loop['title']} · {loop['owner']} · {state}")
    return out


def prompt_for(store, pid: str, now: datetime, memory_index: str) -> str:
    """What the draft or the proposal reads: his list, what Odie remembers, his own words (his), the week's loops
    (fenced: their titles may come from mail)."""
    words = "\n".join(f"- {w}" for w in his_words(store, pid, now)) or "(none)"
    loops = "\n".join(f"- {line}" for line in week_loops(store, pid, now)) or "(none)"
    parts = [f"It is {now.strftime('%A %d %B %Y')}.",
             f"His Now list as it is:\n{text(store, pid) or '(empty)'}",
             f"What Odie remembers about him:\n{memory_index or '(nothing)'}",
             f"His own messages this week:\n{words}",
             f"This week's loops:\n{wrap_untrusted(loops)}"]
    return "\n\n".join(parts)


def parse(answer: str) -> tuple[list[str], str] | None:
    """The model's lines and why, from the first JSON object in its reply; None when there is none. Each line is
    kept as clean keeps lines (trimmed, at most LINE_MOST characters); a line holding a secret is left out; at most
    MOST_LINES.
      '{"lines": ["Ship Odie", ""], "why": "new"}' -> (["Ship Odie"], "new");  "no idea" -> None"""
    found = re.search(r"\{.*\}", answer or "", re.S)
    if found is None:
        return None
    try:
        raw = json.loads(found.group(0))
    except ValueError:
        return None
    if not isinstance(raw, dict) or not isinstance(raw.get("lines"), list):
        return None
    kept = []
    for line in raw["lines"]:
        one = " ".join(str(line).split())[:LINE_MOST]
        if one and not secret_in(one):
            kept.append(one)
    return kept[:MOST_LINES], str(raw.get("why") or "").strip()[:200]


async def draft(store, pid: str, now: datetime, think, memory_index: str) -> list[str] | None:
    """Odie's draft of the list, for his tap ("Draft it for me"): nothing is saved; he edits and saves. The call is
    his (he tapped), so it is counted in the day's proactive calls but never refused by them. None when the call
    fails or can't be read."""
    budget.count(store, now)
    try:
        got = parse(await think(prompt_for(store, pid, now, memory_index), instruction()))
    except Exception:  # noqa: BLE001 (a failed call: he writes it himself)
        log.warning("now: the draft call failed", exc_info=True)
        return None
    if got is None:
        return None
    return got[0]


def week_of(now: datetime) -> str:
    """The ISO week a day is in: Sunday 22 Nov 2026 -> "2026-W47"."""
    year, week, _ = now.isocalendar()
    return f"{year}-W{week:02d}"


def proposal_due(store, pid: str, now: datetime) -> bool:
    """Whether this owner's weekly proposal is due: it is Sunday, PROPOSE_FROM o'clock or later, and none was made
    this week. Sunday 09:30, none yet -> True; Sunday 08:00 -> False; Saturday -> False; made at 09:30, asked at
    12:30 -> False; the next Sunday -> True."""
    if now.weekday() != SUNDAY or now.hour < PROPOSE_FROM:
        return False
    return store.get_setting(_key(pid, PROPOSED_WEEK)) != week_of(now)


def mark_proposed(store, pid: str, now: datetime) -> None:
    store.set_setting(_key(pid, PROPOSED_WEEK), week_of(now))


def open_proposal(store, pid: str) -> dict | None:
    """This owner's proposal waiting for his answer, or None."""
    saved = store.get_setting(_key(pid, PROPOSAL)) or {}
    if saved.get("state") != "open":
        return None
    return saved


async def propose(store, pid: str, now: datetime, think, memory_index: str) -> dict | None:
    """The weekly proposal (one call, no tools, spent from the day's proactive budget): a card "Update your Now?"
    (or "Start your Now list?" when he has none) with the proposed lines. One try a week, whatever comes of it.
    Returns the proposal, or None: no budget left, a failed or unreadable call, or nothing would change."""
    mark_proposed(store, pid, now)
    if not budget.spend(store, now):
        return None
    try:
        got = parse(await think(prompt_for(store, pid, now, memory_index), instruction()))
    except Exception:  # noqa: BLE001 (a failed call: next week)
        log.warning("now: the weekly proposal failed", exc_info=True)
        return None
    if got is None:
        return None
    proposed, why = got
    return offer(store, pid, now, proposed, why)


def offer(store, pid: str, now: datetime, proposed: list[str], why: str) -> dict | None:
    """Odie's proposed lines become the proposal card (the weekly one, or the evening review's), waiting for his tap;
    nothing changes his list until then. None when nothing would change. A waiting proposal is replaced."""
    current = lines(store, pid)
    if not proposed or proposed == current:
        return None
    before = store.get_setting(_key(pid, PROPOSAL)) or {}
    proposal = {"id": int(before.get("id") or 0) + 1, "lines": proposed, "why": why, "first": not current,
                "at": now.isoformat(timespec="seconds"), "state": "open"}
    store.set_setting(_key(pid, PROPOSAL), proposal)
    return proposal


def proposal_card(proposal: dict) -> dict:
    """The proposal as a Pulse card, in the shape every card has (odie.watch.needs), with its lines (a new field the
    web shows as a list; brief carries them too, for an app that shows only the brief): [Accept] (now_accept),
    [No] (dismiss, which every app already carries out) and [Edit] in the third place (now_edit: the web opens the
    list with these lines to change before saving; Later makes no sense for it)."""
    title = "Update your Now?"
    if proposal.get("first"):
        title = "Start your Now list?"
    ref = f"{REF}{proposal['id']}"
    return {"ref": ref, "title": title, "why": proposal.get("why") or "", "brief": " · ".join(proposal["lines"]),
            "lines": list(proposal["lines"]), "icon": "spark", "badge": "", "ask": "Talk about my Now list",
            "main": {"label": "Accept", "action": "now_accept", "value": proposal["id"]},
            "other": {"label": "No", "action": "dismiss", "value": ref},
            "later": {"label": "Edit", "action": "now_edit", "value": proposal["id"]},
            "pile": "alerts", "since": proposal["at"], "decide": False, "evidence": []}


def cards(store, pid: str) -> list[dict]:
    """This owner's waiting proposal as a card, or none."""
    proposal = open_proposal(store, pid)
    if proposal is None:
        return []
    return [proposal_card(proposal)]


def _close(store, pid: str, proposal_id: int, state: str) -> dict | None:
    proposal = open_proposal(store, pid)
    if proposal is None or proposal["id"] != int(proposal_id):
        return None
    store.set_setting(_key(pid, PROPOSAL), {**proposal, "state": state})
    return proposal


def accept(store, pid: str, proposal_id: int, now: datetime) -> bool:
    """His Accept: the proposed lines become his Now list, exactly as the card showed them (kept here, never sent by
    the app). False when it isn't this owner's waiting proposal."""
    proposal = _close(store, pid, proposal_id, "accepted")
    if proposal is None:
        return False
    save(store, pid, proposal["lines"], now)
    return True


def edited(store, pid: str, proposal_id: int) -> bool:
    """He changed the proposal and saved his own lines (PUT /api/now): it is answered."""
    return _close(store, pid, proposal_id, "edited") is not None


def decline(store, pid: str, proposal_id: int) -> bool:
    """His No: the list stays as it is."""
    return _close(store, pid, proposal_id, "declined") is not None


def number_of(ref: str) -> int | None:
    """The proposal a card's ref names: "now:2" -> 2; "now:x", "loop:2" -> None."""
    if not ref.startswith(REF):
        return None
    rest = ref[len(REF):]
    if not rest.isdigit():
        return None
    return int(rest)
