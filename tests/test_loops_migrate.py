"""The upgrade to phase 3 (proactive design §5, "What happens to what exists"): the watch's threads, the Needs-you items
of watch.card, the reminders the watch added (source_kind 'ref') and the loops already there become one loop per thing,
merged where they are the same thing, keeping Later times and Done, never pushing again what was pushed. It runs once
(versioned), is safe to run twice, leaves the old data where it was, and can be dry-run on a copy.
The database here is built from the schema, shaped like a live one; nothing is read from a real home."""
import json
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from odie import personalities
from odie.loops import ledger, migrate
from odie.store.db import Store

TZ = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 11, 19, 12, 0, tzinfo=TZ)
VOTE = "Vote: Northwind postal ballot — e-voting closes 21 Nov"


def utc(days_ago: float = 0, hours: float = 0) -> str:
    """A tasks-table time (UTC, as SQLite's default writes it), `days_ago` before NOW."""
    at = (NOW - timedelta(days=days_ago, hours=hours)).astimezone(ZoneInfo("UTC"))
    return at.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def task(store, title, kind, source_kind, source_ref, status="open", notes=None, due=None, created=1.0, closed=None,
         personality=None, origin="agent"):
    tid = store.add_task(title, kind, due_at=due, source_kind=source_kind, source_ref=source_ref, origin=origin,
                         notes=notes, personality=personality)
    fields = {"created_at": utc(created)}
    if status != "open":
        fields["status"] = status
        fields["completed_at"] = utc(closed if closed is not None else created / 2)
    cols = ", ".join(f"{k}=?" for k in fields)
    store.execute(f"update tasks set {cols} where id=?", (*fields.values(), tid))
    return tid


def thread_notes(kind, thread="", sender="", due=None):
    return json.dumps({"thread": thread, "source": "mail:gmail", "kind": kind, "due": due, "sender": sender})


def live_like(store) -> dict:
    """A database shaped like his live one on 19 Nov: threads, card items (one a PR's duplicate), the triple vote
    reminder, an existing PR loop, a personality's own watch."""
    ids = {}
    ids["reply"] = task(store, "Reply to Asha: the deck", "followup", "watch", "mail:r1",
                        notes=thread_notes("reply", "t1", "asha@example.com"), created=1)
    ids["bill"] = task(store, "Gas bill — ₹1,200", "reminder", "watch", "mail:b1", due="2026-11-25T09:00+05:30",
                       notes=thread_notes("bill", "t2", "billing@gasco.example", "2026-11-25T09:00+05:30"), created=2)
    ids["order"] = task(store, "Order: desk lamp", "waiting", "watch", "mail:o1", status="done",
                        notes='Closed by the watch: delivered 18 Nov\nKept for a reopen: {"thread": "t3", "kind": "order"}',
                        created=5, closed=1)
    ids["dismissed"] = task(store, "Reply: webinar invite", "followup", "watch", "mail:w1", status="done",
                            notes='Closed by the user: dismissed on Today\nKept for a reopen: {"thread": "t4", "kind": "reply"}',
                            created=3, closed=2)
    ids["ancient"] = task(store, "Order: kettle", "waiting", "watch", "mail:k1", status="done",
                          notes="Closed by the watch: delivered", created=70, closed=60)
    ids["vote1"] = task(store, VOTE, "reminder", "ref", "event:uid1", status="done", due="2026-11-21T09:00+05:30",
                        created=0.31, closed=0.30)
    ids["vote2"] = task(store, "Vote: Northwind postal ballot – e-voting closes 21 Nov", "reminder", "ref",
                        "Inbox/Digest 2026-11-19.md", status="done", due="2026-11-21T09:00+05:30", created=0.23,
                        closed=0.22)
    ids["vote3"] = task(store, VOTE, "reminder", "ref", "event:uid1", status="done", due="2026-11-21T09:00+05:30",
                        created=0.12, closed=0.11)
    ids["fee"] = task(store, "Pay the school fee", "reminder", "ref", "event:uid9", due="2026-11-28T09:00+05:30",
                      created=1)
    ids["own"] = task(store, "Call the plumber", "todo", None, None, origin="user", created=1)
    pr = ledger.open_loop(store, "", NOW - timedelta(days=1), "app #46 Threads newest first", "pull request",
                          refs=["example/app#46", "thread:g46"], playbook="github-pr", source="mail", ref="mail:g6",
                          fact="Review requested", state="ready")
    ids["pr_loop"] = pr
    later = (NOW + timedelta(hours=21)).isoformat(timespec="seconds")
    store.set_setting("watch.card", {"checked_at": NOW.isoformat(), "line": "2 new emails", "events": [], "sources": {},
                                     "needs_you": [
        {"ref": "mail:r1", "title": "Reply to Asha", "why": "asks for the deck by Friday", "pile": "personal",
         "at": (NOW - timedelta(days=1)).isoformat(timespec="seconds"), "done": False, "from": "Asha",
         "subject": "The deck", "thread": "t1", "sender": "asha@example.com",
         "suggestion": {"label": "Show the draft", "run": "Show the draft for watch item mail:r1"},
         "draft": {"to": "asha@example.com", "subject": "Re: The deck", "body": "Hi Asha, here it is."}},
        {"ref": "mail:g7", "title": "PR #46: review requested", "why": "your review", "pile": "alerts",
         "at": (NOW - timedelta(hours=20)).isoformat(timespec="seconds"), "done": False,
         "subject": "Re: [example/app] Threads newest first (PR #46)", "thread": "g46"},
        {"ref": "event:e5", "title": "Dentist moved to 16:00", "why": "moved from 11:00", "pile": "events",
         "at": (NOW - timedelta(hours=3)).isoformat(timespec="seconds"), "done": False, "hidden_until": later},
        {"ref": "mail:x9", "title": "Sign the lease", "why": "by Friday", "pile": "alerts", "done": True,
         "at": (NOW - timedelta(days=2)).isoformat(timespec="seconds")},
    ]})
    store.set_setting("watch.flagged", ["mail:r1"])
    mira = personalities.create(store, "Mira").id
    ids["mira"] = mira
    ids["mira_thread"] = task(store, "Reply to the landlord", "followup", "watch", "mail:m1", personality=mira,
                              notes=thread_notes("reply", "tm", "landlord@example.com"), created=1)
    store.set_setting(f"watch.card:{mira}", {"needs_you": [
        {"ref": "mail:m2", "title": "Choir rota", "why": "pick a Sunday", "pile": "personal", "done": False,
         "at": (NOW - timedelta(hours=5)).isoformat(timespec="seconds")}]})
    return ids


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "live-copy.db")
    s.init_schema()
    return s


def loops_of(store, pid=""):
    return [ledger.get(store, r["id"]) for r in store.query(
        "select id from loops where coalesce(personality,'') = ? order by id", (pid,))]


def holding(store, ref, pid=""):
    return [lp for lp in loops_of(store, pid) if ref in lp["refs"]]


def test_everything_becomes_one_loop_per_thing(store):
    ids = live_like(store)
    lines = migrate.run(store, NOW)
    assert lines and store.get_setting(migrate.KEY)["version"] == migrate.VERSION
    # the reply owed: its thread and its card item are one loop, a card, with the draft and Why?
    reply = holding(store, f"task:{ids['reply']}")
    assert len(reply) == 1 and "mail:r1" in reply[0]["refs"] and reply[0]["state"] == "ready"
    assert reply[0]["card"]["draft"]["body"] == "Hi Asha, here it is." and reply[0]["owner"] == "you"
    assert reply[0]["card"]["sender"] == "asha@example.com" and reply[0]["card"]["thread"] == "t1"
    # the PR's old card item joins the PR's loop: one card for the PR
    assert holding(store, "mail:g7") == [] or holding(store, "mail:g7")[0]["id"] == ids["pr_loop"]
    pr_events = [e["ref"] for e in ledger.events(store, ids["pr_loop"])]
    assert "mail:g7" in pr_events
    from odie.watch import needs
    refs = [c["ref"] for c in needs.cards(store, NOW, "")]
    assert refs.count(f"loop:{ids['pr_loop']}") == 1
    assert not any(c["title"] == "PR #46: review requested" for c in needs.cards(store, NOW, ""))
    # the triple vote reminder: one loop, finished by him (Done remembered), every source's ID on it
    vote = holding(store, f"task:{ids['vote1']}")
    assert len(vote) == 1 and vote[0]["closed_by"] == "you" and vote[0]["state"] == "closed"
    assert {f"task:{ids['vote2']}", f"task:{ids['vote3']}", "event:uid1", "note:Inbox/Digest 2026-11-19.md"} <= set(vote[0]["refs"])
    assert len(holding(store, "event:uid1")) == 1
    # Later kept; a done item remembered; a dismissed thread remembered as his; Odie's close kept as Odie's
    dentist = holding(store, "event:e5")[0]
    assert dentist["hidden_until"] == (NOW + timedelta(hours=21)).isoformat(timespec="seconds")
    assert holding(store, "mail:x9")[0]["closed_by"] == "you"
    assert holding(store, f"task:{ids['dismissed']}")[0]["closed_by"] == "you"
    order = holding(store, f"task:{ids['order']}")[0]
    assert order["closed_by"] == "odie" and order["closed_why"] == "delivered 18 Nov"
    assert holding(store, f"task:{ids['ancient']}") == []  # closed two months ago: not carried
    # the open bill keeps its reminder (it rings as before), and its card is the loop's, not the task's
    bill = holding(store, f"task:{ids['bill']}")[0]
    assert bill["due_at"] == "2026-11-25T09:00+05:30" and bill["state"] == "ready"
    assert f"task:{ids['bill']}" not in refs and f"task:{ids['fee']}" not in refs and f"task:{ids['own']}" in refs
    # Mira's stay hers
    assert {lp["title"] for lp in loops_of(store, ids["mira"])} == {"Reply to the landlord", "Choir rota"}


def test_nothing_pushed_before_is_pushed_again(store):
    live_like(store)
    migrate.run(store, NOW)
    reply = holding(store, "mail:r1")[0]
    assert f"loop:{reply['id']}" in store.get_setting("watch.flagged")
    from odie.loops import ladder
    assert ladder.has_step(store, reply["id"], ladder.DUE_PUSH)


def test_done_after_the_upgrade_sticks_for_the_digest_and_the_event(store):
    import asyncio

    from odie.loops import consolidate
    live_like(store)
    migrate.run(store, NOW)
    digest = {"ref": "note:Inbox/Digest 2026-11-19.md", "title": VOTE, "kind": "reminder", "why": "", "owner": "you",
              "due": None, "remind_at": "2026-11-21T09:00+05:30", "done": "", "stage": "", "push": False,
              "refs": ["note:Inbox/Digest 2026-11-19.md"], "card": {}}
    event = {**digest, "ref": "event:uid1", "refs": ["event:uid1"]}

    vote = holding(store, "event:uid1")[0]

    async def matches_the_digest(prompt, instruction):  # a note is a container: matching it is the model's
        return '{"answers": [{"f": "F1", "is": "same", "loop": %d}]}' % vote["id"]
    got = asyncio.run(consolidate.consolidate(store, "", NOW, [digest, event], matches_the_digest, {}))
    assert got.opened == [] and got.reminders == 0 and got.quiet == [vote["id"], vote["id"]]


def test_it_runs_once_and_twice_changes_nothing(store):
    live_like(store)
    migrate.run(store, NOW)
    before = [(lp["id"], lp["state"], tuple(lp["refs"]), lp["hidden_until"]) for lp in loops_of(store)]
    events_before = store.one("select count(*) n from loop_events")["n"]
    assert migrate.run_once(store, NOW) is None  # already at this version
    migrate.run(store, NOW)  # forced again: nothing new
    after = [(lp["id"], lp["state"], tuple(lp["refs"]), lp["hidden_until"]) for lp in loops_of(store)]
    assert after == before and store.one("select count(*) n from loop_events")["n"] == events_before


def test_the_old_data_stays_where_it_was(store):
    live_like(store)
    card = store.get_setting("watch.card")
    tasks = [dict(r) for r in store.query("select * from tasks order by id")]
    migrate.run(store, NOW)
    assert store.get_setting("watch.card")["needs_you"] == card["needs_you"]
    assert [dict(r) for r in store.query("select * from tasks order by id")] == tasks


def test_a_dry_run_writes_nothing_and_says_what_it_would_do(store, tmp_path, capsys):
    live_like(store)
    path = store.path
    store.close()
    before = sqlite3.connect(path).execute("select count(*) from loops").fetchone()[0]
    assert migrate.main(["--dry-run", "--db", str(path), "--now", NOW.isoformat()]) == 0
    out = capsys.readouterr().out
    assert "would" in out.lower() and VOTE[:20] in out and "merge" in out.lower()
    conn = sqlite3.connect(path)
    assert conn.execute("select count(*) from loops").fetchone()[0] == before
    assert conn.execute("select count(*) from settings where key = ?", (migrate.KEY,)).fetchone()[0] == 0
