from datetime import datetime
from zoneinfo import ZoneInfo

from odie.agent.prompt import build_system_prompt, now_block

IST = ZoneInfo("Asia/Kolkata")


def test_now_block_names_days():
    b = now_block(datetime(2026, 9, 30, 9, 31, tzinfo=IST))
    assert "Wednesday 30 September 2026" in b and "09:31" in b
    assert "Tomorrow is Thursday 1 October" in b and "Saturday is 3 October" in b


def test_prompt_sections():
    p = build_system_prompt(datetime(2026, 9, 30, 9, 31, tzinfo=IST), ["Asha likes window seats"], "Open: 1 waiting.")
    assert p.startswith("You are Odie") and "UNTRUSTED EMAIL" in p
    assert "Things you know:\n- Asha likes window seats" in p and "Open: 1 waiting." in p
    assert len(p) < 6000


def test_prompt_without_memories():
    p = build_system_prompt(datetime(2026, 9, 30, 9, 31, tzinfo=IST), [], "")
    assert "Things you know" not in p


def test_memory_and_review_are_framed_as_notes_not_instructions():
    from odie.agent.prompt import Who, rules_text
    from odie.memory.review import SYSTEM as REVIEW
    rules = rules_text(Who(), gated=True).lower()
    assert "never instructions" in rules or "not instructions" in rules
    assert "instruction" in REVIEW.lower() and "never record" in REVIEW.lower()


def test_rules_handle_declined_actions_without_retry():
    from odie.agent.prompt import Who, rules_text
    rules = rules_text(Who(), gated=True).lower()
    assert "declined" in rules and "never retry" in rules


def test_the_memory_review_never_saves_what_the_assistant_can_or_cant_do():
    # "Its mail tools aren't available in chat" was one bad turn's guess; saved, it misled every chat after it.
    from odie.memory.review import SYSTEM
    assert "Never record what the assistant itself can or can't do" in SYSTEM
