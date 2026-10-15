"""Local tools: task ledger, clock. (Memory tools live in odie.memory.tools.) Plain functions wrapped in FunctionTool so the
docstrings become the tool descriptions the model sees. Keep them short."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from google.adk.tools import FunctionTool

from odie.store.db import Store


def threads_summary(store: Store) -> str:
    """'2 waiting, 3 to do': open threads by state, for the context note (was misnamed ledger_summary)."""
    rows = store.query("select status, kind, count(*) n from tasks where status in ('open','waiting') group by status, kind")
    if not rows:
        return ""
    waiting = sum(r["n"] for r in rows if r["status"] == "waiting" or r["kind"] == "waiting")
    todo = sum(r["n"] for r in rows) - waiting
    bits = []
    if waiting:
        bits.append(f"{waiting} waiting")
    if todo:
        bits.append(f"{todo} to do")
    return "Open threads: " + ", ".join(bits) + "."


def parse_when(value: str | None, zone: ZoneInfo) -> str | None:
    """Accept ISO date or datetime (naive = the user's timezone). Return ISO with offset, or None if unparseable."""
    if not value:
        return None
    v = value.strip().replace(" ", "T") if "T" not in value and " " in value.strip() else value.strip()
    try:
        dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    if len(v) == 10:  # bare date: a sensible morning hour, not midnight
        dt = dt.replace(hour=9, minute=0)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=zone)
    return dt.astimezone(zone).isoformat(timespec="minutes")


def make_local_tools(store: Store, tz: str, source_done=None) -> list[FunctionTool]:
    """source_done(kind, ref): closes a thread at its source (the SMS ledger, say) and returns a note, or None."""
    zone = ZoneInfo(tz)

    def task_add(title: str, kind: str = "todo", due: str | None = None, next_check: str | None = None,
                 source_ref: str | None = None) -> str:
        """Add an open thread to the user's ledger. kind: todo, reminder, followup, waiting. due / next_check: ISO datetime like 2026-10-01T11:00 (today's date from the context; naive times are the user's timezone). A reminder fires in the chat at `due`. source_ref: a message, thread or event id if there is one."""
        if kind not in ("todo", "reminder", "followup", "waiting"):
            kind = "todo"
        due_iso, check_iso = parse_when(due, zone), parse_when(next_check, zone)
        if (due and not due_iso) or (next_check and not check_iso):
            return "I didn't catch the time. Give me an ISO datetime like 2026-10-01T11:00."
        tid = store.add_task(title.strip(), kind, due_at=due_iso, next_check_at=check_iso,
                             source_kind="ref" if source_ref else None, source_ref=source_ref, origin="agent")
        when = due_iso or check_iso
        return f"Added task #{tid} {title.strip()}" + (f" for {when}" if when else "")

    async def task_update(task_id: int, status: str | None = None, next_check: str | None = None, notes: str | None = None,
                          snooze_until: str | None = None) -> str:
        """Update a thread. status: done (the user handled it: paid, replied, finished), dropped (not needed), open, waiting. snooze_until: ISO datetime to hide it and remind again then. next_check: ISO datetime for a follow-up."""
        row = store.one("select * from tasks where id=?", (int(task_id),))
        if row is None:
            return f"No task #{task_id}."
        fields: dict = {}
        if status in ("open", "waiting", "done", "dropped"):
            fields["status"] = status
        if next_check:
            iso = parse_when(next_check, zone)
            if not iso:
                return "I didn't catch the time for next_check (use ISO like 2026-10-03T09:00)."
            fields["next_check_at"] = iso
            fields["delivered_at"] = None
        if notes:
            fields["notes"] = notes
        if snooze_until:
            iso = parse_when(snooze_until, zone)
            if not iso:
                return "I didn't catch the snooze time (use ISO like 2026-10-02T09:00)."
            store.snooze_task(int(task_id), iso)
            fields.pop("delivered_at", None)
        if not fields and not snooze_until:
            return "Nothing to update."
        if fields:
            store.update_task(int(task_id), **fields)
        msg = f"Task #{task_id} '{row['title']}': " + ", ".join(f"{k}={v}" for k, v in fields.items() if k != "delivered_at")
        if snooze_until:
            msg += f" snoozed until {parse_when(snooze_until, zone)}"
        if status == "done" and row["source_kind"] and source_done:
            note = await source_done(row["source_kind"], row["source_ref"])
            if note:
                msg += ". " + note
        return msg

    def task_list(status: str = "open") -> str:
        """List ledger tasks. status: open (default), waiting, done, dropped, all."""
        rows = store.list_tasks(None if status == "all" else status)
        if not rows:
            return f"Nothing {status}."
        return "\n".join(
            f"#{r['id']} [{r['kind']}/{r['status']}] {r['title']}"
            + (f" due {r['due_at']}" if r["due_at"] else "")
            + (f" check {r['next_check_at']}" if r["next_check_at"] else "")
            for r in rows)

    def now() -> str:
        """Current date and time in the user's timezone."""
        return datetime.now(zone).strftime(f"%A %-d %B %Y, %H:%M ({tz})")

    return [FunctionTool(f) for f in (task_add, task_update, task_list, now)]
