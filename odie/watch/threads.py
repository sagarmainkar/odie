"""The watch's own threads (22 Oct 2026): the orders, bills, replies owed and deadlines it follows until they close.

Each thread is a row in the tasks table that the watch made (source_kind "watch", source_ref the mail's ref), so it
shows on Today like any other open thread and the user can tick it. The watch moves its threads with `track` (a new
stage, a new due date) and closes them with a reason when the mail shows they're done (a delivery, a payment, the
user's own reply). It never touches a task the user made: only rows with source_kind "watch" are its own. Every check
starts by reviewing them (`open_threads`), so a thread moves even when no new mail about it arrives."""
from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from odie.watch import report
from odie.watch.bills import CLOSED_NOTE, closed_note

KINDS = {"order": "waiting", "bill": "reminder", "reply": "followup", "deadline": "reminder"}  # thread kind -> task kind
FIRES = frozenset({"bill", "deadline"})  # kinds whose due date fires a reminder (pay it, do it); orders and replies don't
USER_CLOSED_NOTE = "Closed by the user: "
CLOSING = ("done", "dropped")
SOURCE_KIND = "watch"


def _own_open(store, ref: str):
    """The watch's open thread for this mail ref, or None (a task the user made never counts): "mail:o1" with the
    watch's open order thread -> that row; "mail:o1" only on the user's own task, or a closed thread -> None."""
    return store.one("select * from tasks where source_kind = ? and source_ref = ? and status in ('open', 'waiting') "
                     "order by id desc limit 1", (SOURCE_KIND, ref))


def _due(value: str | None) -> str | None:
    """A due date as the tasks table keeps it: "2026-10-24" -> 09:00 that day in the user's time zone; "" -> None."""
    from odie import config
    from odie.agent.tools.local import parse_when
    return parse_when(value, ZoneInfo(config.settings.timezone))


def track(store, ref: str, kind: str, title: str, stage: str, due: str | None = None, why: str = "",
          mail_thread: str = "", mail_source: str = "") -> str:
    """Opens, moves or closes one of the watch's threads, and says what it did. Decides by the stage and whether the
    watch already follows this ref:
      ("mail:o1", "order", "Order: desk lamp", "placed", due "2026-10-24"), none open -> opens a waiting thread
        "Tracking #12 …";
      the same ref, stage "shipped", due "2026-10-23" -> the same row moves: "Moved #12: shipped";
      stage "done" with why "delivered: mail 23 Oct" -> closed, the reason in its notes: "Closed thread #12.";
      stage "done" without a why -> nothing changes, asks why; a kind other than order/bill/reply/deadline -> refused;
      a ref only a user's own task has -> "No open thread …" (the user's task is never touched)."""
    if kind not in KINDS:
        return f"Unknown kind {kind!r}: a thread is an order, a bill, a reply or a deadline."
    row = _own_open(store, ref)
    stage_now = (stage or "").strip().lower()
    if stage_now in CLOSING:
        if row is None:
            return f"No open thread for {ref}."
        reason = (why or "").strip()
        if not reason:
            return "Say why it's closed: which mail showed it, or what the user did."
        store.update_task(row["id"], status=stage_now, notes=closed_note(CLOSED_NOTE, reason, _facts(row["notes"])))
        report.drop_item(store, ref)
        return f"Closed thread #{row['id']}."
    due_at = _due(due)
    if due and due_at is None:
        return "I didn't catch the due date: give it as 2026-10-24 or 2026-10-24T18:00."
    fires = kind in FIRES
    if row is None:
        notes = json.dumps({"thread": mail_thread, "source": mail_source, "kind": kind, "due": due_at})
        reminder_at = due_at if fires else None
        tid = store.add_task(title.strip(), KINDS[kind], due_at=reminder_at, source_kind=SOURCE_KIND, source_ref=ref,
                             origin="agent", notes=notes)
        store.update_task(tid, detail=stage_now)
        return f"Tracking #{tid} {title.strip()} ({stage_now})."
    new_title = title.strip()
    if not new_title:
        new_title = row["title"]
    fields: dict = {"detail": stage_now, "title": new_title}
    facts = _facts(row["notes"])
    if due_at and due_at != facts.get("due"):
        facts["due"] = due_at
        fields["notes"] = json.dumps(facts)
        if fires:
            fields["due_at"] = due_at
            fields["delivered_at"] = None  # a moved date fires again
    store.update_task(row["id"], **fields)
    return f"Moved #{row['id']}: {stage_now}."


def close(store, ref: str, why: str, by_user: bool = False) -> str:
    """Closes the watch's open thread for this ref, whatever its kind, and takes its card item off. by_user: the user
    dismissed it (on Today, or in chat): noted as theirs, so it isn't listed as something the watch got done.
    ("mail:o1", "delivered") with an open thread -> "Closed thread #12."; no open thread -> "No open thread …"."""
    row = _own_open(store, ref)
    if row is None:
        return f"No open thread for {ref}."
    if by_user:
        reason = why or "dismissed"
        store.update_task(row["id"], status="done", notes=closed_note(USER_CLOSED_NOTE, reason, _facts(row["notes"])))
        report.drop_item(store, ref)
        return f"Closed thread #{row['id']}."
    kind = _facts(row["notes"]).get("kind") or "reply"
    return track(store, ref, kind, row["title"], "done", why=why)


def _facts(notes: str | None) -> dict:
    """What an open thread remembers about its mail (thread id, source, kind); {} when its notes aren't that."""
    try:
        got = json.loads(notes or "")
    except ValueError:
        return {}
    if not isinstance(got, dict):
        return {}
    return got


def _overdue(due_at: str | None, now: datetime) -> bool:
    """Whether a thread's due date has passed: due yesterday -> True; due tomorrow or no due date -> False."""
    if not due_at:
        return False
    try:
        return datetime.fromisoformat(due_at) < now
    except ValueError:
        return False


def open_threads(store, now: datetime) -> list[dict]:
    """The watch's open threads, soonest due first: id, ref, kind, title, stage, due, overdue, thread, source,
    opened_at."""
    rows = store.query("select * from tasks where source_kind = ? and status in ('open', 'waiting') order by id",
                       (SOURCE_KIND,))
    out = []
    for r in rows:
        facts = _facts(r["notes"])
        due = facts.get("due") or r["due_at"]
        out.append({"id": r["id"], "ref": r["source_ref"], "kind": facts.get("kind", ""), "title": r["title"],
                    "stage": r["detail"] or "", "due": due, "overdue": _overdue(due, now),
                    "thread": facts.get("thread", ""), "source": facts.get("source", ""), "opened_at": r["created_at"]})
    out.sort(key=lambda t: (t["due"] is None, t["due"] or ""))  # soonest due first, undated last
    return out


def open_refs(store) -> set[str]:
    """The refs of the watch's open threads, which a later check may report on again."""
    rows = store.query("select source_ref from tasks where source_kind = ? and status in ('open', 'waiting')",
                       (SOURCE_KIND,))
    return {r["source_ref"] for r in rows}


def closed_refs(store) -> set[str]:
    """The refs whose watch thread is closed and none is open again: their card items go."""
    rows = store.query("select source_ref from tasks where source_kind = ? and status in ('done', 'dropped')",
                       (SOURCE_KIND,))
    return {r["source_ref"] for r in rows} - open_refs(store)
