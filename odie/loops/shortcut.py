"""The same-ID shortcut (proactive design §3): when the exact same ID recurs, code attaches the new evidence to the
loop that holds it and marks it "has news", saving a matching call. Two IDs count: a mail thread a loop already holds
("thread:<id>"), and the same pull request or issue named by GitHub's own notification mail ("example/app#49").
It is never the main matcher: everything else is the model's, and the model still decides what the news means."""
from __future__ import annotations

from datetime import datetime

from odie.loops import github, ledger


def thread_ref(mail) -> str:
    """The ref a loop holds for a mail's thread: thread "t9" -> "thread:t9"; a mail with no thread id -> ""."""
    thread = getattr(mail, "thread", "") or ""
    if not thread:
        return ""
    return f"thread:{thread}"


def refs_of(mail) -> list[str]:
    """Every ID a mail carries that the shortcut can match: its thread, and the pull request or issue a GitHub
    notification names. A GitHub mail about #49 in thread t9 -> ["thread:t9", "example/app#49"]; a plain mail with no
    thread id -> []."""
    out = []
    thread = thread_ref(mail)
    if thread:
        out.append(thread)
    out += github.refs_in_notification(mail)
    return out


def from_github(mail) -> bool:
    """Whether a mail is GitHub's own notification (its sender is GitHub's address): only such a mail may touch a pull
    request's loop. "Asha <notifications@github.com>" -> True; "Mallory <m@evil.example>" saying "merged" -> False."""
    return github.is_from_github(getattr(mail, "frm", "") or "")


def may_join(loop: dict, mail) -> bool:
    """Whether a mail may be added to this loop by its ID: a pull request's loop (a playbook) only takes GitHub's own
    mail; any other loop takes any mail of its thread. A stranger's reply in a PR's thread -> False."""
    if loop["playbook"]:
        return from_github(mail)
    return True


def attach_known(store, pid: str, mails: list, now: datetime) -> dict[str, int]:
    """Attaches each mail whose ID exactly one open loop of this owner holds (its thread, its pull request), as
    evidence, and returns which loop each went to: {mail id: loop id}. A 15th mail about example/app#49, loop 3 holding
    it -> {"m15": 3}, loop 3 has news; a mail nobody holds -> not in the result (the model reads it as new); GitHub's
    mail about a pull request he closed with Done (and still remembered, ledger.remembered) -> kept on that loop quietly
    (no news, no card). A closed loop is never matched by a thread alone, and a pull request's loop never by a
    stranger's mail."""
    went: dict[str, int] = {}
    for mail in mails:
        refs = refs_of(mail)
        if not refs:
            continue
        loop = ledger.find_by_refs(store, pid, refs)
        if loop is not None and may_join(loop, mail):
            ledger.attach(store, loop["id"], now, "mail", f"mail:{mail.id}", mail.subject[:200], refs=refs)
            went[mail.id] = loop["id"]
            continue
        stopped = ledger.find_done_by_user(store, pid, refs, now)
        if stopped is not None and may_join(stopped, mail):  # he said Done: kept as evidence, no news, no card
            ledger.attach(store, stopped["id"], now, "mail", f"mail:{mail.id}", mail.subject[:200], refs=refs,
                          news=False)
            went[mail.id] = stopped["id"]
    return went
