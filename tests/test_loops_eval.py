"""The loop eval's made-up cases, scored with a scripted model (deterministic): code's part — the same-ID shortcut,
checked refs, closes with evidence, cards — must get every case right even when the model is naive. The real model
runs the same cases with scripts/loops_eval.sh."""
import json
import re
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from odie.loops import eval as loops_eval
from odie.loops import ledger
from odie.store.db import Store

NOW = datetime(2026, 11, 18, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
NAME = re.compile(r"\[([\w.-]+/[\w.-]+)\].*\((?:PR|Issue) #(\d+)\)")


@pytest.fixture
def store(isolated_settings, tmp_path, monkeypatch):
    for name in ("ODIE_GH", "FAKE_GH_DATA", "FAKE_GH_LOG"):
        monkeypatch.delenv(name, raising=False)  # run_case sets them; monkeypatch puts them back after
        monkeypatch.setenv(name, "")
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


async def call(tools, name, **args):
    t = next(t for t in tools if t.name == name)
    return await t.run_async(args=args, tool_context=SimpleNamespace())


async def naive_turn(prompt, tools, instruction):
    """A naive model: one loop call per GitHub mail, never looking at open_loops."""
    for mail in json.loads((await call(tools, "new_mail"))["result"]):
        found = NAME.search(mail["subject"])
        if found is None:
            continue
        kind = "issue" if "(Issue" in mail["subject"] else "pull request"
        await call(tools, "loop", title=f"{found.group(1)} #{found.group(2)}", kind=kind,
                   refs=[f"{found.group(1)}#{found.group(2)}"], mail_id=mail["id"])
    await call(tools, "report", needs_you=[], line="")


async def sensible_think(prompt, instruction):
    """Picks as the playbook says, from the fenced facts."""
    fenced = prompt.split("Facts from GitHub just now:\n")[1]
    facts = json.loads(fenced[fenced.index("{"):fenced.rindex("}") + 1])
    if facts["state"] in ("merged", "closed"):
        return json.dumps({"choice": "drop", "why": facts["state"]})
    if facts["kind"] == "issue":
        if facts["assigned_to_you"]:
            return json.dumps({"choice": "ready", "why": "assigned to you", "brief": "A bug assigned to you."})
        return json.dumps({"choice": "drop", "why": "not assigned to you"})
    if facts.get("draft") or facts["checks"] == "running":
        return json.dumps({"choice": "wait", "why": "draft", "hours": 4})
    if facts["review_asked_of_you"] or (facts["yours"] and facts["checks"] == "red"):
        return json.dumps({"choice": "ready", "why": "for you", "brief": "Needs you."})
    return json.dumps({"choice": "wait", "why": "nothing asked of you", "hours": 6})


async def test_every_case_scores_right_with_a_naive_model(store, tmp_path):
    cases = loops_eval.load_cases()
    assert {c["id"] for c in cases} >= {"fourteen-mails-one-pr", "merged-pr-closes", "issue-not-yours", "two-prs-alike",
                                        "lone-merged-mail", "own-pr-ci-failing", "a-draft-waits", "issue-assigned-to-you",
                                        "done-pr-gets-mail"}
    results = []
    for case in cases:
        folder = tmp_path / case["id"]
        folder.mkdir()
        results.append(await loops_eval.run_case(store, case, NOW, naive_turn, sensible_think, folder))
    totals = loops_eval.totals(results)
    assert totals["wrong"] == [] and totals["right"] == totals["of"] > 0


def test_the_score_catches_a_loop_per_mail_and_a_missed_close(store):
    case = {"expect": {"loops": 1, "closed": ["example/app#50"], "no_card": ["example/app#7"]}}
    for _ in range(14):
        ledger.open_loop(store, "", NOW, "x", "pull request", refs=["example/app#50"])
    issue = ledger.open_loop(store, "", NOW, "y", "issue", refs=["example/app#7"])
    ledger.update(store, issue, NOW, state="ready")
    got = loops_eval.score(case, store)
    assert got["right"] == 0 and got["wrong"] == ["15 loops, wanted 1", "example/app#50 not closed with a reason",
                                                  "example/app#7 has a card it shouldn't"]
