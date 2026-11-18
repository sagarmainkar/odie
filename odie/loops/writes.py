"""What the watch's turn writes to the ledger (stages 1 and 2 share that turn in phase 1): the model names the thing,
code checks what it named and keeps the rows honest. A GitHub name must check out (odie.loops.github.parse), a mail
must be one this check knows, a loop must be this owner's and open, and a close must say why. A name an open loop
already holds adds to that loop instead of opening a second one (the same-ID shortcut)."""
from __future__ import annotations

from odie.loops import github, ledger, playbooks, shortcut


def checked_refs(refs: list[str]) -> tuple[list[str], list[str]]:
    """The GitHub names that check out, and the ones that don't. ["example/app#49", "app 49"] ->
    (["example/app#49"], ["app 49"])."""
    good, bad = [], []
    for ref in refs:
        parsed = github.parse(str(ref))
        if parsed is None:
            bad.append(str(ref))
            continue
        good.append(str(parsed))
    return good, bad


def from_watch(check, title: str, kind: str, owner: str, refs: list[str], mail_id: str, next_step: str,
               loop_id: int, close_why: str, priority: str) -> str:
    """Opens, adds to or closes one loop for the watch's owner, and says what it did, in words for the model.
      ("app #49 …", "pull request", refs ["example/app#49"]), none open -> "Opened loop #1 …"
      the same again from another mail -> "Added to loop #1 (it already follows example/app#49)."
      (loop_id 1, close_why "merged 18 Nov") -> "Closed loop #1."
      refs ["app 49"] -> says it isn't a GitHub name, changes nothing;  loop_id of another owner -> "No open loop #9." """
    store, pid, now = check.fetcher.store, check.fetcher.owner, check.fetcher.now
    good, bad = checked_refs(refs)
    if bad:
        return f"Not a GitHub name: {', '.join(bad)}. Write owner/repo#number, as example/app#49."
    mail = None
    if mail_id:
        mail = check.fetcher.read_mail(mail_id.removeprefix("mail:"))
        if mail is None:
            return f"This check doesn't know mail {mail_id}: use an id from new_mail."
    evidence_ref, fact, mail_refs = "", "", []
    if mail is not None:
        evidence_ref, fact, mail_refs = f"mail:{mail.id}", mail.subject[:200], shortcut.refs_of(mail)
    all_refs = list(dict.fromkeys([*good, *mail_refs]))
    if loop_id:
        return _about_one(store, pid, now, int(loop_id), close_why, evidence_ref, fact, all_refs)
    held = ledger.find_by_refs(store, pid, all_refs)
    if held is not None:
        ledger.attach(store, held["id"], now, "mail", evidence_ref, fact or title, refs=all_refs)
        return f"Added to loop #{held['id']} (it already follows {', '.join(set(all_refs) & set(held['refs']))})."
    book = playbooks.for_kind(kind)
    playbook = ""
    if book is not None and good:  # a playbook needs a name it can look up
        playbook = book.name
    lid = ledger.open_loop(store, pid, now, title, kind, owner=owner, refs=all_refs, next_step=next_step,
                           playbook=playbook, priority=priority, source="mail", ref=evidence_ref, fact=fact or title)
    return f"Opened loop #{lid} {title.strip()}."


def _about_one(store, pid: str, now, loop_id: int, close_why: str, evidence_ref: str, fact: str,
               refs: list[str]) -> str:
    """Adds to or closes one named loop: it must be this owner's and still open."""
    loop = ledger.get(store, loop_id)
    if loop is None or loop["personality"] != pid or loop["state"] not in ledger.OPEN:
        return f"No open loop #{loop_id}."
    if close_why.strip():
        ledger.close(store, loop_id, now, "odie", close_why)
        return f"Closed loop #{loop_id}."
    ledger.attach(store, loop_id, now, "mail", evidence_ref, fact or "news", refs=refs)
    return f"Added to loop #{loop_id}."
