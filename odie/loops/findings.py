"""Stage 1's findings (proactive design §4): the check's small notes on what it read — what it's about, who, what is
asked, by when, any reference it noticed. A finding never shows on Pulse; stage 2 (odie.loops.consolidate) places
each one in the ledger: the same as a loop, new, closing one, or nothing.

The check writes them two ways, both kept from before so the model's habits still fit: `report(findings=[…])` (once
`needs_you`, still accepted) and `track_thread` (an order, a bill, a reply owed or a deadline to follow). Code reads
them here into one shape, checks what they claim (a mail must be one this check knows; a GitHub name must check out)
and adds the IDs the mail itself carries (its thread, the pull request GitHub's mail names), which the same-ID
shortcut matches on. Two findings about the same mail are one."""
from __future__ import annotations

import re
from zoneinfo import ZoneInfo

from odie.loops import github, shortcut
from odie.watch import report as rep
from odie.watch.fetch import address_of

OWNERS = ("you", "them", "odie")
# What a thread's kind (track_thread) means as a loop: its kind in words and whose move it is.
THREAD_KINDS = {"order": ("order", "them"), "bill": ("bill", "you"), "reply": ("reply owed", "you"),
                "deadline": ("deadline", "you")}
CLOSING = ("done", "dropped")
# Refs the model may name besides GitHub's: a mail, an event, a thread, a note, an order or invoice number.
NAMED_REF = re.compile(r"^(mail|event|thread|note|order|invoice):\S{1,120}$")
TITLE_MOST = 120
DONE_MOST = 200


def owner_of(value, default: str = "you") -> str:
    """Whose move a finding is: you, them or odie as written (any case); anything else -> the default ("you": a card
    beats a silent miss). "Them" -> "them"; "the user" -> "you"; None -> "you"."""
    text = str(value or "").strip().lower()
    if text in OWNERS:
        return text
    return default


def when_of(value) -> str | None:
    """A due date or a reminder time as the ledger keeps it: "2026-11-21" -> 09:00 that day in the user's time zone,
    "2026-11-21T15:00" -> that time; "Friday" or nothing -> None."""
    from odie import config
    from odie.agent.tools.local import parse_when
    text = str(value or "").strip()
    if not text:
        return None
    return parse_when(text, ZoneInfo(config.settings.timezone))


def same_words(title: str) -> str:
    """A title as code compares it: lower case, letters and digits only. "Vote: Northwind — closes 21 Nov" and
    "Vote: Northwind – closes 21 Nov" -> the same; "Pay rent" and "Pay the rent" -> not."""
    return re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()


REFS_MOST = 5  # refs a finding may carry: a mail names a thing, not a list of things


def read_by_this_check(check) -> set[str]:
    """The IDs this check itself read, which a finding may name as strong refs: its mails (new, searched, its own
    thread's, what the user sent), their threads, and the events it read. Code knows these; the model can't add one."""
    out = set()
    for mail in check.sent:
        out.add(f"mail:{mail.id}")
        if mail.thread:
            out.add(f"thread:{mail.thread}")
    for e in [*check.events, *check.ahead]:
        out.add(f"event:{e.id}")
    return out


def named_refs(values, check, mail_from_github: bool) -> list[str]:
    """The refs a finding names that code keeps: a mail, a thread or an event only when this check read it; a note,
    order or invoice name as it is (never a strong ID). Never a task, and never a GitHub name the model wrote: code
    reads a pull request's name from GitHub's own mail itself (shortcut.refs_of).
      ["mail:m1"] (read this check) -> kept;  ["mail:bill77"] (never read) -> dropped;  ["task:12"] -> dropped;
      ["example/app#46"] (even in GitHub's mail) -> dropped;  ["order:A-1"] -> kept"""
    out = []
    read = read_by_this_check(check)
    for value in values or []:
        text = str(value).strip()
        if github.parse(text) is not None:
            continue  # a pull request's name only as code reads it from GitHub's own mail (shortcut.refs_of)
        if not NAMED_REF.match(text):
            continue
        kind = text.split(":", 1)[0]
        if kind == "mail" and check.fetcher.read_mail(text[len("mail:"):]) is not None:
            out.append(text)
        elif kind in ("mail", "thread", "event"):
            if text in read or (kind == "thread" and thread_read(check, text[len("thread:"):])):
                out.append(text)
        else:
            out.append(text)
    return out


def thread_read(check, thread: str) -> bool:
    """Whether a mail this check read is in this thread (its new mail, by the fetcher's own list)."""
    mails = getattr(check, "mails", None) or []
    return any(m.thread == thread for m in mails)


def from_thread(ref: str, kind: str, title: str, stage: str, due: str, why: str) -> dict:
    """A track_thread call as a finding: ("mail:o1", "order", "Order: desk lamp", "shipped", "2026-11-22", "") ->
    an order, owner them, due 22 Nov, stage shipped; stage "done" with why "delivered 23 Oct" -> a finding that
    says it's done."""
    words, owner = THREAD_KINDS.get(kind, (kind, "you"))
    item = {"ref": ref, "title": title, "kind": words, "owner": owner, "due": due, "stage": stage, "from_thread": True}
    if (stage or "").strip().lower() in CLOSING:
        item["done"] = why or stage
    return item


def mail_fields(mail, statuses: dict) -> dict:
    """What a card shows about the mail behind a loop (report._mail_fields, kept on the loop): sender, subject, time,
    gist, badges, the app holding it; and its thread and sender's address, so his reply to that sender closes it."""
    fields = rep._mail_fields(f"mail:{mail.id}", [mail], statuses)
    if mail.thread:
        fields["thread"] = mail.thread
        fields["sender"] = address_of(mail.frm).lower()
    return fields


def read_new(check, mail) -> bool:
    """Whether code read this mail for this check, so a finding about it has strong IDs: its new mail, the bills
    catch-up, or the user's own sent mail. A mail search_mail or sent_to found is readable context, but a finding
    about it is weak: evidence text only (it can't join a loop by its ID, nor close one).
      a new bill mail -> True;  a catch-up bill from last month -> True;  last year's mail a search found -> False"""
    if mail.id in {m.id for m in check.sent}:
        return True
    if mail.id in {m.id for m in (getattr(check, "mails", None) or [])}:
        return True
    read_by_check = getattr(check.fetcher, "read_by_check", None)
    return read_by_check is not None and read_by_check(mail.id)


def own_ref_ok(ref: str, check) -> bool:
    """Whether a finding's own ref (what it is about) may stand: a mail or an event this check read, a note ("note:…",
    kept as text: never a strong ID, whatever note it names), or none at all. A task, a thread, a mail or an event it
    didn't read, or anything else, can't: such a finding is refused.
      "mail:m1" (read) -> True;  "task:12" -> False;  "thread:tAsha" -> False;  "event:e9" (not read) -> False;
      "note:Inbox/digest.md" -> True;  "" -> True"""
    if not ref:
        return True
    kind = ref.split(":", 1)[0]
    if kind == "mail":
        mail_id = ref[len("mail:"):]
        return check.fetcher.read_mail(mail_id) is not None or any(m.id == mail_id for m in check.sent)
    if kind == "event":
        return ref in read_by_this_check(check)
    return kind == "note"


def one(item: dict, check) -> dict | None:
    """One finding as the model wrote it, read into the ledger's shape; None when it names a mail this check doesn't
    know (made up, or misread). See this module's notes."""
    ref = str(item.get("ref") or "").strip()
    if not own_ref_ok(ref, check):
        return None
    mail = None
    if ref.startswith("mail:"):
        mail = check.fetcher.read_mail(ref[len("mail:"):])
        if mail is None:
            mail = next((m for m in check.sent if f"mail:{m.id}" == ref), None)
    title = str(item.get("title") or "").strip()[:TITLE_MOST]
    if not title and mail is not None:
        title = mail.subject[:TITLE_MOST]
    if not title:
        return None
    labels = rep.labelled({**item, "ref": ref})
    card: dict = {}
    for name in ("pile", "amount", "draft"):
        if name in labels:
            card[name] = labels[name]
    if "suggestion" in labels:
        card["suggestion"] = labels["suggestion"]["label"]
    if "due" in labels:
        card["due"] = labels["due"]  # as the model gave it, for the card's day ("24 Oct")
    refs = [ref] if ref else []
    event = None
    if ref.startswith("event:"):
        event = next((e for e in [*check.events, *check.ahead] if f"event:{e.id}" == ref), None)
        if event is None:
            return None  # an event this check didn't read
    if event is not None:
        card["badges"] = rep.badges_of(event.sources or [event.source], check.fetcher.statuses)
        card["when"] = event.start
        if not item.get("due"):
            item = {**item, "due": event.start}  # the calendar's own time: an event is due when it starts
    github_mail = mail is not None and shortcut.from_github(mail)
    if mail is not None:
        card.update(mail_fields(mail, check.fetcher.statuses))
        refs += shortcut.refs_of(mail)  # its thread, and the pull request GitHub's own mail names: code's
    named = item.get("refs") if isinstance(item.get("refs"), list) else [item.get("refs")]
    refs += named_refs(named, check, github_mail)
    refs = list(dict.fromkeys(refs))[:REFS_MOST]
    weak = mail is not None and not read_new(check, mail)
    return {"ref": ref, "title": title, "from_github": github_mail, "from_thread": bool(item.get("from_thread")),
            "weak": weak, "kind": str(item.get("kind") or "").strip()[:40],
            "why": str(item.get("why") or "").strip()[:rep.WHY_MAX], "owner": owner_of(item.get("owner")),
            "due": when_of(item.get("due")), "remind_at": when_of(item.get("remind_at")),
            "done": str(item.get("done") or "").strip()[:DONE_MOST], "stage": str(item.get("stage") or "").strip()[:40],
            "push": bool(item.get("push")), "refs": refs, "card": card}


def merged(first: dict, second: dict) -> dict:
    """Two findings about the same thing as one: the later one's words win where it has them, refs and card fields
    from both. A track_thread "order shipped, due 22 Nov" and a report item "Order: lamp" for the same mail -> one."""
    out = dict(first)
    for name in ("title", "kind", "why", "due", "remind_at", "done", "stage"):
        if second.get(name):
            out[name] = second[name]
    out["push"] = first["push"] or second["push"]
    out["refs"] = list(dict.fromkeys([*first["refs"], *second["refs"]]))[:REFS_MOST]
    out["card"] = {**first["card"], **second["card"]}
    out["from_thread"] = first["from_thread"] and second["from_thread"]
    if second.get("owner") and second["owner"] != "you":
        out["owner"] = second["owner"]
    return out


def one_thing(first: dict, second: dict) -> bool:
    """Whether two findings about the same mail or event are one thing: only when their titles are the same written
    the same way. Anything else stays two (joining a same-thing duplicate worded differently is stage 2's job).
      "School PTM Saturday" and "Pay school term fee" -> False
      track_thread's "Pay Amex card" and the report's "Pay Visa card", one statement mail -> False
      track_thread's "Order: desk lamp" and the report's "Order: desk lamp" -> True"""
    return same_words(first["title"]) == same_words(second["title"])


def collect(check) -> list[dict]:
    """Every finding of this check, read and numbered F1, F2…: track_thread's first, then the report's; two about the
    same mail (or event) are merged only when they are one thing (one_thing)."""
    raw = [*check.threads_found]
    if check.report is not None:
        raw += check.report.get("findings", [])
    out: list[dict] = []
    for item in raw:
        found = one(item, check)
        if found is None:
            continue
        twin = next((f for f in out if found["ref"] and f["ref"] == found["ref"] and one_thing(f, found)), None)
        if twin is not None:
            out[out.index(twin)] = merged(twin, found)
            continue
        out.append(found)
    for n, found in enumerate(out, start=1):
        found["id"] = f"F{n}"
    return out


def line(found: dict, hint: str = "") -> str:
    """One finding as stage 2 reads it (inside a fence: it carries mail words):
    "F1 · mail:m1 · reply owed · Send the deck by Friday · Asha asks for it by Friday · due 2026-11-21 · owner you ·
    refs thread:t1 (loop #3 holds thread:t1)" """
    bits = [found["id"]]
    if found["ref"]:
        bits.append(found["ref"])
    if found["kind"]:
        bits.append(found["kind"])
    bits.append(found["title"])
    if found["why"]:
        bits.append(found["why"])
    who = found["card"].get("from")
    if who:
        bits.append(f"from {who}")
    if found["due"]:
        bits.append(f"due {found['due'][:16]}")
    if found["remind_at"]:
        bits.append(f"remind {found['remind_at'][:16]}")
    if found["stage"]:
        bits.append(f"stage {found['stage']}")
    if found["done"]:
        bits.append(f"done: {found['done']}")
    bits.append(f"owner {found['owner']}")
    others = [r for r in found["refs"] if r != found["ref"]]
    if others:
        bits.append("refs " + ", ".join(others[:4]))
    text = " · ".join(bits)
    if hint:
        text += f" ({hint})"
    return text
