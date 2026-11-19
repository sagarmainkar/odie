"""The watch's pull requests and issues become loops (proactive design §12): stage 1 writes a finding per mail, stage 2
places them, and code keeps one loop per thing: fourteen notification mails about one pull request are one loop."""
import json
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from odie.loops import ledger
from odie.store.db import Store
from odie.watch import bills, check, report
from tests.test_watch_calls import spec_for

NOW = datetime(2026, 11, 18, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
GH = "Asha <notifications@github.com>"
SUBJECTS = ["[example/app] Threads newest first (PR #49)"] + ["Re: [example/app] Threads newest first (PR #49)"] * 13


def pr_mails(n=14, start=0):
    out = []
    for i in range(start, start + n):
        out.append({"id": f"g{i}", "from": GH, "subject": SUBJECTS[min(i, 13)], "threadId": "t49",
                    "date": f"2026-11-18T0{i // 10}:{i % 10}0:00Z", "body_plain": f"update {i}"})
    return out


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    s.set_setting("watch.state", {"last_check": None, "seen": [], "events": {}, "sources": {}, "caught_up": bills.CATCH_UP})
    return s


async def call(tools, name, **args):
    t = next(t for t in tools if t.name == name)
    return await t.run_async(args=args, tool_context=SimpleNamespace())


async def test_fourteen_mails_about_one_pull_request_are_one_loop(store, tmp_path):
    from odie.plugins import mcp
    mcp.write_config({"home": spec_for("plain", tmp_path, mail=pr_mails())})

    async def naive(prompt, tools, instruction):
        """The worst case: the model writes a finding for every mail it sees."""
        mails = json.loads((await call(tools, "new_mail"))["result"])
        found = [{"ref": f"mail:{m['id']}", "title": "app #49 Threads newest first", "kind": "pull request",
                  "owner": "odie", "refs": ["example/app#49"]} for m in mails]
        await call(tools, "report", findings=found, line="14 GitHub updates")

    async def unsure(prompt, instruction):
        return '{"answers": [' + ", ".join('{"f": "F%d", "is": "new"}' % n for n in range(1, 15)) + "]}"
    assert await check.run_check(store, NOW, naive, lambda t, b: None, think=unsure) == "ok"
    loops = ledger.open_loops(store, "")
    assert len(loops) == 1  # one loop per pull request, whatever the model says
    assert loops[0]["playbook"] == "github-pr" and {"example/app#49", "thread:t49"} <= set(loops[0]["refs"])
    assert len({e["ref"] for e in ledger.events(store, loops[0]["id"])}) == 14
    assert loops[0]["state"] == "new"  # Odie looks at GitHub before any card


async def test_a_later_mail_in_the_same_thread_joins_by_code(store, tmp_path):
    from odie.plugins import mcp
    lid = ledger.open_loop(store, "", NOW - timedelta(hours=2), "app #49", "pull request", refs=["thread:t49"])
    ledger.update(store, lid, NOW, has_news=0)
    mcp.write_config({"home": spec_for("plain", tmp_path, mail=pr_mails(1, 3))})
    seen = {}

    async def turn(prompt, tools, instruction):
        seen["mails"] = json.loads((await call(tools, "new_mail"))["result"])
        await call(tools, "report", needs_you=[], line="")
    await check.run_check(store, NOW, turn, lambda t, b: None)
    assert seen["mails"][0]["loop"] == lid  # the model is told it is already added
    assert ledger.get(store, lid)["has_news"] == 1 and "example/app#49" in ledger.get(store, lid)["refs"]


async def test_findings_are_checked_before_they_reach_the_ledger(store, tmp_path):
    from odie import personalities
    from odie.plugins import mcp
    mcp.write_config({"home": spec_for("plain", tmp_path, mail=pr_mails(1))})
    mira = personalities.create(store, "Mira").id
    hers = ledger.open_loop(store, mira, NOW, "Mira's", "issue", refs=["example/app#7"])

    async def turn(prompt, tools, instruction):
        await call(tools, "new_mail")
        found = [{"ref": "mail:nope", "title": "made up", "kind": "issue"},
                 {"ref": "mail:g0", "title": "app #49", "kind": "pull request", "owner": "odie",
                  "refs": ["app 49; rm -rf ~", "example/app#7"]}]
        await call(tools, "report", findings=found, line="")

    async def says_hers(prompt, instruction):
        return '{"answers": [{"f": "F1", "is": "closes", "loop": %d, "why": "done"}]}' % hers
    await check.run_check(store, NOW, turn, lambda t, b: None, think=says_hers)
    assert ledger.get(store, hers)["state"] == "new"  # another owner's loop: never touched from Odie's watch
    [mine] = ledger.open_loops(store, "")
    assert "app 49; rm -rf ~" not in mine["refs"] and {"example/app#49", "example/app#7"} <= set(mine["refs"])
    assert store.one("select count(*) n from loops where title='made up'")["n"] == 0  # a mail this check never saw
