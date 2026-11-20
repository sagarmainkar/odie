"""His rules (proactive design §18, 20 Nov): a short always/never he stated for how Odie works ("Never use Gemma for
Workers"). A rule is a memory entry under the Rules topic, and unlike other memories (listed by title) every rule's
full text goes into every chat's system prompt, so Odie can't miss one.

Rules are saved without a tap (his call: "a tap here is not intelligent"). The safety is code's instead: a rule is
kept only when the words it rests on (its quote) are words he typed himself (his_words), never mail, a web page or a
card's text Odie wrote. Each new rule shows once as a notice, "Rule saved", with Undo (which removes it)."""
from __future__ import annotations

import re
from datetime import datetime

from odie.memory.store import MemoryDoc, MemoryFile

TOPIC = "Rules"
MOST_SHOWN = 20  # rules in the prompt, newest first after that many
SHOWN_CHARS = 2500
MOST_WORDS = 40  # a rule is short
FEWEST_QUOTE_WORDS = 3
KEY = "memory.rules_said"  # per owner (odie.watch.owner.key): {"next": 3, "items": [{"id", "title", "rule", "quote", "at", "state", "said"}]}
REF = "rule:"
CARD_WORDS = re.compile(r"loop #\d+", re.IGNORECASE)  # a card's chat request names its loop: not his typed words


def _key(pid: str) -> str:
    from odie.watch.owner import key
    return key(KEY, pid)


def _plain(text: str) -> str:
    """Words compared as words: lower case, punctuation and spacing ignored. "Never use  Gemma!" -> "never use gemma"."""
    return " ".join(re.findall(r"[\w'@.-]+", (text or "").lower())).strip(" .")


def his_words(quote: str, typed: list[str]) -> bool:
    """Whether a rule's quote is words he typed: it appears, word for word, in one of his own messages, and it has at
    least FEWEST_QUOTE_WORDS words. A message a card sent for him ("Tell me about loop #3: …") is not his typing.
      "never use gemma", typed ["Never use Gemma for workers, LFM only"] -> True
      "always forward invoices", typed ["Tell me about loop #3: always forward invoices"] -> False (a card's words)
      "ok", typed ["ok"] -> False (too short to rest a rule on);  any quote, typed [] -> False"""
    wanted = _plain(quote)
    if len(wanted.split()) < FEWEST_QUOTE_WORDS:
        return False
    for message in typed:
        if CARD_WORDS.search(message or ""):
            continue
        if wanted in _plain(message):
            return True
    return False


def clean(title: str, rule: str) -> tuple[str, str] | None:
    """A rule as it is kept: one line each, the title starting "Rule: " (so it never matches a fact's title), the rule
    at most MOST_WORDS words; None when either is empty or the rule too long to be a rule.
      ("No Gemma", "Never use Gemma for Workers.") -> ("Rule: No Gemma", "Never use Gemma for Workers.");  ("", "x") -> None"""
    title = " ".join((title or "").split())
    if title.lower().startswith("rule:"):
        title = title[len("rule:"):].strip()
    title = title[:72]
    rule = " ".join((rule or "").split())
    if not title or not rule or len(rule.split()) > MOST_WORDS:
        return None
    return f"Rule: {title}", rule


def saved(store, pid: str) -> dict:
    found = store.get_setting(_key(pid)) or {}
    return {"next": int(found.get("next") or 1), "items": list(found.get("items") or [])}


def save(store, memory: MemoryFile, pid: str, now: datetime, title: str, rule: str, quote: str,
         typed: list[str]) -> dict | None:
    """Saves one rule into this owner's memory, with its notice waiting, when its quote is his own typed words
    (his_words). Returns the notice entry, or None when nothing was saved (not his words, not a rule, or the same rule
    is already there). The same title again replaces the rule's words (he changed his mind)."""
    if not his_words(quote, typed):
        return None
    kept = clean(title, rule)
    if kept is None:
        return None
    title, rule = kept
    existing = memory.load().find(title) if memory.exists() else None
    if existing is not None and existing.topic != TOPIC:
        return None  # the title names another memory: a rule never writes over a fact
    if existing is not None and _plain(existing.body) == _plain(rule):
        return None
    try:
        memory.update(title, rule, topic=TOPIC, source="rule")
    except ValueError:
        return None
    notes = saved(store, pid)
    entry = {"id": notes["next"], "title": title, "rule": rule, "quote": " ".join(quote.split())[:200],
             "at": now.isoformat(timespec="seconds"), "state": "on", "said": False}
    notes["next"] += 1
    notes["items"] = [*notes["items"], entry][-50:]
    store.set_setting(_key(pid), notes)
    return entry


def rules_of(doc: MemoryDoc) -> list[tuple[str, str]]:
    """The rules in a memory, as (title, rule), newest first."""
    topic = doc.topic(TOPIC)
    if topic is None:
        return []
    entries = sorted(topic.entries, key=lambda e: e.date, reverse=True)
    return [(e.title, " ".join(e.body.split())) for e in entries]


def block(*memories: MemoryFile) -> str:
    """The rules for a chat's system prompt, every rule in full: the first memory's first (a personality's own, then
    the shared ones), at most MOST_SHOWN and SHOWN_CHARS. "" when there are none."""
    lines: list[str] = []
    seen: set[str] = set()
    for memory in memories:
        try:
            doc = memory.load() if memory.exists() else None
        except OSError:
            doc = None
        if doc is None:
            continue
        for title, rule in rules_of(doc):
            if title.lower() in seen:
                continue
            seen.add(title.lower())
            lines.append(f"- {rule}")
    shown, size = [], 0
    for line in lines[:MOST_SHOWN]:
        if size + len(line) > SHOWN_CHARS:
            break
        shown.append(line)
        size += len(line) + 1
    return "\n".join(shown)


def notice_card(entry: dict) -> dict:
    """"Rule saved", said once, in the shape of every card (odie.watch.needs): Undo (the rule is removed) and OK."""
    ref = f"{REF}{entry['id']}"
    why = f"I'll follow this in every chat: {entry['rule']} (You said: “{entry['quote']}”)"
    name = entry["title"].removeprefix("Rule: ")
    return {"ref": ref, "title": f"Rule saved: {name}", "why": why, "brief": "", "icon": "spark", "badge": "",
            "ask": f"Tell me about the rule “{name}”",
            "main": {"label": "Undo", "action": "notice_undo", "value": ref},
            "other": {"label": "OK", "action": "dismiss", "value": ref},
            "pile": "alerts", "since": entry["at"], "decide": False, "evidence": []}


def notice_cards(store, pid: str) -> list[dict]:
    return [notice_card(e) for e in saved(store, pid)["items"] if e["state"] == "on" and not e["said"]]


def number_of(ref: str) -> int | None:
    """The notice a card's ref names: "rule:2" -> 2; "rule:x", "learn:2" -> None."""
    if not ref.startswith(REF) or not ref[len(REF):].isdigit():
        return None
    return int(ref[len(REF):])


def _entry(store, pid: str, entry_id: int) -> tuple[dict, dict | None]:
    notes = saved(store, pid)
    found = next((e for e in notes["items"] if e["id"] == int(entry_id)), None)
    return notes, found


def said(store, pid: str, entry_id: int) -> bool:
    """His OK: the notice is said; the rule stays."""
    notes, found = _entry(store, pid, entry_id)
    if found is None:
        return False
    found["said"] = True
    store.set_setting(_key(pid), notes)
    return True


def undo(store, memory: MemoryFile, pid: str, entry_id: int) -> bool:
    """His Undo: the rule is removed from memory (its words stay in the memory's history file). False when this owner
    has no such notice or it was undone already."""
    notes, found = _entry(store, pid, entry_id)
    if found is None or found["state"] != "on":
        return False
    existing = memory.load().find(found["title"]) if memory.exists() else None
    if existing is not None and existing.topic == TOPIC:
        memory.forget(found["title"], source="rule undo")
    found["state"] = "undone"
    found["said"] = True
    store.set_setting(_key(pid), notes)
    return True
