"""Quiet rules (proactive design §5, §8, phase 5): what he wants to hear less about, in plain words he can see and
delete on Pulse. Written only by his tap: "Less like this" in a card's menu, or Accept on a rule the evening review
proposed. They live in the settings table, so no model tool can write them.

A rule names a card kind, and the sender's address when the card had one; with neither, the card's title. A card it
matches, and a card of a kind learned from his taps (odie.loops.learn), is a digest line instead of a card: no card,
no push, no hello line; the evening digest lists it with Done. Pull requests and promises (playbook loops) are never
quieted: they carry Odie's finished work.

Stage 2 reads the rules too (fenced), so it can say "nothing" sooner."""
from __future__ import annotations

from datetime import datetime

from odie.loops import learn, ledger
from odie.loops.secret import secret_in

KEY = "quiet.rules"  # per owner (odie.watch.owner.key): {"next": 3, "rules": [{"id", "kind", "sender", "title", "text", "at"}]}
PROPOSALS = "quiet.proposals"  # per owner: {"next": 2, "items": [{"id", "kind", "sender", "why", "at", "state"}]}
REF = "quiet:"
KIND_MOST = 40
WHY_MOST = 200


def _key(pid: str, name: str = KEY) -> str:
    from odie.watch.owner import key
    return key(name, pid)


def _saved(store, pid: str, name: str, field: str) -> dict:
    found = store.get_setting(_key(pid, name)) or {}
    return {"next": int(found.get("next") or 1), field: list(found.get(field) or [])}


def rules(store, pid: str) -> list[dict]:
    """This owner's Quiet rules, oldest first."""
    return _saved(store, pid, KEY, "rules")["rules"]


def sender_of(loop: dict) -> str:
    """The address a loop's card came from, lower case, or "": {"sender": "News@Acme.example"} -> "news@acme.example"."""
    return str(loop["card"].get("sender") or "").strip().lower()


def title_key(title: str) -> str:
    return " ".join((title or "").lower().split())


def rule_text(kind: str, sender: str, title: str) -> str:
    """A rule in his words, written by code: ("newsletter", "news@acme.example", …) -> 'Fewer "newsletter" cards from
    news@acme.example: they go in the evening digest'; ("notice", "", …) -> 'Fewer "notice" cards: …'; ("", "",
    "Weekly quiz") -> 'Fewer cards like "Weekly quiz": …'."""
    if kind:
        text = f'Fewer "{kind}" cards'
        if sender:
            text += f" from {sender}"
    elif sender:
        text = f"Fewer cards from {sender}"
    else:
        text = f'Fewer cards like "{title}"'
    return f"{text}: they go in the evening digest"


def add(store, pid: str, kind: str, sender: str, now: datetime, title: str = "") -> dict:
    """Writes one rule; only his tap calls this (Less like this, Accept on a proposal). Nothing to match on, or
    anything secret-shaped, raises ValueError."""
    kind = learn.kind_of(kind)[:KIND_MOST]
    sender = (sender or "").strip().lower()[:120]
    title = " ".join((title or "").split())[:120]
    if secret_in(" ".join((kind, sender, title))):
        raise ValueError("Not kept: it holds something secret.")
    if kind or sender:
        title = ""  # the title only when there is nothing else to match on
    if not (kind or sender or title):
        raise ValueError("Nothing to match this rule on.")
    kept = _saved(store, pid, KEY, "rules")
    rule = {"id": kept["next"], "kind": kind, "sender": sender, "title": title_key(title),
            "text": rule_text(kind, sender, title), "at": now.isoformat(timespec="seconds")}
    kept["next"] += 1
    kept["rules"].append(rule)
    store.set_setting(_key(pid), kept)
    return rule


def delete(store, pid: str, rule_id: int) -> bool:
    """His delete on Pulse's Quiet list: cards like that come back. False when this owner has no such rule."""
    kept = _saved(store, pid, KEY, "rules")
    left = [r for r in kept["rules"] if r["id"] != int(rule_id)]
    if len(left) == len(kept["rules"]):
        return False
    store.set_setting(_key(pid), {**kept, "rules": left})
    return True


def matches(rule: dict, loop: dict) -> bool:
    """Whether a rule covers a loop: every part the rule names must match (its kind, its sender, else its title).
      {"kind": "newsletter", "sender": "news@acme.example"} and an Acme newsletter -> True; a Globex newsletter ->
      False; an Acme bill -> False;  {"kind": "notice"} and any notice -> True;  {"title": "weekly quiz"} and "Weekly
      Quiz" -> True"""
    if rule.get("kind") and rule["kind"] != learn.kind_of(loop["kind"]):
        return False
    if rule.get("sender") and rule["sender"] != sender_of(loop):
        return False
    if rule.get("title") and rule["title"] != title_key(loop["title"]):
        return False
    return bool(rule.get("kind") or rule.get("sender") or rule.get("title"))


def digest_only(store, loop: dict) -> bool:
    """Whether a loop is a digest line instead of a card: not a playbook loop, and his Quiet rule covers it or its kind
    was learned from his taps. An Acme newsletter after "Less like this" on one -> True; a pull request -> False;
    "Reply to Asha" -> False."""
    if loop["playbook"]:
        return False
    pid = loop["personality"]
    if learn.is_learned(store, pid, loop["kind"]):
        return True
    return any(matches(rule, loop) for rule in rules(store, pid))


def less_like_this(store, loop: dict, now: datetime) -> dict:
    """His "Less like this" on a card: a rule from its kind and sender (else its title), the tap noted. Raises
    ValueError for a playbook loop (never quieted)."""
    if loop["playbook"]:
        raise ValueError("Pull requests and promises can't be quieted.")
    rule = add(store, loop["personality"], loop["kind"], sender_of(loop), now, title=loop["title"])
    ledger.update(store, loop["id"], now, tapped="less")
    ledger.add_event(store, loop["id"], now, "you", "less", f"Less like this: {rule['text']}")
    return rule


def digest_lines(store, pid: str, now: datetime) -> list[dict]:
    """This owner's ready loops that are digest lines, not cards (not put off with Later), newest first."""
    from odie.loops import cards
    ready = [lp for lp in ledger.open_loops(store, pid) if lp["state"] == "ready" and not cards.hidden(lp, now)]
    out = [lp for lp in ready if digest_only(store, lp)]
    out.sort(key=lambda lp: lp["id"], reverse=True)
    return out


# --- the evening review's proposals: a card each, the rule only on his tap ---

def _proposals(store, pid: str) -> dict:
    return _saved(store, pid, PROPOSALS, "items")


def propose(store, pid: str, now: datetime, kind: str, sender: str, why: str) -> dict | None:
    """A rule the evening review proposes, waiting for his tap as a card. None when there is nothing to match on, it
    holds a secret, a rule like it exists, or he already answered (or has open) one like it."""
    kind = learn.kind_of(kind)[:KIND_MOST]
    sender = (sender or "").strip().lower()[:120]
    why = " ".join(str(why or "").split())[:WHY_MOST]
    if not kind or secret_in(" ".join((kind, sender, why))):
        return None
    for rule in rules(store, pid):
        if rule["kind"] == kind and rule["sender"] == sender:
            return None
    kept = _proposals(store, pid)
    for item in kept["items"]:
        if item["kind"] == kind and item["sender"] == sender:
            return None  # waiting already, or he said no to it
    item = {"id": kept["next"], "kind": kind, "sender": sender, "why": why, "at": now.isoformat(timespec="seconds"),
            "state": "open"}
    kept["next"] += 1
    kept["items"] = [*kept["items"], item][-50:]
    store.set_setting(_key(pid, PROPOSALS), kept)
    return item


def proposal_card(item: dict) -> dict:
    """A proposed rule as a card in the shape every card has (odie.watch.needs): [Add the rule] (quiet_accept) and
    [No] (dismiss, which every app already carries out)."""
    ref = f"{REF}{item['id']}"
    text = rule_text(item["kind"], item["sender"], "")
    return {"ref": ref, "title": "Quiet these?", "why": text, "brief": item["why"], "icon": "spark", "badge": "",
            "ask": f"Why do you suggest: {text}?",
            "main": {"label": "Add the rule", "action": "quiet_accept", "value": item["id"]},
            "other": {"label": "No", "action": "dismiss", "value": ref},
            "pile": "alerts", "since": item["at"], "decide": False, "evidence": []}


def proposal_cards(store, pid: str) -> list[dict]:
    return [proposal_card(i) for i in _proposals(store, pid)["items"] if i["state"] == "open"]


def _answer(store, pid: str, proposal_id: int, state: str) -> dict | None:
    kept = _proposals(store, pid)
    for item in kept["items"]:
        if item["id"] == int(proposal_id) and item["state"] == "open":
            item["state"] = state
            store.set_setting(_key(pid, PROPOSALS), kept)
            return item
    return None


def accept(store, pid: str, proposal_id: int, now: datetime) -> dict | None:
    """His Add the rule: the rule as the card showed it (kept here, never sent by the app). None when it isn't this
    owner's waiting proposal."""
    item = _answer(store, pid, proposal_id, "accepted")
    if item is None:
        return None
    return add(store, pid, item["kind"], item["sender"], now)


def decline(store, pid: str, proposal_id: int) -> bool:
    """His No: no rule, and the same one isn't proposed again."""
    return _answer(store, pid, proposal_id, "declined") is not None


def number_of(ref: str) -> int | None:
    """The proposal a card's ref names: "quiet:2" -> 2; "quiet:x", "loop:2" -> None."""
    if not ref.startswith(REF) or not ref[len(REF):].isdigit():
        return None
    return int(ref[len(REF):])


def text_for_model(store, pid: str) -> str:
    """The rules as stage 2 and the evening review read them (fenced there): "- Fewer "newsletter" cards …"."""
    return "\n".join(f"- {r['text']}" for r in rules(store, pid))
