from datetime import datetime
from zoneinfo import ZoneInfo

from odie.agent.prompt import build_static_prompt, build_turn_context

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 10, 1, 7, 45, tzinfo=IST)


def test_static_prompt_is_stable_across_minutes():
    a = build_static_prompt(NOW, soul=None, memory_index="## Identity\n- Asha", gated=False)
    b = build_static_prompt(NOW.replace(hour=22, minute=13), soul=None, memory_index="## Identity\n- Asha", gated=False)
    assert a == b and "Thursday 1 October 2026" in a and "07:45" not in a
    assert "## Identity" in a and a.startswith("You are Odie")


def test_soul_overrides_identity():
    p = build_static_prompt(NOW, soul="You are Odie, dry wit, short answers.", memory_index="", gated=False)
    assert p.startswith("You are Odie, dry wit") and "Rules:" in p


def test_turn_context_carries_volatile_bits():
    t = build_turn_context(NOW, prefetch="### Flight Seat Preference\nAisle.", ledger="Open threads: 1 waiting.")
    assert t.startswith("[context") and "07:45" in t and "Aisle." in t and "1 waiting" in t
    assert build_turn_context(NOW, prefetch="", ledger="") .count("\n") <= 2


def test_turn_context_lists_open_tasks_with_ids():
    t = build_turn_context(NOW, prefetch="", ledger="Open threads: 2 to do.", tasks="#1 [reminder] ICICI card ₹12,345 · due 2026-09-29\n#3 [reminder] Electricity · due 2026-10-12")
    assert "[open threads]" in t and "#1 [reminder] ICICI" in t and "[/open threads]" in t


def test_rules_route_done_through_task_update():
    from odie.agent.prompt import Who, rules_text
    low = rules_text(Who(), gated=True).lower()
    assert "task_update" in low and "paid" in low and "open threads" in low
