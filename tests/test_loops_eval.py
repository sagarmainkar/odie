"""The loop eval's made-up cases, scored with a scripted model (deterministic): code's part — the same-ID shortcut,
checked refs, the rails of stage 2 (Done remembered, a reminder only for a new loop), closes with evidence, cards —
must get every case right. For a pull request the scripted model is naive (a finding per GitHub mail, no answers in
stage 2); for anything else it writes what the case's script says, as a model would. The real model runs the same
cases, never seeing a script, with scripts/loops_eval.sh."""
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
    from odie.workers import router
    from tests.test_workers import Chat
    router.setup(s, Chat())
    yield s
    for task in list(router._tasks.values()):
        task.cancel()


async def call(tools, name, **args):
    t = next(t for t in tools if t.name == name)
    return await t.run_async(args=args, tool_context=SimpleNamespace())


async def naive_turn(prompt, tools, instruction, script=None):
    """A naive model: one finding per GitHub mail, never knowing what Odie follows; for anything else the case's
    script (the findings it should write, and any thread it should follow)."""
    found = []
    for mail in json.loads((await call(tools, "new_mail"))["result"]):
        hit = NAME.search(mail["subject"])
        if hit is None:
            continue
        kind = "issue" if "(Issue" in mail["subject"] else "pull request"
        found.append({"ref": f"mail:{mail['id']}", "title": f"{hit.group(1)} #{hit.group(2)}", "kind": kind,
                      "owner": "odie", "refs": [f"{hit.group(1)}#{hit.group(2)}"]})
    for args in (script or {}).get("threads", []):
        await call(tools, "track_thread", **args)
    found += (script or {}).get("findings", [])
    await call(tools, "report", findings=found, line="")


def loop_number(prompt: str, ref: str) -> int | None:
    """The number of the loop the prompt lists holding this ref: "#12 Vote … · refs event:uid-vote" -> 12."""
    for line in prompt.splitlines():
        found = re.match(r"#(\d+) ", line)
        if found and ref in line:
            return int(found.group(1))
    return None


async def sensible_think(prompt, instruction, script=None):
    """Stage 2: the case's scripted answers (none for a pull request: the shortcut and the rails place it). Stage 4:
    picks as the playbook says, from the fenced facts."""
    if prompt.startswith("Findings from this check:"):
        answers = []
        for answer in (script or {}).get("answers", []):  # a script names loops by a ref they hold
            answer = dict(answer)
            for key in ("loop_ref", "after_ref"):
                if key in answer:
                    answer[key.removesuffix("_ref")] = loop_number(prompt, answer.pop(key))
            answers.append(answer)
        return json.dumps({"answers": answers})
    fenced = prompt.split("Facts from GitHub just now:\n")[1]
    facts = json.loads(fenced.split("\n")[1])  # the line inside the fence
    if "Odie tested the head commit" in prompt:
        return json.dumps({"choice": "ready", "why": "tested", "brief": "Tests pass.", "review": "Small; fine."})
    if facts["state"] in ("merged", "closed"):
        return json.dumps({"choice": "drop", "why": facts["state"]})
    if facts["kind"] == "issue":
        if facts["assigned_to_you"]:
            return json.dumps({"choice": "ready", "why": "assigned to you", "brief": "A bug assigned to you."})
        return json.dumps({"choice": "drop", "why": "not assigned to you"})
    if facts.get("draft") or facts["checks"] == "running":
        return json.dumps({"choice": "wait", "why": "draft", "hours": 4})
    if facts["yours"] and facts["checks"] == "green":
        return json.dumps({"choice": "test", "why": "your PR, green", "brief": "Your change; CI green."})
    if facts["review_asked_of_you"] or (facts["yours"] and facts["checks"] == "red"):
        return json.dumps({"choice": "ready", "why": "for you", "brief": "Needs you."})
    return json.dumps({"choice": "wait", "why": "nothing asked of you", "hours": 6})


async def test_every_case_scores_right_with_a_naive_model(store, tmp_path):
    cases = loops_eval.load_cases()
    assert {c["id"] for c in cases} >= {"fourteen-mails-one-pr", "merged-pr-closes", "issue-not-yours", "two-prs-alike",
                                        "lone-merged-mail", "own-pr-ci-failing", "a-draft-waits", "issue-assigned-to-you",
                                        "done-pr-gets-mail", "own-pr-green-tested", "own-pr-lockfile",
                                        "someone-elses-pr", "own-pr-no-recipe",
                                        # phase 3: the whole watch in the ledger (the owner's five cases first)
                                        "vote-event-digest-event", "dismissed-event-stays-gone", "old-pr-card-and-loop",
                                        "reply-owed-no-due-date", "deck-by-friday-then-a-call", "reply-from-the-phone",
                                        "bill-then-paid", "order-shipped-then-delivered", "newsletter-is-nothing",
                                        "two-invoices-one-biller", "forward-leaves-reply-open", "personality-inbox"}
    assert len(cases) >= 30
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
