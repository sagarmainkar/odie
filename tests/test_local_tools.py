from odie.agent.tools.local import threads_summary, make_local_tools
from odie.store.db import Store


def tools(tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s, {t.name: t for t in make_local_tools(s, "Asia/Kolkata")}


def test_names(tmp_path):
    _, t = tools(tmp_path)
    assert set(t) == {"task_add", "task_update", "task_list", "now"}


async def test_tasks(tmp_path):
    s, t = tools(tmp_path)
    out = t["task_add"].func(title="Answer Asha", kind="todo", due="2026-10-03")
    tid = int(out.split("#")[1].split()[0])
    assert "Answer Asha" in t["task_list"].func(status="open")
    await t["task_update"].func(task_id=tid, status="done")
    assert "nothing" in t["task_list"].func(status="open").lower()
    assert threads_summary(s) == ""


def test_threads_summary(tmp_path):
    s, t = tools(tmp_path)
    tid = s.add_task("Waiting on Rahul", "waiting", due_at="2026-10-05")
    s.update_task(tid, status="waiting")
    s.add_task("Call dentist", "todo")
    assert threads_summary(s) == "Open threads: 1 waiting, 1 to do."


def test_now(tmp_path):
    _, t = tools(tmp_path)
    assert "Asia/Kolkata" in t["now"].func()


def test_task_add_validates_time_and_echoes(tmp_path):
    s, t = tools(tmp_path)
    out = t["task_add"].func(title="Call dentist", kind="reminder", due="2026-10-01T11:00")
    assert "Call dentist" in out and "2026-10-01T11:00" in out and "#" in out
    assert "didn't catch the time" in t["task_add"].func(title="x", kind="reminder", due="11 am").lower()
    assert s.one("select due_at from tasks where title='Call dentist'")["due_at"].startswith("2026-10-01T11:00")


async def test_task_update_snooze_and_done_propagates(tmp_path):
    calls = []

    async def fake_done(kind, ref):
        calls.append(ref)
        return f"Ledger: Reminder #{ref} marked done"
    from odie.agent.tools.local import make_local_tools
    s = Store(tmp_path / "a.db")
    s.init_schema()
    t = {x.name: x for x in make_local_tools(s, "Asia/Kolkata", source_done=fake_done)}
    tid, _ = s.upsert_source_task("ledger", "7", "ICICI card ₹12,345", "reminder", due_at="2026-09-29")
    out = await t["task_update"].func(task_id=tid, snooze_until="2026-10-02T09:00")
    assert "snooz" in out.lower() and s.one("select snoozed_until from tasks where id=?", (tid,))["snoozed_until"].startswith("2026-10-02T09:00")
    out = await t["task_update"].func(task_id=tid, status="done")
    assert "done" in out.lower() and calls == ["7"]
    assert s.one("select status from tasks where id=?", (tid,))["status"] == "done"
