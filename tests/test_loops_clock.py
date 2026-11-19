"""The clock (proactive design §6): which loops are due, in what order, within the day's calls, and never twice at
once (the background runs one part at a time)."""
import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from odie.background import Background, Part
from odie.loops import budget, clock, ledger
from odie.store.db import Store

NOW = datetime(2026, 11, 18, 10, 0, tzinfo=ZoneInfo("Asia/Kolkata"))


@pytest.fixture
def store(isolated_settings, tmp_path):
    s = Store(tmp_path / "a.db")
    s.init_schema()
    return s


def loop(**fields):
    base = {"playbook": "github-pr", "hidden_until": None, "has_news": 0, "next_check_at": None}
    return {**base, **fields}


def test_is_due():
    assert clock.is_due(loop(has_news=1), NOW)
    assert clock.is_due(loop(next_check_at=(NOW - timedelta(hours=1)).isoformat()), NOW)
    assert not clock.is_due(loop(next_check_at=(NOW + timedelta(hours=2)).isoformat()), NOW)
    assert not clock.is_due(loop(has_news=1, hidden_until=(NOW + timedelta(hours=23)).isoformat()), NOW)
    assert not clock.is_due(loop(has_news=1, playbook=""), NOW)


def test_due_loops_come_by_due_date_then_priority(store):
    low = ledger.open_loop(store, "", NOW, "low", "pull request", priority="low", playbook="github-pr")
    high = ledger.open_loop(store, "", NOW, "high", "pull request", priority="high", playbook="github-pr")
    dated = ledger.open_loop(store, "", NOW, "dated", "pull request", playbook="github-pr",
                             due_at=(NOW + timedelta(days=1)).isoformat())
    assert [lp["id"] for lp in clock.due(store, NOW)] == [dated, high, low]


async def test_the_budget_stops_the_clock_and_nothing_is_lost(store):
    for n in range(3):
        ledger.open_loop(store, "", NOW, f"pr {n}", "pull request", refs=[f"example/app#{n + 1}"], playbook="github-pr")
    store.set_setting(budget.KEY, {"day": NOW.date().isoformat(), "used": budget.CALLS_DAILY})

    def think_for(pid):
        raise AssertionError("no calls left today")
    assert await clock.run(store, NOW, think_for, None) == []
    assert len(clock.due(store, NOW)) == 3  # still due tomorrow


async def test_the_loops_part_never_runs_twice_at_once():
    running, most = [0], [0]

    async def slow():
        running[0] += 1
        most[0] = max(most[0], running[0])
        await asyncio.sleep(0.05)
        running[0] -= 1
    bg = Background([Part("loops", slow)])
    await asyncio.gather(bg.tick(), bg.tick(), bg.tick())
    assert most[0] == 1
