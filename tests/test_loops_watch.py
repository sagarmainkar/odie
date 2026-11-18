"""The watch's turn writes pull requests and issues as loops (proactive design §12, phase 1). The model recognises
them; code keeps one loop per thing: fourteen notification mails about one pull request are one loop."""
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
        """The worst case: the model opens a loop for every mail it sees."""
        mails = json.loads((await call(tools, "new_mail"))["result"])
        for m in mails:
            await call(tools, "loop", title="app #49 Threads newest first", kind="pull request",
                       refs=["example/app#49"], mail_id=m["id"])
        await call(tools, "report", needs_you=[], line="14 GitHub updates")
    assert await check.run_check(store, NOW, naive, lambda t, b: None) == "ok"
    loops = ledger.open_loops(store, "")
    assert len(loops) == 1
    assert loops[0]["playbook"] == "github-pr" and set(loops[0]["refs"]) == {"example/app#49", "thread:t49"}
    assert len(ledger.events(store, loops[0]["id"])) == 14
    assert store.get_setting(report.CARD)["needs_you"] == []  # no card per mail


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


async def test_the_loop_tool_checks_what_the_model_named(store, tmp_path):
    from odie.plugins import mcp
    from odie import personalities
    mcp.write_config({"home": spec_for("plain", tmp_path, mail=pr_mails(1))})
    mira = personalities.create(store, "Mira").id
    hers = ledger.open_loop(store, mira, NOW, "Mira's", "issue", refs=["example/app#7"])
    said = {}

    async def turn(prompt, tools, instruction):
        await call(tools, "new_mail")
        said["bad"] = (await call(tools, "loop", title="x", kind="pull request", refs=["app 49; rm -rf ~"]))["result"]
        said["unknown"] = (await call(tools, "loop", title="x", kind="issue", mail_id="nope"))["result"]
        said["hers"] = (await call(tools, "loop", title="x", kind="issue", loop_id=hers, close_why="done"))["result"]
        said["open"] = (await call(tools, "loop", title="app #49", kind="pull request", refs=["example/app#49"],
                                   mail_id="g0"))["result"]
        lid = int(said["open"].split("#")[1].split()[0])
        said["close"] = (await call(tools, "loop", title="app #49", kind="pull request", loop_id=lid,
                                    close_why="merged 18 Nov"))["result"]
        await call(tools, "report", needs_you=[], line="")
    await check.run_check(store, NOW, turn, lambda t, b: None)
    assert said["bad"].startswith("Not a GitHub name")
    assert "doesn't know mail" in said["unknown"]
    assert said["hers"] == f"No open loop #{hers}."  # another owner's loop: never touched from Odie's watch
    assert ledger.get(store, hers)["state"] == "new"
    assert said["open"].startswith("Opened loop #") and said["close"].startswith("Closed loop #")
