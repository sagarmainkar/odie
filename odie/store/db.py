"""Thin SQLite layer. One connection, a lock, WAL. Small data, single user."""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

SCHEMA = Path(__file__).with_name("schema.sql").read_text()


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def local_now_iso() -> str:
    """Now in the user's timezone, minute precision, with offset: the format every task time is stored and compared in."""
    from zoneinfo import ZoneInfo

    from odie import config
    return datetime.now(ZoneInfo(config.settings.timezone)).isoformat(timespec="minutes")


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._lock = threading.RLock()

    TASK_COLUMNS = {"delivered_at": "TEXT", "snoozed_until": "TEXT", "last_seen_at": "TEXT", "detail": "TEXT",
                    "seen_at": "TEXT", "notice_media": "TEXT"}  # the curtain: when the user acted or dismissed; a spoken memo, as JSON
    APPROVAL_COLUMNS = {"risk": "TEXT"}
    PUSH_COLUMNS = {"device_id": "INTEGER"}  # the paired device that subscribed (none before pairing)
    TRACKER_COLUMNS = {"page_url": "TEXT", "signin_allowed": "INTEGER NOT NULL DEFAULT 0"}  # a signed-in tracker's page and the user's Allow

    def init_schema(self) -> None:
        with self._lock:
            self._conn.executescript(SCHEMA)
            # The old SQLite memories table was replaced by memories.md; existing installs still have it, empty. Drop it
            # (dropping the fts5 table removes its shadow tables; dropping memories removes its triggers).
            self._conn.execute("drop table if exists memories_fts")
            self._conn.execute("drop table if exists memories")
            have = {r["name"] for r in self._conn.execute("pragma table_info(tasks)")}
            for col, typ in self.TASK_COLUMNS.items():
                if col not in have:
                    self._conn.execute(f"alter table tasks add column {col} {typ}")
            self._conn.execute("create index if not exists tasks_source on tasks(source_kind, source_ref)")
            have = {r["name"] for r in self._conn.execute("pragma table_info(approvals)")}
            for col, typ in self.APPROVAL_COLUMNS.items():
                if col not in have:
                    self._conn.execute(f"alter table approvals add column {col} {typ}")
            have = {r["name"] for r in self._conn.execute("pragma table_info(push_subscriptions)")}
            for col, typ in self.PUSH_COLUMNS.items():
                if col not in have:
                    self._conn.execute(f"alter table push_subscriptions add column {col} {typ}")
            have = {r["name"] for r in self._conn.execute("pragma table_info(trackers)")}
            for col, typ in self.TRACKER_COLUMNS.items():
                if col not in have:
                    self._conn.execute(f"alter table trackers add column {col} {typ}")

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def execute(self, sql: str, params: tuple | dict = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, params)

    def query(self, sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self._conn.execute(sql, params).fetchall()

    def one(self, sql: str, params: tuple | dict = ()) -> sqlite3.Row | None:
        with self._lock:
            return self._conn.execute(sql, params).fetchone()

    # tasks
    def add_task(self, title: str, kind: str, due_at: str | None = None, next_check_at: str | None = None,
                 source_kind: str | None = None, source_ref: str | None = None, origin: str = "user",
                 notes: str | None = None) -> int:
        return self.execute(
            "insert into tasks(title,kind,due_at,next_check_at,source_kind,source_ref,origin,notes) values(?,?,?,?,?,?,?,?)",
            (title, kind, due_at, next_check_at, source_kind, source_ref, origin, notes)).lastrowid

    def update_task(self, task_id: int, **fields: Any) -> None:
        fields["updated_at"] = now_iso()
        if fields.get("status") in ("done", "dropped"):
            fields.setdefault("completed_at", now_iso())
        cols = ", ".join(f"{k}=?" for k in fields)
        self.execute(f"update tasks set {cols} where id=?", (*fields.values(), task_id))

    def list_tasks(self, status: str | None = None) -> list[sqlite3.Row]:
        if status:
            return self.query("select * from tasks where status=? order by coalesce(due_at,next_check_at,created_at)", (status,))
        return self.query("select * from tasks order by coalesce(due_at,next_check_at,created_at)")

    def closed_today(self, since_utc_iso: str) -> int:
        """Tasks the user closed since local midnight (given in UTC); ones closed because the source dropped them don't count."""
        row = self.one(
            "select count(*) n from tasks where status='done' and completed_at >= ? and coalesce(notes,'') != 'resolved at source'",
            (since_utc_iso,),
        )
        return int(row["n"]) if row else 0

    # tasks from sources (ledger, mail): one row per (source_kind, source_ref)
    def upsert_source_task(self, source_kind: str, source_ref: str, title: str, kind: str, due_at: str | None = None,
                           detail: str | None = None, next_check_at: str | None = None) -> tuple[int, bool]:
        now = now_iso()
        row = self.one("select id, status from tasks where source_kind=? and source_ref=? order by id desc limit 1", (source_kind, source_ref))
        if row:
            if row["status"] in ("done", "dropped"):  # The user closed it: the source still listing it does not reopen it
                self.execute("update tasks set last_seen_at=? where id=?", (now, row["id"]))
                return row["id"], False
            self.execute("update tasks set title=?, due_at=coalesce(?, due_at), detail=coalesce(?, detail), last_seen_at=?, updated_at=? where id=?",
                         (title, due_at, detail, now, now, row["id"]))
            return row["id"], False
        tid = self.execute(
            "insert into tasks(title,kind,due_at,next_check_at,source_kind,source_ref,origin,detail,last_seen_at) values(?,?,?,?,?,?,?,?,?)",
            (title, kind, due_at, next_check_at, source_kind, source_ref, "system", detail, now)).lastrowid
        return tid, True

    def close_missing_source_tasks(self, source_kind: str, seen_refs: set[str]) -> list[sqlite3.Row]:
        rows = self.query("select * from tasks where source_kind=? and status in ('open','waiting')", (source_kind,))
        closed = [r for r in rows if r["source_ref"] not in seen_refs]
        for r in closed:
            self.update_task(r["id"], status="done", notes="resolved at source")
        return closed

    def open_tasks(self, now: str | None = None) -> list[sqlite3.Row]:
        now = now or local_now_iso()
        return self.query("select * from tasks where status in ('open','waiting') and (snoozed_until is null or snoozed_until <= ?) "
                          "order by coalesce(due_at,next_check_at,created_at)", (now,))

    def due_tasks(self, now: str | None = None) -> list[sqlite3.Row]:
        now = now or local_now_iso()
        # Timed reminders: things the user or Odie set (origin user/agent), plus anything snoozed ("remind me again").
        # Dues synced from the ledger (origin system) are dated, not timed: they stay on Today and in the brief.
        return self.query(
            "select * from tasks where status in ('open','waiting') and delivered_at is null "
            "and (origin != 'system' or snoozed_until is not null) "
            "and coalesce(snoozed_until, due_at, next_check_at) is not null and coalesce(snoozed_until, due_at, next_check_at) <= ? "
            "order by coalesce(snoozed_until, due_at, next_check_at)", (now,))

    def mark_delivered(self, task_id: int, when: str | None = None, notice_media: str | None = None) -> None:
        self.update_task(task_id, delivered_at=when or local_now_iso(), notice_media=notice_media)

    def pending_notices(self) -> list[sqlite3.Row]:
        """Reminders that fired and nobody has answered yet (the curtain shows them, oldest first): delivered, not
        seen, still open. Example: a reminder that rang at 6 pm while the phone was in a pocket -> listed when the app
        opens; one the user dismissed -> not listed, though it stays on Today."""
        return self.query("select * from tasks where delivered_at is not null and seen_at is null and status in ('open','waiting') "
                          "order by delivered_at")

    def mark_seen(self, task_id: int, when: str | None = None) -> None:
        self.update_task(task_id, seen_at=when or local_now_iso())

    def snooze_task(self, task_id: int, until: str) -> None:
        self.update_task(task_id, snoozed_until=until, delivered_at=None)

    # approvals: the index over ADK's pending tool confirmations
    def create_approval(self, session_id: str, invocation_id: str, request_id: str, tool: str, args: dict, summary: str,
                        detail: dict | None, provenance: list | None, risk: str = "normal") -> int:
        return self.execute(
            "insert into approvals(session_id,invocation_id,request_id,tool,args_json,summary,detail_json,provenance_json,risk) values(?,?,?,?,?,?,?,?,?)",
            (session_id, invocation_id, request_id, tool, json.dumps(args, default=str), summary,
             json.dumps(detail or {}, default=str), json.dumps(provenance or [], default=str), risk)).lastrowid

    def pending_approvals(self) -> list[sqlite3.Row]:
        return self.query("select * from approvals where status='pending' order by id")

    def approvals_in_sessions(self, session_ids: list[str]) -> list[sqlite3.Row]:
        if not session_ids:
            return []
        marks = ",".join("?" * len(session_ids))
        return self.query(f"select * from approvals where session_id in ({marks}) order by id", tuple(session_ids))

    def get_approval(self, approval_id: int) -> sqlite3.Row | None:
        return self.one("select * from approvals where id=?", (approval_id,))

    def decide_approval(self, approval_id: int, approve: bool) -> bool:
        """True if this call made the decision; False if it was already decided or expired (second tap is a no-op)."""
        cur = self.execute("update approvals set status=?, decided_at=? where id=? and status='pending'",
                           ("approved" if approve else "rejected", now_iso(), approval_id))
        return cur.rowcount == 1

    def set_approval_result(self, approval_id: int, text: str) -> None:
        self.execute("update approvals set result_text=? where id=?", (text[:2000], approval_id))

    def expire_approvals(self, before: str) -> list[sqlite3.Row]:
        rows = self.query("select * from approvals where status='pending' and created_at < ?", (before,))
        for r in rows:
            self.execute("update approvals set status='expired', decided_at=? where id=?", (now_iso(), r["id"]))
        return rows

    # settings (json values)
    def get_setting(self, key: str, default=None):
        row = self.one("select value_json from settings where key=?", (key,))
        return json.loads(row["value_json"]) if row else default

    def set_setting(self, key: str, value) -> None:
        self.execute("insert into settings(key,value_json) values(?,?) on conflict(key) do update set value_json=excluded.value_json",
                     (key, json.dumps(value, default=str)))

    # block state: what the user did to a block in a chat reply (a checklist's ticks), by reply and place in the reply
    BLOCK_VALUE_MAX = 16000     # characters of JSON for one block's value: a 40-item checklist's ticks need ~120, a sent
                                # 12-field form with long text answers ~7,000 (raised from 4,000, 26 Oct 2026)
    BLOCK_PATHS_PER_REPLY = 50  # blocks with a saved value in one reply

    def block_state(self, session_id: str, message_key: str) -> dict[str, Any]:
        """Every saved value in one reply, by block path: {"0/2": [0, 3]} (the third block of its first fence has items
        0 and 3 ticked). An unknown reply gives {}."""
        rows = self.query("select block_path, value_json from block_state where session_id=? and message_key=?",
                          (session_id, message_key))
        return {r["block_path"]: json.loads(r["value_json"]) for r in rows}

    def save_block_state(self, session_id: str, message_key: str, block_path: str, value: Any) -> None:
        """Saves one block's value, replacing the one before. Raises ValueError (nothing saved) when the value is too big,
        or when it would be a new block in a reply that already holds BLOCK_PATHS_PER_REPLY saved values:
        a 51st path in one reply → refused; the 50th path saved again with new ticks → saved."""
        value_json = json.dumps(value, separators=(",", ":"))
        if len(value_json) > self.BLOCK_VALUE_MAX:
            raise ValueError(f"value is over {self.BLOCK_VALUE_MAX} characters")
        saved = self.block_state(session_id, message_key)
        is_new_path = block_path not in saved
        if is_new_path and len(saved) >= self.BLOCK_PATHS_PER_REPLY:
            raise ValueError(f"a reply holds at most {self.BLOCK_PATHS_PER_REPLY} saved blocks")
        self.execute(
            "insert into block_state(session_id, message_key, block_path, value_json, updated_at) values (?,?,?,?,?) "
            "on conflict(session_id, message_key, block_path) do update set value_json=excluded.value_json, updated_at=excluded.updated_at",
            (session_id, message_key, block_path, value_json, now_iso()))

    # provenance for approval cards (persistent, so a restart does not blank the card)
    def log_mail_seen(self, session_id: str | None, invocation_id: str | None, from_: str, subject: str, via: str) -> None:
        self.audit("agent", "mail_seen", tool=via, args={"from": from_[:200], "subject": subject[:200], "via": via},
                   session_id=session_id, invocation_id=invocation_id)

    def recent_mail_seen(self, session_id: str, limit: int = 10) -> list[dict]:
        """Mail the model has seen in this session, tagged by turn: 'current' (since the latest user message) or
        'previous' (the turn before). Older mail is not provenance for a new action."""
        turns = self.query("select id from audit_log where session_id=? and actor='user' and event='message' order by id desc limit 2", (session_id,))
        if not turns:
            return []
        cur_id = turns[0]["id"]
        prev_id = turns[1]["id"] if len(turns) > 1 else 0
        rows = self.query("select id, args_json from audit_log where session_id=? and event='mail_seen' and id > ? order by id desc limit ?",
                          (session_id, prev_id, limit))
        out = []
        for r in rows:
            d = json.loads(r["args_json"])
            d["turn"] = "current" if r["id"] > cur_id else "previous"
            out.append(d)
        return out

    def log_draft(self, session_id: str | None, invocation_id: str | None, draft_id: str, meta: dict) -> None:
        self.audit("agent", "draft_created", tool="gmail_create_draft", args={"draft_id": draft_id, **{k: meta.get(k) for k in ("to", "cc", "subject", "body")}},
                   session_id=session_id, invocation_id=invocation_id)

    def draft_info(self, session_id: str, draft_id: str) -> dict | None:
        row = self.one("select args_json from audit_log where event='draft_created' and session_id=? and json_extract(args_json,'$.draft_id')=? order by id desc limit 1",
                       (session_id, draft_id))
        return json.loads(row["args_json"]) if row else None

    def unfinished_approvals(self) -> list[sqlite3.Row]:
        return self.query("select * from approvals where status in ('approved','rejected') and result_text is null order by id")

    def tool_ran_after(self, session_id: str, tool: str, after_ts: str) -> bool:
        return self.one("select 1 from audit_log where session_id=? and event='tool_call' and tool=? and ts >= ? limit 1", (session_id, tool, after_ts)) is not None

    # push
    def add_subscription(self, endpoint: str, p256dh: str, auth: str, device_id: int | None = None) -> bool:
        cur = self.execute("insert or ignore into push_subscriptions(endpoint,p256dh,auth,device_id) values(?,?,?,?)",
                           (endpoint, p256dh, auth, device_id))
        if cur.rowcount == 0 and device_id is not None:  # the same browser, paired again
            self.execute("update push_subscriptions set device_id=? where endpoint=?", (device_id, endpoint))
        return cur.rowcount == 1

    def list_subscriptions(self) -> list[sqlite3.Row]:
        return self.query("select * from push_subscriptions")

    def delete_subscription(self, endpoint: str) -> None:
        self.execute("delete from push_subscriptions where endpoint=?", (endpoint,))

    def has_chats(self) -> bool:
        """The install already has chat history (setup and pairing treat it as an existing one)."""
        return self.one("select 1 from audit_log where actor='user' and event='message' limit 1") is not None

    # audit
    def audit(self, actor: str, event: str, tool: str | None = None, args: Any = None, result_summary: str | None = None,
              session_id: str | None = None, invocation_id: str | None = None, approval_id: int | None = None) -> None:
        self.execute(
            "insert into audit_log(session_id,invocation_id,actor,event,tool,args_json,result_summary,approval_id) "
            "values(?,?,?,?,?,?,?,?)",
            (session_id, invocation_id, actor, event, tool, json.dumps(args, default=str) if args is not None else None,
             (result_summary or "")[:500] or None, approval_id))


def approval_dict(r) -> dict:
    """An approvals row for the app: JSON columns parsed (args, detail, provenance)."""
    d = dict(r)
    for k in ("args_json", "detail_json", "provenance_json"):
        try:
            d[k[:-5]] = json.loads(d.pop(k) or "null")
        except (ValueError, TypeError):
            d[k[:-5]] = None
    return d
