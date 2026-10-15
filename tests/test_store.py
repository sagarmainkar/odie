from odie.store.db import Store


def make(tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


def test_schema_tables(tmp_path):
    s = make(tmp_path)
    names = {r["name"] for r in s.query("select name from sqlite_master where type='table'")}
    assert {"approvals", "tasks", "audit_log", "briefs", "push_subscriptions", "settings", "threads"} <= names


# The memories table as older installs created it (replaced by memories.md); init_schema must drop it.
LEGACY_MEMORIES = """
CREATE TABLE memories(
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('fact','preference','contact','project')) DEFAULT 'fact',
  text TEXT NOT NULL, source TEXT, status TEXT NOT NULL CHECK(status IN ('active','proposed','rejected')) DEFAULT 'active',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')), last_used_at TEXT);
CREATE VIRTUAL TABLE memories_fts USING fts5(text, content='memories', content_rowid='id', tokenize='porter unicode61');
CREATE TRIGGER memories_ai AFTER INSERT ON memories BEGIN
  INSERT INTO memories_fts(rowid, text) VALUES (new.id, new.text); END;
CREATE TRIGGER memories_ad AFTER DELETE ON memories BEGIN
  INSERT INTO memories_fts(memories_fts, rowid, text) VALUES ('delete', old.id, old.text); END;
CREATE TRIGGER memories_au AFTER UPDATE OF text ON memories BEGIN
  INSERT INTO memories_fts(memories_fts, rowid, text) VALUES ('delete', old.id, old.text);
  INSERT INTO memories_fts(rowid, text) VALUES (new.id, new.text); END;
"""


def test_init_schema_drops_legacy_memories_tables(tmp_path):
    s = Store(tmp_path / "a.db")
    s._conn.executescript(LEGACY_MEMORIES)
    s.init_schema()
    left = s.query("select name from sqlite_master where name like 'memories%'")
    assert [r["name"] for r in left] == []
    s.init_schema()  # still fine once they are gone


def test_tasks_crud(tmp_path):
    s = make(tmp_path)
    tid = s.add_task("Waiting on Rahul", "waiting", source_kind="thread", source_ref="t103")
    assert s.list_tasks("open")[0]["id"] == tid
    s.update_task(tid, status="done")
    assert s.list_tasks("open") == [] and s.list_tasks("done")[0]["completed_at"]


def test_subscriptions_idempotent(tmp_path):
    s = make(tmp_path)
    assert s.add_subscription("https://e/1", "k", "a") is True
    assert s.add_subscription("https://e/1", "k", "a") is False
    assert len(s.list_subscriptions()) == 1


def test_audit(tmp_path):
    s = make(tmp_path)
    s.audit("agent", "tool_call", tool="gmail_search", args={"query": "x"}, result_summary="3 hits")
    assert s.one("select tool from audit_log")["tool"] == "gmail_search"


def test_tasks_migration_adds_columns(tmp_path):
    s = make(tmp_path)
    cols = {r["name"] for r in s.query("pragma table_info(tasks)")}
    assert {"delivered_at", "snoozed_until", "last_seen_at", "detail"} <= cols
    s.init_schema()  # idempotent


def test_upsert_source_task_dedupes_and_closes_missing(tmp_path):
    s = make(tmp_path)
    tid, created = s.upsert_source_task("ledger", "7", "ICICI card statement ₹12,345", "reminder", due_at="2026-09-29", detail="card_statement")
    tid2, created2 = s.upsert_source_task("ledger", "7", "ICICI card statement ₹12,345 (updated)", "reminder", due_at="2026-09-29")
    assert tid == tid2 and created and not created2
    assert s.one("select title, last_seen_at from tasks where id=?", (tid,))["title"].endswith("(updated)")
    s.upsert_source_task("ledger", "4", "Electricity ₹2,480", "reminder", due_at="2026-10-12")
    closed = s.close_missing_source_tasks("ledger", seen_refs={"4"})
    assert [c["id"] for c in closed] == [tid] and s.one("select status from tasks where id=?", (tid,))["status"] == "done"
    assert s.close_missing_source_tasks("ledger", seen_refs={"4"}) == []  # already closed


def test_due_tasks_deliver_once_and_snooze(tmp_path):
    s = make(tmp_path)
    tid = s.add_task("Call dentist", "reminder", due_at="2026-10-01T11:00:00+05:30")
    assert [t["id"] for t in s.due_tasks("2026-10-01T10:59:00+05:30")] == []
    assert [t["id"] for t in s.due_tasks("2026-10-01T11:00:00+05:30")] == [tid]
    s.mark_delivered(tid, "2026-10-01T11:00:05+05:30")
    assert s.due_tasks("2026-10-01T11:30:00+05:30") == []
    s.snooze_task(tid, "2026-10-01T15:00:00+05:30")
    assert all(t["id"] != tid for t in s.open_tasks("2026-10-01T12:00:00+05:30"))
    assert any(t["id"] == tid for t in s.open_tasks("2026-10-01T15:01:00+05:30"))
    assert [t["id"] for t in s.due_tasks("2026-10-01T15:01:00+05:30")] == [tid]  # snooze re-arms delivery


def test_due_tasks_skip_synced_dues_unless_snoozed(tmp_path):
    s = make(tmp_path)
    led, _ = s.upsert_source_task("ledger", "7", "ICICI card", "reminder", due_at="2026-09-29")
    mine = s.add_task("Stretch", "reminder", due_at="2026-10-01T07:13:00+05:30")
    due = [t["id"] for t in s.due_tasks("2026-10-01T07:14:00+05:30")]
    assert mine in due and led not in due, "a synced due is not a timed reminder; it lives on Today and in the brief"
    s.snooze_task(led, "2026-10-02T09:00:00+05:30")
    assert led in [t["id"] for t in s.due_tasks("2026-10-02T09:01:00+05:30")]  # 'remind me again tomorrow' does fire


def test_closed_today_counts_only_users_closures(tmp_path):
    s = make(tmp_path)
    a = s.add_task("pay bill", "todo")
    b = s.add_task("reply priya", "followup")
    c = s.add_task("old one", "todo")
    d = s.add_task("from ledger", "todo")
    s.update_task(a, status="done", completed_at="2026-10-05T04:00:00.000Z")
    s.update_task(b, status="done", completed_at="2026-10-05T05:00:00.000Z")
    s.update_task(c, status="done", completed_at="2026-10-03T05:00:00.000Z")
    s.update_task(d, status="done", completed_at="2026-10-05T06:00:00.000Z", notes="resolved at source")
    assert s.closed_today("2026-10-04T18:30:00.000Z") == 2
