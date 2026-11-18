"""Stage 4 for github-pr (proactive design §7, phase 1): the facts from GitHub (a fake gh here), then one call to the
model with no tools and the facts fenced, which picks drop, wait or ready. Code keeps it safe: a close cites
evidence, a wait has a next check, a card's facts line and link are written by code, and a muddle twice is a
"stuck" card. The clock picks due loops within the day's budget of model calls."""
import json
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from odie import personalities
from odie.loops import budget, choose, clock, ledger
from odie.store.db import Store
from odie.watch import owner as watch_owner
from odie.watch import pushes
from tests.test_loops_github import OPEN_PR, fake_gh  # noqa: F401 (the fixture)

NOW = datetime(2026, 11, 18, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


def a_pr_loop(store, number=49, pid="", priority="normal"):
    return ledger.open_loop(store, pid, NOW, f"app #{number} Threads newest first", "pull request",
                            refs=[f"example/app#{number}"], playbook="github-pr", priority=priority,
                            fact="Review requested")


def model_says(answer, seen=None):
    async def think(prompt, instruction):
        if seen is not None:
            seen.append((prompt, instruction))
        return answer
    return think


async def test_a_merged_pull_request_closes_with_evidence(store, fake_gh):
    fake_gh.data["pr:example/app#50"] = {**OPEN_PR, "number": 50, "state": "MERGED", "mergedAt": "2026-11-18T03:30:00Z"}
    fake_gh.save()
    lid = a_pr_loop(store, 50)
    seen = []
    got = await choose.choose(store, ledger.get(store, lid), NOW, model_says('{"choice": "drop", "why": "merged"}', seen))
    loop = ledger.get(store, lid)
    assert got == "drop" and loop["state"] == "closed" and loop["closed_why"] == "merged 18 Nov 09:00"
    prompt, instruction = seen[0]
    assert "<<<UNTRUSTED" in prompt and '"state": "merged"' in prompt  # the facts go in fenced
    assert "Answer with JSON only" in instruction  # the playbook's own words
    assert ledger.closed_since(store, "", NOW - timedelta(hours=1))[0]["id"] == lid  # Done today, with Reopen


async def test_a_draft_waits_an_hour(store, fake_gh):
    fake_gh.data["pr:example/app#51"] = {**OPEN_PR, "number": 51, "isDraft": True}
    fake_gh.save()
    lid = a_pr_loop(store, 51)
    got = await choose.choose(store, ledger.get(store, lid), NOW,
                              model_says('Thinking... {"choice": "wait", "why": "still a draft", "hours": 1}'))
    loop = ledger.get(store, lid)
    assert got == "wait" and loop["state"] == "waiting" and loop["has_news"] == 0
    assert loop["next_check_at"] == (NOW + timedelta(hours=1)).isoformat(timespec="seconds")


async def test_ready_makes_a_card_with_facts_written_by_code_and_maybe_a_push(store, fake_gh):
    fake_gh.data["pr:example/app#49"] = OPEN_PR
    fake_gh.save()
    lid = a_pr_loop(store, priority="high")
    sent = []
    answer = json.dumps({"choice": "ready", "why": "review requested", "brief": "Sorts threads newest first. Small and green.",
                         "link": "https://evil.example"})
    got = await choose.choose(store, ledger.get(store, lid), NOW, model_says(answer), push=lambda t, b: sent.append((t, b)))
    loop = ledger.get(store, lid)
    assert got == "ready" and loop["state"] == "ready"
    assert loop["result"] == "Open · CI green · 3 files, +41 −9"
    assert loop["link"] == "https://github.com/example/app/pull/49"  # built by code, never the model's
    assert loop["brief"].startswith("Sorts threads")
    assert sent == [("app #49 Threads newest first", "Open · CI green · 3 files, +41 −9")]
    assert pushes.sent_today(store, NOW) == 1  # counted in the shared budget


async def test_a_drop_without_evidence_or_reason_is_refused_and_twice_is_stuck(store, fake_gh):
    fake_gh.data["pr:example/app#49"] = OPEN_PR
    fake_gh.save()
    lid = a_pr_loop(store)
    assert await choose.choose(store, ledger.get(store, lid), NOW, model_says('{"choice": "drop"}')) == "wait"
    assert ledger.get(store, lid)["state"] == "waiting" and ledger.get(store, lid)["attempts"] == 1
    assert await choose.choose(store, ledger.get(store, lid), NOW, model_says("no idea")) == "stuck"
    loop = ledger.get(store, lid)
    assert loop["state"] == "ready" and loop["result"].startswith("I'm stuck")


async def test_gh_failing_waits_and_never_calls_the_model(store, fake_gh):
    lid = a_pr_loop(store, 404)

    async def think(prompt, instruction):
        raise AssertionError("no facts, no model call")
    assert await choose.choose(store, ledger.get(store, lid), NOW, think) == "wait"


async def test_the_clock_picks_due_loops_within_the_budget(store, fake_gh):
    fake_gh.data["pr:example/app#49"] = OPEN_PR
    fake_gh.save()
    mira = personalities.create(store, "Mira").id
    first = a_pr_loop(store)
    later = ledger.open_loop(store, "", NOW, "Not yet", "pull request", refs=["example/app#52"], playbook="github-pr")
    ledger.update(store, later, NOW, has_news=0, next_check_at=(NOW + timedelta(hours=2)).isoformat())
    hers = a_pr_loop(store, 49, pid=mira)
    no_book = ledger.open_loop(store, "", NOW, "A promise", "promise")
    assert [lp["id"] for lp in clock.due(store, NOW)] == [first]  # hers: Mira's switch is off; no_book: no playbook
    watch_owner.set_proactive(store, mira, True)
    assert [lp["id"] for lp in clock.due(store, NOW)] == [first, hers]
    assert no_book not in [lp["id"] for lp in clock.due(store, NOW)]

    asked_for = []

    def think_for(pid):
        asked_for.append(pid)
        return model_says('{"choice": "wait", "why": "later", "hours": 2}')
    store.set_setting(budget.KEY, {"day": NOW.date().isoformat(), "used": budget.CALLS_DAILY - 1})
    ran = await clock.run(store, NOW, think_for, lambda t, b: None)
    assert ran == [(first, "wait")]  # one call left today: the second loop waits for tomorrow
    assert asked_for == [""]
    assert budget.left(store, NOW) == 0


async def test_the_background_runs_due_loops_with_no_tools_on_the_owners_brain(store, fake_gh):
    from odie.app import main
    fake_gh.data["pr:example/app#49"] = OPEN_PR
    fake_gh.save()
    a_pr_loop(store)
    asked = []

    class Runner:
        async def background_turn(self, prompt, **kw):
            asked.append(kw)
            return '{"choice": "wait", "why": "CI running", "hours": 1}'
    part = next(p for p in main.background_for(store, Runner()).parts if p.name == "loops")
    assert part.due(NOW) is True
    assert await main.run_loops(store, Runner(), NOW) == [(1, "wait")]
    assert asked[0]["bare"] is True and asked[0]["owner"] == ""
